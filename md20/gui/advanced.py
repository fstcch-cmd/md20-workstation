"""Professional-mode settings for membrane systems, peptide folding and long runs (D-80, D-81), without NiceGUI.

The form keeps these settings in one plain dict (`ADV_DEFAULTS` shape); `apply_advanced` writes them into the
workflow config (md.membrane, ligands[i].fold*, md.long_run_confirmed) and `advanced_checks` returns issues in the
same shape as advisor.check, so the page shows them in the same panel.  The computer-status page uses
`tool_rows` and `setup_preview` (plans only: nothing is installed from here).

Text: (zh, en, ja, ko) tuples, plain wording (docs/specs/writing_style.md).
"""
from __future__ import annotations

import copy
import re
import os
import sys
from pathlib import Path

from ..i18n import pick, colon

MEMBRANE_TYPES = {
    "none": ("不用膜（水盒）", "No membrane (water box)", "膜なし（水ボックス）", "막 없음(물 상자)"),
    "protein": ("膜蛋白：受體嵌在脂雙層中", "Membrane protein: the receptor sits in a bilayer",
                "膜タンパク質：受容体を脂質二重膜に埋め込む", "막단백질: 수용체를 지질 이중층에 넣음"),
    "surface": ("膜表面接觸：胜肽或小分子放在膜上方", "Membrane surface: a peptide or small molecule above a bilayer",
                "膜表面への接触：ペプチドか低分子を膜の上に置く", "막 표면 접촉: 펩타이드나 저분자를 막 위에 둠"),
    "bilayer": ("純膜：只有脂雙層", "Bilayer only: lipids, water and ions", "膜のみ：脂質二重膜だけ", "막만: 지질 이중층만"),
}
RESOLUTIONS = {
    "aa": ("全原子（預設）", "All-atom (default)", "全原子（既定）", "전원자(기본)"),
    "cg": ("粗粒化 Martini 3（微秒以上，珠子層級）", "Coarse-grained Martini 3 (microseconds and longer, bead level)",
           "粗視化 Martini 3（マイクロ秒以上、ビーズ単位）", "조립화 Martini 3(마이크로초 이상, 비드 단위)"),
}
LIPID_PRESETS = {
    "mammalian": ("哺乳類細胞膜（POPC）", "Mammalian cell membrane (POPC)", "哺乳類の細胞膜（POPC）", "포유류 세포막(POPC)"),
    "bacterial": ("細菌內膜（POPE 75 %、POPG 25 %）", "Bacterial inner membrane (POPE 75 %, POPG 25 %)",
                  "細菌の内膜（POPE 75 %、POPG 25 %）", "세균 내막(POPE 75 %, POPG 25 %)"),
    "gram_positive": ("格蘭氏陽性菌細胞膜（目前無法建模）", "Gram-positive cell membrane (cannot be built yet)",
                      "グラム陽性菌の細胞膜（現在は構築できません）", "그람 양성균 세포막(아직 구축할 수 없음)"),
    "POPC": ("純 POPC", "POPC only", "POPC のみ", "POPC만"),
    "POPE": ("純 POPE", "POPE only", "POPE のみ", "POPE만"),
    "DOPC": ("純 DOPC", "DOPC only", "DOPC のみ", "DOPC만"),
    "DMPC": ("純 DMPC", "DMPC only", "DMPC のみ", "DMPC만"),
    "DLPC": ("純 DLPC", "DLPC only", "DLPC のみ", "DLPC만"),
    "DPPC": ("純 DPPC（310 K 為凝膠相）", "DPPC only (gel phase at 310 K)", "DPPC のみ（310 K ではゲル相）", "DPPC만(310 K에서 겔 상)"),
}
FOLD_MODES = {
    "off": ("不摺疊（由序列建立構形，交給對接）", "Off (conformation built from the sequence, then docked)",
            "折りたたまない（配列から構造を作ってドッキング）", "접지 않음(서열로 구조를 만든 뒤 도킹)"),
    "dock": ("預測胜肽結構後對接", "Predict the peptide structure, then dock it",
             "ペプチドの構造を予測してからドッキング", "펩타이드 구조를 예측한 뒤 도킹"),
    "complex": ("預測受體與胜肽的複合物，不經對接", "Predict the receptor and peptide complex, no docking",
                "受容体とペプチドの複合体を予測（ドッキングなし）", "수용체와 펩타이드 복합체 예측(도킹 없음)"),
}
FOLD_ENGINES = {
    "auto": ("自動（依顯示卡記憶體選擇）", "Automatic (chosen from the graphics memory)", "自動（GPU メモリで選択）",
             "자동(그래픽 메모리로 선택)"),
    "omegafold": ("OmegaFold（單獨胜肽）", "OmegaFold (peptide alone)", "OmegaFold（ペプチド単独）", "OmegaFold(펩타이드 단독)"),
    "boltz": ("Boltz-2（可預測複合物）", "Boltz-2 (can predict complexes)", "Boltz-2（複合体も予測可）", "Boltz-2(복합체 예측 가능)"),
    "upload": ("上傳預測結構", "Upload a predicted structure", "予測構造をアップロード", "예측 구조 업로드"),
}
ADV_DEFAULTS = {"membrane_type": "none", "lipids": "mammalian", "oriented": False, "surface_distance_nm": 1.0,
                "fold": "off", "fold_engine": "auto", "fold_receptor_seq": "", "fold_upload": "", "long_run_confirmed": False,
                "resolution": "aa"}
LONG_RUN_CONFIRM_NS = 1000.0          # > 1 µs needs md.long_run_confirmed (engine/longrun.py)

TEXT = {
    "membrane": ("膜系統", "Membrane", "膜系", "막 계"),
    "resolution": ("模擬解析度", "Resolution", "分解能", "해상도"),
    "resolution_help": ("粗粒化把約 4 個重原子併成一顆珠子，時間步 20 fs，同一台筆電可以跑到微秒以上，用來看膜蛋白在膜裡的"
                        "排列、胜肽貼上膜的過程與膜的變化。代價是沒有氫鍵與原子細節，也不做對接和結合自由能；小分子配體不會放進系統。",
                        "Coarse-graining merges about four heavy atoms into one bead and uses a 20 fs time step, so the same "
                        "laptop reaches microseconds and longer. Use it to see how a membrane protein sits in the bilayer, how "
                        "a peptide lands on a membrane, and how the membrane responds. The cost: no hydrogen bonds or atomic "
                        "detail, no docking and no binding free energy; small-molecule ligands are left out.",
                        "粗視化では重原子およそ 4 個を 1 個のビーズにまとめ、時間刻みは 20 fs です。同じノート PC でマイクロ秒以上"
                        "まで計算でき、膜タンパク質の膜内での配置、ペプチドが膜に付く過程、膜の変化を見るのに使います。代わりに"
                        "水素結合や原子の細部はなく、ドッキングと結合自由エネルギーも行いません。低分子リガンドは系に入れません。",
                        "조립화는 중원자 약 4개를 비드 하나로 묶고 시간 간격 20 fs를 씁니다. 같은 노트북으로 마이크로초 이상 계산할 수 "
                        "있어 막단백질이 막 안에 놓이는 모습, 펩타이드가 막에 붙는 과정, 막의 변화를 보는 데 씁니다. 대신 수소 결합과 "
                        "원자 수준의 세부는 없고 도킹과 결합 자유 에너지도 하지 않습니다. 저분자 리간드는 계에 넣지 않습니다."),
    "membrane_help": ("膜蛋白、抗菌胜肽或藥物與細胞膜的作用需要脂雙層。膜取代水盒，溫度預設 310 K。"
                      "膜系統目前不做結合自由能。",
                      "Membrane proteins, and peptides or drugs acting on a cell membrane, need a lipid bilayer. The bilayer "
                      "replaces the water box and the default temperature is 310 K. Binding free energy is not available "
                      "for membrane systems yet.",
                      "膜タンパク質や、細胞膜に作用するペプチドや薬物には脂質二重膜が必要です。膜が水ボックスの代わりになり、"
                      "温度の既定値は 310 K です。膜系の結合自由エネルギーはまだ計算できません。",
                      "막단백질이나 세포막에 작용하는 펩타이드와 약물에는 지질 이중층이 필요합니다. 막이 물 상자를 대신하며 "
                      "기본 온도는 310 K입니다. 막 계의 결합 자유 에너지는 아직 계산할 수 없습니다."),
    "membrane_type": ("膜系統類型", "Membrane system", "膜系の種類", "막 계 종류"),
    "lipids": ("脂質組成", "Lipid composition", "脂質の組成", "지질 조성"),
    "lipids_help": ("單一脂質用 OpenMM 內建的平衡膜片。混合膜用格點排列，還沒有在真實引擎上驗證。",
                    "A single lipid uses an equilibrated patch that ships with OpenMM. Mixed membranes are laid out on a grid, "
                    "which has not been verified on a real engine yet.",
                    "単一の脂質には OpenMM 付属の平衡化済み膜パッチを使います。混合膜は格子に並べますが、実際のエンジンではまだ検証していません。",
                    "단일 지질은 OpenMM에 포함된 평형 막 조각을 씁니다. 혼합 막은 격자에 배치하며, 실제 엔진에서는 아직 검증하지 않았습니다."),
    "oriented": ("結構已依膜定向（例如 OPM 下載）", "Structure already oriented in the membrane (for example from OPM)",
                 "構造は膜に合わせて向きをそろえ済み（例：OPM から入手）", "구조가 막에 맞춰 방향이 정해져 있음(예: OPM에서 받음)"),
    "oriented_help": ("勾選時照原樣使用，膜中心在 z = 0。不勾選時由疏水帶自動判定方向，判定不明確會停下來問你。",
                      "When ticked, the structure is used as is with the membrane centre at z = 0. Otherwise the orientation "
                      "comes from a scan for the hydrophobic belt, and the run stops to ask you when the scan is unclear.",
                      "チェックするとそのまま使い、膜の中心を z = 0 とします。チェックしない場合は疎水帯から向きを自動で決め、"
                      "はっきりしないときは止まって確認します。",
                      "체크하면 그대로 쓰며 막 중심은 z = 0입니다. 체크하지 않으면 소수성 띠로 방향을 자동으로 정하고, "
                      "판단이 불분명하면 멈추고 묻습니다."),
    "surface_distance": ("起始距離（膜上方）", "Starting distance above the membrane", "膜からの初期距離", "막 위 시작 거리"),
    "surface_help": ("分子最低的原子放在上層磷原子平面上方這個距離。0.3 nm 以下會擋下，因為分子會從頭基裡面開始。",
                     "The lowest atom of the molecule starts this far above the upper phosphate plane. Below 0.3 nm the run "
                     "is stopped, because the molecule would start inside the head groups.",
                     "分子のいちばん低い原子を、上側のリン原子面からこの距離だけ上に置きます。0.3 nm 以下では頭部基の中から"
                     "始まるので止めます。",
                     "분자의 가장 낮은 원자를 위쪽 인 원자 평면에서 이 거리만큼 위에 둡니다. 0.3 nm 이하면 머리 부분 안에서 "
                     "시작하므로 멈춥니다."),
    "fold": ("胜肽摺疊", "Peptide folding", "ペプチドの折りたたみ", "펩타이드 접힘"),
    "fold_help": ("由序列預測胜肽的結構。結果標註為預測，平均 pLDDT 低於 50 會停下來問你。少於 10 個殘基的胜肽不摺疊。"
                  "需要先安裝摺疊工具（電腦狀態頁）。",
                  "Predicts the peptide structure from its sequence. The result is labelled as predicted, and a mean pLDDT "
                  "below 50 stops the run to ask you. Peptides under 10 residues are not folded. A folding tool must be "
                  "installed first (see the computer status page).",
                  "配列からペプチドの構造を予測します。結果は予測として明記し、平均 pLDDT が 50 未満なら止まって確認します。"
                  "10 残基未満のペプチドは折りたたみません。先にフォールディングツールのインストールが必要です（パソコンの状態のページ）。",
                  "서열로 펩타이드 구조를 예측합니다. 결과는 예측으로 표시하며 평균 pLDDT가 50 미만이면 멈추고 묻습니다. "
                  "10잔기 미만 펩타이드는 접지 않습니다. 먼저 폴딩 도구를 설치해야 합니다(컴퓨터 상태 페이지)."),
    "fold_mode": ("摺疊方式", "Folding", "折りたたみ方法", "접힘 방식"),
    "fold_engine": ("摺疊工具", "Folding tool", "フォールディングツール", "폴딩 도구"),
    "fold_receptor_seq": ("受體序列（可不填）", "Receptor sequence (optional)", "受容体の配列（省略可）", "수용체 서열(선택)"),
    "fold_receptor_help": ("只用在複合物預測。不填時由受體結構讀出序列。結構有缺口時，填完整序列較準。多條鏈用冒號分開。",
                           "Used only for the complex prediction. When empty, the sequence is read from the receptor structure. "
                           "If the structure has gaps, the full sequence gives a better result. Separate chains with a colon.",
                           "複合体の予測にだけ使います。空欄なら受容体の構造から配列を読みます。構造に欠損があるときは完全な配列のほうが"
                           "正確です。複数の鎖はコロンで区切ります。",
                           "복합체 예측에만 씁니다. 비워 두면 수용체 구조에서 서열을 읽습니다. 구조에 빈 곳이 있으면 전체 서열이 더 "
                           "정확합니다. 사슬이 여럿이면 콜론으로 나눕니다."),
    "fold_upload": ("上傳預測結構（PDB 或 mmCIF）", "Upload the predicted structure (PDB or mmCIF)",
                    "予測構造をアップロード（PDB か mmCIF）", "예측 구조 업로드(PDB 또는 mmCIF)"),
    "quick_fold": ("先摺疊這個胜肽", "Fold this peptide first", "このペプチドを先に折りたたむ", "이 펩타이드를 먼저 접기"),
    "long_run": ("長時間模擬", "Long run", "長時間シミュレーション", "장시간 시뮬레이션"),
    "long_run_confirm": ("我已確認天數與硬碟用量，要跑這個長度", "I have checked the days and disk use and want this length",
                         "日数とディスク使用量を確認し、この長さで実行します", "일수와 디스크 사용량을 확인했고 이 길이로 실행합니다"),
    "long_run_note": ("超過 1 µs 要先確認。不勾選時，流程會在正式模擬前停下來問你。",
                      "Runs over 1 µs need a confirmation. Without it, the workflow stops before production and asks you.",
                      "1 µs を超える計算には確認が必要です。チェックしない場合は本計算の前に止まって確認します。",
                      "1 µs를 넘는 계산은 확인이 필요합니다. 체크하지 않으면 본 계산 전에 멈추고 묻습니다."),
    "long_run_estimate": ("估計以水盒中的蛋白計算，膜系統的原子數不同。", "The estimate assumes a protein in a water box. "
                          "Membrane systems have a different atom count.",
                          "見積もりは水ボックス中のタンパク質を想定しています。膜系では原子数が異なります。",
                          "추정은 물 상자 속 단백질을 가정합니다. 막 계는 원자 수가 다릅니다."),
    "predicted_complex": ("預測複合物，沒有對接分數", "Predicted complex, no docking score", "予測複合体（ドッキングスコアなし）",
                          "예측 복합체, 도킹 점수 없음"),
}


def tx(key: str, lang: str) -> str:
    return pick(TEXT[key], lang)


def defaults() -> dict:
    return copy.deepcopy(ADV_DEFAULTS)


def peptide_names(ligands: list[dict]) -> list[str]:
    return [l["name"] for l in ligands or [] if isinstance(l, dict) and l.get("sequence")]


def default_fold_names(ligands: list[dict]) -> list[str]:
    """D-85: peptides folded by default in quick mode (at least MIN_FOLD_RESIDUES residues)."""
    from ..build.fold import MIN_FOLD_RESIDUES
    return [l["name"] for l in ligands or [] if isinstance(l, dict) and len(l.get("sequence") or "") >= MIN_FOLD_RESIDUES]


def membrane_spec(adv: dict) -> dict | None:
    """md.membrane for the chosen settings (None for no membrane)."""
    t = adv.get("membrane_type") or "none"
    if t == "none":
        return None
    lip = adv.get("lipids") or "mammalian"
    spec = {"type": t, "lipids": lip if lip in ("mammalian", "bacterial", "gram_positive") else {lip: 1.0}}
    if t == "protein":
        spec["oriented"] = bool(adv.get("oriented"))
    if t == "surface":
        spec["surface_distance_nm"] = float(adv.get("surface_distance_nm") or 1.0)
    return spec


_AA = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")


def receptor_sequences(text: str) -> list[str]:
    """`fold_receptor_seq` from the form: chains separated by a colon or a new line; spaces are ignored."""
    parts = [re.sub(r"\s+", "", p).upper() for p in re.split(r"[:\n]", text or "")]
    return [p for p in parts if p]


def apply_advanced(cfg: dict, adv: dict, *, quick_fold: set | list | None = None) -> dict:
    """Write the settings into a copy of the config.  Quick mode passes only `quick_fold` (peptide names to fold)."""
    out = copy.deepcopy(cfg)
    md = out.setdefault("md", {})
    spec = membrane_spec(adv)
    if spec:
        md["membrane"] = spec
    else:
        md.pop("membrane", None)
    if spec and spec["type"] in ("surface", "bilayer"):
        out["receptor"] = {}                       # cases B and C have no receptor (workflow.build_membrane_cases)
        out["box"] = {}
        if spec["type"] == "bilayer":
            out["ligands"] = []
    mode = adv.get("fold") or "off"
    qf = set(quick_fold or ())
    for l in out.get("ligands") or []:
        if not l.get("sequence"):
            continue
        for k in ("fold", "fold_engine", "fold_upload", "fold_receptor_seq"):
            l.pop(k, None)
        if l["name"] in qf:
            l["fold"] = True
            continue
        if mode == "off":
            continue
        l["fold"] = True if mode == "dock" else "complex"
        if (adv.get("fold_engine") or "auto") != "auto":
            l["fold_engine"] = adv["fold_engine"]
        if adv.get("fold_engine") == "upload" and adv.get("fold_upload"):
            l["fold_upload"] = adv["fold_upload"]
        seqs = receptor_sequences(adv.get("fold_receptor_seq") or "")
        if mode == "complex" and seqs:
            l["fold_receptor_seq"] = seqs[0] if len(seqs) == 1 else seqs
    if adv.get("resolution") == "cg":
        md["resolution"] = "cg"
        out["ligands"] = [l for l in out.get("ligands") or [] if l.get("sequence")] if (spec or {}).get("type") == "surface" \
            else ([] if spec and spec["type"] == "bilayer" else out.get("ligands") or [])
        out.setdefault("binding", {})["enabled"] = False
    else:
        md.pop("resolution", None)
    if adv.get("long_run_confirmed"):
        md["long_run_confirmed"] = True
    else:
        md.pop("long_run_confirmed", None)
    return out


def _issue(level: str, key: str, label: tuple, text: tuple, lang: str, suggestion=None) -> dict:
    return {"level": level, "key": key, "label": pick(label, lang), "message": pick(text, lang), "suggestion": suggestion}


def advanced_checks(adv: dict, *, ligands: list[dict], has_receptor: bool, binding: bool, solvent: str = "explicit",
                    production_ns: float | None = None, fold_installed: dict | None = None, lang: str = "en",
                    cg_ready: bool | None = None) -> list[dict]:
    """Issues for the right-hand panel (same shape as advisor.check).  error blocks the start button."""
    from ..build.membrane import plan_membrane
    from .gate_text import gate_title, gate_general
    out: list[dict] = []
    spec = membrane_spec(adv)
    peps = peptide_names(ligands)
    mem_label = TEXT["membrane"]
    if spec:
        t = spec["type"]
        if t == "protein" and not has_receptor:
            out.append(_issue("error", "membrane_type", mem_label,
                              ("膜蛋白系統需要受體。請輸入 PDB 編號或上傳結構，或改成膜表面接觸。",
                               "A membrane protein system needs a receptor. Enter a PDB ID or upload a structure, or choose "
                               "the membrane surface system.",
                               "膜タンパク質の系には受容体が必要です。PDB ID を入力するか構造をアップロードしてください。"
                               "または膜表面への接触を選んでください。",
                               "막단백질 계에는 수용체가 필요합니다. PDB ID를 입력하거나 구조를 업로드하십시오. "
                               "또는 막 표면 접촉을 고르십시오."), lang))
        if t == "surface" and not ligands:
            out.append(_issue("error", "membrane_type", mem_label,
                              ("膜表面接觸要有一個胜肽或小分子。請在配體欄填入。", "The membrane surface system needs a peptide "
                               "or small molecule. Enter one in the ligand box.",
                               "膜表面への接触にはペプチドか低分子が一つ必要です。リガンド欄に入力してください。",
                               "막 표면 접촉에는 펩타이드나 저분자가 하나 필요합니다. 리간드 칸에 입력하십시오."), lang))
        if t in ("surface", "bilayer") and has_receptor:
            out.append(_issue("info", "membrane_type", mem_label,
                              ("這個膜系統不使用受體，建立流程時不會放入受體。", "This membrane system does not use the "
                               "receptor. It is left out when the workflow is created.",
                               "この膜系では受容体を使いません。ワークフローを作るときに受容体は入れません。",
                               "이 막 계는 수용체를 쓰지 않습니다. 워크플로를 만들 때 수용체는 넣지 않습니다."), lang))
        if t == "bilayer" and ligands:
            out.append(_issue("info", "membrane_type", mem_label,
                              ("純膜不放配體，配體欄的內容不會使用。", "A bilayer-only system has no ligands. The ligand box "
                               "is not used.", "膜のみの系にはリガンドを入れません。リガンド欄の内容は使いません。",
                               "막만 있는 계에는 리간드를 넣지 않습니다. 리간드 칸의 내용은 쓰지 않습니다."), lang))
        if binding:
            out.append(_issue("error", "binding", mem_label,
                              ("膜系統還不能計算結合自由能：拉離方向可能穿過脂雙層。請關閉結合強度計算。",
                               "Binding free energy is not available for membrane systems: the pulling path may cross the "
                               "bilayer. Turn off the binding strength calculation.",
                               "膜系の結合自由エネルギーはまだ計算できません。引き離しの経路が脂質二重膜を横切る可能性があります。"
                               "結合の強さの計算をオフにしてください。",
                               "막 계의 결합 자유 에너지는 아직 계산할 수 없습니다. 당기는 경로가 지질 이중층을 지날 수 있습니다. "
                               "결합 세기 계산을 끄십시오."), lang, suggestion=False))
        solute = has_receptor if t == "protein" else (bool(ligands) if t == "surface" else False)
        if not (t == "protein" and not has_receptor) and not (t == "surface" and not ligands):
            _, rep = plan_membrane(spec, has_solute=solute, solvent=solvent)
            for g in rep.gates:
                if g.status == "PASS":
                    continue
                level = "error" if g.status == "NEEDS_HUMAN" else "info"
                title = gate_title(g.name, lang)
                msg = gate_general(g.name, lang) or g.explanation
                out.append({"level": level, "key": "membrane_type", "label": pick(mem_label, lang) + colon(lang) + title,
                            "message": msg, "suggestion": None})
    mode = adv.get("fold") or "off"
    if mode != "off":
        fl = TEXT["fold"]
        if not peps:
            out.append(_issue("warning", "fold", fl, ("配體裡沒有胜肽，摺疊設定不會用到。", "There is no peptide among the "
                              "ligands, so the folding setting has no effect.", "リガンドにペプチドがないので、折りたたみの設定は使われません。",
                              "리간드에 펩타이드가 없어 접힘 설정은 쓰이지 않습니다."), lang))
        if mode == "complex" and not has_receptor:
            out.append(_issue("error", "fold", fl, ("複合物預測要有受體結構，才能把胜肽放回受體。", "The complex prediction "
                              "needs a receptor structure to place the peptide back into it.",
                              "複合体の予測には、ペプチドを受容体に戻すための受容体構造が必要です。",
                              "복합체 예측에는 펩타이드를 수용체에 다시 놓을 수용체 구조가 필요합니다."), lang))
        if mode == "complex" and spec and spec["type"] in ("surface", "bilayer"):
            out.append(_issue("error", "fold", fl, ("膜表面系統沒有受體，不能用複合物預測。請改成預測胜肽結構後對接，或不摺疊。",
                              "A membrane surface system has no receptor, so the complex prediction cannot be used. Choose "
                              "folding before docking, or no folding.",
                              "膜表面の系には受容体がないので、複合体の予測は使えません。ペプチドの構造予測かオフを選んでください。",
                              "막 표면 계에는 수용체가 없어 복합체 예측을 쓸 수 없습니다. 펩타이드 구조 예측이나 끔을 고르십시오."), lang))
        if adv.get("fold_engine") == "upload" and not adv.get("fold_upload"):
            out.append(_issue("error", "fold", fl, ("選了上傳預測結構，但還沒有上傳檔案。", "Upload was chosen, but no file has "
                              "been uploaded yet.", "アップロードを選びましたが、まだファイルがありません。",
                              "업로드를 골랐지만 아직 파일을 올리지 않았습니다."), lang))
        bad = [s for s in receptor_sequences(adv.get("fold_receptor_seq") or "") if not _AA.match(s)]
        if bad:
            out.append(_issue("error", "fold", fl, ("受體序列只能有 20 種標準胺基酸的單字母代碼。", "The receptor sequence may "
                              "contain only the one-letter codes of the 20 standard amino acids.",
                              "受容体の配列には 20 種類の標準アミノ酸の 1 文字表記だけを使えます。",
                              "수용체 서열에는 표준 아미노산 20종의 한 글자 기호만 쓸 수 있습니다."), lang))
        inst = fold_installed or {}
        engine = adv.get("fold_engine") or "auto"
        if peps and engine != "upload" and inst and not (inst.get(engine) if engine != "auto" else any(inst.values())):
            out.append(_issue("warning", "fold", fl, ("這台電腦還沒有安裝摺疊工具，流程會在摺疊時停下來。到電腦狀態頁按「一鍵安裝」。",
                              "No folding tool is installed on this computer, so the workflow will stop at the folding step. "
                              "Press Install now on the computer status page.",
                              "このコンピューターにはフォールディングツールがないため、折りたたみの段階で止まります。"
                              "パソコンの状態のページで「今すぐインストール」を押してください。",
                              "이 컴퓨터에는 폴딩 도구가 없어 접힘 단계에서 멈춥니다. 컴퓨터 상태 페이지에서 '지금 설치'를 누르십시오."), lang))
    if adv.get("resolution") == "cg":
        rl = TEXT["resolution"]
        t = (spec or {}).get("type")
        small = [l["name"] for l in ligands or [] if not l.get("sequence")]
        if t in (None, "protein") and not has_receptor:
            out.append(_issue("error", "resolution", rl, ("粗粒化的蛋白系統需要受體。請輸入 PDB 編號或上傳結構，或改成純膜。",
                              "A coarse-grained protein system needs a receptor. Enter a PDB ID or upload a structure, or "
                              "choose the bilayer only.", "粗視化のタンパク質の系には受容体が必要です。PDB ID を入力するか構造を"
                              "アップロードしてください。または膜のみを選んでください。",
                              "조립화 단백질 계에는 수용체가 필요합니다. PDB ID를 입력하거나 구조를 올리십시오. 또는 막만을 고르십시오."), lang))
        if t == "surface" and not peps:
            out.append(_issue("error", "resolution", rl, ("粗粒化的膜表面接觸要有一個胜肽（小分子沒有通用的 Martini 3 參數）。",
                              "The coarse-grained membrane surface system needs a peptide (small molecules have no general "
                              "Martini 3 parameters).", "粗視化の膜表面への接触にはペプチドが必要です（低分子には汎用の Martini 3 "
                              "パラメータがありません）。", "조립화 막 표면 접촉에는 펩타이드가 필요합니다(저분자에는 범용 Martini 3 "
                              "매개변수가 없습니다)."), lang))
        if small and t != "bilayer":
            out.append(_issue("info", "resolution", rl, ("小分子配體不會放進粗粒化系統，也不做對接：" + ", ".join(small),
                              "Small-molecule ligands are left out of the coarse-grained system and are not docked: " + ", ".join(small),
                              "低分子リガンドは粗視化の系に入れず、ドッキングもしません：" + ", ".join(small),
                              "저분자 리간드는 조립화 계에 넣지 않고 도킹도 하지 않습니다: " + ", ".join(small)), lang))
        if binding:
            out.append(_issue("info", "resolution", rl, ("粗粒化不計算結合自由能，結合強度計算會自動關閉。",
                              "Binding free energy is not computed for coarse-grained runs; it is turned off automatically.",
                              "粗視化では結合自由エネルギーを計算しないので、結合の強さの計算は自動でオフになります。",
                              "조립화에서는 결합 자유 에너지를 계산하지 않으므로 결합 세기 계산은 자동으로 꺼집니다."), lang))
        if cg_ready is False:
            out.append(_issue("warning", "resolution", rl, ("這台電腦還沒有安裝粗粒化工具，流程會在建模時停下來。到電腦狀態頁按「一鍵安裝」。",
                              "The coarse-grained tools are not installed on this computer, so the workflow will stop at the "
                              "build. Press Install now on the computer status page.",
                              "このコンピューターには粗視化ツールがないため、構築の段階で止まります。パソコンの状態のページで"
                              "「今すぐインストール」を押してください。",
                              "이 컴퓨터에는 조립화 도구가 없어 구축 단계에서 멈춥니다. 컴퓨터 상태 페이지에서 '지금 설치'를 누르십시오."), lang))
    if production_ns and float(production_ns) > LONG_RUN_CONFIRM_NS and not adv.get("long_run_confirmed"):
        out.append(_issue("warning", "long_run", TEXT["long_run"], TEXT["long_run_note"], lang))
    return out


def long_run_view(values: dict, f, goal: str, lang: str) -> dict:
    """What the long-run card shows: {"show", "needs_confirm", "lines"}.  The plan comes from advisor.long_run_plan
    (engine/longrun.py); > 1 µs asks for the confirmation, > 10 µs is refused by the advisor checks."""
    from .. import advisor
    ns = float(values.get("production_ns") or 0)
    if ns <= 100:
        return {"show": False, "needs_confirm": False, "lines": []}
    lp = advisor.long_run_plan(values, f, goal)
    k = int(lp.get("keep_chunk_states") or 0)
    n_fr, n_ch = lp["n_frames"], lp["n_chunks"]
    keep = ((f"續跑檔只保留最新 {k} 段。", f"Restart files are kept for the latest {k} chunks only.",
             f"再開用ファイルは最新の {k} 区間だけ残します。", f"재시작 파일은 최근 {k}개 구간만 남깁니다.") if k else
            ("所有續跑檔都保留。", "All restart files are kept.", "再開用ファイルはすべて残します。", "재시작 파일은 모두 남깁니다."))
    lines = [pick(lp["summary"], lang),
             pick((f"約 {n_fr:,} 幀，分成 {n_ch:,} 段存檔。", f"About {n_fr:,} frames, saved in {n_ch:,} chunks.",
                   f"約 {n_fr:,} フレームを {n_ch:,} 区間に分けて保存します。", f"약 {n_fr:,}프레임을 {n_ch:,}개 구간으로 나눠 저장합니다."), lang)
             + ("" if lang in ("zh", "ja") else " ") + pick(keep, lang),
             tx("long_run_estimate", lang)]
    for i in lp.get("issues") or []:
        if i.get("level") == "block" and i.get("text"):
            lines.append(pick(i["text"], lang))
    return {"show": True, "needs_confirm": ns > LONG_RUN_CONFIRM_NS, "lines": lines, "plan": lp}


# ------------------------------------------------------------------------------- computer status: optional tools
def md20_command(platform: str | None = None) -> str:
    """How a student calls md20 from a terminal (docs/students)."""
    p = platform or sys.platform
    if p == "win32":
        return r"%LOCALAPPDATA%\MD20\md20.cmd"
    if p == "darwin":
        return "~/MD20/md20"
    return "md20"


TOOL_TEXT = {
    "fold": ("結構預測（胜肽摺疊）", "Structure prediction (peptide folding)", "構造予測（ペプチドの折りたたみ）",
             "구조 예측(펩타이드 접힘)"),
    "cg": ("粗粒化工具（Martini 3）", "Coarse-grained tools (Martini 3)", "粗視化ツール（Martini 3）", "조립화 도구(Martini 3)"),
    "installed": ("已安裝", "Installed", "インストール済み", "설치됨"),
    "missing": ("未安裝", "Not installed", "未インストール", "설치 안 됨"),
    "install_cmd": ("安裝指令（在終端機執行）", "Install command (run it in a terminal)", "インストールのコマンド（ターミナルで実行）",
                    "설치 명령(터미널에서 실행)"),
    "preview": ("顯示安裝計畫（不安裝）", "Show the install plan (installs nothing)", "インストール計画を表示（インストールしない）",
                "설치 계획 보기(설치하지 않음)"),
    "fold_detail": ("裝在獨立的環境，不影響 MD20 本身。第一次預測時會再下載模型權重（數 GB）。",
                    "Installed in a separate environment, so MD20 itself is not changed. The first prediction downloads "
                    "the model weights (several GB).",
                    "別の環境にインストールするので、MD20 本体には影響しません。最初の予測でモデルの重み（数 GB）をダウンロードします。",
                    "별도 환경에 설치하므로 MD20 자체는 바뀌지 않습니다. 첫 예측 때 모델 가중치(수 GB)를 내려받습니다."),
    "cg_detail": ("以 pip 裝進 MD20 的環境，並下載 Martini 3 力場檔（約 16 MB）。不需要另外找檔案。",
                  "Installed into MD20's environment with pip, together with the Martini 3 force-field files (about 16 MB). "
                  "Nothing else needs to be downloaded by hand.",
                  "pip で MD20 の環境にインストールし、Martini 3 の力場ファイル（約 16 MB）も一緒にダウンロードします。"
                  "手作業で集めるファイルはありません。",
                  "pip로 MD20 환경에 설치하고 Martini 3 역장 파일(약 16 MB)도 함께 내려받습니다. 따로 구할 파일은 없습니다."),
    "plan_title": ("安裝時會依序執行", "The install runs these commands in order", "インストール時に次のコマンドを順に実行します",
                   "설치할 때 다음 명령을 차례로 실행합니다"),
    "plan_problem": ("現在無法安裝", "It cannot be installed right now", "今はインストールできません", "지금은 설치할 수 없습니다"),
    "install_now": ("一鍵安裝", "Install now", "今すぐインストール", "지금 설치"),
    "installing": ("安裝中，可以繼續使用其他功能；這一頁會顯示進度。", "Installing. You can keep using MD20; this page shows "
                   "the progress.", "インストール中です。ほかの機能は使えます。このページに進み具合が出ます。",
                   "설치 중입니다. 다른 기능은 계속 쓸 수 있습니다. 이 페이지에 진행 상황이 나옵니다."),
    "install_done": ("安裝結束。結束碼", "Install finished. Exit code", "インストールが終わりました。終了コード",
                     "설치가 끝났습니다. 종료 코드"),
    "install_fold_note": ("會下載 PyTorch 與模型權重，總共數 GB，要 20 到 60 分鐘。請接上電源和網路，在上課前裝好。",
                          "Downloads PyTorch and the model weights, several GB in total, in 20 to 60 minutes. Keep the "
                          "computer on power and online, and install it before class.",
                          "PyTorch とモデルの重みを合わせて数 GB ダウンロードし、20〜60 分かかります。電源とネットにつないで、"
                          "授業の前にインストールしてください。",
                          "PyTorch와 모델 가중치를 합쳐 수 GB 내려받으며 20~60분 걸립니다. 전원과 네트워크를 연결하고 "
                          "수업 전에 설치하십시오."),
    "vram": ("顯示卡記憶體", "Graphics memory", "GPU メモリ", "그래픽 메모리"),
}


def tool_rows(fold_status: dict, cg_avail: dict, lang: str, *, platform: str | None = None,
              ff_ready: bool | None = None) -> list[dict]:
    """Rows for the computer-status page: what is installed and the exact command to install it."""
    cmd = md20_command(platform)
    fe = fold_status.get("engines") or {}
    have = [k for k, v in fe.items() if v]
    vram = fold_status.get("gpu_vram_mb") or 0
    fold_row = {"key": "fold", "title": pick(TOOL_TEXT["fold"], lang), "installed": bool(have),
                "status": pick(TOOL_TEXT["installed" if have else "missing"], lang),
                "detail": ", ".join(f"{k} {'✓' if v else '✗'}" for k, v in fe.items())
                          + f" · {pick(TOOL_TEXT['vram'], lang)} {vram / 1000:.1f} GB · {fold_status.get('fold_env', '')}",
                "note": pick(TOOL_TEXT["fold_detail"], lang),
                "command": f"{cmd} setup-fold --engine omegafold --yes"}
    ok = [k for k, v in cg_avail.items() if v.get("ok")]
    if ff_ready is None:
        from ..build.martini import forcefield_ready
        ff_ready = forcefield_ready()
    cg_ok = len(ok) == len(cg_avail) and bool(cg_avail) and bool(ff_ready)
    cg_row = {"key": "cg", "title": pick(TOOL_TEXT["cg"], lang), "installed": cg_ok,
              "status": pick(TOOL_TEXT["installed" if cg_ok else "missing"], lang),
              "detail": ", ".join(f"{k} {'✓' if v.get('ok') else '✗'}" for k, v in cg_avail.items())
                        + f", Martini 3 force field {'✓' if ff_ready else '✗'}",
              "note": pick(TOOL_TEXT["cg_detail"], lang), "command": f"{cmd} setup-cg --yes"}
    return [fold_row, cg_row]


def install_argv(kind: str, python: str | None = None) -> list[str]:
    """D-85: what the "Install now" button runs (the same command a student would type; see docs/students)."""
    py = python or sys.executable
    if kind == "fold":
        return [py, "-m", "md20", "setup-fold", "--engine", "omegafold", "--yes", "--warmup"]
    if kind == "cg":
        return [py, "-m", "md20", "setup-cg", "--yes"]
    raise ValueError(kind)


INSTALLS: dict = {}          # kind -> {"proc": Popen, "log": Path}; one install of each kind at a time


def start_install(kind: str, log_dir: Path, *, popen=None) -> dict:
    """Start the install in the background and write its output to <log_dir>/setup-<kind>.log.  A running install of
    the same kind is returned as it is (no second copy)."""
    import subprocess
    cur = INSTALLS.get(kind)
    if cur and cur["proc"].poll() is None:
        return cur
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / f"setup-{kind}.log"
    fh = open(log, "w", encoding="utf-8", errors="replace")
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
    proc = (popen or subprocess.Popen)(install_argv(kind), stdout=fh, stderr=subprocess.STDOUT, env=env)
    INSTALLS[kind] = {"proc": proc, "log": log, "fh": fh}
    return INSTALLS[kind]


def install_progress(kind: str, tail: int = 12) -> tuple[str, int | None]:
    """(last lines of the log, exit code or None while running); ("", None) when nothing was started."""
    cur = INSTALLS.get(kind)
    if not cur:
        return "", None
    rc = cur["proc"].poll()
    if rc is not None and not cur["fh"].closed:
        cur["fh"].close()
    try:
        lines = Path(cur["log"]).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    return "\n".join(lines[-tail:]), rc


def setup_preview(kind: str, lang: str, *, fold_plan=None, cg_plan=None) -> list[str]:
    """The plan `md20 setup-fold` or `md20 setup-cg` would run, as lines (commands are not translated).
    Nothing is executed; `fold_plan`/`cg_plan` can be injected for tests."""
    if kind == "fold":
        if fold_plan is None:
            from ..build.fold import setup_plan
            fold_plan = setup_plan("omegafold")
        if not fold_plan.get("ok"):
            return [pick(TOOL_TEXT["plan_problem"], lang) + colon(lang) + str(fold_plan.get("problem", ""))]
        cmds = [s["cmd"] for s in fold_plan["steps"]]
    else:
        if cg_plan is None:
            from ..build.martini import install_plan
            cg_plan = install_plan()
        cmds = cg_plan
    return [pick(TOOL_TEXT["plan_title"], lang)] + [f"{i}. " + " ".join(str(x) for x in c) for i, c in enumerate(cmds, 1)]


# ------------------------------------------------------------------------------- pose selections
def score_text(score, lang: str) -> str:
    """A docking score for the interface; a peptide placed from a predicted complex has none (score None)."""
    if score is None:
        return tx("predicted_complex", lang)
    return f"{float(score):.2f}"


def selection_lines(selection: dict, lang: str) -> list[str]:
    """One line per chosen pose, for the confirm card."""
    out = []
    for name, v in (selection.get("ligands") or {}).items():
        if v.get("score") is None:
            out.append(f"{name}" + colon(lang) + tx("predicted_complex", lang))
        else:
            rk = v.get("rank")
            out.append(f"{name}" + colon(lang) + pick((f"第 {rk} 名姿勢，{v['score']:.2f} kcal/mol", f"pose {rk}, {v['score']:.2f} kcal/mol",
                                                        f"{rk} 位のポーズ、{v['score']:.2f} kcal/mol", f"{rk}위 포즈, {v['score']:.2f} kcal/mol"), lang))
    return out
