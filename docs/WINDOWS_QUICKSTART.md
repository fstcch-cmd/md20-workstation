# Windows 快速上手（獨顯筆電當測試機）

目標：30 分鐘內在你的筆電上裝好、確認 GPU 被用到、跑完一個真實案例，並把結果回報到 repo，讓這台筆電成為正式的測試環境。
每一步都寫「預期看到什麼」；沒看到就停下來，把畫面文字貼到 `docs/COMPATIBILITY.md` 或告訴開發 session。

## 0. 前置（5 分鐘）
- Windows 10/11，可用磁碟 ≥ 8 GB（環境約 6 GB；`-Root D:\MD20` 可改裝到其他磁碟）。
- NVIDIA 筆電：先更新驅動（GeForce Experience 或官網），然後在 PowerShell 打 `nvidia-smi`，記下右上角 **CUDA Version**（≥ 11.8 才走 CUDA，否則自動改 OpenCL）。
- 安裝 [Git for Windows](https://git-scm.com/download/win)（或直接下載 repo ZIP 解壓）。

## 1. 安裝（10–20 分鐘，多半在下載）
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
- 403 下載 Vina → 之後重跑 `md20.cmd setup-vina`（GitHub API 限流）。

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
預期：平台階梯列出 CUDA → OpenCL → CPU，**選用的平台不是 CPU**，20 秒 benchmark 給出 ns/day（GTX 1060 約 200，RTX 3060 筆電約 400–600，純 CPU 約 5–15）。
把 doctor 輸出的「選用平台／裝置／ns/day／tier 建議」四行貼到 `docs/COMPATIBILITY.md` 的表格新增一列（日期、機器、OS、GPU/驅動、平台、ns/day）。

## 3. 不碰 OpenMM 的全流程演練（1 分鐘）
```cmd
%LOCALAPPDATA%\MD20\md20.cmd demo
```
預期：合成後端跑完 docking→MD→報告，印出報告路徑；開啟 HTML 看得到圖表、決策日誌、三態閘門。這一步證明安裝與報告鏈正常。

## 4. 圖形介面
雙擊桌面 **`MD20-GUI.cmd`** → 瀏覽器開 http://127.0.0.1:8020 。只有本機能連（預設 127.0.0.1）。

## 5. 第一個真實案例：胰蛋白酶＋苯甲脒（teaching tier，GPU 上約 1–3 小時）
```cmd
cd %USERPROFILE%\Desktop
%LOCALAPPDATA%\MD20\md20.cmd pipeline example > trypsin.json
%LOCALAPPDATA%\MD20\md20.cmd pipeline run trypsin.json --project 測試
```
預期：RCSB 下載 3PTB → 受體閘門 → 對接（redocking RMSD < 2 Å）→ pose 選擇 → 建模（十二面體盒、padding 0.8）→ 最小化／NVT／NPT／production →
分析（歸零 DCD）→ 報告。中途可關掉視窗，重跑同一指令會續跑；GUI 的「開始／繼續」等同。
**先改 `trypsin.json` 的 `"tier": "classroom"`（2 ns）可在 20–40 分鐘內看到完整結果。**

## 6. 高通量篩選演練（可選，30 分鐘）
```cmd
%LOCALAPPDATA%\MD20\md20.cmd screen template --out compounds.xlsx     # 填 5–20 個化合物（smiles 或 PubChem CID）
%LOCALAPPDATA%\MD20\md20.cmd pipeline example --screen > screen.json  # 把 screen.library 指到 compounds.xlsx
%LOCALAPPDATA%\MD20\md20.cmd pipeline run screen.json --project 篩選
```
預期：下載 3D → 批次對接 → 停在「篩選：選擇化合物」閘門 → GUI「篩選」分頁勾選 → 按「開始／繼續」進入正式對接與 MD。

## 7. 回報什麼（讓筆電成為測試環境）
1. `docs/COMPATIBILITY.md` 加一列（步驟 2）。
2. 真實案例跑完後，`專案\...\runs\<run>\report.html` 與 `analysis/production_centered.dcd` 在 VMD 打開：蛋白是否在盒中央、配體是否在口袋。
3. 任何 NEEDS_HUMAN 閘門的文字（這些是通則的測試樣本，不是要針對這台機器修）。
4. 跑不動的地方：把終端機最後 50 行貼給開發 session，附 `md20.cmd doctor --no-benchmark` 的輸出。

## 開發者模式
安裝器是 `pip install -e .`（editable）：改 repo 裡的程式，`md20.cmd` 立刻生效，不用重裝。`git pull` 後若 `environment/*.yml` 有變，重跑一次安裝器即可（環境存在時只補套件）。
