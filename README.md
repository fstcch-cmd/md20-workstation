# MD20 單機教學版工作站（開發中）

[![CI](https://github.com/fstcch-cmd/md20-workstation/actions/workflows/ci.yml/badge.svg)](https://github.com/fstcch-cmd/md20-workstation/actions/workflows/ci.yml)

> © HCC Lab, National Kaohsiung University of Science and Technology. All rights reserved.
> 本 repo 暫時公開僅供持續整合（CI）測試使用；未附授權，請勿重製、散布或用於其他用途。

> 接手開發看 [`docs/HANDOFF.md`](docs/HANDOFF.md);現況看 [`docs/STATUS.md`](docs/STATUS.md)。

Docking → 建模 → MD → 增強取樣，在學生自己的筆電上跑（Windows 優先；NVIDIA／AMD／內顯／純 CPU），
環境、拓撲、PDB 修復、驗收與圖表全部自動，每個自動決策都留下「為什麼」。

## 快速開始

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File installer\install.ps1      # 自動偵測 NVIDIA → cuda，否則 opencl
```
```bash
# macOS / Linux
bash installer/install.sh
```

安裝器內嵌 micromamba、建立 `md20` 環境、安裝套件並立即執行 `md20 doctor`。

```text
md20 gui                         # 圖形介面（瀏覽器）：建立流程、即時曲線、改選 pose、看報告
md20 pipeline example > my.json  # 全流程範本：docking → MD（apo/docked）→ SMD＋傘狀採樣 → 報告
md20 pipeline run my.json --project 課堂A
md20 doctor                      # 硬體／平台／套件診斷 + 20 秒 benchmark → ns/day 與 ETA
md20 project new 課堂A
md20 build --project 課堂A --case kinase --receptor 1ABC.pdb --ligand lig_ref.sdf --pose vina_pose.sdf
md20 run   --project 課堂A --case kinase_xxxxxx --tier classroom
md20 status --project 課堂A
md20 report --project 課堂A --case kinase_xxxxxx --bundle    # HTML 報告 + 可重現包
md20 queue add --project 課堂A --case kinase_xxxxxx --tier teaching --replicas 3
md20 queue run --project 課堂A --hours 22-7                   # 只在夜間跑；電池供電或建立 PAUSE 檔即暫停
md20 demo                        # 不需 OpenMM：用合成後端跑完整流程，產生圖表、決策日誌與報告
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
  sampling/   0913 `MDH` 函式庫（WHAM/MBAR/overlap/bootstrap）＋ window 規劃
  report/     自含 HTML 報告（方法段落自動產生）＋ 可重現包 ＋ workflow 總報告
  docking/    Vina independent／simultaneous、受體 PDBQT、Meeko 配體、pose 分析與推薦
  workflow.py 全流程協調（每步可續跑）
  gui/        NiceGUI 介面
  cli.py      命令列
tests/        26 個純 Python 測試（任何機器可跑）＋ OpenMM 整合測試（有 openmm 時自動啟用）
```

## 狀態（誠實分層）

見 `docs/STATUS.md`（驗證狀態）、`docs/WORKFLOW.md`（設定檔）、`docs/COMPATIBILITY.md`（硬體實測）、`docs/TEACHING.md`（課程對照）。
