# MD20 單機教學版工作站（開發中）

[![CI](https://github.com/fstcch-cmd/md20-workstation/actions/workflows/ci.yml/badge.svg)](https://github.com/fstcch-cmd/md20-workstation/actions/workflows/ci.yml)

> © HCC Lab, National Kaohsiung University of Science and Technology. All rights reserved.
> 本 repo 暫時公開，只供持續整合（CI）測試使用。沒有附授權，請勿重製、散布或用於其他用途。

> **最新版本：[v0.1.0a7](https://github.com/fstcch-cmd/md20-workstation/releases/tag/v0.1.0a7)**，2026-11-03 發行，含 Windows 與 macOS 安裝檔，是教學預覽版。
> 學生操作說明在 [`docs/students/WINDOWS.md`](docs/students/WINDOWS.md) 和 [`docs/students/MAC.md`](docs/students/MAC.md)，有繁中、English、日本語、한국어 四種版本。
> 測試機的安裝與回報看 [`docs/WINDOWS_QUICKSTART.md`](docs/WINDOWS_QUICKSTART.md)。接手開發看 [`docs/HANDOFF.md`](docs/HANDOFF.md)，現況看 [`docs/STATUS.md`](docs/STATUS.md)。

MD20 讓學生在自己的筆電上做完分子對接、系統建模、分子動力學與增強取樣。以 Windows 為優先，NVIDIA、AMD、內建顯示晶片或只有 CPU 都能跑。
環境安裝、拓撲、PDB 修復、驗收與圖表都自動完成，每個自動決定都會記下理由。

## 快速開始

**一般使用者（不需要 git）**：到 [Releases](https://github.com/fstcch-cmd/md20-workstation/releases) 下載最新版。
- Windows：下載 `MD20-Windows-<版本>.zip`，解壓縮後雙擊 `Install-MD20.cmd`。程式會裝到 `%LOCALAPPDATA%\MD20`，桌面會多一個 `MD20-GUI.cmd`。命令列是 `%LOCALAPPDATA%\MD20\md20.cmd`。
- macOS：下載 `MD20-macOS-<版本>.zip`，雙擊解壓縮，在終端機執行 `bash ~/Downloads/MD20-<版本>/Install-MD20.command`。程式會裝到 `~/MD20`，桌面會多一個 `MD20-GUI.command`。命令列是 `~/MD20/md20`。

**開發者（git clone）**：
```powershell
# Windows（PowerShell 5.1 即可）
powershell -ExecutionPolicy Bypass -File installer\install.ps1      # 有 NVIDIA 顯示卡時用 cuda，否則用 opencl
```
```bash
# macOS 或 Linux
bash installer/install.sh
```

安裝器內含 micromamba。它會建立 `md20` 環境、安裝套件、下載 Vina，最後執行一次 `md20 doctor`。舊版不刪除，會移到 `_to_delete`。
圖形介面在 http://127.0.0.1:8020 。首頁有四種模式：教學模式一（多種小分子）、教學模式二（胜肽）、快速模式和專業模式。
右上角有兩個選單。資源選單有「省資源：可同時寫報告」、「平衡（預設）」、「全速：電腦閒置時」三個選項，從下一個計算步驟起生效。語言選單有 English、繁體中文、日本語、한국어。
計算進行時，請不要關閉啟動 GUI 的黑色主控台視窗（macOS 是終端機視窗）。關掉它會一起結束計算。重新開啟後按「開始／繼續」，會從中斷的地方接著算。

```text
md20 gui                         # 圖形介面（瀏覽器）：四種模式、即時曲線、改選 pose、看報告
                                 #   預設只有本機能連（127.0.0.1）。教室要分享請加 --host 0.0.0.0，同一網路的人都能操作
md20 pipeline example > my.json  # 全流程範本：docking → MD（apo 與 docked）→ SMD 與傘狀採樣 → 報告
md20 pipeline run my.json --project classA   # 專案名稱請用英文字母和數字，中文名稱會被改成英數代碼的資料夾
md20 doctor                      # 診斷硬體、平台和套件，跑 20 秒 benchmark，估 ns/day 與完成時間
md20 --mode background pipeline run my.json --project classA   # 資源模式：background（省資源）、balanced（預設）或 full（全速）
md20 validate hsieh2024          # HCC Lab 論文的教學案例設定（hsieh2024 多配體，hsieh2025 胜肽）
md20 resume                      # 重開機或當機後，續跑所有未完成的流程
md20 project new classA
md20 build --project classA --case kinase --receptor 1ABC.pdb --ligand lig_ref.sdf --pose vina_pose.sdf
md20 run   --project classA --case kinase_xxxxxx --tier classroom
md20 status --project classA
md20 report --project classA --case kinase_xxxxxx --bundle    # HTML 報告和可重現包
md20 queue add --project classA --case kinase_xxxxxx --tier teaching --replicas 3
md20 queue run --project classA --hours 22-7                   # 只在夜間跑。改用電池或建立 PAUSE 檔時會暫停
md20 demo                        # 不需要 OpenMM，用合成後端跑完整流程，產生圖表、決策日誌與報告
md20 screen template             # 高通量篩選的化合物庫 Excel 範本（name 加上 smiles、pubchem_cid、inchikey、chembl_id、ccd 或 sdf 其中一欄）
md20 pipeline example --screen   # 含篩選的全流程範本：100–500 個化合物自動下載 3D → 快速對接 → 看圖勾選 → 正式對接 → MD
```

## 架構

```
md20/
  util/       跨平台路徑、原子寫檔、檔案鎖（Windows 用 msvcrt，POSIX 用 fcntl）、便宜指紋、決策日誌
  env/        Doctor：硬體探測、OpenMM 平台階梯 CUDA→HIP→OpenCL→CPU（真的建 Context）、benchmark
  project/    專案、case、run 的檔案庫，取代 Google Drive JSON 加 lease。階段由完成檔推斷
  build/      受體檢查與 PDBFixer 修復、配體參考與 pose 映射、參數階梯（OpenFF→GAFF2）、真空煙霧測試、
              Modeller 組裝、溶劑化、位置約束、三態閘門（PASS / AUTO_FIXED / NEEDS_HUMAN）
  engine/     可續跑的 chunk 引擎（自 v6.1 移植）。自癒 watchdog 遇到 NaN 或溫度失控時回滾、dt 減半再重試
              HMR、各 tier 的預設 protocol、驗收與自動延長。Backend 抽象層有 OpenMM 和 Fake 兩種
  analysis/   log 解析、驗收、自動圖表（PNG+SVG+plotly HTML）
  sampling/   0913 `MDH` 函式庫（WHAM、MBAR、overlap、bootstrap），window 規劃與智慧補窗、SMD、PMF 涵蓋與持平檢查
  report/     自含的 HTML 報告（方法段落自動產生）、可重現包、workflow 總報告
  docking/    Vina independent 與 simultaneous、受體 PDBQT、Meeko 配體、pose 分析與推薦。
              library.py 和 screen.py 負責高通量前期篩選：化合物庫下載、批次對接、排名與圖
  validation/ HCC Lab 論文教學案例（hsieh2024、hsieh2025）
  advisor.py  依個案建議參數與合理性檢查
  workflow.py 全流程協調（每步可續跑）
  gui/        NiceGUI 介面：四種模式、教學頁、四種語言
  cli.py      命令列
tests/        純 Python 測試（任何機器都能跑），以及 OpenMM 和 Vina 整合測試（有 openmm 時自動啟用，CI 在三個平台實際執行）
```

## 狀態

驗證狀態分三級，寫在 `docs/STATUS.md`。每個決定的理由與證據在 `docs/DECISIONS.md`。設定檔說明在 `docs/WORKFLOW.md`，硬體實測在 `docs/COMPATIBILITY.md`，課程對照在 `docs/TEACHING.md`。
