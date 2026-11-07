# 分析解析度與分析快取指紋（D-135，R3 + R4）

狀態：**已實作・純 Python 驗證（容器）；真實 mdtraj 路徑（`analyse_run` 串流持續性、`extended_metrics` 對真實拓樸）待 CI。**
來源：`docs/specs/evidence_driven_repair_prompt.md` §3 R3、R4。範圍：`md20/analysis/{persistence,extended,stream,traj,common_basis,fingerprint}.py`。`workflow.py` 的接線由主 session 做（見 DECISIONS D-135 的「整合說明」）。

## 1. R3：科學分析解析度 ≠ 繪圖解析度

### 1.1 三種幀，分開記錄
| 層 | 內容 | 在哪裡 |
|---|---|---|
| source | production DCD 儲存的所有幀（`source_frame_interval_ps`） | `production_complete.json`、`resolution.source_frame_interval_ps` |
| analysed | `analyse_run` 載入的幀；記憶體保護 stride > 1 時只有每 k 幀取一幀 | `resolution.effective_stride`、`effective_interval_ps`、`n_frames_used` |
| 子樣本 | PCA／叢集／SASA／DSSP／DCCM／水橋／共同基底用 `frame_indices`（≤ 250 幀，均勻） | `extended.json` 的 `sampling`、`pca.sampling`、`clusters.sampling`、`ca_labels.json` 的 `sampling` |

### 1.2 解析度紀錄（`persistence.resolution_record`）
欄位：`source_frame_interval_ps`、`effective_stride`、`effective_interval_ps`、`n_frames_source`、`n_frames_used`、`observation_length_ps`、`resolution.{status, reasons}`。
`status`：`full`（stride = 1）、`limited`（stride > 1：短於有效間隔的中斷看不見、事件長度是上限、救不回來）、`unverified`（呼叫端沒宣告 stride，不宣稱全解析度）。
寫入位置：`metrics.json`／`analysis_manifest.json` 的 `resolution`、`extended.json` 的 `resolution`、每個指紋的 `fingerprint.resolution`、`fingerprint.persistence.resolution`、tICA 的 `resolution`。

### 1.3 持續性與指紋的狀態
- `fingerprint.status`、`persistence.status`、每個 item 的 `status`：`computed`／`limited`／`unverified`／`unavailable`。stride > 1 且沒有全節奏結果時一律 `limited`，附 `reason`；item 另有 `lifetime_qualifier`（「解析度上限的上界，不是滯留時間或 k_off」）。
- 持續性**永遠不改名**為 residence time 或 k_off（`note` 欄位保留原句）。

### 1.4 真正的修正：在儲存節奏上串流算事件
- `persistence.EventAccumulator`：一個 run 的許多互作，一塊一塊餵；跨 chunk 帶著「開著的事件」、上一幀時間、段落編號與判斷時間跳躍的參考步長。事件在**段落斷點**（`segment_ids` 改變、時間步長 ≤ 0 或 > `max_dt_factor` × 參考步長）結束，絕不橋接；不同 run／replica 用不同 accumulator，絕不串接。`events()` 就是它一次餵完，所以 chunked 與 unchunked 相同（有測試，chunk 大小 1…1000，連續與間歇兩種定義）。
- `stream.PersistenceStream`（純 numpy）：每個 chunk 做完整鄰居搜尋與化學標籤（沿用 `interactions.dynamic_pairs`／`fingerprint`），只保留每個（殘基，標籤）的 on/off，餵給 accumulator；記憶體是「幀數 × 互作」的 run-length 狀態，不留座標。
- `stream.stream_production_persistence`（mdtraj）：包上述，讀 DCD chunk、歸零（不疊合）、用 `production_times_ps` 的真實時間；寫 `analysis/stream_persistence.json`。沒有時間軸就不算（不猜時間）。
- `traj.analyse_run`：`stride > 1`（記憶體保護或使用者指定）時，抽幀的指紋照舊（佔有率是抽樣估計，標 `limited`），**持續性改用串流結果**取代，`persistence_decimated_status` 留下原本的狀態；串流失敗則維持 `limited` 並寫 `streamed_persistence_error`。
- chunk 檔邊界（同一個 run 的續跑）不是段落斷點：事件跨 DCD 檔延續；真正的不連續只有時間跳躍或 `segment_ids`。

### 1.5 子樣本：說清楚，並報告敏感度（不承諾收斂）
- `extended.json.sampling`：方案（均勻、決定性、非隨機）、N、n、使用的區塊與全幀區塊清單。
- `pca.sensitivity`（`extended.pca_sensitivity`）：奇偶交錯兩半各做 PCA（解釋變異、PC1 |cos|、子空間重疊），並在成本允許時與全部分析幀的 PCA 比較；`consistent` 只對宣告的報告門檻（`SENSITIVITY_TOLERANCES`，經驗值）比較，**不是收斂判準**。
- `clusters.sensitivity`：奇／偶兩半叢集數與最大族群比例。
- `common_basis`：每個系統加 `interleaved_split`（奇偶幀的盆地族群差）與 `sampling`（讀 `ca_labels.json.sampling`；舊檔標 `not_recorded`）。
- `frame_indices` 的預設上限改為呼叫時讀 `MAX_FRAMES`（以前在定義時綁定）。

### 1.6 已知限制
- tICA／MSM 仍用分析幀（stride 後），`resolution` 已附上；沒有串流版。
- `stream_production_metrics` 的接觸頻率仍是 D-89 之前的「第一幀 1.2 nm 候選」版本，未改（不在本次範圍）。
- 串流持續性使用歸零但不疊合的 chunk；與記憶體內路徑的幾何一致，但真實 mdtraj 路徑未在容器驗證。

## 2. R4：分析快取指紋

### 2.1 指紋（`fingerprint.analysis_fingerprint`）
扁平 `components`（名稱 → 字串）＋ 總 `digest`，另有 `thresholds`、`details`：
| 組件 | 內容 |
|---|---|
| `analysis_version` | `ANALYSIS_VERSION`（目前 `2026-11-07.1`）：任何輸出語意或必備欄位改變時手動升版 |
| `persistence_schema`、`interactions_schema`、`extended_schema` | 對應模組的 schema 常數（`extended.EXTENDED_SCHEMA`） |
| `extended_thresholds`、`ligand_state_thresholds` | 截斷距離、`MAX_FRAMES`、敏感度門檻、ligand_state 門檻的雜湊 |
| `assessment_thresholds_version` | `sampling.assessment.THRESHOLDS_VERSION` |
| `dcd:<序>:<檔名>` | 大小＋前後 64 KiB 雜湊（`util.hashing.cheap_fingerprint`；不重新全檔雜湊）；mtime 記在 `details` 但不進雜湊（複製專案不應使快取失效）。與 `production_progress.json` 當時記錄的 chunk 指紋比對，不符寫 `details.recorded_mismatch` |
| `production_state_sha256`、`production_record` | stage 封存時的完整 SHA、步數／時間步長／DCD 原子集合 |
| `topology` | 拓樸檔完整 SHA-256 |
| `selections` | 配體原子群、金屬索引、配體電荷、是否為膜系統 |
| `protocol` | `run.json` 的 `protocol_hash` |
| `analysis_memory_gb` | `MD20_ANALYSIS_MEM_GB`（影響自動 stride，也就是有效解析度） |
| `extra:<k>` | 呼叫端另外要納入的設定 |

### 2.2 決定（`fingerprint.reuse_decision`）
`{"reuse", "reason", "changed", "recompute_parts", "missing", "modified", "notes", "manifest_analysis_version"}`。`reason`：`unchanged`、`no_manifest`、`not_pass`、`legacy`（PASS 但沒有指紋）、`missing_files`（`*_file`／figures 指到的檔不存在）、`output_modified`（輸出內容的 SHA 與清單不符）、`changed`。
`recompute_parts`：`core`（指標、圖、歸零匯出）、`extended`、`assessment`。只有 schema／門檻類組件變動時只列 `extended` 或 `assessment`；其餘（輸入、版本）列 `core` + `extended`。**`analyse_run` 目前仍整份重算**（不重跑 MD）；部分重算是已知的後續項目，指標只供顯示與決策紀錄。
舊報告與新驗證的結果可區分：新清單有 `fingerprint`、`analysis_version`、`outputs`、`commit_id`；舊清單沒有，`legacy` 一律重算；舊結果在 `analysis_manifest.prev.json`（含 `superseded` 來源說明，`legacy: true`）與 `analysis/prev/`。

### 2.3 原子重算
`begin_staging` → 把 `metrics.json`、`extended.json`、`stream_metrics.json`、`stream_persistence.json`、`ca_xyz.npy`、`ca_labels.json` 寫進 `analysis/.staging-*` → `commit_staging`：
1. 暫存區算 SHA、寫新清單；2. 現有輸出與清單複製到 `analysis/prev/`、`analysis_manifest.prev.json`（加 `superseded`）；3. 寫 `.swap_journal.json`；4. 逐檔 `os.replace`；5. 清單**最後** `os.replace`；6. 刪日誌與暫存區。
中途當機：下一次 `reuse_decision`／`recover_interrupted` 看到日誌，若現行清單的 `commit_id` 不是新的，就從 `prev/` 還原輸出並刪除這次新建的檔案；若是新的（只差刪日誌）就清理。因此完整結果不會被半成品取代。
未涵蓋：`production_centered.dcd`／`production_aligned.dcd`（大檔，由 `export_centered` 直接寫）與 `figures/` 仍就地覆寫，它們是從同樣輸入決定性重生的便利輸出；清單只檢查圖檔存在。膜分析（`membrane_run`）自有清單，沒有指紋，會被視為 `legacy`。
