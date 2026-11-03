# MD20 單機教學版工作站（開發中）

[![CI](https://github.com/fstcch-cmd/md20-workstation/actions/workflows/ci.yml/badge.svg)](https://github.com/fstcch-cmd/md20-workstation/actions/workflows/ci.yml)

> © HCC Lab, National Kaohsiung University of Science and Technology. All rights reserved.
> 本 repo 暫時公開僅供持續整合（CI）測試使用；未附授權，請勿重製、散布或用於其他用途。

> **最新版本：[v0.1.0a3](https://github.com/fstcch-cmd/md20-workstation/releases/tag/v0.1.0a3)**（2026-11-03，Windows 與 macOS 安裝檔，教學預覽版）。
> 學生操作說明：[`docs/students/WINDOWS.md`](docs/students/WINDOWS.md)、[`docs/students/MAC.md`](docs/students/MAC.md)；
> 測試機安裝與回報：[`docs/WINDOWS_QUICKSTART.md`](docs/WINDOWS_QUICKSTART.md)；接手開發看 [`docs/HANDOFF.md`](docs/HANDOFF.md)；現況看 [`docs/STATUS.md`](docs/STATUS.md)。

Docking → 建模 → MD → 增強取樣，在學生自己的筆電上跑（Windows 優先；NVIDIA／AMD／內顯／純 CPU），
環境、拓撲、PDB 修復、驗收與圖表全部自動，每個自動決策都留下「為什麼」。

## 快速開始

**一般使用者（不需要 git）**：到 [Releases](https://github.com/fstcch-cmd/md20-workstation/releases) 下載最新版。
- Windows：`MD20-Windows-<版本>.zip` → 解壓縮 → 雙擊 **`Install-MD20.cmd`**。程式裝到 `%LOCALAPPDATA%\MD20`，桌面多一個 **`MD20-GUI.cmd`**，命令列為 `%LOCALAPPDATA%\MD20\md20.cmd`。
- macOS：`MD20-macOS-<版本>.zip` → 雙擊解壓 → 終端機執行 `bash ~/Downloads/MD20-<版本>/Install-MD20.command`。程式裝到 `~/MD20`，桌面多一個 **`MD20-GUI.command`**，命令列為 `~/MD20/md20`。

**開發者（git clone）**：
```powershell
# Windows（PowerShell 5.1 即可）
powershell -ExecutionPolicy Bypass -File installer\install.ps1      # 自動偵測 NVIDIA → cuda，否則 opencl
```
```bash
# macOS / Linux
bash installer/install.sh
```

安裝器內嵌 micromamba、建立 `md20` 環境、安裝套件、下載 Vina 並立即執行 `md20 doctor`；舊版不刪除，移到 `_to_delete`。
圖形介面在 http://127.0.0.1:8020 ：首頁有四種模式（教學模式一：多種小分子；教學模式二：胜肽；快速模式；專業模式），右上角有資源選單（省資源／平衡／全速，下一個計算步驟起生效）與語言選單（英文／繁體中文）。
計算進行中請勿關閉啟動 GUI 的黑色主控台（或終端機）視窗；關閉它會一併結束計算，重新開啟後按「開始／繼續」會從中斷處接續。

```text
md20 gui                         # 圖形介面（瀏覽器）：四種模式、即時曲線、改選 pose、看報告
                                 #   預設只本機可連（127.0.0.1）；教室要分享請加 --host 0.0.0.0（同網路任何人都能操作）
md20 pipeline example > my.json  # 全流程範本：docking → MD（apo/docked）→ SMD＋傘狀採樣 → 報告
md20 pipeline run my.json --project classA   # 專案名稱請用英數字（中文名稱會被改成「英數＋亂碼」資料夾）
md20 doctor                      # 硬體／平台／套件診斷 + 20 秒 benchmark → ns/day 與 ETA
md20 --mode background pipeline run my.json --project classA   # 資源模式：background（省資源）／balanced（預設）／full
md20 validate hsieh2024          # HCC Lab 論文教學案例設定（hsieh2024 多配體、hsieh2025 胜肽）
md20 resume                      # 重開機／當機後續跑所有未完成的流程
md20 project new classA
md20 build --project classA --case kinase --receptor 1ABC.pdb --ligand lig_ref.sdf --pose vina_pose.sdf
md20 run   --project classA --case kinase_xxxxxx --tier classroom
md20 status --project classA
md20 report --project classA --case kinase_xxxxxx --bundle    # HTML 報告 + 可重現包
md20 queue add --project classA --case kinase_xxxxxx --tier teaching --replicas 3
md20 queue run --project classA --hours 22-7                   # 只在夜間跑；電池供電或建立 PAUSE 檔即暫停
md20 demo                        # 不需 OpenMM：用合成後端跑完整流程，產生圖表、決策日誌與報告
md20 screen template             # 高通量篩選：化合物庫 Excel 範本（name + smiles/pubchem_cid/inchikey/chembl_id/ccd/sdf）
md20 pipeline example --screen   # 含篩選的全流程範本：100–500 個化合物自動下載 3D → 快速對接 → 看圖勾選 → 正式對接 → MD
```

## 架構

```
md20/
  util/       跨平台路徑、原子寫檔、檔案鎖（Windows msvcrt／POSIX fcntl）、便宜指紋、決策日誌
  env/        Doctor：硬體探測、OpenMM 平台階梯 CUDA→HIP→OpenCL→CPU（真的建 Context）、benchmark
  project/    專案／case／run 檔案庫（取代 Google Drive JSON + lease）；階段由完成檔推斷
  build/      受體檢查與 PDBFixer 修復、配體參考＋pose 映射、參數階梯（OpenFF→GAFF2）、真空煙霧測試、
              Modeller 組裝＋溶劑化＋位置約束、三態閘門（PASS / AUTO_FIXED / NEEDS_HUMAN）
  engine/     可續跑 chunk 引擎（自 v6.1 移植）＋ 自癒 watchdog（NaN／溫度失控 → 回滾、dt 減半、重試）
              ＋ HMR ＋ tier 預設 protocol ＋ 驗收與自動延長；Backend 抽象（OpenMM／Fake）
  analysis/   log 解析、驗收、自動圖表（PNG+SVG+plotly HTML）
  sampling/   0913 `MDH` 函式庫（WHAM/MBAR/overlap/bootstrap）＋ window 規劃與智慧補窗、SMD、PMF 涵蓋與持平檢查
  report/     自含 HTML 報告（英文／繁中；方法段落自動產生）＋ 可重現包 ＋ workflow 總報告
  docking/    Vina independent／simultaneous、受體 PDBQT、Meeko 配體、pose 分析與推薦；
              library.py／screen.py：高通量前期篩選（化合物庫下載、批次對接、排名與圖）
  validation/ HCC Lab 論文教學案例（hsieh2024、hsieh2025）
  advisor.py  依個案建議參數與合理性檢查
  workflow.py 全流程協調（每步可續跑）
  gui/        NiceGUI 介面（四種模式、教學頁、雙語）
  cli.py      命令列
tests/        純 Python 測試（任何機器可跑）＋ OpenMM／Vina 整合測試（有 openmm 時自動啟用；CI 三平台真跑）
```

## 狀態（誠實分層）

見 `docs/STATUS.md`（驗證狀態）、`docs/DECISIONS.md`（每個決定的理由與證據）、`docs/WORKFLOW.md`（設定檔）、`docs/COMPATIBILITY.md`（硬體實測）、`docs/TEACHING.md`（課程對照）。
