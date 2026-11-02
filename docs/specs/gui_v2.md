# GUI v2：快速版／專業版＋合理性檢查（設計中，2026-11-02）

狀態：**[設計中，原型審查]**。互動原型：https://claude.ai/artifact/JpJC545W7D8CnbuvUDf9q8（artboard「v2 Workbench」）。
取代 `docs/specs/gui.md` 的頁面結構；後端（workflow、閘門、DecisionLog）不變。

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
