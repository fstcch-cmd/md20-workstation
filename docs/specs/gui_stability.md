# GUI 穩定性：計算獨立程序、狀態從檔案讀回（D-103）

狀態：**[已實作・待 CI]**（容器：`tests/test_gui_worker.py` 含真實子程序；瀏覽器 e2e：CI gui-preview 的穩定性檢查）。

## 要解決的問題
學生回報 GUI「很容易斷線」。斷線後進度列、即時曲線、傘狀採樣斷點提示消失，狀態變成閒置，看起來像計算停了。

## 原因
| # | 原因 | 位置（D-103 前） |
|---|---|---|
| 1 | 計算 thread 和 NiceGUI 事件迴圈在同一個程序，長時間持有 GIL 的工作（載入大 System XML、WHAM/MBAR bootstrap、畫圖）讓 WebSocket 心跳沒有回應 | `gui/logic.py` `Runner.start` |
| 2 | 平台探測（import OpenMM、建 Context）在事件迴圈上 | `app._platform()`（第一次按開始） |
| 3 | 「重新整理報告」在事件迴圈同步建報告 | `app.py` `rebuild()` |
| 4 | 進度只在記憶體 queue，重連／重開就沒了 | `Job.events` |

## 設計
```
GUI (NiceGUI)                          worker (python -m md20.gui.worker)
  按「開始」→ Runner.start_process ──► Popen（與 GUI 主控台分離）
                                        探測平台、PausePolicy、wf.run(progress_cb=sink)
  ProcessJob.snapshot() ◄── 讀檔 ───── <wf>/_gui_job/job.json        狀態、訊息、報告、心跳（5 s）
                        ◄── 增量讀 ── <wf>/_gui_job/progress.jsonl   一行一個事件
  頁首「計算進行中」    ◄── 讀檔 ───── <root>/_gui_running.json      目前在跑的 workflow
  暫停 ─────────────── PAUSE 檔 ─────► chunk 邊界停下（與以前相同）
```
- **存活判定**：GUI 有 Popen handle 時用 `poll()`；GUI 重開後只有心跳，`STALE_S = 180 s` 沒心跳才判定結束。結束卻沒寫結果 → ERROR＋worker.log 末段，可按「開始或繼續」從最後 chunk 續跑。
- **一次只跑一個（D-67）**：`Runner.running(root)` 先看本程序的 job，再看指標檔，因此 GUI 重開或開兩個視窗也不會重複啟動。
- **讀檔安全**：`ProgressReader` 只讀到最後一個換行；檔案被新一輪截斷（大小變小或 inode/ctime 變了）就從頭讀。`job.json` 以 `os.replace` 原子寫入，Windows 上讀者佔用時重試。
- **不用 `os.kill(pid, 0)`**：Windows 上那會 TerminateProcess。

## 行為改變
關掉 GUI 不再中斷計算（以前 daemon thread 會死）。要停請按「暫停」。若要改成「關 GUI＝暫停」，在 GUI 結束鉤子放 PAUSE 檔即可（未做，待使用者決定）。

## 測試
- `tests/test_gui_worker.py`：整行讀／截斷、心跳、worker 寫檔與指標清除、NEEDS_HUMAN／ERROR、死掉的 worker、重開後接回不重啟、真實子程序 fake run。
- `tools/gui_preview.py stability`（CI gui-preview）：換四種語言不重啟（D-74）＋**關 GUI → 計算仍跑 → 重開 GUI → 首頁看到計算中、流程頁進度列回來、再按開始不重啟**。

## 未做／待審
- 定時更新改成「檔案有變才讀」（目前每 2 秒在事件迴圈讀 state.json 與決策紀錄；量小，先不動）。
- 筆電實測：Windows 上關掉 GUI 主控台視窗時子程序是否確實存活（CI 的 Windows runner 沒有 GUI 主控台可關）。
- 審查問題：180 秒的心跳門檻在筆電上是否太長（GUI 重開後最多 3 分鐘才發現子程序已經死掉）？
