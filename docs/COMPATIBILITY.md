# 相容性矩陣（真機與 CI 實測）

每一台跑過 `md20 doctor` 的機器記一行。ns/day 為 24k 原子 TIP3P 水盒、dt 4 fs 的 benchmark。

| 日期 | 機器 | OS | GPU / 驅動 | 選用平台 | ns/day | 備註 |
|---|---|---|---|---|---|---|
| 2026-11-02 | MSI Cyborg 14 A13VF（i7-13620H 10C/16T、15.7 GB RAM） | Windows 11 家用版 26200 | RTX 4060 Laptop 8 GB／566.14（CUDA 12.7）+ Intel UHD | — | — | **v0.1.0a1 安裝失敗**：`ocl-icd-system =* * does not exist` → `Could not solve for environment specs`（CUDA 路徑；D-36 已修，a2）。修補後重測中 |
| 2026-10-31 | 教師筆電 | Windows 10 | GTX 1060 4 GB（舊驅動）+ UHD 630 | OpenCL（GTX 1060） | 200 | CUDA 失敗 `INVALID_PTX`（驅動過舊）；殘留 `nvopencl.dll` 觸發 DLL 錯誤視窗（已改為靜默失敗） |
| CI | GitHub windows-latest | Windows Server | 無 | CPU | 見 Actions artifact | 安裝路徑驗證 |
| CI | GitHub macos-latest | macOS (arm64) | 無 | CPU | 見 Actions artifact | |
| CI | GitHub ubuntu-latest | Ubuntu | 無 | CPU | 見 Actions artifact | 全流程（docking→MD→PMF）測試在此跑 |

## 安裝時已知問題與自動處理

| 症狀 | 原因 | 安裝器／Doctor 的處理 |
|---|---|---|
| Git Bash 執行 `install.sh` 出現 `Exec format error` | 抓到 Linux 版 micromamba | 偵測 MINGW/MSYS，改抓 win-64 |
| solver：`__cuda` 衝突 | win-64 的 openmm 都是 CUDA 連結版，無 NVIDIA 驅動時 solver 拒絕 | 非 NVIDIA 機器自動設 `CONDA_OVERRIDE_CUDA=12.4` |
| solver：`ambertools` 不存在 | conda 的 openmmforcefields 硬性依賴 ambertools（Windows 沒有） | openmmforcefields 改用 pip |
| `No space left on device` | C 槽滿；pip 暫存在 `%TEMP%` | 安裝前檢查空間；`MD20_ROOT=/d/MD20` 改裝其他磁碟；暫存與快取都放安裝目錄 |
| 彈出「無法找到程序輸入點 fatBinaryCtl」 | 舊 NVIDIA 驅動殘留 `nvopencl.dll` | `SetErrorMode` 靜默失敗；Doctor 偵測並說明 |
| `CUDA_ERROR_INVALID_PTX (218)` | 驅動比 OpenMM 的 CUDA 工具鏈舊 | Doctor 給兩個解法：更新驅動或改裝 `cuda-version=11.8` 版 |
