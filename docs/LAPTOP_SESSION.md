# 筆電工作站 session 交接（Windows 獨顯筆電）

使用者把一台有獨立顯示卡的 Windows 筆電當成 MD20 的**真機測試工作站**。這份檔給「在那台筆電上開的新 session」讀。

## 你是誰、要做什麼
- 你在使用者的 Windows 筆電上（透過 Claude 桌面 App 連到這台電腦）。目標：**讓 MD20 Windows 版至少在這台筆電上跑起來**，並把它變成之後的實機測試站。
- 先讀 repo 的 `CLAUDE.md` → `docs/HANDOFF.md` → `docs/STATUS.md` → `docs/WORKBOARD.md`（多個 session 同時開發，開工前認領）。

## 硬規則（使用者明確要求）
- **刪除任何東西之前，先問使用者**（檔案、資料夾、舊環境、`%LOCALAPPDATA%\MD20` 的任何內容）。需要清掉時，先列出要刪的路徑等使用者同意；不同意就搬到同層 `_to_delete\`。
- 不安裝驅動、不改系統設定；驅動只用 `md20.cmd drivers download` 下載到「下載」資料夾，由使用者自己安裝。
- 每個修正：程式＋測試＋`docs/DECISIONS.md` 條目同一個 commit；commit 尾端加 Co-Authored-By 與自己的 Claude-Session 連結。

## 步驟
1. 下載最新 Release：https://github.com/fstcch-cmd/md20-workstation/releases （目前 `v0.1.0a1`，`MD20-Windows-v0.1.0a1.zip`）→ 解壓 → 執行 `Install-MD20.cmd`。
   - 或 `git clone` 後 `powershell -ExecutionPolicy Bypass -File installer\install.ps1`（開發用，程式留在原地 editable）。
2. `%LOCALAPPDATA%\MD20\md20.cmd doctor`：**選用平台必須是 CUDA 或 OpenCL（不是 CPU）**，記下裝置、驅動、ns/day。
3. `md20.cmd demo`；雙擊桌面 `MD20-GUI.cmd` 確認 http://127.0.0.1:8020 開得起來。
4. 真實案例（`docs/WINDOWS_QUICKSTART.md` §5）：`pipeline example > trypsin.json`，把 `"tier"` 改 `"classroom"`，`pipeline run trypsin.json --project 測試`。
5. 把結果寫進 `docs/COMPATIBILITY.md`（日期、機器、Windows 版本、GPU／驅動、平台、ns/day、各步驟成敗、錯誤原文），push。
6. 任何失敗：在 repo 修（優先 `installer/`、`md20/env/`），本機重跑驗證；需要新安裝包時用
   `gh api -X POST repos/fstcch-cmd/md20-workstation/actions/workflows/release-windows.yml/dispatches -f ref=main -f "inputs[tag]=v0.1.0aN"`
   發行（release workflow 會先在乾淨 Windows runner 實裝驗證）。

## 已知事項
- CI runner 沒有 GPU：CUDA／OpenCL on GPU 的路徑**從未被驗證**，這台筆電是第一次。
- GBn2 只在 GPU 上較快；鋅鍵結模型仍在修（D-34），金屬案例先不要當驗收。
- 雲端開發 session（session_016gcJz8q2F6515MWPncJEZu）持續巡檢 CI 與 MD 檔；看到你的回報會協助修正。

## v0.1.0a3 介面實測清單（GUI v2，使用者週二要用）
CI 只能確認每頁渲染（HTTP 200 與截圖），**互動要在筆電上確認**。安裝 a3 後依序做，結果寫進 `docs/COMPATIBILITY.md`：
1. 首頁四張模式卡片可點；右上角語言切換（English、繁體中文）後頁面立即改變，重開 GUI 仍記得。
2. 教學模式二（胜肽）→「Start this teaching case」→ 流程頁：CPP 與活性位可及性的「科學限制」卡片出現但**不阻擋**；
   對接完成後頂端出現「Proceed to molecular dynamics?」卡片，按下後進入建模與模擬。
3. 教學模式一（六個代謝物同時對接，1VKX）：同上；確認同時對接的姿勢表與配體碰撞檢查。
4. 專業模式：改步長為 5 fs → 右側出現「Error」且「Create and start」停用；按「Apply suggestion」恢復。研究目標改「Binding strength」→ 未改過的參數跟著更新。
   先在「Computer status」做一次效能測試，再回專業模式看時間估計是否合理。
5. 快速模式：上傳一個 PDB 檔、貼兩行配體（其中一行 `PEP peptide:GGGGGKP`）、建立並開始。
6. 篩選：下載範例表格 → 上傳 → 排名長條圖點選長條會勾選化合物；手動上傳一個命名錯誤的 SDF 應被拒絕並說明原因。
7. 流程完成後「Open report」：英文與中文各開一次，確認每節五段（是什麼、科學意義、參數、圖表、解釋）與圖表編號。

## 監看執行中的 cmd 並回傳結果（使用者 11/02 16:45：雲端 session 要自行解讀並修正）
雲端開發 session 看不到筆電螢幕，所以由筆電 session 負責監看、回傳原始數據；解讀與修正由雲端 session 做。
1. 每 20 到 30 分鐘看一次 teaching 重跑的 cmd 視窗（不要用 sleep 迴圈；只讀，不要中斷它）。記下目前步驟與最後 30 行。
2. 出現錯誤、Traceback、NEEDS_HUMAN 或流程結束時，立刻建立 `docs/runs/2026-11-02_teaching_rerun.md`，內容：
   - 指令與設定（config.json 的 md、binding 區塊）、開始與結束時間、rc、最後 80 行輸出（原文）。
   - 若已結束：`workflows/<名稱>/state.json` 中 binding 的 results（ΔPMF、ΔG°、half_split、caveats）、
     `binding_*/smd.json` 的 `diagnostics`（D-45 振盪指標）、`binding_manifest.json` 的 `result.pmf.coverage` 與 `quality`。
   - 只放文字與小型 JSON（不要放 DCD、PNG 或整份 HTML）。
3. `git add docs/runs/… && git commit && git push`（commit 尾端加 Co-Authored-By 與筆電 session 連結）。不刪任何檔案。
雲端 session 會讀這個檔案，判斷預設拉離速度（0.01 或 0.005 nm ps⁻¹，看板待判斷項）並修正發現的問題。
