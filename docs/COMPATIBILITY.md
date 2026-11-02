# 相容性矩陣（真機與 CI 實測）

每一台跑過 `md20 doctor` 的機器記一行。ns/day 為 24k 原子 TIP3P 水盒、dt 4 fs 的 benchmark。

| 日期 | 機器 | OS | GPU / 驅動 | 選用平台 | ns/day | 備註 |
|---|---|---|---|---|---|---|
| 2026-11-02 | MSI Cyborg 14 A13VF（i7-13620H 10C/16T、16 GB RAM） | Windows 11 家用版 26200 | RTX 4060 Laptop 8 GB／566.14（CUDA 12.7）+ Intel UHD | **CUDA**（mixed，cuda-version 12.4，OpenMM 8.2.0） | **601–613** | v0.1.0a1 安裝失敗兩次：① `ocl-icd-system` 不存在（D-36）② 套件快取路徑 263 字元 > 260（D-38）。修正後（e9051ce）：安裝 2.6 min（環境已部分下載）、doctor OK（建議 tier research；classroom 2.3 ns ≈ 0.1 h）、`drivers plan` OK（不需更新）、demo OK、GUI http 200（3 s）。classroom 3PTB：**`pipeline run` rc=0，76.5 min**（apo＋docked BEN 兩個 run 都產出 report.html；自測 log `selftest_20261102_114651.log`，使用者 13:06 回報）；結果：redocking RMSD 0.38 Å（Vina −6.11）；backbone RMSD apo 0.87／holo 0.79 Å；BEN 全程留在口袋（末段 0.6 Å，Asp189／Ser190／Gly219 氫鍵候選 100%）；SMD 最大力 524 kJ/mol/nm、功 251 kJ/mol；umbrella 13 → 40 window（自動補窗 6 輪）；**ΔPMF 80.3 ± 1.0 kJ/mol，ΔG° 不輸出（not converged；classroom 本就不輸出）**——見 D-40 |
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

## 實機案例：MSI Cyborg 14／RTX 4060 Laptop，3PTB 胰蛋白酶＋苯甲脒，classroom tier（2026-11-02）

程式：v0.1.0a1 ＋ D-36／D-38 安裝修補（MD20 本體程式碼為 a1，未含其後 main 的修改）。`MD20-SelfTest.cmd` 全部步驟 rc=0。

| 步驟 | 結果 | 耗時 |
|---|---|---|
| 安裝 | OK（CUDA，cuda-version 12.4，OpenMM 8.2.0；套件快取 `C:\MD20pkgs`） | 2.6 min（環境已部分下載） |
| doctor | CUDA，601–613 ns/day（24k 原子水盒），建議 tier research | 0.6 min |
| demo／GUI | OK／http 200（3 s） | — |
| 對接 | redocking RMSD **0.378 Å**，−6.11 kcal/mol，PASS | 12 s |
| apo MD（2 ns） | PASS，約 330 ns/day（十二面體盒） | 11.2 min |
| docked_BEN MD（2 ns）＋分析＋SMD | 配體全程留在 S1 口袋（Asp189 接觸 100%、`stays_bound`）；PBC 假象偵測並校正（表觀 7.34 nm → 真實 0.22 nm）；SMD 最大力 524 kJ/mol/nm、功 250.6 kJ/mol | 15.1 min |
| 傘狀採樣 | 13 → 40 window、5 輪補窗後連續（上限 6 輪），延長 59 次 | 36.0 min |
| 報告 | apo／docked 各一份 report.html | — |

### 發現（待處理）
1. **PMF 被截斷（a1，MBAR 路徑）**：40 個 window 取樣到 1.72 nm，但 `pmf.png` 只畫到 0.50 nm 且仍在上升；
   報告的 ΔPMF 80.3 ± 1.0 kJ/mol 只是截斷邊緣的值，不是井深。同一批樣本用 main 的 `pmf_from_windows`（WHAM）重算，PMF 涵蓋 0.16–1.83 nm。
   main 的 D-43（MBAR 未收斂時與 WHAM 交叉比對）可能已部分防護，但仍需在**有 pymbar 的機器**以 main 重跑確認；並應加閘門：PMF 有限值範圍未涵蓋取樣範圍 → NEEDS_HUMAN。
2. **classroom tier 的結合自由能高估約 5 倍**：完整 radial PMF 在約 1.0 nm 後平台 125–134 kJ/mol → ΔG° ≈ −29.5 kcal/mol，實驗值約 −6.4 kcal/mol。
   原因判斷：window 只有 50 ps，配體被拉出時周圍水與 Asp189 鹽橋來不及鬆弛（取樣滯後）。a1 已正確**不輸出 ΔG°**；main 的 D-43 井深警示（9 個重原子上限約 57 kJ/mol）會標出此案例。
   classroom 的結合計算應明示「僅供示範流程，數值不可用」，或改為 teaching 等級再比較。
3. 補窗效率差：初始 window 等距、k 一律 1000，未利用 SMD 力曲線（見使用者試算表「補窗效率」）。
4. 外觀：doctor 顯示「Windows 10」與「NVIDIA NVIDIA」（D-39 已修）；pymbar 英文警告大量出現在 CMD（待處理）。

## 實機：教學一（hsieh2024，六配體同時對接）— MSI Cyborg 14／RTX 4060，a3 候選版（819c8ec），2026-11-03 夜間
- 安裝（從 9173daf／819c8ec 本機副本）1 分鐘內完成；doctor CUDA；GUI 正常；切換語言不再重跑（D-67 修正後實測）。
- 對接：exhaustiveness 32、六配體 simultaneous、資源模式全速。**00:12 開始，03:14 仍無輸出（> 3 小時）**。工作管理員：vina.exe CPU 約 24%（16 執行緒中約 4 個），
  優先順序「標準」、親和性 16 個全勾（D-70 更正）。關閉 GUI 視窗後舊 vina.exe 仍在跑（孤兒程序，D-69 修正）。
- 結論：論文設定在學生筆電上不可行 → 課堂／教學等級改為 8（D-71）。vina.exe 多配體只用約 4 執行緒、以及 3 小時以上是否已卡住，**未查明**。
