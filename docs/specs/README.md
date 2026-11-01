# MD20 開發規格與構想（供外部審查）

本資料夾是 MD20 單機教學版各子系統的**規格與設計理由**。寫給要審查設計的人（或更強的模型）：每份文件都說明
「要解決什麼問題 → 採用的原理 → 具體演算法與參數 → 目前狀態與證據 → 已知限制 → 想請審查者回答的問題」。

狀態標記：
- **[已驗證]** 已實作，CI 在真實 OpenMM/Vina 上跑過且通過（註明 commit）。
- **[已實作・待 CI]** 已實作且有純 Python 測試，真實引擎路徑尚待 CI。
- **[設計中]** 只有設計，尚未實作；最適合在實作前審查。

| 文件 | 範圍 | 狀態 |
|---|---|---|
| [umbrella_adaptive.md](umbrella_adaptive.md) | 傘狀採樣智慧補窗（由粗到細）、每 window 各自的 k、即時覆蓋圖、手動補採樣 | 已實作・待 CI |
| [restraints_freeze_truncation.md](restraints_freeze_truncation.md) | 分階段約束策略、凍結選項、口袋截斷模型、資源估算 | **設計中**（引擎掛鉤已加） |
| [implicit_solvent.md](implicit_solvent.md) | 隱式溶劑 GBn2：組裝、protocol、閘門（金屬、結合計算擋下） | 已實作・待 CI |
| [metal_sites.md](metal_sites.md) | 金屬 policy、幾何鍵結模型（含金屬中心與經金屬的 1-3/1-4 修正）、擬合參數（QM Hessian／MCPB.py／JSON）、QM 小模型輸入 | 部分已驗證・鋅配位仍待 CI（37bc6b1 那輪仍紅） |
| [gate_actions.md](gate_actions.md) | 三態閘門、GUI 一鍵決定、選項→設定修補、失效重跑 | 已驗證（GUI 伺服器測試）|
| [viewer_interactions.md](viewer_interactions.md) | 離線 3D viewer、幾何互作標示、vdW 表面 | 已實作・純 Python 驗證（Chromium 繪圖測試在 CI 恆跳過，未驗證） |
| [drivers.md](drivers.md) | 顯示卡驅動偵測→判定→一鍵下載官方驅動（不自動安裝）；`-Cuda` 不動驅動的替代路 | 已實作・查詢服務待真機 |
| [solvent_box.md](solvent_box.md) | 水盒：菱形十二面體、tier padding（0.8／1.0）、下限閘門、離子強度可調——算力不浪費在水與鹽 | 已實作・待 CI |
| [pbc_centering.md](pbc_centering.md) | 週期邊界歸零：蛋白鏈＋bonded 金屬為錨、配體／胜肽折回、歸零 DCD 輸出、視覺性解離閘門 | 已實作・待 CI |
| [hts_screen.md](hts_screen.md) | 高通量前期篩選：Excel/CSV 化合物庫 → 自動下載 3D → 批次快速對接 → 排名圖 → 勾選進入正式對接/MD | 已實作・待 CI |
| [ci_validation.md](ci_validation.md) | CI 架構、重測、論文對接重現、hsieh2024 不可重現分析、這幾輪抓到的 bug | 進行中 |
| [REVIEW_QUESTIONS.md](REVIEW_QUESTIONS.md) | 彙整：最希望審查者挑戰的設計決定 | — |
| [REVIEW_ANSWERS_2026-11-01.md](REVIEW_ANSWERS_2026-11-01.md) | **會診結果**：每個審查問題的回答、各規格沒寫到的科學缺口、下一個 session 的優先順序 | 待採納 |
| docking.md、gui.md | **已被取代**的第一個 session 規格（模組名與頁面結構都和現況不符）；現況見 ../WORKFLOW.md、hts_screen.md、gate_actions.md | 歷史 |

## 全專案共通原則（MD20_optimization_brief）
1. **不新增 phase/step**，只強化既有邏輯。
2. **三態閘門** PASS / AUTO_FIXED / NEEDS_HUMAN；每個自動決策寫 `DecisionLog`，`why` 用中文、寫給學生看。
3. **寧可擋也不要猜**：條件不足就 NEEDS_HUMAN 並給選項；「選了卻沒做」的選項不能存在。
4. **誠實**：`docs/STATUS.md` 分三級；報告與圖上標明近似（例如互作只看距離、表面是 vdW 球）。
5. 目標使用者：博士生、Windows 筆電（OpenCL/CPU 為主）、要能在一般硬體上跑完，並為進入藥廠做準備。

## 程式碼位置速查
- 傘狀採樣：`md20/sampling/adaptive.py`、`binding.py`、`pmf.py`、`_mdh_legacy.py`（WHAM/MBAR）
- 金屬：`md20/build/metal.py`、`metal_params.py`
- 約束／引擎：`md20/build/assemble.py`（`add_position_restraints`）、`md20/engine/protocol.py`、`chunks.py`、`runner.py`
- 閘門與 GUI：`md20/build/gates.py`、`md20/gui/actions.py`、`views.py`、`app.py`
- 驗證案例：`md20/validation/`、`tests/test_validation_papers.py`
