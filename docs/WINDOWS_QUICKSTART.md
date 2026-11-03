# Windows 快速上手（用獨顯筆電當測試機）

> 適用 **v0.1.0a6**（2026-11-03）。只是上課使用的話，請看較短的學生版 `docs/students/WINDOWS.md`，macOS 看 `docs/students/MAC.md`。

這份說明的目標是在 30 分鐘內把 MD20 裝到你的筆電上，確認有用到 GPU，跑完一個真實案例，再把結果回報到 repo。這樣這台筆電就成為正式的測試環境。
每一步都寫了「預期看到什麼」。沒看到的話就停下來，把畫面上的文字貼到 `docs/COMPATIBILITY.md`，或告訴開發 session。

## 0. 事前準備（5 分鐘）
- Windows 10 或 11，可用磁碟 ≥ 8 GB。環境約佔 6 GB，加上 `-Root D:\MD20` 可以改裝到其他磁碟。
- NVIDIA 筆電請先更新驅動（用 GeForce Experience 或到官網下載）。接著在 PowerShell 輸入 `nvidia-smi`，記下右上角的 **CUDA Version**。≥ 11.8 才會用 CUDA，否則自動改用 OpenCL。
- 安裝 [Git for Windows](https://git-scm.com/download/win)，或直接下載 repo 的 ZIP 解壓縮。

## 1. 安裝（10–20 分鐘，大多花在下載）
**最簡單的方式（不需要 git）**：到 GitHub 的 Releases 頁下載最新的 `MD20-Windows-<版本>.zip`，目前是 `MD20-Windows-v0.1.0a6.zip`。在檔案上按右鍵選「解壓縮全部」，再雙擊 `Install-MD20.cmd`。
SmartScreen 出現時，按「其他資訊」，再按「仍要執行」。程式會複製到 `%LOCALAPPDATA%\MD20\app`，解壓縮的資料夾之後可以刪掉。
已安裝的舊版不會刪除，會移到 `%LOCALAPPDATA%\MD20\_to_delete\`。其他預期畫面和下面的開發者安裝相同。

**測試機一鍵自測**：雙擊 `installer\MD20-SelfTest.cmd`。它會依序下載最新 Release、安裝、執行 doctor、demo、GUI，最後跑 classroom 3PTB。
整個過程記錄在 `桌面\MD20_test\selftest_<時間>.log`。

**開發者（git）**：
打開「Windows PowerShell」。內建的 5.1 版就可以，不需要 PowerShell 7。
```powershell
git clone https://github.com/fstcch-cmd/md20-workstation.git
cd md20-workstation
powershell -ExecutionPolicy Bypass -File installer\install.ps1          # 有 nvidia-smi 時用 cuda，否則用 opencl
```
預期依序看到 `[1/4] 下載 micromamba`、`[2/4] 建立環境 (cuda|opencl)`、`[3/4] 安裝 md20`（包含用 `setup-vina` 下載 Vina）、`[4/4] Doctor`，
最後印出「完成」。安裝器會在桌面放 `MD20-GUI.cmd`，並在 `%LOCALAPPDATA%\MD20\` 放 `md20.cmd`。

常見的卡關點如下，完整的表在 `docs/COMPATIBILITY.md`。
- `__cuda` solver 衝突：驅動太舊。安裝器已經自動改用 OpenCL。
- `CUDA_ERROR_INVALID_PTX`：驅動比 OpenMM 用的 CUDA 舊。請更新驅動，或加 `-Gpu opencl`。
- 下載 Vina 時出現 403：這是 GitHub API 限流。之後重跑 `md20.cmd setup-vina`，它會自動改用固定版本 v1.2.5 的下載網址。
- 套件快取路徑太長（Windows 有 260 字元上限）：安裝器會自動改用 `C:\MD20pkgs`。

## 1b. 驅動（安裝器跑完後，doctor 說驅動太舊時）
```cmd
%LOCALAPPDATA%\MD20\md20.cmd drivers plan       # 偵測顯示卡，判斷支援的 CUDA，列出兩種做法
%LOCALAPPDATA%\MD20\md20.cmd drivers download   # 下載官方最新驅動到「下載」並打開資料夾，雙擊安裝、重開機後再跑一次安裝器
```
不想更新驅動的話，執行 `powershell -ExecutionPolicy Bypass -File installer\install.ps1 -Cuda 11.8`，安裝能配合舊驅動的 OpenMM。GUI 的 Doctor 頁也有同樣的按鈕。

## 2. 確認 GPU 真的在計算（2 分鐘）
```cmd
%LOCALAPPDATA%\MD20\md20.cmd doctor
```
預期：平台階梯列出 CUDA → OpenCL → CPU，**選用的平台不是 CPU**。20 秒的 benchmark 會給出 ns/day。實測值是 RTX 4060 Laptop 用 CUDA 601–613，GTX 1060 用 OpenCL 約 200，只有 CPU 約 5–15。
把 doctor 輸出的選用平台、裝置、ns/day 和 tier 建議這四行，在 `docs/COMPATIBILITY.md` 的表格新增一列（日期、機器、OS、GPU 與驅動、平台、ns/day）。

## 3. 不用 OpenMM 的全流程演練（1 分鐘）
```cmd
%LOCALAPPDATA%\MD20\md20.cmd demo
```
預期：合成後端跑完分子對接、MD 和報告，最後印出報告路徑。打開 HTML 可以看到圖表、決策日誌和三態閘門。這一步確認安裝和報告產生都正常。

## 4. 圖形介面
雙擊桌面的 `MD20-GUI.cmd`，瀏覽器會打開 http://127.0.0.1:8020 。預設只有本機能連（127.0.0.1）。
- 首頁有四種模式：教學模式一（多種小分子，hsieh2024）、教學模式二（胜肽，hsieh2025）、快速模式和專業模式。
- 右上角有兩個選單。資源選單有「省資源：可同時寫報告」、「平衡（預設）」、「全速：電腦閒置時」，從下一個計算步驟起生效。語言選單有 English、繁體中文、日本語、한국어。
- 一次只跑一個計算。切換語言或離開頁面不會重跑。頂端的橫幅「計算進行中…回到進度」可以帶你回到進度頁。
- **計算期間不要關掉黑色主控台視窗**，瀏覽器可以關。關掉主控台會一起結束計算（包括 vina.exe）。重新開啟後按「開始／繼續」，會從中斷的地方接著算。

## 5. 第一個真實案例：胰蛋白酶與苯甲脒（3PTB）
```cmd
cd %USERPROFILE%\Desktop
%LOCALAPPDATA%\MD20\md20.cmd pipeline example > trypsin.json
%LOCALAPPDATA%\MD20\md20.cmd pipeline run trypsin.json --project first_case
```
專案名稱請用英文字母和數字。中文名稱會被改成英數代碼加亂碼的資料夾名（例如 `測試` 會變成 `item_xxxxxx`，D-67），不好找。
結果在 `文件\MD20_Projects\first_case`。
預期流程：從 RCSB 下載 3PTB → 受體閘門 → 分子對接（redocking RMSD < 2 Å）→ 選擇 pose → 建模（十二面體盒、padding 0.8）→ 最小化、NVT、NPT、production →
分析（置中後的 DCD）→ SMD 拉離與傘狀採樣（結合強度）→ 報告。中途可以關掉視窗，重跑同一行指令會接著算。GUI 的「開始／繼續」作用相同。

| 等級（`md` 區塊的 `"tier"`） | MD 長度 | RTX 4060 Laptop（CUDA）全流程 |
|---|---|---|
| `teaching`（範本預設） | 10 ns × 2 系統（apo、docked） | 約 3 小時（估算，以約 330 ns/day 計，含傘狀採樣約 16.5 ns，未實測） |
| `classroom` | 2 ns × 2 系統 | **76.5 分鐘（2026-11-02 實測）** |

**上課時建議先把 `trypsin.json` 裡的 `"tier": "teaching"` 改成 `"tier": "classroom"`。** 用記事本搜尋 `teaching` 就找得到，範本裡只有這一處。
classroom 的結合計算只示範流程，報告不輸出 ΔG°。teaching 只有在 PMF 末端持平時才輸出 ΔG°（D-65）。一維 COM PMF 對埋在口袋裡的配體會高估結合強度，只能比較趨勢。

## 6. 高通量篩選演練（可選，30 分鐘）
```cmd
%LOCALAPPDATA%\MD20\md20.cmd screen template --out compounds.xlsx     # 填 5–20 個化合物（smiles 或 PubChem CID）
%LOCALAPPDATA%\MD20\md20.cmd pipeline example --screen > screen.json  # 把 screen.library 指到 compounds.xlsx
%LOCALAPPDATA%\MD20\md20.cmd pipeline run screen.json --project screen_test
```
預期流程：下載 3D 結構 → 批次對接 → 停在「篩選：選擇化合物」閘門 → 在 GUI 的「篩選」分頁勾選 → 按「開始／繼續」進入正式對接與 MD。

## 7. 要回報什麼
1. 在 `docs/COMPATIBILITY.md` 加一列（見第 2 節）。
2. 真實案例跑完後，打開 `文件\MD20_Projects\first_case\...\runs\<run>\report.html`，再用 VMD 打開同一個 run 裡的 `analysis/production_centered.dcd`，看蛋白是否在盒子中央、配體是否在口袋裡。
3. 任何 NEEDS_HUMAN 閘門的文字。這些是檢驗通則的測試樣本，不需要針對這台機器修改。
4. 跑不動的地方：把終端機最後 50 行貼給開發 session，並附上 `md20.cmd doctor --no-benchmark` 的輸出。

## 開發者模式
從 git clone 執行 `installer\install.ps1` 時，安裝方式是 `pip install -e .`（editable）。改了 repo 裡的程式，`md20.cmd` 馬上生效，不用重裝。
Release ZIP 的 `Install-MD20.cmd` 則是把程式複製到 `%LOCALAPPDATA%\MD20\app`。`git pull` 之後如果 `environment/*.yml` 有變，重跑一次安裝器即可。環境已經存在時，安裝器只補裝缺少的套件。
