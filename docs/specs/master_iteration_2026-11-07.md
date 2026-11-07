# 整合規格（Master Iteration Prompt 2026-11-06 版）複核、盤點與本輪增量

來源：使用者 2026-11-07 09:39 提供的 `MD20_Claude_Code_Master_Iteration_Prompt_EN.md`（631 行，取代先前片段）。
本檔是該規格在本 repo 的落地紀錄：A1–A12 逐項複核、F01–F19 盤點、本輪實作範圍、驗收對照與後續計畫。
決策理由同步寫在 `docs/DECISIONS.md` D-96 起。

## 0. 檢查基準（§2.1）
- repo：`/home/claude/md20-workstation`（session_016gcJzASwmZ7ZUPX5BewTyo 的 clone），分支 `main`，開工時 HEAD `aea9c06`（docs）／程式最後一個 commit `5561dd7`（D-94）；工作樹乾淨。規格的審查基準 `d879f2b` 之後只多了 D-94（GUI 3D 分頁）與文件，與 A1–A12 涉及的檔案無關，所以規格裡的行號大致仍可用。
- 執行環境：開發容器 Python 3.13、numpy 2.5、scipy 1.18、matplotlib 3.11；**沒有** OpenMM、RDKit、mdtraj、pymbar、NiceGUI（CLAUDE.md 硬限制）。凡是要 mdtraj 的路徑只能交給 CI `openmm-stack`。
- 研究資料：參考報告 `Molecular Simulation Project Report · hsieh2024_rela_1vkx.pdf`（67 頁、75 圖）與原始軌跡都**不在**容器內（在使用者筆電）。本輪**沒有**重新分析原始案例；所有新測試用合成資料（fixtures），不代表已重現該報告。依使用者指示不把研究資料傳到容器。
- 基線測試：`python3 -m pytest -o addopts="" -q` → 635 passed、48 skipped（skip 皆為容器缺套件的整合測試）。

## 1. A1–A12 複核表

分類：**確認缺陷**／**已修正**／**方法限制**（不是 bug，但必須在結論層擋住）／**證據不足**。行號為 `5561dd7`。

| ID | 本地位置 | 觀察到的行為 | 分類 | 影響 | 本輪處理 |
|---|---|---|---|---|---|
| A1 | `sampling/binding.py:797`（`BindingResult(status="PASS")`）、`:877–906`（只擋 ΔG°）；`workflow.py:1704`（results 只帶 status 與數值）；`sampling/multi.py:128–187` `compare_binding` | 只要算完就 `PASS`；品質不足時只撤 ΔG°、ΔPMF 照留；比較只看 `status=="PASS"` 與數值存在，ΔG° 缺就改用 −ΔPMF 排名，產生「參考（最強）」「弱於參考」 | **確認缺陷** | 重疊圖不連通、PMF 未持平的結果仍被排名並標「最強」 | **已修**：執行狀態／科學評估／比較資格分開（`sampling/assessment.py`）；比較只用合格者；ΔPMF 只做「路徑特定」描述；舊資料標「待重新分析」 |
| A2 | `report/figure_text.py:506` `classify_umbrella`、`:1169` `classify_overlap`、`:1195` `classify_convergence` | 池化直方圖無缺口→「整條路徑分布重疊、剖面連續」；相鄰最小重疊 < 0.05 →「剖面在此斷開」；最後兩個累積估計差 ≤ 2 →「自由能已收束」 | **確認缺陷** | 三個局部檢查各自宣告整體結論，互相矛盾 | **已修**：單一 Assessment 物件（每項診斷：方法、範圍、門檻來源、版本）；三個圖說改讀 Assessment，局部通過只說局部，矛盾明講；三個反例測試 |
| A3 | `build/structure_gate.py:68–92`；`report/interpret.py:16–37` | 解析度 2.5–3.2 Å、R-free 0.28–0.32、缺 EXPDTA、NMR 都標 `AUTO_FIXED`，摘要說「已自動修正」；英文「Below 2.5 Å resolution」方向反了（數值大＝解析度差） | **確認缺陷** | 讓人以為結構限制已消失 | **已修**：這四種改為 `PASS` + `limitation`（接受的限制、原因、政策），只有帶 `diff` 的才算修正；舊紀錄中沒有 diff 的 AUTO_FIXED 在報告計為限制；四語用詞改為「比 2.5 Å 差（數值較大）」 |
| A4 | `analysis/traj.py:145,178`（`stays_bound` = 末 20% RMSD < 3 Å，參考為第一個 production 幀）；`figure_text.py:248` `classify_rmsd`（apo/holo 差 0.3 Å →「配體讓蛋白更穩定」；< 2 Å 平台→「已平衡」） | 單一 RMSD 門檻同時決定「仍結合」、「穩定」、「平衡」 | **確認缺陷** | 過度解讀 | **部分修**：新增 `ligand_state`（姿勢保留／姿勢改變但留在口袋／有離開證據／未知；結合接觸與 COM），寫明 RMSD 參考是第一個 production 幀；apo/holo 與「已平衡」的圖說改為描述性。`stays_bound` 欄位保留（相容）但報告不再用它下結論。約束實際出力的時間比例**未做**（需要 production 期間的力紀錄） |
| A5 | `report/chem.py:66–85` `pose_contacts`；`analysis/extended.py:283–316` fingerprint、`:318–333` water bridges | 配體任何 N/O 靠近帶電殘基原子＝ionic（不看配體官能基電荷）；靜態 N/O ≤ 3.5 Å＝hbond；指紋只保留一個「最強」類別（ionic > polar > hydrophobic）；沒有水時 water bridge 輸出全 0 | **確認缺陷** | 同號電荷被叫鹽橋；距離被叫氫鍵；並存互作被蓋掉；缺資料變成「0 個水橋」 | **已修**（分析層）：`analysis/interactions.py` 統一的化學判定（殘基質子化狀態決定蛋白電荷、配體電荷只接受原子層級的正負號，不知道就是 unknown）；鹽橋／同號接近／帶電接近（配體電荷未知）分開；距離只叫「極性接近」；多標籤；水資料缺→`unavailable`。`pose_contacts` 改用同一規則。**未做**：建模時把配體每個原子的形式電荷寫進 manifest（需 RDKit，交 CI 驗證）——在那之前配體電荷一律 unknown，所以不會出現任何配體鹽橋結論 |
| A6 | `analysis/traj.py:148–155`；`analysis/extended.py:293–295` | 只保留第一幀 1.2 nm 內的原子對 | **確認缺陷** | 後來形成的接觸永遠看不到，會假裝成接觸流失 | **已修**：`interactions.dynamic_pairs` 每個區塊（chunk）重新做完整鄰居搜尋（含三斜盒的最小映像），候選集合是所有幀的聯集；殘基鍵含 chain、resSeq、插入碼。`traj.compute_metrics` 與 fingerprint 改用它 |
| A7 | `docking/poses.py:129–146`；`workflow.py:828–840`、`:903` `_least_risk_joint_pose` | 無推薦時用最低風險 fallback；拒絕理由是自由文字，沒有區分「可修幾何」與「假設改變」 | **確認缺陷**（設計層） | fallback 可能繞過共同佔據假設的拒絕理由 | **已修（D-98）**：結構化 reason code（見 §5 第 1 項）；原文「未修（本輪延後）」保留於 git 歷史 |
| A8 | `sampling/binding.py::radial_pmf`；`sampling/multi.py::cooperativity` | 全域最小值即結合態；共同佔據系統裡拉不同配體的結果可互相排名；ΔPMF 差與循環閉合被當協同證據 | **方法限制＋確認缺陷** | 把路徑／anchor／旁觀配體相依的量當內在親和力 | **部分修**：multi 情境只輸出「特定共同佔據條件下的拉離結果」，不排名；共同佔據位移與協同性需雙方都通過評估，用語改為「條件差異，不是協同證據」；每個結果帶條件簽章（CV、anchor 來源、骨架約束、旁觀配體與保持限制、溫度），簽章不同不比較。結合／未結合盆地的事前定義、bulk 無接觸檢查、標準態校正**未做**（漏斗約束規格仍是設計中） |
| A9 | `workflow.py:1660` `md_runs[i % len(md_runs)]`；`multi.py:295` 文字固定寫「MD 起點都不同」 | SMD replica 數 > MD replica 數時循環重用同一個 MD 終點，但文字仍宣稱獨立起點；research tier 的「≥ 3 replica」也用 SMD 數 | **確認缺陷** | 三個 SMD 種子被當三個獨立平衡起點 | **已修**：每個 replica 記錄 `md_run_id`、seed、起點檔；彙總分開「共用起點的隨機拉離次數」與「獨立 MD 起點數」；文字依實際情況；tier 規則改看獨立起點數 |
| A10 | `report/workflow_report.py:1385–1389`（`key[:10]`）、`:1389–1390`（decisions 只用 stage 前綴過濾）；`util/decisions.py`（無 workflow 欄位） | 同一專案多個流程的決策混在一起；重點摘要截前 10 條 | **確認缺陷** | 出處污染；後來的嚴重 PMF 問題可能被截掉 | **已修**：DecisionLog 寫入帶 `workflow`；報告只取本流程，舊紀錄（無歸屬）另列「歸屬不明」而不猜；摘要去重後 caution 全部保留，其他依序補到 10 條 |
| A11 | `analysis/extended.py` PCA/cluster；`figure_text.py:1049` `classify_pca`、`:1073` `classify_clusters`、`:1095` `classify_dccm` | 各系統各自做 PCA；短軌跡投影密度叫自由能地形 | **方法限制** | 跨系統不可比；密度≠熱力學 FEL | **未修**（下一輪 F12）：需要共同基底與代表結構連結 |
| A12 | `analysis/extended.py:27` `frame_indices`（MAX_FRAMES 250） | 昂貴分析共用抽幀；目前**沒有**任何事件持續時間估計使用它 | **方法限制**（擴充風險，不是現有錯誤） | 若新持續性分析沿用抽幀會漏掉短暫中斷 | **已處理於新分析**：F09 持續性用自己的節奏契約（讀儲存幀、不吃顯示抽幀、replica 不串接、稀疏資料給限制）；既有抽幀預設**不改**（沒有回歸測試前不動） |

## 2. F01–F19 盤點（§6）

分類：**有**／**有但科學上不完整**／**有但整合差**／**缺**。

| ID | 現況 | 分類 | 位置／說明 |
|---|---|---|---|
| F01 研究設計與證據覆蓋矩陣 | 報告有流程與設定，沒有「預定 vs 實際執行 vs 證據缺口」矩陣 | 缺 | 下一輪 |
| F02 化合物清單、描述子、實測豐度 | 有 Lipinski／化學空間圖（`properties_plot`、`chem_space_plot`）；豐度沒進流程 | 有但不完整 | 豐度屬 P3 |
| F03 多尺度標靶解剖 | 有離線 3D viewer（全蛋白＋配體），沒有 domain／鏈／DNA 註記層 | 有但不完整 | `gui/static/md20view.js` |
| F04 對接穩健性與姿勢家族 | 有姿勢相似度、漏斗、位置圖（D-59） | 有但不完整 | 單次搜尋的 9 個 pose 未與獨立種子分開 |
| F05 跨候選證據／可比性矩陣 | 比較表帶資格與不比較理由（D-96）；候選 × 候選的可比性矩陣（每格等級與原因）在報告研究設計節（D-120） | **已實作・純 Python** | `report/comparability.py`；等級沿用 `compare_binding`（`multi.context_basis`）；MD 設定差異只列提醒（真實 binding 結果的報告渲染待 CI／筆電） |
| F06 同步配體狀態時間線 | RMSD、接觸數、COM 分開畫 | 有但整合差 | 本輪：`ligand_state` 分段（資料層） |
| F07 初始接觸保留 vs 新接觸 | 缺；而且 A6 讓新接觸看不到 | 缺 | 本輪：`interactions.initial_vs_new` |
| F08 化學正確的互作熱圖／條碼 | `fingerprint_plot` 有，但 A5 定義錯、單一類別 | 有但不完整 | 本輪：多標籤指紋（資料層＋圖例） |
| F09 互作持續性 | 缺（只有佔有率） | 缺 | 本輪：`analysis/persistence.py`（事件表、設限、存活估計、節奏契約） |
| F10 apo–holo 配對差異 | `compare_runs` 有 ΔRMSF 前 10 名，條件可比性未檢查 | 有但不完整 | 下一輪 |
| F11 口袋幾何與水合 | 有配體 SASA／埋藏率；口袋體積、水合事件缺 | 缺 | 下一輪 |
| F12 共同基底構形探索與代表結構 | PCA、地形、分群與時間線有，各系統各自基底，代表結構未連結 | 有但不完整 | 下一輪 |
| F13 SMD 路徑與接觸釋放 | 有力／功曲線；D-116 加沿路徑稀疏座標（`smd_path.npz`）、接觸釋放點與峰值時斷開的接觸、報告圖與表 | 已實作・待 CI | D-116；真實拓撲路徑待 CI，詳見 `smd_contacts.md` |
| F14 取樣品質與合格 PMF | 有覆蓋、重疊矩陣、半分、累積圖 | 有但不完整（A2） | 本輪：Assessment 統一判斷 |
| F15 replica 與 protocol 敏感度 | 有 replica 彙總 | 有但不完整（A9） | 本輪修 replica 階層語意 |
| F16 單／雙／多配體情境比較 | 有共同佔據位移與協同循環 | 有但不完整（A8） | 本輪：條件簽章與不排名 |
| F17 自動行動效益與資源 | 有 refine 紀錄（窗口補採樣輪次） | 有但整合差 | 下一輪（P1A） |
| F18 實驗回饋 | 缺 | 缺 | P3，需外部資料 |
| F19 MM/GBSA／MM/PBSA | 缺 | 缺 | P2B；本輪不做（見 §5） |

## 2b. 第二批（D-97）落地摘要
A5/A6/F07/F08/F09/A4/A12 已實作（純 Python，容器可測；真實 mdtraj 路徑交 CI）：
- `md20/analysis/interactions.py`：統一化學判定（鹽橋需電荷相反、同號接近、配體電荷未知→不判鹽橋、極性接近只看距離不叫氫鍵、多標籤並存）、完整動態鄰居搜尋（每幀最小映像、含三斜盒、候選集合為全幀聯集）、chain-aware 殘基鍵、`initial_vs_new`、`legacy_matrix` 後備、`water_unavailable`。
- `md20/analysis/persistence.py`：事件表、連續／間歇（物理時間允許中斷）、左右設限、Kaplan–Meier（右設限；左設限排除並計數）、節奏契約（稀疏→limited、事件不足→不給壽命）、replica 不串接、斷點不橋接。
- `md20/analysis/extended.py`：fingerprint 改用上述模組（schema `md20.fingerprint/2`，多標籤、持續性、initial_vs_new），water bridges 缺水→`unavailable`。
- `md20/analysis/traj.py`：`compute_metrics` 動態接觸、`ligand_state`（A4，接觸＋COM＋RMSD，約束如實標註，RMSD 參考＝第一個 production 幀）。
- `md20/report/chem.py`：`pose_contacts` 同一化學層、用分子形式電荷。
- 報告：多通道指紋圖、持續性表、initial-vs-new、缺水「無法進行」行；`interpret.md` 的配體狀態與 RMSD 圖說改為描述性（A4）。

## 3. 本輪實作（P0 增量）

### 3.1 科學評估（`md20/sampling/assessment.py`，新檔）
- `assess_pmf(pmf, *, n_replicas, md_run_ids, thresholds)` → `{"schema", "thresholds_version", "diagnostics": [...], "sampling_adequate", "conflicts", "eligibility", "reasons"}`。
- 每項診斷：`id`、`method`、`scope`（local／global）、`status`（pass／fail／unknown）、`value`、`threshold`、`threshold_source`。
  - `histogram_coverage`（池化直方圖連續；local）
  - `adjacent_overlap_min`（相鄰窗口最小重疊；local，**不**決定連通性）
  - `overlap_graph`（全部窗口對的重疊圖是否連通；global；優先用 MBAR 品質報告的 `graph_connected`，否則用直方圖重疊矩陣）
  - `mbar_overlap`（D-113；MBAR 估計器 overlap matrix 的全窗口對連通性，邊 ≥ 0.03；WHAM 估計沒有矩陣 → unknown 但**不擋**；有矩陣且不連通 → 擋 path-specific 與 ΔG°；與 `overlap_graph` 結論不同時列為 conflict）
  - `window_ess`（每窗口時間相關有效樣本數最小值；與 MBAR 權重 ESS 不同，名稱寫明）
  - `solver`（MBAR／WHAM 是否收斂）
  - `half_split`（前後半 ΔPMF 差）
  - `cumulative_drift`（25／50／75／100% 估計：|ΔPMF(f) − ΔPMF(100%)| 的最大值，f ≥ 50%）
  - `endpoint_plateau`（末端持平）
  - `range_coverage`（PMF 是否涵蓋取樣範圍）
- 缺欄位一律 `unknown`，**不視為通過**。
- 資格：`delta_pmf_curve`（診斷曲線永遠可顯示）、`delta_pmf_path_specific`（所有必要診斷 pass）、`dG_standard`（再加上 ΔG° 沒被撤回）、`affinity_ranking`（只有 ΔG° 合格才可能）。
- 門檻集中在 `THRESHOLDS`（帶版本 `2026-11-07.2`（D-113 新增 `mbar_overlap_edge_min`；原為 `2026-11-07.1`） 與每項來源說明），可由 config 覆寫；不是普遍定律。

### 3.2 比較（`sampling/multi.py`）
- `compare_binding`：只用 `assessment.eligibility` 合格者；舊結果沒有 assessment →「待重新分析」；單獨情境：ΔG° 全部合格才做 ΔΔG°，否則 ΔPMF 只在路徑特定合格且條件簽章一致時列順序，用語「沿各自拉離路徑的井深較深／較淺，不是內在親和力」，不出現「最強」；multi 情境一律 `DESCRIPTIVE`（列值，不排名）。
- 共同佔據位移、協同循環：雙方都要路徑特定合格且條件一致；用語不再說「可能有協同或互斥」。

### 3.3 replica 語意（`workflow.py`、`multi.aggregate_binding_replicas`）
- 每個 replica 記錄 `md_run_id`、`seed`、起點檔；`n_independent_md_starts` = 不同 `md_run_id` 的數目。
- 文字：全部獨立／部分共用起點／全部共用起點 三種說法；tier 的 replica 下限看獨立起點數。

### 3.4 結構限制（A3）
- `Gate` 加 `limitation` 欄位；解析度、R-free、EXPDTA、NMR 改為 `PASS` + `limitation`。
- `interpret.structure`：分開數「通過」「真正修正（有 diff）」「接受的限制」「需要決定」。

### 3.5 互作化學與動態接觸（A5/A6，`md20/analysis/interactions.py`，新檔）
- `residue_charge_sign(resname, atom)`：依殘基名稱判斷質子化狀態（ASP/GLU −，ASH/GLH 0；LYS +，LYN 0；ARG +；HIP +，HIS/HID/HIE 0）。
- 配體電荷：只接受 `{原子索引: ±1}`；沒有就是 unknown。
- `dynamic_pairs(xyz, box, A, B, cutoff, chunk)`：每個 chunk 做完整搜尋（最小映像，含三斜盒），回傳所有幀中曾進入 cutoff 的原子對聯集，以及逐幀距離。
- `classify_frame_contacts(...)` 多標籤：`salt_bridge`、`like_charge_proximity`、`charged_proximity_unknown_ligand_charge`、`polar_proximity`、`hydrophobic`；`hbond` 只在有幾何判定（Wernet–Nilsson，含 H）時才給。
- 水：沒有水座標→`{"status": "unavailable"}`。
- 殘基鍵：`chain:resname:resSeq[icode]`。

### 3.6 互作持續性（F09，`md20/analysis/persistence.py`，新檔）
- 輸入：一個 run 的布林序列＋每幀實際時間（ps）＋ `run_id`、`segment_id`（真正的軌跡斷點）；不吃顯示抽幀。
- 連續事件；間歇事件＝允許中斷 ≤ `max_gap_ps`（物理時間）；左邊界（起點就存在，onset 未知）、右設限（結束時仍存在）。
- 輸出事件表（run、起訖幀與時間、長度、中斷、邊界旗標）、時間加權佔有率、事件長度分布、Kaplan–Meier 存活（右設限；左設限事件另計並標明處理方式）。
- 節奏契約：儲存間隔 > 允許中斷→`limited`（短暫中斷無法分辨，事件長度是上限）；可辨識的最大延遲＝觀察窗；事件數 < 5 或觀察窗不足 → 不擬合壽命（`lifetime: unavailable`）。
- 不同 run 絕不串接；chunk 邊界不切斷事件。
- 明文：接觸持續性不是配體滯留時間、不是 koff。

## 4. 驗收對照（§11）
本輪新增測試對應：Test 1、2、3（assessment）；4 的高 RMSD 但接觸保留、anchor 改變不影響狀態判定（ligand_state 只用接觸與口袋，不用絕對距離）；5、6（interactions）；7（replica）；9 的四語一致（圖說讀同一個 Assessment）；10（決策紀錄分流程）；14 的解析度不算修正；19 的缺水資料→unavailable；25、36（persistence）。
未涵蓋：8、11、12、13、15–18、20–24、26–35（見 §5）。

## 5. 未做與下一步（精確）
1. **【已做，D-98】A7 reason code**：`docking/poses._rejections` 回傳 `(code, text)`；code 分 `geometry_repairable`／`model_limitation`／`hypothesis_change`；`_least_risk_joint_pose` 只接受全部 `geometry_repairable`；報告保留原始拒絕理由與修復後評估。測試：共同佔據拒絕不可被 fallback 清除。
2. **【已做，D-98；實作與原文不同：SDF 順序的 `atom_formal_charges`／`atom_charge_signs`（共振聯集），在 workflow 以 `atom_indices` 對應，長度不符即未知】配體原子形式電荷進 manifest**：`build/ligand.py` 在 `ref` 已映射到拓撲時寫 `charged_atoms: {topology_index: sign}`；需 RDKit，CI `openmm-stack` 驗證；之後鹽橋才會出現在配體上。
3. **【已做，D-97；11/07 第四個 session 複核】報告整合**：把 `persistence` 事件表與 `ligand_state` 接進 `workflow_report._md` 的配體段（條碼＋持續性＋時間對應結構）；目前資料層已寫入 `extended.json`／`metrics.json`，圖未接。
4. **【F12/F10 已做 D-106；F01 已做 D-108】F12/F10/F11**、**F01/F05 證據矩陣**、**P1A 自動行動迴圈**（偵測窗口 ESS 不足→延長 vs 重疊不足→補窗，已有 adaptive.py 可接）。
5. **F19 MM/GBSA pilot（P2B）**：先決條件——①選定後端（OpenMM GBn2 單軌跡，因為 D-20 已有 GBn2 且不需轉檔，保留 OpenFF 參數）；②小型可獨立驗證的基準（需要 OpenMM，容器無法執行）；③使用者授權計算預算。本輪未開始，也未宣稱任何能量驗證。
6. 本輪所有 mdtraj 路徑（`traj.compute_metrics`、`extended_metrics` 的新接觸）**只在 CI 能測**；commit 未 push，因此尚未驗證。
