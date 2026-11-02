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
