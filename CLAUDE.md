# CLAUDE.md — MD20 單機教學版工作站

**接手前先讀 `docs/STATUS.md`(開頭是目前版本與誠實現況)、`docs/WORKBOARD.md` 與 `docs/DECISIONS.md` 最上面幾條,再讀 `docs/HANDOFF.md`(一般說明)。舊的交接、審查與發行說明在 `docs/archive/`。** 以下是每次都要遵守的重點。

## 這個 repo 是什麼
Docking → 建模 → OpenMM MD → SMD/傘狀採樣的單機教學版,給博士生在自己筆電上跑(Windows 優先)。擁有者 HCC Lab, NKUST。所有成果在本 repo + GitHub Actions CI 上。

## 硬限制(違反會卡住)
- 開發容器**連不到 RCSB 或任意網站**(只有 PyPI/conda/GitHub);需要 PDB 請用 `gh` 或請使用者附上。
- 容器**裝不了 OpenMM/RDKit/OpenFF/Vina**;本地用 `FakeBackend` 測邏輯,**真實測試交給 CI** `openmm-stack` 矩陣,不要在容器裡裝這些。
- 查 CI 用**單次** `gh run view`/`gh api ... comments`,**不要**長 `sleep`+迴圈輪詢,也避免 `rm -rf $VAR` 式語法(會觸發安全中斷)。

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
- 使用者規則：開發順序自己決定；**push 要批次**（一輪 CI 跑完再推）；可用 Sonnet 子代理平行開發（HANDOFF §0）。

## Skills 與工具（使用者 2026-11-07 指定：適合時自動使用）
- **frontend-design**（Anthropic 官方 skill）：任何 GUI（`md20/gui/`）、報告 HTML 版面、學生說明頁的設計或改版，先載入再動手。
- **Playwright**：驗證 GUI 行為。CI 已有 `tools/gui_preview.py`（Playwright 截圖）；本機若有 Playwright MCP（使用者以 `npx @playwright/mcp@0.0.84 --isolated` 固定版本、隔離模式加入），用它實際操作畫面確認。升級版本前先檢查 `microsoft/playwright-mcp` 的發行內容。
