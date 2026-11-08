# 有界自主行動帳本（R8，D-137）

狀態：**已實作・純 Python（容器可測，待 CI）；預設只提建議。D-143 起有擁有者入口（CLI）與執行器，但只有擁有者寫下政策檔才會執行任何東西（§9）。** 規格來源：`evidence_driven_repair_prompt.md` §3 R8；對應 `master_iteration_2026-11-07.md` 的 P1A。
**使用者尚未授權任何計算預算，所以預設不會自動啟動任何模擬。** 要啟用自動執行，必須由使用者寫下行動政策（見 §3）。

## 1. 要解決什麼
傘狀補窗／延長是真的自動化（`sampling/adaptive.py`），但：
- 沒有統一的紀錄：誰提議、依據哪些證據、花了多少、結果有沒有變好。
- 沒有預算與授權邊界：自動行動不該超出使用者核准的範圍，也不該「一直做到結果好看為止」。
- GUI 重連、第二個 worker、重複提案時，沒有保證不會重複啟動模擬。
`report/auto_actions.py`（D-122）只是事後報告成本與效益，**維持只報告**；本模組是事前的提案、授權、帳本與停止規則。

## 2. 流程與模組
```
assess  →  propose  →  authorize  →  execute  →  reassess  →  stop / escalate
評估物件   rules.py    model.authorize  Controller.execute   Controller._reassess   ledger.stop / escalate
```
| 檔案 | 內容 |
|---|---|
| `md20/autonomy/model.py` | `ActionProposal`、`Policy`、`AuthorizationDecision`、`authorize()`、`idempotency_key()`、`load_policy`／`save_policy` |
| `md20/autonomy/ledger.py` | `Ledger`：append-only JSONL＋跨平台檔案鎖＋`claim()`（唯一決定「能不能啟動」的地方）＋成本彙總 |
| `md20/autonomy/rules.py` | 現有評估物件（`md20.assessment.pmf/1`）＋`RefinePlan` → 提案；驗證評估；前後比較 |
| `md20/autonomy/controller.py` | `Controller`：`step`／`authorize`／`approve`／`execute`／`cycle`／`run_until_stop`／`dry_run`／`recover_stale` |
| `md20/autonomy/integration.py` | 讓既有補窗規劃器把它的動作記進帳本的可選掛勾 |

### 2.1 支援的行動（第一批）與先決條件、比較後果
| 行動 | 觸發（診斷） | 先決條件 | 比較後果 |
|---|---|---|---|
| `reanalysis` | 診斷為 unknown、舊評估（legacy）、solver 未收斂 | 原始樣本仍在磁碟上（輸入須明說，未知＝擋） | 不產生新取樣；要用同一版門檻重新分析，被比較的候選也要同版 |
| `refine_approved_umbrella_windows` | 覆蓋／重疊類診斷失敗，且規劃器本輪有可插入的窗口 | 規劃器有計畫、k 不超過 k_max、未超過窗口總數上限 | PMF／ΔPMF 與不確定度要重算；補窗是依資料決定的適應性程序，須在報告註明；比較雙方須在同一個覆蓋判準下評估，不能只替有利的候選補窗 |
| `extend_approved_run` | 窗口有效樣本、前後半差、累積漂移失敗 | 有已核准的執行（run_id＋協定雜湊）、有檢查點（執行前再驗指紋）、延長次數未達上限 | 同協定延長；取樣量變大，與未延長者比較要註明或一併延長；不可只延長結果有利的系統 |
| `add_independent_replica` | 重複數少於所需 | 系統已建好並核准、沿用同一協定（不同種子） | 跨重複彙總重算；每條重複都要合格（不挑有利的）；比較雙方重複數應相同 |

規則只讀診斷狀態（pass／fail／unknown），**不讀 ΔG 數值**：是否行動取決於證據夠不夠，不取決於結果好不好看。修正方式會改變 CV 範圍或參考態的診斷（`endpoint_plateau`、`range_coverage`）沒有例行行動，直接升級給使用者。

### 2.2 `ActionProposal` 欄位
`action_type`、`scope`、`target`、`trigger`（診斷 id）、`evidence_ids`（`assessment@<摘要>:<診斷 id>`、評估檔識別、`refine_log` 輪次）、`prerequisites`（`satisfied` 為 True／False／None）、`affected_claims`、`expected_benefit`（`kind` 預設且除非附 `calibration_ref` 否則一律 `heuristic`）、`estimate`（`sim_ns`／`gpu_hours`／`core_hours`／`storage_gb`，未知＝None 不是 0，附 `basis`）、`protocol_changes`、`inputs`（提案當時的證據狀態，進 hash）、`max_attempts`、`checkpoint`（`required`／`path`／`fingerprint`）、`recovery_plan`、`comparison_consequences`、`baseline`（提案時的評估摘要，供行動後比較）、`authorization_class`、`idempotency_key`、`proposal_id`。
- **idempotency key** = sha256(行動、scope、target、inputs 的標準化 JSON)。相同行動＋相同標的＋相同證據狀態＝同一個 key，不論誰提、提幾次。行動完成後評估會變，下一個合理的行動 inputs 不同，key 就不同；證據狀態沒變就是重複。
- `authorization_class` 與 key 都會在授權時**重算**；內容被改過或自稱的類別與內容不符，一律 `denied`。

## 3. 授權
- **`Policy`**（使用者寫的）：`policy_id`、`approved_by`、`approved_at`、`allowed_actions`、預算上限（`max_sim_ns`、`max_gpu_hours`、`max_core_hours`、`max_storage_gb`，None＝該資源沒有核准）、`max_attempts`（含第一次，預設 2）、`no_improvement_stop`（預設 2）。放在 `<workflow>/autonomy/autonomy_policy.json`；沒有檔、檔案無效、沒有核准者、沒有任何允許行動或沒有正的預算，都視為**沒有政策**。本套件沒有任何程式會自己寫這個檔（`save_policy` 只給使用者的授權步驟用）。
- **授權結果**（`authorize()`，確定性）。順序：提案無效 → 禁止 → 無政策（只提建議）→ 先決條件未滿足（blocked）→ 預算不足 → 需要核准 → 授權。
  | 結果 | 條件 | 會執行嗎 |
  |---|---|---|
  | `denied` / `forbidden` | `protocol_changes` 非空（力場、化學身分、質子化、約束、參考態、科學模型、付費後端、對外傳送資料，或任何不認得的標籤），或行動類型不支援，或提案無效 | **永不**；使用者個案核准也不行，有預算也不行 |
  | `recommendation_only` | 沒有可用政策 | 否 |
  | `blocked` | 先決條件為 False 或未知 | 否 |
  | `budget_exhausted` | 已用＋進行中＋本行動估計 > 上限 | 否，並停止該 scope |
  | `needs_approval` | 行動類型不在政策內、估計未知、用到政策沒核准的資源 | 否，直到人核准（綁 idempotency key，內容變了要重核准） |
  | `authorized`（`routine_within_policy`） | 以上皆非 | 是，且只經過 `claim()` |
- 核准（`Controller.approve`）必須記錄是誰；只解除「需要核准」，不解除禁止、擋住、無政策、預算不足。

## 4. 帳本（`<workflow>/autonomy/ledger.jsonl`）
- **append-only**，一行一筆 JSON，`seq` 遞增。事件：`proposed`、`authorization`（誰、何時、結果、理由、政策）、`approval`、`exec_start`、`exec_end`、`post_assessment`、`cancel_requested`、`stop`、`resume`、`escalate`、`observed`、`observed_end`。
- **鎖**：每個寫入操作都在 `md20.util.FileLock`（Windows 用 msvcrt、POSIX 用 flock、最後後備用鎖目錄）下「重讀帳本 → 判斷 → 追加」；套件內沒有自己的 `fcntl`／`msvcrt`。`state.json` 是衍生快照（`atomic_write_json`），只是方便讀取，永遠可由 JSONL 重建，寫失敗（例如 Windows 檔案被占用）不影響正確性。
- **只有 `Ledger.claim()` 能讓執行器被呼叫**：在鎖內重讀帳本，依序檢查帳本完整、是否已在跑、是否已成功、是否被取消、重試是否用完、scope 是否已停止、授權＋預算（含進行中的保留量）、重試類型，才追加 `exec_start`（保留估計量）。所以重複提案、第二個 worker、GUI 重連、重新整理，都只會看到第一個人的紀錄。
- **進行中但 worker 不見了**：未知的 worker 一律當作還在跑，**不自動重啟**；只有 `recover_stale(is_alive)` 在探測回報「確定已死」（False）時才關閉該次嘗試（計為一次失敗嘗試，以估計值計費），之後仍受重試上限與檢查點驗證約束。
- **寫到一半當機**：最後一行沒有換行且無法解析＝追加尚未完成，從未產生任何效果；下次追加前把它存到 `ledger.jsonl.torn` 並截掉。中間有無法解析的行＝完整性受損，`claim()` 拒絕執行（需人檢查）。
- **成本**：`exec_end.resources`（`wall_s`、`gpu_hours`、`core_hours`、`storage_gb`，**實際使用**）和 `exec_end.simulated_ps`（模擬時間）分開記。失敗、取消、重試的嘗試全部計入（營運成本）；執行器沒回報的維度以提案估計值計費並標 `charged_from: estimate`（不是免費）。`Ledger.cost_summary()` 回傳嘗試數、重試數、失敗／取消嘗試、實際資源、模擬 ps（回報的／成功的）、依行動分項；既有流程記錄的動作（`observed`）另列，不計入任何政策預算。

## 5. 控制器
- `step(inputs)`：驗證評估（schema 不認得、診斷狀態不是 pass／fail／unknown、不是物件 → `unknown_assessment`）→ 提案 → 記入帳本（重複不重複寫）→ 授權決定（有變才寫）。回傳 `StepResult`（`proposals`、`decisions`、`skipped`、`escalations`、`stop`）。
- `authorize(p)`、`approve(id, by)`、`request_cancel(id, by)`（可由另一個行程／GUI 呼叫；執行器用 `request.cancelled()` 輪詢）、`resume(scope, by)`。
- `execute(p)`：授權 → 檢查點驗證（無效或沒指紋 → `escalate invalid_checkpoint`，**不執行**；修好後同一提案可再跑）→ `claim()` → 呼叫**注入的** `executor(ExecutionRequest)` → `finish()` → 重新評估。
  - **重試**：只重試 `TechnicalError` 或回報 `error_kind="technical"` 的失敗；上限＝min(提案 `max_attempts`, 政策 `max_attempts`)；每次重試都重新過 `claim()`（預算、取消、停止狀態都再檢查）、都計入成本；`ExecutionRequest` 每次都一樣（同提案、同 key、同檢查點），重試**不能**改協定。其他例外或 `scientific`／`unexpected` 失敗不重試，升級給使用者。`invalid_model` 停止該 scope。
  - **取消**：行動前取消不啟動；執行中取消由執行器回報 `cancelled`（`ActionCancelled`）；取消後同一提案永不自動重啟。已花的部分照樣計費。
  - **重新評估**：行動後的評估來自注入的 `reassessor` 或執行結果；不可解讀 → 停止 `unknown_assessment`。改善的定義（`improved`）：通過的診斷變多、或達到足夠；重新分析另外算「未知變少」。連續 `no_improvement_stop` 次沒有改善 → 停止 `no_improvement`。
- `cycle(inputs)`：`step` 之後，**只有**有可用政策＋有執行器＋決定為 `authorized` 時才執行，且一次最多一個行動（行動後證據已變，剩下的提案過期，要用新評估重新導出）。`run_until_stop(get_inputs, max_cycles)` 每圈都重新取評估，有上限。
- `dry_run(inputs, policy=...)`：不寫任何檔，回傳「如果現在執行會怎樣」（每個提案的決定、`would_execute`、剩餘預算、停止原因、中文說明）。
- **停止與升級**（寫入帳本，之後需人 `resume`）：`budget_exhausted`、`no_improvement`、`unknown_assessment`、`insufficient_evidence`（含規劃器沒有可插入窗口、無例行行動）、`invalid_model`、`protocol_decision_needed`、`attempts_exhausted`、`action_failed`、`invalid_checkpoint`（升級但可修好後續跑）。`goal_met` 只回報不持久化。
- 不含 LLM 輔助。分子名稱、文件詮釋資料、備註文字都只被當成字串記錄，不會被解讀成指令；執行器是呼叫端注入的可呼叫物件，控制器不組命令、不執行字串。

## 6. 既有補窗規劃器的掛勾
`plan_refinement(..., recorder=None)`：預設 None，行為完全不變；給 `md20.autonomy.make_refine_recorder(workflow_dir, scope=..., costs=..., round_no=...)` 時，規劃器把本輪的 insert／extend 以 **observed**（既有自動流程、不受政策管轄、不計政策預算）記進帳本，同一輪重新規劃（續跑）不重複寫；掛勾裡的例外一律吞掉，不會改變或中斷規劃。實際花費可再用 `record_refine_result` 補記（模擬 ps 與牆鐘時間分開）。`binding.py` **沒有改**，所以目前不會自動呼叫；要啟用，是在 `binding.py` 呼叫 `plan_refinement` 處傳 `recorder=`。

## 7. 誠實限制
- 只有純 Python 邏輯與 fake 執行器的測試；沒有接真正的 Runner／ProcessJob，沒有任何真實模擬被這個模組啟動過。
- 預期效益與成本估計都是啟發式（只由已記錄的設定推得；沒有時間／速度資料就是未知，未知會讓政策預算要求人工核准）。
- 政策入口：D-143 起有 CLI（§9）；GUI 入口尚未做。
- 帳本沒有輪替／壓縮；規模預期很小（每個行動幾行）。
- `recover_stale` 需要呼叫端提供存活探測（pid／host／heartbeat）；沒提供就永遠不自動回收。
- 提案的 `checkpoint` 指紋：D-143 起引擎在 production 完成時寫進 `run.json`（§9.4）；舊 run 沒有，延長會升級並說明原因。

## 8. 想請審查者回答的問題
1. 「沒有改善」的定義（通過診斷數、達到足夠、重新分析看未知數）合理嗎？要不要看具體診斷值（例如重疊度上升）？
2. 預設 `max_attempts=2`、`no_improvement_stop=2` 是否過鬆或過緊？
3. 估計未知時要求人工核准是否太保守（會讓沒有速度資料的案例永遠要人核准）？
4. 在不能確認 worker 存活的平台（Windows 無 pid 檔）上，進行中卻無心跳的行動要多久才建議人工 `abandon`？

## 9. 可用化（D-143）
**原則不變：沒有擁有者寫下的政策檔，什麼都不會自動執行；程式碼裡沒有任何預算預設值，AI session 不得替擁有者執行 `policy set`。**

### 9.1 擁有者入口（`md20/autonomy/cli.py`，`md20 autonomy ...`）
| 指令 | 作用 |
|---|---|
| `policy set --approver 名字 --allow 行動[,..] [--ns N] [--gpu-hours H] [--core-hours H] [--storage-gb G] [--max-attempts K] [--no-improvement-stop K] [--yes]` | 寫 `<workflow>/autonomy/autonomy_policy.json`（用既有 `save_policy`），核准時間由程式記錄。先印出完整白話摘要（允許什麼、各項上限、永遠不會自動做什麼），要擁有者輸入 yes 或明確加 `--yes` 才寫；沒有終端機又沒有 `--yes` 就拒絕。舊政策改名為 `autonomy_policy.superseded-<時間>.json` 保留。帳本記 `policy_set`。 |
| `policy show [--json]` | 白話摘要＋剩餘額度；沒有政策或無效就明說「只提建議」。 |
| `policy revoke --by 名字` | 政策檔改名為 `autonomy_policy.revoked-<時間>.json`（保留歷史），帳本記 `policy_revoked`。控制器每次 `claim` 前重讀政策，所以撤銷在下一次啟動前就生效；進行中的行動不會被殺掉（用 `request_cancel`）。 |
| `plan [--extend-ps PS] [--json]` | 乾跑：每個結合目標會提出什麼、怎麼決定、為什麼不能執行。**不寫任何檔案**（測試以整個資料夾的位元組比對）。 |
| `status [--json]` | 帳本摘要：嘗試／失敗／取消／重試次數、實際用量（牆鐘、GPU 小時、核心小時、磁碟）與模擬時間（分開）、剩餘額度、已停止的範圍、帳本完整性。`status_data()` 回傳同一份資料，GUI 之後可唯讀顯示。 |
| `approve 提案 --by 名字` | 個案核准（只解除「需要核准」）。 |
| `run [--max-cycles N] [--extend-ps PS] [--fake]` | 沒有有效政策就拒絕（exit 2）。有政策時，對每個結合目標用**新**證據跑 `Controller.run_until_stop`，每圈最多一個行動。 |

- **拒絕**：未知行動、禁止類別（`FORBIDDEN_CHANGES` 的八個標籤）、空的允許清單、沒有核准者、沒有任何正的預算、負數或非有限數、`--max-attempts`／`--no-improvement-stop` < 1，一律 exit 2、什麼都不寫。預算數字沒給＝那項資源沒核准（不是預設值）。
- 語言：`--lang zh|en|ja|ko`（預設 zh；命令列文字依 `writing_style.md` §3 維持中文為預設）。政策摘要、拒絕訊息、狀態標籤有四語。

### 9.2 輸入（`md20/autonomy/inputs.py`，只讀檔案）
每個完成的結合目標一份 `AssessmentInputs`，`scope = <workflow>/<目標>`：
- **評估**：`state.json` 儲存的評估；舊結果用 `resolve_assessment` 由 manifest 的 PMF 欄位重算（顯示診斷、資格不成立）。**舊（legacy）評估即使 `sampling_adequate` 為 True 也不算達標**（它是重算的檢視，不是儲存的判定），所以仍會提出重新評估。
- **成本**：
  - `ns_per_day`：`app_data_dir()/doctor/doctor_report.json` 的 benchmark（`md20 doctor` 存的），用原子數與時間步依 `engine.longrun.scaled_ns_per_day` 換算到這個系統；沒有記錄＝未知（估計 None，政策要求人工核准）。benchmark 的平台是 CPU 時，同樣的時數記為核心小時（× 邏輯核心數）、GPU 小時為 0。
  - `gb_per_ns`：每 ns 的幀數（run.json 的 production 軌跡間隔）× `engine.longrun.dcd_frame_bytes(原子數)`。
  - `replica_ns`：一條重複的模擬 ns × 系統數（工作流程的重複數是全域設定，補一條＝每個系統各補一條，比較雙方重複數才相同）。
  - 窗口時間與重複數取自該目標的 `binding_manifest.json` 的 config（檔案為準）。
  - 重新評估（由已儲存欄位，不模擬）的 CPU 時間與磁碟估計為 0（可忽略）；執行器會**量測**實際用量並計入帳本，所以不會繞過預算。
  - 估計的依據寫在 `estimate.basis`（含 benchmark 時間）。
- **approved_run**：該目標第一次拉離所用的 MD run（`replica_sources[0].md_run_id`），帶 `run.json` 的 `checkpoint_fingerprint`；沒有指紋的 run 標 `legacy_run`。`extend_ps` 由使用者以 `--extend-ps` 指定，**沒有預設值**；沒給時延長提案被「extension_length」先決條件擋住。
- **replicas**：只附在第一個目標（重複屬於工作流程，不屬於某次拉離），`required` 為 `required_replicas()`。
- 限制：只讀結合評估，所以沒有完成結合計算的工作流程沒有提案。

### 9.3 執行器（`md20/autonomy/executors.py`，`WorkflowExecutors`）
`Controller(executor=ex, preflight=ex.preflight, reassessor=ex.reassessor)`。執行器只會在 `Ledger.claim()` 成功後被呼叫；`preflight` 在 `claim` 之前（不花嘗試次數、不記成本），失敗就升級 `cannot_start`。
| 行動 | 呼叫的既有公開操作 | 先決（preflight） |
|---|---|---|
| `reanalysis`（結合） | `sampling.reassess.reassess_workflow`（`include_outdated=True`，只用已儲存欄位） | 無 |
| `reanalysis`（軌跡，`target.what == "trajectory analysis"`） | `Workflow.analyse(全部 runs)`——只傳受影響的系統會讓 `steps.analysis` 少了其他系統；沒變的系統由分析指紋沿用，只算受影響的 | 目前沒有規則會提出這個變體 |
| `add_independent_replica` | config `md.replicas` +1、丟掉 analysis／report 步驟、`Workflow.run_md`（D-131 補跑路徑：同一組、只跑缺的）、`Workflow.analyse` | 設定要求的重複數 ≤ 已完成＋1（一次只補一條，否則請用一般流程）；沒有別的 MD20 程序擁有該工作流程（`running.json`）；授權 |
| `refine_approved_umbrella_windows` | config `binding.manual_windows[目標]` 加窗口、從 state 移除該目標的結果、`Workflow.binding` → `run_binding` 續跑（與 GUI 的 `resample_range` 同一條路，只是決策紀錄 `kind="auto"`）；完成後 `refresh_report` | 同上，且需要平台 |
| `extend_approved_run` | `engine.chunks.run_stage` 對該 run 的 production stage 用較長的 spec（引擎自己的自動延長機制：同一串 chunk、同一組種子、從已驗證檢查點接續）；成功後 `run.json` 加 `extensions`、`effective_production_ps`、新的 `checkpoint_fingerprint`，並重做分析 | `extend_ps` 由使用者給；提案時的 `protocol_hash`、延長次數與 run.json 一致，否則 `scientific` 失敗；**窗口層級的延長（`window_centres` 非空）沒有公開介面，不啟動** |
- **只有人決定的 DecisionLog**：這些行動的決策紀錄 `kind="auto"`，`why` 寫明「自主行動（帳本 key、政策）」；不冒充使用者在 GUI 的選擇。
- **量測**：`resources.wall_s`＝牆鐘；`gpu_hours`＝GPU 平台時的牆鐘小時（否則 0.0）；`core_hours`＝本程序的 CPU 秒數／3600；`storage_gb`＝被監看資料夾的增加量。`simulated_ps` 另外由檔案讀回（`*_complete.json` 的步數×時間步；窗口樣本數×取樣間隔＋平衡時間）。GPU／CPU 小時不是硬體計量，是牆鐘與程序 CPU 時間。
- **取消／暫停**：`req.cancelled()` 併入引擎的 `should_pause`；被取消回報 `cancelled`，其他暫停回報 `failed`（`paused`，不重試、升級）。
- **事後評估**：`reassessor` 讀該目標在 state 裡的評估。replica／extend 不改變結合評估，所以通常算「沒有改善」，連續 N 次就停止——這是如實的結果，不是錯誤。

### 9.4 檢查點指紋（`engine/runner.py`）
production 完成（`run.json` `COMPLETE`）時記 `checkpoint_fingerprint = {bytes, mtime_ns, edge_sha256, sha256, stage, state_file, recorded_at, chunk_manifest: {file, digest}}`。`chunk_manifest.digest` 是 `production_progress.json` 的每個 chunk（編號、步數範圍、各 artifact 的大小與邊緣雜湊）的 sha256，不含路徑與時間，所以搬動專案不變。計算失敗不會讓 run 失敗（只是沒有指紋，之後延長會升級）。
`default_checkpoint_validator` 驗：檔案存在非空、大小與邊緣雜湊、（有記錄時）完整 sha256、chunk 清單摘要。舊 run（沒有指紋）：升級 `invalid_checkpoint`，訊息說明「在記錄指紋之前完成的舊版，無法確認未損毀」，不執行。

### 9.5 其他控制器變動
`preflight`（可選）、`policy_loader`（`for_workflow` 預設；每次 `claim` 前重讀政策，撤銷立即生效，政策消失則不再啟動）；`dry_run` 回報 `preflight`。`rules.py`：`target_key`、裝置類型、延長長度、重複數倍率、基礎說明；舊測試全數不變。

### 9.6 未做／未驗證（誠實）
- GUI 入口與唯讀面板沒做（`status_data()` 已備好）。
- 沒有真實 OpenMM／真實 `Workflow.run_md`／`run_binding` 的整合測試：執行器的測試用 FakeBackend（延長）與 Workflow 替身（補重複、補窗），CI 的真實引擎矩陣還沒跑過這條路。
- 延長的是 **MD production 軌跡**；規則把傘狀窗口的 ESS／漂移失敗對應到「延長已核准的執行」，這個對應是否真的改善窗口診斷沒有證據（預期效益標 heuristic）。窗口層級延長需要 `binding.py` 公開 API。
- 延長後 `run.json['protocol']` 仍是原核准長度；實際長度在 `effective_production_ps`／`extensions`。`analysis`／`report/comparability` 目前讀 protocol，**還不知道**延長（比較兩個長度不同的 run 時不會自動註明）。
- 延長中途當機：`run.json` 狀態停在 `EXTENDING`（分析會略過，使用者可見），不會自動接續。
- 只讀結合評估；沒有結合結果的工作流程沒有提案。軌跡分析變體沒有規則觸發。
- 預算數字：待擁有者設定。
