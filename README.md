# MD20 分子模擬教學工作站

[![CI](https://github.com/fstcch-cmd/md20-workstation/actions/workflows/ci.yml/badge.svg)](https://github.com/fstcch-cmd/md20-workstation/actions/workflows/ci.yml)

> © HCC Lab, National Kaohsiung University of Science and Technology. All rights reserved.
> 本 repo 暫時公開，只供持續整合（CI）測試使用。沒有附授權，請勿重製、散布或用於其他用途。

**最新版本 [v0.1.0a15](https://github.com/fstcch-cmd/md20-workstation/releases/tag/v0.1.0a15)**（2026-11-04，教學預覽版，Windows 與 macOS）

MD20 讓學生在自己的筆電上，從分子對接一路做到分子動力學與結合自由能，最後得到一份可以直接讀的報告。
安裝環境、修 PDB、建拓撲、平衡驗收、畫圖、寫方法段落都由程式完成。程式每做一個自動決定，都會記下理由；遇到需要人判斷的地方就停下來，列出可以選的做法。
以 Windows 為優先，NVIDIA、AMD、內建顯示晶片或只有 CPU 都能跑。介面與報告有繁體中文、English、日本語、한국어 四種語言。

## 安裝（學生用，不需要 git）

到 [Releases](https://github.com/fstcch-cmd/md20-workstation/releases) 下載最新版。需要約 8 GB 的磁碟空間與網路。

| | Windows | macOS |
|---|---|---|
| 下載 | `MD20-Windows-<版本>.zip`，右鍵「解壓縮全部」 | `MD20-macOS-<版本>.zip`，雙擊解壓縮 |
| 安裝 | 雙擊 `Install-MD20.cmd` | 終端機執行 `bash ~/Downloads/MD20-<版本>/Install-MD20.command` |
| 開啟介面 | 雙擊桌面的 `MD20-GUI.cmd` | 雙擊桌面的 `MD20-GUI.command` |
| 命令列 | `%LOCALAPPDATA%\MD20\md20.cmd` | `~/MD20/md20` |

安裝約 15 到 30 分鐘，最後會自動跑一次 `md20 doctor` 檢查顯示卡。介面在瀏覽器的 http://127.0.0.1:8020 打開。
計算進行時不要關掉那個黑色主控台視窗（macOS 是終端機視窗），關掉會一起結束計算。重新打開後按「開始或繼續」，會從中斷的地方接著算。

選用工具，只裝一次，各要數 GB：
- 胜肽摺疊（OmegaFold）：雙擊解壓資料夾裡的 `Install-Folding.cmd`（macOS 是 `Install-Folding.command`），或在介面「電腦狀態」頁按「一鍵安裝」。
- 粗粒化 Martini 3：在「電腦狀態」頁按「一鍵安裝」，或執行 `md20 setup-cg --yes`。會一起下載力場檔。

逐步說明在 [`docs/students/`](docs/students/)，四種語言各有 Windows 與 Mac 版。

## 可以做什麼

| 功能 | 說明 |
|---|---|
| 分子對接 | AutoDock Vina。一次對接一個配體，或多個配體同時放進同一個口袋。有晶體配體時先做 redocking 確認可信度 |
| 高通量前期篩選 | 從 Excel 或 CSV 化合物庫（100 到 500 個）自動下載 3D 結構，快速對接、畫排名圖，勾選要進入正式對接的化合物 |
| 分子動力學 | OpenMM。自動修受體、配體參數化（OpenFF，失敗時改用 GAFF2）、十二面體水盒、平衡驗收，失敗會自動延長或回滾重試 |
| 結合自由能 | SMD 拉離加傘狀採樣，WHAM 與 MBAR、bootstrap 誤差。可以只挑某個配體計算；做完報告後還能回來加做別的配體，或同一個配體多做幾次，報告會整合 |
| 胜肽 | 在配體欄直接貼序列。10 個殘基以上先預測結構再對接；預測信心太低會停下來問 |
| 膜系統 | 膜蛋白、胜肽或小分子在膜表面接觸（不穿膜）、純膜 |
| 長時間與粗粒化 | 全原子最長 10 µs，分段存檔、可續跑。Martini 3 粗粒化可以跑到微秒以上，報告標註為珠子層級 |
| 報告 | 單一 HTML 檔，每張圖都附「怎麼讀」與「這個專案看到什麼」，方法段落可以直接貼進論文 |

功能的驗證程度不一樣。哪些在真實引擎上跑過、哪些只有測試、哪些還沒做，都寫在 [`docs/STATUS.md`](docs/STATUS.md)。
膜、摺疊、粗粒化與長時間模擬是新功能，結果請當作初步。

## 圖形介面

首頁有四種模式：
- **教學模式一**：論文中的六個代謝物同時對接 NF-κB p65（hsieh2024）。
- **教學模式二**：甘胺酸豐富的胜肽對接 Keap1（hsieh2025）。
- **快速模式**：輸入受體和配體，選研究目標，其餘參數依個案建議。
- **專業模式**：每個參數都能改，改的同時檢查是否合理；膜、摺疊、長時間與粗粒化在這裡設定。

其他常用的地方：
- 首頁「專案資料夾」：指定專案要存在哪裡（例如空間較大的 D 槽），也可以直接打開別人給你的專案或流程資料夾。程式會記住這個選擇。
- 首頁「最近的流程」：列出存過的所有流程，可以搜尋。未完成的點進去按「開始或繼續」。
- 流程頁「結合自由能（SMD＋傘狀採樣）」：選配體計算、同一配體再做一次、重新整理報告。
- 右上角：資源模式（省資源、平衡、全速）與語言。

## 命令列

```text
md20 doctor                                  檢查硬體與套件，跑 20 秒 benchmark，估算 ns/day 與完成時間
md20 gui                                     打開圖形介面（只有本機能連；教室要分享才加 --host 0.0.0.0）
md20 pipeline example > my.json             產生全流程設定範本
md20 pipeline run my.json --project classA   跑全流程：對接、MD、結合自由能、報告（專案名稱用英文字母和數字）
md20 resume                                  重開機或當機後，續跑所有未完成的流程
md20 validate hsieh2024                      HCC Lab 論文的教學案例設定（hsieh2025 是胜肽）
md20 screen template                         高通量篩選的化合物庫 Excel 範本
md20 fold <序列>                             預測胜肽結構
md20 setup-fold --yes / md20 setup-cg --yes  安裝選用工具（不加 --yes 只列出會做的事）
md20 demo                                    不需要 OpenMM，用模擬後端跑一遍，產生圖、決策紀錄與報告
md20 --mode background pipeline run ...      省資源模式（background、balanced、full）
```

專案預設存在「文件」裡的 `MD20_Projects`。在介面指定過別的資料夾後，命令列也會用同一個；要臨時改用其他資料夾就加 `--dir <路徑>`。
設定檔每個欄位的意思在 [`docs/WORKFLOW.md`](docs/WORKFLOW.md)。

## 實測

MSI Cyborg 14 筆電（RTX 4060 Laptop 8 GB、Windows 11）：24k 原子水盒約 600 ns/day。胰蛋白酶加苯甲脒（3PTB）的 classroom 等級全流程，包含 apo 與複合物各 2 ns MD、SMD 與傘狀採樣，共 76.5 分鐘。
其他機器的紀錄在 [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md)。

使用時請留意：
- classroom 等級的結合自由能只用來示範流程，報告不輸出 ΔG°。要比較數值請用 teaching 以上的等級，並看報告裡的收斂檢查。
- 多配體系統中拉一個配體時，其他配體留在口袋裡，量到的是共存時的結合強度，不能直接和單獨結合比較。
- 預測的胜肽結構不是實驗結構，報告會這樣標註。

## 文件

| 文件 | 內容 |
|---|---|
| [`docs/students/`](docs/students/) | 學生安裝與操作步驟（四種語言） |
| [`docs/TEACHING.md`](docs/TEACHING.md) | 上課怎麼用：教學案例、可以帶學生討論的問題 |
| [`docs/STATUS.md`](docs/STATUS.md) | 每個版本的內容，以及驗證程度（跑過、只有測試、未完成） |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | 每項修改的理由、被否決的做法與證據 |
| [`docs/specs/`](docs/specs/) | 各子系統的規格，給審查者看 |
| [`docs/WORKFLOW.md`](docs/WORKFLOW.md) | 流程設定檔的欄位 |
| [`docs/WINDOWS_QUICKSTART.md`](docs/WINDOWS_QUICKSTART.md) | 測試機的安裝與回報 |
| [`docs/HANDOFF.md`](docs/HANDOFF.md) | 接手開發的人先讀這份 |

## 開發

```powershell
# Windows（PowerShell 5.1 即可）
powershell -ExecutionPolicy Bypass -File installer\install.ps1      # 有 NVIDIA 顯示卡用 -Gpu cuda，否則 -Gpu opencl
```
```bash
# macOS 或 Linux
bash installer/install.sh
pytest                                  # 沒有 OpenMM 時只跑純 Python 測試，整合測試自動跳過
```

安裝器內含 micromamba，會建立 `md20` 環境、安裝套件、下載 Vina。舊版不刪除，移到 `_to_delete`。

```
md20/
  env/        硬體偵測、OpenMM 平台選擇（CUDA、HIP、OpenCL、CPU，實際建 Context 確認）、benchmark
  project/    專案、case、run 的檔案庫
  build/      受體修復、配體參數化、組裝與溶劑化、膜、摺疊、粗粒化建模、三態閘門
  engine/     分段可續跑的模擬引擎；遇到 NaN 或溫度失控會回滾並減半時間步重試
  analysis/   軌跡分析、驗收、圖表
  sampling/   SMD、傘狀採樣、WHAM 與 MBAR、補窗與收斂檢查
  docking/    Vina、受體 PDBQT、Meeko、pose 分析、高通量篩選
  report/     HTML 報告、方法段落、圖說
  gui/        NiceGUI 介面
  workflow.py 全流程協調，每一步都能續跑
  cli.py      命令列
tests/        純 Python 測試在任何機器都能跑；OpenMM 與 Vina 的整合測試在 CI 的 Windows、macOS、Linux 上實際執行
tools/        GUI 截圖與瀏覽器點擊自我測試（gui_preview.py）等
```

開發規則：
- 每項修改的理由寫進 `docs/DECISIONS.md`，規格寫進 `docs/specs/`，和程式碼放在同一個 commit。
- 自動決定分三種狀態：通過、已自動修正、需要人決定。條件不足時寧可停下來，不猜。
- 每次 push 後，CI 會把各平台的測試結果貼在該 commit 的留言；被跳過的整合測試不算通過。

## English summary

MD20 is a teaching workstation for molecular docking, molecular dynamics and binding free energy on a student's own
laptop (Windows first; NVIDIA, AMD, integrated graphics or CPU only). It installs its own environment, repairs
structures, parametrises ligands, checks equilibration, draws the figures and writes a report in English, Traditional
Chinese, Japanese or Korean. Every automatic decision is logged with its reason, and the run stops with options when a
decision needs a person. Download the installer from
[Releases](https://github.com/fstcch-cmd/md20-workstation/releases); step-by-step guides are in
[`docs/students/`](docs/students/) (`WINDOWS.en.md`, `MAC.en.md`). What has been verified on real engines, and what has
not, is listed in [`docs/STATUS.md`](docs/STATUS.md).
