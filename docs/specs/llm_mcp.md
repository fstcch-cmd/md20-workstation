# Spec: LLM 編排 L1——MCP 轉接頭（D-184）

狀態：**[已實作・容器測試綠・待 CI／本機]**。這是 `llm_orchestration.md`（D-161）§5 的轉接頭 1、§12 里程碑 L1，實作 `llm_interface.md`（L0，D-178）的契約。使用者 2026-11-11 指派並決定範圍：**只暴露 L1 三個工具、零依賴自寫 stdio**（不用官方 `mcp` SDK 當產品依賴）。L2 以後未收到使用者回饋前不做。

## 1. 怎麼用（路徑 A：用現有訂閱，MD20 不碰金鑰）
```
md20 [--dir <專案根目錄>] mcp
```
stdio MCP server；`--dir` 省略時沿用 GUI 上次選的資料夾（與其他命令相同）。Claude Desktop 範例設定（`claude_desktop_config.json`）：
```json
{"mcpServers": {"md20": {"command": "<MD20 環境的 python>", "args": ["-m", "md20", "--dir", "<專案根目錄>", "mcp"]}}}
```
不做授權檢查：L1 只有唯讀／提議工具，不執行任何計算；真正執行在 `md20 pipeline run`，由既有授權把關（D-128）。

## 2. 架構
- `md20/llm/mcp_server.py`（協定層，只用標準函式庫）：換行分隔 JSON-RPC 2.0，stdin/stdout **binary + 明確 UTF-8**（Windows cp950 主控台不影響；e2e 測試以 `PYTHONIOENCODING=cp950` 驗）。
  - 方法：`initialize`、`notifications/initialized`、`ping`、`tools/list`、`tools/call`；notification 不回應；initialize 前除 ping 外一律擋（-32002）；未知方法 -32601（含新版 SDK 的 `server/discover` 探測，SDK 收到後退回 initialize 握手）；壞 JSON -32700；未知工具 -32602；單行上限 4 MiB；不支援 batch（2025-06-18 已移除）。
  - **版本協商**：支援 `2025-06-18`／`2025-03-26`／`2024-11-05`；client 要求的在清單內就回同版，否則回 `2025-06-18`。官方 SDK 2.3.0 client 會要 `2025-11-25`，接受我們回的 `2025-06-18`（其 `HANDSHAKE_PROTOCOL_VERSIONS` 含 2024-11-05～2025-11-25），互通測試已證實。`structuredContent` 只在 ≥2025-06-18 給。
  - **stdout 只放協定訊息**：真 stdout 的 fd 1 先複製成私有出口，再把 fd 1 與 `sys.stdout` 都導向 stderr——md20 其他程式碼、子行程或 C 層的輸出都不會汙染串流。log 只寫 stderr。
  - **核心不外露**：handler 例外只回 `internal error`，traceback 只進 stderr；參數 schema 不合法回 `isError` 讓模型自行修正。
- `md20/llm/tools.py`（工具層）：`L1_TOOLS`＝`read_capabilities`、`plan_workflow`、`read_report`，順序與 `interface.L1_EXPOSED` 一致（import 時 assert）。
- `md20/llm/interface.py`（L0 契約擴充）：新增唯讀動作 `read_report`（ACTIONS 7→8）、`L1_EXPOSED`、`KNOWN_DRAFT_KEYS`、`PLANNABLE_DECISION_PATHS`、純函式 `validate_workflow_draft`。`validate_proposed_change` 的型別範圍邏輯抽成共用 `_value_problem`，行為不變（另擋 NaN/inf）。

## 3. 三個工具
### read_capabilities（唯讀）
回 `capabilities_view()`：id、feature、states、last_known_status、released_installer；**不含 implementation 路徑**。

### plan_workflow（只提議）
參數 `draft`（物件，必填）、`rationale`（字串，≤2000，選填）。先 `validate_workflow_draft`（純函式）：
1. dict，`name` 為非空安全名（`safe_name(name)==name`），`receptor` 為物件。
2. 頂層鍵必須在 `KNOWN_DRAFT_KEYS`（由 workflow.py／advisor.py／replica_plan.py 實際讀取的鍵推出，加 DECISION_KEYS 的頂層鍵；見程式註解）；其他鍵擋。
3. **人工決定鍵一律擋**：`workflow.DECISION_KEYS` 任一路徑或任一配體的 `LIGAND_DECISION_KEYS` 有非空值→REJECTED（原則 2：LLM 永遠不能代替人在閘門做決定）。**唯一例外 `md.replicas`**（`PLANNABLE_DECISION_PATHS`）：它雖被當決定沿用，但重複計畫只是資訊＋預設、從不擋流程（`engine/replica_plan.py`、D-131），且在 SAFE_KEYS；草稿可設，仍照 PARAMS 範圍檢查。`screen.next_mode` 等其餘一律是人在閘門的選擇。
4. `advisor.values_from_config` 的每個值依 `advisor.PARAMS` 檢查型別／範圍／choices；超出→REJECTED。屬 `SCIENCE_SENSITIVE_KEYS` 且有設的→列入 `human_review`（不擋，因 docking_mode／binding／tier 本來就走 plan_workflow，但必須明確交人審）。
5. `advisor.check()`（goal 取法同 Workflow：draft 的 goal 在 GOALS 就用，否則 binding 啟用→binding，否則 teaching）的 error→REJECTED、warning→warnings；評估本身例外→REJECTED（不放行）。
6. 附 `required_features`（資訊用）。

結果：
- 無論結果都在 `<root>/llm_proposals/decisions.jsonl` 用 DecisionLog 記一列（stage `llm.plan_workflow`、kind `proposal`、why 中文、evidence：actor=llm、client（initialize 的 clientInfo）、draft_sha256、proposal 檔名）。
- 只有 ALLOWED 才寫兩個新檔：`<UTC>_<name>_<sha8>.json`（`md20.llm_proposal/1`、`PENDING_USER_CONFIRMATION`、`applied:false`、草稿、sha256、verdict、rationale、client；有戳記）與同 stem 的 `.config.json`（只放草稿本體、無戳記，使用者審查後自行 `md20 pipeline run`）。先寫 tmp 再 `os.link` 建立，**目的地已存在就失敗、絕不覆寫**。
- **不建立專案目錄、不碰任何 workflows/、不執行任何東西**；專案根目錄不存在→ToolError（不替 LLM 建資料夾）。
- sha256 對 canonical JSON（sort_keys、無空白、UTF-8）計算。

### read_report（唯讀，L1 新增）
參數 `project`、`workflow`、`offset`（≥0）、`max_chars`（1–20000，預設 8000）。兩個名稱都省略→列出 `[{project, workflow, status}]`；只給一個→錯誤。名稱必須是安全名（不默默清洗），路徑 `resolve()` 後必須在專案根目錄內（擋 `..`、絕對路徑、symlink 逃逸，含報告檔本身）。回 `status`、`steps`（**只有名稱與狀態，不含閘門訊息／選項**——那是 L2 的 read_problem）、報告 `workflow_report.html` 抽純文字（去 script/style）分頁＋sha256＋bytes；未完成→`report: null`。**絕不回絕對路徑。**

## 4. 證據
- `tests/test_llm_mcp_server.py`（協定層，含官方 SDK 2.3.0 stdio client 互通，SDK 不在就 skip）、`tests/test_llm_tools.py`（工具層）、`tests/test_llm_interface.py`（L0，ACTIONS 7→8）、`tests/test_llm_mcp_e2e.py`（**真的起 `python -m md20 --dir X mcp` 子行程**：只列三工具、stdout 純協定、提議只寫檔不建專案不執行、閘門決定鍵被擋、L2 動作不存在、官方 SDK client 驅動真 CLI）。
- 官方 SDK **只用於測試**，不在任何 environment yml，不是產品依賴。

## 5. 已知限制／刻意沒做
- 協定層 schema 驗證只做頂層（type、required、additionalProperties、enum、min/max）；草稿深層由 `validate_workflow_draft` 負責。
- `human_review` 只涵蓋 PARAMS 讀得到的科學鍵；`receptor` 內容、`box`、`screen.library` 路徑等自由欄位不做 schema 驗證——草稿可能通過、到 `pipeline run` 才失敗；靠使用者審查提議檔。
- 尚無「使用者在 GUI/CLI 檢視並確認提議」的介面：目前確認＝使用者自己看檔、自己跑 `pipeline run`。是否做確認介面屬 L2/L4 範圍，待指派。
- 未支援 `2025-11-25` 協定版本（新增只需改 `SUPPORTED_VERSIONS`，並確認該版要求）。
- 同一連線重複 initialize 視為重新協商；`tools/call` 不要求先收到 `notifications/initialized`。
- 真實 Claude Desktop／Windows 主控台實機連線尚未驗證（待本機／筆電）。

## 6. 想請審查者回答
- `md.replicas` 從決定鍵豁免是否同意（其餘決定鍵含 `screen.next_mode` 一律擋）。
- 提議檔放專案根目錄的 `llm_proposals/`（而非某個專案內）是否合適。
- L2 之前要不要先做「檢視/確認提議」的 CLI（如 `md20 mcp proposals`）。
