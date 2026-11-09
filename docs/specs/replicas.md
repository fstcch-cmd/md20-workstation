# 獨立重複（replicas）：哪些分析需要、需要幾條、報告怎麼呈現不確定性

狀態：**§3–§5（重複計畫與開始前告知）已實作（D-131，待 CI）；§2 的分析彙總與報告已實作（D-130 重做，§7，待 CI；D-142 補完 §2 表其餘項目的跨重複彙總，見 §8）。** 規格 D-129，2026-11-07。 使用者 22:51 授權：「根據每一個分析思考哪些需要重複、哪些不需要；需要重複的取最大值，在一開始模擬時就告訴使用者會多花時間，確保報告完整。」

## 1. 缺口（查到的事實）
- `Workflow.analyse()` 只讀 `r["run_ids"][0]`：RMSD、RMSF、接觸、指紋、持續性、PCA／地形、DCCM、tICA／MSM、水合、膜指標、系統比較（D-106 共同基底、ΔRMSF）全部只看**第一條**軌跡；其餘重複跑了卻沒有進報告。
- 只有結合自由能已經跨重複彙總（D-96／A9：每個重複都要合格才算、research 要 ≥ 3 個獨立 MD 起點）。

## 2. 每個分析的判斷
原則：**結論是「這個系統平均來說怎樣」或「兩個系統哪裡不同」的，需要重複**（單一軌跡只是一次抽樣，看不出是系統的性質還是這一次的偶然）；**每條軌跡各自的品質檢查、或本來就不是取樣結果的，不需要重複**（逐條檢查，不平均）。

| 分析 | 需要重複？ | 最少條數 | 報告呈現 |
|---|---|---|---|
| 主鏈 RMSD、Rg、蛋白 SASA（平穩值與趨勢） | 是 | 3 | 每條一條線疊圖；平穩值 mean ± SD；各條不一致時標註 |
| RMSF（每殘基） | 是 | 3 | mean ± SD 色帶 |
| apo–複合物 ΔRMSF | 是（兩邊各 3） | 3 | 每殘基差值 ± 95% CI（t 分布，n−1）；CI 不含 0 才稱「不同」，並註明多重比較 |
| 配體 RMSD／配體狀態（留在口袋、漂移、離開） | 是 | 3 | 「n 條中 k 條留在口袋」，不用單一軌跡下結論 |
| 接觸、互作指紋、氫鍵、水橋、持續性（壽命） | 是 | 3 | 頻率 mean ± SD；「持續存在」需在多數重複成立並列出 k／n；壽命合併事件後估計並標註來自幾條 |
| 水合位點佔有率 | 是 | 3 | mean ± SD；只在單一重複出現的位點標「未重現」 |
| DSSP 二級結構比例 | 是 | 3 | mean ± SD |
| PCA／自由能地形／分群／共同基底低谷佔比 | 是 | 3 | 所有重複放在同一組軸；每條各自的低谷佔比與 mean ± SD；各條不一致 → 「取樣分布、未收斂」 |
| DCCM | 是 | 3 | 平均矩陣；只標出各重複一致的相關 |
| tICA／MSM | 是（各條各自檢查資格） | 3 | **不合併軌跡成速率**（D-142 更正：原寫「合併」）；每條各自資格（D-105），報「n 條中 k 條合格」；單一軌跡永不報速率 |
| 膜面積、厚度、序參數 | 是 | 3 | mean ± SD |
| 結合 ΔPMF／ΔG°（SMD＋傘狀採樣） | 是（既有 D-96） | 3（research） | 維持現狀 |
| 對接 | 否 | — | 本身是搜尋，另有 redocking 驗證 |
| 建模閘門、最小化、NVT／NPT 平衡驗收 | 否（逐條檢查） | — | 每條各自驗收；不合格的重複排除並寫原因，不平均 |
| PBC 置中、配體是否真的離開 | 否（逐條） | — | 每條各自列出 |
| 對接姿勢的靜態 2D 互作圖 | 否 | — | 靜態結構 |
| SMD 路徑接觸釋放（D-116） | 否（路徑描述） | — | 有多個結合重複時逐條列出，不平均 |
| 證據矩陣、可比性矩陣 | 否（彙整） | — | 改讀重複數與跨重複結果 |

## 3. 需要幾條：取最大值
- 需要重複的分析最少都要 **3 條**：3 是能算樣本標準差與 t 分布信賴區間的最小數（n = 3 時 t₀.₉₇₅ = 4.30，區間仍寬，報告照實寫）。常見做法見 Grossfield et al. 2018（LiveCoMS，模擬不確定性最佳實務）。
- 每個工作流程都會跑 RMSD、RMSF、接觸等需要重複的分析 → **所需條數 = 3**（所有等級，包括 classroom）。使用者可以在設定裡提高（例如 research 要 5）。

## 4. 一開始就告訴使用者（不新增步驟）
- 在既有的「開始前」位置（顧問建議、環境檢查的 ETA、GUI 開始按鈕前的確認卡片、CLI 開始時的訊息）顯示**重複計畫**：「為了讓報告能呈現不確定性，每個系統會跑 3 條獨立重複，計算時間約 ×3（依 benchmark 估計約 X 小時）。」
- 選項：
  - 照建議 3 條：預設。
  - 改成 1 條：報告每一處標「單一軌跡，無法估計不確定性」，比較結論降級為描述。
  - 自訂條數。
- 這是告知加預設值，不是 NEEDS_HUMAN 停下；使用者的選擇寫入決策紀錄。
- 已在跑或已完成、少於 3 條的舊專案：報告標明，並提供「補跑重複」選項（沿用既有的續跑機制），不重算已有的條。

## 5. 每條重複的獨立性
- 不同速度 seed，從同一個平衡後結構開始，或各自重新平衡（沿用既有 `run_replicas` 的做法，報告寫明是哪一種）。
- 只有完成且通過平衡驗收的重複才進彙總；少於 3 條時照實降級。

## 6. 實作（D-131）：重複計畫與開始前告知
- 純函式模組 `md20/engine/replica_plan.py`：`required_replicas()`（§2 表各列最少條數的最大值 = 3）、`DEFAULT_REPLICAS`（= 3，`make_protocol` 所有 tier、`example_config`、顧問建議值、論文驗證案例、`queue add`、GUI 表單預設都用它）、
  `configured_replicas(cfg)`（設定有寫 `md.replicas` 就照用，沒寫就 3；回傳是否明確設定）、`plan_replicas(cfg, benchmark=, n_atoms=, done=)`（所需條數、目前條數、倍數、ETA、seed、已完成條數、缺的條數、選項）、
  四語文字 `summary_text`／`line_text`／`independence_text`／`topup_text`、`lines()`（CLI）、`card_lines()`（GUI）。
- **時間**：有效能測試才給小時數（`md.ns_per_day` > 依原子數換算的 doctor benchmark > 不換算的 benchmark，後者註明「以測試系統大小計算」）；沒有就只給倍數，說「不猜時間」。只算分子動力學部分（SMD／傘狀採樣不隨重複數變）。
- **告知位置（都是既有位置，不停下）**：
  - CLI：`pipeline run` 在印出平台之後；`md.replicas` 沒寫 → 完整計畫（說明、seed、三個選項），有寫 → 一行。`run` 一開始印一行：該指令只跑 1 條，要 3 條請用 `pipeline run` 或 `queue add --replicas 3`（`run` 存的 protocol 也寫 `replicas=1`）。
  - GUI 流程頁：「開始或繼續」按鈕上方的「重複計畫」卡片（`gui/views.py::replica_card`）；一鍵按鈕：照建議／改為 1 條／（舊專案）補跑到 3 條，另有自訂條數輸入加「套用」。沒有 alert 或 confirm 對話框，只有 `ui.notify`。MD 確認卡片（`confirm_before_md`）多印一行目前的計畫。
  - 顧問：`replicas` 的建議值（3）與四語理由；`check()` 在條數少於 3 時給 info（發表等級為 warning）與一鍵套用的建議值 3。
  - 新建流程表單：既有的參數列與預估時間（`estimate_hours` 本來就乘上重複數）。
- **選擇的紀錄**：`Workflow.run_md` 開始時 `record_replica_plan()` 寫 DecisionLog（`workflow.replicas`，同一個選擇只寫一次；設定指定為 human、採預設為 auto）與 `state["replica_plan"]`；GUI 的選擇由 `gui/actions.py::set_replicas` 寫 `md.replicas` 並記 `gui.replicas`（human，含 patch）。`("md", "replicas")` 已加入 `workflow.DECISION_KEYS`。
- **補跑**：`run_md` 發現某系統已 COMPLETE 但條數少於 `md.replicas`，就沿用同一個 `replica_group` 呼叫 `run_replicas`，它從檔案判斷哪幾條 COMPLETE 並跳過，只新建缺的 `replica_index`；`set_replicas` 只丟掉 `analysis` 與 `report` 兩步，不動 `md_runs`、`binding`。測試：已有 1 條 → 補到 3 條，原本那條的 `run.json` 未被改動。
- **每條的獨立性（照 `run_replicas` 現況）**：第 i 條的 seed = 基礎 seed 2026 + 1000×i；每條從同一個建好的系統開始，各自做最小化、加熱與平衡，初速由自己的 seed 產生（不是從同一個平衡後結構分出去）。
- **限制**：粗粒化（`md.resolution: cg`）目前每個系統只跑 1 條，計畫卡片只告知這點，沒有選項；GUI 卡片在 NiceGUI 上的渲染要等 CI／筆電。

## 7. 實作（D-130 重做）：每一條重複都分析，跨重複彙總與報告
- **關係**：case → 獨立 MD 重複（`run_replicas`，各自 seed）→ 後代（SMD 拉動、傘狀採樣視窗）。只有第二層算「重複」；同一條母軌跡拉出的拉動與視窗只列在該重複底下，**不增加條數**。輸出 schema `md20.replica_set/1` 把這個關係與 `concatenation: never` 寫在檔案裡。
- **純函式模組 `md20/analysis/replica_set.py`**（只依賴 numpy）：
  - 每個觀測量先宣告 estimand，再彙總。每條重複先算出**一個數**（後半段時間平均、每殘基接觸占有率、是／否結果），才跨重複算平均、樣本標準差（n−1）、SEM 與 Student-t 95 % CI（自由度 n−1；t 分位數用內建表，df 1 到 30 與 scipy 一致到 4 位，更大的 df 以 1/df 內插；scipy 不是相依套件）。**n 是重複的條數，不是幀數**；同一條軌跡的幀有自相關，不當成獨立樣本。
  - 目前涵蓋：主鏈 RMSD、蛋白質 Rg、每殘基 Cα RMSF（平均、SD、CI，逐殘基）；每個配體的口袋 RMSD、接觸殘基數、極性接觸、質心距離（後半段平均）；`stays_bound`（舊旗標）與 `in_pocket_final20`（由 `ligand_state` 最後 20 %：留在口袋的狀態占 ≥ 0.5 → 是；離開證據占 ≥ 0.5 → 否；其餘 → 未知，不計入 n）的 **k／n**；每個接觸殘基的占有率（平均、SD、CI、占有率 ≥ 0.5 的條數 k／n；某條完全沒碰到記 0）。
  - **n = 1**：`between_replica = {status: unavailable, reason: 「單一軌跡無法估計重複間不確定性」}`，SD、SEM、CI 都是 `null`，絕不給區間。n = 2 照算但標 `below_recommended_n`（t₀.₉₇₅ = 12.7，區間極寬）；n < 3 一律在報告與 DecisionLog 提醒。
  - **單條軌跡內的變異另列**：每條重複的區塊平均標準誤（`extended.block_average`，5 區塊，後半段），放在 `within_trajectory`，不與重複間不確定性相加或混用。
  - **不一致標註**：各條數值的變異係數 > 0.25（經驗起始值，要依系統驗證）→ `divergent:<觀測量>`；二元結果不是全 0 或全 k → `inconsistent:<配體>:<結果>`。
  - **失敗、未完成、被排除的重複留在輸出**（`replicas[]` 與 `excluded[]`，附原因）；每條數值都帶 `run_id`。
  - **不接合重複**：事件長短與持續性只在單條內算（`extended.json` 的路徑逐條列出），這裡只彙總各條已算好的數。
- **`Workflow.analyse`**：對 `run_ids` 的每一條分析（沿用既有 `analyse_run`、膜分析路徑與「已有 PASS 的 `analysis_manifest.json` 就沿用」的邏輯；沿用判斷集中在 `_reuse_analysis_manifest()` 一個函式，之後換成快取指紋只改這裡）。run.json 狀態不是 COMPLETE 的重複不分析、保留原因。單一重複分析失敗不擋其他重複（保留原因並寫 DecisionLog）；全部失敗才照舊丟出第一個錯誤。
  - `summaries[key]` 向下相容：原有欄位是**第一條可分析的重複**（`representative_run_id`），另加 `replicas`（逐條 `run_id`、狀態、是否納入、原因、每條的 manifest 摘要）、`n_replicas_analysed`、`replica_set_file`（`<workflow>/analysis_replicas_<系統>.json`，`atomic_write_json`）、`replica_overlay`（疊圖 PNG）。
  - 疊圖 `md20/report/replica_figs.py`：每條重複一條線（用 run id 命名）加跨重複平均 ± SD 灰帶，主鏈 RMSD 與各配體口袋 RMSD 各一格，規則照 `figures.md`（圖例在右側外、時間軸不遞增就不畫成時間）。只有一條時沒有色帶，標題寫明。
  - `compare_runs`（apo 對複合物）的 RMSF 改用各系統**重複平均**；RMSD 曲線仍是一條代表重複，圖例寫明是哪一條。ΔRMSF 的重複間 CI 尚未做（見限制）。
- **可比性（`_comparability`）**：讀**每一條**重複的 `run.json`。任何一條條件不同或不明 → 該比較「不可比」，並指出是系統之間還是同一系統的重複之間不同（`within_system`）；`conditions[key]` 是該系統的合併視圖（重複不同意的欄位變成「replicas differ: …」，不明就是 `null`），所以既有的成對可比性矩陣也會被擋。**只擋比較，各條自己的分析與彙總照常。** 每條的條件另存 `replica_conditions`。
- **共同基底（`_common_basis`）**：每條可分析的重複各自成為一條軌跡，標籤 `系統/run_id`（只有一條的系統維持原標籤）；各自有地形與低谷佔比，**不頭尾接合**。`analysis_common.json` 的 `trajectory_labels` 對應回系統與 run id。
- **報告（`md20/report/replica_section.py`，四語）**：MD 區加「獨立重複的彙總」：說明重複的定義與後代不算；每條重複的表（狀態、是否納入、RMSD 後半段平均與單條 SE、配體口袋 RMSD 與是否留在口袋、排除原因）；跨重複表（觀測量、n、平均 ± SD、t 區間、k／n、備註）；接觸占有率前 10 名；疊圖；n = 1 時寫「不可得」、不印 SD 與區間；不一致與排除會進該節的解讀。方法段與限制段的重複數改讀實際條數（`configured_or_actual`），不再把沒寫 `md.replicas` 讀成 1。
- **限制（誠實）**：
  - §2 表其餘項目（ΔRMSF 區間、水合、DSSP、PCA 低谷佔比、DCCM、tICA／MSM、膜指標）已在 D-142 補完，見 §8。
  - 更正（D-164）：`engine/replicas.aggregate_replicas` 在 n = 1 時 SD 已是 `null` 並寫 `sd_unavailable`，原寫「SD 寫成 0.0、尚未改」的描述過時。
  - 證據矩陣（`report/evidence.py`）仍讀 `md.get("replicas") or 1`，由另一個代理處理。
  - 真實 mdtraj／OpenMM 路徑沒有在容器內跑，只用偽分析輸出測邏輯，真實路徑交給 CI。
- 測試：`tests/test_replica_analysis.py`。

## 8. 實作（D-142）：補完 §2 表的跨重複彙總
輸出仍是 schema `md20.replica_set/1`，加 `schema_revision: "1.1"`（只新增欄位）。輸入是各重複的 `extended.json`、`membrane_metrics.json`、`membrane_report.json`（`Workflow.analyse` 讀入）；欄位缺少或該區塊出錯 → `{status: unavailable, reason, missing:[{run_id, reason}]}`，不補數字。n = 1 → 平均照列、SD／CI 為 `null`，`between_replica` 寫「單一軌跡無法估計重複間不確定性」。

| 觀測量 | 每條重複先算出的數 | 跨重複彙總 | 位置 |
|---|---|---|---|
| apo–複合物 ΔRMSF | 各條 Cα RMSF（殘基以名稱＋編號配對，質子化變體折疊） | 每殘基 ΔRMSF＝複合物重複平均 − apo 重複平均，**Welch t** 95 % CI（Welch–Satterthwaite 自由度）；每邊至少 2 條，否則 unavailable 且不給區間；CI 不含 0 才稱「不同」；`sign_k／n`＝與差值同方向的複合物重複數；寫明預期偶然數量 0.05·N，**不做多重比較校正** | `analysis_delta_rmsf_replicas.json`、`comparison.delta_rmsf_replicas`；系統不可比（D-106）→ `not_comparable` |
| 水合位點 | 該重複各位點占有率 | 位點以位置配對：占有率由高到低貪婪，與最近、尚無同重複位點的群組距離 ≤ **0.2 nm** 歸同一位點（座標在各重複自己的疊合座標系，註明）；占有率 mean±SD **只含偵測到該位點的重複**（沒偵測到＝沒有值，不是 0）；偵測 k／n；只在 1 條出現 → `not_reproduced`；水不存在或幀數不足的重複列為缺失 | `ligands.<配體>.hydration` |
| DSSP | H／E／C 幀比例的時間平均；逐殘基 H、E 比例 | 平均、SD、t CI；殘基以共同標籤對齊；列出 SD 最大的殘基 | `structure.dssp` |
| PCA 低谷佔比 | 共同基底上，該重複投影幀離各配對低谷中心最近的比例 | mean±SD、t CI、範圍；範圍 > 0.25（經驗起始值）→「取樣分布、未收斂」旗標 `unconverged:pca_basins`。**只有共同基底（≥ 2 個系統，`analysis_common.json`）且同系統重複條件可比時才算**；否則 `not_comparable` 並寫原因（各重複自己的 PCA 軸不同） | `structure.pca_basins`（`Workflow._replica_cross_system` 寫入） |
| 分群 | 群數、最大群占比（與群編號無關） | mean±SD；群編號跨重複不對應，不彙總逐群占比 | `structure.clusters` |
| DCCM | 各條 Cα 互相關矩陣 | 逐元素平均與 SD（≤ 500 殘基才存矩陣）；遠距離（序號差 ≥ 5）平均 \|C\| 的 mean±SD；強相關（\|mean\| ≥ 0.5）對數與「每條重複同號且 \|C\| ≥ 0.3」的對數；前 10 對的 sign k／n | `structure.dccm` |
| tICA／MSM | 每條自己的資格（D-105：`msm.eligibility == exploratory`）、`its_flat` | **不合併軌跡、不報平均時間尺度或速率**；只報「n 條中 k 條合格」「其中 k 條持平」，`rate_reportable` 要求 ≥ 3 條都合格且持平（只是允許，不產生數值） | `structure.tica_msm` |
| 膜指標 | 後半段平均：磷酸頭基間距、單脂面積、疏水核心水數；插入深度；是否穿過中心；平衡驗收是否 PASS；S_CD 逐碳 | mean±SD、t CI；k／n；膜-only 系統讀 `metrics.json["membrane"]` | `membrane` |

- **CV 規則（D-144）**：「divergent」只用於嚴格為正的比例尺量（RMSD、Rg、RMSF、計數、距離）。差值型、帶正負號與比例型（ΔRMSF、DCCM 元素、插入深度、S_CD、DSSP／占有率／低谷佔比）一律 `divergent: null` 並寫 `divergent_reason`，改看 CI 與正負號一致的重複數 k／n。
- **報告**（`report/replica_section.py::structure_html`／`delta_rmsf_html`，四語）：各表放在該系統「獨立重複的彙總」之後；沒有彙總的項目逐項列出原因。
- **平衡過程與驗收表**（`report/workflow_report.py::_acceptance_html`／`_equil_figures`）：每條重複一列（run id、MD 狀態、NVT／NPT／正式模擬的「通過數／檢查數」與未通過的項目名）；逐項明細與平衡圖放在 `<details class=fold>`（多條時每條一個，第一條展開）。沒完成的重複照列狀態。只有一條時版面不變。列印時 `details` 不展開（CSS 既有規則），所以重點在永遠可見的緊湊表。
- **膜-only 分析快取（D-135 未決項）**：`membrane_only_analysis(fingerprint=…)` 輸出先寫暫存區，`commit_staging` 換入並最後寫清單（含指紋、輸出雜湊、`prev/` 備份）；指紋 `extra` = 膜計畫、頭基原子、溶質群、`MEMBRANE_ANALYSIS_VERSION`。`_reuse_analysis_manifest` 對膜-only 也用指紋：舊清單（PASS 但無指紋）→ `legacy` 重算，**只重算分析、不重跑 MD**，舊結果留在 `analysis/prev/`。
- 測試：`tests/test_replica_observables.py`。
- **限制**：位點配對是貪婪、依序的，緊鄰的兩個位點可能被錯配（0.2 nm 是沿用單條內合併距離）；各重複的疊合參考不同（各自的第一幀），所以位點座標一致也需要各條從同一個姿勢起步。共同基底只在 ≥ 2 個系統時建立，單一系統的多條重複目前沒有可比的低谷佔比（`not_comparable`）。DCCM 平均矩陣原本沒有出圖，D-164 補上（見下）。tICA／MSM 不合併是刻意的；「合併增加資料」的做法（原規格表）改為不採用，見 DECISIONS D-142。

## 9. D-164：兩張跨重複圖（不新增計算）
- `delta_rmsf_replicas`（`report/replica_figs.py::delta_rmsf_replicas`）：逐殘基 ΔRMSF（複合物重複平均 − apo 重複平均）加 Welch t 95 % 區間灰帶，區間不含 0 的殘基標紅點。圖說與解讀明講**未做多重比較校正**、約 5 % 殘基單憑機率會不含 0。多重比較校正方法仍未決，不自選。
- `dccm_replicas`（`report/replica_figs.py::dccm_replicas`）：左為各重複 DCCM 逐元素平均，右為逐元素樣本 SD；n = 1 只畫平均。只在彙總檔存了矩陣時出圖（≤ 500 殘基）。不遮蔽任何元素，因為判斷「各條同號」需要每條矩陣，彙總檔沒有存。
- 報告位置：ΔRMSF 圖接在 `delta_rmsf_html` 的表之前；DCCM 圖接在 `structure_html` 的 DCCM 表之後。範本由 `tools/report_template.py::_replica_demo` 的合成重複渲染。
- 盤點結論：§2 表的其餘項目（水合、DSSP、PCA 低谷佔比、tICA／MSM、膜指標、平衡驗收逐條列）在 D-142 已完成，沒有再補。決策見 `docs/_pending/D-164.md`。
