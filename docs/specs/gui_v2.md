# GUI v2：快速版／專業版＋合理性檢查（設計中，2026-11-02）

狀態：**[設計中，原型審查]**。互動原型：https://claude.ai/artifact/JpJC545W7D8CnbuvUDf9q8（artboard「v2 Workbench」）。
取代 `docs/archive/specs/gui.md` 的頁面結構；後端（workflow、閘門、DecisionLog）不變。
> **2026-11-03 更新**：已實作並隨 **v0.1.0a3** 發行（D-50–D-52、D-54、D-67、D-68）。CI 每頁兩種語言渲染截圖；筆電實際操作過教學模式一、語言切換（不再重跑）與資源用量選單。完整互動清單見 `docs/archive/LAPTOP_SESSION.md`，尚未逐項確認。

## 使用者回饋（2026-11-02 14:27／14:30，原文要點）
- 不能調 minimize／NVT／NPT 的步長、溫度梯度、約束參數；高通量、pose 選擇、多配體對接等詳細參數都看不到。舊版自由度大、報告圖表多，這版太少。
- 介面「很 AI、不專業」。
- **不分教學版**：只要「快速版」與「專業版」。專業版所有參數可調，系統要聰明地預估／判斷使用者參數是否不合理。

## 決定
1. **兩種模式**（取代 classroom／teaching／research 作為 UI 概念；tier 仍是後端預設表）：
   - 快速版：只填受體、配體、對接位置、要算什麼（MD／MD＋結合自由能）；其餘由系統決定，顯示「系統選用」與預估時間；一鍵切到專業版檢視同一組參數。
   - 專業版：左側設定樹（受體、配體、對接與 pose、高通量篩選、MD protocol、結合自由能、報告與輸出；結果、決策日誌），中間參數表，右側**合理性檢查**面板。
2. **專業版參數全開**，直接對應 config 鍵：`docking.*`（mode independent/simultaneous、scoring、exhaustiveness、n_poses、seed、redock、box 來源／center／size）、
   `pose_choices`（pose 表單選）、`docking.pose_md_screen.*`、`screen.*`（library、filters、top_n、next_mode、protonation、allow_partial…）、
   `md.*`（溶劑、盒形、padding、離子強度、HMR、replicas、`restraints`）、**每個 stage 的長度／dt／溫度起訖與 ramp／壓力／摩擦／各約束組起訖倍率／記錄間隔**（寫入 `md.stage_overrides`）、
   `binding.config.*`（BindingConfig 全欄位）、報告輸出項目勾選。
3. **合理性檢查**（即時、規則表、依物理與數值條件，不依 tier）：三級「錯誤（擋下執行）／警告（可執行，寫入報告）／自動修正（系統將改的值與代價）」＋提示。
   初版規則：dt > 2 fs 且無 HMR → 錯誤；dt > 4 fs → 錯誤；NVT < 50 ps、NPT < 200 ps、production < 2 ns → 警告；padding < 0.6 nm → 錯誤；
   結合計算時 padding < pull_distance + 0.5 nm → 自動修正（列出原子數增加）；pull_velocity > 0.005 nm/ps → 警告；window < 500 ps → 警告（ΔG° 不輸出，引 D-40）；
   exhaustiveness < 8 → 警告、> 64 → 提示；hold_backbone → 提示（RMSD 受約束）；總預估 > 24 h → 提示。預估時間用本機 doctor 速度與盒子大小換算。
   後端在 `pipeline run` 前用同一規則表驗證（同一份程式，GUI 與 CLI 一致）。
4. **視覺**：工程軟體風格——中性灰底、1 px 邊框、緊湊 30 px 列高、等寬數字、單一強調色 #0b5cad、狀態用小方標籤；不用大圓角卡片、漸層、表情符號。
5. **報告**：12 類圖表逐項可選（T/E/ρ 時間序列、最小化、RMSD、RMSF apo vs holo、Rg、配體口袋 RMSD、接觸頻率、氫鍵／疏水佔有率、SMD 力與功、window 直方圖、PMF（MBAR/WHAM）、覆蓋與補窗紀錄）＋決策日誌、CSV、DCD、config／protocol hash。

## 待使用者確認
- 原型上的參數分組與命名（用 config 鍵名還是中文名、或兩者並列）。
- 合理性規則的門檻值。
- 舊版（Colab v6.1）有、這版沒有的圖表清單——請使用者列出，補進第 5 點。

## 第二輪回饋（2026-11-02 14:37–14:42）與處理
- 不顯示實驗室戳記；不過度縮寫（bb、sc、T、γ 等改為完整中文名稱與單位）；介面文字不使用「/」分隔；用語去除 AI 感。
- **通用化**：介面不得預設任何特定蛋白或配體。範例資料只出現在明確標示「範例」的結果頁。「共晶殘基代碼」欄位附說明（例：3PTB 中苯甲脒的代碼 BEN）。
- **高通量篩選**：
  1. 提供範例 Excel 檔下載（欄位：name 必填；smiles、pubchem_cid、inchikey、chembl_id、ccd、sdf 擇一），使用者貼上後上傳。
  2. 自動下載失敗（網路阻擋、資料庫無 3D）時，列出待補件化合物，提供手動上傳；也接受放入專案的 `library_inbox` 資料夾。
  3. 命名規則：檔名必須等於 name，副檔名 .sdf 或 .mol2；名稱只允許英數、底線、連字號，64 字元內，不分大小寫亦不可重複。違反規則的檔案不收、並說明原因。
  4. 篩選結果輸出排序長條圖（含最佳分數減 1.0 kcal mol⁻¹ 的誤差線）、分數對重原子數散佈圖、分數分佈、口袋接觸熱圖；長條可直接點選加入或移出下一步。
- **流程銜接**：篩選結果 → 以已選化合物正式對接 → 姿勢選擇（推薦與人工改選）→ 確認後**詢問是否進入分子動力學**（列出系統、預估時間、之後的步驟）→ 分子動力學完成後再詢問是否計算結合自由能。
- 後端待辦：`library_inbox` 掃描與命名規則檢查、範例檔加說明工作表、篩選圖表（散佈、分佈、熱圖）、各步驟之間的確認閘門。


## 第三輪（11/02 15:04–15:14）與實作（D-51）
- 模式改為四種：教學模式一（多種小分子，hsieh2024）、教學模式二（胜肽，hsieh2025）、快速、專業；教學模式使用快速模式參數。
- 專業模式依個案給建議初始值（`md20/advisor.py`，D-49），所有入口共用；介面與報告雙語，英文預設。
- 頁面：`/`、`/teach/{case}`、`/new/quick`、`/new/pro`、`/wf/{project}/{name}`、`/system`、`/template/compound_library.xlsx`。
- 實作檔：`md20/gui/pages_v2.py`（頁面）、`md20/gui/content.py`（文字與教學內容）、`md20/gui/logic.py::config_from_mode`。

## D-80 整合：膜系統、胜肽摺疊、長時間模擬接上流程與介面（2026-11-03，實作，待 CI 與筆電）
狀態：**[已實作，純 Python 測試通過；NiceGUI 頁面只在 CI `gui-preview` 與 `test_gui_server.py` 執行]**。

### 流程（`md20/workflow.py`，增量修改）
- 情境 B（`md.membrane.type: surface`）與 C（`bilayer`）：`Workflow._run` 一開始就轉到 `_run_membrane_only`，
  不取受體、不對接，沿用既有步驟鍵 `md_cases → md_runs → analysis → binding → report`（沒有新增 phase）。
  `build_membrane_cases`：surface 每個溶質一個系統（鍵 `surface_<名稱>`），bilayer 一個系統（鍵 `bilayer`），
  以 `membrane.build_membrane_system(ligands=...)` 建模；胜肽用 `prepare_peptide`（設了 `fold` 時起始構形取預測結構），
  小分子用 `prepare_ligand`（由 SMILES 產生構形）。建好後把 assemble 的紀錄另存一份在 build_manifest 的 `assembly`，
  讓所有讀取端（manifest_ligands、閘門卡片、長時間規劃）和一般流程一樣。
- 擋下（閘門 `membrane type`，NEEDS_HUMAN）：B 或 C 卻有受體、surface 沒有配體、bilayer 有配體、`fold: complex`（沒有受體可疊合）。
  不猜「受體是不是要放進膜」。GUI 建立 B、C 時會自己把受體拿掉，並在合理性檢查顯示「不會放入受體」。
- 膜系統的結合自由能仍由 `membrane binding` 擋下；GUI 在膜系統開著結合計算時列為錯誤，可一鍵關閉。
- `assess_equilibration`：要在 NPT 之後檢查並延長 NPT，必須在 engine 的 stage 之間停下來讀軌跡，等於新步驟；
  依開發規則**改成只在分析時執行**（`md20/analysis/membrane_run.py`）：以正式模擬後半段計算面積、P–P 厚度、核心水，
  `attempt=1`（不會說「延長一次」）。通過記 PASS；不通過記為提醒卡片（AUTO_FIXED、advisory，存在 `state["advisories"]`），
  因為模擬已經跑完，擋下只會讓報告出不來。只存溶質的軌跡沒有水，驗收寫「未檢查」。情境 A 在一般分析之後加做膜分析；B、C 只做膜分析
  （沒有受體，主鏈 RMSD 與口袋接觸不適用），`metrics.json` 只有 `membrane` 區塊，不做系統比較圖。
  報告用的資料另以 `analysis/membrane_report.membrane_report_data`（報告端的格式）寫成 `analysis/membrane_report.json`，路徑放在 `analysis.summaries[系統]["membrane_file"]`。
- 順便修正：`_plan_long_run` 讀原子數時也看 `assembly`（`build_case` 的 manifest 只在 `assembly` 下有 `n_atoms`，
  原本 > 100 ns 的一般流程一定被「build 沒有原子數」擋下；`test_longrun.py` 的假 manifest 把數字放在最上層所以沒測出來）。
- `confirm_md` 的訊息：預測複合物的胜肽（score None）寫「預測複合物，沒有對接分數」，不再印出 `None kcal/mol`。
- `DECISION_KEYS` 加入 `("md", "membrane", "oriented")`（一鍵「結構已定向」的決定，重跑時保留）。

### 介面
- 新模組 `md20/gui/advanced.py`（純 Python）：選項表、四種語言文字、`apply_advanced`（寫入 `md.membrane`、`ligands[i].fold*`、
  `md.long_run_confirmed`）、`advanced_checks`（和 advisor.check 同格式，錯誤會擋下「建立並開始」；膜的組成、相、力場、擺放閘門
  直接呼叫 `membrane.plan_membrane`，顯示 `gate_text` 的四語標題與說明）、`long_run_view`、`tool_rows`、`setup_preview`、`score_text`、`selection_lines`。
- 專業模式：參數群組下方加「膜系統」（類型 none、protein、surface、bilayer；脂質組成預設；已定向；起始距離）與「胜肽摺疊」
  （off、預測後對接、預測複合物；工具 auto、omegafold、boltz、upload；受體序列可不填，多條鏈用冒號分開；上傳預測結構）。
  `/new/pro?expand=all` 打開所有群組（截圖用）。
- 長時間模擬：正式模擬 > 100 ns 時右欄顯示規劃（天數、硬碟、存檔間隔、幀數與分段、續跑檔保留數，取自 `advisor.long_run_plan`）；
  > 1 µs 顯示確認勾選，勾了寫 `md.long_run_confirmed: true`，沒勾是警告（流程會在正式模擬前停下來問）。估計以水盒中的蛋白計算，卡片上註明。
- 快速模式：配體欄裡每個胜肽旁邊一個「先摺疊這個胜肽」勾選（`fold: true`，只對勾選的胜肽）。
  D-85：配體欄可直接貼序列（不用 `peptide:`），10 個殘基以上預設勾選；電腦狀態頁加「一鍵安裝」（背景執行 setup-fold --warmup / setup-cg）。見 `structure_prediction.md` §8。
- 電腦狀態頁「選用工具」：摺疊環境與粗粒化工具是否安裝、完整安裝指令（Windows `%LOCALAPPDATA%\MD20\md20.cmd setup-fold --engine omegafold --yes`、
  `... setup-cg --yes`；macOS `~/MD20/md20`），「顯示安裝計畫（不安裝）」按鈕只呼叫 `fold.setup_plan` 與 `martini.install_plan` 列出指令，不執行任何程式。
- 閘門一鍵（`actions.py`）：`fold`、`fold confidence`、`fold placement`（不摺疊、仍使用、改用對接、改用指定工具、輸入工具名或受體序列）；
  `membrane orientation`（已定向）、`membrane phase`（溫度、改預設組成）、`membrane force field`、`membrane composition`（預設名稱或 `{脂質: 比例}`；
  `gram_positive` 不給按鈕）、`membrane surface placement`（距離、方向）；`membrane binding` 用既有的「binding.enabled: false」。
  安裝工具、上傳結構、改膜系統類型、模板資料夾、OPM 下載維持文字。`STEP_ORDER` 加入 `fold`（在 docking 前），一鍵後從 fold 起重跑。
- 姿勢表：預測複合物放置的胜肽列出一列，分數欄寫「預測複合物，沒有對接分數」（四種語言），點選不會改姿勢；確認進入 MD 的卡片逐條列出選用的姿勢。
- 測試：`tests/test_gui_advanced.py`、`tests/test_membrane_workflow.py`；`tools/gui_preview.py` 另存 `05b_pro_membrane_fold`、`05c_pro_long_run`、`07b_system_tools`（失敗只印出，不影響穩定性檢查）。

### 未決
- 長時間估計對膜系統的原子數（3–12 萬）不準；要不要在膜系統改用膜的原子數估計。
- 膜表面系統一個溶質一個系統；多個胜肽同時在膜上（聚集）沒有做。
- 情境 B、C 的報告內容（`metrics.json` 的 `membrane` 區塊、`membrane_metrics.json`）要由報告端接上（md20/report 屬其他 session）。
