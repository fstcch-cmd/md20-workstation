# 能力清單（capability manifest）與膜診斷驗收器（D-136）

狀態：**已實作・純 Python 測試**（`tests/test_capability_manifest.py`、`tests/test_validate_membrane_diag.py`）。真實 CI 結果待下一輪（本 session 沒有推送）。
來源：`docs/specs/evidence_driven_repair_prompt.md` §3 R7（單一能力清單）與 R5 膜部分（診斷與驗收分開）。

## 1. 要解決什麼問題
- 「這個功能到底好了沒」散在 STATUS 的歷史段落、DECISIONS、README 與 CI 留言裡，讀的人要自己拼：哪個是只有單元測試、哪個真實引擎跑過、哪個有對外部參考比對、哪個已經在學生拿得到的安裝程式裡。
- 兩個會讓人誤判的結構：`paper-docking` 是 `continue-on-error`（紅了也不影響整體），`tools/diag_membrane_nan.py` 永遠回傳 0（綠燈什麼都沒證明）。它們的「成功」被讀成資格。
- 版本漂移：`md20/__init__.py` 寫 a19、學生文件叫人下載 `MD20-Windows-v0.1.0a19.zip`，但 GitHub 上最新發行是 a17（a18、a19 從未發行）。

## 2. 單一清單
- **機器可讀**：`docs/capabilities.json`，schema `md20.capabilities/1`。手維護，是唯一來源。
- **人讀**：`docs/CAPABILITIES.md`，由 `python tools/capability_manifest.py --write` 產生，不要手改。
- **只寫現況**。歷史（某個 commit 當時如何）留在 `docs/STATUS.md`、`docs/DECISIONS.md`。清單只引用「最後已知結果」那一筆與它的證據。

### 欄位（每個功能）
`id`、`feature`、`implementation`（檔案或 `檔案::符號`）、`supported_system_types`、`restrictions`、`tests`（`{file, type, ci_job}`）、`states`、`last_known_result`（`status`、`commit`、`evidence_url`、`basis`、`changed_since_evidence`）、`benchmark_scope`、`released_installer`（另附 `released_installer_note`）。

### 五種彼此獨立的狀態
| 狀態 | 值 | 意思 | 不能從哪個推 |
|---|---|---|---|
| implemented | yes／partial／no | 程式存在 | 不代表有測試 |
| synthetic_tested | yes／no | 純 Python、FakeBackend 或合成資料測試通過 | 不代表引擎或科學正確 |
| real_engine_tested | yes／partial／failing／no | 阻擋型 CI job 用真實 OpenMM／Vina／RDKit／mdtraj 跑過 | 不由合成測試推得；跳過不算 |
| scientifically_benchmarked | none／observed／yes | observed = 只有非阻擋／診斷 job 的觀察；yes = 阻擋型 job 對外部參考通過 | 真實引擎通過 ≠ benchmark |
| released_installer | 已發行 tag／`unreleased (main only)` | 哪個 prerelease 含它 | main 通過 ≠ 已發行 |

目前**沒有任何功能是 `scientifically_benchmarked=yes`**。`docking_vina` 是 `observed`（paper-docking 的縮減搜尋觀察，一個案例未重現）。

`last_known_result.status`：`pass`、`fail`、`partial`、`stale`、`unverified`。`stale` = 證據 commit 當時通過，但之後實作或測試檔改過，現況沒有 CI 結果（不能把舊綠燈當現況）。證據基準是 `580cbff`（2026-11-07 最後一輪在 main 完整跑完的 CI，run 42374500293；14 個 job 成功、`heavy[metal]` 失敗）。哪些檔案在它之後改過，用 git blob 比對得到並寫進 `changed_since_evidence`。

### 測試類型與 CI job 類別
`unit`、`synthetic`、`real_engine`、`gui`、`diagnostic`、`benchmark`。清單的 `ci_jobs` 列出每個 workflow job 的類別、是否阻擋、可支持哪些狀態（`counts_for`）。**benchmark 與 diagnostic 類的 job 必須非阻擋且 `counts_for` 為空**——它們的結果只描述特定 protocol 下看到什麼，不能拿來當資格。

## 3. `--check` 擋什麼
`python tools/capability_manifest.py --check`（結束碼 1 = 有問題；CI `pure-python` job 每個矩陣格都跑，成本約 0.1 秒；同樣的邏輯在 `tests/test_capability_manifest.py`）：
1. schema、欄位、各狀態詞彙。
2. 每個 `implementation` 路徑存在，`::符號` 在檔內有 `def`／`class`／賦值；每個測試檔存在。
3. 測試類型與 CI job 類別相符（benchmark 只能在 benchmark job、real_engine 只能在 real_engine job…）。
4. **狀態不互相推論**：`real_engine_tested≠no` 需要阻擋型 real_engine job 裡的 real_engine 測試；`synthetic_tested=yes` 需要 unit／synthetic 測試；`scientifically_benchmarked≠none` 需要 benchmark 測試與非 `none` 的 `benchmark_scope`，`yes` 還要阻擋型 job；`failing` 必須對應 `fail`；`pass／fail／partial／stale` 需要 commit 與 https 證據網址。
5. `released_installer` 必須是 `unreleased (main only)` 或**真的已發行**的 tag（精確比對；`v0.1.0a19` 不會被 `v0.1.0a1` 前綴放行）。
6. 版本：pyproject、`md20.__version__`、清單三者一致；dev 樹的版本不能等於已發行 tag；README 寫出最新已發行版；README／學生文件／快速入門不得叫人下載從未發行的 tag。
7. 每個 workflow job 都列在 `ci_jobs`；`continue-on-error` 的 job 清單必須標非阻擋；**非阻擋、diagnostic、benchmark 的 job，顯示名稱（`name:`）必須含 "not qualification"**；`ci.yml` 必須真的跑這個檢查、`diag-membrane.yml` 必須真的跑驗收器。
8. `docs/CAPABILITIES.md` 與 JSON 同步。

`--stale`（資訊性，永不失敗，需要完整 git 歷史）：列出「狀態寫 pass 但證據之後檔案已改」的功能，提醒下次更新清單時重算。

## 4. 如何更新
改功能或拿到新的 CI 結果時：改 `docs/capabilities.json` 對應功能的 `states`、`last_known_result`（commit 與 URL 只寫你查證過的；沒查證寫 `unverified`）→ `python tools/capability_manifest.py --write` → `--check`。發行後把新 tag 加進 `versions.published_releases`（只在 GitHub 上真的存在時）。

## 5. 膜診斷驗收器（R5）
- `tools/diag_membrane_nan.py` **維持回傳 0**（收集診斷不該因為系統炸掉而丟資料）。D-136 只加輸出欄位，模擬行為不變：`protocol` 區塊（要求的 builds／velocity seeds／steps／最小化次數、`construction_seed`、`construction_seed_varied=false`、未受控的隨機來源）、每個 build 的 `construction_seed`、結束時的 `finished=true`。
- `tools/validate_membrane_diag.py` 讀 `diag.json`：
  - **完整性（會讓結束碼為 1）**：檔案不存在或不可讀、沒有 `finished`、build 或 run 記錄缺少、build 有 `error`、沒有 NaN 卻 chunk 數不足（被截斷）、run 記錄缺欄位、重複記錄、artifact 的 protocol 與要求的 CI 輸入不符、舊格式又沒給期望值（無法判斷完整性）、跨 OS 執行找不到 builds。
  - **觀察（只報告，不判定）**：NaN 的 run 數、短／長最小化各自的計數、每個 build 與每個 velocity seed 的計數；construction（獨立 build 的起始結構雜湊、construction seed）與 velocity seed 變異分開講：只有部分 seed 失敗的 build = 對 velocity seed 敏感；同一 seed 只在部分 build 失敗 = 對 construction 敏感；某 build 全 seed 失敗 = 指向建構本身。run 數少，只是描述。
  - 結論句固定附：這是特定 protocol 下的觀察，不是資格，也不是膜系統穩定與否的一般性陳述。
- **為什麼驗收器只擋完整性、不擋 NaN**：診斷的目的是量化失敗；若 NaN 讓 job 變紅，下一次沒人敢跑診斷。NaN 要不要擋，是回歸測試（`test_membrane_integration`）與科學驗收的事，不是診斷的事。
- **CI**：`diag-membrane.yml` 的 `build` 與 `cross` 在診斷步驟之後各有一個 `if: always()` 的驗收步驟，帶 `--expect-builds／--expect-seeds／--expect-steps`（來自 workflow 輸入），摘要寫進 `$GITHUB_STEP_SUMMARY`，並把 `validation.json` 一起上傳。診斷 job 名稱標 `diagnostic … - not qualification`。
- **誠實限制**：build 的隨機性中，construction seed（膜 plan 的 `seed`，預設 2026）在診斷中**沒有被變動**；獨立 build 之間的差異來自 seed 不控制的步驟。barostat 的亂數種子 md20 不設定（OpenMM 預設）；CPU 加總順序除非 `OPENMM_CPU_THREADS=1` 否則不固定。診斷不能把這三者拆開，所以不能對「是建構還是動力學」下因果結論，只能報告上面的計數樣態。
- 580cbff 診斷 run（42374753967）四個 job 結論 success，但這只代表腳本結束碼 0；STATUS 記載「32 次 0 NaN、對照組 3/32」，本次無法下載 artifact 重讀，所以清單只把它當未重驗的診斷紀錄。

## 6. 版本對齊（R7，延續 D-132）
- 已發行（`gh api repos/fstcch-cmd/md20-workstation/releases`，2026-11-07）：a1–a4、a6–a17，共 16 個 prerelease。**沒有 a5、a18、a19。**
- `pyproject.toml` 與 `md20/__init__.py` 都是 `0.1.0a20.dev0`（之前 `__init__` 還寫 `0.1.0a19`，會被寫進每份報告與專案檔的 `md20_version` 與授權的版本上限判斷）。
- `docs/students/*`、`docs/WINDOWS_QUICKSTART.md` 把『下載 `MD20-…-v0.1.0a19.zip`』改為 a17（真的存在的檔案）。
- `docs/releases/v0.1.0a18.md`、`v0.1.0a19.md` 是從未發行的 tag 的說明草稿；`release-windows.yml` 以 `docs/releases/<tag>.md` 當 release 內文，所以**不在草稿內加橫幅**（會原樣進公開內文），改在清單的 `unpublished_release_note_drafts` 記錄。
- 本任務不建立 tag 或 release。
