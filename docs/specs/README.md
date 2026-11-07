# MD20 開發規格與構想（供外部審查）

本資料夾是 MD20 單機教學版各子系統的**規格與設計理由**（狀態更新至 2026-11-03、v0.1.0a3）。寫給要審查設計的人（或更強的模型）：每份文件都說明
「要解決什麼問題 → 採用的原理 → 具體演算法與參數 → 目前狀態與證據 → 已知限制 → 想請審查者回答的問題」。

狀態標記：
- **[已驗證]** 已實作，CI 在真實 OpenMM/Vina 上跑過且通過（註明 commit）。
- **[已實作・待 CI]** 已實作且有純 Python 測試，真實引擎路徑尚待 CI。
- **[設計中]** 只有設計，尚未實作；最適合在實作前審查。

| 文件 | 範圍 | 狀態 |
|---|---|---|
| [umbrella_adaptive.md](umbrella_adaptive.md) | 傘狀採樣智慧補窗（由粗到細）、每 window 各自的 k、即時覆蓋圖、手動補採樣；PMF 涵蓋與持平（D-62、D-65） ；D-101 SMD 力曲線預先規劃、即時斷點提示 | 已驗證（heavy workflow，c868014；筆電實跑） |
| [restraints_freeze_truncation.md](restraints_freeze_truncation.md) | 分階段約束策略、凍結選項、口袋截斷模型、資源估算 | 分組約束已驗證（81b72d9）；智慧建議已實作・純 Python（D-118，待 CI）；凍結／截斷**設計中** |
| [implicit_solvent.md](implicit_solvent.md) | 隱式溶劑 GBn2：組裝、protocol、閘門（金屬、結合計算擋下） | 已驗證（81b72d9 起） |
| [metal_sites.md](metal_sites.md) | 金屬 policy、幾何鍵結模型（含金屬中心與經金屬的 1-3/1-4 修正）、擬合參數（QM Hessian／MCPB.py／JSON）、QM 小模型輸入 | 部分已驗證・鋅配位 heavy metal 自 c4b5de6 起綠，但平均鍵長在 0.3 Å 臨界（D-32／D-34） |
| [gate_actions.md](gate_actions.md) | 三態閘門、GUI 一鍵決定、選項→設定修補、失效重跑 | 已驗證（GUI 伺服器測試）|
| [viewer_interactions.md](viewer_interactions.md) | 離線 3D viewer、幾何互作標示、vdW 表面 | 已實作・純 Python 驗證（Chromium 繪圖測試在 CI 恆跳過，未驗證） |
| [drivers.md](drivers.md) | 顯示卡驅動偵測→判定→一鍵下載官方驅動（不自動安裝）；`-Cuda` 不動驅動的替代路 | 已實作・筆電 `drivers plan` 實測正常，下載未在真機用過 |
| [solvent_box.md](solvent_box.md) | 水盒：菱形十二面體、tier padding（0.8／1.0）、下限閘門、離子強度可調；**D-99 更正 padding 意義（只加一次＝溶質到影像距離）與 SMD 案例的盒子大小** | 已驗證（全流程 CI＋筆電）；D-99 待 CI |
| [pbc_centering.md](pbc_centering.md) | 週期邊界歸零：蛋白鏈＋bonded 金屬為錨、配體／胜肽折回、歸零 DCD 輸出、視覺性解離閘門 | 已驗證（全流程 CI＋筆電） |
| [hts_screen.md](hts_screen.md) | 高通量前期篩選：Excel/CSV 化合物庫 → 自動下載 3D → 批次快速對接 → 排名圖 → 勾選進入正式對接/MD | 已驗證（`test_screen_integration` 三 OS，1634916 起含 Windows） |
| [ci_validation.md](ci_validation.md) | CI 架構、重測、論文對接重現、hsieh2024 不可重現分析、這幾輪抓到的 bug | 進行中 |
| [binding_funnel_restraints.md](binding_funnel_restraints.md) | 結合自由能的漏斗約束與標準態校正：沿拉離軸投影 CV、圓錐＋圓柱側向約束、解析 K_b；筆電 3PTB 證據（一維距離 PMF 高估 3 倍以上） | **設計中**（a3 不含；請審查 §5） |
| [analysis_toolbox.md](analysis_toolbox.md) | 軌跡分析工具箱：tICA、MSM（附資格）、側鏈氫鍵網路、水合位點（D-105） | 已實作・待 CI |
| [smd_contacts.md](smd_contacts.md) | SMD 拉離路徑上的接觸釋放：稀疏溶質座標、釋放點、峰值時斷開的接觸、報告圖與表（D-116，F13） | 已實作・待 CI |
| [gui_stability.md](gui_stability.md) | GUI 穩定性：計算獨立子程序、狀態與進度從檔案讀回、GUI 重開接回（D-103） | 已實作・待 CI |
| [gui_v2.md](gui_v2.md) | GUI v2：四種模式、教學頁、依個案建議參數、雙語、進 MD 前確認 | 已實作・隨 v0.1.0a3 發行（CI 渲染；互動部分筆電確認） |
| [multi_ligand.md](multi_ligand.md) | 多配體同時對接進 MD：穿環／重疊／漂浮檢查、剛體微調、軟核鬆弛、協同自由能熱力學循環 | 已驗證（CI openmm-stack；D-60、D-61、D-64） |
| [analysis_cache.md](analysis_cache.md) | 分析解析度（來源／有效節奏、stride、串流事件、子樣本與敏感度）與分析快取指紋（輸入／版本／門檻、重用決定、原子重算與舊結果保存）（D-135，R3＋R4） | 已實作・純 Python 驗證（真實 mdtraj 路徑待 CI） |
| [master_iteration_2026-11-07.md](master_iteration_2026-11-07.md) | 整合規格複核：A1–A12 逐項判定、F01–F19 盤點、P0 兩批增量（評估／比較資格、replica 語意、結構限制、決策分流程、互作化學、動態接觸、配體狀態、互作持續性）、驗收對照與後續計畫 | 已實作・純 Python 驗證（D-95/96/97；真實引擎路徑待 CI） |
| [assessment.md](assessment.md) | 統一科學評估（D-134、R2）：執行狀態／診斷／說法資格／比較資格分開；`claim_status` 版本化紀錄；證據矩陣、圖說、摘要、比較、GUI 讀同一份；舊資料待重新分析；override 只記錄 | 已實作・純 Python 驗證（真實引擎路徑待 CI） |
| [report_language.md](report_language.md) | 報告用語規範與圖表 F1–F42：每種圖的怎麼讀、門檻與中英文句型 | 已實作（`figure_text.py`，測試檢查一致） |
| [membrane.md](membrane.md) | 膜系統：膜蛋白、膜表面接觸、純膜；定向、建膜、膜專用流程、分析 | **部分實作，未在真實引擎驗證**（D-80） |
| [structure_prediction.md](structure_prediction.md) | 輸入序列一鍵摺疊（OmegaFold、ESMFold、Boltz-2、ColabFold、上傳）與 pLDDT 閘門 | **設計中**（D-80） |
| [long_timescale.md](long_timescale.md) | 微秒級以上：全原子長時間模擬的儲存與續跑、粗粒化 Martini 3 | **設計中**（D-80） |
| [vina_cpu_use.md](vina_cpu_use.md) | Vina 執行檔的 CPU 使用：平行度上限、資源模式→--cpu／優先權／Windows QoS、每次執行的實際執行緒量測 | 已實作・待 Windows CI 與筆電實測 |
| [REVIEW_QUESTIONS.md](../archive/specs/REVIEW_QUESTIONS.md)（已封存） | 彙整：最希望審查者挑戰的設計決定 | — |
| [REVIEW_ANSWERS_2026-11-01.md](../archive/specs/REVIEW_ANSWERS_2026-11-01.md)（已封存） | **會診結果**：每個審查問題的回答、各規格沒寫到的科學缺口、下一個 session 的優先順序 | 待採納 |
| ../archive/specs/docking.md、gui.md | **已被取代**的第一個 session 規格（模組名與頁面結構都和現況不符）；現況見 ../WORKFLOW.md、hts_screen.md、gate_actions.md | 歷史 |

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
| `report_language.md` | 報告用語規範：每張圖的通用說明（圖說、如何判讀、情境句型與門檻；D-54） |
| `multi_ligand.md` | 多配體同時對接 → MD：穿環、重疊、漂浮的檢查與處置順序、力場一致性、報告版型（D-60） |
| [figures.md](figures.md) | 自動產圖規則：時間軸、圖例在圖外、每條線命名、顏色一致、多系列改小圖、細線＋移動平均（D-89） | 已實作・純 Python 與繪圖測試 |
| [licensing.md](licensing.md) | 簽章授權（第 2–3 層）：授權檔格式 v1／v2、機器碼、期限、閘門清單（擋／不擋）、功能閘門與評估版浮水印、輸出授權編號、簽章撤銷清單、不可由外部關閉、誠實限制（D-125、D-128）；md20 只留驗證、簽發端在私人 repo、格式測試向量 v1／v2（D-127） | 已實作・純 Python 測試（Windows 工具與 GUI 卡片待真機／CI） |
| [supply_chain.md](supply_chain.md) | 外部執行檔與環境版本：Vina 單一釘選版＋sha256 驗證、執行檔身分記錄；micromamba／conda 鎖版待做（D-114，REVIEW #19） | Vina 已實作・純 Python 測試 |
| [claims_audit.md](claims_audit.md) | 宣稱稽核（R6）：PMF／ΔG°／共存的區分、Jacobian 與標準態現況、進階描述子與機制文字改為有界觀察（D-138） | 文字已改；A8 參考態待授權 |
| [replicas.md](replicas.md) | 獨立重複：每個分析是否需要重複、條數取最大值（3）、報告如何呈現跨重複不確定性、開始時告知使用者（D-129）；重複計畫與告知（D-131） | 規格；§3–§5 已實作，待 CI；§7 每條重複分析與跨重複彙總（D-130 重做）已實作，待 CI |
