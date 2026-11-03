# Spec: 結構預測（輸入序列一鍵摺疊）

狀態：**[已實作，未實機驗證]**（2026-11-03，D-80；設計 2026-11-03，實作見 §7）。使用者要求：整合輕量版 AlphaFold，使用者只要輸入胜肽序列就能一鍵摺疊。

## 1. 現況
胜肽（`peptide:序列`）由序列建出延伸構形，交給 Vina 柔性對接；Vina 只在約 8 個殘基、32 個可旋轉鍵以內可靠。沒有結構預測。

## 2. 候選工具（查證結果，實作前再確認版本與授權）
| 工具 | 需要 MSA | 支援複合物 | 授權 | 資源（文獻或文件所述） | 適用 |
|---|---|---|---|---|---|
| OmegaFold | 否（單序列） | 否 | Apache-2.0 | 語言模型約 6.7 億參數，8 GB 顯示卡可跑短序列 | 單獨胜肽，預設 |
| ESMFold | 否 | 否（可用連接子技巧） | MIT | 完整模型約需 16–24 GB；分塊後約 8 GB 可跑 600 aa 內 | 單獨胜肽或蛋白，較大顯示卡 |
| Boltz-2 | 可選 | 是（蛋白＋胜肽、蛋白＋配體） | MIT | 文件寫 8 GB 以上建議，複合物常需 16 GB 以上 | 受體＋胜肽複合物 |
| ColabFold（AlphaFold2） | 是（MMseqs2 伺服器，需網路） | 是（Multimer） | Apache-2.0，權重 CC BY 4.0 | 本機需 Linux 或 WSL；可改用遠端 | 最高準確度；選用 |
| 使用者上傳 | — | — | — | — | AlphaFold Server、ColabFold 的結果 |
AlphaFold 3 的權重限非商業且需申請，不能內建。

## 3. 設計
- 新模組 `md20/build/fold.py`：統一介面 `fold(sequence(s), engine="auto") → 結構檔＋每殘基 pLDDT（＋複合物的 ipTM）`。
- `engine="auto"`：依 doctor 偵測的顯示卡記憶體選擇：單獨胜肽 → OmegaFold（GPU 不足時 CPU）；受體＋胜肽 → Boltz-2（記憶體不足 → 提示改用上傳或遠端 ColabFold）。
- 安裝：模型權重數 GB，不放進安裝包；`md20 setup-fold` 在需要時下載，GUI 的「電腦狀態」頁顯示是否已安裝。
- 流程：GUI 輸入序列 → 預測 → 預測結構進入既有的胜肽路徑（ff14SB、獨立鏈）→ 對接或直接以複合物進 MD 驗證穩定性。
- 很短的胜肽（< 10 殘基）通常沒有穩定結構：不硬摺疊，改用構形集合（多個起始構形）並在報告說明。

## 4. 閘門
- 平均 pLDDT ≥ 70：PASS；50–70：AUTO_FIXED（標註「低可信度，以 MD 檢驗」）；< 50：NEEDS_HUMAN（選項：視為無規捲曲用構形集合、改用其他工具、上傳結構）。
- 複合物 ipTM < 0.5：介面不可信，提醒以 MD 與對接交叉檢查。
- 預測結果一律標註為「預測」，報告不得寫成實驗結構。

## 5. 驗證
- 已知結構的胜肽（例如 melittin 2MLT、Trp-cage 1L2Y）預測後與實驗結構比較 RMSD，結果寫入本檔。
- CI 只能驗證介面與閘門邏輯（CI 沒有 GPU）；實際預測在筆電驗證。

## 6. 想請審查者回答
- 預設工具選 OmegaFold 是否恰當？胜肽（10–40 aa）上的準確度是否有文獻比較？
- pLDDT 門檻是否適用於短胜肽？

## 7. 實作（2026-11-03）
程式：`md20/build/fold.py`；命令列 `md20 fold`、`md20 setup-fold`（`md20/cli.py`）；流程掛點 `Workflow._fold_peptide`（`md20/workflow.py`）；
Vina 主鏈固定 `LigandInput.rigid_backbone`（`md20/docking/run.py`）；閘門標題與選項翻譯 `md20/gui/gate_text.py`；測試 `tests/test_fold.py`。

### 7.1 介面
`fold(sequences, engine="auto", out_dir, upload=None, confidence_json=None, peptide_index=-1, msa_server=False, device=None, accept_low=False) → FoldResult`。
`sequences` 是一條序列或清單（受體在前、胜肽在最後），鏈依序命名 A、B、C。`FoldResult`：`pdb_path`（一律轉成 PDB，B 因子＝pLDDT 0–100）、
`per_residue_plddt`（胜肽鏈）、`mean_plddt`（胜肽鏈，閘門用這個）、`complex_plddt`、`iptm`、`engine`、`device`、`runtime_s`、`status`、`gates`、
`notes`（四種語言 dict）、`provenance`（"predicted" 或 "predicted (uploaded)"，不會是實驗結構）。結果另存 `out_dir/fold_result.json`。
失敗一律丟 `FoldError`（`.text` 四種語言、`.options`），找不到工具是 `FoldUnavailable`。

### 7.2 各工具的呼叫方式（已讀原始碼查證，2026-11-03 的 main 分支）
| 工具 | 呼叫 | 輸出與信心值 |
|---|---|---|
| OmegaFold | `omegafold input.fasta outdir --device cuda\|cpu` | `outdir/<FASTA 標頭>.pdb`；B 因子＝confidence×100（`omegafold/__main__.py`）；殘基從 0 編號、沒有 OXT、沒有氫 |
| ESMFold | `esm-fold -i fasta -o dir --chunk-size 64 [--cpu-only]`（fair-esm），否則 HF transformers `EsmForProteinFolding.infer_pdb`（MD20 寫一個小腳本以 `python -I` 執行） | B 因子＝pLDDT×100；若檔案是 0–1 會自動乘 100 並註明 |
| Boltz-2 | `boltz predict md20fold.yaml --out_dir D --output_format pdb --accelerator gpu\|cpu [--use_msa_server]` | `D/boltz_results_md20fold/predictions/md20fold/md20fold_model_0.pdb`（B 因子＝pLDDT×100），`confidence_md20fold_model_0.json`（`iptm`、`complex_plddt` 0–1） |
| ColabFold | `colabfold_batch input.fasta D --num-models 1`（複合物以 `受體:胜肽` 一行） | `*_unrelaxed_rank_001_*.pdb`、`*_scores_rank_001_*.json`（`plddt`、`ptm`、`iptm`） |
| 上傳 | PDB 或 mmCIF（AlphaFold Server、ColabFold、Boltz 的輸出） | B 因子；ipTM 只依工具自己的檔名找對應的 JSON（AF Server `x_model_0.cif`→`x_summary_confidences_0.json`；ColabFold `unrelaxed`→`scores`；Boltz `confidence_x_model_0.json`），找不到就不填 |

Boltz 預設 `msa: empty`（單序列模式，不把序列送出去）並在 notes 註明受體準確度較低；`--msa-server` 才使用 MMseqs2 公開伺服器（序列會送出，未發表序列要注意）。

### 7.3 自動選擇（`engine="auto"`）
顯示卡記憶體由 `md20.env.hardware._nvidia()`（nvidia-smi）讀取；這幾個工具在 AMD 與 Apple 顯示卡上改用 CPU。
- 單一胜肽：OmegaFold（≥ 4 GB 用 GPU，否則 CPU 並註明）→ ESMFold（≥ 8 GB）→ Boltz（≥ 8 GB）→ ColabFold → ESMFold CPU → `FoldUnavailable`。
- 受體＋胜肽：Boltz（≥ 8 GB；總長 > 600 殘基且 < 16 GB 時提醒可能記憶體不足）→ ColabFold → `FoldUnavailable`（選項：安裝、上傳、不摺疊）。
- 記憶體門檻取自 §2 的文件數字，**尚未在 RTX 4060（8 GB）實測**。

### 7.4 閘門（與 §4 相同）
`fold confidence`：胜肽鏈平均 pLDDT ≥ 70 PASS；50–70 AUTO_FIXED（diff：低可信度預測，以 MD 檢驗）；< 50 NEEDS_HUMAN，選項
「不使用預測結構，改用延伸構形（fold: false）」「改用其他摺疊工具（fold_engine）」「上傳預測結構（fold_upload）」「仍使用這個預測結構（fold_accept_low: true）」。
選了最後一項時 AUTO_FIXED 並在 DecisionLog 記為 human。`fold interface`（只有複合物且有 ipTM）：< 0.5 為 advisory（不阻擋），≥ 0.5 PASS。
`fold`（流程層）：工具不可用或執行失敗時 NEEDS_HUMAN。

### 7.5 短胜肽
單獨胜肽 < 10 殘基不摺疊，回傳 `status="SKIPPED_SHORT"` 與說明，流程沿用既有由序列建立的延伸構形，由 Vina 搜尋改變構形
（Vina 每次搜尋會隨機化所有可旋轉鍵，等於在搜尋中取樣構形；沒有另外做多個起始構形的集合）。**精修**：此規則只用在單獨胜肽；
複合物預測與使用者上傳的結構即使短也照讀，因為結合狀態的構形可以由複合物預測得到，上傳則是使用者自己的選擇。

### 7.6 流程掛點與對接
設定 `ligands: [{"name": "PEP", "sequence": "...", "fold": true, "fold_engine": "auto", "fold_upload": "...", "fold_accept_low": false}]`。
`run_docking` 在 CPP 與口袋檢查之後呼叫 `_fold_peptide`：預測結果存在 `state["fold"][名稱]`（含 request、pLDDT、閘門、notes、docking_sdf），同一請求再跑時沿用。
`fold_accept_low`、`fold_upload`、`fold_engine` 已加入 `LIGAND_DECISION_KEYS`，`pipeline run` 重跑時保留。
預測結構以 `MolFromSequence` 模板（與 `md20/build/peptide.py` 相同的原子）加上預測座標寫成 SDF，當作 `LigandInput.sdf`。
**關鍵判斷**：只把預測結構當「起始構形」對 Vina 沒有意義，因為 Vina 每次 Monte Carlo 搜尋開始時會把位置、方向與所有可旋轉扭轉角隨機化，
預測的摺疊會被打散。所以 `rigid_backbone=True`：Meeko 以 `rigidify_bonds_smarts=["[#7]-[#6X4]-[#6X3](=[#8])"]×2`、索引 (0,1)、(1,2)
（0 起算，已讀 Meeko `bondtyper.py` 確認）把每個殘基的 φ（N–CA）與 ψ（CA–C）設為不可旋轉，側鏈仍可轉。Meeko 不支援此參數時直接報錯，不退回柔性。
附帶好處：可旋轉鍵大幅減少，回到 Vina 較可靠的範圍。之後建模仍走 `prepare_peptide`（ff14SB、獨立 chain），MD 檢查預測是否穩定。
被否決：(a) 把預測結構當起始構形但不固定主鏈（理由如上）；(b) 預測結構直接當受體的一部分（失去對接搜尋）。

原子對應：依殘基順序與標準原子名，Ile `CD`→`CD1`、`OT1/OT2`→`O/OXT` 視為同一原子並註明；缺 C 端 OXT 時以 C、O、CA 幾何補上（1.25 Å，在 O–C–CA 平面外側二等分方向）；
其他缺原子一律 `FoldError`，不猜。

### 7.7 安裝（`md20 setup-fold`）
**與原規劃不同**：不裝進 md20 環境，而是裝到獨立環境 `<root>/envs/md20-fold`（Python 3.10；可用 `MD20_FOLD_ENV` 指定）。理由（已讀原始碼）：
- OmegaFold 的 `setup.py` 只接受 Python 3.8–3.10，其他版本直接 `raise Exception`；md20 環境是 Python 3.11，所以 `pip install git+…OmegaFold` 在 md20 環境一定失敗。
  它還把 torch 1.12.0+cu113 的 wheel 網址寫死在相依套件裡，因此用 `--no-deps` 安裝，torch 另外裝。
- Boltz 2.2.1 鎖定 `numpy<2`、`scipy==1.13.1`、`gemmi==0.6.5`、`rdkit>=2024.3.2` 等，裝進 md20 環境會降級 OpenMM 與對接用到的套件。
- MD20 以外部程式呼叫這些工具（subprocess），所以環境分開沒有成本。
`md20 setup-fold [--engine omegafold|boltz|esmfold]` 先列出已安裝狀態、每一步指令、大小與第一次預測時會下載的權重，**只有加 `--yes` 才執行**。
步驟：`micromamba create -p <prefix> python=3.10 pip` → `pip install torch`（有 NVIDIA 時 `--index-url …/whl/cu121`）→ 工具本身。
找 micromamba：`MAMBA_EXE`、PATH、`<root>/micromamba.exe`、`<root>/bin/micromamba`。PyTorch 不加進 `environment/*.yml`。
大小（約，未實測）：PyTorch CUDA 約 2.5 GB；OmegaFold 權重約 3 GB（`~/.cache/omegafold_ckpt`）；Boltz-2 權重數 GB（`~/.boltz`）；ESMFold 約 8 GB（`~/.cache/huggingface`）。

### 7.8 驗證狀態
- 容器內（純 Python，`tests/test_fold.py`）：PDB 與 mmCIF 解析、0–1 B 因子換算、自動選擇、三態閘門、ipTM 提醒、短胜肽規則、上傳與信心檔對應、
  OXT 補位與缺原子不猜、安裝計畫、命令列、流程掛點（假工具、阻擋、使用者接受、快取、重跑保留決定）。
- CI（openmm-stack，有 RDKit 與 Meeko）：`test_docking_sdf_from_prediction`（模板原子名與預測座標對應）、`test_rigid_backbone_reduces_torsions`（TORSDOF 減少）。
- 尚未驗證：任何真實工具的執行（CI 沒有 GPU 也沒裝工具；`test_omegafold_real` 在沒有 omegafold 時跳過）、RTX 4060 的記憶體門檻、
  OmegaFold 在 torch 2.x 下是否正常（它用了 `torch.utils.hipify.hipify_python.str2bool`）、Boltz 在 Windows 的安裝、§5 的 RMSD 比較。

### 7.9 複合物直接進 MD（`fold: "complex"`，協調者 2026-11-03 決定）
- 決定：有實際受體結構（晶體或上傳）時，把預測的受體疊合到實際受體，只取預測的胜肽姿勢放進實際受體；只有受體序列時用預測的受體並標註為預測。
- `place_peptide(result, out_dir, reference=受體檔, accept_rmsd=False)`：每條預測受體鏈以 Needleman–Wunsch 全域比對（相同 +2、不同 −1、缺口 −2）
  配對到實際結構中最相符的鏈（每條實際鏈只用一次），只取**相同殘基**的 Cα 配對，Kabsch 疊合（含反射修正）。
  閘門 `fold placement`：Cα RMSD ≤ 2.0 Å PASS；> 2.0 Å NEEDS_HUMAN（選項：仍使用這個胜肽姿勢（fold_accept_rmsd: true）、改用對接（fold: true）、
  上傳預測結構、提供完整受體序列（fold_receptor_seq））；配對 Cα < 20 個 NEEDS_HUMAN。沒有實際受體時 AUTO_FIXED，受體檔第一行標 PREDICTED。
  另記錄口袋 Cα RMSD（胜肽 10 Å 內的配對 Cα，只當證據）與胜肽和受體最近重原子距離（< 1.5 Å 時註明由建模的最小化處理）。
- 流程：`ligands: [{"name": "PEP", "sequence": "...", "fold": "complex"}]`。受體序列預設由 `fetch_receptor` 的受體檔取（排除 `exclude_chains`），
  結構有缺口（Cα–Cα > 4.2 Å）時註明並建議以 `fold_receptor_seq`（字串或清單）提供完整序列。`run_docking` 對這個胜肽呼叫 `_fold_complex` 後不送進 Vina；
  所有配體都是 complex 時不執行對接，寫一份空的 docking 結果。`choose_poses` 以 `_complex_picks` 加入 `{"rank": 1, "score": None, "source": "fold_complex"}`，
  之後走同一條建模路徑（`prepare_peptide`、ff14SB、獨立 chain）與 MD。胜肽 SDF 由 `docking_sdf(result, path, transform=(R, t))` 寫出。
  `fold_accept_rmsd`、`fold_receptor_seq` 加入 `LIGAND_DECISION_KEYS`。DecisionLog `build.fold` 記錄配對數、RMSD、門檻與「不經對接」。
- 測試：比對與 Kabsch（已知旋轉還原）、正確疊合（缺 N 端 3 殘基、鏈名不同）、雜訊 RMSD > 2 Å 阻擋與使用者接受、無關受體、無受體、缺口提示、流程掛點，
  以及 CI 的 `test_docking_sdf_with_transform`。
- 限制：疊合用整條受體的 Cα；受體構形變化大（例如 loop 移動）時整體 RMSD 會超過 2 Å，即使口袋相符（看證據中的口袋 RMSD 再決定是否接受）。

### 7.10 未決
- GUI：輸入序列一鍵摺疊的按鈕、「電腦狀態」頁顯示 `fold_status()`、NEEDS_HUMAN 選項的一鍵寫回（`md20/gui/actions.py`）都還沒做。
  - 更正（D-85）：以上三項已在 D-80 後續與 D-85 做完（直接貼序列、預設勾選、一鍵安裝），見 §8。
- 報告：`state["fold"]` 已存，報告還沒有顯示（須標註「預測」）。

## 8. 直接貼序列就自動摺疊（D-85，2026-11-03 夜，使用者要求「打入序列在配體欄就自動做完所有的事」）
### 8.1 序列辨識（`md20/build/peptide.py: classify_ligand_text`）
- 規則：整串只有 20 種胺基酸字母、全大寫或全小寫，且至少含一個**不能不加括號出現在 SMILES 的字母**（A D E G H K L M Q R T V W Y）→ 胜肽。
  SMILES 不加括號可出現的大寫字母只有有機子集 B C N O P S F I；其中 C N P S F I 也是胺基酸。
- 只由 C N P S F I 組成：少於 5 個字母當 SMILES（`CCN`、`CC`）；5 個以上（`CCCCCN`）兩種讀法都說得通 → 擋下，請使用者加 `peptide:` 或 `smiles:`（寧可擋也不要猜）。
- 大小寫混合（`ClCCl`、`CBr`）一律是 SMILES。`peptide:`、`smiles:` 前綴仍可強制讀法。
- 一行只有序列時，名稱自動取 PEP、PP2…；只有 SMILES 仍要名稱（名稱是拓撲殘基名，自動取 LIG 容易與晶體配體混淆），加 `smiles:` 才自動取 LIG、LG2…。
- 被否決的做法：用 RDKit 試解析 SMILES 來判斷——介面解析在沒有 RDKit 的環境（CI 純 Python、GUI 預覽）也要能跑，而且 `CCCCCN` 兩種讀法都合法，解析成功不代表使用者的意思。
### 8.2 預設摺疊
- 快速模式：10 個殘基以上（`MIN_FOLD_RESIDUES`）的胜肽第一次出現時，「先摺疊這個胜肽」**預設勾選**；使用者可取消。短胜肽本來就會被 `fold()` 略過，不勾。
- 專業模式不變（摺疊群組由使用者選）；教學一、二不變（GGGGGKP 7 個殘基）。命令列的 config 不變（`fold` 未設就不摺疊），避免既有專案重跑時行為改變。
### 8.3 安裝
- `md20 setup-fold --warmup`：裝完試摺 melittin（26 殘基），在家把模型權重下載好，上課時不用再下載；試摺失敗回傳 3，訊息說明工具已裝但不能預測。
- 解壓資料夾新增 `Install-Folding.cmd`（Windows）與 `Install-Folding.command`（macOS）：雙擊即執行上述指令；自訂安裝位置用參數或 `MD20_ROOT`。
- `Install-MD20.cmd -WithFold`、macOS `MD20_WITH_FOLD=1`：主程式裝完接著裝摺疊；失敗不影響 MD20 本身。
- GUI「電腦狀態」頁的摺疊列多一個「一鍵安裝」：背景執行同一個指令，日誌寫到 `MD20_Projects/_tools/setup-fold.log`，頁面每 2 秒顯示最後 12 行；同類安裝同時只跑一個。缺工具時的警告與 `no_engine` 閘門文字改為指向這個按鈕。
- 不放進預設安裝：數 GB 且要 20–60 分鐘，沒有要用胜肽的學生不需要。
### 8.4 驗證狀態
- 純 Python 測試：`tests/test_peptide_input.py`（辨識、自動命名、歧義擋下、預設勾選、安裝按鈕的背景執行）。
- **未驗證**：Windows 筆電上 `Install-Folding.cmd` 實際安裝與 GPU 試摺（a10 修好安裝後尚未重跑）；macOS 未測。

