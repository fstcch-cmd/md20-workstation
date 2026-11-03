"""Sequence → predicted 3D structure ("one-click folding", D-80; spec docs/specs/structure_prediction.md).

One interface over several predictors:

    fold(sequences, engine="auto", out_dir=...) -> FoldResult

`sequences` is one sequence (a peptide) or a list: receptor chain(s) first, the peptide last (`peptide_index=-1`).
Chains are named A, B, C ... in that order.

Engines (all run as external programs, so they may live in their own environment, see `setup_plan`):
  omegafold  single chain, no MSA, Apache-2.0           CLI `omegafold input.fasta outdir`
  esmfold    single chain, no MSA, MIT                   `esm-fold` CLI, or HF transformers EsmForProteinFolding
  boltz      single chain or complex (receptor+peptide)  CLI `boltz predict input.yaml` (Boltz-2, MIT)
  colabfold  single chain or complex, needs the MMseqs2 server (internet)   CLI `colabfold_batch`
  upload     a PDB or mmCIF file the user made with AlphaFold Server, ColabFold or any other tool

pLDDT is read from the B-factor column (0-100; files with 0-1 values are scaled and the note says so).  ipTM comes
from the engine's confidence JSON (Boltz, ColabFold, AlphaFold Server).

Rules (spec §4): mean pLDDT of the peptide ≥ 70 PASS, 50-70 AUTO_FIXED (low confidence, MD checks it), < 50
NEEDS_HUMAN; complex ipTM < 0.5 is an advisory.  A single peptide shorter than MIN_FOLD_RESIDUES is not folded.
Every failure raises FoldError with a four-language message; nothing falls back silently.
Predicted structures are always labelled "predicted" (`FoldResult.provenance`), never as experimental.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .gates import Gate, GateReport, PASS, AUTO_FIXED, NEEDS_HUMAN

AA1 = "ACDEFGHIKLMNPQRSTVWY"
THREE_TO_ONE = {"ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q", "GLU": "E", "GLY": "G",
                "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P", "SER": "S",
                "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
                # protonation / variant names some tools write
                "HID": "H", "HIE": "H", "HIP": "H", "HSD": "H", "HSE": "H", "HSP": "H", "CYX": "C", "CYM": "C",
                "ASH": "D", "GLH": "E", "LYN": "K", "MSE": "M"}
ONE_TO_THREE = {v: k for k, v in THREE_TO_ONE.items() if k in
                {"ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE", "LEU", "LYS", "MET", "PHE",
                 "PRO", "SER", "THR", "TRP", "TYR", "VAL"}}
SIDECHAIN = {"A": "CB", "R": "CB CG CD NE CZ NH1 NH2", "N": "CB CG OD1 ND2", "D": "CB CG OD1 OD2", "C": "CB SG",
             "Q": "CB CG CD OE1 NE2", "E": "CB CG CD OE1 OE2", "G": "", "H": "CB CG ND1 CD2 CE1 NE2",
             "I": "CB CG1 CG2 CD1", "L": "CB CG CD1 CD2", "K": "CB CG CD CE NZ", "M": "CB CG SD CE",
             "F": "CB CG CD1 CD2 CE1 CE2 CZ", "P": "CB CG CD", "S": "CB OG", "T": "CB OG1 CG2",
             "W": "CB CG CD1 CD2 NE1 CE2 CE3 CZ2 CZ3 CH2", "Y": "CB CG CD1 CD2 CE1 CE2 CZ OH", "V": "CB CG1 CG2"}
HEAVY_ATOMS = {aa: ["N", "CA", "C", "O"] + sc.split() for aa, sc in SIDECHAIN.items()}
NAME_SYNONYMS = {("I", "CD"): "CD1", ("*", "OT1"): "O", ("*", "OT2"): "OXT", ("*", "O1"): "O", ("*", "O2"): "OXT"}

MIN_FOLD_RESIDUES = 10
PLDDT_PASS, PLDDT_LOW, IPTM_MIN = 70.0, 50.0, 0.5
ENGINES = ("omegafold", "esmfold", "boltz", "colabfold", "upload")
COMPLEX_ENGINES = ("boltz", "colabfold", "upload")
# GPU memory (MB) below which "auto" does not pick the engine on the GPU (spec §2; first-hand laptop numbers pending)
MIN_VRAM_MB = {"omegafold": 4000, "esmfold": 8000, "boltz": 8000, "colabfold": 0}
DEFAULT_TIMEOUT_S = 4 * 3600

# --------------------------------------------------------------------------- four-language messages (zh, en, ja, ko)
M = {
    "bad_seq": ("序列 {name} 含非標準胺基酸字母 {bad}。只接受 20 種標準胺基酸的單字母碼。",
                "Sequence {name} contains non-standard letters {bad}. Only the 20 standard one-letter amino acid codes are accepted.",
                "配列 {name} に標準でない文字 {bad} があります。20 種類の標準アミノ酸の 1 文字表記だけを使えます。",
                "서열 {name}에 비표준 문자 {bad}가 있습니다. 20가지 표준 아미노산 한 글자 코드만 사용할 수 있습니다."),
    "too_short": ("序列 {name} 太短（{n} 個殘基）。至少需要 2 個殘基。",
                  "Sequence {name} is too short ({n} residues). At least 2 residues are needed.",
                  "配列 {name} が短すぎます（{n} 残基）。2 残基以上が必要です。",
                  "서열 {name}이(가) 너무 짧습니다({n}개 잔기). 잔기가 2개 이상 필요합니다."),
    "short": ("胜肽只有 {n} 個殘基，少於 {min} 個。這麼短的胜肽單獨存在時通常沒有穩定結構，所以不摺疊。"
              "改用既有的延伸構形，由對接在搜尋時改變它的構形。報告會說明這一點。",
              "The peptide has {n} residues, fewer than {min}. A peptide this short usually has no stable structure on its own, "
              "so it is not folded. The existing extended build is used and docking changes its conformation during the search. "
              "The report states this.",
              "ペプチドは {n} 残基で、{min} 残基より短いです。この長さのペプチドは単独では安定な構造をとらないことが多いため、"
              "フォールディングしません。従来の伸びた構造を使い、ドッキングの探索で立体配座を変えます。レポートにこのことを記載します。",
              "펩타이드 잔기가 {n}개로 {min}개보다 적습니다. 이렇게 짧은 펩타이드는 단독으로는 안정된 구조가 없는 경우가 많아 "
              "폴딩하지 않습니다. 기존의 펼쳐진 구조를 사용하고 도킹 탐색 중에 형태가 바뀝니다. 보고서에 이 내용을 적습니다."),
    "no_engine": ("這台電腦沒有可用的結構預測工具。可以在電腦狀態頁按「一鍵安裝」（或執行 md20 setup-fold --engine omegafold --yes），或到 AlphaFold Server 或 ColabFold 預測後上傳結構檔。",
                  "No structure prediction tool is available on this computer. Press Install now on the computer status page (or run md20 setup-fold --engine omegafold --yes), "
                  "or predict the structure on AlphaFold Server or ColabFold and upload the file.",
                  "このコンピュータで使える構造予測ツールがありません。パソコンの状態のページで「今すぐインストール」を押す（または md20 setup-fold --engine omegafold --yes を実行する）か、"
                  "AlphaFold Server または ColabFold で予測して構造ファイルをアップロードしてください。",
                  "이 컴퓨터에서 사용할 수 있는 구조 예측 도구가 없습니다. 컴퓨터 상태 페이지에서 '지금 설치'를 누르거나(또는 md20 setup-fold --engine omegafold --yes 실행) "
                  "AlphaFold Server 또는 ColabFold에서 예측한 후 구조 파일을 업로드하십시오."),
    "no_engine_complex": ("受體加胜肽的複合物需要 Boltz-2（顯示卡記憶體至少 {need} GB，這台偵測到 {have}）或 ColabFold。"
                          "也可以到 AlphaFold Server 預測後上傳結果。",
                          "A receptor and peptide complex needs Boltz-2 (at least {need} GB of GPU memory, this computer has {have}) "
                          "or ColabFold. You can also predict it on AlphaFold Server and upload the result.",
                          "受容体とペプチドの複合体には Boltz-2（GPU メモリ {need} GB 以上、このコンピュータは {have}）か ColabFold が必要です。"
                          "AlphaFold Server で予測した結果をアップロードすることもできます。",
                          "수용체와 펩타이드 복합체에는 Boltz-2(GPU 메모리 {need} GB 이상, 이 컴퓨터는 {have}) 또는 ColabFold가 필요합니다. "
                          "AlphaFold Server에서 예측한 결과를 업로드할 수도 있습니다."),
    "engine_missing": ("指定的工具 {engine} 沒有安裝。請執行 md20 setup-fold --engine {engine}。",
                       "The selected tool {engine} is not installed. Run md20 setup-fold --engine {engine}.",
                       "指定したツール {engine} がインストールされていません。md20 setup-fold --engine {engine} を実行してください。",
                       "선택한 도구 {engine}이(가) 설치되어 있지 않습니다. md20 setup-fold --engine {engine}을 실행하십시오."),
    "single_only": ("{engine} 只能預測單一條鏈。受體加胜肽的複合物請用 boltz、colabfold 或上傳結構。",
                    "{engine} predicts a single chain only. For a receptor and peptide complex use boltz, colabfold or upload a structure.",
                    "{engine} は 1 本の鎖しか予測できません。受容体とペプチドの複合体には boltz か colabfold を使うか、構造をアップロードしてください。",
                    "{engine}은(는) 사슬 하나만 예측합니다. 수용체와 펩타이드 복합체는 boltz, colabfold를 사용하거나 구조를 업로드하십시오."),
    "unknown_engine": ("不認得的摺疊工具 {engine}。可用的有 {choices}。",
                       "Unknown folding tool {engine}. Available: {choices}.",
                       "不明なフォールディングツール {engine} です。使えるのは {choices} です。",
                       "알 수 없는 폴딩 도구 {engine}입니다. 사용 가능: {choices}."),
    "failed": ("{engine} 執行失敗（結束碼 {rc}）。紀錄檔在 {log}。",
               "{engine} failed (exit code {rc}). The log is at {log}.",
               "{engine} の実行に失敗しました（終了コード {rc}）。ログは {log} にあります。",
               "{engine} 실행에 실패했습니다(종료 코드 {rc}). 로그 위치: {log}."),
    "timeout": ("{engine} 超過 {minutes} 分鐘沒有完成，已停止。紀錄檔在 {log}。",
                "{engine} did not finish within {minutes} minutes and was stopped. The log is at {log}.",
                "{engine} が {minutes} 分以内に終わらなかったため停止しました。ログは {log} にあります。",
                "{engine}이(가) {minutes}분 안에 끝나지 않아 중지했습니다. 로그 위치: {log}."),
    "no_output": ("{engine} 執行結束，但在 {where} 找不到輸出的結構檔。",
                  "{engine} finished, but no output structure was found in {where}.",
                  "{engine} は終了しましたが、{where} に出力構造ファイルがありません。",
                  "{engine}이(가) 끝났지만 {where}에서 출력 구조 파일을 찾을 수 없습니다."),
    "upload_missing": ("找不到上傳的結構檔 {path}。",
                       "The uploaded structure file {path} was not found.",
                       "アップロードした構造ファイル {path} が見つかりません。",
                       "업로드한 구조 파일 {path}을(를) 찾을 수 없습니다."),
    "upload_format": ("上傳的檔案 {path} 不是 PDB 或 mmCIF，或裡面沒有原子座標。",
                      "The uploaded file {path} is not PDB or mmCIF, or it has no atom coordinates.",
                      "アップロードしたファイル {path} は PDB でも mmCIF でもないか、原子座標がありません。",
                      "업로드한 파일 {path}은(는) PDB나 mmCIF가 아니거나 원자 좌표가 없습니다."),
    "seq_mismatch": ("結構檔裡沒有序列為 {seq} 的鏈。檔案裡的鏈是 {chains}。",
                     "The structure file has no chain with the sequence {seq}. Chains in the file: {chains}.",
                     "構造ファイルに配列 {seq} の鎖がありません。ファイル内の鎖は {chains} です。",
                     "구조 파일에 서열 {seq}인 사슬이 없습니다. 파일 안의 사슬: {chains}."),
    "atoms_missing": ("預測結構第 {i} 個殘基 {res} 缺少原子 {atoms}，無法對應到序列模板。",
                      "Residue {i} ({res}) of the predicted structure lacks atoms {atoms}, so it cannot be mapped to the sequence template.",
                      "予測構造の {i} 番目の残基 {res} に原子 {atoms} がないため、配列テンプレートに対応づけられません。",
                      "예측 구조의 {i}번째 잔기 {res}에 원자 {atoms}이(가) 없어 서열 템플릿에 대응시킬 수 없습니다."),
    "plddt_pass": ("平均 pLDDT {v:.1f}，達到 70，預測可信度高。這仍是預測，不是實驗結構。",
                   "Mean pLDDT {v:.1f}, at least 70. The prediction has high confidence. It is still a prediction, not an experimental structure.",
                   "平均 pLDDT は {v:.1f} で 70 以上です。予測の信頼度は高いです。これは予測であり、実験構造ではありません。",
                   "평균 pLDDT {v:.1f}로 70 이상입니다. 예측 신뢰도가 높습니다. 그래도 예측이며 실험 구조가 아닙니다."),
    "plddt_low": ("平均 pLDDT {v:.1f}，介於 50 和 70 之間，可信度偏低。仍用這個結構當起始構形，MD 會檢查它是否穩定。報告會標註為低可信度的預測。",
                  "Mean pLDDT {v:.1f}, between 50 and 70. Confidence is low. The structure is still used as the starting conformation "
                  "and MD checks whether it stays stable. The report labels it as a low-confidence prediction.",
                  "平均 pLDDT は {v:.1f} で 50 から 70 の間です。信頼度は低めです。この構造を初期構造として使い、"
                  "MD で安定かどうかを確かめます。レポートには信頼度の低い予測と記載します。",
                  "평균 pLDDT {v:.1f}로 50과 70 사이입니다. 신뢰도가 낮습니다. 이 구조를 시작 구조로 사용하고 "
                  "MD로 안정한지 확인합니다. 보고서에 신뢰도가 낮은 예측으로 표시합니다."),
    "plddt_bad": ("平均 pLDDT {v:.1f}，低於 50，這個預測不可信，胜肽可能沒有固定結構。請選擇下一步。",
                  "Mean pLDDT {v:.1f}, below 50. The prediction is not reliable and the peptide may have no fixed structure. Choose the next step.",
                  "平均 pLDDT は {v:.1f} で 50 未満です。この予測は信頼できず、ペプチドに決まった構造がない可能性があります。次の手順を選んでください。",
                  "평균 pLDDT {v:.1f}로 50 미만입니다. 이 예측은 신뢰할 수 없고 펩타이드에 고정된 구조가 없을 수 있습니다. 다음 단계를 선택하십시오."),
    "plddt_accepted": ("平均 pLDDT {v:.1f}，低於 50。使用者選擇仍使用這個預測結構，報告會標註。",
                       "Mean pLDDT {v:.1f}, below 50. The user chose to use this predicted structure anyway. The report labels it.",
                       "平均 pLDDT は {v:.1f} で 50 未満です。利用者がこの予測構造を使うことを選びました。レポートに記載します。",
                       "평균 pLDDT {v:.1f}로 50 미만입니다. 사용자가 이 예측 구조를 그래도 사용하기로 했습니다. 보고서에 표시합니다."),
    "iptm_low": ("ipTM {v:.2f}，低於 0.5，預測的結合介面不可信。請用 MD 與對接結果交叉檢查。",
                 "ipTM {v:.2f}, below 0.5. The predicted interface is not reliable. Cross-check it with MD and docking.",
                 "ipTM は {v:.2f} で 0.5 未満です。予測された結合界面は信頼できません。MD とドッキングの結果で確かめてください。",
                 "ipTM {v:.2f}로 0.5 미만입니다. 예측된 결합 계면은 신뢰할 수 없습니다. MD와 도킹 결과로 교차 확인하십시오."),
    "iptm_ok": ("ipTM {v:.2f}，達到 0.5。介面仍是預測，請以 MD 確認。",
                "ipTM {v:.2f}, at least 0.5. The interface is still a prediction. Confirm it with MD.",
                "ipTM は {v:.2f} で 0.5 以上です。界面は予測なので MD で確かめてください。",
                "ipTM {v:.2f}로 0.5 이상입니다. 계면은 예측이므로 MD로 확인하십시오."),
    "msa_empty": ("Boltz 以單序列模式執行（沒有 MSA，序列不會送到外部伺服器）。受體的準確度會比有 MSA 時低。",
                  "Boltz ran in single-sequence mode (no MSA, the sequences are not sent to an outside server). "
                  "Receptor accuracy is lower than with an MSA.",
                  "Boltz を単一配列モードで実行しました（MSA なし、配列は外部サーバーに送られません）。受容体の精度は MSA ありより下がります。",
                  "Boltz를 단일 서열 모드로 실행했습니다(MSA 없음, 서열을 외부 서버로 보내지 않음). 수용체 정확도는 MSA가 있을 때보다 낮습니다."),
    "msa_server": ("已把序列送到 MMseqs2 公開伺服器建立 MSA。未發表的序列請考慮這一點。",
                   "The sequences were sent to the public MMseqs2 server to build the MSA. Keep this in mind for unpublished sequences.",
                   "MSA を作るために配列を MMseqs2 の公開サーバーへ送りました。未発表の配列ではこの点に注意してください。",
                   "MSA를 만들기 위해 서열을 MMseqs2 공개 서버로 보냈습니다. 미발표 서열이라면 이 점을 고려하십시오."),
    "scaled": ("檔案的 B 因子在 0 到 1 之間，已乘以 100 當作 pLDDT。",
               "The B-factors in the file are between 0 and 1. They were multiplied by 100 to give pLDDT.",
               "ファイルの B 因子は 0 から 1 の間なので、100 倍して pLDDT としました。",
               "파일의 B 인자가 0과 1 사이이므로 100을 곱해 pLDDT로 사용했습니다."),
    "oxt": ("預測結構沒有 C 端的 OXT 原子，已依 C、O、CA 的幾何位置補上。",
            "The predicted structure has no C-terminal OXT atom. It was placed from the C, O and CA geometry.",
            "予測構造に C 末端の OXT 原子がないため、C、O、CA の配置から補いました。",
            "예측 구조에 C 말단 OXT 원자가 없어 C, O, CA의 기하 배치로 추가했습니다."),
    "renamed": ("原子名稱 {old} 視為 {new}（同一個原子的另一種寫法）。",
                "Atom name {old} was read as {new} (another name for the same atom).",
                "原子名 {old} を {new}（同じ原子の別表記）として読みました。",
                "원자 이름 {old}을(를) {new}(같은 원자의 다른 표기)로 읽었습니다."),
    "big_complex": ("複合物共 {n} 個殘基，顯示卡記憶體 {have}。Boltz 可能記憶體不足，失敗時請改用上傳結構。",
                    "The complex has {n} residues and the GPU has {have}. Boltz may run out of memory. If it fails, upload a structure instead.",
                    "複合体は全部で {n} 残基、GPU メモリは {have} です。Boltz はメモリ不足になるかもしれません。失敗したら構造をアップロードしてください。",
                    "복합체는 모두 {n}개 잔기이고 GPU 메모리는 {have}입니다. Boltz가 메모리 부족으로 실패할 수 있습니다. 실패하면 구조를 업로드하십시오."),
    "cpu": ("沒有偵測到可用的 NVIDIA 顯示卡，{engine} 改用 CPU 執行，會比較慢。",
            "No usable NVIDIA GPU was found, so {engine} runs on the CPU. It is slower.",
            "使える NVIDIA GPU が見つからないため、{engine} を CPU で実行します。時間がかかります。",
            "사용할 수 있는 NVIDIA GPU가 없어 {engine}을(를) CPU로 실행합니다. 더 느립니다."),
    "predicted": ("預測結構（{engine}），不是實驗結構。",
                  "Predicted structure ({engine}), not an experimental structure.",
                  "予測構造（{engine}）であり、実験構造ではありません。",
                  "예측 구조({engine})이며 실험 구조가 아닙니다."),
    "sup_pass": ("預測的受體疊合到實際受體，{n} 個 Cα 的 RMSD {rmsd:.2f} Å（不超過 {max:.1f} Å）。只取預測的胜肽姿勢放進實際受體。",
                 "The predicted receptor was superposed onto the actual receptor. RMSD over {n} Cα atoms is {rmsd:.2f} Å "
                 "(at most {max:.1f} Å). Only the predicted peptide pose is placed into the actual receptor.",
                 "予測した受容体を実際の受容体に重ね合わせました。{n} 個の Cα の RMSD は {rmsd:.2f} Å（{max:.1f} Å 以下）です。"
                 "予測したペプチドのポーズだけを実際の受容体に入れます。",
                 "예측한 수용체를 실제 수용체에 겹쳤습니다. Cα {n}개의 RMSD는 {rmsd:.2f} Å({max:.1f} Å 이하)입니다. "
                 "예측한 펩타이드 포즈만 실제 수용체에 넣습니다."),
    "sup_high": ("預測的受體與實際受體差異大，{n} 個 Cα 的 RMSD {rmsd:.2f} Å（超過 {max:.1f} Å）。疊合後的胜肽姿勢可能不在正確位置。請選擇下一步。",
                 "The predicted receptor differs from the actual receptor. RMSD over {n} Cα atoms is {rmsd:.2f} Å (more than {max:.1f} Å). "
                 "The superposed peptide pose may be in the wrong place. Choose the next step.",
                 "予測した受容体と実際の受容体の差が大きく、{n} 個の Cα の RMSD は {rmsd:.2f} Å（{max:.1f} Å 超）です。"
                 "重ね合わせたペプチドのポーズは正しい位置にないかもしれません。次の手順を選んでください。",
                 "예측한 수용체와 실제 수용체의 차이가 큽니다. Cα {n}개의 RMSD는 {rmsd:.2f} Å({max:.1f} Å 초과)입니다. "
                 "겹친 펩타이드 포즈가 올바른 위치에 있지 않을 수 있습니다. 다음 단계를 선택하십시오."),
    "sup_accepted": ("Cα RMSD {rmsd:.2f} Å，超過 {max:.1f} Å。使用者選擇仍使用這個胜肽姿勢，報告會標註。",
                     "Cα RMSD {rmsd:.2f} Å, more than {max:.1f} Å. The user chose to use this peptide pose anyway. The report labels it.",
                     "Cα RMSD は {rmsd:.2f} Å で {max:.1f} Å を超えています。利用者がこのペプチドのポーズを使うことを選びました。レポートに記載します。",
                     "Cα RMSD {rmsd:.2f} Å로 {max:.1f} Å를 넘습니다. 사용자가 이 펩타이드 포즈를 그래도 사용하기로 했습니다. 보고서에 표시합니다."),
    "sup_few": ("預測的受體只有 {n} 個 Cα 能和實際受體序列對上（至少要 {min} 個），無法可靠疊合。",
                "Only {n} Cα atoms of the predicted receptor match the actual receptor sequence (at least {min} are needed), "
                "so it cannot be superposed reliably.",
                "予測した受容体で実際の受容体の配列と対応する Cα は {n} 個だけです（{min} 個以上が必要）。確かな重ね合わせができません。",
                "예측한 수용체에서 실제 수용체 서열과 맞는 Cα가 {n}개뿐입니다(최소 {min}개 필요). 신뢰할 수 있게 겹칠 수 없습니다."),
    "sup_predicted": ("沒有實際的受體結構，直接使用預測的受體加胜肽複合物。受體也是預測結構，報告會標註。",
                      "There is no actual receptor structure, so the predicted receptor and peptide complex is used as is. "
                      "The receptor is also a predicted structure and the report labels it.",
                      "実際の受容体構造がないため、予測した受容体とペプチドの複合体をそのまま使います。受容体も予測構造であり、レポートに記載します。",
                      "실제 수용체 구조가 없어 예측한 수용체와 펩타이드 복합체를 그대로 사용합니다. 수용체도 예측 구조이며 보고서에 표시합니다."),
    "contact": ("放進實際受體後，胜肽與受體最近的重原子距離 {d:.2f} Å。建模時的能量最小化會先處理，MD 會檢查。",
                "After placement in the actual receptor, the closest peptide and receptor heavy atoms are {d:.2f} Å apart. "
                "Energy minimisation in the build handles this first and MD checks it.",
                "実際の受容体に入れたあと、ペプチドと受容体の最も近い重原子間距離は {d:.2f} Å です。"
                "モデル作成時のエネルギー最小化で先に処理し、MD で確かめます。",
                "실제 수용체에 넣은 뒤 펩타이드와 수용체의 가장 가까운 무거운 원자 거리는 {d:.2f} Å입니다. "
                "모델 생성 시 에너지 최소화로 먼저 처리하고 MD로 확인합니다."),
    "chain_break": ("受體 chain {chain} 的結構有缺口（{n} 處），由結構取得的序列會把缺口兩端接起來預測。可用 fold_receptor_seq 提供完整序列。",
                    "Receptor chain {chain} has {n} gaps in the structure. The sequence taken from the structure joins the ends of each gap "
                    "in the prediction. Give the full sequence with fold_receptor_seq.",
                    "受容体の鎖 {chain} の構造に欠損が {n} か所あります。構造から取った配列では欠損の両端をつないで予測します。"
                    "fold_receptor_seq で完全な配列を指定できます。",
                    "수용체 사슬 {chain} 구조에 결손이 {n}곳 있습니다. 구조에서 얻은 서열은 결손 양 끝을 이어서 예측합니다. "
                    "fold_receptor_seq로 전체 서열을 줄 수 있습니다."),
}

# option keys (Chinese text is the key stored in config and DecisionLog; md20/gui/gate_text.py translates them)
OPT_NO_FOLD = "不使用預測結構，改用延伸構形（fold: false）"
OPT_OTHER_ENGINE = "改用其他摺疊工具（fold_engine）"
OPT_UPLOAD = "上傳預測結構（fold_upload）"
OPT_ACCEPT_LOW = "仍使用這個預測結構（fold_accept_low: true）"
OPT_INSTALL = "安裝摺疊工具（md20 setup-fold）"
OPT_ACCEPT_RMSD = "仍使用這個胜肽姿勢（fold_accept_rmsd: true）"
OPT_DOCK = "改用對接（fold: true）"
OPT_RECEPTOR_SEQ = "提供完整受體序列（fold_receptor_seq）"
SUP_MAX_RMSD = 2.0             # Å, Cα after superposition (coordinator decision 2026-11-03)
SUP_MIN_MATCHED = 20           # matched Cα needed for a superposition


def msg(key: str, **kw) -> dict:
    """{"zh", "en", "ja", "ko"} for a message key, with the placeholders filled (works with md20.i18n.pick)."""
    return {lang: text.format(**kw) for lang, text in zip(("zh", "en", "ja", "ko"), M[key])}


class FoldError(RuntimeError):
    """A folding step failed.  `.text` holds the four-language message, `str()` is the Chinese one (command line)."""

    def __init__(self, key: str, *, options: list[str] | None = None, **kw):
        self.key, self.kw = key, kw
        self.text = msg(key, **kw)
        self.options = list(options or [])
        super().__init__(self.text["zh"])

    def pick(self, lang: str = "en") -> str:
        from ..i18n import pick
        return pick(self.text, lang)


class FoldUnavailable(FoldError):
    """No engine can run this job here (not installed, or not enough GPU memory)."""


# --------------------------------------------------------------------------- result
@dataclass
class FoldResult:
    engine: str
    sequences: list[str]
    chains: list[str]
    peptide_chain: str
    peptide_sequence: str = ""
    pdb_path: str = ""                       # always PDB (mmCIF input is converted)
    source_path: str = ""                    # the engine's own output or the uploaded file
    per_residue_plddt: list[float] = field(default_factory=list)          # peptide chain
    plddt_by_chain: dict = field(default_factory=dict)
    mean_plddt: float | None = None          # peptide chain (the gated value)
    complex_plddt: float | None = None
    iptm: float | None = None
    runtime_s: float = 0.0
    device: str = ""
    status: str = ""                         # PASS / AUTO_FIXED / NEEDS_HUMAN after fold_gates; SKIPPED_SHORT
    gates: dict = field(default_factory=dict)
    notes: list[dict] = field(default_factory=list)                       # four-language dicts
    provenance: str = "predicted"
    log_path: str = ""

    @property
    def is_complex(self) -> bool:
        return len(self.sequences) > 1

    def to_dict(self) -> dict:
        d = asdict(self)
        d["is_complex"] = self.is_complex
        return d


# --------------------------------------------------------------------------- sequences
def clean(seq: str, name: str = "") -> str:
    s = re.sub(r"[\s\-*]+", "", str(seq).upper())
    bad = sorted(set(s) - set(AA1))
    if bad:
        raise FoldError("bad_seq", name=name or "", bad="".join(bad))
    if len(s) < 2:
        raise FoldError("too_short", name=name or "", n=len(s))
    return s


def chain_ids(n: int) -> list[str]:
    return [chr(ord("A") + i) for i in range(n)]


# --------------------------------------------------------------------------- structure files (pure Python)
def parse_pdb(text: str) -> list[dict]:
    """ATOM/HETATM records of the first model."""
    atoms = []
    for line in text.splitlines():
        rec = line[:6]
        if rec.startswith("ENDMDL") and atoms:
            break
        if rec not in ("ATOM  ", "HETATM") or len(line) < 54:
            continue
        try:
            b = float(line[60:66]) if len(line) >= 66 and line[60:66].strip() else 0.0
            atoms.append({"hetero": rec == "HETATM", "name": line[12:16].strip(), "altloc": line[16].strip(),
                          "resname": line[17:20].strip(), "chain": line[21].strip() or "A",
                          "resseq": int(line[22:26]), "icode": line[26].strip() if len(line) > 26 else "",
                          "x": float(line[30:38]), "y": float(line[38:46]), "z": float(line[46:54]), "b": b,
                          "element": (line[76:78].strip() if len(line) >= 78 else "") or re.sub(r"[^A-Z]", "", line[12:16])[:1]})
        except ValueError:
            continue
    return atoms


_CIF_TOKEN = re.compile(r"'(?:[^']|'(?=\S))*'|\"[^\"]*\"|\S+")


def parse_mmcif(text: str) -> list[dict]:
    """`_atom_site` loop of an mmCIF file (first model).  Author chain and residue numbers when present."""
    lines = text.splitlines()
    i, n = 0, len(lines)
    while i < n:
        if lines[i].strip() == "loop_" and i + 1 < n and lines[i + 1].strip().startswith("_atom_site."):
            break
        i += 1
    else:
        return []
    i += 1
    keys = []
    while i < n and lines[i].strip().startswith("_atom_site."):
        keys.append(lines[i].strip().split(".", 1)[1].split()[0])
        i += 1
    col = {k: j for j, k in enumerate(keys)}

    def get(row, *names, default=""):
        for nm in names:
            if nm in col and col[nm] < len(row) and row[col[nm]] not in ("?", "."):
                return row[col[nm]]
        return default

    atoms, model0 = [], None
    while i < n:
        s = lines[i].strip()
        i += 1
        if not s or s.startswith("#"):
            if atoms:
                break
            continue
        if s.startswith("_") or s == "loop_":
            break
        row = [t[1:-1] if t[:1] in "'\"" and t[-1:] == t[:1] and len(t) > 1 else t for t in _CIF_TOKEN.findall(s)]
        model = get(row, "pdbx_PDB_model_num", default="1")
        model0 = model0 or model
        if model != model0:
            break
        try:
            atoms.append({"hetero": get(row, "group_PDB") == "HETATM", "name": get(row, "auth_atom_id", "label_atom_id"),
                          "altloc": get(row, "label_alt_id"), "resname": get(row, "auth_comp_id", "label_comp_id"),
                          "chain": get(row, "auth_asym_id", "label_asym_id", default="A"),
                          "resseq": int(get(row, "auth_seq_id", "label_seq_id", default="0")),
                          "icode": get(row, "pdbx_PDB_ins_code"),
                          "x": float(get(row, "Cartn_x")), "y": float(get(row, "Cartn_y")), "z": float(get(row, "Cartn_z")),
                          "b": float(get(row, "B_iso_or_equiv", default="0") or 0), "element": get(row, "type_symbol")})
        except ValueError:
            continue
    return atoms


def read_structure(path: Path | str) -> list[dict]:
    p = Path(path)
    if not p.is_file():
        raise FoldError("upload_missing", path=str(p))
    text = p.read_text(encoding="utf-8", errors="replace")
    atoms = parse_mmcif(text) if (p.suffix.lower() in (".cif", ".mmcif") or "_atom_site." in text[:200000]) else parse_pdb(text)
    atoms = [a for a in atoms if a["altloc"] in ("", "A", "1")]
    if not atoms:
        raise FoldError("upload_format", path=str(p))
    return atoms


def residues(atoms: list[dict]) -> dict[str, list[dict]]:
    """chain → ordered residues [{"resname", "resseq", "icode", "one", "atoms": {name: atom}}] (polymer residues only)."""
    out: dict[str, list[dict]] = {}
    index: dict[tuple, dict] = {}
    for a in atoms:
        if a["resname"] not in THREE_TO_ONE or (a.get("element") or "").upper() in ("H", "D"):
            continue
        key = (a["chain"], a["resseq"], a["icode"])
        r = index.get(key)
        if r is None:
            r = index[key] = {"resname": a["resname"], "resseq": a["resseq"], "icode": a["icode"],
                              "one": THREE_TO_ONE[a["resname"]], "atoms": {}}
            out.setdefault(a["chain"], []).append(r)
        r["atoms"].setdefault(a["name"], a)
    return out


def chain_sequences(res: dict[str, list[dict]]) -> dict[str, str]:
    return {c: "".join(r["one"] for r in rs) for c, rs in res.items()}


def residue_plddt(res_list: list[dict]) -> list[float]:
    """Per-residue value: B-factor of CA, or the residue mean when CA is missing."""
    out = []
    for r in res_list:
        ca = r["atoms"].get("CA")
        out.append(float(ca["b"]) if ca else sum(a["b"] for a in r["atoms"].values()) / max(1, len(r["atoms"])))
    return out


def _mean(v: list[float]) -> float | None:
    return round(sum(v) / len(v), 2) if v else None


def find_chain(res: dict[str, list[dict]], seq: str, prefer: str | None = None) -> str:
    seqs = chain_sequences(res)
    if prefer and seqs.get(prefer) == seq:
        return prefer
    hits = [c for c, s in seqs.items() if s == seq]
    if not hits:
        raise FoldError("seq_mismatch", seq=seq, chains=", ".join(f"{c}:{s[:30]}{'…' if len(s) > 30 else ''}" for c, s in seqs.items()) or "-")
    return hits[0]


def write_pdb(res: dict[str, list[dict]], path: Path | str, *, remark: str = "") -> Path:
    """PDB of the polymer residues (heavy atoms, B-factor = pLDDT on 0-100), one TER per chain, ASCII only."""
    lines = []
    if remark:
        lines.append(("REMARK   1 " + remark.encode("ascii", "replace").decode("ascii"))[:80])
    k = 0
    for c, rs in res.items():
        for r in rs:
            for nm, a in r["atoms"].items():
                k += 1
                el = (a.get("element") or nm[:1]).upper()[:2]
                name = f" {nm:<3s}" if len(nm) < 4 and len(el) == 1 else f"{nm:<4s}"
                lines.append(f"ATOM  {k % 100000:5d} {name}{a.get('altloc', '')[:1] or ' '}{r['resname']:>3s} {c[:1]}"
                             f"{r['resseq'] % 10000:4d}{(r['icode'] or ' ')[:1]}   {a['x']:8.3f}{a['y']:8.3f}{a['z']:8.3f}"
                             f"  1.00{a['b']:6.2f}          {el:>2s}")
        lines.append("TER")
    lines.append("END")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="ascii")
    return p


def peptide_heavy_coords(res_list: list[dict], seq: str) -> tuple[list[dict[str, tuple]], list[dict]]:
    """Per residue {standard atom name: (x, y, z)} for every heavy atom of the sequence template, plus notes.

    Known synonyms (Ile CD → CD1, OT1/OT2 → O/OXT) are renamed and noted; a missing C-terminal OXT is placed in the
    C-O-CA plane (1.25 Å, 120° from O).  Any other missing atom raises FoldError: the structure is not guessed."""
    if "".join(r["one"] for r in res_list) != seq:
        raise FoldError("seq_mismatch", seq=seq, chains="".join(r["one"] for r in res_list))
    out, notes, renamed = [], [], set()
    for i, (r, aa) in enumerate(zip(res_list, seq), 1):
        have = {}
        for nm, a in r["atoms"].items():
            std = NAME_SYNONYMS.get((aa, nm)) or NAME_SYNONYMS.get(("*", nm)) or nm
            if std != nm:
                renamed.add((nm, std))
            have.setdefault(std, (a["x"], a["y"], a["z"]))
        need = HEAVY_ATOMS[aa] + (["OXT"] if i == len(seq) else [])
        if i == len(seq) and "OXT" not in have and all(k in have for k in ("C", "O", "CA")):
            have["OXT"] = _place_oxt(have["C"], have["O"], have["CA"])
            notes.append(msg("oxt"))
        missing = [k for k in need if k not in have]
        if missing:
            raise FoldError("atoms_missing", i=i, res=r["resname"], atoms=", ".join(missing))
        out.append({k: have[k] for k in need})
    notes += [msg("renamed", old=a, new=b) for a, b in sorted(renamed)]
    return out, notes


def _place_oxt(c, o, ca) -> tuple:
    def sub(a, b): return [a[k] - b[k] for k in range(3)]
    def unit(v):
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]
    u1, u2 = unit(sub(o, c)), unit(sub(ca, c))
    d = unit([-(u1[k] + u2[k]) for k in range(3)])       # bisects the outside of the O-C-CA angle → ≈ 120° from both
    return tuple(round(c[k] + 1.25 * d[k], 3) for k in range(3))


# --------------------------------------------------------------------------- hardware and tool discovery
def gpu_vram_mb() -> int:
    """Largest NVIDIA GPU memory in MB (0 when none).  The engines here use CUDA; AMD and Apple GPUs run on the CPU."""
    try:
        from ..env.hardware import _nvidia
        return max([int(g.get("vram_mb") or 0) for g in _nvidia() if g.get("vram_mb")] or [0])
    except Exception:  # noqa: BLE001
        return 0


def fold_env_prefix() -> Path:
    """Separate environment for the folding tools (see setup_plan): $MD20_FOLD_ENV, else <root>/envs/md20-fold next
    to the md20 environment, else ~/.md20/envs/md20-fold."""
    if os.environ.get("MD20_FOLD_ENV"):
        return Path(os.environ["MD20_FOLD_ENV"])
    p = Path(sys.prefix)
    if p.parent.name == "envs":
        return p.parent / "md20-fold"
    return Path.home() / ".md20" / "envs" / "md20-fold"


def _env_bin_dirs(prefix: Path) -> list[Path]:
    return [prefix / "bin", prefix / "Scripts", prefix]


def find_tool(name: str) -> str | None:
    """Executable on PATH or in the folding environment."""
    w = shutil.which(name)
    if w:
        return w
    for d in _env_bin_dirs(fold_env_prefix()):
        for cand in (d / name, d / f"{name}.exe"):
            if cand.is_file():
                return str(cand)
    return None


def _fold_env_python() -> str | None:
    pre = fold_env_prefix()
    for cand in (pre / "bin" / "python", pre / "python.exe"):
        if cand.is_file():
            return str(cand)
    return None


def _has_package(python: str | None, pkg: str) -> bool:
    if python is None:
        import importlib.util
        try:
            return importlib.util.find_spec(pkg) is not None
        except (ImportError, ValueError):
            return False
    pre = Path(python).parent if Path(python).name.startswith("python.exe") else Path(python).parent.parent
    return any(pre.glob(f"lib/python3*/site-packages/{pkg}")) or (pre / "Lib" / "site-packages" / pkg).is_dir()


def _esmfold_runner() -> tuple[str, str] | None:
    """("cli", path) for the fair-esm `esm-fold` script, or ("hf", python) for HF transformers in some environment."""
    exe = find_tool("esm-fold")
    if exe:
        return "cli", exe
    if _has_package(None, "transformers") and _has_package(None, "torch"):
        return "hf", sys.executable
    py = _fold_env_python()
    if py and _has_package(py, "transformers") and _has_package(py, "torch"):
        return "hf", py
    return None


def engine_available(name: str) -> bool:
    if name == "upload":
        return True
    if name == "esmfold":
        return _esmfold_runner() is not None
    return find_tool({"omegafold": "omegafold", "boltz": "boltz", "colabfold": "colabfold_batch"}[name]) is not None


def fold_status(vram_mb: int | None = None) -> dict:
    """What is installed (for `md20 setup-fold` and the computer-status page)."""
    v = gpu_vram_mb() if vram_mb is None else vram_mb
    return {"gpu_vram_mb": v, "fold_env": str(fold_env_prefix()),
            "engines": {e: engine_available(e) for e in ENGINES if e != "upload"}}


def choose_engine(n_chains: int, *, vram_mb: int, available: dict[str, bool]) -> tuple[str, str, list[dict]]:
    """(engine, device, notes) for engine="auto".  Raises FoldUnavailable with the reason."""
    notes: list[dict] = []
    if n_chains > 1:
        if available.get("boltz") and vram_mb >= MIN_VRAM_MB["boltz"]:
            return "boltz", "cuda", notes
        if available.get("colabfold"):
            return "colabfold", "cuda" if vram_mb else "cpu", notes
        raise FoldUnavailable("no_engine_complex", need=MIN_VRAM_MB["boltz"] // 1000,
                              have=f"{vram_mb / 1000:.0f} GB" if vram_mb else "0 GB",
                              options=[OPT_INSTALL, OPT_UPLOAD, OPT_NO_FOLD])
    if available.get("omegafold"):
        if vram_mb >= MIN_VRAM_MB["omegafold"]:
            return "omegafold", "cuda", notes
        notes.append(msg("cpu", engine="omegafold"))
        return "omegafold", "cpu", notes
    if available.get("esmfold") and vram_mb >= MIN_VRAM_MB["esmfold"]:
        return "esmfold", "cuda", notes
    if available.get("boltz") and vram_mb >= MIN_VRAM_MB["boltz"]:
        return "boltz", "cuda", notes
    if available.get("colabfold"):
        return "colabfold", "cuda" if vram_mb else "cpu", notes
    if available.get("esmfold"):
        notes.append(msg("cpu", engine="esmfold"))
        return "esmfold", "cpu", notes
    raise FoldUnavailable("no_engine", options=[OPT_INSTALL, OPT_UPLOAD, OPT_NO_FOLD])


# --------------------------------------------------------------------------- running engines
def _run(cmd: list[str], log: Path, engine: str, timeout_s: float, cwd: Path | None = None) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "w", encoding="utf-8", errors="replace") as fh:
        fh.write("$ " + " ".join(cmd) + "\n")
        fh.flush()
        try:
            rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=str(cwd) if cwd else None,
                                timeout=timeout_s).returncode
        except subprocess.TimeoutExpired:
            raise FoldError("timeout", engine=engine, minutes=int(timeout_s // 60), log=str(log)) from None
        except OSError as exc:
            fh.write(f"\n{type(exc).__name__}: {exc}\n")
            raise FoldError("failed", engine=engine, rc=type(exc).__name__, log=str(log)) from None
    if rc != 0:
        raise FoldError("failed", engine=engine, rc=rc, log=str(log))


def _write_fasta(path: Path, name: str, seq: str) -> Path:
    path.write_text(f">{name}\n{seq}\n", encoding="ascii")
    return path


def _run_omegafold(seqs, chains, out: Path, device: str, timeout_s: float, **_) -> tuple[Path, dict]:
    exe = find_tool("omegafold")
    if not exe:
        raise FoldUnavailable("engine_missing", engine="omegafold", options=[OPT_INSTALL, OPT_UPLOAD, OPT_NO_FOLD])
    fasta = _write_fasta(out / "input.fasta", "peptide", seqs[0])
    _run([exe, str(fasta), str(out / "omegafold"), "--device", device], out / "omegafold.log", "omegafold", timeout_s)
    pdb = out / "omegafold" / "peptide.pdb"
    if not pdb.is_file():
        raise FoldError("no_output", engine="omegafold", where=str(out / "omegafold"))
    return pdb, {"log": str(out / "omegafold.log")}


ESMFOLD_HF_RUNNER = '''import sys
import torch
from transformers import EsmForProteinFolding
seq, out, device = sys.argv[1], sys.argv[2], sys.argv[3]
model = EsmForProteinFolding.from_pretrained("facebook/esmfold_v1", low_cpu_mem_usage=True)
if device == "cuda":
    model = model.cuda()
    model.esm = model.esm.half()
    torch.backends.cuda.matmul.allow_tf32 = True
model.trunk.set_chunk_size(64)
model.eval()
with torch.no_grad():
    pdb = model.infer_pdb(seq)
open(out, "w").write(pdb)
'''


def _run_esmfold(seqs, chains, out: Path, device: str, timeout_s: float, **_) -> tuple[Path, dict]:
    r = _esmfold_runner()
    if r is None:
        raise FoldUnavailable("engine_missing", engine="esmfold", options=[OPT_INSTALL, OPT_UPLOAD, OPT_NO_FOLD])
    kind, exe = r
    log = out / "esmfold.log"
    if kind == "cli":
        fasta = _write_fasta(out / "input.fasta", "peptide", seqs[0])
        cmd = [exe, "-i", str(fasta), "-o", str(out / "esmfold"), "--chunk-size", "64"] + (["--cpu-only"] if device == "cpu" else [])
        _run(cmd, log, "esmfold", timeout_s)
        pdb = out / "esmfold" / "peptide.pdb"
    else:
        script = out / "esmfold_runner.py"
        script.write_text(ESMFOLD_HF_RUNNER, encoding="utf-8")
        pdb = out / "esmfold" / "peptide.pdb"
        pdb.parent.mkdir(parents=True, exist_ok=True)
        _run([exe, "-I", str(script), seqs[0], str(pdb), device], log, "esmfold", timeout_s)
    if not pdb.is_file():
        raise FoldError("no_output", engine="esmfold", where=str(pdb.parent))
    return pdb, {"log": str(log)}


def boltz_yaml(seqs: list[str], chains: list[str], *, msa_server: bool) -> str:
    lines = ["version: 1", "sequences:"]
    for c, s in zip(chains, seqs):
        lines += ["  - protein:", f"      id: {c}", f"      sequence: {s}"]
        if not msa_server:
            lines.append("      msa: empty")
    return "\n".join(lines) + "\n"


def _confidence_from_json(path: Path | None) -> dict:
    if not path or not path.is_file():
        return {}
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {"confidence_json": str(path)}
    for k in ("iptm", "ptm", "complex_plddt"):
        v = d.get(k)
        if isinstance(v, list) and v and not isinstance(v[0], (list, dict)):
            v = v[0]                                 # AlphaFold Server summary may list one value per sample
        if isinstance(v, (int, float)):
            out[k] = float(v)
    if isinstance(d.get("plddt"), list) and d["plddt"] and isinstance(d["plddt"][0], (int, float)):
        out["plddt"] = [float(x) for x in d["plddt"]]
    return out


def _run_boltz(seqs, chains, out: Path, device: str, timeout_s: float, *, msa_server: bool = False, **_) -> tuple[Path, dict]:
    exe = find_tool("boltz")
    if not exe:
        raise FoldUnavailable("engine_missing", engine="boltz", options=[OPT_INSTALL, OPT_UPLOAD, OPT_NO_FOLD])
    y = out / "md20fold.yaml"
    y.write_text(boltz_yaml(seqs, chains, msa_server=msa_server), encoding="ascii")
    cmd = [exe, "predict", str(y), "--out_dir", str(out), "--output_format", "pdb",
           "--accelerator", "gpu" if device == "cuda" else "cpu"] + (["--use_msa_server"] if msa_server else [])
    _run(cmd, out / "boltz.log", "boltz", timeout_s)
    pred = out / "boltz_results_md20fold" / "predictions" / "md20fold"
    pdb = pred / "md20fold_model_0.pdb"
    if not pdb.is_file():
        hits = sorted(out.glob("boltz_results_*/predictions/*/*_model_0.pdb"))
        if not hits:
            raise FoldError("no_output", engine="boltz", where=str(out))
        pdb, pred = hits[0], hits[0].parent
    conf = _confidence_from_json(next(iter(sorted(pred.glob("confidence_*_model_0.json"))), None))
    return pdb, {**conf, "log": str(out / "boltz.log"), "msa": "server" if msa_server else "empty"}


def _run_colabfold(seqs, chains, out: Path, device: str, timeout_s: float, **_) -> tuple[Path, dict]:
    exe = find_tool("colabfold_batch")
    if not exe:
        raise FoldUnavailable("engine_missing", engine="colabfold", options=[OPT_INSTALL, OPT_UPLOAD, OPT_NO_FOLD])
    fasta = _write_fasta(out / "input.fasta", "md20fold", ":".join(seqs))
    res = out / "colabfold"
    _run([exe, str(fasta), str(res), "--num-models", "1"], out / "colabfold.log", "colabfold", timeout_s)
    hits = sorted(res.glob("md20fold*_unrelaxed_rank_001_*.pdb"))
    if not hits:
        raise FoldError("no_output", engine="colabfold", where=str(res))
    pdb = hits[0]
    conf = _confidence_from_json(Path(str(pdb).replace("_unrelaxed_rank_", "_scores_rank_")).with_suffix(".json"))
    return pdb, {**conf, "log": str(out / "colabfold.log"), "msa": "server"}


def upload_confidence_json(path: Path) -> Path | None:
    """The confidence file that belongs to an uploaded model, found only by the tools' own naming:
    AlphaFold Server  fold_x_model_0.cif → fold_x_summary_confidences_0.json
    ColabFold         x_unrelaxed_rank_001_….pdb → x_scores_rank_001_….json
    Boltz             x_model_0.pdb → confidence_x_model_0.json"""
    n = path.name
    cands = []
    m = re.match(r"(.*)_model_(\d+)\.(cif|pdb)$", n)
    if m:
        cands += [path.with_name(f"{m.group(1)}_summary_confidences_{m.group(2)}.json"),
                  path.with_name(f"confidence_{m.group(1)}_model_{m.group(2)}.json")]
    if "_unrelaxed_rank_" in n or "_relaxed_rank_" in n:
        cands.append(path.with_name(re.sub(r"_(un)?relaxed_rank_", "_scores_rank_", n)).with_suffix(".json"))
    return next((c for c in cands if c.is_file()), None)


RUNNERS = {"omegafold": _run_omegafold, "esmfold": _run_esmfold, "boltz": _run_boltz, "colabfold": _run_colabfold}


# --------------------------------------------------------------------------- main entry
def fold(sequences: list[str] | str, *, engine: str = "auto", out_dir: Path | str, upload: Path | str | None = None,
         confidence_json: Path | str | None = None, peptide_index: int = -1, msa_server: bool = False,
         device: str | None = None, vram_mb: int | None = None, timeout_s: float = DEFAULT_TIMEOUT_S,
         available: dict[str, bool] | None = None, apply_gates: bool = True, accept_low: bool = False) -> FoldResult:
    """Predict (or read an uploaded) structure.  Returns a FoldResult with gates applied (see fold_gates).

    A single peptide shorter than MIN_FOLD_RESIDUES returns status "SKIPPED_SHORT" without running anything."""
    seqs = [sequences] if isinstance(sequences, str) else list(sequences)
    seqs = [clean(s, f"#{i + 1}") for i, s in enumerate(seqs)]
    chains = chain_ids(len(seqs))
    pi = peptide_index % len(seqs)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if engine not in ("auto",) + ENGINES:
        raise FoldError("unknown_engine", engine=engine, choices=", ".join(("auto",) + ENGINES))
    if upload is not None:
        engine = "upload"
    if len(seqs) == 1 and len(seqs[0]) < MIN_FOLD_RESIDUES and engine != "upload":
        r = FoldResult(engine="none", sequences=seqs, chains=chains, peptide_chain=chains[pi], peptide_sequence=seqs[pi],
                       status="SKIPPED_SHORT",
                       provenance="extended build (not folded)",
                       notes=[msg("short", n=len(seqs[0]), min=MIN_FOLD_RESIDUES)])
        _save(r, out)
        return r
    notes: list[dict] = []
    t0 = time.time()
    v = gpu_vram_mb() if vram_mb is None else int(vram_mb)
    if engine == "upload":
        if upload is None:
            raise FoldError("upload_missing", path="-")
        src, meta, dev = Path(upload), {}, ""
        cj = Path(confidence_json) if confidence_json else upload_confidence_json(src)
        meta.update(_confidence_from_json(cj))
    else:
        avail = available if available is not None else {e: engine_available(e) for e in RUNNERS}
        if engine == "auto":
            engine, dev, n0 = choose_engine(len(seqs), vram_mb=v, available=avail)
            notes += n0
        else:
            if len(seqs) > 1 and engine not in COMPLEX_ENGINES:
                raise FoldError("single_only", engine=engine, options=["fold_engine: boltz", OPT_UPLOAD])
            if not avail.get(engine):
                raise FoldUnavailable("engine_missing", engine=engine, options=[OPT_INSTALL, OPT_UPLOAD, OPT_NO_FOLD])
            dev = "cuda" if v >= MIN_VRAM_MB[engine] and v > 0 else "cpu"
            if dev == "cpu":
                notes.append(msg("cpu", engine=engine))
        dev = device or dev
        if engine == "boltz" and len(seqs) > 1 and sum(map(len, seqs)) > 600 and v < 16000:
            notes.append(msg("big_complex", n=sum(map(len, seqs)), have=f"{v / 1000:.0f} GB"))
        src, meta = RUNNERS[engine](seqs, chains, out, dev, timeout_s, msa_server=msa_server)
        if engine == "boltz":
            notes.append(msg("msa_server" if msa_server else "msa_empty"))
        elif engine == "colabfold":
            notes.append(msg("msa_server"))
    res = residues(read_structure(src))
    # chain identity: by sequence (engines may rename chains); receptor chains keep the order given
    pep_chain = find_chain(res, seqs[pi], prefer=chains[pi])
    scale = 100.0 if max((a["b"] for rs in res.values() for r in rs for a in r["atoms"].values()), default=0) <= 1.0 else 1.0
    if scale != 1.0:
        notes.append(msg("scaled"))
        for rs in res.values():
            for r in rs:
                for a in r["atoms"].values():
                    a["b"] = a["b"] * scale
    by_chain = {c: [round(x, 2) for x in residue_plddt(rs)] for c, rs in res.items()}
    pdb = write_pdb(res, out / "predicted.pdb", remark=f"MD20 predicted structure ({engine}); B-factor = pLDDT")
    allv = [x for vv in by_chain.values() for x in vv]
    r = FoldResult(engine=engine, sequences=seqs, chains=list(res.keys()), peptide_chain=pep_chain,
                   peptide_sequence=seqs[pi], pdb_path=str(pdb),
                   source_path=str(src), per_residue_plddt=by_chain[pep_chain], plddt_by_chain=by_chain,
                   mean_plddt=_mean(by_chain[pep_chain]),
                   complex_plddt=(round(meta["complex_plddt"] * (100 if meta["complex_plddt"] <= 1 else 1), 2)
                                  if "complex_plddt" in meta else (_mean(allv) if len(res) > 1 else None)),
                   iptm=meta.get("iptm") if len(res) > 1 else None, runtime_s=round(time.time() - t0, 1), device=dev,
                   notes=notes, log_path=meta.get("log", ""),
                   provenance="predicted" if engine != "upload" else "predicted (uploaded)")
    r.notes.append(msg("predicted", engine=engine))
    if apply_gates:
        rep = fold_gates(r, accept_low=accept_low)
        r.gates, r.status = rep.to_dict(), rep.status
    _save(r, out)
    return r


def _save(r: FoldResult, out: Path) -> None:
    (out / "fold_result.json").write_text(json.dumps(r.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def fold_gates(r: FoldResult, *, accept_low: bool = False) -> GateReport:
    """Spec §4.  Gate explanations are Chinese (DecisionLog convention); `evidence.text` has all four languages."""
    rep = GateReport()
    if r.status == "SKIPPED_SHORT" or r.mean_plddt is None:
        return rep
    v = float(r.mean_plddt)
    ev = {"mean_plddt": v, "engine": r.engine, "per_residue_plddt": r.per_residue_plddt}
    if v >= PLDDT_PASS:
        t = msg("plddt_pass", v=v)
        rep.add(Gate("fold confidence", PASS, t["zh"], evidence={**ev, "text": t}))
    elif v >= PLDDT_LOW:
        t = msg("plddt_low", v=v)
        rep.add(Gate("fold confidence", AUTO_FIXED, t["zh"], diff=["標註：低可信度預測，以 MD 檢驗"], evidence={**ev, "text": t}))
    elif accept_low:
        t = msg("plddt_accepted", v=v)
        rep.add(Gate("fold confidence", AUTO_FIXED, t["zh"], diff=["使用者選擇：仍使用 pLDDT < 50 的預測結構"],
                     evidence={**ev, "text": t, "human": True}))
    else:
        t = msg("plddt_bad", v=v)
        rep.add(Gate("fold confidence", NEEDS_HUMAN, t["zh"], options=[OPT_NO_FOLD, OPT_OTHER_ENGINE, OPT_UPLOAD, OPT_ACCEPT_LOW],
                     evidence={**ev, "text": t}))
    if r.is_complex and r.iptm is not None:
        if r.iptm < IPTM_MIN:
            t = msg("iptm_low", v=r.iptm)
            rep.add(Gate("fold interface", AUTO_FIXED, t["zh"], options=["接受並在報告中標註"], advisory=True,
                         evidence={"iptm": r.iptm, "text": t}))
        else:
            t = msg("iptm_ok", v=r.iptm)
            rep.add(Gate("fold interface", PASS, t["zh"], evidence={"iptm": r.iptm, "text": t}))
    return rep


# --------------------------------------------------------------------------- into MD20's peptide path
def peptide_residues(r: FoldResult) -> list[dict]:
    return residues(read_structure(r.pdb_path))[r.peptide_chain]


def docking_sdf(r: FoldResult, out_sdf: Path | str, *, transform=None) -> tuple[Path, list[dict]]:
    """The predicted peptide as an SDF with the sequence template's chemistry (RDKit MolFromSequence, same atoms as
    md20.build.peptide) and the predicted heavy-atom coordinates.  Used as the docking input conformation."""
    from rdkit import Chem
    from rdkit.Geometry import Point3D
    seq = r.peptide_sequence or r.sequences[-1]
    coords, notes = peptide_heavy_coords(peptide_residues(r), seq)
    if transform is not None:
        coords = [{k: apply_transform(v, transform) for k, v in c.items()} for c in coords]
    tmpl = Chem.RemoveHs(Chem.MolFromSequence(seq))
    conf = Chem.Conformer(tmpl.GetNumAtoms())
    for a in tmpl.GetAtoms():
        info = a.GetPDBResidueInfo()
        nm, ri = info.GetName().strip(), info.GetResidueNumber()
        xyz = coords[ri - 1].get(nm)
        if xyz is None:
            raise FoldError("atoms_missing", i=ri, res=info.GetResidueName(), atoms=nm)
        conf.SetAtomPosition(a.GetIdx(), Point3D(*xyz))
    tmpl.RemoveAllConformers()
    tmpl.AddConformer(conf, assignId=True)
    tmpl.SetProp("_Name", f"predicted_{r.engine}")
    tmpl.SetProp("md20_provenance", r.provenance)
    out_sdf = Path(out_sdf)
    out_sdf.parent.mkdir(parents=True, exist_ok=True)
    w = Chem.SDWriter(str(out_sdf)); w.write(tmpl); w.close()
    return out_sdf, notes


# --------------------------------------------------------------------------- complex → actual receptor (superposition)
def align(a: str, b: str, *, match: int = 2, mismatch: int = -1, gap: int = -2) -> list[tuple[int, int]]:
    """Global (Needleman-Wunsch) alignment; returns the aligned index pairs (i in a, j in b) of identical residues."""
    n, m = len(a), len(b)
    S = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        S[i][0] = i * gap
    for j in range(1, m + 1):
        S[0][j] = j * gap
    for i in range(1, n + 1):
        ai, Si, Sp = a[i - 1], S[i], S[i - 1]
        for j in range(1, m + 1):
            Si[j] = max(Sp[j - 1] + (match if ai == b[j - 1] else mismatch), Sp[j] + gap, Si[j - 1] + gap)
    i, j, out = n, m, []
    while i > 0 and j > 0:
        if S[i][j] == S[i - 1][j - 1] + (match if a[i - 1] == b[j - 1] else mismatch):
            if a[i - 1] == b[j - 1]:
                out.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif S[i][j] == S[i - 1][j] + gap:
            i -= 1
        else:
            j -= 1
    return out[::-1]


def kabsch(P, Q):
    """(R, t, rmsd) with Q ≈ P @ R.T + t (least squares, proper rotation)."""
    import numpy as np
    P, Q = np.asarray(P, float), np.asarray(Q, float)
    pc, qc = P.mean(0), Q.mean(0)
    H = (P - pc).T @ (Q - qc)
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    D = np.diag([1.0, 1.0, d])
    R = Vt.T @ D @ U.T
    t = qc - pc @ R.T
    rmsd = float(np.sqrt(((P @ R.T + t - Q) ** 2).sum(1).mean()))
    return R, t, rmsd


def apply_transform(xyz, transform) -> tuple:
    import numpy as np
    R, t = transform
    v = np.asarray(xyz, float) @ np.asarray(R).T + np.asarray(t)
    return tuple(round(float(x), 3) for x in v)


def chain_breaks(res_list: list[dict], max_ca_ca: float = 4.2) -> int:
    n, prev = 0, None
    for r in res_list:
        ca = r["atoms"].get("CA")
        if ca and prev and math.dist((ca["x"], ca["y"], ca["z"]), (prev["x"], prev["y"], prev["z"])) > max_ca_ca:
            n += 1
        prev = ca or prev
    return n


def receptor_sequences(reference: Path | str, *, exclude_chains: set[str] | None = None) -> tuple[list[str], list[str], list[dict]]:
    """Protein chain sequences of an actual receptor structure (for folding the complex), with gap notes."""
    res = residues(read_structure(reference))
    chains = [c for c in res if c not in (exclude_chains or set()) and len(res[c]) >= 2]
    seqs = chain_sequences(res)
    notes = [msg("chain_break", chain=c, n=k) for c in chains if (k := chain_breaks(res[c]))]
    return [seqs[c] for c in chains], chains, notes


@dataclass
class Placement:
    peptide_pdb: str
    receptor_source: str                 # "actual" (crystal or uploaded receptor) or "predicted"
    rmsd_ca: float | None = None
    n_matched: int = 0
    pocket_rmsd_ca: float | None = None  # matched Cα within 10 Å of the placed peptide (evidence only)
    chain_map: dict = field(default_factory=dict)
    min_contact_A: float | None = None
    transform: list | None = None        # [R (3×3), t (3)] mapping the prediction onto the actual receptor
    receptor_pdb: str = ""               # predicted receptor when there is no actual one
    status: str = PASS
    gates: dict = field(default_factory=dict)
    notes: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def place_peptide(r: FoldResult, out_dir: Path | str, *, reference: Path | str | None = None,
                  exclude_chains: set[str] | None = None, accept_rmsd: bool = False,
                  max_rmsd: float = SUP_MAX_RMSD) -> Placement:
    """Complex prediction → peptide pose for MD.

    With an actual receptor (`reference`, crystal or uploaded): every predicted receptor chain is aligned by sequence to
    the actual chain it matches best, identical aligned residues give Cα pairs, Kabsch superposes the prediction onto the
    actual receptor and only the peptide is taken over.  Cα RMSD > max_rmsd → NEEDS_HUMAN (unless accept_rmsd).
    Without one: the predicted receptor is used as is and labelled predicted."""
    import numpy as np
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pred = residues(read_structure(r.pdb_path))
    pep = pred[r.peptide_chain]
    rep = GateReport()
    if reference is None:
        rec = {c: v for c, v in pred.items() if c != r.peptide_chain}
        pl = Placement(peptide_pdb=str(write_pdb({r.peptide_chain: pep}, out / "peptide_pose.pdb",
                                                 remark=f"MD20 predicted peptide ({r.engine})")),
                       receptor_source="predicted",
                       receptor_pdb=str(write_pdb(rec, out / "receptor_predicted.pdb",
                                                  remark=f"MD20 PREDICTED receptor ({r.engine}), not experimental")))
        t = msg("sup_predicted")
        rep.add(Gate("fold placement", AUTO_FIXED, t["zh"], diff=["受體為預測結構"], evidence={"text": t}))
        pl.notes.append(t)
        pl.gates, pl.status = rep.to_dict(), rep.status
        return pl
    ref = {c: v for c, v in residues(read_structure(reference)).items() if c not in (exclude_chains or set())}
    ref_seq = chain_sequences(ref)
    pairs_p, pairs_q, used, cmap = [], [], set(), {}
    for c, rs in pred.items():
        if c == r.peptide_chain:
            continue
        ps = "".join(x["one"] for x in rs)
        best = max(((rc, align(ps, s)) for rc, s in ref_seq.items() if rc not in used), key=lambda x: len(x[1]), default=None)
        if not best or not best[1]:
            continue
        rc, al = best
        used.add(rc)
        cmap[c] = rc
        for i, j in al:
            a, b = rs[i]["atoms"].get("CA"), ref[rc][j]["atoms"].get("CA")
            if a and b:
                pairs_p.append((a["x"], a["y"], a["z"]))
                pairs_q.append((b["x"], b["y"], b["z"]))
    n = len(pairs_p)
    pl = Placement(peptide_pdb="", receptor_source="actual", n_matched=n, chain_map=cmap)
    if n < SUP_MIN_MATCHED:
        t = msg("sup_few", n=n, min=SUP_MIN_MATCHED)
        rep.add(Gate("fold placement", NEEDS_HUMAN, t["zh"], options=[OPT_RECEPTOR_SEQ, OPT_UPLOAD, OPT_DOCK],
                     evidence={"text": t, "n_matched": n}))
        pl.gates, pl.status = rep.to_dict(), rep.status
        return pl
    R, tvec, rmsd = kabsch(pairs_p, pairs_q)
    pl.rmsd_ca, pl.transform = round(rmsd, 3), [R.tolist(), tvec.tolist()]
    moved = {r.peptide_chain: [{**x, "atoms": {k: {**a, **dict(zip("xyz", apply_transform((a["x"], a["y"], a["z"]), (R, tvec))))}
                                                for k, a in x["atoms"].items()}} for x in pep]}
    pl.peptide_pdb = str(write_pdb(moved, out / "peptide_pose.pdb",
                                   remark=f"MD20 predicted peptide ({r.engine}) superposed on the actual receptor"))
    P = np.array([(a["x"], a["y"], a["z"]) for x in moved[r.peptide_chain] for a in x["atoms"].values()])
    Q = np.array([(a["x"], a["y"], a["z"]) for rs in ref.values() for x in rs for a in x["atoms"].values()])
    if len(P) and len(Q):
        pl.min_contact_A = round(float(np.sqrt(((P[:, None, :] - Q[None, :, :]) ** 2).sum(-1)).min()), 2)
    PP, QQ = np.asarray(pairs_p) @ R.T + tvec, np.asarray(pairs_q)
    near = np.sqrt(((QQ[:, None, :] - P[None, :, :]) ** 2).sum(-1)).min(1) <= 10.0 if len(P) else np.zeros(n, bool)
    if near.sum() >= 3:
        pl.pocket_rmsd_ca = round(float(np.sqrt(((PP[near] - QQ[near]) ** 2).sum(1).mean())), 3)
    ev = {"rmsd_ca": pl.rmsd_ca, "n_matched": n, "pocket_rmsd_ca": pl.pocket_rmsd_ca, "chain_map": cmap,
          "min_contact_A": pl.min_contact_A}
    if rmsd <= max_rmsd:
        t = msg("sup_pass", n=n, rmsd=rmsd, max=max_rmsd)
        rep.add(Gate("fold placement", PASS, t["zh"], evidence={**ev, "text": t}))
    elif accept_rmsd:
        t = msg("sup_accepted", rmsd=rmsd, max=max_rmsd)
        rep.add(Gate("fold placement", AUTO_FIXED, t["zh"], diff=["使用者選擇：仍使用 RMSD 超過門檻的胜肽姿勢"],
                     evidence={**ev, "text": t, "human": True}))
    else:
        t = msg("sup_high", n=n, rmsd=rmsd, max=max_rmsd)
        rep.add(Gate("fold placement", NEEDS_HUMAN, t["zh"], options=[OPT_ACCEPT_RMSD, OPT_DOCK, OPT_UPLOAD, OPT_RECEPTOR_SEQ],
                     evidence={**ev, "text": t}))
    if pl.min_contact_A is not None and pl.min_contact_A < 1.5:
        pl.notes.append(msg("contact", d=pl.min_contact_A))
    pl.gates, pl.status = rep.to_dict(), rep.status
    return pl


# --------------------------------------------------------------------------- installation plan (md20 setup-fold)
# Approximate sizes (from the projects' documentation and wheel sizes; not measured on the laptop yet).
# Plan texts are Chinese: they are command-line output (docs/specs/writing_style.md §3).
SETUP = {
    "omegafold": {"pip": ["--no-deps", "https://github.com/HeliXonProtein/OmegaFold/archive/refs/heads/main.zip", "biopython"],
                  "download": "OmegaFold 權重 release1.pt（約 3 GB，未實測）到 ~/.cache/omegafold_ckpt",
                  "license": "Apache-2.0"},
    "boltz": {"pip": ["boltz"],
              "download": "Boltz-2 權重 boltz2_conf.ckpt 與 mols.tar（數 GB，未實測）到 ~/.boltz",
              "license": "MIT"},
    "esmfold": {"pip": ["transformers", "accelerate"],
                "download": "Hugging Face 的 facebook/esmfold_v1（約 8 GB，未實測）到 ~/.cache/huggingface",
                "license": "MIT"},
}
FOLD_ENV_PYTHON = "3.10"      # OmegaFold's setup.py accepts only Python 3.8-3.10; Boltz needs >= 3.10


def find_micromamba() -> str | None:
    if os.environ.get("MAMBA_EXE") and Path(os.environ["MAMBA_EXE"]).is_file():
        return os.environ["MAMBA_EXE"]
    w = shutil.which("micromamba")
    if w:
        return w
    root = Path(sys.prefix).parent.parent
    for cand in (root / "micromamba.exe", root / "bin" / "micromamba", root / "Library" / "bin" / "micromamba.exe"):
        if cand.is_file():
            return str(cand)
    return None


def setup_plan(engine: str, *, vram_mb: int | None = None, platform: str | None = None,
               micromamba: str | None = "auto", prefix: Path | None = None) -> dict:
    """Commands that `md20 setup-fold` runs, in order, with what they download.  Nothing runs here.

    The tools go into a separate environment (default <root>/envs/md20-fold, Python 3.10), not into md20's own:
    OmegaFold refuses Python 3.11 (md20's version) in its setup.py, and Boltz pins numpy<2, scipy 1.13.1 and
    gemmi 0.6.5, which would downgrade packages the OpenMM and docking stack uses.  MD20 calls the tools as programs."""
    if engine not in SETUP:
        raise FoldError("unknown_engine", engine=engine, choices=", ".join(SETUP))
    plat = platform or sys.platform
    v = gpu_vram_mb() if vram_mb is None else vram_mb
    mm = find_micromamba() if micromamba == "auto" else micromamba
    pre = prefix or fold_env_prefix()
    py = str(pre / ("python.exe" if plat == "win32" else "bin/python"))
    cuda = v > 0 and plat != "darwin"
    torch_cmd = [py, "-m", "pip", "install", "torch"] + (["--index-url", "https://download.pytorch.org/whl/cu121"] if cuda else [])
    steps = []
    if not Path(py).is_file():
        if not mm:
            return {"engine": engine, "prefix": str(pre), "ok": False, "steps": [],
                    "problem": "找不到 micromamba（請從 MD20 的啟動器開啟，或設定 MAMBA_EXE）"}
        steps.append({"cmd": [mm, "create", "-y", "-p", str(pre), "-c", "conda-forge", f"python={FOLD_ENV_PYTHON}", "pip"],
                      "what": f"建立新環境 {pre}（Python {FOLD_ENV_PYTHON}，約 100 MB）"})
    steps.append({"cmd": torch_cmd, "what": "PyTorch " + ("CUDA 12.1 版（約 2.5 GB）" if cuda else "CPU 版（約 200 到 800 MB）")})
    steps.append({"cmd": [py, "-m", "pip", "install"] + SETUP[engine]["pip"],
                  "what": f"{engine}（授權 {SETUP[engine]['license']}）"})
    return {"engine": engine, "prefix": str(pre), "ok": True, "cuda": cuda, "steps": steps,
            "first_run_download": SETUP[engine]["download"]}
