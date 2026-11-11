# Spec: LLM 介面定義（L0，D-178）

> **L1 擴充（D-184，2026-11-11）**：ACTIONS 7→8（新增唯讀 `read_report`）、`L1_EXPOSED`、`KNOWN_DRAFT_KEYS`、`PLANNABLE_DECISION_PATHS`、`validate_workflow_draft`；轉接頭本身見 `llm_mcp.md`。

狀態：**[已實作・待 CI]**（純 Python 測試 12 項綠；不需真實引擎）。這是 LLM 編排 track（`llm_orchestration.md`，D-161）的 **L0**——契約層，不是 server、不呼叫 LLM、不套用任何東西。使用者 2026-11-10 指派 L0 實作。

## 要解決什麼
L1 以後的轉接頭（MCP、程式內 BYO-key 面板、REST bot）都要照同一份契約跟 MD20 核心對話。L0 把這份契約先定下來、用測試釘住，讓之後的 server 有穩定的實作目標，也讓審查者在「接任何 LLM 進來」之前先看清楚邊界。

## 內容（`md20/llm/interface.py`）
1. **動作契約 `ACTIONS`**（7 個，對應 `docs/llm/MD20_LLM_GUIDE.md §3`）：`read_capabilities`、`plan_workflow`、`read_problem`、`select_gate_option`、`propose_config_change`、`read_file`、`write_report_narrative`。每個標 `mode`：`read`（唯讀）或 `propose`（只提議）。**刻意沒有** `apply`／`execute`／`write_config`／`edit_code` 之類動作（測試強制）。
2. **只提議、不自動套用（D-177）**：所有 `propose` 動作都只回提議，MD20 要等使用者確認才套用。本模組沒有任何「套用」程式碼路徑。
3. **設定暴露白名單（D-177）**：
   - `SAFE_KEYS`——資源/取樣/輸出旋鈕（`exhaustiveness`、`n_poses`、`padding_nm`、`minimize_iterations/tolerance`、`nvt_ps`、`npt_ps`、`production_ns`、`replicas`、`trajectory_interval_ps`、`window_equil_ps`、`window_prod_ps`、`target_overlap`）。改這些影響成本/取樣/輸出，不動物理模型。
   - `SCIENCE_SENSITIVE_KEYS`——力場/溶劑/離子環境/熱力學狀態/約束/積分步長/tier/SMD 與傘狀力常數/工作流模式。**不可由 LLM 提議**，`validate_proposed_change` 一律 REJECTED 並註明「需人工決定」。
   - 範圍與型別**直接取自 `md20.advisor.PARAMS`**（唯一事實來源，不自行發明數字）。
   - 守衛：測試 `test_no_params_key_is_silently_unclassified...` 斷言 `advisor.PARAMS` 每個鍵都明確落在 SAFE 或 SENSITIVE，之後新增參數必須先分類才可能被暴露（不會默默漏進安全集）。
4. **`validate_proposed_change(key, value)`**：純函式，回 `{status: ALLOWED|REJECTED, reason}`。ALLOWED 僅代表「使用者可以確認」，不套用、不觸發跑。
5. **`capabilities_view(features=None)`**：把 `docs/capabilities.json` 的 features 投影成唯讀視圖（id、feature、states、last_known_status、released_installer），**隱藏 implementation 原始碼路徑**（guide §1 規則 5：LLM 不看核心原始碼）。

## 目前狀態與證據
- `tests/test_llm_interface.py` 12 項綠（動作契約與 guide 一致、無 apply 動作、propose 標記、白名單與敏感集互斥、每個安全鍵有範圍、敏感鍵被拒、無未分類鍵、範圍/型別驗證、capabilities 視圖隱藏 implementation）。
- 容器全套 1503 passed、0 failed。

## 已知限制／邊界
- L0 只是契約與驗證，**沒有任何 server 或 LLM 呼叫**；L1（MCP 轉接頭）才會實作這份契約。
- SAFE/SENSITIVE 的分類本身是設計決定，歡迎審查調整（尤其 `padding_nm`、`target_overlap` 這種邊界）。

## 想請審查者回答
- 白名單分類是否同意（特別是把 `tier`、`timestep_fs`、所有 SMD/傘狀力常數列為敏感、不可由 LLM 動）。
- `capabilities_view` 要不要再收斂（例如連 `states` 細節都簡化）。
