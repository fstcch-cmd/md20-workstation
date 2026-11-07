# 有界自主行動帳本（R8，D-137）

狀態：**已實作・純 Python（容器可測，待 CI）；預設只提建議，沒有接進工作流程的執行路徑。** 規格來源：`evidence_driven_repair_prompt.md` §3 R8；對應 `master_iteration_2026-11-07.md` 的 P1A。
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
- 沒有政策檔的 GUI／CLI 入口；使用者目前要自己放 `autonomy_policy.json`（`save_policy` 可用）。
- 帳本沒有輪替／壓縮；規模預期很小（每個行動幾行）。
- `recover_stale` 需要呼叫端提供存活探測（pid／host／heartbeat）；沒提供就永遠不自動回收。
- 提案的 `checkpoint` 指紋來自「核准執行當時的記錄」，目前 workflow 沒有寫這個欄位；整合時要補（沒有指紋＝視為無效，會擋）。

## 8. 想請審查者回答的問題
1. 「沒有改善」的定義（通過診斷數、達到足夠、重新分析看未知數）合理嗎？要不要看具體診斷值（例如重疊度上升）？
2. 預設 `max_attempts=2`、`no_improvement_stop=2` 是否過鬆或過緊？
3. 估計未知時要求人工核准是否太保守（會讓沒有速度資料的案例永遠要人核准）？
4. 在不能確認 worker 存活的平台（Windows 無 pid 檔）上，進行中卻無心跳的行動要多久才建議人工 `abandon`？
