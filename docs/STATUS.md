# MD20 單機教學版 — 狀態報告（2026-11-01，第二個 session）

本檔誠實分成三級:**(A) 真實跑過並通過** /（B）**寫好、靠 CI 驗證** /（C）**已知限制與未完成**。
原則:寧可標「未驗證」，不誇大。每次 push 後，CI 會把各 OS 的測試結果貼到該 commit 的留言。

CI 依據(`fstcch-cmd/md20-workstation`):
- **L01 修正（a72ba6b）**:openmm-stack macOS 91 passed、Windows OpenCL 89 passed;Ubuntu 重測見 commit 留言（UBUNTU_A72）。
- **第二個 session 的新功能（WP5/WP9/金屬/WP13/誤差/replica）**:最新 commit 的 CI 結果見留言（NEW_RUN）。
- 測試函式:133 個(pure-python 部分本地全過)。

---

## A. 真實執行並通過

### A1. 無 OpenMM 也能跑(pure-python;CI 6 平台 + 本地)
| 模組 | 測試檔 | 重點 |
|---|---|---|
| chunk 引擎 | test_engine_fake | 分段封存/續跑、損壞 chunk 丟棄、watchdog、GPU context 重建、裝置反覆出錯→NEEDS_HUMAN |
| build 閘門 | test_build_gates | 壞 PDB 分類、loop、serial 溢位、口袋質子化審查(PROPKA) |
| docking 推薦 | test_docking_pure | 保守推薦、無合格候選→不推薦、口袋體積、同號電荷、redocking 自檢 |
| **短 MD 篩 pose(WP5)** | test_pose_screen | 候選挑選(推薦 + 每個其他 cluster)、穩定判定(後段 RMSD、接觸保留)、三態決策、暫停續跑快取、人工選擇不被覆寫 |
| **多配體結合(WP9)** | test_multi_binding | 拉離路徑閘門、ΔΔ 比較(ΔΔG° 只在全部有 ΔG° 時;< 2σ 不可區分)、共存效應、docked_multi 每個配體各自拉離、**bootstrap σ**、**replica 彙總與 research tier 以實際完成數判定** |
| **金屬** | test_metal | 配位位點辨識、bonded 計畫(鍵/角/CYM/HID/HIE)、擋關情境(< 3 配位、配體配位、His 雙氮)、policy 優先序、二硫鍵不被誤判為 CYM |
| **GUI 檢視(WP13)** | test_gui_views、test_gui_logic | 閘門卡片、時間軸、即時曲線、3D 場景;**離線 3D viewer 在 headless Chromium 實際繪圖且無 JS 錯誤**(含互作/表面切換);pose 表顯示短 MD 結果 |
| **閘門一鍵決定** | test_gate_actions | 選項→設定修補(structure_override、metal_policy、human_choices、box、skip_redock、CPP、peptide_policy);需理由的選項必填;寫回 config.json、記 human 決策、自該步驟起失效重跑;**沒實作的選項不給按鈕、閘門維持擋關**(受體長 loop/未知殘基等) |
| **3D 互作標示** | test_gui_views | 逐幀幾何互作(氫鍵候選 N/O ≤3.5 Å 未檢查角度、疏水 C–C ≤4.0 Å、配體–金屬 ≤2.8 Å)+ 殘基佔有率表;vdW 球表面近似 |
| 工作流程閘門 | test_workflow_gates | 共晶盒必做 redocking、盲對接需同意、結合計算加大 padding、**binding 讀取組裝後原子索引(L01 迴歸)** |
| 胜肽/CPP、結構可信度、續跑/鎖、資源模式、PMF/採樣、專案/佇列/報告/doctor/stamp | 各檔 | 同前版 |

### A2. 真實 OpenMM + Vina(CI openmm-stack)
| 測試檔 | 內容 | 狀態 |
|---|---|---|
| test_openmm_integration | 平台選擇、HMR、benchmark、doctor | 三平台綠(a72ba6b:mac/win) |
| test_real_case_integration | 3PTB 建模 + 短 MD;胜肽 | 同上 |
| test_docking_integration | 苯甲脒 redocking RMSD<2Å;多配體 | 同上 |
| test_binding_integration | NaCl PMF;水盒過小擋關;**拉離路徑被擋(WP9)** | 見 B |
| test_workflow_integration | 3PTB 全流程(含 binding);**短 MD 篩 pose(WP5)** | Ubuntu 重測,見 B |
| test_metal_integration | **CA II(3KS3)Zn–His3 鍵結模型**:建模、互變異構體、力項、最小化+MD 後鍵長維持 | Ubuntu 重測,見 B |
| test_gui_server | **啟動 `md20 gui` 並請求每個頁面與 /viewer** | 有 NiceGUI 的 CI 環境 |

### A3. 使用者實機(先前回報)
- Windows 10 + GTX 1060 → OpenCL,約 200 ns/day。
- HCC Lab 戳記端到端驗證:私鑰可解開 demo 輸出的加密溯源。

---

## B. 寫好、靠 CI 驗證(開發容器裝不了 OpenMM/NiceGUI,也連不到 PyPI/npm/RCSB)
- 第二個 session 加入的真實路徑測試(上表粗體)以最新 commit 的 CI 留言為準;若某項紅,留言含失敗 log,會在下一個 commit 修正並更新本檔。
- Ubuntu `MD20_HEAVY=1` 另跑兩篇論文的真實對接重現,結果以 JSON 貼到 commit 留言。

---

## C. 已知限制與未完成(誠實交代)

### C1. 論文驗證案例(教學背景用)
- **hsieh2024**(NF-κB RELA,六配體同時對接):論文標 PDB 1VKF,但 1VKF 是 *Thermotoga* 蛋白;系統判定正解為 **1VKX**。
- **hsieh2025**(Keap1-BTB 4CXT,胜肽 GGGGGKP):胞內標靶但淨電荷 +1,**CPP 閘門擋下並給替代設計**;「covalent bonding」實為凡得瓦接觸;盒子比整個 domain 還大(等同盲對接)。
目的是示範把關流程,不是逐位重現論文數字。

### C2. 刻意簡化或未做
- **短 MD 篩 pose**只排除會散開的 pose,不以短 MD 排名結合強度;非 research tier 預設關閉。
- **金屬鍵結模型**是晶體幾何的諧和鍵/角(電荷沿用力場),**不是** MCPB.py/ZAFF 擬合參數;配體直接配位金屬、少於 3 個蛋白配位原子一律 NEEDS_HUMAN。配位水被移除(位置開放,報告標註)。
- **多配體 PMF**:共存效應是「單獨 vs 共同口袋」的趨勢比較,不是封閉的熱力學循環;拉離路徑被另一配體擋住時不計算。
- **誤差**:σ 為 bootstrap(每個重抽樣 PMF 重算 ΔPMF/ΔG°)與 replica 標準誤取大者;不含力場誤差。
- **ΔG°**:一維 COM 距離 PMF + 徑向積分,未做方向/構形限制校正;classroom 不輸出;research 需 ≥3 個**實際完成**的 replica + 半段收斂。
- **3D viewer** 是自寫的 Canvas 2D(離線、無 WebGL):球棍 + Cα 骨架 + 口袋殘基,可旋轉/縮放/播放軌跡;互作為**純距離準則**(氫鍵不檢查角度,不是能量分解);「表面」是口袋原子 vdW 球近似,**不是**溶劑可及表面;沒有卡通。
- **GUI 閘門一鍵決定**只涵蓋程式真的會執行的選項;換結構、改序列、MCPB.py/QM 參數、補長 loop 等仍需在程式外處理(卡片列為「需要在程式外處理」)。
- **受體閘門的 human_choices**(修正):先前任何選擇都會讓閘門轉為已處理,但長 loop/未知殘基/重複原子名的選項並未實作(例如長 loop 仍被丟棄→主鏈斷裂);現在只接受 hetero groups 的移除/保留,其他選擇維持 NEEDS_HUMAN 並說明原因。「保留為參考配體」改為**不**留在 MD 受體中。
- **PROPKA** 只審查/提示,不自動改質子化。

### C3. 平台
- AMD GPU 走 OpenCL;Apple Silicon 走 CPU/OpenCL。
- Vina:Windows 無 python bindings 時用官方執行檔(`md20 setup-vina`)。

---

**一句話**:docking→MD→結合自由能的核心與把關閘門、短 MD 篩 pose、多配體各自 PMF(含誤差與 replica)、金屬 policy/幾何鍵結模型、GUI 閘門/時間軸/即時曲線/離線 3D 都已實作並有測試;真實 OpenMM 路徑的最終綠燈以 CI 留言為準。
