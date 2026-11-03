# Windows 快速上手（獨顯筆電當測試機）

> 適用 **v0.1.0a3**（2026-11-03）。只想上課使用請看較短的學生版 `docs/students/WINDOWS.md`（macOS：`docs/students/MAC.md`）。

目標：30 分鐘內在你的筆電上裝好、確認 GPU 被用到、跑完一個真實案例，並把結果回報到 repo，讓這台筆電成為正式的測試環境。
每一步都寫「預期看到什麼」；沒看到就停下來，把畫面文字貼到 `docs/COMPATIBILITY.md` 或告訴開發 session。

## 0. 前置（5 分鐘）
- Windows 10/11，可用磁碟 ≥ 8 GB（環境約 6 GB；`-Root D:\MD20` 可改裝到其他磁碟）。
- NVIDIA 筆電：先更新驅動（GeForce Experience 或官網），然後在 PowerShell 打 `nvidia-smi`，記下右上角 **CUDA Version**（≥ 11.8 才走 CUDA，否則自動改 OpenCL）。
- 安裝 [Git for Windows](https://git-scm.com/download/win)（或直接下載 repo ZIP 解壓）。

## 1. 安裝（10–20 分鐘，多半在下載）
**最簡單（不需要 git）**：到 GitHub 的 Releases 頁下載最新的 `MD20-Windows-<版本>.zip`（目前 `MD20-Windows-v0.1.0a3.zip`）→ 右鍵「解壓縮全部」→ **雙擊 `Install-MD20.cmd`**
（SmartScreen 出現時按「其他資訊」→「仍要執行」）。程式會複製到 `%LOCALAPPDATA%\MD20\app`，解壓的資料夾之後可刪；
已安裝的舊版不刪除，移到 `%LOCALAPPDATA%\MD20\_to_delete\`。其餘預期畫面同下。

**測試機一鍵自測**：雙擊 `installer\MD20-SelfTest.cmd`（下載最新 Release → 安裝 → doctor → demo → GUI → classroom 3PTB），
全程記錄到 `桌面\MD20_test\selftest_<時間>.log`。

**開發者（git）**：
開「Windows PowerShell」（內建的 5.1 即可，不需要 PowerShell 7）：
```powershell
git clone https://github.com/fstcch-cmd/md20-workstation.git
cd md20-workstation
powershell -ExecutionPolicy Bypass -File installer\install.ps1          # 自動：有 nvidia-smi → cuda，否則 opencl
```
預期：`[1/4] 下載 micromamba` → `[2/4] 建立環境 (cuda|opencl)` → `[3/4] 安裝 md20`（含 `setup-vina` 下載 Vina）→ `[4/4] Doctor`，
最後印「完成」。安裝器會在桌面放 **`MD20-GUI.cmd`**，並在 `%LOCALAPPDATA%\MD20\` 放 `md20.cmd`。

常見卡點（`docs/COMPATIBILITY.md` 有完整表）：
- `__cuda` solver 衝突 → 驅動太舊；安裝器已自動改 OpenCL。
- `CUDA_ERROR_INVALID_PTX` → 驅動比 OpenMM 的 CUDA 舊；更新驅動或 `-Gpu opencl`。
- 403 下載 Vina → 之後重跑 `md20.cmd setup-vina`（GitHub API 限流；會自動改用固定版本 v1.2.5 的下載網址）。
- 套件快取路徑太長（Windows 260 字元上限）→ 安裝器自動改用 `C:\MD20pkgs`。

## 1b. 驅動（安裝器跑完若 doctor 說驅動太舊）
```cmd
%LOCALAPPDATA%\MD20\md20.cmd drivers plan       # 偵測這張卡、判定支援的 CUDA、兩條路
%LOCALAPPDATA%\MD20\md20.cmd drivers download   # 一鍵下載官方最新驅動到「下載」並開啟資料夾 → 雙擊安裝 → 重開機 → 重跑安裝器
```
不想動驅動：`powershell -ExecutionPolicy Bypass -File installer\install.ps1 -Cuda 11.8`（安裝對應舊驅動的 OpenMM）。GUI 的 Doctor 頁有同樣的按鈕。

## 2. 確認 GPU 真的在算（2 分鐘）
```cmd
%LOCALAPPDATA%\MD20\md20.cmd doctor
```
預期：平台階梯列出 CUDA → OpenCL → CPU，**選用的平台不是 CPU**，20 秒 benchmark 給出 ns/day（實測：RTX 4060 Laptop／CUDA 601–613、GTX 1060／OpenCL 約 200；純 CPU 約 5–15）。
把 doctor 輸出的「選用平台／裝置／ns/day／tier 建議」四行貼到 `docs/COMPATIBILITY.md` 的表格新增一列（日期、機器、OS、GPU/驅動、平台、ns/day）。

## 3. 不碰 OpenMM 的全流程演練（1 分鐘）
```cmd
%LOCALAPPDATA%\MD20\md20.cmd demo
```
預期：合成後端跑完 docking→MD→報告，印出報告路徑；開啟 HTML 看得到圖表、決策日誌、三態閘門。這一步證明安裝與報告鏈正常。

## 4. 圖形介面
雙擊桌面 **`MD20-GUI.cmd`** → 瀏覽器開 http://127.0.0.1:8020 。只有本機能連（預設 127.0.0.1）。
- 首頁四種模式：教學模式一（多種小分子，hsieh2024）、教學模式二（胜肽，hsieh2025）、快速模式、專業模式。右上角兩個選單：資源（「省資源：可同時寫報告」／「平衡（預設）」／「全速：電腦閒置時」，下一個計算步驟起生效）與語言（English／繁體中文）。
- 一次只跑一個計算；切換語言或離開頁面不會重跑，頂端橫幅「計算進行中…回到進度」可回到進度頁。
- **計算期間不要關掉黑色主控台視窗**（關瀏覽器沒關係）：關掉它會一併結束計算（含 vina.exe），重開後按「開始／繼續」從中斷處接續。

## 5. 第一個真實案例：胰蛋白酶＋苯甲脒（3PTB）
```cmd
cd %USERPROFILE%\Desktop
%LOCALAPPDATA%\MD20\md20.cmd pipeline example > trypsin.json
%LOCALAPPDATA%\MD20\md20.cmd pipeline run trypsin.json --project first_case
```
專案名稱請用英數字：中文名稱會被改成「英數＋亂碼」的資料夾名（例如 `測試` → `item_xxxxxx`，D-67），不好找。
結果在 `文件\MD20_Projects\first_case`。
預期：RCSB 下載 3PTB → 受體閘門 → 對接（redocking RMSD < 2 Å）→ pose 選擇 → 建模（十二面體盒、padding 0.8）→ 最小化／NVT／NPT／production →
分析（歸零 DCD）→ SMD 拉離＋傘狀採樣（結合強度）→ 報告。中途可關掉視窗，重跑同一指令會續跑；GUI 的「開始／繼續」等同。

| 等級（`md` 區塊的 `"tier"`） | MD 長度 | RTX 4060 Laptop（CUDA）全流程 |
|---|---|---|
| `teaching`（範本預設） | 10 ns × 2 系統（apo、docked） | 約 3 小時（估算：約 330 ns/day，含傘狀採樣約 16.5 ns；未實測） |
| `classroom` | 2 ns × 2 系統 | **76.5 分鐘（2026-11-02 實測）** |

**上課建議先把 `trypsin.json` 裡的 `"tier": "teaching"` 改成 `"tier": "classroom"`**（記事本搜尋 `teaching`；範本只有這一處）。
classroom 的結合計算只示範流程，報告不輸出 ΔG°；teaching 只有 PMF 末端持平時才輸出 ΔG°（D-65），且一維 COM PMF 對埋入口袋的配體會高估，只比較趨勢。

## 6. 高通量篩選演練（可選，30 分鐘）
```cmd
%LOCALAPPDATA%\MD20\md20.cmd screen template --out compounds.xlsx     # 填 5–20 個化合物（smiles 或 PubChem CID）
%LOCALAPPDATA%\MD20\md20.cmd pipeline example --screen > screen.json  # 把 screen.library 指到 compounds.xlsx
%LOCALAPPDATA%\MD20\md20.cmd pipeline run screen.json --project screen_test
```
預期：下載 3D → 批次對接 → 停在「篩選：選擇化合物」閘門 → GUI「篩選」分頁勾選 → 按「開始／繼續」進入正式對接與 MD。

## 7. 回報什麼（讓筆電成為測試環境）
1. `docs/COMPATIBILITY.md` 加一列（步驟 2）。
2. 真實案例跑完後，`文件\MD20_Projects\first_case\...\runs\<run>\report.html` 與 `analysis/production_centered.dcd` 在 VMD 打開：蛋白是否在盒中央、配體是否在口袋。
3. 任何 NEEDS_HUMAN 閘門的文字（這些是通則的測試樣本，不是要針對這台機器修）。
4. 跑不動的地方：把終端機最後 50 行貼給開發 session，附 `md20.cmd doctor --no-benchmark` 的輸出。

## 開發者模式
從 git clone 執行 `installer\install.ps1` 時是 `pip install -e .`（editable）：改 repo 裡的程式，`md20.cmd` 立刻生效，不用重裝。
（Release ZIP 的 `Install-MD20.cmd` 則把程式複製到 `%LOCALAPPDATA%\MD20\app`。）`git pull` 後若 `environment/*.yml` 有變，重跑一次安裝器即可（環境存在時只補套件）。
