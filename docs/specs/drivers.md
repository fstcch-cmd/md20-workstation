# 顯示卡驅動：偵測 → 判定 → 一鍵下載（環境問題要徹底解決，不只診斷）

狀態：**[已實作・查詢服務待真機驗證]**（2026-11-01）。判定規則與下載器有 11 個離線測試；NVIDIA 查詢服務在 CI runner（無 GPU）不會被呼叫，只能在真機驗證。

## 1. 使用者要求
Doctor 只說「驅動太舊」不夠：程式要自己找到載點，讓使用者找到最適合自己的驅動並一鍵下載，不需要思考。

## 2. 誠實邊界
- **下載一鍵、安裝不自動**：驅動安裝需要管理員權限與重開機；程式替使用者靜默執行驅動安裝器是不該做的事（也會被防毒／UAC 擋）。下載完開啟資料夾，使用者雙擊。
- **只從官方網域（https）下載**：`nvidia.com`／`geforce.com`／`amd.com`／`intel.com`，其他一律拒絕；下載長度不符即刪除。
- **查不到就給官方頁面，不猜型號**。
- AMD／Intel 沒有公開的型號查詢 API：給官方自動偵測工具（AMD Auto-Detect、Intel DSA）。

## 3. 判定（`md20/env/drivers.py::plan_drivers`）
| 情況 | 狀態 | 現在會用 | 動作 |
|---|---|---|---|
| NVIDIA，驅動 ≥ 551.61（CUDA 12.4） | OK | CUDA | 不需更新 |
| NVIDIA，452.39 ≤ 驅動 < 551.61 | UPDATE | CUDA（cuda-version 11.8）或 OpenCL | ① 一鍵下載最新 WHQL → 安裝 → 重跑安裝器；② 不動驅動：`install.ps1 -Cuda 11.8` |
| NVIDIA，驅動 < 452.39 | UPDATE | OpenCL | 只有更新驅動一途（CUDA 11.8 也不支援） |
| AMD | FALLBACK | OpenCL | AMD 自動偵測工具 |
| Intel 內顯 | FALLBACK | OpenCL（慢） | 提醒指派獨顯 |
| 無 GPU | NONE | CPU | 建議 GBn2 或借機器 |

驅動→CUDA 對照取自 NVIDIA CUDA release notes（12.4: 551.61／550.54.14；12.0: 527.41／525.60.13；11.8: 452.39／450.80.02）。
Windows WMI 的版本字串（31.0.15.5161）轉成 GeForce 版本（551.61）。

## 4. NVIDIA 載點查詢（`resolve_nvidia_download`）
nvidia.com 下載頁背後的公開服務：`lookupValueSearch.aspx?TypeID=2/3` 取產品家族／系列（XML），以顯示卡名稱比對（完全相同 → 最長包含 → 系列前綴＋筆電／桌機），
再以 `AjaxDriverService.php?func=DriverManifestLookup&pfid&psid&osID(135=Win11, 57=Win10)&isWHQL=1&dch=1` 取最新套件的 `DownloadURL`／`Version`。
任何一步失敗 → `None` → 官方頁面。**這個服務不是 NVIDIA 正式文件化的 API，可能變動**；變動時行為退化為官方頁面，不會給錯檔案。

## 5. 介面
- `md20 doctor`：每張卡一行「驅動 …」finding（狀態、現在會用什麼、兩條路、安裝器指令）。
- `md20 drivers plan|download|open`：列計畫／下載到 ~/Downloads 並開資料夾／開官方頁。
- GUI Doctor 頁：每張卡一張卡片，「一鍵下載官方驅動（版本）」按鈕與「開啟官方下載頁」。
- 安裝器 `-Cuda 11.8|12.0|12.4`：不更新驅動時安裝對應的 OpenMM。

## 6. 待真機驗證（明早筆電）
`md20 drivers plan` 是否正確對到型號與 Windows 版本；下載的檔名／版本是否與 nvidia.com 頁面一致。

## 想請審查者回答
1. 查詢服務失效時，要不要退一步用 NVIDIA App 的安裝連結當「一鍵」？
2. 是否要把驅動版本→CUDA 對照表做成可更新的 JSON，而不是寫死在程式裡？
