# MD20 決策紀錄

依日期由新到舊。每條：主題｜決定｜理由／取捨｜證據（測試、CI、commit）｜未決問題。
判斷錯誤時在原條目下加「更正」，不刪除原文。子系統細節見 `docs/specs/`。

---

## 2026-11-03

### D-80　專業版：建膜、輸入序列一鍵摺疊、微秒級模擬——先寫規格
- 使用者要求（11/03 14:32）：專業版要能到微秒級以上；建膜功能要完備；整合輕量版 AlphaFold，輸入序列一鍵摺疊胜肽；
  雖然不能穿膜，但使用者可能只要做膜表面接觸。
- 決定：依專案規則先寫三份規格供審查，再分階段實作（每階段要 CI 與實機驗證）：
  `docs/specs/membrane.md`、`structure_prediction.md`、`long_timescale.md`。
- 查證摘要（實作前再確認版本與授權）：OmegaFold（Apache-2.0，單序列）、ESMFold（MIT，完整模型約需 16–24 GB 顯示卡記憶體）、
  Boltz-2（MIT，可預測蛋白＋胜肽複合物，複合物常需 16 GB 以上）、ColabFold（需要 MSA 伺服器與 Linux／WSL）；AlphaFold 3 權重限非商業，不內建。
  Martini 2／3 已有 OpenMM 實作（MacCallum et al., Biophys J 2023）。
- 初步選擇：單獨胜肽預設 OmegaFold；受體＋胜肽用 Boltz-2，記憶體不足時改用上傳或遠端；全原子膜用 OpenMM 建膜（單一中性磷脂）或 MD20 格點排列器（混合膜）；
  微秒以上的膜現象走 Martini 3 粗粒化。
- 被否決：把 AlphaFold2 本體（需要 MSA 資料庫，數百 GB）裝在學生筆電；宣稱全原子膜蛋白可在筆電上常規跑到數微秒（估計需 1–3 週／µs）。
- 未決：力場組合（Lipid21 或 CHARMM36）、格蘭氏陽性菌膜比例與出處、OmegaFold 在短胜肽上的準確度——列在各規格「想請審查者回答」。

### D-79　高通量篩選的範例 Excel 上傳後卡住：改成可直接試跑的範例；發行 v0.1.0a8
- 使用者回報（11/03 14:16）：高通量篩選示範的 Excel 上傳「怪怪的」。
- 原因：範例同時示範六種化合物來源（smiles、pubchem_cid、inchikey、chembl_id、ccd、sdf），其中 `my_compound` 指向不存在的 `my_compound.sdf`，
  另外四列要連 PubChem、ChEMBL、RCSB 下載；篩選預設 `allow_partial: false`，任何一列失敗就停在閘門，所以「原封不動上傳」一定卡住。
  化合物（ATP、imatinib 等）也和範例受體 3PTB 無關，排名沒有教學意義。
- 決定：第一張工作表 `compounds` 只用 SMILES（不需網路），8 個化合物：4 個苯甲脒類胰蛋白酶抑制劑與 4 個對照；
  第二張工作表「說明 How to fill」逐欄說明其他來源各舉一例（讀取只看第一張工作表，不會被誤讀）。CSV 範本只有化合物。
- 證據：`tests/test_screen_library.py::test_template_runs_as_uploaded`、`::test_read_xlsx_and_template_roundtrip`（sdf 相對路徑改用獨立 CSV 測）。
- 未決：使用者說的「怪怪的」是否還包括其他現象（例如 Excel 開啟時的警告），尚待確認。

### D-78　多配體同時對接時所有聯合姿勢都碰撞：改選「進入 MD 風險最低」的姿勢，不再卡住；發行 v0.1.0a7
- 使用者回報（11/03 14:06，截圖）：教學一（hsieh2024）9 個聯合姿勢全部標「碰撞」，流程停在姿勢選擇，課堂卡住；就算點選某一列也會被「請改選」擋下。
  使用者要求：發現碰撞擋下沒錯，但要能合理、安全地進到 MD，提示哪個風險最低，**要通則，不是針對這個範例**。
- 判斷：對接層的「碰撞」（配體間最短距離 < 2 Å）是保守的篩選，不是不能進 MD 的證明。MD20 在建模前本來就有一整套能修復並**驗證**的機制
  （D-60 幾何檢查與剛體微調、D-61 軟核鬆弛、最小化後穿環檢查、漂浮配體自動移出）。在姿勢選擇就擋下，等於不讓這些機制有機會處理。
  依「寧可擋也不要猜」，真正該擋的是無法修復或無法驗證的情況。
- 決定（通則）：
  1. 沒有聯合姿勢通過保守條件時，`Workflow._least_risk_joint_pose` 把**所有**聯合姿勢交給 `multi_ligand.rank_for_md` 排序，依序比較：
     對接層的其他疑點數（分數窗口外、接觸太少、配體分開）→ 建模前的檢查與剛體微調能否解開（0 可直接或微調、1 會排除漂浮配體、2 需軟核）→
     排除的配體數 → 微調後剩餘的重疊與穿環數 → 需要微調的配體數 → 最短接觸距離 → 對接分數。取第一名，決策記為 AUTO_FIXED，理由寫出排序依據與前三名；
     排序表存在 `state["least_risk_poses"]`。
  2. 使用者手動點選的碰撞姿勢不再被「請改選」擋下：記錄決策後交給建模前的幾何檢查。
  3. 仍會停下的情況：redocking 自檢失敗（對接設定本身不可信）、姿勢檔讀不到、建模時軟核鬆弛也解不開（此時請使用者選擇排除哪個配體，原本的 D-60 閘門）。
- 被否決：(a) 直接放寬碰撞門檻——會把真正穿插的姿勢當成正常；(b) 只在教學模式放行——使用者要通則；(c) 用分數最佳的碰撞姿勢——分數不反映能否安全進 MD。
- 證據：`tests/test_multi_ligand_geometry.py::test_rank_for_md_prefers_the_pose_that_can_be_repaired`、
  `tests/test_workflow_gates.py::test_all_joint_poses_clashing_takes_the_least_risk_pose`、`::test_failed_redocking_still_stops`；純 Python 測試全過。
- 版本：使用者要求「第五版」發行；v0.1.0a5 的發行在 13:3x 被 GitHub 拒絕而沒有發出，v0.1.0a6 已發行，版本號必須遞增，所以這版是 **v0.1.0a7**。

### D-77　Windows 啟動檔遇到很長的 PATH 時失敗（The input line is too long）；發行 v0.1.0a6
- 使用者回報（11/03 13:30，照片）：執行 `%LOCALAPPDATA%\MD20\MD20-GUI.cmd` 出現「The input line is too long. The syntax of the command is incorrect.」。
- 原因（判斷）：`micromamba run` 在 Windows 以 cmd 腳本啟用環境，把環境的資料夾加到 PATH 前面；這台筆電裝過 conda、MGLTools、PyMOL 等，PATH 本來就很長，
  加上去後超過 cmd 單行 8191 字元的上限，MD20 還沒開始就失敗。CI 的乾淨 runner PATH 很短，所以從沒測出來。
- 決定：`md20.cmd` 與 `MD20-GUI.cmd` 在呼叫 micromamba 前把 PATH 換成短的系統路徑（system32、Windows、Wbem、PowerShell、NVIDIA NVSMI）。
  MD20 不依賴使用者 PATH 上的任何東西（Vina 以絕對路徑找、OpenMM 用環境內的 DLL、NVIDIA 驅動在 system32）。只影響這兩個啟動檔的視窗，不改系統設定。
  CI installer-windows 與發行的 verify-windows：雙擊桌面啟動檔前把 PATH 加長到約 8,000 字元，仍須在 http://127.0.0.1:8020 回 200。
- 當下的暫時解法（已告訴使用者）：在 cmd 先 `set PATH=C:\Windows\system32;C:\Windows;C:\Windows\System32\Wbem` 再執行啟動檔。
- 被否決：繞過 micromamba 直接執行 envs\md20\python.exe——要自己重建環境啟用時的 PATH 與變數，改動較大；在發行前時間有限。
- 證據：`tests/test_installer_paths.py::test_windows_launchers_start_from_a_short_path`；發行流程的長 PATH 桌面啟動檢查。
- v0.1.0a5（只含 D-76）在發現本問題時已在發行中，未取消（取消 CI 曾被拒絕）；請一律用 a6。
- 結果：a5 的發行在建立 Release 時被 GitHub 拒絕（403），沒有發出；**a6 發行成功**（release run 41584490507），verify-windows 以 10,104 字元的 PATH 雙擊桌面啟動檔，介面回 200。

### D-76　Windows 桌面的 MD20-GUI.cmd 打不開介面；發行 v0.1.0a5
- 使用者回報（11/03 13:24）：GUI 打不開。筆電桌面的 `MD20-GUI.cmd` 內容是 `"%~dp0micromamba.exe" run -p "%~dp0envs\md20" md20 gui`。
- 原因：安裝器（自 11/01 的 1b8117b 起）把 `%LOCALAPPDATA%\MD20\MD20-GUI.cmd` **原樣複製**到桌面；`%~dp0` 是「這個 .cmd 所在的資料夾」，
  在桌面上就變成桌面，找不到 micromamba.exe 與環境，視窗一閃即關。CI 只檢查安裝目錄裡的啟動檔存在，從沒雙擊過桌面那一份，所以一直沒被發現。
  先前筆電能開 GUI，是透過自測腳本或安裝目錄裡的啟動檔。
- 決定：桌面啟動檔改為一行 `call "<安裝目錄>\MD20-GUI.cmd"`（絕對路徑；`-Encoding Default` 讓中文使用者名稱的路徑也正確）。
  installer-windows（CI）與 verify-windows（發行）新增步驟：真的執行桌面啟動檔，等 http://127.0.0.1:8020 回 200 才算通過。macOS 的桌面啟動檔本來就用絕對路徑，不受影響。
- 已安裝 a4 的人不必重裝：用 `%LOCALAPPDATA%\MD20\MD20-GUI.cmd` 開啟。
- 證據：`tests/test_installer_paths.py::test_desktop_gui_launcher_points_at_the_install`；發行流程的桌面啟動檢查。
- 版本：0.1.0a5（只改安裝器與 CI；程式碼與 a4 相同）。

### D-75　教學前清理舊文件：移到 `docs/archive/`，不刪除
- 使用者要求（11/03 13:01）：清理舊的 Markdown，準備教學。
- 決定：把已過時或只具歷史價值的文件**移到 `docs/archive/`**（交接快照、11/01 審查、筆電 session 守則、規格審查問答、被取代的第一版規格、a1–a3 發行說明、筆電 3PTB 重分析圖），
  並更新所有現行文件與 CLAUDE.md 的連結；`docs/archive/README.md` 列出每個檔案是什麼。
- 理由：專案規則要求不刪除歷史（判斷與證據要可追溯），移動同樣讓 `docs/` 只剩教學與開發會用到的文件；git 也保留完整歷史。
- 被否決：直接刪除（違反「不刪歷史」，且 DECISIONS 舊條目引用這些檔案）。
- 留在原處：學生 `docs/students/`、`README.md`、`docs/TEACHING.md`、`docs/WINDOWS_QUICKSTART.md`、`docs/WORKFLOW.md`、`docs/STATUS.md`、`docs/DECISIONS.md`、
  `docs/COMPATIBILITY.md`、`docs/HANDOFF.md`、`docs/WORKBOARD.md`、`docs/specs/`（現行規格）、`docs/releases/v0.1.0a4.md`。

### D-74　介面、報告與學生文件改寫成人寫的語氣，並新增日文與韓文；發行 v0.1.0a4
- 使用者要求（11/03 09:31）：用語太有 AI 感（AI 常用的斷句與符號），請改寫；新增日文與韓文。範圍（使用者在選項中選定）：
  改寫涵蓋介面、報告與學生文件；日韓文加到介面、報告與學生說明。09:50 追加：改完後自己進介面檢查，確認切換語系穩定、不會中斷任何工作，再發行第四版。
- 找 skill：使用者的 skill 庫沒有改寫或翻譯相關的 skill，所以直接依自訂規範改寫（`docs/specs/writing_style.md`）。
- 決定：
  1. `md20/i18n.py`：四種語言 `LANGS = en, zh, ja, ko`，文字一律寫成 `(zh, en, ja, ko)`；`pick()` 解析，缺日韓文時退回英文。
     中、日文用全形標點，韓、英文用半形（`cjk()`、`colon()`、`paren()`、`stop()`）。原本散在各處的 `if lang == "zh"` 全部改掉。
  2. 改寫規則：去掉破折號接子句、冒號與分號串句、層層括號、「／」當「或」、句中箭頭、套話與硬湊三項；數字、門檻、單位與科學判斷不變。
  3. 不翻譯：DecisionLog 的 `why`（專案規則：中文）、命令列、`drivers.py`／`platforms.py`／`winfix.py` 的診斷文字（在報告與電腦狀態頁以原文顯示）。
  4. 報告的方法段落日文用である調、韓文用 -했다，因為是要貼進論文的文字。
  5. 學生文件：`docs/students/` 四語版本（繁中為原檔，另加 `.en.md`、`.ja.md`、`.ko.md`）。
- 被否決：以英文字串為鍵的翻譯目錄（`ja.json`、`ko.json`）在執行時比對——大量 f-string 是先組好才翻譯，比對不到就會中英夾雜；
  文字與程式放在一起改，佔位符在各語言裡都由 Python 填入，不會漏。
- 介面檢查與語系穩定性：開發容器裝不了 NiceGUI（PyPI 被擋；從 GitHub 原始碼執行外部套件被安全規則拒絕），所以改在 CI 用真的 NiceGUI 與 Chromium 檢查：
  `tools/gui_preview.py` 四種語言各頁截圖，並用 `MD20_GUI_FAKE_RUN`（Runner 以計時替身代替化學計算，其餘頁面、Runner、忙碌橫幅、語言選單都是正式程式）
  從教學頁啟動計算，計算中依序切換四種語言、每次離開再回來並再按「開始」；必須只啟動一次、持續有進度、只有一個流程，否則 CI 失敗。
- 證據：`tests/test_i18n_coverage.py`（i18n_scan 為 0）、`tests/test_gui_stability.py::test_fake_run_counts_starts_and_beats`、純 Python 測試全過、
  CI `gui-preview` 的 `stability.txt` 與截圖（gui-preview 分支）。
- 版本：0.1.0a4（`pyproject.toml`、`md20/__init__.py`），發行說明 `docs/releases/v0.1.0a4.md`。
- 未決：日韓文未經母語者校對；3D 檢視器以外的舊版 v1 表單函式仍有中文。
- 介面檢查結果（CI gui-preview，bffc0e9）：`stability.txt` = OK——計算中切換 zh→ja→ko→en，每次離開再回來並再按開始：始終只啟動 1 次，進度 13→22→30→38 持續增加，只有一個流程。
  我逐張看了日文與韓文截圖（首頁、教學二、專業模式、流程頁）：文字完整、無亂碼或缺字，資源選單與語言選單顯示正確。發現兩個問題並修正：
  (1) 空表格顯示 Quasar 的英文「No data available」（Quasar 語言在伺服器啟動時固定）→ 每個表格設 `no-data-label`；
  (2) 首頁「最近的流程」的時間是 UTC 原始字串、步驟與狀態是程式代碼（md_cases、PASS）→ 改為本機時間與所選語言的名稱。
- **更正（CI bffc0e9，03:28 UTC）**：openmm-stack（Ubuntu、macOS 各 1 失敗／488 通過）與 heavy workflow 紅。原因都是只在真環境跑的測試仍斷言改寫前的中文：
  `test_gui_server` 找「需要在程式外處理」（現為「以下要在程式外處理…」），`test_full_workflow_3ptb` 找報告裡的「production 軌跡」（現為「正式模擬軌跡」）。
  科學結果都通過（3PTB 全流程 binding PASS）。改寫時各子代理只能跑純 Python 測試，這兩處沒被抓到——之後改用語要先 grep 只在 CI 跑的測試。
- **發行（12:5x）**：使用者要求 13:00 前發行第四版。49e2eae 的 CI 14／15 綠，只剩 Windows openmm-stack 在跑；判斷：該 commit 相對於上一輪全綠的程式只改了文字、
  測試斷言與報告 3D 檢視的語言參數，Windows 的安裝與純 Python 測試已綠，發行流程本身還會在乾淨 Windows 與 macOS 實裝驗證——風險低，於是先發行，
  Windows openmm-stack 結果出來後補記在此（若紅，修正後發 a5）。**補記（13:09）：Windows openmm-stack 綠（490 passed、6 skipped），發行點 15 個 job 全綠，不需要 a5。**release run 41579558389：verify-windows、verify-macos 通過。
  同時修正：報告的 3D 檢視沒有把語言傳給 `viewer_targets`／`viewer_html`，英日韓報告的檢視器標題與按鈕會是中文。發行改等新一輪 CI 全綠。

### D-73　全部文件與 v0.1.0a3 同步
- 使用者要求（11/03 09:03）：遍歷 GitHub 上所有文件，全部更新為與最新版一致。
- 決定（文件的寫法規則）：
  1. **範例專案名稱一律英數字**（`first_case`、`classA`、`screen_test`）：D-67 起中文名稱會變成「英數＋亂碼」資料夾（`測試` → `item_xxxxxx`），學生找不到。
  2. **時間只寫實測或標明估算**：classroom 3PTB 全流程 76.5 分鐘（RTX 4060，a1 實測）；teaching 約 3 小時是估算（2×10 ns MD＋傘狀約 16.5 ns，約 330 ns/day）；
     Mac 2–4 小時是估算。舊的「classroom 20–40 分鐘」「teaching 1–1.5 小時」沒有依據，已改。
  3. 介面文字照程式實際顯示寫（資源選單：「省資源：可同時寫報告」／「平衡（預設）」／「全速：電腦閒置時」，下一個計算步驟起生效）。
  4. **歷史文件不改寫**：`DECISIONS.md` 舊條目、`releases/v0.1.0a1.md`、`v0.1.0a2.md`、`REVIEW_*`、`HANDOFF_2026-11-02.md`、`specs/docking.md`、`specs/gui.md` 保留原文；
     需要時在檔頭加「後續」說明（HANDOFF_2026-11-02），規格檔在狀態行下加「2026-11-03 更新」。
- 更新的檔案：README、CLAUDE.md、HANDOFF、HANDOFF_2026-11-02（檔頭）、STATUS（開頭「目前版本」）、COMPATIBILITY（發現的處置）、WINDOWS_QUICKSTART、LAPTOP_SESSION、WORKFLOW、TEACHING、
  students/WINDOWS、students/MAC、releases/v0.1.0a3（補 D-64–D-72）、specs/README（狀態；補登 gui_v2、multi_ligand、report_language）、
  specs 的 umbrella_adaptive、implicit_solvent、solvent_box、pbc_centering、gui_v2、drivers、restraints_freeze_truncation、ci_validation。
- 更正的錯誤敘述：預設拉速 0.01 → 0.005（WORKFLOW）；hsieh2025 的 CPP「擋下」→ 只提醒（HANDOFF、STATUS、ci_validation；D-48）；CI「cancel-in-progress」→ main 不取消（HANDOFF）；
  最新 Release a1 → a3（LAPTOP_SESSION）；commit 屬名格式（CLAUDE.md、HANDOFF）。
- 未決：GitHub Release 頁面上的說明仍是發行當時的版本（本 session 無權編輯 Release，HTTP 403），需使用者把 `docs/releases/v0.1.0a3.md` 貼到 Release 的 Edit；claude.ai 上的「安裝與使用說明」文件（非 repo）不在本次範圍。

### D-72　vina.exe 只用約 4 執行緒：Vina 本身不限制，是 Windows 11 的 QoS 把它排到節能核心（推測，附量測）
- 使用者要求（11/03 08:35）：調查 D-68／D-70／D-71 留下的「多配體對接 vina.exe 只用約 4 個 CPU 執行緒（約 24%）」。
- **讀原始碼的結論（AutoDock-Vina main，`src/lib/vina.cpp` `global_search`、`parallel_mc.cpp`、`parallel.h`）**：
  Vina 的平行只有一處——蒙地卡羅搜尋開 `--cpu` 條執行緒，分配 `exhaustiveness` 個互相獨立的工作（含多配體時也一樣，每個工作複製整個模型）；
  格點圖計算（`cache::populate`）與最後的精修是單執行緒。`--cpu 16`、exhaustiveness 32 時搜尋階段應該 16 條全忙。
  所以 **D-70 更正中「限制來自 vina.exe 本身」是錯的**（見下方更正），程式裡沒有任何會把多配體對接限制在 4 條的機制。
- **最可能的原因（推測，待筆電驗證）**：Microsoft 文件〈Quality of Service〉：擁有視窗的程序**及其子孫**依視窗狀態取得 QoS——
  前景 High、可見未聚焦 Medium、**最小化或完全被遮住 Low**；Low 在混合架構上排到**節能核心**（文件寫「用電池時」，
  但多份實測回報插電時最小化視窗的程式也只跑 E-core）。MD20 的 GUI 是從主控台視窗啟動的 Python，vina.exe 是它的子孫；
  學生看的是瀏覽器，主控台視窗被蓋住或最小化 → vina.exe 被降為 Low QoS。i7-13620H 有 4 個 E-core＝16 執行緒的 25%，
  與觀察的 23.7%／24.5% 一致；優先順序「標準」、親和性全勾也不影響 QoS，與使用者 00:20 的檢查一致。
- 決定：
  1. `winfix.set_power_throttling()`：vina.exe 一啟動就以 `SetProcessInformation(ProcessPowerThrottling)` 明確標記——
     平衡／全速為 **HighQoS**（ControlMask＝EXECUTION_SPEED、StateMask＝0；文件：明確標記的程序取代依視窗判定的等級），
     省資源為 **EcoQoS**（使用者選了省資源，本來就該留在節能核心、讓出效能核心寫報告）。
  2. **量測而不是猜**：`vina_cli._run_measured` 記錄每次 Vina 的 CPU 秒數／牆鐘秒數＝實際平均執行緒數
     （Windows `GetProcessTimes`、其他 `getrusage`），連同要求的執行緒、exhaustiveness 寫入對接結果 `params.vina_runs` 與 DecisionLog `docking.run/cpu_use`。
     實際值低於上限 min(--cpu, exhaustiveness) 的一半且執行超過 2 分鐘時，`why` 直接寫出可能原因與處理方式。這是速度提示，不是閘門：對接結果不受影響。
- 附帶說明（不是錯誤）：D-71 課堂 exhaustiveness 8 在 16 執行緒筆電上**最多只會用 8 條**（約 50%），這是 Vina 的設計；
  在 16 執行緒機器上改 16 的牆鐘時間大致相同（一輪即完成），但不同學生電腦執行緒數不同，若依機器調整，同一題各人結果會不同——
  為了課堂可重現，**暫不自動調整**，留給使用者決定。
- 被否決：(a) 把 vina.exe 親和性綁到 P-core——要辨識核心型別、各機型不同，且 QoS 仍可能覆蓋；(b) 要求學生把主控台視窗留在前景——
  可作為暫時的手動驗證，但不能當解法；(c) 改用 `--batch` 或逐一對接——平行度相同，且換掉教學一的科學問題（D-71 已否決）。
- 驗證方法（使用者可在 1 分鐘內做）：對接進行中把 MD20 的黑色主控台視窗**切到前景**，看工作管理員 vina.exe 是否從約 25% 升到接近 100%；
  再最小化，看是否掉回 25%。新版會在報告的決策紀錄顯示「實際平均 X 條執行緒」，X 接近 16（全速）即確認修正有效。若仍約 4，本推測錯誤，在此更正。
- 證據：`tests/test_vina_cpu_use.py`（子程序量測：忙碌約 1 條、閒置約 0 條；判讀文字；Windows CI 上 `SetProcessInformation` 回傳成功、
  vina 子程序 qos＝high）；`tests/test_installer_paths.py::test_vina_executable_always_gets_cpu`（改用 `_run_measured`）。
- 相關檔案：`md20/env/winfix.py`、`md20/env/resources.py`（`child_eco_qos`）、`md20/docking/vina_cli.py`、`md20/docking/run.py`、`docs/specs/docking.md`。
- 未決：筆電實測確認（需要使用者在新版上再跑一次對接）。
- **使用者決定（11/03 08:50）**：直接定案，不做筆電驗證、不再監控，推上 GitHub 後發行 v0.1.0a3。D-72 以「推測＋每次執行量測」狀態出貨；學生電腦上的實際執行緒數會寫在報告決策紀錄，若顯示偏低再更正。

## 2026-11-02

### D-71　教學一（多配體同時對接）的課堂搜尋強度改為 8；研究等級保留論文的 32
- 事實（筆電 2026-11-03，a3 候選版，資源模式全速）：教學一六個代謝物同時對接、exhaustiveness 32，**00:12 開始，02:28 仍未完成（> 2 小時 16 分）**；
  vina.exe 全程約 25% CPU（D-68／D-70：約 4 個執行緒，原因在 vina.exe 本身）。CI 以 exhaustiveness 8 重現同一對接，兩篇論文合計 25 分鐘（4 vCPU），
  並涵蓋論文報告的結合位置殘基（paper-docking 留言 `hsieh2024_*`）。
- 決定：`hsieh2024.workflow_config` classroom／teaching 用 8、research 用 32；教學頁的參數表與步驟說明寫明「論文 32、課堂 8、為什麼、怎麼改回」。
  這是課堂可行性的取捨，不是說 8 和 32 一樣好：搜尋強度低時聯合姿勢的分數較不穩定，報告仍會標明實際使用的值。
- 被否決：先逐一對接（independent）再同時對接——更快，但教學一的科學重點正是「六個一起放進口袋能不能共同佔位」；改模式等於換題目。
- 證據：`tests/test_gui_stability.py::test_teaching_one_docks_at_classroom_effort_and_research_keeps_the_paper`。
- 未決：本次筆電對接最終耗時（若完成）補記於此；vina.exe 多配體時只用約 4 執行緒的根因（→ D-72：Windows QoS，待實測確認）。

### D-70　Windows 混合架構 CPU：Vina 的優先權依資源模式設定（低優先權被排到節能核心）
- 事實（筆電 2026-11-03 00:12，D-68 的 `--cpu` 已生效、資源模式「全速」）：vina.exe 仍是 **24.5%**、記憶體 1,445 MB，與 23:50 幾乎相同。
- 判斷（**推測，待驗證**）：i7-13620H 為 6 P-core（12 執行緒）＋ 4 E-core，16 執行緒的 25% 恰為 4 個執行緒＝4 個 E-core。
  Windows 11 的排程（Thread Director／EcoQoS）把低於一般優先權的程序排到 E-core；MD20 自己降為 below normal，vina.exe 繼承，
  因此 `--cpu` 再大也只用到 E-core。資源模式只在 MD 後端建立時套用 `apply_priority`，對接階段沒有依模式設定。
- 決定：`resources.child_creationflags()`——平衡與全速以 **NORMAL_PRIORITY_CLASS** 啟動 vina.exe（平衡仍只給 n−2 個執行緒，電腦可用）；
  省資源為 IDLE（刻意留在節能核心）。其他作業系統沿用繼承。
- 驗證計畫：下一次筆電對接時，工作管理員 vina.exe CPU% 應明顯高於 25%（全速接近 100%、平衡約 85%）。若仍約 25%，推測錯誤，改查 Vina 多配體演算法的平行度並在此更正。
- 證據：`tests/test_installer_paths.py::test_vina_priority_follows_mode_on_windows`（Windows CI）。
- **更正（2026-11-03 00:20，使用者實機檢查）**：工作管理員「詳細資料」中 vina.exe 的優先順序已是**標準**、處理器親和性**16 個全勾**，
  CPU 仍約 24%。所以「低優先權被排到 E-core」的推測**錯誤**；限制來自 vina.exe 本身（多配體同時對接時實際只跑約 4 個執行緒），
  不是 Windows 排程。依模式設定子程序優先權仍保留（省資源模式需要它，對平衡／全速無害），但它**不能**解決這個問題。
  後續：查 Vina 1.2 多配體對接的平行度，必要時調整教學一的對接策略（見 HANDOFF 未決）。
- **更正（2026-11-03，D-72）**：讀 Vina 原始碼後，Vina 本身沒有把多配體對接限制在 4 條執行緒的機制（搜尋階段開滿 min(--cpu, exhaustiveness) 條）。
  「限制來自 vina.exe 本身」的判斷錯誤。上面原本的推測方向（Windows 把它排到 E-core）可能是對的，但機制不是優先權，而是**依視窗可見度決定的 QoS**；
  處理見 D-72。


### D-69　Windows：關掉 MD20 視窗時，子程式（vina.exe）必須一起結束
- 事實（使用者 2026-11-03 00:08）：關掉 GUI 黑色視窗後，舊的 vina.exe 仍在跑（Windows 不會連帶結束子程式）；重開 GUI 後新舊兩個對接同時搶 CPU，
  無法測「全速」的真實狀態。稍早工作管理員看到的 23.7% 很可能就是孤兒程序。
- 決定：`md20` 一啟動（CLI 與 GUI 共用入口）就以 `winfix.kill_children_on_exit()` 把自己放進 Windows Job Object（KILL_ON_JOB_CLOSE）；
  子程式繼承這個 job，主程式因任何原因結束（含關閉命令視窗、當機）時，系統一併結束子程式。失敗時不擋啟動（回傳 False）。
- 證據：`tests/test_winjob.py`（Windows CI：父程序綁 job 後啟動 ping，`os._exit` 突然結束，子程序必須在 10 秒內消失）。
- **更正（2026-11-03 01:50，CI c4d7232 Windows 紅）**：`kill_children_on_exit()` 在 Windows 回傳 False——沒有宣告 `argtypes`，64 位元的
  job／process handle 被 ctypes 當 32 位元 int 傳遞而失敗（例外被吞掉）。也就是 D-69 原版在 Windows 上**沒有作用**，是新測試抓到的。補上四個 API 的 `argtypes`／`restype`。
- 被否決：atexit／signal 清理（關閉命令視窗時常常來不及執行）；啟動時掃描並結束「看起來是孤兒」的 vina.exe（可能誤殺使用者自己開的 Vina）。
- 未決：GUI 啟動時偵測到既有孤兒 vina.exe 時是否提示使用者（目前只在說明文件寫明手動結束）。

### D-68　Windows vina.exe：一律傳 `--cpu`；多配體同時對接的時限依配體數放寬
- 事實（筆電 2026-11-02 23:05–23:50，a3 候選版，教學一 hsieh2024 六個代謝物 simultaneous、exhaustiveness 32）：對接 45 分鐘仍無輸出；
  工作管理員 vina.exe **CPU 23.7%**（16 個邏輯 CPU 中約 4 個），總 CPU 26%，沒有其他負載。CI（Linux、Python bindings）兩篇論文對接重現共 25 分鐘。
- 判斷：MD20 呼叫 vina.exe 時 `cpu=0` 就不傳 `--cpu`，由 vina.exe 自行決定；資源模式 balanced 只降優先權、不限核心數，不是原因。
  **未確認**是否就是 vina.exe 預設的執行緒數不足（也可能是多配體演算法某階段只用少數執行緒）——以下一次筆電實跑的工作管理員 CPU% 驗證。
- 決定（使用者 23:52：「讓使用者自己調配資源，學生只有一台電腦，CPU 全開不利於做報告」）：
  - **資源用量由使用者選**：GUI 頁首「資源用量」三選一並記住（`gui_settings.json`）——省資源（¼ 個 CPU、最低優先權、GPU 50%，可同時寫報告）／
    平衡（預設，留 2 個 CPU、較低優先權、GPU 85%）／全速（全部、電腦閒置時）；命令列沿用 `md20 --mode`。設定經環境變數 `MD20_RESOURCE_MODE`
    傳到 Vina 等深層呼叫，下一個計算步驟起生效。
  - `run_vina_cli` 一律傳 `--cpu`＝所選模式的執行緒數（平衡：16 個邏輯 CPU 的筆電為 14）；
  時限由固定 2 小時改為 2 小時＋每多一個配體 1 小時（六配體 7 小時），避免慢但正常的同時對接被逾時中斷而整個流程報錯。
- 證據：`tests/test_installer_paths.py::test_vina_executable_always_gets_cpu`。待筆電驗證。
- 未決：若傳 `--cpu 16` 後 CPU 仍約 25%，教學一的預設對接強度（exhaustiveness 32、同時對接）對筆電可能太重，考慮教學層級改 16 或先 independent 再 simultaneous。

### 觀察（未改程式）：CI f558059 `heavy (pose-screen)` 紅
- 短 MD 篩選的 NPT 延長兩次後 `density_drift` 仍未通過 → 閘門擋下（行為正確：不以其他 pose 代替），但測試預期的是「都不穩定」訊息。
  前兩輪（617658e、5021a3a）同一程式路徑通過；今晚的改動（D-62–D-67）未觸及 MD 或驗收。判斷為短 MD 的隨機性（CPU Reference、短 NPT）。
- 發行前不動 MD 驗收門檻；若下一輪仍紅，再檢查篩選用 NPT 長度（50 ps）是否太短。

### D-67　GUI 執行穩定性：切換語言／離開再回來不得重跑；同時只跑一個計算；時間顯示本地時間
- 事實（使用者筆電 2026-11-02 22:36–22:57，a3 候選版，教學一 hsieh2024）：
  1. 英文介面開始教學 → 專案 `Teaching`；切到中文後再按開始 → 教學頁以 `"教學"` 為專案名，`safe_name` 把非 ASCII 全濾掉成預設 `project`，
     找不到既有流程 → **在 `project/` 從頭重跑**；同一個 GUI 程序同時跑兩個相同案例（PID 26016），互搶 CPU。
  2. 離開進度頁再回來，找不到回到正在跑的流程的入口（計算其實仍在背景）。
  3. 時間軸顯示 UTC（14:51:30），使用者在台灣是 22:51。
- 決定（通則）：
  - 教學專案名固定 `Teaching`，與介面語言無關。
  - `safe_name`：名稱含非 ASCII 時保留 ASCII 部分並附原名 SHA-1 前 6 碼（`教學`、`測試` 不再都變成同一個資料夾；路徑仍是 ASCII，避免 cp950 問題）。
  - `Runner`：**同一台電腦同時只跑一個計算**；有計算在跑時再按開始，回傳正在跑的那一個並導向它（不另開）；新建流程只建立不啟動並提示。
  - 每一頁頁首常駐「計算進行中：專案／流程　回到進度」。
  - 時間：檔案仍存 UTC（跨時區可比對），顯示一律轉本機時間（`timeutil.to_local`；時間軸、步驟表）。
- 仍成立的設計：關掉**瀏覽器**不影響計算；關掉**黑色命令視窗**＝停止 GUI 程序，計算中斷，重開後在流程頁按「開始／繼續」從已完成的步驟接續（每步與每個 MD chunk 都已存檔）。
- 證據：`tests/test_gui_stability.py`（名稱不碰撞、本地時間、單一計算、教學專案名）；頁面繪製由 CI 的 GUI 伺服器測試。
- 未決：關掉命令視窗時跳出確認、或把計算改為獨立於 GUI 的背景服務（重開 GUI 自動接回）——後者是較大的改動，a3 之後評估。

### D-66　macOS 版：與 Windows 相同的安裝版面、`Install-MD20.command`、CI 與發行時在 Mac 實裝驗證（使用者：週二 09:00 要 Windows＋Mac 兩版與學生說明）
- 事實：`install.sh` 的 macOS 分支只建環境，從解壓資料夾 editable 安裝（刪掉資料夾就壞）、沒有啟動器、沒有任何 CI 走過這條路；發行只有 Windows ZIP。
- 決定：
  - `install.sh`（macOS／Linux）：安裝位置預設 `~/MD20`（學生找得到；原 `~/.local/share/MD20` 為隱藏資料夾），非 git 副本時程式複製到 `~/MD20/app`，
    舊版移到 `_to_delete/app-<時間>`（不刪，D-37）；啟動器 `~/MD20/md20`（命令列）與 `MD20-GUI.command`（複製到桌面）；`md20 setup-vina`；訊息中英並列。
  - repo 根目錄 `Install-MD20.command`（Finder 雙擊或 `bash Install-MD20.command`）；`.gitattributes` 讓 `*.command`／`*.sh` 保持 LF、git 記錄可執行權限。
  - CI 新增 `installer-macos`：以 `git archive` 匯出（無 .git，等同發行 ZIP）→ 執行 `Install-MD20.command` → 刪除匯出資料夾 → doctor／demo／pipeline example／GUI 啟動器存在。
  - 發行 workflow：同一個 ZIP 另存 `MD20-macOS-<tag>.zip`；新增 `verify-macos`（`ditto` 如 Finder 解壓、安裝、刪除解壓資料夾後仍可用），兩個平台都通過才發行。
  - 學生說明：`docs/students/WINDOWS.md`、`docs/students/MAC.md`（指令可直接複製）。
- 取捨（時間限制下）：Mac 不做 .app／簽章（Gatekeeper：說明改用 `bash` 執行安裝檔；桌面啟動器由安裝程式在本機產生，不帶隔離屬性）；
  Mac 只在 CI runner（Apple Silicon、無 GPU 實測）驗證，**沒有真機**；Mac 學生預設建議 classroom 等級。
- 證據：待 CI `installer-macos` 與發行 `verify-macos`。
- **更正（2026-11-02 23:50，CI f558059 `installer-macos` 紅）**：`install.sh: line 76: ROOT（: unbound variable`。macOS 內建 bash 3.2 把緊接在 `$ROOT` 後的全形「（」
  的位元組當成變數名的一部分（Linux 的 bash 5 不會），`set -u` 即中止。所有 `$變數` 緊接非 ASCII 處改為 `${變數}`（install.sh 5 處、Install-MD20.command 1 處），
  並加測試 `test_shell_scripts_never_follow_a_variable_with_non_ascii`。


### D-65　ΔPMF 只有在 PMF 末端持平時才是「井深」；報告寫出 MBAR 截斷改用 WHAM
- 事實：筆電兩次 3PTB 的報告值 80.3／80.6 kJ/mol 都是曲線在約 0.5 nm 被截斷時、仍在上升的邊緣值（D-62）。
  截斷只是原因之一；拉離距離不夠、盒子太小也會讓曲線末端未持平，同樣不能稱為井深。
- 決定（通則）：`radial_pmf` 以「最外側 window 平均」以內的尾段 10% 做直線擬合，尾段變化 > 1 kT → `plateau=False`，
  ΔG° 不輸出並寫明理由（建議加長 `pull_distance_nm` 或檢查盒子）；只到最外側 window 平均是因為更外側的 bin 只被單一 window 的尾巴取樣（邊緣假象）。
  `quality["sampled_nm"]` 記錄取樣範圍。D-62 的 MBAR→WHAM 替換在報告注意事項中明列（範圍、改用的估計器）。
- 證據：筆電真實樣本——classroom／teaching 全範圍：尾段變化 0.58／0.005 kJ/mol（持平）；截斷到 0.54 nm：8.1／7.5 kJ/mol（擋下）。
  `tests/test_pmf_plateau.py`（持平、截斷、邊緣假象）。
- 被否決：用整條曲線最大值當平台（截斷或上升時同樣錯）；1 kT 以外的固定 kJ/mol 門檻（與溫度無關不合理）。

### D-64　軟核修復（D-61）的平底保持半徑 0.3 → 0.2 nm：自由漂移必須小於接受上限
- 事實：CI 617658e，`test_softcore_unthreads_and_keeps_the_ligand_near` 三個 OS 同樣失敗——**穿環已解開**，但配體移動 RMSD 3.38 Å > `ACCEPT_RMSD_A` 3.0 Å。
- 原因判斷：配體質心的平底保持在 `hold_nm`＝0.3 nm（3 Å）內**完全無力**，6 段 × 1 ps、300 K Langevin 期間質心在區內隨機漂移；
  自由漂移範圍等於接受上限，正確解開的配體也有相當機率被判「已是不同姿勢」→ 實際建模時會把可修好的案例送去 NEEDS_HUMAN。
- 決定：`HOLD_NM = 0.2`（2 Å），接受上限維持 3.0 Å 不放寬；新增測試保證自由半徑 ≤ 上限 − 0.5 Å。解開穿環所需的位移是一個鍵長量級（約 1.5 Å），2 Å 足夠。
- 被否決：把 `ACCEPT_RMSD_A` 放寬到 3.5 Å（只是讓測試過，且讓真正換了姿勢的結果被接受）。
- **更正（2026-11-02 23:50，CI f558059）**：保持半徑 0.2 nm 後 RMSD 3.38 → **3.22 Å**，仍 > 3.0。判斷錯在把「整體 RMSD ≤ 3 Å」當作同一姿勢的標準：
  把穿過環的一根鍵抽出來，該端至少要移動「環半徑＋接觸距離」（約 2.5–3.5 Å），小配體的整體 RMSD 必然接近或超過 3 Å。
  改為：**質心移動 ≤ 2.5 Å（`ACCEPT_CENTROID_A`）＋蛋白接觸保留（原有）**判定結合模式；整體 RMSD 只作 4 Å 的防翻轉上限。保持半徑 0.2 nm 保留（自由漂移 < 質心上限）。
  測試同步改判質心，並印出實際質心移動與 RMSD 供下一輪檢查。
- 證據：只有 CI（容器無 OpenMM）。若 0.2 nm 解不開（piercing 斷言失敗），下一步是 hold 半徑依「穿入深度」自適應，而不是放寬上限。

### D-63　預設拉離速度 0.01 → **0.005 nm ps⁻¹**（依筆電 teaching 重跑判斷；使用者 11/02 14:58 授權由開發 session 決定）
- 證據（MSI Cyborg 14／RTX 4060，3PTB 苯甲脒，兩次都是 0.01 nm ps⁻¹；本 session 直接讀筆電檔案，以 D-62 的程式在同一批樣本重算全範圍 PMF）：

  | | window 長度 | window 數 | 筆電報告的 ΔPMF | **全範圍重算 ΔPMF（平台）** | ΔG° |
  |---|---|---|---|---|---|
  | classroom | 50 ps | 40 | 80.3（截斷於 0.50 nm） | 134 ± 1.5 kJ/mol | −29.5 kcal/mol |
  | teaching | 500 ps | 33 | 80.6（截斷於 0.54 nm） | **100 ± 2.3 kJ/mol** | −21.2 kcal/mol |
  | 實驗 | — | — | — | — | ≈ −6.4 kcal/mol |

  圖：`docs/runs/2026-11-02_laptop_3ptb/pmf_classroom_vs_teaching.png`。兩次報告值幾乎相同（80.3／80.6）只是兩條曲線在 0.5 nm 附近被截斷的巧合（D-62），**不是**「window 加長無效」。
- 判斷：
  1. teaching 的 SMD 做功 355 kJ/mol，對照平台約 100 kJ/mol → **耗散約 255 kJ/mol（≈ 100 kT）**，拉離遠離平衡，窗口起點帶著被擾動的口袋（鹽橋、水）。
     線性響應下耗散與速度成正比，減半約可減半。
  2. 代價很小：1.5 nm 從 150 ps 變 300 ps，RTX 4060 上約多 1 分鐘；teaching 的 window 合計約 16.5 ns。
  3. window 加長 10 倍使平台由 134 降到 100 → 起點記憶是誤差來源之一，放慢拉離直接減少這個記憶。
- 決定：`BindingConfig.pull_velocity_nm_per_ps = 0.005`；`advisor` 各目標一律建議 0.005（原本只有胜肽與發表等級）；`pipeline example` 範本同步。
- **誠實限制（不要誤讀這個決定）**：0.2–0.5 nm 段在兩次中完全重合（與 window 長度無關）→ 剩下的高估主要來自**一維 COM 座標**（配體方向、水進入口袋未受控，
  正交自由度慢）與窗口未收斂，**不是拉速能解決的**。預期 0.005 只會小幅降低平台；要接近實驗需要方向／構形約束（Woo–Roux）或 funnel，
  已列在 HANDOFF_2026-11-02 §6 未決。teaching 的 ΔG° 仍應被閘門擋下（本次確實擋下：pmf.quality.passed=False）。
- 驗證計畫：a3 發行後，筆電以 teaching tier、0.005 重跑同案例，比較 SMD 耗散功與全範圍 ΔPMF；結果補在本條「更正／補充」。
- 相關：D-40（窗口長度）、D-44／D-45（彈簧鬆弛幀、振盪診斷；本次筆電是 a2 以前版本，未含）、D-62（截斷修正）。

### D-62　MBAR bootstrap 加速（暖啟動＋沿用求解法）與「PMF 必須涵蓋取樣範圍」閘門
- 事實：
  - 筆電 teaching 重跑時，傘狀採樣結束後的 PMF 步驟極慢：`bootstrap_pmf_1d` 的 100 次重抽樣**每次都從零解 MBAR**，
    且基本解的 hybr 已失敗（`trying next method`），每次重抽樣再失敗一次才換法。
  - 筆電 classroom 3PTB（v0.1.0a1）：40 個 window 取樣到 1.72 nm，`pmf.png` 只到 0.50 nm 且仍在上升，報告「ΔPMF 80 kJ/mol」是截斷邊緣值。
    同一批樣本用 WHAM 重算涵蓋 0.16–1.83 nm（平台約 125–134 kJ/mol）。機制：f_k 不準時遠處 window 的 MBAR 權重下溢為 0 → 該處密度 0 → PMF 為 NaN，
    `pmf[valid]` 只保留有限值，曲線就無聲地停住；D-43 的 WHAM 交叉比對只比 ΔPMF，沒有比範圍。
- 決定：
  1. `mbar_pmf_1d` 接受 `initial_f_k`、`solver_protocol`（pymbar 不接受就自動不傳，結果相同只是慢）；回報 `solver_fallback`。
  2. `bootstrap_pmf_1d`：重抽樣以基本解的 f_k 暖啟動；基本解用過備援求解法時，重抽樣直接用 `solver_protocol="robust"`。
     記錄 `timing_s`（基本解、bootstrap 總時間、每次）到 `quality["solver"]`，讓加速倍數由下一次 CI／筆電實測給出。
  3. `pmf_from_windows`：PMF 有限值範圍必須涵蓋「最低到最高 window 平均」（±1 bin）。MBAR 沒涵蓋 → 以 WHAM（含 bootstrap）重算，
     涵蓋就改用並記錄 `quality["pmf_truncated"]`；兩者都沒涵蓋 → `converged=False`，不輸出邊緣值當井深。
- 證據：`tests/test_mbar_bootstrap.py`（7 項；以 numpy 版 MBAR 取代 pymbar：暖啟動傳入、備援後改 robust、舊版 pymbar 相容、暖啟動不改答案、
  截斷→WHAM、計時欄位）。筆電 40 個 window 的真實樣本：固定點迭代的重抽樣迭代數由約 4,600 降到約 3,600（−20～30%）。
- **誠實限制**：容器裝不了 pymbar（PyPI 不通、從 GitHub 取原始碼被拒），**真正 pymbar（hybr，類牛頓法）的加速倍數未測**；
  預期暖啟動對牛頓法幫助比固定點大，且省掉每次重抽樣 hybr 失敗再換法的時間，但以 `timing_s` 實測為準。
- 被否決（這次）：bootstrap 改用 WHAM（快，但誤差棒與基本解不同估計器）；自適應提早停止 bootstrap（σ 收斂就停，可確定省時間，但改變統計精度，留給使用者決定）。

### D-61　補完 D-60 的三個未決：主鏈穿環、軟核鬆弛第二層修復、協同自由能（熱力學循環）
- 使用者（18:25）：這三項應該要一起做。（接受：D-60 把它們列為未決是我該一起完成的範圍。）
- 主鏈穿環：最小化後檢查原本逐殘基建分子，肽鍵（跨殘基 C–N）不算鍵；改為把配體附近所有殘基當一個分子推定鍵結。測試以甘胺酸肽鍵穿過苯環驗證。
- 軟核鬆弛（`md20/build/softcore.py`）：剛體微調修不好時，建模層對該配體做 λ 0.05→1 的軟核鬆弛（Beutler 1994），其他重原子固定、配體質心保持 0.3 nm 內；
  接受條件為幾何全部通過、RMSD ≤ 3 Å、保留 ≥ 70 % 接觸。姿勢層在有 OpenMM 時改為 DEFERRED（交給建模層），建模層也失敗才 NEEDS_HUMAN；`multi_ligand.softcore: false` 可關閉。
  取捨：3 Å 比微調寬，因為解開穿環本身需要沿鍵軸移動約一個環半徑；更寬就是另一個結合模式。只動配體不動側鏈（列未決）。
- 協同自由能（`sampling/multi.py::cooperativity`）：用已有的單獨拉離與共同口袋拉離組成熱力學循環；**先檢驗兩路徑閉合（≤ 2σ，無誤差 4 kJ/mol）**，
  閉合才報 ΔΔG_coop（兩路徑平均，σ/2），否則 NOT_CLOSED 不下結論。原本的「共存效應」只是單一路徑，文字改為指向循環判定。
- 自我檢查發現的缺口：從共同口袋拉離 A 時，B 原本完全不加限制（決策日誌寫「可自由移動」），B 若中途離開，這一腿就不是「B 已結合」，循環失去意義。
  新增 `binding.hold_spectators`（預設開）：B 對口袋錨點距離 ±0.3 nm 平底保持，範圍內零力；每窗口記錄碰到邊界的比例，> 10 % 加 caveat。
  `finished_result` 改為以預設值補齊舊設定再比較，避免新增欄位讓已完成的結合計算全部重跑（筆電上的結果不受影響）。
- 報告：結合自由能一節加 F42 協同自由能圖與「協同與循環閉合」表。
- 證據：`tests/test_cooperativity.py`（正協同、不閉合、無效應、互斥、缺腿、缺誤差）、`tests/test_softcore.py`（CI：軟核解開穿環、保持限制）、主鏈穿環測試、報告範本涵蓋 F42。
- 未決：軟核只動配體；三個以上配體的成對子系統不自動建立。
- **更正（20:15，CI d3502f0 ubuntu／macOS 各 2 個失敗）**：
  1. `test_3ptb_with_peptide_on_own_chain` 被建模層幾何檢查擋下（「P01 未與蛋白接觸」）：漂浮判定原本對單一配體也生效，但漂浮是多配體系統的概念；
     單獨一個不在口袋的配體是姿勢品質問題，已有自己的閘門（胜肽活性位可及性）。改為只在 ≥ 2 個配體時判定漂浮。這是 D-60 的誤擋，正是要 CI 抓的那種。
  2. `test_softcore_unthreads…` 產生 NaN：配體質心保持限制寫成 sqrt(Δx²+…)，起點 Δ = 0 時導數 0/0。加 1e-8 nm² 修正。
     同時發現測試幾何太苛刻（4 原子鏈整段穿在環中央，解開需移動 > 3 Å，超過接受上限），改為只有末端鍵穿環的實際情況；建模層修復改為依序試三個亂數種子
     （穿過環的鍵往哪邊滑出由熱擾動決定）。其餘 457 個測試通過，含花費最久的完整流程與短 MD 篩姿勢（真實對接複合物未被誤擋）。

### D-60　多配體同時對接進入 MD：穿環／重疊／漂浮的檢查、自動改選與微調、指名排除、力場一致性、報告版型
- 使用者（17:48）：多重分子同時對接時版型與圖表要調整；進入 MD 要小心穿模與不合理構型；要能排除與智慧調整（改姿勢或判斷哪一個不合理而排除）；力場也很複雜。
- 診斷（現況缺口）：原本只檢查對接重原子的配體間最短距離（< 3.3 Å 擋），independent 組合也只看 2.5 Å。
  沒有檢查加氫後的重疊、沒有任何穿環檢查（最危險：最小化解不開、可能不報錯）、漂浮配體會直接進 MD、不同配體可能落在不同力場與電荷模型。
- 決定（細節見 `docs/specs/multi_ligand.md`）：
  - 新模組 `md20/build/multi_ligand.py`（純 numpy）：穿環（鍵與環平面交點在環內）、跨分子重疊（重–重 2.2／重–H 1.3／H–H 1.0 Å，不誤判氫鍵）、漂浮配體。
  - 處置順序：自動改選其他已通過對接規則且幾何可用的聯合姿勢 → 剛體微調（≤ 30°、≤ 2 Å、RMSD ≤ 2 Å、保留 ≥ 70 % 接觸）→ 漂浮配體移出多配體系統
    → 其餘 NEEDS_HUMAN 並**指名**建議排除的配體（牽涉問題最多；平手取蛋白接觸少者），GUI 一鍵 `multi_ligand.exclude` ／改選姿勢／照原樣（不建議）。
  - 三道關卡：姿勢層（建 docked_multi 前）、建模層（全部原子含氫，所有系統）、最小化後（`minimize_final.pdb` 穿環 → NeedsHuman，不進入加熱）。
  - 力場：同一系統的小分子配體統一力場與電荷模型（先試全 Sage、再試全 GAFF2），做不到時 advisory 標註。
  - 報告：同時對接改以「排列」為主角——聯合姿勢相似度、F38 共同佔位檢查、F39 各配體位置（偵測互換）、F40 子位點地圖、姿勢表按配體分列＋配體間距離、
    幾何檢查表；MD 加 F41 配體間距離（有平底限制時明說「維持」不能當證據）；限制一節加入多配體的力場與限制說明。
- 被否決：自動排除碰撞元兇（改變科學問題，屬使用者決定；漂浮配體例外）；讓最小化自己推開（推出口袋或穿環推不開）；軟核最小化／重新柔性對接（成本高，列未來）。
- 自我檢查發現：多配體系統原本就有質心平底限制（±0.4 nm），所以 MD 中「配體間距離穩定」部分是限制造成——報告必須說清楚，已加 caution 與限制條目。
- 證據：`tests/test_multi_ligand_geometry.py`（11 項，含工作流程擋下 → GUI 一鍵排除 → 通過、自動改選乾淨姿勢）、`tests/test_docking_figs.py`、報告範本 71 張圖涵蓋 F38–F41；本地全綠。建模層與最小化後檢查需 OpenMM，待 CI。
- 未決：最小化後檢查未涵蓋跨殘基主鏈鍵穿環；軟核最小化作為第二層修復；多配體協同的結合自由能。

### D-59　分子對接多產生圖（5 種）＋ 報告範本（所有圖表一次看到）
- 使用者（17:24）：分子對接也可多產生圖，請思考；並給一份目前報告的範本，包含所有圖表。
- 思考（對接能回答哪些問題、哪些還沒有圖）：原本只有「各姿勢分數」一張。對接結果另外還能回答：
  前幾名是不是同一個結合模式？評分函數能否辨認晶體姿勢？配體是否集中在一個口袋？哪些殘基是穩定的結合位核心？多個配體之間怎麼比？
- 決定：新增 `md20/report/docking_figs.py`（純 numpy，讀姿勢 SDF 與對接受體 PDB），報告對接一節每個配體加：
  - F33 姿勢相似度矩陣（受體座標系、不疊合的 RMSD）：前 3 名平均 ≤ 2 Å → 收斂到同一模式；否則分數相近的姿勢模式不同。
  - F34 對接漏斗（分數 vs 與共結晶姿勢的 RMSD；只有有參考結構時才畫）：最佳姿勢 ≤ 2 Å 且 r > 0.3 → 漏斗；≤ 2 Å 但無相關 → 區辨力有限；> 2 Å → 評分偏好錯誤模式。
  - F35 姿勢在搜尋區中的位置（x–y 與 x–z 投影、框線＝搜尋區、顏色＝分數）：三種情境（見下方自我修正）。
  - F36 各姿勢的接觸殘基（殘基 × 姿勢，4 Å）：≥ 70 % 姿勢共同接觸者列為結合位核心。
  - F37 配體比較（最佳分數、配體效率、重原子數）：分數差 < 1 kcal/mol 不排序。
- 自我修正（模板首跑發現）：F35 原本只用平均離散 ≤ 3 Å 判斷，範本中 4 個近似姿勢＋5 個離群姿勢（離散 4.4 Å）被說成「不只一個位置」，
  不合理；改為以第 1 名姿勢為基準：≥ 60 % 姿勢在其 4 Å 內 → 主要位置＋分數較差的替代位置；否則 → 數個競爭位置（warn，建議 MD 比較或縮小搜尋區）。
- 報告範本：`tools/report_template.py` 以合成資料建一個示範流程（篩選 40 個化合物、2 個配體各 9 個姿勢與 SDF、受體、apo 與複合體兩個模擬含
  最小化、NVT、NPT、正式模擬、3 個重複、延伸分析、SMD、傘狀窗口、重疊矩陣、收斂、PMF、胜肽限制），輸出中英文兩份 HTML，頂端標明「合成示範資料，請勿引用」。
  本地（無 RDKit）51 張圖、34 種；CI 新 workflow `report-template.yml` 裝 RDKit 後應為全部 37 種，HTML 推到 `report-template` 分支。
  `tests/test_report_template.py` 保證：之後新增圖種而範本沒有資料 → 測試失敗（避免範本落後）。
- 順手修正（範本暴露的真 bug）：`actual_values` 原本「有執行 protocol 就整份用它」，舊或不完整的 run manifest 缺階段欄位時方法段落會因 None 崩潰；
  改為逐階段以 tier 預設補缺（執行值優先）。熱圖 ≤ 12 列時每列都標（原本 9 個姿勢會漏標第 8 名）。`build_workflow_report` 加 `banner_html`（受信任標記，供範本標示）。
- 證據：`tests/test_docking_figs.py`（每個情境一個測試）、`tests/test_report_template.py`、`tests/test_report_v2.py`；本地全綠，CI 待確認。
- 未決：範本的接觸圖列數多（合成受體 80 個殘基）；實際 3PTB 案例的版面待筆電重跑結果確認。

### D-58　圖表豐富度：目前能力可做到的所有分析都產出圖、進結案報告（中英文）與系統「圖表」分頁，並套用通用用語
- 使用者（16:51）：目前能力可做到的所有圖表都要在結案報告與系統中看得到；圖表豐富度太低；報告要有相關論述；要通則不是特例；中英文版都要。
- 盤點（16:48 回覆）：原有 17 種靜態圖、6 種互動檢視，但結案報告只放約 10 種；有兩項已計算卻從未畫圖（極性接觸、質心距離）。
- 決定：
  - 新增 `md20/analysis/extended.py`（分析步驟自動執行，結果寫 `analysis/extended.json`，每一塊獨立、失敗只記錄不中斷）：
    二級結構（DSSP）、Cα 主成分分析與自由能地形、Cα 加配體 RMSD 叢集（GROMOS 式、2 Å）、動態交互相關、蛋白溶劑可及面積、蛋白內部氫鍵、
    每個配體：與蛋白的氫鍵（Wernet–Nilsson）數與每組佔有率、作用指紋（離子、極性、疏水；殘基 × 時間）、水橋、配體埋藏比例（溶劑可及面積）。
    昂貴部分最多取 250 幀（蛋白內部氫鍵 100 幀）。
  - 結合自由能另存 PMF 收斂（每窗口前 25、50、75 % 與全部）與窗口重疊矩陣。
  - 化合物：性質分佈（分子量、logP、極性表面積、氫鍵供受體、可轉動鍵，Lipinski 與 Veber 門檻）、分子指紋化學空間、選用姿勢的二維作用圖（`md20/report/chem.py`，需要 RDKit，沒有時記錄原因）。
  - 結案報告把原本只在單次模擬報告中的圖也放進來：能量最小化、各階段溫度密度與盒體積（附驗收結果）、全程概覽、重複疊圖、篩選分數分佈與分數對大小。
  - 分子動力學一節分為「平衡過程品質」「蛋白的穩定性與動態」「配體在模擬中的結合」三小節；每張圖都有圖說、如何判讀、本專案的結果（規範 `docs/specs/report_language.md` F11 到 F32，共 32 種圖）。
  - 系統：流程頁新增「圖表」分頁，按「產生或更新圖表」即以目前語言重建，顯示每張圖與其說明（`report_figures/index_<語言>.json`）。
- 自由能地形的低谷判定（自我修正）：最初以局部最小值計數，稀疏直方圖下雜訊被算成 22 個狀態；改為平滑後 1 kT 以下的連通區域且占 ≥ 5 % 幀數、
  直方圖格數隨幀數調整（√n／1.5，10 到 30）；兩狀態與單一狀態的合成資料在 51 到 500 幀都判定正確（測試）。
- 不做（說明理由）：MM/GBSA 與每殘基能量分解——需要以隱式溶劑重建含配體參數的系統，目前的建模輸出不直接支援；列為下一步。
- 證據：`tests/test_extended_analysis.py`（純 numpy 部分本地；mdtraj 合成軌跡在 CI）、`tests/test_report_v2.py`（測試資料至少 20 個圖區塊、圖檔存在、索引完整）、`tests/test_figure_text.py`。

### D-57　執行進度的剩餘時間與實測速度（介面與命令列）
- 使用者（16:45）：要能監看 cmd 的資訊。原本命令列每 15 秒印一行 `stage=…, completed_local_steps=…` 原始欄位，看不出還要多久。
- 決定：`md20/engine/progress_text.py::StageMeter` 由同一階段第一與最新兩筆心跳計算速率（續跑時時鐘重設也能處理），命令列輸出
  `[npt]  11.0 % | T 300.0 K | 14 min left in stage | 35 ns/day`；介面即時曲線分頁同樣顯示「此階段約剩」與本機實測 ns/day（`views.live_series`）。
  只估目前階段，不估整個流程（後續階段長度依閘門與補窗而變，整體估計會誤導）。
- 雲端 session 無法看到筆電螢幕（本 session 沒有電腦操作工具）：改由筆電 session 依 `docs/LAPTOP_SESSION.md` 的監看流程把進度與結果推到 `docs/runs/`，雲端 session 讀取後解讀並修正。
- 證據：`tests/test_progress_text.py`、`tests/test_gui_views.py::test_live_series_stage_eta_and_speed`。

### D-56　搜尋區過大提醒（REVIEW #6、看板待認領項）：不擋流程，卡片＋報告限制段落
- 決定：`docking_preflight` 在使用者給定中心與尺寸時，計算最長邊與搜尋區內殘基數；最長邊 > 40 Å 或殘基 > 300 個 → 科學限制提醒（AUTO_FIXED、advisory），
  說明格點數（間距 0.375 Å）與「等同盲對接、可信度下降」；存於 `state["advisories"]`，GUI 顯示卡片（選項：以共結晶配體或活性位殘基重新定義、接受並標註），報告列入限制。
  縮小後提醒自動消失。專業模式的合理性檢查（D-49）已在填表時提示同一件事。
- 為什麼不擋：論文常用大搜尋區（例如教學案例二 36 × 51 × 45 Å），使用者可能刻意要重現；寧可清楚標示也不阻止。
- 證據：`tests/test_workflow_gates.py::test_oversized_box_is_a_notice_not_a_block`。

### D-55　英文介面的閘門卡片：英文標題、一般說明、選項翻譯；原始中文細節收在「Details」
- 問題：介面預設英文，但閘門卡片（需要決定的地方）的說明、來源、狀態與選項全是中文。
- 決定：`md20/gui/gate_text.py` 為程式中每一種閘門提供中英標題與英文一般說明（測試掃描原始碼中所有 `Gate("…")` 與 NEEDS_HUMAN 名稱，缺一個就失敗），
  選項以完整字串或前綴翻譯（`仍要使用（…）` → Use anyway、`box.from_residue: X` → Define the box from residue X …），沒列到的照原文顯示。
  英文卡片顯示英文標題與一般說明，該次執行的中文細節（含數字）收在「Details (recorded in Chinese)」；來源與狀態徽章也翻譯，科學限制提醒用灰藍色「Scientific notice」。
- 不做：把每個閘門的說明全文翻成英文模板（說明含大量動態數值，量大且易出錯；先以一般說明＋原文細節，之後逐步改為雙語模板）。
- 同時修正（CI 1a2d2fc、c4bc96c）：手動上傳 SDF 的命名比對改為不分大小寫（Windows 與 macOS 檔案系統不分大小寫，原規則在使用者的筆電上不成立），
  以表格中的拼法存檔，表格內只差大小寫的名稱列為衝突；科學限制提醒卡片的選項恢復可點（gate_actions 原本只處理 NEEDS_HUMAN；本地缺 RDKit 使該測試被略過，CI 才抓到）。
- 證據：`tests/test_gate_text.py`、`tests/test_screen_library.py`、`tests/test_gate_actions.py::test_advisory_gate_keeps_clickable_options`。

### D-54　報告用語規範：每張圖都有「圖說、如何判讀、本專案的結果」，情境句型是通則，由數據選擇
- 使用者（15:53）：報告沒有圖表；每一張圖表都要有專案說明；先建立通用用語、幾種可能，產出的報告才順；**要通則不是個案**。
- 事實：先前的預覽是測試資料，沒有圖檔；真實流程的圖存在，但報告只放圖加一行圖說，沒有判讀。
- 決定：
  - 規範 `docs/specs/report_language.md`：10 種圖（對接姿勢分數、篩選排名、主鏈 RMSD、迴轉半徑、配體在口袋中的位移、RMSF、接觸頻率、SMD 拉力與功、傘狀採樣分佈、PMF），
    每種寫明「圖上畫什麼、如何判讀（任何專案相同）、可能的情境（門檻寫在句子裡）」。程式 `md20/report/figure_text.py` 逐條實作，測試檢查每種圖都在規範中、每個情境都能被觸發。
  - 圖由報告依數據自行繪製（`md20/report/figures.py`：metrics.json、smd.tsv、binding_manifest.json），樣式一致，確保每張圖都有對應的說明；沒有數據時退回原圖並只附判讀原則。
  - 每張圖的區塊：圖＋圖號與圖說 →「如何判讀」→「本專案的結果」（情境句，可多條）。章節的「結果解釋」改為綜合：先列支持的結論，再列需保守看待的結果，不重複圖下的細節。
    重點摘要直接取自這些句子（注意事項優先），因此摘要與內文一定一致。
- 被否決：每個案例手寫說明（使用者明確要求通則）；只加長圖說（沒有判讀與情境，讀者仍不知道結果代表什麼）。
- 證據：`tests/test_figure_text.py`（10 種圖的每個情境）、`tests/test_report_v2.py`（兩種語言各至少 8 個圖區塊，含如何判讀與本專案結果）。

### D-53　配體直接配位金屬的後備：選用的平底距離約束（ligand_metal: restrain），此配體不計算結合自由能
- 背景：REVIEW #15 之後，對接姿勢直接配位金屬時一律 NEEDS_HUMAN，選項只有換姿勢、QM 參數化、移除金屬——對沒有 QM 資源的使用者等於卡住。使用者 14:5x「全部修正」。
- 決定：閘門新增一鍵選項「ligand_metal: restrain」。選用後在建模時對每個配位對（金屬、配體 N／O／S，對接距離 d）加平底距離約束：
  d ± 0.25 Å 內零力，外側 5000 kJ mol⁻¹ nm⁻²，全程開啟（力名 `msw_ligand_metal`，紀錄於 build manifest `restraints.ligand_metal`）。
  閘門改為 AUTO_FIXED 並在說明中寫清楚：這是幾何後備，配位能不在力場中。結合自由能步驟跳過該配體（拉離會量到約束而不是結合），結果標 SKIPPED 並附理由；報告限制段落列出。
- 為什麼預設不自動套用：約束會讓配位「看起來穩定」，若使用者不知道，會把約束的結果誤當成結合證據（寧可擋也不要猜）；所以只能由使用者明確選擇，且報告標註。
- 被否決：用 12-6-4 或非鍵結模型直接跑（D-17 已說明會散開或塌陷）；自動移除金屬（改變系統化學）。
- 證據：`tests/test_ligand_metal.py`（預設擋、選擇後 AUTO_FIXED、一鍵寫回、Reference 平台算出平底能量在三個距離皆正確）、`tests/test_metal.py`。真實建模流程尚未有含配位配體的 CI 案例（未決）。

### D-47　主鏈斷裂截斷：中性 ACE／NME 端帽，斷點後片段改為獨立 chain；長 loop「補建並接受風險」可執行
- 使用者（14:5x）問對接後 PDB 斷鏈怎麼處理，隨後「全部修正」。事實：選項「截斷（加 ACE/NME 端帽）」早已出現在閘門上，但程式不執行（D-17 後一律維持擋關）。
- 決定：
  - `md20/build/caps.py`：只用斷點兩側的主鏈原子以理想反式胜肽幾何放置重原子（C–N 1.33 Å、N–CH3 1.46 Å、C=O 1.23 Å、C–N–CA 121.7°、N–C–O 122.7°、
    N–C–CH3 116°；甲基與前一個 Cα 反式、羰基 O 與 Cα 順式）。斷點前殘基後接 NME（resSeq＋1）＋TER，斷點後殘基前接 ACE（resSeq−1），
    後段改用未使用的 chain ID——OpenMM `createStandardBonds()` 只在同一 chain 內連鍵，這是避免假鍵的關鍵。重原子之外的氫由第二次 PDBFixer（不補殘基）加上。
  - `receptor_choice_action`：三個斷鏈閘門（短缺口無 SEQRES、長缺口、補建後仍斷）選「截斷」→ cap；長缺口選「以 PDBFixer 補建並接受風險」→ fill（只有 SEQRES 涵蓋時才真的補得出來，
    否則補建後檢查會再擋下並說明）。截斷後仍以 `inspect_pdb_text` 驗證每條 chain 內沒有斷點；閘門「chain breaks capped」列出每個斷點與新 chain。
  - GUI：這些選項成為一鍵按鈕（docking 受體與 MD 建模兩處的卡片都可按，寫回 `human_choices.receptor`）。
  - 修正既有錯誤：`build_case` 沒有把 `human_choices` 傳給 MD 建模的 `prepare_receptor`，閘門上的受體決定只套用到對接受體。
- 為什麼用中性端帽而不是帶電末端：斷點在蛋白內部，人為的 NH3⁺／COO⁻ 會在原本是中性主鏈的位置產生錯誤的靜電作用（Amber 與 CHARMM 的標準做法）。
- 證據：`tests/test_caps.py`（幾何、chain 分割、序號重編、無殘留斷點；3PTB 刪除 70–73 且無 SEQRES 的真實流程在 CI）、`tests/test_gate_actions.py`。
- 未決：缺失殘基若在結合位附近，截斷後的口袋形狀仍不完整；目前在閘門說明中提醒，尚未自動計算缺口到結合位的距離。

### D-52　報告改為專案報告等級：每節「這一步是什麼 → 科學意義 → 使用的參數 → 圖表 → 結果解釋」，雙語，結果解釋由數據產生
- 使用者（15:09）：報告每項先有文字敘述這項目是什麼、科學意義，接著使用者選擇的參數，最後圖片或表格及報告解釋；要專業、可直接用於專案報告、要夠聰明。
- 決定：`md20/report/workflow_report.py` 重寫；新增 `md20/report/interpret.py`（純 Python，結果解釋）。
  - 結構：重點摘要（所有「注意」優先，再取各節第一條）→ 1 研究設計 → 2 受體準備與結構可信度 → 3 高通量篩選（有才出現）→ 對接與姿勢 →
    胜肽科學限制（有才出現）→ 分子動力學 → 結合自由能 → 方法（可直接貼用）→ 限制與注意事項 → 3D 檢視 → 附錄 A 完整參數表、B 決策紀錄、C 設定檔。
  - 參數表四欄：參數、採用值、本案例建議值、理由；使用者改過且不同於建議者標「使用者修改」。採用值取自實際執行的 protocol（run.json），不是設定猜測。
  - 圖、表自動編號並附說明；結果解釋的門檻寫在句子裡（例：重新對接 RMSD ≤ 2 Å、主鏈 RMSD < 2 Å 穩定、後半段漂移 > 0.5 Å 未達平台、
    配體最後 20 % 口袋 RMSD ≥ 3 Å 視為離開、前後半段 ΔPMF 差 ≤ 2 kJ mol⁻¹ 收斂、井深 > 80 kJ mol⁻¹ 不合理、前兩名分數差 < 1 kcal mol⁻¹ 名次無意義、叢集 < 30 % 未收斂）。
  - 方法段落依實際參數產生（力場、水盒、離子、PME、HMR、各階段長度、積分器、SMD 與傘狀採樣設定）。
  - 語言：`cfg.language`（GUI 依介面語言寫入），GUI「開啟報告」以 `/report/{project}/{name}?lang=` 依目前介面語言重建。
- 同時修正（advisor）：保留的金屬預設是非鍵結離子（metal.py：沒有 metal_policy 即 default_nonbonded）；只有 `metal_policy: bonded`
  才算鍵結模型、才建議 2 fs 與溫和約束。原本把 trypsin 的鈣離子當鍵結金屬是錯的（本 session 自己的錯，測試已補）。
- 證據：`tests/test_report_v2.py`（兩種語言的章節順序、每節五段、解釋句子含實際數字、方法段落）、`tests/test_gui_server.py`（兩種語言報告 HTTP 200）。

### D-51　GUI v2 實作：首頁四種模式（教學一、教學二、快速、專業）、教學頁、依個案建議的參數表單、雙語
- 使用者（15:04）：週二需要完整程式與完整使用者介面；新增教學頁面，用兩篇論文（快速模式）；教學模式一（多種小分子）、教學模式二（胜肽）、快速模式、專業模式。
  （15:06）專業模式也要依個案建議初始值。（15:14）介面可選繁中與英文，英文預設。
- 決定：
  - 首頁 `/`：四張模式卡片＋最近流程；電腦狀態移到 `/system`。語言選單在頁首，存於 `<projects>/gui_settings.json`（檔案變更即生效）。
  - 教學頁 `/teach/hsieh2024`、`/teach/hsieh2025`：論文出處、研究背景、學習目標、本案例示範的科學檢查、流程與每步重點、本教學使用的參數（含理由）、討論題；
    「開始這個教學案例」以論文設定＋快速模式建議值（課堂目標）建立流程。論文明確給出的設定（對接方式、搜尋強度、邊距）保留不覆寫。
  - 快速 `/new/quick`：只顯示 9 個關鍵參數；專業 `/new/pro`：34 個參數分五組，每個參數旁有建議值理由，改過的參數顯示「已修改．建議值」；
    右側即時合理性檢查（錯誤、注意、提示，可一鍵套用建議值；有錯誤時「建立並開始」停用）與本機時間估計。研究目標改變時，未修改的參數跟著新建議更新。
  - 配體行支援 `名稱 peptide:序列`；HTS 可下載範例表格、上傳化合物表格；篩選分頁新增可點選的排名長條圖（點選即勾選）與手動上傳 SDF（嚴格命名，D-50）。
  - GUI 建立的流程一律 `confirm_before_md`；姿勢選定後流程頁頂端出現「是否進入分子動力學？」卡片。
- 被否決：在瀏覽器端存語言（app.storage.user 需要 storage_secret，單機工作站不需要多使用者）；每個參數用滑桿（數值範圍跨數個數量級，輸入框較精確）。
- 證據：`tests/test_gui_v2_logic.py`（配體行、模式→config、教學 config、雙語內容與「不用斜線」規則）、`tests/test_gui_server.py`（各頁 HTTP 200、範例表格為 xlsx）、CI `gui-preview` 兩種語言截圖。
- 未決：NiceGUI 在開發容器無法安裝，頁面版面以 CI 截圖審查；舊閘門說明仍只有中文（見 D-49）。

### D-50　HTS 手動上傳（嚴格命名）與「姿勢選定後確認是否進入 MD」
- 使用者（11/02 14:3x，GUI 第二輪回饋）：自動下載被阻擋時要有手動上傳機制並限制命名原則；姿勢選擇後詢問是否進入 MD。
- 決定：
  1. `<library>/manual_upload/<name>.sdf`：檔名必須與表格 name 欄完全相同（英數、底線、連字號，≤ 40 字元，大小寫不同視為不同），
     存在時優先於任何下載（來源記為 manual-upload）。`manual_upload_report` 列出已對上、仍缺、命名不合、對不到任何列的檔案；
     命名不合或對不到的檔案**一律不使用**，避免誤名的檔案頂替另一個化合物。`check_upload_name` 供 GUI 上傳時即時檢查（雙語理由，含大小寫提示）。
  2. `confirm_before_md: true`（GUI 建立的流程預設開啟；CLI 預設關閉，照常一路跑完）：姿勢選定後在新步驟 `md_confirm` 停下，
     閘門「confirm MD」一鍵「進入分子動力學」寫回 `md_confirmed`（已加入 DECISION_KEYS，重跑不會遺失）。改選姿勢會清掉此步驟。
- 證據：`tests/test_screen_library.py::test_manual_upload_naming_and_priority`、`tests/test_gate_actions.py::test_confirm_before_md_gate`。

### D-49　依個案建議初始參數（快速、專業、教學模式共用）＋合理性檢查＋時間估計；介面與報告雙語（英文預設）
- 使用者（15:06）：動力學參數複雜，即使是專業模式也應依個案建議初始預設值，要夠聰明。（15:14）操作介面與報告可選語系，繁中與英文，英文預設。
- 決定：新增 `md20/advisor.py`（純 Python，所有入口共用）：
  - `features_from_config`：殘基數、配體種類（小分子／胜肽）、配體數、對接方式、保留的金屬、預測模型、主鏈缺口、搜尋區大小、本機效能測試。
  - `recommend(features, goal, lang)`：34 個參數各給建議值與理由（目標：課堂示範、化合物比較、結合強度、發表等級）。例：胜肽 → 搜尋強度 32、溫和約束、教學等級 20 ns、拉速 0.005；
    金屬鍵結 → 2 fs、加熱延長 50 %、溫和約束；發表等級 → research、3 次重複、窗口 2 ns；要算結合強度 → 邊距 1.2 nm；搜尋區最長邊 > 30 Å → 搜尋強度 32。
  - `check(values, features, lang)`：error（會失敗或物理錯誤：步長 > 4 fs、研究等級 > 2 fs、溫度在液態水外、邊距 < 0.8 nm、隱式溶劑做結合計算、窗口平衡 ≥ 取樣）、
    warning（能跑但結果弱：加熱 < 50 ps、NPT < 100 ps、粗糙結構用標準釋放、拉速 > 0.02、彈簧常數範圍外、搜尋區 > 40 Å 等）、info；每條附建議值。
  - `estimate_hours`：以本機效能測試換算原子數與步長，估計 MD 與結合計算時間。
  - `apply`／`values_from_config`：參數與 workflow config 雙向對應（`md.stage_overrides` 每個鍵都是 StageSpec 欄位，測試驗證）。
  - NPT 長度覆寫視為基本長度，溫和策略仍自動加倍（`workflow.run_md`），與理由文字一致。結合計算的窗口保留自己的 2 fs 步長（窗口不用 HMR）。
- 雙語：所有文字以（繁中、英文）成對保存，`lang` 決定輸出；英文預設。DecisionLog 的 `why` 依 CLAUDE.md 仍寫中文；
  舊的閘門說明目前只有中文，英文報告會原文呈現並註明（逐步翻譯）。
- 自我一致性測試：各目標下系統建議值本身不得觸發 error 或 warning。
- 證據：`tests/test_advisor.py`。未決：時間估計的原子數公式（Rg ≈ 2.2·N^0.38）尚未以實際建模原子數校正。

### D-48　胜肽科學閘門改為「科學限制提醒」：CPP 不擋流程；新增活性位可及性檢查（對接前、pose 選定後）
- 使用者（15:04）：胜肽對接常有「根本進不去目標蛋白」的問題，要先過類似 CPP 的科學閘門；**即使沒通過也不影響後續操作**
  （使用者可能不是做酵素科學），但要告知科學限制。
- 決定：
  1. `cpp_gate` 不再回 NEEDS_HUMAN。標靶位置未指定或預測不穿膜 → AUTO_FIXED＋`advisory=True`，說明開頭「科學限制提醒（流程照常進行）」，
     `record["limitation"]` 寫入 state，GUI 以「科學限制」卡片顯示（位置選項仍可一鍵寫回），報告列出。`cpp_override` 保留但不再必要。
  2. 新增 `peptide_access_precheck`（對接前）：胜肽緊縮直徑（Rg ≈ 2.2·N^0.38 Å，+3 Å）大於搜尋區最短邊 → 可能放不進；
     搜尋區不是由共晶配體或指定殘基定義 → 等同盲對接，無法判斷是否在活性位；最長邊 ≥ 30 Å → 偏向表面結合位。
  3. 新增 `peptide_pose_access`（pose 選定後）：埋藏比例（6 Å 內 ≥ 30 個蛋白重原子的胜肽原子比例；平面表面約 20–25、完全埋藏約 50）、
     接觸比例、距活性位（共晶配體原子）最近距離。埋藏 < 25 % 或距活性位 > 4 Å → 提醒「表面貼附／沒到活性位」，附「改選 pose」「縮小搜尋區」。
- 理由：Vina 對任何胜肽都會給出 pose 與分數；大而柔軟的胜肽最常見的失敗是停在活性位旁的表面。這是科學假設問題，
  不是計算錯誤，所以用數字說清楚、交給使用者判斷，而不是擋下（表面結合本身也可能是研究目的）。
- 被否決：沿用 NEEDS_HUMAN＋override（使用者明確要求不影響後續）；用口袋體積計算（需 fpocket 等外部工具，容器與 Windows 都無法保證）。
- 門檻 25 %、4 Å、30 個鄰居是依原子密度估算的初值（蛋白重原子密度約 0.055 Å⁻³），尚未以實際胜肽–酵素共晶校正 → 未決。
- 證據：`tests/test_peptide.py`（提醒不擋、預檢三情境、口袋內與表面 pose 的合成幾何）、`tests/test_gate_actions.py::test_cpp_advisory_card_from_workflow`、
  `tests/test_validation_papers.py::test_cpp_gate_flags_grp`（GRP 被標註但不擋）。檔案：`md20/build/peptide.py`、`md20/build/gates.py`（`advisory` 欄位）、
  `md20/workflow.py`、`md20/gui/views.py`、`md20/gui/app.py`。

### D-46　鹽的種類與濃度要明確：md.ions（陽離子、陰離子、濃度、是否中和）
- 使用者（14:53）：離子濃度與種類標示不清，不一定只有 NaCl。
- 事實：原本只有 `ionic_strength_molar`，`addSolvent` 用預設 Na⁺／Cl⁻，報告寫「離子強度」——對 1:1 鹽其實就是鹽濃度，種類完全沒寫。
- 決定：`md.ions = {positive, negative, concentration_molar, neutralize}`；一價陽離子 Na⁺、K⁺、Li⁺、Rb⁺、Cs⁺，陰離子 Cl⁻、Br⁻、F⁻、I⁻
  （amber14/tip3p.xml 的 Joung–Cheatham 參數都有）。二價（Mg²⁺、Ca²⁺）、多原子陰離子與 > 2 M → NEEDS_HUMAN，選項可一鍵寫回。
  決策紀錄寫明鹽的種類、濃度與是否中和，實際離子數在 build_manifest `n_ions`（離子殘基名單擴充到 K、LI、RB、CS、BR、F、I）。
  舊設定 `ionic_strength_molar` 仍可用（等同 NaCl 該濃度）。
- 證據：`test_ion_spec_resolution`、`test_ion_gate_options_are_one_click`；實際放置待 CI。
- 未決：二價鹽的放置與參數（12-6-4 或 Li–Merz）。

### D-45　SMD「幀數倒退」：是黏滑與彈簧振盪，不是幀亂序；但窗口起始幀因此可能取在反彈點，已修
- 事實（使用者 14:42 提出，附筆電的 `smd_force_work.svg`）：力與功對「配體實際距離」作圖時，曲線沿距離來回折返，看起來像幀數倒退。
- 判讀：紀錄每 0.2 ps 一筆、時間單調，幀沒有亂序。折返段斜率 ≈ −k（1000 kJ mol⁻¹ nm⁻²），代表彈簧位置幾乎不動而配體距離跳動：
  拉離時先「卡住」再「滑脫」，滑脫後配體在彈簧中心附近振盪（小分子質量約 120 Da、k = 1000 時週期約 2 ps，Langevin γ = 1 ps⁻¹ 為欠阻尼），
  末段力為負（−150）表示配體跑到彈簧前面。這是拉離速度 0.01 nm ps⁻¹ 偏快、彈簧偏硬的典型現象，物理上可能，但**舊規則用「第一次越過窗口中心的幀」當窗口起點，這一幀常是反彈的瞬間**，
  配體帶著彈簧往回拉的位能進入窗口——這與 D-40 中「中心 0.604 nm 的窗口實際停在 0.27 nm」吻合。
- 決定：
  1. `WindowStartPicker`：越過中心後，改等「彈簧接近鬆弛」的幀（|彈簧位置 − 距離| ≤ 0.05 nm 且距離在中心 ±0.05 nm 內）；彈簧已超過中心 0.3 nm 仍沒有，才沿用第一次越過的幀並標記。
  2. `smd_ringing`：記錄相鄰紀錄最大跳動、倒退比例、配體超前比例；跳動 > 0.1 nm 時報告加註，建議降速。
  3. SMD 圖改為三格、橫軸用**彈簧位置**（隨時間單調）：距離（彈簧與配體兩條）、拉力、功。
- 證據：`tests/test_smd_window_starts.py`（反彈幀被跳過、改取鬆弛幀；全程落後時退回第一次越過且不漏窗口；振盪指標）。真實拉離待 heavy workflow。
- 未決：預設拉離速度是否從 0.01 降到 0.005 nm ps⁻¹（時間加倍）；等 teaching 重跑結果一起判斷。
  （使用者 2026-11-02 14:58：同意等 teaching 重跑結果出來後，由開發 session 判斷並另立條目記錄；已列入 WORKBOARD。）已存在的 SMD 結果（smd.json 已封存）續跑時沿用舊起點。

### D-44　GUI 改為「快速版／專業版」＋參數全開＋合理性檢查（使用者 2026-11-02 14:27／14:30）
- 使用者：舊版自由度大、圖表多，新版參數幾乎不能調、介面「很 AI」；不要教學版分級，只要快速版與專業版，專業版全部參數可調但系統要判斷不合理的設定。
- 決定：規格 `docs/specs/gui_v2.md`；互動原型（v2 Workbench）先給使用者點選審查，確認後才改 NiceGUI 程式。v1 原型保留在畫布上作對照，不刪除。
- 我的判斷：後端其實早已支援這些參數（`md.stage_overrides`、`BindingConfig`、`screen.*`、`pose_choices`…），問題在 GUI 只暴露了 6 個欄位；所以這是介面層的工作，不需改計算核心。
  合理性檢查要做成後端模組（GUI 與 CLI 共用），而不是只在前端。
- 未決：使用者要列出舊版有而新版缺的圖表。

### D-43　ΔG° 擋下的理由要具體；overlap 圖依實際取樣而非名目中心；pymbar 求解訊息收進報告；井深合理性提示
- 事實（D-40 筆電報告）：只寫「not converged」。追查後：MBAR 路徑永遠回報 converged=True，真正擋下的是 `graph_connected=False`——
  而它只檢查**名目中心相鄰**的 window 對；補窗後 k = 5000 的 window 會停在離中心很遠的位置（0.604 nm 取樣在 0.27 nm），相鄰中心的分佈不重疊，
  但所有取樣的聯集是連續的（自動補窗的連續性判定也是這樣說）。等於 overlap 判準與補窗判準互相矛盾。
- 決定：
  1. `assess_umbrella_samples`：連通性改為**所有 window 對**（取樣範圍有交集才算 overlap）建圖；名目相鄰的 pair_stats 仍保留給補窗建議。
  2. `mbar_pmf_1d`：pymbar 的 logger／stdout 訊息收集起來，不再印到學生的命令列；出現 "No solution found" → converged=False 並附 `solver_note`。
     `pmf_from_windows` 此時用 WHAM 對同一組樣本交叉驗證，ΔPMF 差 ≤ 2 kJ/mol 才接受（報告註明）。
  3. 報告的 ΔG° 擋下理由逐條寫出（重疊圖不連通／MBAR 未達容差且與 WHAM 差 X／WHAM 未收斂）。
  4. `well_depth_hint`：ΔPMF > max(40, 6.3 × 配體重原子數) kJ/mol 時加 caveat（取樣滯後等常見原因、建議 teaching 或延長 window）；不改數值、不擋流程。
- 證據：`tests/test_pmf_diagnostics.py`（滑動的硬彈簧 window 不破壞連通、真斷點仍被擋、井深提示門檻）；pymbar 路徑待 CI。
- 被否決：放寬 overlap 門檻（會放過真斷點）；用井深上限自動「修正」數值（沒有物理根據）。

### D-42　GUI 設計審查：CI 自動截圖每個頁面
- 決定：`tools/gui_preview.py` 建一個示範專案（含一個被擋下的閘門與決策），啟動 `md20 gui`，用 Playwright 截圖儀表板／新流程／流程頁／3D 檢視器；
  `.github/workflows/gui-preview.yml`（手動或 `md20/gui/**` 變更時觸發）上傳 PNG artifact，開發 session 下載後交給使用者審查。
- 理由：使用者要在週二前調整互動介面；開發容器裝不了 NiceGUI，筆電又正在跑 teaching 重跑。截圖讓介面修改可以「改→看→再改」而不佔用筆電。
- 未決：示範專案只有一個閘門狀態；需要時再加「跑完」「傘狀採樣中」等狀態的截圖。

### D-41　teaching／research 預設跑足它們要求的 window 長度
- 事實：`TIER_BINDING` 要求 teaching ≥ 500 ps、research ≥ 2000 ps 才輸出 ΔG°，但 `BindingConfig` 預設 window 只有 50 ps，`binding.config` 沒寫就照 50 ps 跑——teaching／research 永遠被自己的規則擋下，等於白跑。D-40 的重跑實驗會撞上這個坑。
- 決定：`Workflow._binding_config`：tier 有 `min_window_ps` 且使用者沒指定 `window_prod_ps` 時，自動採用該長度（equil = 長度 / 10，至少 10 ps），記 DecisionLog；使用者明確指定的值照用（仍由 tier 規則判定）。classroom 不變。
- 代價：每個 window 算力約為 classroom 的 10 倍（teaching）／40 倍（research）；報告與決策日誌寫明。
- 證據：`test_teaching_tier_runs_the_windows_it_requires`。

### D-40　筆電第一次真跑結果判讀：流程正確，但 ΔPMF 80 kJ/mol 不可信；閘門擋下 ΔG° 是對的
- 事實（RTX 4060 筆電，classroom 3PTB，workflow_report 05:06Z）：redocking RMSD 0.38 Å；MD 穩定（backbone 0.8–0.9 Å、BEN 全程在 S1 口袋，Asp189／Ser190／Gly219 接觸 100%）；
  SMD 最大力 524 kJ/mol/nm、功 251 kJ/mol；umbrella 自動補窗 6 輪 13 → 40 個 window，連續性通過；**ΔPMF 井深 80.3 ± 1.0 kJ/mol（≈ 19 kcal/mol），ΔG° 不輸出（`not converged`：MBAR 求解未達容差，pymbar 退回梯度 2.1e-4 的解）**；前／後半 85.0／82.1。
- 判讀（我的判斷）：苯甲脒–胰蛋白酶實驗 ΔG ≈ −6 kcal/mol（約 −26 kJ/mol），1D COM PMF 井深合理範圍約 25–50 kJ/mol；80 kJ/mol 偏大約 2–3 倍，**不能當作物理結果**。
  證據指向取樣滯後而非程式錯誤：補窗紀錄顯示中心 0.604 nm 的 window 實際停在 0.268 nm（彈簧 1000 時回復力 ≈ 336 kJ/mol/nm），配體被強力拉回口袋——短 window（classroom）下溶劑重新進入 S1、Asp189 鹽橋斷開等正交自由度來不及鬆弛，一維 CV 會把這些累積成假的高能障。bootstrap ±1.0 只反映 window 內雜訊，低估真實不確定度。
- 決定（下一步，尚未實作）：
  1. 報告寫明**哪一個**收斂條件沒過（MBAR 求解、overlap 圖連通、半段差、tier 規則），不再只寫「not converged」；pymbar 警告捕捉後寫進 caveat，命令列不再噴紅字。
  2. **井深合理性提示**：ΔPMF 超過「配體重原子數 × 經驗上限」或明顯大於 SMD 功的一半等條件時，報告標「井深異常偏大，常見原因：window 太短、路徑滯後」，給選項（teaching tier、延長 window、雙向／重跑）；不改數值、不擋流程。
  3. 第一個定量驗收改用 **teaching tier**（window ≥ 500 ps）在筆電重跑同案例（約數小時），以 ΔPMF 是否回到合理範圍判斷是取樣問題還是模型問題。
- 被否決：直接調參數讓數字變好看（沒有證據前不改物理）；把 classroom 的 ΔPMF 當驗收（tier 規則本來就不支持定量）。
- 未決：Woo–Roux／funnel 校正前，1D PMF 與實驗 ΔG 只能比趨勢（會診 §2）。

### D-39　Doctor 文字：Windows 11 被報成「Windows 10」、GPU 名稱重複「NVIDIA NVIDIA」
- 事實（MSI Cyborg 14 實機）：`platform.release()` 在 Python 3.11 的 Windows 11（build 26200）回傳 "10"；`nvidia-smi` 的名稱已含廠牌，前面再加 vendor 變成重複。
- 決定：`hardware.os_release()` 以 build ≥ 22000 判定 Windows 11；`hardware.gpu_label()` 名稱已以廠牌開頭時不重複；Doctor 報告、驅動 finding、`md20 drivers plan` 都改用。只影響顯示文字，不影響平台選擇。
- 證據：`tests/test_installer_paths.py::test_windows_11_and_gpu_label_seen_on_the_msi_laptop`。

### D-38　Windows 260 字元路徑：套件快取太深 → 安裝路徑過長時改放 `<磁碟>:\MD20pkgs`；並更正 D-36 的修正其實沒進 commit
- 事實（MSI Cyborg 14，2026-11-02 11:39）：CUDA 環境已解出（cuda-version 12.4、openmm 8.2.0），但解壓 pytorch 時
  `remove_all: The directory is not empty` 失敗。最深的檔案在
  `<root>\pkgs\https\conda.anaconda.org\conda-forge\win-64\pytorch-2.14.1-…\…\composable_kernel\docs\LICENSE.rst`，
  以 `C:\Users\user\AppData\Local\MD20` 為 root 共 263 字元（> 260）。pytorch 是 openff-nagl 的相依。
  安裝好的環境路徑（`envs\md20\Lib\…`）只有 182 字元，不受影響；問題只在 micromamba 的套件快取。
- 為什麼 CI 沒抓到：runner 的 root 是 `D:\a\_temp\MD20`（246 字元，剛好過）。快取版面下 root 最多只能 28 字元——**幾乎所有學生的 `%LOCALAPPDATA%` 都超過**。
- 決定：`install.ps1` 計算 `<root>\pkgs` + 226 字元，≥ 260 就把 `CONDA_PKGS_DIRS` 設成 `<root 所在磁碟>:\MD20pkgs`（建不出來就停並建議 `-Root C:\MD20`）。
  測試 `tests/test_installer_paths.py` 以已知最深檔案驗證規則。
- 被否決：開啟 `LongPathsEnabled`（改系統設定、需要系統管理員權限，且 micromamba 是否支援長路徑不確定）；預設 root 改為 `C:\MD20`（改變已發行的安裝位置與文件，留待使用者決定）；拿掉 openff-nagl（預設電荷模型依賴它）。
- 未決：`C:\MD20pkgs` 約數 GB，裝完可刪；是否由安裝器在成功後 `micromamba clean` 交給使用者決定。
- **更正 D-36**：09be59f 其實**沒有**刪掉 `windows-cuda.yml` 的 `ocl-icd-system`（那行 `sed` 接在一個失敗的指令後面而沒有執行）；所以 1440c02 的
  CI「CUDA dry-run solve」紅燈是**正確的**。筆電能解出是因為本機副本是另外手動修補的。本 commit 才真正移除，並加測試防止再發生。

### D-36　Windows CUDA 安裝路徑壞掉：`windows-cuda.yml` 列了 Windows 不存在的 `ocl-icd-system`；發行 v0.1.0a2
- 事實：使用者 MSI Cyborg 14（RTX 4060 Laptop，驅動 566.14／CUDA 12.7，Windows 11 26200）以 v0.1.0a1 自測，`[2/4] 建立環境 (cuda)` 失敗：
  `ocl-icd-system =* * does not exist (perhaps a typo or a missing channel)` → `Could not solve for environment specs`。
  該行註解寫「harmless if solver drops it」——錯的：micromamba 不會略過不存在的套件，而是整個解不出來。
- 為什麼 CI 沒抓到：runner 沒有 `nvidia-smi`，安裝器一律走 OpenCL／CPU；`windows-cuda.yml` 從未被解過。v0.1.0a1 等於「所有 NVIDIA 學生機都裝不起來」。
- 決定：移除該行；CI `installer-windows` 與 `release-windows` 驗證都加上 **CUDA 環境 dry-run solve（cuda-version 12.4 與 11.8，`CONDA_OVERRIDE_CUDA=12.7`）**，解不出來就紅、不發行；版本 0.1.0a2。
- 實機：筆電上已解壓的 a1 副本同樣移除該行後重跑安裝（`MD20_test\local_src.txt` 指向它），結果記入 `docs/COMPATIBILITY.md`。
- 被否決：在 install.ps1 失敗時自動退回 OpenCL——會把真正的設定錯誤藏起來，RTX 卡卻跑 OpenCL（寧可擋也不要猜）。

### D-35　筆電實機測試：一鍵自測腳本 `installer/MD20-SelfTest.cmd`
- 決定：新增雙擊即跑的自測腳本（cmd/PowerShell 5.1 polyglot、純 ASCII、CRLF）：系統資訊（OS、CPU、RAM、GPU/驅動、`nvidia-smi`、各磁碟剩餘）→ 下載最新 Release ZIP 並比對 SHA256 → `Install-MD20.cmd` → `doctor` → `drivers plan` → `demo` → 啟動 GUI 並以 HTTP 200 判定 → `pipeline example` 改 `tier: classroom` 後 `pipeline run --project laptop_test`。全程 `Start-Transcript` 寫到 `桌面\MD20_test\selftest_<時間>.log`，最後印每步 rc 與耗時。
- 理由：筆電 session 的遠端工具是 Linux VM（不能執行 Windows 程式、量不到 Windows 的 GPU），電腦操作對終端機只允許點擊、不允許輸入；所以由使用者雙擊一次、Claude 讀 log 是唯一可稽核且不繞過權限的做法。
- 安全（初版）：**不刪任何東西**。若 `%LOCALAPPDATA%\MD20`（或 `MD20_ROOT`）已有 `app`／`envs\md20`／`md20.cmd`，安裝步驟跳過並列出路徑（安裝器會 `Remove-Item` 取代 `app`，須先問使用者），改用既有安裝繼續測。
- 更正（2026-11-02 09:50）：使用者授權 Claude 在本專案範圍內自行新增／刪除檔案。自測腳本改為一律執行安裝（安裝器取代 `app`、沿用並補齊環境），log 會列出被取代的路徑；另加 `MD20_test\local_src.txt`（一行：含 `Install-MD20.cmd` 的資料夾）供開發時用修補過的本機副本安裝。
- 更正（2026-11-02 22:28）：固定專案名 `laptop_test` 第二次執行時 `pipeline run` 直接回報 COMPLETE（0.5 分鐘、沿用舊結果），自測失去意義；改為每次 `laptop_<時間>`。
- 未決：電池模式下 pipeline 會依 PausePolicy 暫停（測試時請接電源）；中文使用者名稱路徑由本次實機驗證。

### D-37　安裝器不再刪除舊版 `app`：改為移到 `_to_delete\app-<時間>`（使用者規則「刪除前先問」）
- 事實：D-33 的 `install.ps1` 在 ZIP 安裝時會 `Remove-Item` 既有的 `%LOCALAPPDATA%\MD20\app` 再複製新版；筆電 session（D-35）指出這違反使用者「刪除任何東西前先問我」的規則。
- 決定：改為 `Move-Item` 到 `%LOCALAPPDATA%\MD20\_to_delete\app-yyyyMMdd-HHmmss` 並印出路徑，由使用者確認新版可用後自行刪除。安裝器內不再有任何刪除動作（`tmp`／`pipcache` 也不清）。
- 理由：安裝器是非互動執行（CI、雙擊），無法在中途詢問；移走不刪是唯一同時滿足「不中斷」與「不刪」的做法。
- 證據：release workflow 的 verify-windows 為全新安裝（不觸發此分支）；重裝情境待筆電實測。
- 編號註記：與筆電 session 同時寫的 D-36（CUDA 安裝修正）撞號，本條改為 D-37。

### D-34　鋅鍵結模型偏移：先診斷再改物理
- 決定：先不改模型；`test_bonded_zinc_ca2` 在失敗時附上平均鍵長、r0 與「Zn 3 Å 內的非鍵重原子（殘基:原子、出現幀數、平均距離）」。
  依證據在三個假說中選修法（`docs/specs/metal_sites.md` §4c：H1 第四配位水、H2 元素×配位原子力常數、H3 Li–Merz IOD LJ）。
- 理由：k = 46 已在 ZAFF 範圍，猜著加大 k 或放寬容差都可能掩蓋真正的推力來源（寧可擋也不要猜）。這個失敗是約 50% 機率出現的臨界值，下一次紅就會帶出診斷。
- 證據：待 heavy metal。未決：H1 若成立，需要決定 CA II 的第四配位是 H₂O 還是 OH⁻（pH 依賴，應走閘門讓使用者決定）。

## 2026-11-01（第一個 session，續）

### D-33　Windows 安裝程式發行：GitHub Release ZIP＋雙擊 `Install-MD20.cmd`，發行前在 Windows 實裝驗證（使用者要求 11/02 11:00）
- 決定：
  - 發行物＝`MD20-Windows-<tag>.zip`（`git archive`，`*.cmd` 以 `.gitattributes` 保持 CRLF）＋`SHA256SUMS.txt`，GitHub Release（prerelease）。
  - 入口＝repo 根目錄 `Install-MD20.cmd`：雙擊即以 `-ExecutionPolicy Bypass` 執行 `installer\install.ps1`，參數透傳（`-Gpu`、`-Root`、`-Cuda`），結束時顯示成功／失敗並暫停。
  - `install.ps1`：不是 git checkout（ZIP）時，先把程式**複製到 `%LOCALAPPDATA%\MD20\app`** 再從那裡安裝（解壓資料夾通常在「下載」且會被刪）；git checkout 維持原地 editable。
    原生指令（micromamba create/install、pip）失敗即停並說明（PS 5.1 的 `$ErrorActionPreference=Stop` 不攔原生指令的 exit code，之前會「看似完成」）；Vina 下載失敗只警告。
  - `.github/workflows/release-windows.yml`：tag `v*` 觸發 → 打包 → **在乾淨 Windows runner 解壓、雙擊入口安裝（PS 5.1、CPU）、刪除解壓資料夾後 doctor／demo／pipeline example 仍可執行** → 才建立 Release。
  - 版本 0.1.0a1（教學預覽版）；發行說明 `docs/releases/v0.1.0a1.md` 誠實列出已知限制。
- 理由：學生不一定會 git；交付物必須是「下載→解壓→雙擊」。只發行 CI 證明可裝、可在原資料夾刪除後運作的那一個 ZIP。
- 被否決（這次）：Inno Setup／NSIS 的 `setup.exe`（未簽章的 exe 一樣會被 SmartScreen 擋，且 3 小時內無法在真機驗證；可作下一版）；
  把整個 conda 環境打包離線安裝（約 3–4 GB，且 CUDA／OpenCL 變體要分開打包）。
- 未決：程式碼簽章（SmartScreen 警告）；離線安裝包；`Install-MD20.cmd` 在中文使用者名稱路徑下的實機驗證。

### D-32　1634916：Windows 真全綠；macOS GBn2 最小化 NaN、heavy workflow umbrella window NaN、鋅模型平均偏 0.31 Å
- 事實（run 41347336927）：**Windows OpenCL 366 passed、5 skipped**（skip 全是設計內：MD20_HEAVY／MD20_PAPERS／playwright），
  `test_docking_integration`、`test_screen_integration` 這次真跑通過（D-31 有效）；Ubuntu 366 passed；installer-windows、pose-screen、paper-docking 綠。紅三項：
  1. macOS `test_3ptb_gbn2…`：OpenMM 在**最小化途中**丟 `Particle coordinate is NaN`；同一測試在 99c8b64 的 macOS 通過（程式未變）→ 平台差異或數值偶發，原因未確定。
  2. heavy workflow：umbrella 第一批 window 的平衡段 NaN，例外直接中止整個 workflow（81b72d9、99c8b64 同程式通過；本輪 gemmi 讓 meeko 正常 import，對接 pose 可能不同）。
  3. heavy metal：D-29 的平均判定下 Zn–His94 NE2 平均 2.34 Å（r0 2.03，σ 0.08 Å）——**依 D-29 的約定這是模型問題，不再調測試**。
- 決定：
  - 引擎 `_minimize`：最小化途中的 NaN 轉為 NEEDS_HUMAN（學生看得懂的原因與選項：檢查碰撞／改 CPU 平台／改 explicit），不再是原始 traceback。測試 `test_minimizer_nan_becomes_needs_human`。
  - umbrella `sim_window`：NaN → 從同一起點（偏壓開著）短暫最小化、重給速度、**半步長、相同模擬時間**重跑一次並記 AUTO_FIXED；再失敗就停下回報，不內插、不略過 window。
  - GBn2 整合測試固定用 CPU 平台（三 OS 一致；GPU 上的 GBn2 留給真機驗證）。
  - 鋅模型：不改測試，列為模型待修（會診 §3 Q2 依元素×配位原子的力常數表、§3 Q1 Li–Merz IOD LJ、配位水納入鍵結），**不擋 Windows 里程碑**（只在 Ubuntu heavy 跑）。
- 被否決：再放寬鋅的容差（違反 D-29 約定）；umbrella NaN 時跳過該 window（會留下覆蓋斷點、把錯藏起來）。
- 證據：純 Python 本地全過；NaN 重試路徑待 heavy workflow 重跑（無法在容器內觸發真 NaN）。
- 未決：GBn2 在 macOS 最小化 NaN 的根因；heavy workflow 的 NaN 是 pose 不同還是 D-23 釋放側鏈後拉離更劇烈。

### D-31　Windows 的 meeko 其實沒裝好（缺 gemmi）→ 對接／HTS 整合測試在 Windows 一直是 SKIPPED，綠是假的
- 現象：99c8b64 Windows openmm-stack「351 passed, 7 skipped」綠，但 skip 原因是 `could not import 'meeko': No module named 'gemmi'`——
  `test_docking_integration`、`test_screen_integration` 整檔跳過。明早筆電用同一條安裝路徑，對接第一個配體就會 ImportError。
- 決定：`gemmi` 加進 `environment/base.yml` 與三處 pip 安裝行；openmm-stack job 設 `MD20_STACK=1`，`tests/test_stack_present.py` 在該旗標下
  **斷言**所有核心套件可 import（openmm、rdkit、openff、meeko、vina…），缺了就紅，不再是 skip。
- 理由：`importorskip` 讓「環境壞了」看起來像「這台機器不需要」；在宣稱有全套的 job 裡，skip 必須是失敗。
- 證據：CI 這輪（Windows openmm-stack 的 skip 數應降到 ≤ 5，且 docking／screen 整合測試出現在 PASSED 裡）。
- 未決：macOS／Ubuntu 是否也靠別的套件間接帶入 gemmi（現在明寫後無差）。
- 編號註記（session_016gcJz8q2F6515MWPncJEZu）：原標為 D-30，與 99c8b64 的「Windows 時間預算」D-30 撞號，改為 D-31；內容未動。

### D-30　Windows 時間預算：GBn2 3PTB 測試只驗管線（f140a49 Windows 84／90 分鐘）
- 事實：f140a49 Windows OpenCL 338 passed／1 failed（同 D-28 的連接圖，已修），但總時長 **84 分鐘（上限 90）**：
  `test_nacl_pmf` 2475 s、縮短後的 GBn2 3PTB 仍 1971 s（Ubuntu 1231 s、macOS 1405 s）——CPU runner 上每次 GB 力評估約 1.5 s。
- 決定：GBn2 3PTB 測試每 stage 20 步、最小化 50 次（物理驗證不在 CI 的 CPU 上做）。
- 理由：明早 Windows 里程碑不能撞時間上限。被否決：拉長 openmm-stack 上限（掩蓋問題）。
- 另：鋅測試單幀判定的問題我也獨立修了一版，與另一 session 的 D-29（dcdc8a9）撞號；採用對方版本（種子＋後半段平均＋任一幀偏離上限），我的版本捨棄。
- 未決：NaCl PMF 在 Windows 41 分鐘偏長；會診 §3 Q2 力常數依元素×配位原子可能才是 Zn–His119 2.39 Å 的根因。

### D-29　鋅鍵結模型測試改為「固定種子、後半段平均」，不再以單一幀判定
- 現象：`test_bonded_zinc_ca2` 在 64166b7 綠、81b72d9 紅（Zn–His119 ND1 2.39 Å vs 2.02），兩者之間 `md20/build` 只改了一行註解——是測試不穩定，不是模型退步。
- 決定：積分器與初始速度固定種子；跑 2 ps 丟掉瞬態，再 2 ps 每 0.1 ps 取樣；**平均**鍵長與 r0 差 < 0.3 Å，且任一幀偏離 < 0.8 Å（真的鬆脫才算）。
- 理由：從晶體座標＋隨機速度起跑，前 2 ps 溶劑未平衡，單一幀是雜訊；鍵結模型的物理主張是「平均幾何守住」，測試要量它主張的東西。容忍值不放寬（0.3 Å 已比 ZAFF 等級的 0.1 Å 寬）。
- 證據：CI heavy (metal)（待這輪）。
- 未決：若平均值也偏 > 0.3 Å，則是模型問題（His119 ND1 的 1-4 或角項），不得再調測試。

### D-27　驅動問題徹底解決：偵測→判定→一鍵下載官方驅動；不自動安裝（使用者要求）
- 決定：`md20/env/drivers.py`：驅動→CUDA 對照表判定 OK/UPDATE/FALLBACK/NONE，NVIDIA 用 nvidia.com 下載頁背後的查詢服務對型號取最新 WHQL 載點，
  只從官方 https 網域下載到 ~/Downloads、不執行；查不到就官方頁面不猜。`md20 drivers`、Doctor finding、GUI 卡片、安裝器 `-Cuda`。
- 被否決：靜默執行驅動安裝器（需管理員與重開機，不該由程式代做）；從非官方鏡像下載；對不到型號時用「最接近」的猜。
- 證據：`tests/test_drivers.py`（11，含查詢服務 fixture）；真機驗證待明早筆電。規格 `docs/specs/drivers.md`。
- 未決：查詢服務非正式 API，變動時退化為官方頁面。

### D-26　Windows 安裝器必須在 Windows PowerShell 5.1 下可跑，且由 CI 真的執行
- 決定：`install.ps1` 移除 PS7 專用的 `?.`／`??`（內建 `powershell.exe` 是 5.1，第一行就語法錯誤）；加 UTF-8 BOM（5.1 讀無 BOM 的 UTF-8 會把中文當 ANSI）；
  設 `PYTHONUTF8=1`；產生 `md20.cmd` 與桌面 `MD20-GUI.cmd` 啟動器。新增 CI job `installer-windows`：用 `shell: powershell`（5.1）跑安裝器，再用 `md20.cmd` 跑 doctor／demo／範本。
- 理由：安裝器是學生與明早測試筆電的第一步，但 CI 用 setup-micromamba 建環境，從未執行過安裝器本身。
- 證據：CI `installer-windows`（待這輪）。文件：`docs/WINDOWS_QUICKSTART.md`（安裝→doctor→demo→GUI→真實案例→回報清單）。
- 未決：CUDA 路徑只能在真機驗證（runner 無 GPU）。

### D-28　f140a49：Ubuntu／macOS openmm-stack 各剩 1 紅（配體連接圖對應）、heavy workflow 1 紅（測試鍵名）
- 事實（run 41320101307）：Ubuntu 342 passed／1 failed（49 分鐘）、macOS 同（68 分鐘）——D-25 的修正生效：質子化教科書案例、HTS 測試、
  縮短後的 GBn2 3PTB、`test_restraint_groups_openmm`（分組約束實算）全過；heavy pose-screen、metal、paper-docking 綠。
  1. `test_shuffled_pose_without_bond_orders_maps_by_graph`：**D-18 我寫的** `_connectivity_match` 用 `AdjustQueryProperties(makeBondsGeneric)` 當查詢，
     但查詢原子仍比對芳香旗標與非零形式電荷；只有座標的 pose 沒有芳香性也沒有電荷 → 苯甲脒的苯環與 NH2+ 對不上。
  2. heavy `test_full_workflow_3ptb`：PBC 檢查以組裝後的配體殘基名（L01）為鍵，測試寫成 BEN（另一 session 的 D-21 測試）。
     實際值顯示功能正確：原始 DCD 看起來 6.95 nm（已解離），歸零後 0.205 nm，並記 AUTO_FIXED。
- 決定：(1) 兩邊都轉成「只剩元素的圖」再比對（`_bare_graph`：電荷 0、非芳香、所有鍵 SINGLE、無立體），仍要求鍵數相同＋完整匹配，
  乙醇／二甲醚的反例照樣被擋；(2) 測試改為檢查每個配體的 `true_nm < 1.0`，不綁輸入名稱。
- 證據：待下一輪 CI（容器沒有 RDKit）。

### D-25　c4b5de6 openmm-stack 三 OS 紅：質子化 SMARTS 寫錯、HTS 純路徑測試遇到 RDKit、GBn2 在 CPU 極慢
- 事實（run 41309973844；Ubuntu 16 failed／239 passed，87 分鐘；Windows／macOS 撞 90 分鐘上限）：
  1. **我寫的** `ionize` 脂肪胺規則 `[NX3;…;!$(N-[!CX4])]`：SMARTS 隱式 AND 比 `!` 緊，`[!CX4]` 是「非脂肪碳 **且** 4 連接」，
     幾乎什麼都不匹配 → 苯胺、乙醯胺、醯基胍、已帶電苯甲脒的 NH2 都被質子化（苯甲脒變 +2）。這是 D-18 的錯，本地沒有 RDKit 所以沒抓到。
  2. `test_ligand_mapping`：numpy.int64 傳給 `Conformer.GetAtomPosition`（Boost 不收），測試本身的錯。
  3. HTS 的 `test_screen_library`／`test_screen_workflow`（另一個 session）：測試用 1 原子的假 SDF，在有 RDKit 的環境被大小篩選
     （5–80 重原子）全部略過。程式行為正確，是測試只為無 RDKit 環境寫。
  4. `test_3ptb_build_and_short_md`／胜肽：D-22 的 `np` 未匯入（D-24 已修）。
  5. **GBn2 3PTB 測試在 Ubuntu CPU 跑了 3921 s（65 分鐘）才通過**；Windows/macOS 因此超時。CustomGBForce＋NoCutoff 是 O(N²)，
     CPU 上每次能量評估約秒級。
- 決定：(1) 規則改為 `!$(N~[#6;!X4])`（任何非 4 連接的碳鄰居都排除），程式內註明這個 SMARTS 陷阱；
  (2) 測試以 `int` 索引；(3) 兩個 HTS 測試檔加 autouse fixture 把 `_rdkit_available` 固定為 False（RDKit 路徑由 `test_screen_integration` 驗證）；
  (4) GBn2 整合測試縮到每 stage 0.4 ps、最小化 100 次（只驗管線，不驗物理）；GBn2 的決策說明改為「**有 GPU 才明顯較快，CPU 上可能比顯式水慢**」。
- 更正 D-20／`implicit_solvent.md`：原寫「筆電上快很多」只對有 GPU 的筆電成立。使用者主力 GTX 1060（OpenCL）適用；純 CPU 筆電不該推薦 GBn2。
- 被否決：把 openmm-stack 步驟上限從 90 分鐘拉長（掩蓋真問題）；預設給 GB 加截斷（改變物理，需另行驗證）。
- 未決：GBn2 在 CPU 平台時應自動 NEEDS_HUMAN 或建議 explicit（需要在 workflow 取得實際平台）；GBn2 截斷（2 nm、CutoffNonPeriodic）的準確度與速度評估；
  NaCl PMF 測試 1190 s 偏長。

### D-24　heavy CI 紅：`np` 未匯入（fc4da13）＋純 Python 靜態未定義名稱檢查；鋅鍵結模型確認修好
- 事實：c4b5de6（run 41309973844）heavy workflow 與 pose-screen 都死在 `build/assemble.py` 溶劑化後的 `np.linalg.det`
  （D-22 新增的盒體積紀錄；模組沒有 `import numpy as np`）。同一輪 **heavy metal 全綠**——`test_bonded_zinc_ca2` 通過，
  另一 session 的經金屬 D–M–D′ 1-3/1-4（9c20327）確實修好 Zn–His 配位漂移（12dcd80 時 2.03→2.56 Å）。
- 決定：模組層補 `import numpy as np`；新增 `tests/test_static_names.py`：以標準庫 `symtable` 檢查每個函式引用的全域名稱
  都在模組層定義或為 builtin（容器與 CI 都沒有 pyflakes，不新增依賴）。已驗證拿掉該 import 時此測試會紅。
- 理由：這類錯誤只在 OpenMM 路徑上執行到才爆，heavy 要 10 分鐘以上才看到；靜態檢查在 6 個純 Python 平台幾秒內擋下。
- 被否決：在 pure-python CI 安裝 pyflakes/ruff（多一個依賴與版本漂移；本檢查只需要未定義名稱這一類）。
- 未決：屬性錯字、參數錯誤仍只能靠整合測試。

### D-23　約束策略修正：分組約束、主要釋放移到 NPT、配體 k ≥ 蛋白、受約束 RMSD 標註（會診 §1 Q1）
- 決定：
  - `add_position_restraints` 改為**單一力、三組**：`msw_position_restraints` 每粒子參數 `k, x0, y0, z0, grp`
    （0 主鏈 N/CA/C/O/OXT、1 蛋白側鏈重原子、2 配體重原子），能量 `0.5·msw_restraint_scale·msw_rs_<grp>·k·d²`；
    各組 `msw_rs_*` 預設 1.0。k：主鏈 1000、側鏈 1000、**配體 1000（原 500）**。水、離子、金屬、輔因子不約束。
  - `make_protocol(restraints=standard|gentle|hold_backbone)`，設定鍵 `md.restraints`（未知值 → NEEDS_HUMAN，選項可一鍵寫回）。
    standard：NVT 主倍率固定 1.0、bb 1→1、sc 1→0.5、lig 1→1（只升溫）；NPT bb 1→0、sc 0.5→0、lig 1→0；production 0。
    gentle：NVT 全 1→1，NPT 全 →0 且 NPT 長度 ×2。hold_backbone：NPT bb 1→0.05，production bb 0.05（50 kJ/mol/nm²）全程。
  - `engine.protocol.production_restraints()` 判斷 production 是否受約束；`analyse_run` 寫入 `restrained_production`，
    圖例與工作流程報告的 RMSD 欄標「受約束；低 RMSD 不代表結構穩定」。
  - SMD／umbrella（`build_pulling_system`）把配體**與側鏈**的 k 設 0，只留主倍率縮放後的主鏈；舊 build（4 參數、無 grp）照舊處理。
- 理由：會診 Q1——Amber／Desmond 都在 NPT 內釋放，NVT 中釋放＝在錯誤密度下鬆弛；k ≤ 1000 的位置約束對 barostat 體積偏差可忽略，
  先前 WP4「約束主要在 NVT 放掉」的顧慮被業界慣例否決。最小化時配體 k 低於蛋白是反的（溶劑未鬆弛前對接 pose 最容易漂）。
  單一力＋`grp` 參數比三個力好：binding、metal 整合測試與舊 system.xml 都只認 `msw_position_restraints` 這個名字。
  側鏈在拉離時必須自由，否則口袋無法重排、PMF 偏高。
- 取捨／影響：預設 protocol 的雜湊改變——**新程式對進行中的舊 run 會從受影響的 stage 重新跑**（identity 不同，這是正確行為：
  約束排程改了，舊平衡不再代表新 protocol）；已 COMPLETE 的 workflow MD 不重跑。側鏈現在也被約束（原本不約束），最小化與 NVT 更穩。
- 被否決：三個分開的力（破壞既有名稱約定）；把主倍率也做斜坡（與各組斜坡重複、難以閱讀）；hold_backbone 直接當預設（低 RMSD 誤導學生）。
- 證據：`tests/test_restraint_strategy.py`（7，純 Python：排程、連續性、gentle/hold、未知策略擋下、GUI 一鍵、報告標註）、
  `tests/test_restraint_groups_openmm.py`（Reference 平台實算各組能量與 binding 釋放側鏈；CI openmm-stack 驗證）。
- 未決：`recommend_restraint_strategy`（依解析度、AlphaFold、補 loop、碰撞、胜肽、金屬自動建議 gentle）尚未做；凍結與截斷仍在規格階段。
  hold_backbone 時 NPT 末段 density 驗收仍在約束下計算（可接受，待真實資料確認）。

## 2026-11-01（第三個 session）

### D-22　水盒不過大：菱形十二面體 + tier padding + 下限閘門（使用者原則）
- 決定：預設 `box_shape=dodecahedron`（立方的 71%）；`padding_nm` 未指定時 classroom／teaching 0.8、research 1.0；< 0.6 nm NEEDS_HUMAN；
  篩 pose 短 MD 用 min(pad, 0.8)；`md.ionic_strength_molar` 可設 0（只中和）。水比例閘門改為說明而非警告。
- 理由：算力在水（80–90% 原子），立方盒以最長軸定三邊對細長蛋白浪費最大；鹽 < 1% 原子，不是成本（誠實告知）。
- 被否決：長方盒貼合蛋白（蛋白旋轉後短邊碰影像）；padding 0（蛋白與影像直接接觸）。
- 證據：`test_binding_raises_padding`；CI `test_3ptb_build_and_short_md` 斷言非對角盒向量且水 < 9000。規格 `docs/specs/solvent_box.md`。
- 未決：0.8 nm 對 teaching 是否太緊；十二面體在 VMD 的顯示。

### D-21　週期邊界歸零：分析層錨定＋歸零 DCD，不在模擬中加力（使用者痛點）
- 決定：`analysis/pbc.py`＋`traj.center_trajectory`：錨＝蛋白鏈＋bonded 金屬（manifest），其他分子以質心最小影像折回，錨質心置盒中心；
  `analyse_run` 一律輸出 `production_centered.dcd`／`production_aligned.dcd`，可重現包含歸零版；viewer 走同一條。
  `apparent_vs_true_distance` 在原始與歸零後差 > 0.5 nm 時記 AUTO_FIXED「視覺性假象」。
- 理由：蛋白擴散是物理，`CMMotionRemover` 只除整體質心；症狀來自 per-molecule 折回與 mdtraj 自猜錨（多鏈／胜肽／金屬是獨立分子）。
- 被否決：模擬中加「歸零」約束（改物理）；把 `enforcePeriodicBox=False` 寫 DCD（原子座標無界、檔案與工具相容性差，且仍需 image）。
- 證據：`tests/test_pbc_centering.py`（6）；CI `test_full_workflow_3ptb` 斷言歸零檔與 `true_nm`。規格 `docs/specs/pbc_centering.md`。
- 未決：多配體互相錨定；三斜盒只靠 mdtraj。
- 另一個 session 留言（GBn2 無週期盒）：已處理——`center_trajectory` 無盒時只置中（質心到原點）、不折影像。

### D-20　隱式溶劑 GBn2（會診 §1 Q6）
- 決定：`md.solvent: explicit|gbn2`、`docking.pose_md_screen.solvent`；細節見 `docs/specs/implicit_solvent.md`。
  GB 力用 OpenMM 內建 `GBSAGBn2Force`（依元素／鍵結指派 mbondi3），因為 `implicit/gbn2.xml` 對 OpenFF/GAFF 配體沒有參數。
  NPT 改 NVT、約束排程保留；金屬位點與結合自由能在 gbn2 下 NEEDS_HUMAN（GUI 一鍵改回 explicit）。
- 取捨：預設仍為 explicit；篩 pose 預設是否改 gbn2 等三個 OS 的 CI 結果再決定。被否決：用 `implicit/gbn2.xml` 加配體樣板（每個配體都要補 GB 參數，不可行）。
- 證據：`tests/test_workflow_gates.py::test_gbn2_protocol_and_binding_gate`（本地）、
  `tests/test_real_case_integration.py::test_3ptb_gbn2_implicit_solvent_short_md`（三 OS CI）。

### D-19　重測拆成平行 job（會診 §5 Q2）
- 決定：`openmm-stack` 三個 OS 跑同一套（不帶 MD20_HEAVY）；新增 `heavy` job（Ubuntu）矩陣 workflow／pose-screen／metal 平行，
  各自 75 分步驟上限、各自貼「CI heavy (<組>)」留言（`tail -c 40000 pytest.log`，含 traceback）。
- 理由：單一 job 時任何一項慢（3e7f941：NaCl PMF 與 3PTB 全流程各 > 15 分）就讓整個步驟在 100 分逾時，被殺掉的 pytest 不印 FAILURES，
  `test_bonded_zinc_ca2` 的失敗原因連續三輪讀不到。
- 取捨：每個 heavy job 各自建環境（多約 3 分 × 3，有下載快取）；換來失敗可診斷與總時間縮短。

### D-18　採納會診 §0：配體依 pH 7.4 主要離子態對接；GUI 預設只本機可連
- 配體質子化：在 `docking/run.py::_ligand_mol`（SMILES 與 SDF 兩條路、HTS 也經過）呼叫 `docking/ionize.py`。
  MD 建模的 SMILES 取自對接結果裡的分子，所以對接、HTS、MD 三邊同一電荷態。
  - 規則只處理 pKa 離 7.4 夠遠的類別（羧酸、磺酸、磷酸第一個 OH、四唑、醯基磺醯胺 → −1；sp3 脂肪胺、脒、胍 → +1）；
    咪唑、羥肟酸、磷酸第二個 OH 等接近 7.4 的不改、只註記；已帶電的基團不動（使用者明寫的電荷態保留）；
    陽離子 3 個鍵內的第二個胺不質子化（piperazine pKa₂ 5.6）；pH 偏離 7.4 超過 1 時規則不套用並註記。
  - 被否決：引入 dimorphite-dl（會診建議）。理由：規則表透明、可教、零新依賴，且 dimorphite 在 pKa 精度窗內會給多個態、仍需選擇規則；
    若之後需要更廣的官能基覆蓋再接 dimorphite 作為可選後端。
  - `docking.protonation: auto|as_given`（全域；每個配體可覆蓋）；HTS `screen.protonation`／`screen.ph` 預設跟隨工作流程。
  - 證據：`tests/test_ionize.py`（23 個教科書 pKa 類別＋SDF 座標保留；需 RDKit，CI）。
- GUI：`md20 gui` 預設 `--host 127.0.0.1`；`0.0.0.0` 需明確指定並印出警告。`tests/test_gui_logic.py::test_gui_listens_on_localhost_by_default`。
- 會診 §0.3（舊規格標示取代）已由另一個 session 完成。

### D-17　REVIEW #15／#16：配體直接配位金屬要擋；pose 對應要比連接圖，不能只比元素順序
- #15 決定：組裝時在配體加入後、溶劑化前，對整個複合物重新找「配體 N/O/S 在金屬配位距離內」（N ≤ 2.45、O/S ≤ 2.6 Å）。
  有 → NEEDS_HUMAN（選項：換 pose、MCPB.py/QM 參數化後匯入、metal_policy remove〔僅限非功能必要，GUI 可一鍵〕）。
  理由：金屬位點原本只在受體上分析，對接 pose 咬住金屬時永遠不會被發現；力場沒有配體–金屬鍵，非鍵結模型下配位會散開或塌陷。
- #16 決定：模板指定鍵級失敗時，不再接受「元素序列逐一相同」的原子順序對應；改為由 pose 座標判斷連接（不計鍵級）、
  與參考分子做「鍵類型不限」的子結構比對，原子順序不同也能對上；鍵數或連接圖不同 → NEEDS_HUMAN。
  理由：乙醇 C–C–O 與二甲醚 C–O–C 可以有相同元素順序，舊後備會把座標貼錯原子且標 AUTO_FIXED。
- 證據：`tests/test_metal.py::test_ligand_coordinating_metal_is_stopped_after_assembly`（本地）；
  `tests/test_ligand_mapping.py`（需 RDKit，openmm-stack CI）。組裝路徑的真實檢查待 CI。

### D-16　補窗必須可續跑且冪等：完成的輪次不重新規劃
- 問題（3e7f941，Windows OpenCL，`test_nacl_pmf`）：第二次呼叫 `run_binding`（續跑）得到不同 ΔPMF（3.518 → 3.396 kJ/mol）。
  續跑時補窗迴圈從第 1 輪重新開始，拿已補過的全部樣本重新規劃，又多補 window，改變了已完成的 PMF。
- 決定：`refine_log.json` 每輪完成時標記 `completed`；`refine_state.json` 記錄是否已結束與手動 window 簽章。
  續跑從下一個未完成輪次接續；已結束則整段略過。只有使用者加入新的手動補採樣區間時才重新開啟，並給一份新的輪次預算。
- 被否決：只比對 window 檔案是否存在（無法區分「中途暫停」與「已結束」）。
- 與第四個 session（21bb0f1）合併：對方的 `finished_result()` 處理「已完成 → 直接回傳儲存結果」，並限制每個 window
  最多延長 2 次（`max_extensions_per_window`，解決同一測試的 15 分鐘逾時）；本條的輪次標記處理「中途暫停／當機後續跑」，
  兩者互補。延長次數改以 `w_<c>_ext*.done` 檔案計數，手動請求重開的輪次也算在內。
- 證據：待 CI（`test_nacl_pmf` 的冪等斷言）。同輪 Windows 其餘 170 個測試通過。

### D-15　決策與規格一律寫進 repo 的 Markdown
- 決定：任何專項修改都把討論結論或判斷寫進 `docs/DECISIONS.md`（本檔）與 `docs/specs/`，與程式碼同一個 commit 推送。規則寫入 `CLAUDE.md`。
- 理由：使用者要能審查、做版本管理，並用其他模型審查規格後回饋。
- 附帶：只改文件的 push 不再觸發 CI（`paths-ignore: docs/**, *.md`），避免文件更新取消正在跑的長時間重測。

### D-14　hsieh2024 無法重現的原因：ADT 格點數被當成 Vina 的 Å
- 決定：以 CI 量測結論更新教學案例；建議新增「盒子過大」防呆閘門（待審查，見 `docs/specs/REVIEW_QUESTIONS.md` 第 5 點）。
- 證據（37bc6b1，`test_hsieh2024_box_hypotheses`）：論文盒子照字面 28.5×34.5×26.25 Å 在 1VKX 框到 0/11 個報告殘基；
  讀成 76×92×70 Å（格點數誤當 Å）框到全部 9 個存在的報告殘基；中心距 1VKX 原子 0.48 Å、在 1VKF 中落於蛋白外 39.6 Å。
- **更正**：先前判斷「主因是中心座標來自另一座標系」是錯的；使用者提出的格點間距混淆假設才正確。

### D-13　傘狀採樣改為由粗到細的智慧補窗，並提供即時覆蓋圖與手動補採樣
- 決定：見 `docs/specs/umbrella_adaptive.md`。依實際取樣分佈找空洞、大缺口一輪補多個、陡處才加硬 k（漂移 ≲ 2σ、上限 5000）、
  中心預先往上坡偏移；以合併直方圖判定連續；樣本不足延長不複製；補不起來時回報並停止；不連續則不輸出 ΔG°。
  手動「從 a 到 b 補採樣」只重開該結合目標。
- 理由：Colab 版 PMF 斷點來自 window 被斜率推離中心，舊的中點同 k 補窗補不到。
- 取捨：平滑剖面上新規則比舊規則多用約 50% window（換較小誤差）；目標重疊 0.15 時陡牆補不連續，所以預設 0.2。
  「漂移 ≤ σ/2」的 k 規則被否決（把 k 頂到上限、過度採樣）；自動補窗的中心偏移上限用 1σ（3σ 在陡牆案例過衝）。
- 證據：`tests/test_adaptive_windows.py`、`tests/test_umbrella_manual.py`（合成剖面、精確偏壓取樣）；commit 3e7f941；真實 OpenMM 路徑待 CI。

### D-12　約束策略、凍結、口袋截斷：先設計、等審查再實作
- 決定：見 `docs/specs/restraints_freeze_truncation.md`（狀態：設計中）。使用者選擇「全部都做」（分組分階段約束＋智慧建議、凍結選項、口袋截斷＋資源估算）。
- 關鍵判斷：OpenMM（及使用 Verlet cutoff 的現代 GROMACS）凍結原子不會減少力的計算，凍結的價值是穩定性與教學隔離；
  真正省資源要靠減少原子數（截斷模型）。已向使用者說明並取得同意。
- 已做：引擎掛鉤 `StageSpec.restraint_groups`、`StageSpec.freeze`（預設值不進 protocol 雜湊，進行中的 run 可續跑）。

### D-11　幾何金屬鍵結模型：金屬–配位原子比照共價鍵處理非鍵作用
- 決定：1-2、1-3 排除，1-4 縮放（靜電 ÷1.2、LJ ÷2），加金屬–配位原子–鄰原子角。
- 理由：CI（12dcd80）中 3KS3 鋅位點 Zn–NE2 由 2.03 被推到 2.56 Å；只排除 1-2 時 Zn²⁺ 與咪唑環 CE1/CD2 及其氫的斥力仍在。
- 狀態：37bc6b1 的 Ubuntu 重測中 `test_bonded_zinc_ca2` 仍失敗，該輪被取消、沒有 traceback；待 3e7f941 的結果。**未解決。**

### D-10　金屬擬合參數：內建 Hessian 轉換＋MCPB.py 轉譯＋JSON，不依賴 AmberTools
- 決定：見 `docs/specs/metal_sites.md`。Hessian 以 Wilson B 矩陣 pseudo-inverse 轉內座標力常數；Seminario 只當交叉檢查。
- 理由：使用者授權「內建或轉譯，自己處理」；Windows 無 AmberTools。modified Seminario 在共用角高估約 30%（測試量到），故不採用。
- 證據：`tests/test_metal_params.py`；JSON 路徑在 Ubuntu 真跑通過（12dcd80）。

### D-9　閘門一鍵決定只給「程式真的會執行」的選項
- 決定：見 `docs/specs/gate_actions.md`。同時修正受體閘門 `human_choices` 會接受未實作選項的漏洞。
- 證據：f879764 Windows/macOS GUI 伺服器測試通過。

### D-8　3D 互作標示採純距離準則並明示近似
- 決定：見 `docs/specs/viewer_interactions.md`。氫鍵不檢查角度、表面為 vdW 球，畫面與報告寫明。

### D-7　論文對接重現移出必綠的重測，改為獨立非阻擋 CI 工作
- 理由：六配體同時對接與 7 胜肽對接在 4 核 runner 上要數小時，讓重測卡死；這兩個重現從未在 CI 跑完過（更正先前文件說法）。
- 做法：`paper-docking` job（exhaustiveness 8，JSON 標明為縮減搜尋）；加 faulthandler 與步驟逾時。

### D-6　第一次完整 Ubuntu 重測抓到的 bug 一律修在產品，不放寬測試
- altloc 被當重複原子名；`_md20` 戳記欄位讓結果檔讀不回；短 stage 記錄太少且「延長 0 ps」；padding 讀錯鍵名且套到不需要的系統；
  setup-vina 遇 GitHub API 限流。細節見 `docs/specs/ci_validation.md`。
