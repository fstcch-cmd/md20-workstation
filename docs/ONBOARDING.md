# MD20 接手開發說明（給第二位開發者）

> 最後更新：2026-11-12（D-187）。擁有者：HCC Lab, NKUST。
> 這份文件是第二位開發者在自己的電腦上開始開發前要讀的唯一入口。讀完就知道：專案現在分成哪幾塊、流程是什麼、有哪些功能、哪些待做、哪些等驗收、哪些要在本機驗證，以及所有必須遵守的規則。
> 規則的原始出處是 `CLAUDE.md`。兩邊有出入時以 `CLAUDE.md` 為準，並請回報讓這份文件更正。

## 目錄
1. 這個專案是什麼
2. 現有的開發分成哪幾塊
3. 第一天：在本機把環境建起來
4. 軟體的流程
5. 功能清單與每項的真實狀態
6. 待做
7. 等驗收（要擁有者看過或決定）
8. 要在本機驗證
9. 所有規則
10. 每次開發的固定步驟
11. 文件地圖

---

## 1. 這個專案是什麼
MD20 是單機版的分子模擬教學工作站：分子對接、建模、OpenMM 分子動力學、SMD 與傘狀採樣算 PMF、自動產生報告。對象是博士生，在自己的筆電上跑，Windows 優先，也支援 macOS 與 Linux。介面是 NiceGUI（本機瀏覽器），同時有命令列。介面、報告、學生說明有四種語言：繁體中文、英文、日文、韓文。

- 產品 repo：`fstcch-cmd/md20-workstation`（公開，只為了用 GitHub Actions；保留所有權利，見 `LICENSE`）。
- 簽章簽發端：`fstcch-cmd/md-digital-signature`（私人）。產品 repo 只有驗證端。需要存取請向擁有者申請。
- 對外最新發行：v0.1.0a22（prerelease）。`main` 是開發中的 `0.1.0a23.dev0`。
- 決策紀錄已編到 D-187。

## 2. 現有的開發分成哪幾塊
目前有四條線。認領工作時要寫明屬於哪一條，以及屬於〔完整版〕〔Lite〕還是〔共用〕。

### 2.1 兩個版本架構（D-186，最重要）
專案出貨兩個版本，**共用同一份源碼和同一個 `main` 分支**。不為 Lite 另開長期分支。

| | 完整版 | Lite（導流版） |
|---|---|---|
| 給誰 | 實驗室內、已授權的使用者 | 實驗室以外的人，免費，需擁有者簽發的授權檔 |
| 定位 | 功能完整、規模不限 | 流程完整但規模受限，讓人用過後想升級完整版 |
| 怎麼產生 | 源碼樹本身 | `tools/build_lite.py` 打包：移除完整版模組、換成空殼、寫入版本標記，再編譯核心 |
| 專案格式 | 相同 | 相同。Lite 專案用完整版直接打開接著跑 |

Lite 的上限（`md20/edition.py`，未經實機校準）：每個系統 3 萬原子、蛋白 400 殘基、同一流程 2 個配體、一次篩選 10 個化合物、正式模擬 10 ns、每個系統 1 次重複、傘狀採樣 12 窗口且不自動補窗。

工作分三類：
1. **共用的基本路線**（對接、分子動力學、快速 PMF、基本分析、報告、介面骨架）。兩個版本都會跑到。改完要確認 Lite 樹仍可用（見第 10 節）。
2. **只有完整版才有的功能**（膜系統、胜肽摺疊、粗粒化、長時間模擬、多重複、完整結合自由能、大型篩選、進階分析、自動補跑，以及之後的進階功能）。新功能要在 `md20/edition.py` 的 `PRO_FEATURES` 登錄，並在 `check_config` 加入口判斷。新模組獨立成檔、由基本路線延遲 import，才能從 Lite 乾淨移除。
3. **Lite 專屬**（上限數字、碰到上限的閘門與文字、報告附錄 D、介面的版本頁、打包工具）。只改 `md20/edition.py`、`md20/edition_preview.py`、`md20/report/edition_section.py`、`md20/gui/edition_ui.py`、`tools/build_lite.py` 與它們的測試。

規格：`docs/specs/lite_edition.md`。決策：D-181、D-182、D-186。

### 2.2 核心科學流程
對接、建模、分子動力學、增強取樣、分析、報告。這是產品本體，已發行到 a22。細項狀態見第 5 節。

### 2.3 授權與發行保護
四層設計（`docs/specs/licensing.md`）：專有條款、簽章授權驗證與機器碼、等級與功能與席次與撤銷、發行版核心編譯。前三層已實作。核心編譯（`tools/build_protected.py`）是選用、預設關閉，從未在發行流程實跑。

### 2.4 LLM 編排
讓 LLM 當常駐的生資助手，負責編排、診斷、報告敘述，疊在確定性引擎之上。
- L0 介面定義層（D-178）與 L1 的 MCP 轉接頭 `md20 mcp`（D-184）已實作，只暴露三個唯讀或只寫提議檔的工具。
- **L2 以後還沒做，而且規格 `docs/specs/llm_orchestration.md` 是草案：擁有者與其他模型審查、收到回饋之前不得實作。**

## 3. 第一天：在本機把環境建起來
```bash
git clone https://github.com/fstcch-cmd/md20-workstation.git
cd md20-workstation
```
Windows（PowerShell）：
```powershell
powershell -ExecutionPolicy Bypass -File installer\install.ps1     # 有 NVIDIA 顯示卡加 -Gpu cuda，否則 -Gpu opencl
```
macOS 或 Linux：
```bash
bash installer/install.sh
```
安裝器內含 micromamba，會建立 `md20` 環境、安裝套件、下載 Vina。之後：
```bash
pytest                              # 沒有 OpenMM 時只跑純 Python 測試，整合測試自動跳過
python -m md20 doctor               # 硬體與 OpenMM 平台檢查
python -m md20 edition              # 目前版本與 Lite 上限對照
python -m md20.cli demo --dir <暫存資料夾>
```
然後依序讀：`CLAUDE.md`、`docs/STATUS.md` 開頭、`docs/WORKBOARD.md`、`docs/DECISIONS.md` 最上面十條、`docs/CAPABILITIES.md`。

授權：MD20 執行計算需要有效的授權檔。請向擁有者索取開發用授權檔。**不要**用任何方式繞過驗證（見第 9.6 節）。

## 4. 軟體的流程
使用者看到的一條路線（`md20/workflow.py` 協調，每一步都能中斷後續跑）：

1. **環境檢查**（`md20 doctor`）：偵測顯示卡與驅動，實際建立 OpenMM Context 選平台，跑 benchmark 估時間。
2. **受體準備**：從原始結構修復缺原子、決定質子化、辨識金屬位點並依 `metal_policy` 處理。
3. **配體準備**：小分子參數化（OpenFF 為主）；胜肽走蛋白力場；胜肽可由序列摺疊（完整版）。
4. **對接**（AutoDock Vina）：單配體、多配體獨立、多配體同時。大量化合物走高通量篩選：上傳表格、取得 3D、快速對接、排名、使用者挑選。
5. **選 pose**：可用短分子動力學篩穩定性。這裡會停下來等人確認要不要進分子動力學。
6. **建模**：組裝受體與配體、溶劑化（水盒只包住蛋白，不浪費）、加離子；膜系統與粗粒化（完整版）。三態閘門檢查碰撞、電荷、原子數。
7. **分子動力學**：最小化、NVT、NPT、正式模擬。分段存檔、續跑、發散時自動回滾並減半時間步。
8. **分析**：RMSD、RMSF、迴轉半徑、氫鍵、接觸與互作持續性；多重複彙總；進階工具箱（完整版）。
9. **結合自由能**：SMD 拉離、傘狀採樣、WHAM 與 MBAR、bootstrap、評估物件判定能不能下結論、能不能排名。
10. **報告**：HTML，含圖、圖說、方法段落、決策日誌、證據覆蓋。Lite 多一個附錄 D。

貫穿全流程的三個機制：
- **三態閘門**：通過、已自動修正（附差異）、需要人決定（附選項）。
- **決策日誌**：每個自動決定都寫下理由。
- **評估與資格**（D-96）：執行完成、科學評估、比較資格三件事分開。資料不足就標為描述性，不排名。

設定檔欄位與人工決定點的完整說明在 `docs/WORKFLOW.md`。

## 5. 功能清單與每項的真實狀態
權威來源是 `docs/CAPABILITIES.md`（由 `docs/capabilities.json` 產生，不可手改）。下表是 2026-11-12 的摘要。

欄位意義（**五種狀態彼此獨立，不可互相推論**）：
- 合成測試：純 Python 或假引擎測試通過。只證明邏輯。
- 真實引擎：在 CI 用真的 OpenMM、Vina、RDKit 跑過。
- 最近結果：`pass` 通過；`stale` 證據之後程式改過、現況沒有結果；`fail` 失敗；`unverified` 沒有結果。
- **目前沒有任何功能通過對外部實驗或文獻的科學 benchmark。**

| 功能 | 已實作 | 合成測試 | 真實引擎 | 最近結果 |
|---|---|---|---|---|
| 分子對接（Vina，獨立與同時） | 是 | 是 | 是 | pass |
| 高通量篩選 | 是 | 是 | 是 | pass |
| 短分子動力學篩 pose | 是 | 是 | 是 | pass |
| 受體與配體建模 | 是 | 是 | 是 | stale |
| 多配體同時進分子動力學 | 是 | 是 | 部分 | pass |
| 金屬位點辨識與 policy | 是 | 是 | 否 | stale |
| 鋅的鍵結模型 | 是 | 是 | **失敗** | **fail** |
| 金屬擬合參數匯入 | 是 | 是 | 部分 | partial |
| 膜系統建模 | 是 | 是 | 部分 | stale |
| 膜專用分析 | 是 | 是 | 否 | pass |
| OpenMM 引擎（分段、續跑、watchdog） | 是 | 是 | 是 | stale |
| 粗粒化 Martini 3 | 是 | 是 | 是 | pass |
| 胜肽序列摺疊 | 是 | 是 | 否 | pass |
| 獨立重複與跨重複彙總 | 部分 | 是 | 否 | stale |
| SMD、傘狀採樣、PMF | 是 | 是 | 是 | pass |
| 傘狀採樣自動補窗 | 是 | 是 | 是 | stale |
| SMD 接觸釋放 | 是 | 是 | 否 | pass |
| PMF 結構化評估 | 是 | 是 | 否 | pass |
| 互作與持續性 | 是 | 是 | 部分 | pass |
| 共同基底系統比較 | 是 | 是 | 否 | pass |
| 分析工具箱（tICA、MSM、氫鍵網路、水合） | 是 | 是 | 否 | pass |
| HTML 報告 | 是 | 是 | 部分 | stale |
| 介面與獨立計算子程序 | 是 | 是 | 否 | stale |
| 授權第 1 層（條款） | 是 | 否 | 否 | unverified |
| 授權第 2、3 層（簽章驗證等） | 是 | 是 | 否 | stale |
| 授權第 4 層（發行版加密） | **否** | 否 | 否 | unverified |
| 安裝程式 | 是 | 是 | 部分 | stale |
| 分析快取 | 是 | 是 | 否 | unverified |
| 自主行動帳本 | 是 | 是 | 否 | unverified |
| 漏斗約束與標準態 ΔG° | 是 | 是 | 否 | unverified |
| 金屬配位水的 OH⁻ 選項 | 是 | 是 | 否 | unverified |
| **MD20 Lite**（D-181，尚未列入能力清單） | 是 | 是 | 否 | 未在真機執行 |
| **LLM 的 MCP 轉接頭**（D-184，尚未列入能力清單） | 是 | 是 | 否 | 未實機連線 |

CI 現況（2026-11-12 中午查詢）：`f14ecc4`（Lite 第一批）的 16 個工作中 10 個成功，包含新的 `lite-build` 與六個純 Python 工作；三個真實引擎工作、兩個 heavy 工作、論文對接 benchmark 當時仍在執行，結果未知。接手後第一件事請查這一輪和之後幾輪的結果。

## 6. 待做
依重要性。來源是 `docs/WORKBOARD.md`「待認領」與 `docs/STATUS.md`。動手前先在 WORKBOARD 認領。

**可以直接認領的**
| 項目 | 類別 | 出處 |
|---|---|---|
| 把 Lite 與 MCP 轉接頭登錄進能力清單 `docs/capabilities.json` | 共用 | D-181、D-184 |
| Lite：完整版打開被縮小過的專案時，提供「還原原設定」（原值已記在 `state["edition"]["clamped"]`） | 完整版 | D-181 問題 3 |
| Lite：教學案例一有六個配體，在 Lite 會直接撞上限；需要一個 Lite 可跑的示範案例 | Lite | D-181 問題 5 |
| Lite：報告「ΔG° 沒有輸出」在 classroom 等級不是 Lite 造成的，措辭要分開 | Lite | D-181 問題 6 |
| 建議邏輯在偵測不到顯示卡時建議隱式溶劑，與 D-25 實測相反 | 共用 | D-181 問題 4 |
| 金屬：力常數依元素與配位原子的表、配位水納入鍵結、配體配位金屬的距離約束後備 | 完整版 | WORKBOARD |
| 傘狀採樣：MBAR 重疊矩陣門檻、metadynamics 後備 | 完整版 | WORKBOARD |
| 約束策略建議、凍結、口袋截斷、資源估算 | 共用 | `restraints_freeze_truncation.md` |
| micromamba 與環境版本鎖定 | 共用 | REVIEW #19 |
| 戳記改為私鑰簽章（目前只有公鑰加密，不能證明來源） | 共用 | REVIEW #20 |
| heavy 工作變慢的深層原因（D-175 只繞過 timeout，沒查原因） | 共用 | STATUS |
| 受體長 loop 的自動處理；配體直接配位金屬的參數化 | 完整版 | CLAUDE.md |

**不可自行開始的**（要擁有者先決定，見第 7 節）
- LLM 編排 L2 以後。
- 把 `adaptive.py`、`longrun.py`、`extended.py` 拆成基本與完整版兩半（D-182 決定現階段不拆）。
- 鋅的科學模型修改。
- 路線圖後段：metadynamics 與 GaMD、REST2、相對與絕對結合自由能、QM/MM、MM/GBSA 試作。這些需要工作站與計算預算。

## 7. 等驗收（要擁有者看過或決定）
這些項目程式已經在 `main`，但還不算完成。擁有者一天大約只做五個決定，所以**提問一定要附可選的選項和你的建議**。

| 項目 | 需要擁有者做什麼 |
|---|---|
| Lite 的上限數字（3 萬原子等） | 看過實機結果後確認或調整 |
| Lite 授權：`features` 欄位帶 `lite` 這個字 | 確認簽發工具接受這個字（私人 repo） |
| Lite 的介面與報告附錄 D | 看過實際畫面與報告後驗收 |
| Lite 規格 `lite_edition.md` 第 11 節的三個問題 | 回答或交其他模型審查 |
| D-184 MCP 轉接頭的兩個審查點（`md.replicas` 豁免、提議檔位置） | 決定 |
| LLM 編排規格與使用指南 | 審查回饋 |
| 鋅的科學模型（D-150、D-152） | 選解法 |
| 發行版加密層（D-166） | 選方案 |
| `n_jobs` 要不要接到介面或設定（D-168） | 決定 |
| 任何公開發行（推 tag） | 授權。只有擁有者能決定發行 |
| 四種語言中的日文與韓文 | 找母語者校對 |

## 8. 要在本機驗證
開發容器和 CI 的 runner 都沒有顯示卡，容器也裝不了 OpenMM、RDKit、Vina。下列項目只有在真的電腦上才驗得了。**規則（D-180）：真實引擎驗證在本機做，跑完刪除產生的中繼檔與暫存，不把驗證產物留在工作區或 repo。結果寫進 DECISIONS。**

| 項目 | 怎麼驗 | 出處 |
|---|---|---|
| Lite 端到端 | `build_lite.py` 產生 Lite 樹，再跑 `build_protected.py`，安裝後用示範案例從對接跑到報告 | D-182 未決 |
| Lite 上限校準 | 在低配目標機（GTX 1060 4 GB 等級）量 3 萬原子、10 ns 實際要多久 | D-181 |
| Lite 介面 | 在真的瀏覽器看徽章、版本頁、上限卡片、語言切換；確認計算中切換不會重跑 | D-181 問題 2 |
| 核心編譯 | `compiled_core` 發行實跑；D-182 新加入的四個模組能否用 Cython 編譯 | D-166、D-182 |
| 隱式溶劑快速預覽 | 有顯示卡時開關出現、純 CPU 時不出現；平台偵測子程序在 Windows 不跳黑視窗 | D-181 |
| MCP 轉接頭 | 真的 Claude Desktop 加 Windows 主控台實機連線 | D-184 |
| 漏斗約束 ΔG° | 筆電上 3PTB 的驗收條件 | D-140 |
| 鋅 OH⁻ 路徑 | 真機上競爭羧基守不守得住 | D-165 |
| D-72 | 筆電實測 | STATUS |
| 介面穩定性 | 關掉介面視窗後計算是否繼續、重開能否接回 | D-103 |
| 介面一般行為 | 有 Playwright 時實際操作畫面 | CLAUDE.md |

已知可用的測試機：擁有者的 Windows 筆電（MSI，RTX 4060 Laptop，沙盒資料夾 `C:\Users\user\MD20-sandbox`）、舊筆電（GTX 1060 4 GB）、Ubuntu 工作站（RTX 3090）。第二位開發者請用自己的機器，並在 DECISIONS 註明硬體與驅動版本。

## 9. 所有規則
以下每一條都是必守。括號是出處。

### 9.1 兩個版本（D-181、D-186）
1. 版本的唯一來源是 `md20/edition.py`。其他地方不准寫死 `if lite` 或自己判斷版本，一律問 `edition.current()`、`edition.limits()`、`edition.check_*`。
2. 完整版的行為、輸出、protocol hash 不得因為 Lite 的改動而改變。Lite 的邏輯在完整版必須是空操作。
3. 沒有任何環境變數、設定或參數可以改版本。測試用 monkeypatch 模擬 Lite。
4. Lite 的結果在它的範圍內必須是對的。不得為了推升級而降低、隱藏或模糊結果。
5. 自動縮小只縮規模，不替使用者拿掉功能或刪配體。
6. `md20/_edition.json` 只存在於 Lite 安裝包，絕不提交進 repo。
7. 給外部的 Lite 必須是 `build_lite.py` 的產物並開核心編譯。

### 9.2 開發原則（CLAUDE.md「開發規則」）
8. 不新增 phase 或 step，只強化既有邏輯。
9. 三態閘門：通過、已自動修正、需要人決定。每個自動決定寫 `DecisionLog`，`why` 用中文。
10. **寧可擋也不要猜。** 條件不足就停下來，給選項。
11. MD20 是通用工作站，不綁定任何一個蛋白或配體。
12. 計算一旦開始，不得因為關視窗、切語言、換頁、改設定而從頭重跑（D-103）。
13. 新增閘門的決定鍵要加進 `workflow.DECISION_KEYS`，否則重跑會遺失使用者的決定。
14. 水盒不可過大，只包住蛋白。

### 9.3 誠實（CLAUDE.md、D-136）
15. `docs/STATUS.md` 分清楚三級：真的執行過、合成或假引擎測試、沒驗證。不可混寫。
16. 能力清單的五種狀態彼此獨立，不可由一個推另一個。合成測試通過不等於真實引擎測過。
17. 被跳過的測試不算通過。看 CI 要看跳過數。
18. 沒跑過的東西不可說成可用。判斷錯了，在原決策條目下方加「更正」並保留原文，不刪歷史。

### 9.4 文件與決策（2026-11-01 起必守）
19. **任何修改**都要把結論、理由、取捨、被否決的做法、證據寫成 Markdown，**與程式碼同一個 commit**。
    - 決策：`docs/DECISIONS.md`，新條目加在最上面，編號接續（下一個是 D-188）。推送前先 `git pull`，撞號就改自己的。
    - 子系統規格：`docs/specs/<主題>.md`，並在 `docs/specs/README.md` 登記。
20. 改動能力或 CI 工作時，同步 `docs/capabilities.json`，再跑 `python tools/capability_manifest.py --write` 與 `--check`。`docs/CAPABILITIES.md` 不可手改。
21. 擁有者會用其他模型審查 `docs/specs/`。收到回饋時，在該規格檔記錄採納或不採納與理由。
22. 與擁有者的重要討論寫成紀錄放 `docs/archive/discussions/`。

### 9.5 協作（D-180、WORKBOARD）
23. 開工前 `git pull`，讀 `docs/WORKBOARD.md`，**認領後才動手**，寫明〔完整版〕〔Lite〕或〔共用〕。完成後更新看板。不動別人認領中的主題。
24. **推上 GitHub 每週一次。** 平時在本機累積、整合、驗證。例外：`main` 變紅的緊急修復，或擁有者明確要求。
25. 改動要有測試，而且 CI 綠才算完成。
26. 提問要附可選的選項與建議，不問開放式問題。小事與開發順序自己決定，只把需要授權的事（protocol 變更、計算預算、發行）帶給擁有者。
27. 擁有者要的是通則，不是個案解法。例如報告文字做成可重用的模板。
28. 刪除檔案：只在 MD20 專案內可以自行新增與刪除。專案以外的任何東西，刪除前先問。
29. 不使用付費 API。

用 Claude 開發時另外適用（D-180）：指揮的 session 用 Fable 5.5；平行開發開 Sonnet 5.5 子代理（high effort），指揮者審查後才整合。commit 結尾加屬名：
```
Co-Authored-By: Claude <模型名稱> <noreply@anthropic.com>
Claude-Session: <本次 session 連結>
```
人類開發者用自己的 git 身分 commit 即可。

### 9.6 安全紅線（不可退讓）
30. **私鑰永遠不進任何 repo。** 公鑰 `md20/util/owner_pub.pem` 在 repo，私鑰由擁有者離線保管。
31. 授權驗證**不得有任何後門**：沒有環境變數、設定、參數可以略過。測試會檢查原始碼。
32. 不提交任何密鑰、權杖、授權檔。
33. 只有擁有者能決定公開發行。
34. LLM 編排：碰到核心資料一律用本地模型；LLM 不得替人做閘門決定。規格審查前不實作。

### 9.7 文字（`docs/specs/writing_style.md`）
35. 所有給使用者看的文字都要四種語言，寫成 `(zh, en, ja, ko)`。`tests/test_i18n_coverage.py` 會擋。
36. 要像實驗室老師寫的：短句、白話、數字與門檻寫精確。不用破折號連接子句，不用斜線表示「或」，句子裡不用箭頭，不疊括號，不用套話。
37. 介面文字少用縮寫，不顯示 HCC Lab 戳記。介面要專業、克制。
38. 專案名稱用英數字（D-67）。PDB 與 PDBQT 內的戳記必須是純 ASCII（繁中 Windows 會當掉）。`system.xml` 不可加註解。

### 9.8 測試（repo 慣例）
39. 測試以 `pytest tests/<檔名>.py` 執行。**不可**寫 `from tests.x import`。
40. 載入 `tools/*.py` 用 `importlib.util.spec_from_file_location`。
41. 沒有引擎的環境用 `FakeBackend` 測邏輯；需要引擎的整合測試要能自動跳過。
42. 不可為了讓測試通過而放寬科學門檻。例如鋅的 0.03 nm 門檻不放寬，改用 xfail 並寫明原因。

### 9.9 介面與工具（2026-11-07）
43. 改介面、報告版面、學生說明頁之前，先載入 frontend-design skill（用 Claude 時）。
44. 介面行為用 Playwright 驗證。CI 有 `tools/gui_preview.py` 截圖。

### 9.10 開發容器的限制（只適用於雲端容器）
45. 容器連不到 RCSB 或一般網站，裝不了 OpenMM、RDKit、OpenFF、Vina。不要在容器裡硬裝。
46. 查 CI 用單次查詢，不要長時間輪詢。
47. 代理會擋建立 git tag。發行的繞法見 D-160。

## 10. 每次開發的固定步驟
1. `git pull`。讀 `docs/STATUS.md` 開頭、`docs/WORKBOARD.md`、`docs/DECISIONS.md` 最上面幾條。
2. 在 WORKBOARD 認領，寫明類別。
3. 新子系統或大改動：先寫或更新 `docs/specs/` 的規格。需要審查的先給擁有者。
4. 寫程式與測試。
5. 本機檢查：
   ```bash
   pytest                                                        # 全套
   python tools/capability_manifest.py --check                   # 能力清單同步
   python tools/build_lite.py --src . --out <暫存資料夾> --verify --smoke-tests   # 改到基本路線時必跑
   ```
6. 需要真實引擎的部分在本機驗證，跑完刪除產物，結果寫進 DECISIONS。
7. 寫 DECISIONS 條目，更新 STATUS 與 WORKBOARD，與程式同一個 commit。
8. 每週彙整推一次 `main`。推完看 CI 留言，確認跳過數是預期的。

## 11. 文件地圖
| 檔案 | 內容 |
|---|---|
| `CLAUDE.md` | 規則的原始出處，每次都要守 |
| `docs/ONBOARDING.md` | 本檔 |
| `docs/STATUS.md` | 目前版本與誠實現況，最新的在最上面 |
| `docs/WORKBOARD.md` | 誰在做什麼、待認領 |
| `docs/DECISIONS.md` | 所有決策，最新的在最上面 |
| `docs/CAPABILITIES.md` | 功能現況的權威清單（自動產生） |
| `docs/HANDOFF.md` | 一般交接說明 |
| `docs/WORKFLOW.md` | 設定檔欄位與人工決定點 |
| `docs/specs/` | 各子系統規格，索引在 `README.md` |
| `docs/specs/lite_edition.md` | Lite 規格 |
| `docs/specs/licensing.md` | 授權與發行保護 |
| `docs/specs/writing_style.md` | 文字規範 |
| `docs/specs/llm_orchestration.md` | LLM 編排（草案，審查前不實作） |
| `docs/students/` | 給學生的安裝與解鎖步驟，四種語言 |
| `docs/archive/` | 舊的交接、審查、發行說明、討論紀錄 |
