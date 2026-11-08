# GUI 設計系統（D-146）與連線穩定性（D-147）

## 1. 設計系統（`md20/gui/theme.py`）
用 frontend-design 的方法替教學工作站做一套設計語言，所有頁面從 `theme.css(lang)` 與 `theme.QUASAR_COLORS` 套用，不散落在各檔的 inline style。

- **主題**：介面的工作是「說清楚計算在哪一步、哪裡需要學生決定、怎麼安全繼續」。唯一張揚的元素是**三態閘門**，用**形狀＋顏色**雙重區分（● 通過、◐ 已自動修正、◆ 需要你決定），卡片左緣有狀態色條；形狀讓色盲者與列印也分得出來。其餘保持安靜。
- **配色**（WCAG AA，測試強制）：紙面 `#F3F6F6`（淡水色，不是米黃）、墨 `#13232A`、主色溶劑藍綠 `#0D6870`；狀態色分工：**綠=通過**、**藍=自動修正（程式動的，機器色）**、**琥珀=需要你決定**、**紫=正在執行**（唯一的紫，呼吸點）。琥珀改為 `#9A5A00` 以達 4.5:1。
- **字體**：用筆電自己的 UI 字（離線、無 web font），每語言挑 CJK 清楚的：繁中 Microsoft JhengHei UI、日 Yu Gothic UI、韓 Malgun Gothic，拉丁 Segoe UI Variable。數字 tabular。等寬只給機器碼與路徑。
- **版面**：單一內容寬度 1120px；階層決定圓角（區塊 10px、控制項 6px、狀態徽章圓形）；用髮絲線不用陰影；標題負字距，正文行長 ≤ 72ch。
- **動效**：只有「執行中」橫幅的呼吸點一處；尊重 `prefers-reduced-motion`。`:focus-visible` 全站可見。
- **避開 AI 生成的 tell**：不用米黃＋terracotta、不用全大寫 eyebrow、不用每段加編號、不在每張卡加同一種陰影、不用 `→` 接在按鈕文字後。閘門編號只在真的是序列時才用。

## 2. 連線穩定性（`md20/gui/connection.py`）
使用者要求「增強連線穩定性」。筆電教學場景會斷線：背景分頁被 Windows/Chrome 節流（計時器降到約每分鐘一次）、筆電睡眠、教室 Wi-Fi 掉、載入大的 OpenMM XML 時 GIL 被佔住（D-93）。

- **伺服器心跳**：`tune_heartbeat` 把 engine.io 的 ping timeout 從預設 20 s 調到 90 s（interval 20 s），撐過背景節流與 GIL 佔用；瀏覽器真的關掉仍會在一兩分鐘內被發現。
- **用戶端重連**：`CONNECTION_JS` 監聽 `visibilitychange`/`online`/`focus`，一旦分頁回到前景或網路恢復且 socket 斷著，立刻重連，不等指數退避的下一步。重連**保留頁面**（狀態都在伺服器與磁碟，D-103）；只有伺服器已不認得這個 client（GUI 重啟）時 NiceGUI 才會重載。
- **檔案替換重試**（`util/jsonio.replace_retry`）：Windows 上另一個程序（GUI 讀進度檔、防毒掃描、OneDrive）開著目的檔時，`os.replace` 會丟 PermissionError。計算不能因此中止或掉一次狀態更新：短退避重試約 1.2 s，最後仍失敗就**丟出**（不靜默跳過）。套用到 `atomic_write_json` 與 `atomic_copy`（GUI/worker 的進度檔早在 D-103 已自帶重試）。

## 3. 驗證
- 純測試 `tests/test_gui_theme_connection.py`：配色對比 AA、白字在填色鈕/徽章上可讀、三態形狀相異、每語言 CJK 字型堆疊且無 web font、reduced-motion 與 focus 樣式在、Quasar 品牌色跟著 token、`replace_retry` 退避/丟出/不吞其他錯、`atomic_write_json` 走重試、心跳調整、用戶端重連不強制重載。
- `tools/theme_preview.py`：產生離線的設計參考頁（本機 Playwright 截圖）。真實 GUI 各頁套用後的樣子由 CI `gui-preview`（D-42）產出。
