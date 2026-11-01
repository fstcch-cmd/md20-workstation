# MD20 單機教學版 — 狀態報告（2026-11-01）

本檔誠實分成三級:**(A) 真實跑過並通過** /（B）**寫好、靠 CI 驗證** /（C）**已知限制與未完成**。
原則:寧可標「未驗證」，不誇大。每次 push 後，CI 會把各 OS 的測試結果貼到該 commit 的留言。

當前 CI(commit b20ff7d/0d9dfb1,`fstcch-cmd/md20-workstation`):
- **pure-python 工作(Windows / macOS / Linux × Py3.11/3.12,共 6 個):全綠。**
- **openmm-stack(真實 OpenMM + Vina):Windows OpenCL 綠**(使用者主力平台);macOS、Ubuntu(含 `MD20_HEAVY=1` 重測)撰寫此檔時仍在跑,結果見 commit 留言。
- 測試總數:91 個測試函式(含 2 篇論文驗證案例)。

---

## A. 真實執行並通過

### A1. 無 OpenMM 也能跑(pure-python,6 平台 CI 全綠)
| 模組 | 測試檔 | 重點 |
|---|---|---|
| chunk 引擎 | test_engine_fake（9） | 分段封存/續跑、損壞 chunk 丟棄、identity 不符拒絕、watchdog dt 減半升級、**GPU context 重建**、**裝置反覆出錯→NEEDS_HUMAN** |
| build 閘門 | test_build_gates（9） | 壞 PDB 分類、loop 判定、serial 溢位、**口袋質子化審查(PROPKA)** |
| docking 推薦邏輯 | test_docking_pure（10） | 保守推薦、**無合格候選→不推薦**、口袋體積過小、同號電荷、redocking 自檢擋關 |
| 胜肽/CPP | test_peptide（7） | 序列模板、capped 端點、CPP 閘門、**無法穿膜時給替代設計(GKP/KP/富集/載體)+外部預測工具** |
| 結構可信度 | test_structure_gate（5） | 解析度/R-free/B-factor/occupancy/組裝、**口袋金屬閘門** |
| 工作流程閘門 | test_workflow_gates（5） | 共晶盒必做 redocking、盲對接需同意、無推薦擋 pose 選擇、結合計算自動加大 padding |
| 續跑/鎖 | test_resume（3） | owner lock、死 PID stale 接手、工作流程探索 |
| 資源模式 | test_resources（3） | background/balanced/full 執行緒數、RAM/GPU 溫度守門、GPU duty cycle |
| PMF/採樣 | test_sampling（5） | window 規劃、WHAM 還原、gap 偵測 |
| 專案/佇列/報告/doctor/GUI/stamp | 各檔 | 檔案庫、replica 彙總、暫停策略、HTML 報告、tier 建議、GUI 邏輯、**HCC Lab 戳記(可見+隱藏+擁有者加密)** |

### A2. 真實 OpenMM + Vina(CI openmm-stack;Windows 已綠)
| 測試檔 | 內容 |
|---|---|
| test_openmm_integration（4） | 平台選擇、HMR、benchmark、doctor |
| test_real_case_integration（2） | 3PTB 真實建模 + 短 MD;胜肽案例 |
| test_docking_integration（2） | 苯甲脒 redocking RMSD<2Å;多配體 simultaneous(遵守無候選規則) |
| test_binding_integration（2） | NaCl PMF(Jacobian 校正、auto-refine、resume);**水盒過小擋關** |
| test_workflow_integration（1） | 3PTB 全流程 apo+docked→分析→binding→報告,且可重入 |

### A3. 使用者實機(先前回報)
- Windows 10 + GTX 1060 → OpenCL,約 200 ns/day;當時 28 個本地測試通過。
- HCC Lab 戳記端到端驗證:私鑰可解開 demo 輸出的加密溯源。

---

## B. 寫好、靠 CI 驗證(需要重環境,本地沙盒無法裝)
- `MD20_HEAVY=1` 的 Ubuntu 工作額外跑**兩篇論文的真實對接重現**(見 C 下方),結果以 JSON 貼到 commit 留言。
- openmm-stack 的 macOS/Ubuntu 結果每次 push 由 CI 回報;若某 OS 紅,留言含失敗 log。

---

## C. 已知限制與未完成(誠實交代)

### C1. 論文驗證案例(教學背景用)
兩個案例以 `md20 validate <case>` 產生設定。目的是**示範把關流程**,不是逐位重現論文數字(exhaustiveness/質子化/亂數種子未公開)。
- **hsieh2024**(NF-κB RELA,六配體同時對接):論文標 PDB 1VKF,但 1VKF 其實是 *Thermotoga* 甘油操縱子蛋白;系統以「殘基是否存在」判定正解為 **1VKX**。這正是結構可信度閘門要抓的錯。
- **hsieh2025**(Keap1-BTB 4CXT,胜肽 GGGGGKP):胞內標靶但胜肽淨電荷僅 +1,**CPP 閘門擋下並給替代設計**;論文稱的「covalent bonding」實為凡得瓦接觸;其盒子比整個 domain 還大(等同盲對接)。

### C2. 尚未做或刻意簡化
- **WP5**(choose_poses 前做短 MD 篩 pose):未實作;目前以對接保守推薦 + 建模短 MD 驗證替代。
- **WP9**(多配體各自的 PMF / ΔΔG):binding 目前一次一個配體;多配體共同 PMF 未實作。
- **WP13 GUI**:離線 3D viewer、即時曲線、閘門卡片、時間軸尚未做;GUI 目前為表單 + 檔案瀏覽 + 執行。
- **金屬**:僅有「口袋金屬閘門」提示與 `metal_policy`(保留非鍵結/移除);未做鍵結金屬(bonded model)參數化。
- **PROPKA**:只做口袋質子化**審查/提示**,不自動改變質子化狀態(避免未經同意更動化學)。
- ΔG° 的 tier 限制:classroom 不輸出絕對 ΔG°;research 要 ≥3 replica + 半段收斂,否則只給 ΔPMF。

### C3. 平台
- AMD GPU 走 OpenCL(非 HIP,除非該機有 ROCm OpenMM build);Apple Silicon 走 CPU/OpenCL。
- Vina:Windows 無 python bindings 時用官方執行檔(`md20 setup-vina` 下載)。

---

**一句話**:核心引擎、建模/對接/結合的把關閘門、戳記、兩篇論文案例都已就緒且(pure-python)6 平台 CI 全綠,真實 OpenMM 路徑 Windows 已綠;未完成的是 GUI 視覺化、多配體 PMF、短 MD 篩 pose 與鍵結金屬。
