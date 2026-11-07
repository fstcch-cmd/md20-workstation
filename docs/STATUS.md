# MD20 單機教學版 — 狀態報告（最後更新 2026-11-07；本檔自 2026-11-01 起累積）

本檔誠實分成三級:**(A) 真實跑過並通過** /（B）**寫好、靠 CI 驗證** /（C）**已知限制與未完成**。
原則:寧可標「未驗證」，不誇大。每次 push 後，CI 會把各 OS 的測試結果貼到該 commit 的留言。

## 本 session（2026-11-07 晚，session_016gcJz8q8wadWxHb24EMCKt；主 session 指派 Sonnet 子代理開發、審查後整合）：D-111～D-123（屬 a20）
- **ac5fba5 CI 結果（真實引擎）**：(A) D-102 膜情境 B 在 Windows／macOS／Ubuntu 都通過（Windows 先前 12/36 NaN）；D-104 建膜即時 3D 階段 bilayer→declashed；D-105 工具箱與 D-106 共同基底真實 mdtraj 測試通過；D-107 讓 pure-python 六個與 heavy-metal 轉綠；paper-docking、installer 兩個綠。紅燈全是測試或無氫拓撲問題，已修：D-111（heavy 斷言位置）、D-112（頭基原子 256≠128）、D-121（無氫拓撲的蛋白氫鍵）。
- **(C) 膜 NaN 尚未完全解決**：28e87aa 的 Ubuntu 情境 B 在 D-102 之後仍 NaN；重讀診斷資料，水重疊每個建構都有、不是區分因子；判斷為「離子落在重疊的水上」並修（D-115，D-102 加更正）。**這是與資料一致的判斷，尚待膜診斷直接證實。**
- **(B) 新功能，容器測試通過、真實路徑交 CI**：D-113 PMF 評估納入 MBAR overlap matrix；D-114 Vina 單一釘選版 v1.2.7＋sha256（同班不再混版本）；D-116 SMD 路徑接觸釋放（F13）；D-117 micromamba 釘選 2.10.0-0＋sha256；D-118／D-123 約束策略智慧建議（只建議）＋從建模與對接紀錄接入特徵、採用時記錄；D-119 補窗近重複提案放棄並記理由（REVIEW #18 bug 部分）；D-120 跨候選可比性矩陣（F05）；D-122 自動行動成本與效益報告（F17）。
- D-103 決定維持「關 GUI 不中斷計算」（開發者決定，使用者可推翻）。容器 923 passed、49 skipped。
- (C) 待授權：REVIEW #18 門檻（min_effective_samples=100 讓補窗成本約 ×5–6）、A8、P1A、藍圖第 2–4 階段、F19；conda 環境鎖版未做。

## 本 session（2026-11-07，session_016gcJz7pQmKkZzkUxg6SqVs）：D-103 GUI 穩定性（屬 a20）
- **D-106 系統比較**：條件可比性檢查（未知即不可比）、所有系統放在同一組主成分軸、低谷代表幀、前後半一致性、殘基對應的 ΔRMSF。(A) 容器 766 passed；(B) 真實流程交 CI heavy workflow。
- **D-105 分析工具箱**：tICA、MSM（附資格，單一軌跡不報速率）、側鏈氫鍵網路、水合位點，進報告。(A) 容器 760 passed；(B) mdtraj 接線交 CI。
- **D-104 建膜即時 3D**：建模每一步（溶質定向／放置＋目標磷平面、加膜、去水碰撞）寫場景，GUI 3D 分頁自動跟著更新。(A) 容器 752 passed；(B) 真實建膜快照與瀏覽器自動重畫交 CI；(C) MD 平衡階段的即時軌跡未做。
- 計算改成獨立子程序（`md20/gui/worker.py`）；GUI 的狀態、進度列、即時曲線從 `_gui_job/` 檔案讀回；GUI 斷線或重開後接回同一個計算，不重複啟動。關 GUI 不再中斷計算（按「暫停」才停）。
- **(A)** 容器 743 passed、49 skipped（含真實子程序測試）。**(B)** NiceGUI 頁面與「關 GUI→重開→接回」交 CI gui-preview。**(C)** 筆電上關主控台視窗時子程序是否存活未實測；建膜即時 3D 未開始。
- 金鑰檢查（11/07）：工作樹與全部 git 歷史（含所有分支）沒有 token／私鑰；`owner_pub.pem` 是公鑰；兩個像 Google key 的字串是報告範本 PNG base64 裡的巧合。程式沒有呼叫付費 API。

## 本 session（2026-11-07，session_016gcJzAV8UjRW4ixPZLxddG）新增，已 push、未發行（屬 a20，不入 a19）
- **D-99/D-100**：SMD 水盒事先依規則決定＋通則檢查；**padding 意義更正、預設全部 2.0 nm**。
- **D-101**：傘狀採樣 SMD 力曲線預先規劃＋即時斷點提示＋覆蓋圖一定存在。
- **D-102**：膜 NaN 根因＝OpenMM 放出重疊水（建構缺陷、平台無關）；加「去水碰撞」閘門修復。
- 中期開發藍圖 Claude Doc（對標市面軟體）：artifact/X7GWyffsMwTL2r9fr3SX6B。
- **誠實狀態**：以上容器測試通過（純 Python／FakeBackend）；真實 OpenMM 路徑（heavy workflow、openmm-stack、膜測試）**交 HEAD `f61f305` 的 CI 確認**，本 session 結束時尚未全部跑完。
- **新需求（待開發）**：GUI 穩定性（UI 易斷線）、建膜即時 3D 顯示。

## 待發行：v0.1.0a19——**`e0a0f77` CI 全綠**（openmm-stack 三 OS 777–778 passed、skip 均為預期；heavy 三個、installer 兩個、pure-python 六個、paper-docking 綠）。推 tag 屬公開發行，需使用者執行。膜表面測試曾在 `5a3fa37` Windows 偶發 NaN 一次（`e0a0f77` 三 OS 通過），根因診斷進行中（DECISIONS 11/07）。

## 進行中（2026-11-07，session_016gcJzAV8UjRW4ixPZLxddG）：D-98 配體原子電荷＋A7 拒絕代碼＋DevCheck P0
- **(A)** 容器 697 passed、49 skipped（新增 24 項）。
- **(B)** 交 CI：RDKit 共振判定（`test_rdkit_acetate_and_neutral_molecule`）、3PTB 完整流程的新斷言（heavy workflow）；另可在筆電以 `MD20-DevCheck-P0.cmd` 於沙盒資料夾隔離驗證。
- **(C)** 胜肽配體原子電荷仍未記錄；docking 拒絕理由已四語（D-110）；pose 推薦 prose 仍照 D-55 以中文記錄＋展開翻譯。

## 整合規格 P0（D-95、D-96、D-97，2026-11-07，已 push、未發行）
已 push 到 main，HEAD **`ba4d7da`**。**未發行**（對外版本是 **a17**——a18 實際上從未發行，見 DECISIONS 11/07 紀錄）。這批是科學正確性修正，不是新 phase。
- **(A) 真實跑過並通過**：容器內 `pytest -o addopts="" -q` → **673 passed、48 skipped**。新增純 Python 測試：assessment 9、interactions/persistence 14、extended 接線 2、報告持續性 1、provenance 4、structure/multi-binding 多項。
- **(B) CI 驗證狀態（2026-11-07）**：
  - **D-95 已由 CI 確認**：openmm-stack（ubuntu）的「Install md20」步驟在 `2979908` **success**——釘選 `openmmforcefields==0.15.1` 後安裝成功（原本撤回版找不到的錯誤消失）。
  - **Report template、GUI preview 在 `2979908` 綠**（D-96 合成評估資料、D-94 3D 分頁正常）。
  - `2979908` 的 pure-python 六個 job 全紅＋openmm-stack 步驟 8 紅，原因是 `tests/test_interactions_report.py` 用了 `from tests.` 的 import（CI rootdir 無此 package），collection 失敗；**已於 `ba4d7da` 修正**（改 `from test_report_v2`，與 `test_report_subsystems` 同慣例），本地以 CI 方式（`pytest tests/<file>.py`）重驗通過。
  - **新 run `42330665732`（`ba4d7da`）進行中**：下一個 session 要確認 pure-python 六個轉綠、openmm-stack 三 OS 的真實 mdtraj 路徑（新 fingerprint／ligand_state／動態接觸／persistence／`run_binding` 寫入的 assessment）。查法見 HANDOFF §0。
- **(C) 已知限制／未完成**：A7（docking fallback reason code）、A8（PMF 參考態／漏斗約束）、A11（跨系統 PCA 共同基底）仍待做；配體原子形式電荷未寫入 build manifest（在那之前配體不判鹽橋，只標「帶電接近，配體電荷未知」）；F19 MM/GBSA pilot 未開始。詳見 `docs/specs/master_iteration_2026-11-07.md` §5。
- **需發行新版（a19）**：install.ps1/sh 已含 D-95 釘選，但對外的 a17 zip 仍是舊的（a18 從未發行）；學生新安裝要能成功需重新發行（待使用者授權）。

## v0.1.0a18（**未發行**：pyproject 已是 a18，但 release 流程沒有跑；更正見 DECISIONS 11/07。以下是 main 上 D-93/D-94 的內容）
- 拉離路徑判定修正（貼著的鄰居不再算擋路）、「只做 MD」真的停下結合自由能、閘門加「只算單獨結合」與「指定 anchor 殘基」（D-93）。**測試過**：純 Python（5 項新測試）；以筆電 hsieh2024 的 topology.pdb 重算路徑：原方向淨空。**沒測過**：筆電上 URI 的實際 SMD／PMF；「連線丟失」是否消失（reconnect_timeout 180 秒）。
- GUI「3D 檢視」分頁空白的修正（D-94，NiceGUI 3 清掉 iframe）。**測試過**：CI gui-preview e2e 點分頁並確認 iframe 內畫出 canvas（以該次 CI 為準）。報告內的 3D 一直正常（筆電報告實測）。
- CI：46fdbdb 與 d879f2b 各有 1 項 CPU 整合測試隨機失敗（Windows 膜胜肽 NaN；macOS 長時間溫度看門狗），各自在另一輪通過，見 DECISIONS 11/07 CI 紀錄。
- **D-94 的 commit `5561dd7` 第一輪 CI（run 42322469948）大量紅燈，但不是程式問題**：openmm-stack 三 OS／heavy／installer／paper-docking 全卡在安裝步驟 `pip install openmmforcefields`（CI 當下連不到 PyPI：「Could not find a version … from versions: none」），`md20` 沒裝成，之後 import 全部 `ModuleNotFoundError`；pure-python ubuntu 另因 runner 硬碟只剩 15.7 GB 卡在長時間模擬的磁碟檢查。**真正測到 D-94 的 gui-preview 工作是綠的。** 2026-11-07 09:34 已重跑失敗 job（rerun-failed-jobs），下一個 session 要確認重跑結果；若仍紅，先看是不是同一個 PyPI／磁碟 infra flake 再判斷。

## 目前對外版本：v0.1.0a17（2026-11-04 發行）
- 多配體拉離路徑被擋住時自動改道（D-92）。**測試過**：純 Python 幾何測試。**沒測過**：筆電 hsieh2024 URI 改道後的實際 SMD。

## v0.1.0a16（2026-11-04 發行，已被 a17 取代）
- 在 zip 裡直接執行安裝程式時，改為提示先解壓縮（D-91；發行流程在 Windows 驗證）。其餘同 a15。
- 發行紀錄：a14（01:44 UTC）、a15（02:17）、a16（02:43）三版的 Windows 與 macOS 安裝驗證都通過後才上架。
- CI（97d2f85，D-87 程式）：openmm-stack Linux、macOS 通過（各 16 項設計內跳過）；heavy workflow、pose-screen、論文對接、兩個安裝器通過；heavy metal 失敗，是已知的鋅鍵長臨界（His94 平均 2.355 Å，r0 2.03 Å，差 0.032 nm，門檻 0.03 nm；D-32、D-34 的未決問題，與本日修改無關）；Windows 仍在跑。之後幾個 commit 的 CI 在排隊時被較新的 commit 取代（GitHub 同一群組只保留一個待跑），以 46fdbdb 那一輪為準。
- GUI 瀏覽器點擊自我測試（7885017）13 項全部通過。

## v0.1.0a15（2026-11-04 發行，已被 a16 取代）
- 折線圖重新規劃（D-89）：分段軌跡的時間軸修正（舊專案按「重新整理報告」即可）、圖例在圖外、線名用配體名、顏色一致、多系列改小圖。**測試過**：繪圖規則測試（含圖例不重疊的量測）。**沒測過**：筆電舊專案重新整理後的實際圖。

## v0.1.0a14（2026-11-04 發行，已被 a15 取代）
- 結合自由能可指定配體（含多配體系統）、報告後加做配體或加做 SMD 次數並整合報告、首頁找回所有流程（D-87）。**測試過**：純 Python（目標選擇、保留已完成、資料夾、報告）。另：專案資料夾由使用者指定、可打開任何專案或流程資料夾（D-88）。**測試過**：CI 瀏覽器點擊自我驗證（gui-preview `e2e`，以該次 CI 結果為準）。**沒測過**：GPU 上實際加做 SMD；筆電上的資料夾視窗。

## v0.1.0a13（2026-11-03 發行，已被 a14 取代）
- 粗粒化 Martini 3 接成一鍵流程（D-86）：`setup-cg` 含力場檔、膜蛋白／膜表面胜肽／純膜／水中蛋白、可續跑模擬、分析與報告、專業模式選項。**測試過**：純 Python 流程測試；CI（7eef553）以真工具 `md20 setup-cg --yes` 安裝後建三個小系統（POPC 純膜、跨膜螺旋、膜表面胜肽）各跑數千步 CPU：**Linux 3/3 通過（5.6 分鐘）、macOS 3/3 通過**；Windows 在 8d6a651 那輪 3/3 通過（39、95、107 秒），7eef553 這輪發行時仍在跑。8d6a651 Linux 的膜表面胜肽曾卡住一次，7eef553 改成獨立步驟並釋放 Simulation 後通過（184 秒），原因未確定，持續觀察。**沒測過**：筆電 GPU 速度與長時間穩定性。

## v0.1.0a12（2026-11-03 發行，已被 a13 取代）
- 胜肽直接貼序列：自動辨識、10 個殘基以上預設摺疊、`Install-Folding.cmd` 與 GUI 一鍵安裝摺疊工具（D-85）。**測試過**：純 Python 單元測試。**沒測過**：筆電實際安裝與 GPU 摺疊、macOS。

## v0.1.0a11（2026-11-03 發行，已被 a12 取代）
- a10 加上 `setup-cg` 找不到 martinize2 的修正（D-84，待筆電確認）。

## v0.1.0a10（2026-11-03 發行，已被 a11 取代）
- a9 的內容，加上筆電驗證抓到的四個修正（D-83：OpenMM 8.2 建膜參數、只存溶質軌跡、setup-fold 不需 git、setup-cg 改用 PyPI）。摺疊的 GPU 實測待重跑。

## v0.1.0a9（2026-11-03 發行，已被 a10 取代）
- 新增（D-80–D-82）：一鍵摺疊、膜系統（膜蛋白、膜表面接觸、純膜）、長時間模擬規劃與粗粒化工具、對應的介面與報告。
- 驗證等級：**B 級**（寫好、純 Python 測試通過；OpenMM 整合測試在 CI；筆電關鍵項目進行中）。發行前沒有等完整 CI 與筆電結果（使用者要求盡快發行）。
- 筆電（11/03 15:48）：開發版安裝 10 分鐘通過、doctor 為 CUDA（RTX 4060 Laptop）；膜、長時間引擎測試與摺疊結果待補。

## v0.1.0a8（2026-11-03 發行）
- a7 的全部內容，加上 D-79：高通量篩選範例 Excel 改成只用 SMILES、可直接試跑。

## v0.1.0a7（2026-11-03 發行）
- a6 的全部內容，加上 D-78：多配體同時對接所有聯合姿勢都碰撞時，改選進入 MD 風險最低的姿勢並繼續（純 Python 測試全過；真實多配體建模路徑在 CI openmm-stack）。

## v0.1.0a6（2026-11-03 13:4x 發行）
- https://github.com/fstcch-cmd/md20-workstation/releases/tag/v0.1.0a6 ——程式與 a4 相同，修正 Windows 啟動檔：桌面捷徑（D-76）與很長的 PATH（D-77）。
- 發行前 verify-windows 真的執行桌面 `MD20-GUI.cmd`，PATH 加長到 10,104 字元，介面回 HTTP 200。
- v0.1.0a5（只含 D-76）的發行在最後「建立 Release」被 GitHub 拒絕（403 Resource not accessible by integration），沒有發出；a6 同一步驟成功，原因未明。

## v0.1.0a4（2026-11-03 12:5x 發行）
- https://github.com/fstcch-cmd/md20-workstation/releases/tag/v0.1.0a4 （Windows、macOS 安裝檔；發行前 verify-windows 與 verify-macos 實裝驗證通過）。
- 發行點 49e2eae：CI 15 個 job 中 14 個綠（含三 OS 中的 Ubuntu、macOS openmm-stack 與 heavy workflow）；**Windows openmm-stack 在發行時仍在跑**，
  使用者要求 13:00 前發行，所以沒有等它。**13:09 補記：Windows openmm-stack 也綠（490 passed、6 skipped），49e2eae 的 15 個 job 全綠。**
- gui-preview（0ec6ce2，介面程式最後一次修改）：四語截圖正常，計算中切換語系穩定性檢查 OK。
- 四種介面與報告語言（英文、繁中、日文、韓文，D-74）；介面、報告與學生文件改寫。純 Python 測試全過；介面四語截圖與「計算中切換語系」穩定性檢查在 CI `gui-preview`。
- 日韓文未經母語者校對。

## 目前版本：v0.1.0a3（2026-11-03 發行）
- 發行：https://github.com/fstcch-cmd/md20-workstation/releases/tag/v0.1.0a3 （`MD20-Windows-v0.1.0a3.zip`、`MD20-macOS-v0.1.0a3.zip`；發行前在乾淨 Windows 與 macOS runner 實裝驗證通過）。
- 發行的 main 包含 D-72（578c484）。**4bccdff（D-71）以前的程式 CI 15 個 job 全綠**；D-72（vina.exe HighQoS 標記與執行緒量測）的完整 CI 尚未確認，使用者 11/03 08:50 決定不等筆電驗證直接發行。
- 真機（A 級）：MSI Cyborg 14／RTX 4060 Laptop／Windows 11，CUDA 601–613 ns/day；classroom 3PTB 全流程 76.5 分鐘（a1）；teaching 3PTB 重跑完成（a2 以前）並以全範圍 WHAM 重分析（D-62）。
  GUI v2 的互動、教學一（六配體同時對接）完整跑完、macOS 真機**尚未**在實機確認。
- 已知限制：一維 COM PMF 對埋入口袋的配體高估 3 倍以上（3PTB teaching −21 kcal/mol 對實驗約 −6.4），只比較趨勢；鋅鍵結模型平均鍵長在 0.3 Å 臨界；
  vina.exe 在 Windows 混合核心上只用約 4 執行緒的原因判斷為 QoS（D-72），**未實測確認**。
- 以下為歷次紀錄（由新到舊為主，保留原文）。

CI 依據(`fstcch-cmd/md20-workstation`):
- **11/02 下午（session_016gcJz8q2F6515MWPncJEZu）：週二交付版的新功能，目前等級**（CI 結果出來後更新）：
  - **B 級（寫好、本地純 Python 測試全過、等 CI 真環境）**：D-47 斷鏈 ACE／NME 截斷（3PTB 真流程測試在 CI）、D-48 胜肽科學限制（CPP 不擋流程＋活性位可及性）、
    D-49 依個案建議參數與合理性檢查、D-50 HTS 手動上傳與「確認進入 MD」、D-51 GUI v2（四種模式、教學頁、雙語）、D-52 專案報告等級的雙語報告。
  - **GUI v2 已由 CI 截圖確認可渲染**（gui-preview，英文與繁中各 7 頁，HTTP 200）；按鈕實際互動、上傳、建立流程後的真跑，要在筆電上確認（開發容器無法安裝 NiceGUI）。
  - **C 級（未做）**：配體直接配位金屬的距離約束後備；舊閘門說明的英文翻譯；預設拉離速度（等筆電 teaching 重跑結果判斷）。
- **63d363b（第二個 session 最終版）openmm-stack**:**Windows OpenCL 124 passed、macOS 126 passed**,各只有 1 個失敗——`test_gui_pages_render`,原因是 NiceGUI 在子行程看到 pytest 環境變數就切到它自己的測試模式(非 GUI 本身問題),本 session 已修;Ubuntu `MD20_HEAVY=1` 重測結果見該 commit 留言。
- **f879764(第三個 session:閘門一鍵決定、3D 互作、金屬擬合參數、GUI server 測試修正)openmm-stack**:**Windows OpenCL 與 macOS 全綠**(含 `test_gui_pages_render`);Ubuntu `MD20_HEAVY=1` 重測卡在論文對接重現(已移出)。**ef32b48 的 Ubuntu 重測跑完:151 passed、4 failed,全是從未在 Ubuntu 跑完過的重測抓到的真 bug**,已修:(1)重複原子名閘門把 altloc A/B 同名原子算成重複(3KS3 被擋,兩個金屬整合測試因此失敗);(2)`DockingResult.load` 讀到戳記 `_md20` 欄位就當掉(全流程續跑時);(3)短 MD 篩 pose 的 2 ps stage 只記 4 筆 log → 無法驗收,且引擎用 +0 ps「延長」兩次白跑——現在短 stage 自動加密記錄、無法靠延長解決的直接 NEEDS_HUMAN;(4)workflow 讀 `pull_distance`(實際鍵名 `pull_distance_nm`),padding 一律被拉到 2.0 nm,且套到 apo 與篩選系統——全流程測試因此跑了 51 分鐘。
- **12dcd80 Ubuntu 重測:158 passed、1 failed**。全流程(3PTB,含 binding)、短 MD 篩 pose、金屬擬合參數(JSON)整合測試**在 Ubuntu 真跑通過**。唯一失敗:**幾何鍵結的鋅模型守不住配位**——最小化+2 ps MD 後 Zn–His94 NE2 由 2.03 Å 拉到 2.56 Å。原因:只排除了金屬–配位原子(1-2)非鍵作用,+2 的鋅仍與咪唑環上 CE1/CD2(1-3)及其氫有完整靜電斥力。已改成與一般共價鍵相同的處理:1-2、1-3 排除,1-4 依 Amber 縮放(靜電 ÷1.2、LJ ÷2),並加金屬–配位原子–鄰原子角項;待下一輪 CI 確認。Windows OpenCL 該輪因 `setup-vina` 遇 GitHub API 限流在測試前失敗(已修:token + 固定版本後備下載)。
- **第四個 session（審查 + HTS）**:純 Python 測試 **220 個本地全過**;以下皆 **待 CI**:(1)金屬鍵結模型補上經金屬的 1-3/1-4(37bc6b1 之後 CI 仍紅,見下);(2)引擎三個 watchdog/延長缺陷修正;(3)HTS 篩選整合測試;(4)缺口補建後主鏈連續性檢查。
  **更正先前聲稱**:「3D viewer 在 headless Chromium 實際繪圖」在 CI 三個 OS 都是 SKIPPED(playwright 不在環境裡),降為 B 級。
  37bc6b1 那輪 Ubuntu heavy 被下一個 push 取消前已印出 `test_bonded_zinc_ca2 FAILED`,所以「1-3 排除」並沒有修好鋅配位;本 session 加了 donor–donor 排除,待這輪確認。
  全部發現與處置見 `docs/archive/REVIEW_2026-11-01.md`。
- **c4b5de6（run 41309973844）heavy metal 全綠**:`test_metal_integration`（含 `test_bonded_zinc_ca2`）在 Ubuntu 真跑通過——鋅鍵結模型守住配位（經金屬 1-3/1-4 修正有效）。同輪 heavy workflow／pose-screen 因 `assemble.py` 漏 `import numpy` 失敗（D-24 已修，待下一輪）。
- **v0.1.0a2 發行（2026-11-02 13:2x）**：https://github.com/fstcch-cmd/md20-workstation/releases/tag/v0.1.0a2 ——含 D-36（CUDA 環境可解）、D-37（不刪舊版）、D-38（260 字元路徑）、D-39（doctor 顯示）；verify-windows 含 CUDA dry-run 通過才發行。**v0.1.0a1 在 NVIDIA 機器上裝不起來，請改用 a2。**
- **4bccdff（D-71，run 41501295929）main 15 個 job 全綠（2026-11-03 04:29 確認）＝ v0.1.0a3 發行候選**；筆電教學一對接（exhaustiveness 32）是否完成未知（筆電離線）。
- **c868014（run 41495051284）main 15 個 job 全綠（2026-11-03 01:51 起）**：三 OS openmm-stack、installer-windows、**installer-macos**、三個 heavy（含 metal、pose-screen）、paper-docking、6 平台 pure-python。v0.1.0a3 發行候選。夜間修正 D-62–D-71（PMF 截斷與持平閘門、MBAR 暖啟動、拉速 0.005、軟核接受標準、GUI 穩定性、Mac 安裝、資源用量、Windows 子程序、教學一對接強度）。
- **筆電 teaching 重跑與全範圍重分析（2026-11-02 22:00，本 session 直接讀筆電檔案）**：classroom 與 teaching 報告的 ΔPMF（80.3／80.6）**都是 PMF 在約 0.5 nm 被截斷的邊緣值**（a1／a2 的 MBAR 路徑；D-62）。同一批 window 樣本以 WHAM 重算全範圍：classroom 134、teaching **100 kJ/mol**（ΔG° −29.5／−21.2 kcal/mol，實驗約 −6.4）。已修：截斷改用 WHAM（D-62）、井深需末端持平否則不輸出 ΔG°（D-65）、預設拉速 0.005（D-63）。**一維 COM PMF 對埋入口袋的配體仍高估 3 倍以上**——只能比較配體間趨勢；方向／構形約束未做。圖：`docs/archive/runs/2026-11-02_laptop_3ptb/`。
- **第一次真 GPU 端到端（2026-11-02 13:06，使用者回報）**：MSI Cyborg 14／RTX 4060 Laptop，CUDA 601–613 ns/day；自測腳本全通過：安裝 2.6 min、doctor、drivers plan、demo、GUI（http 200）、**classroom 3PTB `pipeline run` rc=0（76.5 min，apo＋docked BEN 報告產出）**。報告：redocking 0.38 Å、配體留在口袋、補窗 13→40；**ΔPMF 80.3 kJ/mol 物理上偏大約 2–3 倍（實驗 ΔG ≈ −26 kJ/mol），ΔG° 被閘門擋下（正確）**，見 D-40；分析時 pymbar 的「Did not converge… max_delta = 0」為已收斂到機器精度的誤報（待改為只在真未收斂時提示）。
- **發行 v0.1.0a1（Windows 安裝程式，2026-11-02 08:26 台灣時間）**：https://github.com/fstcch-cmd/md20-workstation/releases/tag/v0.1.0a1 ——這個 ZIP 在乾淨 Windows runner 上以 PS 5.1 解壓、雙擊入口安裝（CPU）、刪除解壓資料夾後 doctor／demo／pipeline example 通過（release run 41365326632）。GPU 路徑未經 CI。
- **bb36a4b（run 41357112830）main 全部 job 綠——11/02 09:00 Windows 里程碑就緒**:Windows OpenCL **367 passed、5 skipped**（53 分鐘；skip 逐條核對，全是 MD20_HEAVY／MD20_PAPERS／playwright 設計內）、Ubuntu／macOS 367 passed;heavy workflow（含 binding）、pose-screen、metal、installer-windows、paper-docking、6 平台 pure-python 綠。保留風險:鋅鍵結模型平均鍵長偏移在 0.3 Å 臨界（上一輪 0.305 Å 紅、這輪綠），模型問題未修（D-32）;umbrella NaN 半步長重試路徑尚未被觸發驗證;真 GPU 路徑只能筆電驗證。
- **1634916（D-32）Windows OpenCL 真全綠**:366 passed、5 skipped（全是設計內的 skip），**對接與 HTS 整合測試在 Windows 真跑通過**——Windows 里程碑的 CI 條件此輪才真正達成。仍紅:macOS GBn2 最小化 NaN（偶發，測試改固定 CPU）、heavy workflow umbrella NaN（已加半步長重試）、heavy metal 鋅平均偏 0.31 Å（**模型問題，未修**）。
- **更正（D-31，另一 session 發現）**:99c8b64 的 Windows「351 passed」裡，`test_docking_integration`、`test_screen_integration` 因 meeko 缺 gemmi **整檔 SKIPPED**（Windows 10 skipped vs 其他 8），所以**Windows 上的對接與 HTS 並未真跑過**，下面「Windows 里程碑達成」的說法不成立，待 1634916 那輪確認。我當時只看了 passed/failed 數，沒有逐條比對 skip 原因——CLAUDE.md 已要求看 skip 數，這是我的疏失。
- **99c8b64（run 41329655849）main 全綠——11/02 09:00 Windows 里程碑的 CI 條件達成**:openmm-stack Windows OpenCL 351 passed（67 分鐘）、Ubuntu 355 passed（49 分鐘）、macOS 355 passed（52 分鐘）;heavy metal（**鋅鍵結模型以平均幾何判定通過**）、heavy workflow、heavy pose-screen、installer-windows、paper-docking、6 平台 pure-python 全綠。剩餘風險:Windows 最慢兩項 NaCl PMF 2233 s、GBn2 3PTB 1167 s——後者縮到 20 步仍 19 分鐘，耗時不在 MD 步數（待查：GB 建立／平台探測／逐步 chunk 封存），上限仍有 23 分鐘餘裕。真機 GPU（CUDA/OpenCL）路徑只能明早筆電驗證。
- **81b72d9（run 41326677606）openmm-stack 三 OS 全綠**:**Windows OpenCL 351 passed**（67 分鐘）、Ubuntu 355 passed（55 分鐘）、macOS 355 passed（67 分鐘）;heavy workflow（3PTB 全流程含 binding，**D-23 新約束排程**）、heavy pose-screen、installer-windows、paper-docking 綠。因此升為 A 級（真跑過）:配體質子化（真 RDKit）、連接圖 pose 對應、分組約束（Reference 實算）、GBn2 管線、HTS 純路徑、PBC 歸零於全流程。唯一紅:heavy metal 單幀判定的鋅測試（測試問題，D-29 已改平均判定，待 99c8b64）。跳過項:MD20_HEAVY 專屬（由 heavy job 跑）、論文對接（由 paper-docking 跑）、playwright 繪圖（環境沒有，仍是 B 級）。
- **f140a49 openmm-stack（D-28）**:Ubuntu／macOS **342 passed、1 failed**（49／68 分鐘，不再超時）。真 RDKit 下質子化、HTS、GBn2 管線、**分組約束 Reference 實算**通過;heavy pose-screen（新約束排程）、metal、paper-docking 綠。剩配體連接圖對應（已修）與全流程測試鍵名（已修），待下一輪;Windows 結果待出。
- **c4b5de6 openmm-stack（D-25）**:Ubuntu 16 failed／239 passed;Windows／macOS 撞 90 分鐘上限。真 bug:**配體質子化把苯胺／醯胺／苯甲脒 NH2 也質子化**（SMARTS 錯，已修）;HTS 純路徑測試在有 RDKit 的環境失敗（測試問題，已修）;**GBn2 在 CPU 上極慢**（3PTB 65 分鐘），「GBn2 較快」降為「僅 GPU 成立」。`test_restraint_groups_openmm`、質子化與配體對應的真 RDKit 驗證待下一輪。
- 測試函式:約 220 個(pure-python 部分本地全過)。

---

## A. 真實執行並通過

### A1. 無 OpenMM 也能跑(pure-python;CI 6 平台 + 本地)
| 模組 | 測試檔 | 重點 |
|---|---|---|
| chunk 引擎 | test_engine_fake | 分段封存/續跑、損壞 chunk 丟棄、watchdog、GPU context 重建、裝置反覆出錯→NEEDS_HUMAN |
| build 閘門 | test_build_gates | 壞 PDB 分類、loop、serial 溢位、口袋質子化審查(PROPKA) |
| docking 推薦 | test_docking_pure | 保守推薦、無合格候選→不推薦、口袋體積、同號電荷、redocking 自檢 |
| **短 MD 篩 pose(WP5)** | test_pose_screen | 候選挑選(推薦 + 每個其他 cluster)、穩定判定(後段 RMSD、接觸保留)、三態決策、暫停續跑快取、人工選擇不被覆寫 |
| **多配體結合(WP9)** | test_multi_binding | 拉離路徑閘門、ΔΔ 比較(ΔΔG° 只在全部有 ΔG° 時;< 2σ 不可區分)、共存效應、docked_multi 每個配體各自拉離、**bootstrap σ**、**replica 彙總與 research tier 以實際完成數判定** |
| **金屬** | test_metal | 配位位點辨識、bonded 計畫(鍵/角/CYM/HID/HIE)、擋關情境(< 3 配位、配體配位、His 雙氮)、policy 優先序、二硫鍵不被誤判為 CYM |
| **金屬擬合參數** | test_metal_params | QM Hessian(Gaussian fchk / ORCA hess)→ 內座標轉換擬合鍵/角力常數(對已知諧和模型**完全還原**,含共用角);cluster 與蛋白位點以元素+最佳置換疊合對應;MCPB.py frcmod/mol2/pdb 轉譯(鍵角查表、RESP 電荷、原子名一致性);JSON 匯入;檢查閘門(r0 與晶體差、力常數範圍、電荷整數與力場一致);QM 小模型輸入產生(Cα 封端、電荷/多重度、開殼層擋關) |
| **GUI 檢視(WP13)** | test_gui_views、test_gui_logic | 閘門卡片、時間軸、即時曲線、3D 場景資料;pose 表顯示短 MD 結果。(headless Chromium 繪圖測試在 CI 恆 SKIPPED,見 B) |
| **HTS 篩選** | test_screen_library、test_screen_workflow | 化合物庫解析(別名、缺識別欄、重名)、假網路下載(重試/限速/快取/失敗記錄/名稱查詢預設關)、批次對接續跑與失敗隔離、排名/LE/誤差內標記、圖檔、篩選閘門(部分失敗、未選擇)、GUI 勾選寫回與失效、庫檔改變重篩 |
| **重跑正確性** | test_workflow_rerun | CLI 重跑沿用人工決定、config.json 相同不重寫、metal_params null、舊 case 的 MD 不沿用、RCSB 下載驗證、PDB ID 驗證 |
| **引擎(修正後)** | test_engine_fake | dt 減半仍跑滿模擬時間、retry 以 ramp 目標溫度重生、延長不重收緊約束 |
| **閘門一鍵決定** | test_gate_actions | 選項→設定修補(structure_override、metal_policy、human_choices、box、skip_redock、CPP、peptide_policy);需理由的選項必填;寫回 config.json、記 human 決策、自該步驟起失效重跑;**沒實作的選項不給按鈕、閘門維持擋關**(受體長 loop/未知殘基等) |
| **傘狀採樣智慧補窗** | test_adaptive_windows、test_umbrella_manual | 合成自由能剖面＋精確偏壓取樣:陡牆案例舊規則留斷點、新規則補成連續且 PMF 誤差較小;每 window 各自 k 的 WHAM/MBAR;極端能障明確回報補不起來;覆蓋圖資料、手動區間補採樣只重開單一目標(真實 OpenMM 路徑待 CI) |
| **3D 互作標示** | test_gui_views | 逐幀幾何互作(氫鍵候選 N/O ≤3.5 Å 未檢查角度、疏水 C–C ≤4.0 Å、配體–金屬 ≤2.8 Å)+ 殘基佔有率表;vdW 球表面近似 |
| 工作流程閘門 | test_workflow_gates | 共晶盒必做 redocking、盲對接需同意、結合計算加大 padding、**binding 讀取組裝後原子索引(L01 迴歸)** |
| 胜肽/CPP、結構可信度、續跑/鎖、資源模式、PMF/採樣、專案/佇列/報告/doctor/stamp | 各檔 | 同前版 |

### A2. 真實 OpenMM + Vina(CI openmm-stack)
| 測試檔 | 內容 | 狀態 |
|---|---|---|
| test_openmm_integration | 平台選擇、HMR、benchmark、doctor | 三平台綠(a72ba6b:mac/win) |
| test_real_case_integration | 3PTB 建模 + 短 MD;胜肽 | 同上 |
| test_docking_integration | 苯甲脒 redocking RMSD<2Å;多配體 | 同上 |
| test_binding_integration | NaCl PMF;水盒過小擋關;**拉離路徑被擋(WP9)** | **f879764:Windows OpenCL / macOS 真跑通過** |
| test_workflow_integration | 3PTB 全流程(含 binding);**短 MD 篩 pose(WP5)** | Ubuntu 重測,見 B |
| test_binding_integration / test_real_case / test_docking / test_openmm | NaCl PMF、拉離路徑閘門(WP9)、3PTB 建模與胜肽、redocking、平台/HMR/doctor | **63d363b:Windows OpenCL 與 macOS 真跑通過** |
| test_metal_integration | **CA II(3KS3)Zn–His3 鍵結模型**:建模、互變異構體、力項、最小化+MD 後鍵長維持;**JSON 擬合參數套用與 r0 偏差擋關**;QM 小模型輸入產生 | Ubuntu 重測,見 B |
| test_gui_server | **啟動 `md20 gui` 並請求每個頁面與 /viewer**(含閘門一鍵按鈕) | **f879764:Windows OpenCL / macOS 真跑通過** |

### A3. 使用者實機(先前回報)
- Windows 10 + GTX 1060 → OpenCL,約 200 ns/day。
- HCC Lab 戳記端到端驗證:私鑰可解開 demo 輸出的加密溯源。

---

## B. 寫好、靠 CI 驗證(開發容器裝不了 OpenMM/NiceGUI,也連不到 PyPI/npm/RCSB)
- **3D viewer headless 繪圖**(`test_viewer_renders_in_headless_browser`):需要 playwright,CI 環境沒有 → 從未執行過;只有純資料層測試是 A 級。
- **約束策略（D-23）**：分組約束（主鏈／側鏈／配體）、主要釋放移到 NPT、`md.restraints` standard/gentle/hold_backbone、受約束 RMSD 標註。純 Python 排程測試本地通過；`test_restraint_groups_openmm`（Reference 平台實算各組能量、binding 釋放側鏈）與 3PTB 全流程在新排程下的驗收待 openmm-stack／heavy。
- **HTS 真下載＋真 Vina**(`test_screen_integration.py`,3PTB + PubChem/RCSB):待 openmm-stack。
- **金屬 1-3/1-4 經金屬排除**是否讓 3KS3 的 Zn–His 守住:待 Ubuntu heavy(現在 main 不再被取消)。
- **受體缺口**:無 SEQRES 時擋關、補建後 CA–CA 檢查,真實 PDBFixer 路徑待 CI。
- 第二個 session 加入的真實路徑測試(上表粗體)以最新 commit 的 CI 留言為準;若某項紅,留言含失敗 log,會在下一個 commit 修正並更新本檔。
- **兩篇論文的對接重現從未在 CI 跑完過**(更正先前說法):六配體同時對接(28×34×26 Å 盒)與 7 胜肽對接(36×51×45 Å 盒、exhaustiveness 32)在 4 核 runner 上要數小時,之前每輪都被取消或在更早處失敗。已移到獨立、不阻擋的 CI 工作 `paper-docking`(exhaustiveness 8,JSON 標明為縮減搜尋)。PDB 判定(1VKF→1VKX)、殘基存在性、結構閘門這幾項**輕量**驗證則每輪都有跑、有 JSON。

---

## C. 已知限制與未完成(誠實交代)

### C1. 論文驗證案例(教學背景用)
- **hsieh2024**(NF-κB RELA,六配體同時對接):論文標 PDB 1VKF,但 1VKF 是 *Thermotoga* 蛋白;系統判定正解為 **1VKX**。
- **hsieh2025**(Keap1-BTB 4CXT,胜肽 GGGGGKP):胞內標靶但淨電荷 +1,**CPP 科學限制提醒並給替代設計**(D-48 起不擋流程);「covalent bonding」實為凡得瓦接觸;盒子比整個 domain 還大(等同盲對接)。
目的是示範把關流程,不是逐位重現論文數字。

**論文對接重現(CI `paper-docking`,ef32b48,exhaustiveness 8 縮減搜尋)——第一次跑完**:
- **hsieh2025**(4CXT,GGGGGKP,91 s):第 1 名 −5.91 kcal/mol(論文 −5.22);第 1 名 pose 與論文報告的接觸殘基 recall **100%**,第 2–5 名 0–100%。
- **hsieh2024**(1VKX,六配體同時對接,38 分):聯合分數 −11.7(論文 −13.86),但六個配體與論文殘基的 recall **全為 0**——落點在論文口袋之外;系統**拒絕推薦任何 pose**:口袋可用體積約 107 Å³、六配體總體積約 1386 Å³,建議改 independent 對接。這正是要教的:分數接近不代表結合模式對,而同時塞六個配體進一個口袋在幾何上就不成立。
- **hsieh2024 不可重現的原因已確定(37bc6b1 盒子幾何檢查)**:論文盒子尺寸若照字面 28.5×34.5×26.25 Å,框不到任何報告殘基(0/11);
  若是把 AutoDockTools 的**格點數 76×92×70 直接當 Vina 的 Å 填**,盒子 76×92×70 Å 會框到全部 9 個存在的報告殘基。盒子中心是 1VKX 的有效座標
  (距原子 0.48 Å),在 1VKF 中則落在蛋白外 39.6 Å——先前「中心來自其他座標系」的推論錯誤,已更正。

### C0. 審查發現但本 session 未修(細節見 `docs/archive/REVIEW_2026-11-01.md` §2)
- 對接配體直接配位金屬不會被擋(金屬 policy 在配體加入前執行);`map_pose_onto_reference` 的 order 後備可能錯配;
  `sampling/runner.py` 未被使用但有錯(勿用);自適應補窗端點碰撞「假新增」與 `min_effective_samples` 門檻;
  Vina/micromamba 下載無 pin、無 sha256,環境未鎖定;戳記第三層是加密不是簽章,證明不了作者。
- **HTS 篩選**:分數只用最佳 pose 的 Vina 分數(縮減搜尋),去鹽取最大片段可能誤刪季銨鹽/金屬配合物;名稱查 PubChem 預設關閉。

### C2. 刻意簡化或未做
- **短 MD 篩 pose**只排除會散開的 pose,不以短 MD 排名結合強度;非 research tier 預設關閉。
- **金屬鍵結模型**預設是晶體幾何的諧和鍵/角(電荷沿用力場)。**擬合參數**可由三種來源匯入(`metal_params`):QM Hessian(內建轉換,電荷仍沿用力場)、MCPB.py 輸出(含 RESP 電荷;二面角與金屬 LJ 不轉譯)、JSON。QM 計算本身(ORCA/Gaussian)在程式外執行;程式負責產生小模型輸入與檢查結果。配體直接配位金屬、少於 3 個蛋白配位原子一律 NEEDS_HUMAN。配位水被移除(位置開放,報告標註)。開殼層金屬的 QM 電荷/自旋不猜,需使用者指定。
- **多配體 PMF**:共存效應是「單獨 vs 共同口袋」的趨勢比較,不是封閉的熱力學循環;拉離路徑被另一配體擋住時不計算。
- **誤差**:σ 為 bootstrap(每個重抽樣 PMF 重算 ΔPMF/ΔG°)與 replica 標準誤取大者;不含力場誤差。
- **ΔG°**:一維 COM 距離 PMF + 徑向積分,未做方向/構形限制校正(漏斗約束設計中,`docs/specs/binding_funnel_restraints.md`);classroom 不輸出;PMF 未涵蓋取樣範圍或末端未持平不輸出(D-62、D-65);research 需 ≥3 個**實際完成**的 replica + 半段收斂。
- **3D viewer** 是自寫的 Canvas 2D(離線、無 WebGL):球棍 + Cα 骨架 + 口袋殘基,可旋轉/縮放/播放軌跡;互作為**純距離準則**(氫鍵不檢查角度,不是能量分解);「表面」是口袋原子 vdW 球近似,**不是**溶劑可及表面;沒有卡通。
- **GUI 閘門一鍵決定**只涵蓋程式真的會執行的選項;換結構、改序列、MCPB.py/QM 參數、補長 loop 等仍需在程式外處理(卡片列為「需要在程式外處理」)。
- **受體閘門的 human_choices**(修正):先前任何選擇都會讓閘門轉為已處理,但長 loop/未知殘基/重複原子名的選項並未實作(例如長 loop 仍被丟棄→主鏈斷裂);現在只接受 hetero groups 的移除/保留,其他選擇維持 NEEDS_HUMAN 並說明原因。「保留為參考配體」改為**不**留在 MD 受體中。
- **PROPKA** 只審查/提示,不自動改質子化。

### C3. 平台
- AMD GPU 走 OpenCL;Apple Silicon 走 CPU/OpenCL。
- 資源模式(省資源／平衡／全速)同時決定 MD 的 CPU 執行緒／GPU 工作比例、Vina 的 `--cpu`、Windows 子程序優先權與 QoS(D-68、D-70、D-72)。
- Windows:關閉 MD20 視窗會一併結束 vina.exe(Job Object,D-69)。
- Vina:Windows 無 python bindings 時用官方執行檔(`md20 setup-vina`)。

---

**一句話**:docking→MD→結合自由能的核心與把關閘門、短 MD 篩 pose、多配體各自 PMF(含誤差與 replica)、金屬 policy/幾何鍵結模型、GUI 閘門/時間軸/即時曲線/離線 3D 都已實作並有測試;真實 OpenMM 路徑的最終綠燈以 CI 留言為準。
