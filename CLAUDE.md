# CLAUDE.md — MD20 單機教學版工作站

**接手前先讀 `docs/STATUS.md`(開頭是目前版本與誠實現況)、`docs/WORKBOARD.md` 與 `docs/DECISIONS.md` 最上面幾條,再讀 `docs/HANDOFF.md`(一般說明)。舊的交接、審查與發行說明在 `docs/archive/`。** 以下是每次都要遵守的重點。

**第二位開發者或新加入的人：先讀 `docs/ONBOARDING.md`（D-187）。** 它把現有的開發分線、流程、功能現況、待做、等驗收、要在本機驗證的項目和所有規則整理在一份。

## 這個 repo 是什麼
Docking → 建模 → OpenMM MD → SMD/傘狀採樣的單機教學版,給博士生在自己筆電上跑(Windows 優先)。擁有者 HCC Lab, NKUST。所有成果在本 repo + GitHub Actions CI 上。
**出貨兩個版本：完整版與 Lite，共用同一份源碼（見下方「兩個版本架構」一節，接手必讀）。**

## 硬限制(違反會卡住)
- 開發容器**連不到 RCSB 或任意網站**(只有 PyPI/conda/GitHub);需要 PDB 請用 `gh` 或請使用者附上。
- 容器**裝不了 OpenMM/RDKit/OpenFF/Vina**;本地用 `FakeBackend` 測邏輯,**真實測試交給 CI** `openmm-stack` 矩陣,不要在容器裡裝這些。
- 查 CI 用**單次** `gh run view`/`gh api ... comments`,**不要**長 `sleep`+迴圈輪詢,也避免 `rm -rf $VAR` 式語法(會觸發安全中斷)。

## 開發節奏與角色(使用者 2026-11-11 指定,D-180;取代先前的 push 規則)
- **主要指揮大腦 = Fable 5.5**:領導 session 用 Fable 5.5 規劃與整合。
- **子代理 = Sonnet 5.5**:平行開發一律開 Sonnet 5.5 子代理協助,指揮者審查後整合。
- **推 GitHub 頻率 = 每週一次**(不再是「一輪 CI 跑完就推」):平時在本機累積、整合、驗證,每週彙整推一次 main。緊急修復(主線紅)例外。
- **驗證一律在本機(local)電腦執行,執行完刪除**:真實引擎驗證(OpenMM/RDKit/Vina、heavy 流程、安裝)在使用者本機(RTX 3090/Ubuntu 工作站,見 workstation-setup)跑,**跑完刪除產生的中繼檔/暫存**,不把驗證產物留在工作區或 repo。容器仍只用 `FakeBackend` 測邏輯。
  - *備註(接手者注意)*:此規則與「真實測試交給 CI」並行——push 時 CI 仍會跑;「本機驗證+刪除」是 push 前的主要把關。若與 CI 牴觸,以本機驗證為準,並把疑點記 DECISIONS。

## 兩個版本架構：完整版與 Lite（使用者 2026-11-12 指定，D-186；接手必讀）
這個專案出貨**兩個版本**，共用**同一份源碼、同一個 main 分支**。不要為 Lite 另開長期分支或另寫一套程式。

| | 完整版 | Lite（導流版） |
|---|---|---|
| 給誰 | 實驗室內、簽約或授權的使用者 | 實驗室以外的人，免費，需使用者簽發的授權檔 |
| 定位 | 功能完整、規模不限 | 流程完整但規模受限，目的是讓人用過後想升級完整版 |
| 怎麼產生 | 源碼樹本身（`tools/build_protected.py` 可選編譯核心） | `tools/build_lite.py` 從源碼樹打包：移除完整版模組、換成空殼、寫入 `md20/_edition.json`，再編譯核心（D-182） |
| 專案格式 | 相同。Lite 專案用完整版直接打開接著跑 | 相同 |

規格：`docs/specs/lite_edition.md`。決策：D-181、D-182。討論紀錄：`docs/archive/discussions/2026-11-11_lite.md`。

**動手前先判斷這次的工作屬於哪一類，並在 WORKBOARD 認領時寫明「完整版」「Lite」或「共用」：**
1. **共用的基本路線**（docking、分子動力學、快速 PMF、基本分析、報告、介面骨架）：兩個版本都會跑到。改完除了平常的測試，還要確認 Lite 樹仍然可用：`python tools/build_lite.py --src . --out <暫存資料夾> --verify --smoke-tests`（CI 的 `lite-build` 做同一件事）。
2. **只有完整版才有的功能**（膜系統、胜肽摺疊、粗粒化、長時間模擬、多重複、完整結合自由能、大型篩選、進階分析、自動補跑，以及之後新增的進階功能）：新功能要在 `md20/edition.py` 的 `PRO_FEATURES` 登錄（四語標題、一句好處、`modules=` 列出要從 Lite 移除的原始檔），並在 `check_config` 加上入口判斷。新模組盡量獨立成檔、由基本路線**延遲 import**，這樣才能從 Lite 乾淨移除。
3. **Lite 專屬**（上限數字、碰到上限的閘門與文字、報告附錄 D、介面的版本頁與提示、打包工具）：只改 `md20/edition.py`、`md20/edition_preview.py`、`md20/report/edition_section.py`、`md20/gui/edition_ui.py`、`tools/build_lite.py` 與它們的測試。

**硬規則：**
- 版本的唯一來源是 `md20/edition.py`。其他任何地方**不准寫死 `if lite`** 或自己判斷版本，一律問 `edition.current()`、`edition.limits()`、`edition.check_*`。
- 完整版的行為、輸出、protocol hash 不得因為 Lite 的改動而改變。Lite 的邏輯在完整版必須是空操作。
- 沒有任何環境變數、設定或參數可以改版本。測試裡用 monkeypatch 模擬 Lite，不用環境變數。
- Lite 的結果在它的範圍內必須是對的。不得為了推升級而降低、隱藏或模糊結果。
- 自動縮小只縮規模，不替使用者拿掉功能或刪配體（寧可擋也不要猜）。
- `md20/_edition.json` 只存在於 Lite 安裝包，**絕不提交進 repo**。
- 給外部的 Lite 必須是 `build_lite.py` 的產物並開核心編譯。帶 `lite` 字的授權裝在完整安裝包上只供內部測試。

**Lite 目前的真實狀態（2026-11-12）**：容器測試與 CI `lite-build` 通過。**沒有**在真的瀏覽器看過介面、**沒有**用真實引擎跑過 Lite 樹、上限數字未校準、核心編譯新加的四個模組未真的編譯過。已知問題列在 D-181「整合後仍成立的問題」。

## 開發規則(MD20_optimization_brief)
- 不新增 phase/step,只強化既有邏輯。
- 三態閘門 PASS / AUTO_FIXED / NEEDS_HUMAN;每個自動決策寫 `DecisionLog`,`why` 用中文。
- **寧可擋也不要猜**:條件不足就 NEEDS_HUMAN 並給選項。
- `STATUS.md` 要誠實三級;改動要有測試且 CI 綠才算完成。

## 決策與規格要寫進 repo(使用者 2026-11-01 指定,必守)
- **任何專項修改**,都要把與使用者討論的結論或你自己的判斷(含理由、取捨、被否決的做法、證據)寫進 Markdown,
  **與程式碼同一個 commit** 推上 GitHub,供使用者審查與版本管理:
  - 依日期累積的決策紀錄:`docs/DECISIONS.md`(新條目加在最上面:日期、主題、決定、理由、證據/測試、相關 commit 與檔案、未決問題)。
  - 子系統規格:`docs/specs/<主題>.md`(新子系統建新檔;既有子系統更新該檔並在 `docs/specs/README.md` 索引登記)。
- 判斷錯了要在原條目下方加「更正」並保留原文,不刪除歷史。
- **多個 session 同時開發**:開工前 `git pull` 並讀 `docs/WORKBOARD.md`,認領項目後才動手,完成後更新看板;不動別人認領中的主題。
- 使用者會用其他模型審查 `docs/specs/` 後回饋;收到回饋時,在對應規格檔記錄採納/不採納與理由。

## Commit 屬名
每次 commit 結尾加(用你自己的 session 連結):
```
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: <本次 session 連結>
```

## 戳記
`md20/util/stamp.py`;公鑰 `md20/util/owner_pub.pem` 在 repo,**私鑰不在 repo 也不該進 repo**(使用者離線保管)。`system.xml` 不可加註解(OpenMM 會讀不了)。

## 第四個 session 之後必知
- 2026-11-01 全面審查結果在 `docs/archive/REVIEW_2026-11-01.md`(未修項目從那裡接)。HTS 篩選規格 `docs/specs/hts_screen.md`。
- `pipeline run` 會沿用 workflow config.json 的人工決定(`workflow.DECISION_KEYS`);新增閘門決定鍵要加進去。
- CI main 不取消進行中的 run;看 summary 留言的 **skip 數**,SKIPPED 的整合測試不算通過。
- PDB/PDBQT 的戳記必須純 ASCII(cp950 Windows 會崩)。

## 現況與還沒做
**對外版本是 v0.1.0a20**（2026-11-09 prerelease，D-160）；main 為開發中 a21.dev0。代理封鎖建 git tag，發行繞法（推 `release/<tag>` 分支＋`gh workflow run release-windows.yml -f tag=<tag>`）見 D-160。能力現況以 `docs/CAPABILITIES.md` 為準（D-136）；四種語言：英、繁中、日、韓（文字規範 `docs/specs/writing_style.md`）。給學生的步驟在 `docs/students/`；專案名稱用英數字（D-67）。**LLM 編排規格 `docs/specs/llm_orchestration.md`（D-161）是草案：使用者與其他模型審查、收到回饋前不實作。**
WP5、WP9、WP13、金屬 policy/幾何鍵結模型已實作(真實驗證狀態見 `docs/STATUS.md`)。
GUI 閘門一鍵決定(`md20/gui/actions.py`)、3D 互作/vdW 表面、金屬擬合參數(`md20/build/metal_params.py`:QM Hessian 內建轉換/MCPB.py 轉譯/JSON,附 QM 小模型輸入產生)已實作。
還沒做:配體直接配位金屬的參數化(目前只有 D-53 距離約束後備)、受體長 loop 等選項的自動處理、漏斗約束 ΔG°：`BindingConfig` dataclass 預設徑向，pipeline 層 teaching/research 預設漏斗、classroom 徑向（D-151/D-154；D-140 的筆電 3PTB 驗收條件仍未完成）、D-72 筆電實測。細節見 `docs/HANDOFF.md` §6。

## 授權與數位簽章（2026-11-07 起，必知）
- 私人 repo **`fstcch-cmd/md-digital-signature`** 是簽發端（擁有者工具、簽出授權紀錄）；本 repo 只放驗證端。接手時兩個都要 add_repo＋clone。
- **私鑰永遠不進任何 repo**（擁有者離線保管，與 `md20/util/owner_pub.pem` 成對）；驗證不得有任何環境變數／設定／參數後門。
- 設計：`docs/specs/licensing.md`（D-125）、D-124 LICENSE、設計文件 https://claude.ai/artifact/222jyPJRrE1Pzspv7shAS6 。
- 使用者規則：開發順序自己決定。**push 節奏、子代理與指揮模型、本機驗證規則見上面「開發節奏與角色」(D-180,取代先前「push 批次」)。**

## Skills 與工具（使用者 2026-11-07 指定：適合時自動使用）
- **frontend-design**（Anthropic 官方 skill）：任何 GUI（`md20/gui/`）、報告 HTML 版面、學生說明頁的設計或改版，先載入再動手。
- **Playwright**：驗證 GUI 行為。CI 已有 `tools/gui_preview.py`（Playwright 截圖）；本機若有 Playwright MCP（使用者以 `npx @playwright/mcp@0.0.84 --isolated` 固定版本、隔離模式加入），用它實際操作畫面確認。升級版本前先檢查 `microsoft/playwright-mcp` 的發行內容。
