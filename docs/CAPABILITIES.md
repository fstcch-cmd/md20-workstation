# MD20 能力清單（Capability manifest）

> 由 `tools/capability_manifest.py --write` 從 `docs/capabilities.json` 產生，**不要手改**（`--check` 會擋下不同步）。
> 規格：`docs/specs/capabilities.md`。只寫現況；歷史紀錄在 `docs/STATUS.md` 與 `docs/DECISIONS.md`。

MD20 目前能力的單一機器可讀清單（R7，D-136）。只寫現況；歷史紀錄留在 docs/STATUS.md 與 docs/DECISIONS.md。docs/CAPABILITIES.md 由 tools/capability_manifest.py --write 產生，不要手改。

## 版本事實

- 套件版本（pyproject／`md20.__version__`）：`0.1.0a20.dev0`（開發中，未發行）
- 已發行的最新版本：**v0.1.0a17**；已發行共 16 版：v0.1.0a1, v0.1.0a2, v0.1.0a3, v0.1.0a4, v0.1.0a6, v0.1.0a7, v0.1.0a8, v0.1.0a9, v0.1.0a10, v0.1.0a11, v0.1.0a12, v0.1.0a13, v0.1.0a14, v0.1.0a15, v0.1.0a16, v0.1.0a17
- 從未發行：v0.1.0a5, v0.1.0a18, v0.1.0a19（發行說明草稿：docs/releases/v0.1.0a18.md, docs/releases/v0.1.0a19.md）
- 查證：gh api repos/fstcch-cmd/md20-workstation/releases（2026-11-07 查證：a1–a17 共 16 個 prerelease，無 a5、a18、a19；a17 tag 指向 8e2fc14ba8b54752aa8e02d0d2c7c72c807e0483）
- release-windows.yml 在推 tag（v*）時自動建立 prerelease；本清單與 R7 規格期間不得自動發行。

## 證據基準

- commit `580cbff`，CI run https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293
- 為什麼選它：2026-11-07 最後一輪在 main 上完整跑完的 CI（之後 650bc65 被取消、f3ecf71 的 Windows openmm-stack 當時仍在跑、58d81bc 當時排隊中）。
- 結果：14 個 job 成功、1 個失敗（共 15 個）：heavy[metal]（test_bonded_zinc_ca2）。openmm-stack Ubuntu 1002 passed／9 skipped／1 xfailed（另有獨立 CG 步驟 3 passed）、Windows 1003 passed／8 skipped／1 xfailed。
- 查證方式：gh api actions/runs/42374500293/jobs 與 commit 留言（單次查詢）；『程式在證據之後是否改過』用 git ls-tree 的檔案 blob 比對。
- 跳過的測試不算通過；各功能的 basis 只在對應測試未被跳過時才引用 CI 成功。
- 清單對應的樹：`0b66ade`（2026-11-07）。清單內容對應此 commit 的樹；CI 證據對應下方 evidence_baseline 的 commit，兩者不同時看各功能的 last_known_result.status（stale = 證據之後程式或測試有改過）。

## 五種狀態（彼此獨立，不得互相推論）

- **implemented**：yes｜partial｜no。程式存在；不代表有測試或有被驗證。
- **synthetic_tested**：yes｜no。有純 Python 單元測試、FakeBackend 或合成資料測試通過；不代表引擎或科學正確。
- **real_engine_tested**：yes｜partial｜failing｜no。在阻擋型 CI job（openmm-stack／heavy）用真實 OpenMM／Vina／RDKit／mdtraj 跑過測試；failing = 該測試目前失敗。不由合成測試推得。
- **scientifically_benchmarked**：none｜observed｜yes。observed = 只有非阻擋或診斷 job 的觀察（描述特定 protocol 下看到什麼，不構成資格）；yes = 對外部參考（實驗或文獻）以阻擋型 job 比對並通過。目前沒有任何功能是 yes。
- **released_installer**：已發行的哪個 prerelease 含此功能；否則 'unreleased (main only)'。'(older code)' = 該版含舊版程式，main 的差異未發行。
- **last_known_result.status**：pass｜fail｜partial｜stale｜unverified。stale = 證據 commit 當時通過，但之後實作或測試檔改過，現況沒有 CI 結果；unverified = 沒有 CI 結果。
- **rule**：五種狀態彼此獨立，不得由一個推另一個（例：合成測試通過 ≠ 真實引擎測過；真實引擎通過 ≠ 科學 benchmark；main 通過 ≠ 已進安裝程式）。tools/capability_manifest.py --check 會擋下最明顯的矛盾。

測試類型：`unit` = 純 Python 小輸入邏輯測試；`synthetic` = 合成資料、FakeBackend 或假網路；證明邏輯，不證明真實系統；`real_engine` = 真實 OpenMM／Vina／RDKit／mdtraj 或真實安裝程式（CPU 平台；runner 沒有 GPU）；`gui` = GUI 伺服器或瀏覽器檢查；只證明介面，不證明計算；`diagnostic` = 蒐集資料的診斷，結束碼不代表科學通過；`benchmark` = 對外部參考的比對；縮減版或非阻擋時只算 observed

## CI job 分類（誰能當資格、誰不能）

| job | 類別 | 阻擋 | 可支持的狀態 | 580cbff 結果 | 說明 |
|---|---|---|---|---|---|
| `ci.yml:pure-python` | unit | 是 | synthetic_tested | success（6/6：三 OS × Python 3.11／3.12） | 不含化學引擎；另跑 capability manifest 檢查（D-136） |
| `ci.yml:openmm-stack` | real_engine | 是 | synthetic_tested, real_engine_tested | success（Windows／macOS／Ubuntu） | 完整套件，CPU 平台；Ubuntu 另有獨立 CG 步驟。看 skip 數：跳過不算通過。 |
| `ci.yml:heavy` | real_engine | 是 | real_engine_tested | workflow 成功、pose-screen 成功、metal 失敗 | Ubuntu，MD20_HEAVY=1 |
| `ci.yml:paper-docking` | benchmark | **否** | —（不能當資格） | success（continue-on-error；結果不阻擋） | 兩篇論文對接重現，縮減搜尋（exhaustiveness 8），斷言只檢查一致性。綠燈不是資格；最多支持 scientifically_benchmarked=observed。job 名稱已標 BENCHMARK, non-blocking - not qualification。 |
| `ci.yml:installer-macos` | real_engine | 是 | real_engine_tested | success | git archive 副本 + Install-MD20.command + 啟動檔 |
| `ci.yml:installer-windows` | real_engine | 是 | real_engine_tested | success | PowerShell 5.1 安裝 CPU 路徑 + CUDA 環境 dry-run 求解 + 桌面啟動檔 |
| `gui-preview.yml:screenshots` | gui | 是 | —（不能當資格） | 580cbff 成功（run 42374500297） | 四語截圖與點擊自測；GUI 檢查，不是科學驗證 |
| `report-template.yml:template` | unit | 是 | —（不能當資格） | 580cbff 成功（run 42374500285） | 合成資料畫出每種圖；只證明圖會畫，不是科學驗證 |
| `diag-membrane.yml:build` | diagnostic | **否** | —（不能當資格） | 手動；580cbff 的診斷 run 42374753967 四個 job 結論 success（success 只代表腳本結束碼 0） | diag_membrane_nan.py 永遠回傳 0。D-136 起接 validate_membrane_diag.py：artifact 不完整會紅，NaN 計數只報告。不是資格。 |
| `diag-membrane.yml:cross` | diagnostic | **否** | —（不能當資格） | 手動；同上 | 在另一個 OS 建的系統上跑動力學；同上不是資格。 |
| `release-windows.yml:package` | release | 是 | —（不能當資格） | 只在推 tag 時跑 | git archive 產生 zip |
| `release-windows.yml:verify-windows` | release | 是 | —（不能當資格） | 只在推 tag 時跑 | 發行前在乾淨 Windows 實裝驗證 |
| `release-windows.yml:verify-macos` | release | 是 | —（不能當資格） | 只在推 tag 時跑 | 發行前在乾淨 macOS 實裝驗證 |
| `release-windows.yml:publish` | release | 是 | —（不能當資格） | 只在推 tag 時跑 | 建立公開 prerelease；R7 規格明令不自動執行 |

## 總覽

| 功能 | 實作 | 合成測試 | 真實引擎 | 科學 benchmark | 已發行安裝程式 | 最後已知結果 |
|---|---|---|---|---|---|---|
| [分子對接（AutoDock Vina：independent／simultaneous、盒子、redocking、拒絕代碼）](#docking_vina) | yes | yes | yes | observed | v0.1.0a17 (older code) | pass |
| [高通量前期篩選（Excel/CSV 化合物庫 → 3D → 批次快速對接 → 排名）](#hts_screen) | yes | yes | yes | none | v0.1.0a17 | pass |
| [短 MD 篩 pose（WP5）](#pose_screen) | yes | yes | yes | none | v0.1.0a17 | pass |
| [受體與配體建模（修復、質子化、配體參數化、水盒、閘門）](#receptor_ligand_build) | yes | yes | yes | none | v0.1.0a17 (older code) | stale |
| [多配體同時進 MD（穿環／重疊／漂浮檢查、軟核鬆弛、共存效應比較）](#multi_ligand_complex) | yes | yes | partial | none | v0.1.0a17 (older code) | pass |
| [金屬位點辨識與 policy（remove／keep_nonbonded／bonded 選擇、擋關情境）](#metal_policy) | yes | yes | no | none | v0.1.0a17 | stale |
| [鋅的晶體幾何鍵結模型（含金屬中心與經金屬的 1-3/1-4 修正）](#metal_bonded_zinc) | yes | yes | failing | none | v0.1.0a17 | fail |
| [金屬擬合參數匯入（QM Hessian／MCPB.py／JSON）與 QM 小模型輸入產生](#metal_fitted_params) | yes | yes | partial | none | v0.1.0a17 | partial |
| [膜系統建模（膜蛋白、膜表面接觸、純膜；去水碰撞、離子清理、即時 3D）](#membrane_build) | yes | yes | partial | none | v0.1.0a17 (older code) | stale |
| [膜專用分析與報告（厚度、面積／脂質、序參數、胜肽表面接觸）](#membrane_analysis) | yes | yes | no | none | v0.1.0a17 | pass |
| [OpenMM MD 引擎（階段、分段存檔、續跑、watchdog、資源模式、doctor）](#md_openmm_restart) | yes | yes | yes | none | v0.1.0a17 (older code) | stale |
| [粗粒化 Martini 3（setup-cg、純膜／跨膜螺旋／膜表面胜肽）](#coarse_grained_martini) | yes | yes | yes | none | v0.1.0a17 | pass |
| [胜肽序列摺疊（OmegaFold 等）與 pLDDT 閘門](#peptide_structure_prediction) | yes | yes | no | none | v0.1.0a17 | pass |
| [獨立重複（replica 計畫、預設 3 條、補跑）與跨重複彙總](#replicas) | partial | yes | no | none | v0.1.0a17 (older code) | stale |
| [SMD 拉離、傘狀採樣、WHAM／MBAR PMF、bootstrap、ΔPMF／ΔG°](#smd_umbrella_pmf) | yes | yes | yes | none | v0.1.0a17 (older code) | pass |
| [傘狀採樣智慧補窗（由粗到細、每窗各自 k、覆蓋圖、手動補採樣、行動成本報告）](#adaptive_windows) | yes | yes | yes | none | v0.1.0a17 (older code) | stale |
| [SMD 拉離路徑接觸釋放（D-116，F13）](#smd_contact_release) | yes | yes | no | none | unreleased (main only) | pass |
| [PMF 結構化評估（執行狀態／科學評估／比較資格三分、overlap graph 連通）](#assessment) | yes | yes | no | none | unreleased (main only) | pass |
| [化學定義的互作（氫鍵、電荷感知鹽橋、多標籤、PBC 感知）與持續性（事件、截尾、Kaplan–Meier）](#interactions_persistence) | yes | yes | partial | none | v0.1.0a17 (older code) | pass |
| [共同基底系統比較（同軸 PCA、可比性檢查、前後半一致性、ΔRMSF）](#common_basis_comparison) | yes | yes | no | none | unreleased (main only) | pass |
| [分析工具箱：tICA、MSM、側鏈氫鍵網路、水合位點](#toolbox_tica_msm) | yes | yes | no | none | unreleased (main only) | pass |
| [HTML 報告（圖、圖說、方法段落、證據覆蓋、四語）](#reports) | yes | yes | partial | none | v0.1.0a17 (older code) | stale |
| [GUI（NiceGUI）與獨立計算子程序（worker）、重開接回](#gui_worker) | yes | yes | no | none | v0.1.0a17 (older code) | stale |
| [授權第 1 層：LICENSE 專有條款（D-124）](#licence_l1_terms) | yes | no | no | none | unreleased (main only) | unverified |
| [授權第 2–3 層：簽章授權驗證、機器碼、等級／功能／席次、撤銷清單、評估版浮水印、輸出授權編號（D-125、D-127、D-128）](#licence_l2_l3_verification) | yes | yes | no | none | unreleased (main only) | stale |
| [授權第 4 層：發行版 Cython＋AES-256-GCM（D-125 設計）](#licence_l4_distribution_protection) | no | no | no | none | unreleased (main only) | unverified |
| [安裝程式（Windows install.ps1、macOS install.sh、環境檔、啟動檔、doctor）](#installer) | yes | yes | partial | none | v0.1.0a17 (older code) | stale |
| [分析快取指紋與原子替換（R4，D-135）](#analysis_cache) | yes | yes | no | none | unreleased (main only) | unverified |
| [有界自主行動帳本（R8，D-137）](#autonomy_ledger) | yes | yes | no | none | unreleased (main only) | unverified |
| [漏斗約束與解析標準態 ΔG°（A8，D-140）](#funnel_standard_state) | yes | yes | no | none | unreleased (main only) | unverified |
| [金屬配位水的 OH⁻ 選項（D-141）](#metal_water_hydroxide) | yes | yes | no | none | unreleased (main only) | unverified |

<a id="docking_vina"></a>
## 分子對接（AutoDock Vina：independent／simultaneous、盒子、redocking、拒絕代碼）

`docking_vina`

**實作**：`md20/docking/run.py::dock`、`md20/docking/vina_cli.py::ensure_vina_exe`、`md20/docking/box.py`、`md20/docking/poses.py`、`md20/docking/receptor_pdbqt.py`、`md20/docking/ionize.py`

**支援的系統類型**：蛋白受體 + 小分子配體（獨立或同時多配體）；胜肽配體（<10 殘基直接對接；≥10 殘基先摺疊）

**限制**：
- Vina 分數不是結合自由能；只做排序與姿勢候選
- 配體直接配位金屬不會在對接階段被擋（審查 C0，D-53 只有距離約束後備）
- Windows 無 python bindings，改用官方執行檔（單一釘選版 v1.2.7 + sha256，D-114）
- 同時對接多配體進單一小口袋會被拒絕推薦（hsieh2024 重現：口袋約 107 Å3 對六配體約 1386 Å3）

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_docking_pure.py` | unit | `ci.yml:pure-python` |
| `tests/test_docking_rejection_codes.py` | unit | `ci.yml:pure-python` |
| `tests/test_vina_pin.py` | unit | `ci.yml:pure-python` |
| `tests/test_vina_cpu_use.py` | unit | `ci.yml:pure-python` |
| `tests/test_ionize.py` | unit | `ci.yml:pure-python` |
| `tests/test_docking_integration.py` | real_engine | `ci.yml:openmm-stack` |
| `tests/test_validation_papers.py` | benchmark | `ci.yml:paper-docking` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`yes`｜scientifically_benchmarked=`observed`｜released_installer=`v0.1.0a17 (older code)`

**最後已知結果**：`pass`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：openmm-stack 三 OS 成功且 test_docking_integration 未被跳過（redocking、simultaneous）

**benchmark 範圍**：僅 paper-docking（非阻擋、縮減搜尋 exhaustiveness 8）的觀察，不構成資格：hsieh2025（4CXT，GGGGGKP）第 1 名 -5.91 kcal/mol（論文 -5.22）、接觸殘基 recall 100%；hsieh2024（1VKX，六配體）聯合分數 -11.7（論文 -13.86）但與論文殘基 recall 0/11，未重現（來源：STATUS.md C1，ef32b48）。

**已發行安裝程式**：v0.1.0a17 (older code)（a17 含較舊版本：6/6 個實作檔存在於 a17，3 個與 main 相同；main 的差異未發行）

<a id="hts_screen"></a>
## 高通量前期篩選（Excel/CSV 化合物庫 → 3D → 批次快速對接 → 排名）

`hts_screen`

**實作**：`md20/docking/library.py`、`md20/docking/screen.py`

**支援的系統類型**：100–500 個小分子 + 單一受體口袋

**限制**：
- 分數只用最佳 pose 的縮減搜尋 Vina 分數
- 去鹽取最大片段可能誤刪季銨鹽或金屬配合物（審查 C0）
- PubChem 名稱查詢預設關閉；下載需要網路

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_screen_library.py` | unit | `ci.yml:pure-python` |
| `tests/test_screen_workflow.py` | synthetic | `ci.yml:pure-python` |
| `tests/test_screen_integration.py` | real_engine | `ci.yml:openmm-stack` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`yes`｜scientifically_benchmarked=`none`｜released_installer=`v0.1.0a17`

**最後已知結果**：`pass`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：test_screen_integration（3PTB，真實下載 + 真實 Vina）在 openmm-stack 未被跳過

**benchmark 範圍**：none

**已發行安裝程式**：v0.1.0a17（實作檔與 a17 逐檔相同）

<a id="pose_screen"></a>
## 短 MD 篩 pose（WP5）

`pose_screen`

**實作**：`md20/docking/pose_screen.py`

**支援的系統類型**：已對接的蛋白–小分子複合物（候選 pose 為推薦 + 各 cluster）

**限制**：
- 只排除會散開的 pose，不以短 MD 排名結合強度
- 非 research tier 預設關閉

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_pose_screen.py` | unit | `ci.yml:pure-python` |
| `tests/test_workflow_integration.py` | real_engine | `ci.yml:heavy[pose-screen]` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`yes`｜scientifically_benchmarked=`none`｜released_installer=`v0.1.0a17`

**最後已知結果**：`pass`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：heavy[pose-screen]（-k pose_md_screen）成功

**benchmark 範圍**：none

**已發行安裝程式**：v0.1.0a17（實作檔與 a17 逐檔相同）

<a id="receptor_ligand_build"></a>
## 受體與配體建模（修復、質子化、配體參數化、水盒、閘門）

`receptor_ligand_build`

**實作**：`md20/build/receptor.py::prepare_receptor`、`md20/build/ligand.py::prepare_ligand`、`md20/build/protonation.py`、`md20/build/structure_gate.py`、`md20/build/caps.py`、`md20/build/gates.py`、`md20/build/assemble.py::assemble_system`

**支援的系統類型**：蛋白（單鏈或多鏈）+ 0 個或多個小分子；水盒（十二面體）或隱式溶劑 GBn2

**限制**：
- 胜肽配體原子電荷未寫入 build manifest：鹽橋判定時視為未知，不當作中性
- PROPKA 只審查提示，不自動改質子化
- 受體長 loop、未知殘基等選項尚無自動處理（維持 NEEDS_HUMAN）
- 配體參數：OpenFF，失敗退 GAFF2；GBn2 在 CPU 上很慢，僅 GPU 有意義
- conda 環境尚未鎖版（見 installer）

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_build_gates.py` | unit | `ci.yml:pure-python` |
| `tests/test_structure_gate.py` | unit | `ci.yml:pure-python` |
| `tests/test_caps.py` | unit | `ci.yml:pure-python` |
| `tests/test_ligand_mapping.py` | unit | `ci.yml:pure-python` |
| `tests/test_ligand_atom_charges.py` | unit | `ci.yml:pure-python` |
| `tests/test_real_case_integration.py` | real_engine | `ci.yml:openmm-stack` |
| `tests/test_workflow_integration.py` | real_engine | `ci.yml:heavy[workflow]` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`yes`｜scientifically_benchmarked=`none`｜released_installer=`v0.1.0a17 (older code)`

**最後已知結果**：`stale`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：3PTB 全流程（heavy[workflow]）與 test_real_case_integration 成功。證據之後改動的檔案（現況沒有 CI 結果）：`md20/build/assemble.py`

**benchmark 範圍**：none

**已發行安裝程式**：v0.1.0a17 (older code)（a17 含較舊版本：7/7 個實作檔存在於 a17，3 個與 main 相同；main 的差異未發行）

<a id="multi_ligand_complex"></a>
## 多配體同時進 MD（穿環／重疊／漂浮檢查、軟核鬆弛、共存效應比較）

`multi_ligand_complex`

**實作**：`md20/build/multi_ligand.py`、`md20/build/softcore.py`、`md20/sampling/multi.py`、`md20/report/comparability.py`

**支援的系統類型**：單一受體 + 多個小分子同時結合

**限制**：
- 共存效應是『單獨 vs 共同口袋』的趨勢比較，不是封閉熱力學循環，不能推論混合物協同
- 拉離路徑被另一配體擋住時不計算結合自由能
- 跨候選比較只在條件可比時成立（D-120），否則標不可比

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_multi_ligand_geometry.py` | unit | `ci.yml:pure-python` |
| `tests/test_multi_binding.py` | unit | `ci.yml:pure-python` |
| `tests/test_cooperativity.py` | unit | `ci.yml:pure-python` |
| `tests/test_comparability_matrix.py` | unit | `ci.yml:pure-python` |
| `tests/test_softcore.py` | real_engine | `ci.yml:openmm-stack` |
| `tests/test_docking_integration.py` | real_engine | `ci.yml:openmm-stack` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`partial`｜scientifically_benchmarked=`none`｜released_installer=`v0.1.0a17 (older code)`

**最後已知結果**：`pass`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：只有 softcore（真實 OpenMM）與 simultaneous 對接在真實引擎跑過；多配體複合物進 MD 的完整路徑沒有專屬真實引擎測試

**benchmark 範圍**：none

**已發行安裝程式**：v0.1.0a17 (older code)（a17 含較舊版本：3/4 個實作檔存在於 a17，2 個與 main 相同；main 的差異未發行）

<a id="metal_policy"></a>
## 金屬位點辨識與 policy（remove／keep_nonbonded／bonded 選擇、擋關情境）

`metal_policy`

**實作**：`md20/build/metal.py::find_sites`、`md20/build/metal.py::apply_metal_policy`、`md20/build/metal.py::ligand_metal_gate`

**支援的系統類型**：含 Zn、Mg、Ca 等結構金屬的蛋白受體

**限制**：
- policy 在配體加入前執行，配體直接配位金屬以 D-53 距離約束後備處理，不是參數化
- 溶劑離子清理不得移除結構金屬（D-126；回歸測試見 test_ion_water_clash）

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_metal.py` | unit | `ci.yml:pure-python` |
| `tests/test_ligand_metal.py` | unit | `ci.yml:pure-python` |
| `tests/test_ion_water_clash.py` | unit | `ci.yml:pure-python` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`no`｜scientifically_benchmarked=`none`｜released_installer=`v0.1.0a17`

**最後已知結果**：`stale`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：只有純 Python 測試；policy 的真實引擎路徑僅間接經由 metal 整合測試（見下兩項）。證據之後改動的檔案（現況沒有 CI 結果）：`tests/test_ion_water_clash.py`

**benchmark 範圍**：none

**已發行安裝程式**：v0.1.0a17（實作檔與 a17 逐檔相同）

<a id="metal_bonded_zinc"></a>
## 鋅的晶體幾何鍵結模型（含金屬中心與經金屬的 1-3/1-4 修正）

`metal_bonded_zinc`

**實作**：`md20/build/metal.py::bonded_metal_terms`、`md20/build/metal.py::add_metal_forces`、`md20/build/metal.py::site_waters_to_add`、`md20/build/metal.py::site_water_ligand_gate`、`md20/build/receptor.py::metal_site_water_lines`

**支援的系統類型**：CA II（3KS3）型 Zn–His3 位點（唯一真實測試過的案例）

**限制**：
- 580cbff／58d81bc 在 heavy-metal CI 失敗（58d81bc：HIS119:ND1 2.36 Å 對 r0 2.02 Å；GLU106 OE1 塌陷到 Zn 1.74 Å）。D-133 改為保留晶體配位水作第四個鍵結配位（模型變更，使用者授權），門檻未放寬；新模型尚無 CI 結果
- 電荷沿用力場；未擬合的諧和鍵/角
- 不得因此重新分類為基礎設施問題：這是科學／模型失敗
- 鋅水以中性 TIP3P 表示，未提供 OH⁻ 模型；配體佔據配位水位置時 NEEDS_HUMAN

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_metal.py` | unit | `ci.yml:pure-python` |
| `tests/test_metal_integration.py` | real_engine | `ci.yml:heavy[metal]` |
| `tests/test_metal_site_water.py` | unit | `ci.yml:pure-python` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`failing`｜scientifically_benchmarked=`none`｜released_installer=`v0.1.0a17`

**最後已知結果**：`fail`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：heavy[metal] 在 580cbff 與 58d81bc 失敗（test_bonded_zinc_ca2）；D-133 修正後待 CI

**benchmark 範圍**：none

**已發行安裝程式**：v0.1.0a17（實作檔與 a17 逐檔相同）

<a id="metal_fitted_params"></a>
## 金屬擬合參數匯入（QM Hessian／MCPB.py／JSON）與 QM 小模型輸入產生

`metal_fitted_params`

**實作**：`md20/build/metal_params.py`

**支援的系統類型**：單一金屬位點的 cluster／蛋白位點

**限制**：
- QM 計算本身在程式外執行（ORCA/Gaussian）
- MCPB.py 轉譯不含二面角與金屬 LJ
- 只有 JSON 匯入路徑在真實引擎跑過；QM Hessian 與 MCPB.py 轉譯是純 Python 測試（對已知諧和模型還原）

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_metal_params.py` | unit | `ci.yml:pure-python` |
| `tests/test_metal_integration.py` | real_engine | `ci.yml:heavy[metal]` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`partial`｜scientifically_benchmarked=`none`｜released_installer=`v0.1.0a17`

**最後已知結果**：`partial`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：heavy[metal] 的 test_fitted_zinc_params_json_ca2 通過（同一 job 的 bonded 測試失敗）

**benchmark 範圍**：none

**已發行安裝程式**：v0.1.0a17（實作檔與 a17 逐檔相同）

<a id="membrane_build"></a>
## 膜系統建模（膜蛋白、膜表面接觸、純膜；去水碰撞、離子清理、即時 3D）

`membrane_build`

**實作**：`md20/build/membrane.py::build_membrane_system`、`md20/build/assemble.py::remove_overlapping_waters`、`md20/build/live3d.py`

**支援的系統類型**：純 POPC 雙層（情境 C）；胜肽在 POPC 膜表面（情境 B，不穿膜）；膜蛋白（情境 A）：只有純 Python 測試

**限制**：
- 情境 B 曾間歇 NaN（28e87aa 失敗；根因判斷為離子落在重疊水上，D-115／D-126），單次綠燈不是穩定性證明
- 脂質混合（test_grid_mixture_popc_pope）為 xfail，未驗證
- 膜蛋白（情境 A）無真實引擎測試
- tools/diag_membrane_nan.py 永遠回傳 0；診斷結果不構成資格，只有 validate_membrane_diag.py 判定的 artifact 完整性與觀察計數

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_membrane.py` | unit | `ci.yml:pure-python` |
| `tests/test_ion_water_clash.py` | unit | `ci.yml:pure-python` |
| `tests/test_declash_waters.py` | unit | `ci.yml:pure-python` |
| `tests/test_live3d.py` | unit | `ci.yml:pure-python` |
| `tests/test_membrane_integration.py` | real_engine | `ci.yml:openmm-stack` |
| `tests/test_validate_membrane_diag.py` | unit | `ci.yml:pure-python` |
| `tools/diag_membrane_nan.py` | diagnostic | `diag-membrane.yml:build` |
| `tools/validate_membrane_diag.py` | diagnostic | `diag-membrane.yml:build` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`partial`｜scientifically_benchmarked=`none`｜released_installer=`v0.1.0a17 (older code)`

**最後已知結果**：`stale`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：test_membrane_integration（情境 C、情境 B）在 openmm-stack 三 OS 未被跳過且成功；一項 xfail。證據之後改動的檔案（現況沒有 CI 結果）：`md20/build/assemble.py`、`tests/test_ion_water_clash.py`、`tests/test_validate_membrane_diag.py`、`tools/validate_membrane_diag.py`

**benchmark 範圍**：none（膜診斷是 diagnostic，不是 benchmark；STATUS 記載 580cbff 診斷 32 次 0 NaN、對照組 3/32，artifact 未能由本代理下載重讀）

**已發行安裝程式**：v0.1.0a17 (older code)（a17 含較舊版本：2/3 個實作檔存在於 a17，0 個與 main 相同；main 的差異未發行）

<a id="membrane_analysis"></a>
## 膜專用分析與報告（厚度、面積／脂質、序參數、胜肽表面接觸）

`membrane_analysis`

**實作**：`md20/analysis/membrane.py`、`md20/analysis/membrane_report.py`、`md20/analysis/membrane_run.py`

**支援的系統類型**：上列膜系統的軌跡

**限制**：
- 新功能，結果當初步；沒有對照實驗或文獻 benchmark

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_membrane_workflow.py` | synthetic | `ci.yml:pure-python` |
| `tests/test_membrane.py` | unit | `ci.yml:pure-python` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`no`｜scientifically_benchmarked=`none`｜released_installer=`v0.1.0a17`

**最後已知結果**：`pass`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：純 Python／合成資料

**benchmark 範圍**：none

**已發行安裝程式**：v0.1.0a17（實作檔與 a17 逐檔相同）

<a id="md_openmm_restart"></a>
## OpenMM MD 引擎（階段、分段存檔、續跑、watchdog、資源模式、doctor）

`md_openmm_restart`

**實作**：`md20/engine/backend.py::OpenMMBackend`、`md20/engine/protocol.py::make_protocol`、`md20/engine/chunks.py::run_stage`、`md20/engine/runner.py`、`md20/engine/longrun.py`、`md20/env/doctor.py`、`md20/env/resources.py`

**支援的系統類型**：任何建好的 system.xml／topology.pdb；CPU、CUDA、OpenCL 平台

**限制**：
- CI 只在 CPU 平台跑；CUDA／OpenCL 路徑只有使用者筆電的紀錄（STATUS A3：GTX 1060／RTX 4060），不是 CI 證據
- 續跑與 GUI 重連的邏輯用 FakeBackend／合成檔測試；乾淨安裝後的真實續跑／重連流程沒有 CI 專屬測試（R7 驗收項，未完成）
- 筆電關主控台視窗時子程序是否存活未實測

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_engine_fake.py` | synthetic | `ci.yml:pure-python` |
| `tests/test_resume.py` | unit | `ci.yml:pure-python` |
| `tests/test_longrun.py` | unit | `ci.yml:pure-python` |
| `tests/test_progress_text.py` | unit | `ci.yml:pure-python` |
| `tests/test_resources.py` | unit | `ci.yml:pure-python` |
| `tests/test_openmm_integration.py` | real_engine | `ci.yml:openmm-stack` |
| `tests/test_longrun_integration.py` | real_engine | `ci.yml:openmm-stack` |
| `tests/test_winjob.py` | unit | `ci.yml:pure-python` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`yes`｜scientifically_benchmarked=`none`｜released_installer=`v0.1.0a17 (older code)`

**最後已知結果**：`stale`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：test_openmm_integration（水盒 MD、平台、HMR、doctor）與 3PTB 全流程；test_longrun_integration 中 MD20_CG_TEST_DIR 那項被跳過。證據之後改動的檔案（現況沒有 CI 結果）：`md20/engine/protocol.py`、`tests/test_longrun.py`

**benchmark 範圍**：none

**已發行安裝程式**：v0.1.0a17 (older code)（a17 含較舊版本：7/7 個實作檔存在於 a17，6 個與 main 相同；main 的差異未發行）

<a id="coarse_grained_martini"></a>
## 粗粒化 Martini 3（setup-cg、純膜／跨膜螺旋／膜表面胜肽）

`coarse_grained_martini`

**實作**：`md20/build/martini.py`、`md20/build/cg_system.py`、`md20/engine/cg_run.py`、`md20/analysis/cg.py`

**支援的系統類型**：POPC 純膜、跨膜螺旋 in POPC、膜表面胜肽（三個小系統）

**限制**：
- 只跑數千步的小系統；筆電 GPU 速度與長時間穩定性未測
- 報告標註為珠子層級

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_cg_pure.py` | unit | `ci.yml:pure-python` |
| `tests/test_martini.py` | unit | `ci.yml:pure-python` |
| `tests/test_cg_integration.py` | real_engine | `ci.yml:openmm-stack` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`yes`｜scientifically_benchmarked=`none`｜released_installer=`v0.1.0a17`

**最後已知結果**：`pass`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：openmm-stack 的獨立 CG 步驟（MD20_CG=1）在 Ubuntu 與 Windows 3 passed

**benchmark 範圍**：none

**已發行安裝程式**：v0.1.0a17（實作檔與 a17 逐檔相同）

<a id="peptide_structure_prediction"></a>
## 胜肽序列摺疊（OmegaFold 等）與 pLDDT 閘門

`peptide_structure_prediction`

**實作**：`md20/build/fold.py`、`md20/build/peptide.py`

**支援的系統類型**：≥10 殘基胜肽序列

**限制**：
- CI 沒有安裝 omegafold：真實摺疊測試被跳過
- 筆電實測的摺疊結果屬使用者回報，未在 CI

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_fold.py` | unit | `ci.yml:pure-python` |
| `tests/test_peptide.py` | unit | `ci.yml:pure-python` |
| `tests/test_peptide_input.py` | unit | `ci.yml:pure-python` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`no`｜scientifically_benchmarked=`none`｜released_installer=`v0.1.0a17`

**最後已知結果**：`pass`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：純 Python；真實摺疊測試在 CI 為 SKIPPED

**benchmark 範圍**：none

**已發行安裝程式**：v0.1.0a17（實作檔與 a17 逐檔相同）

<a id="replicas"></a>
## 獨立重複（replica 計畫、預設 3 條、補跑）與跨重複彙總

`replicas`

**實作**：`md20/engine/replicas.py::run_replicas`、`md20/engine/replica_plan.py::plan_replicas`、`md20/workflow.py::Workflow.analyse`、`md20/analysis/replica_set.py::aggregate_replica_set`、`md20/report/replica_section.py`

**支援的系統類型**：任何 MD 工作流程（SMD／傘狀採樣不隨重複數變）

**限制**：
- D-130／D-142：每條重複都分析並彙總（RMSD 等、ΔRMSF Welch 區間、水合位點、DSSP、PCA 低谷佔比、DCCM、tICA/MSM 逐條資格、膜指標）；n=1 不給重複間不確定性；真實 mdtraj 路徑待 CI
- 重複計畫與預設 3 條（D-131）合入 main 後尚未有 CI 結果
- 每條從同一個建好的系統開始、各自 seed（2026+1000×條序）；不是從同一平衡結構分出

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_queue_replicas.py` | unit | `ci.yml:pure-python` |
| `tests/test_replica_plan.py` | unit | `ci.yml:pure-python` |
| `tests/test_replica_analysis.py` | synthetic | `ci.yml:pure-python` |
| `tests/test_replica_observables.py` | synthetic | `ci.yml:pure-python` |

**狀態**：implemented=`partial`｜synthetic_tested=`yes`｜real_engine_tested=`no`｜scientifically_benchmarked=`none`｜released_installer=`v0.1.0a17 (older code)`

**最後已知結果**：`stale`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：純 Python。證據之後改動的檔案（現況沒有 CI 結果）：`md20/engine/replica_plan.py`、`md20/workflow.py`、`tests/test_replica_plan.py`

**benchmark 範圍**：none

**已發行安裝程式**：v0.1.0a17 (older code)（a17 含較舊版本：2/3 個實作檔存在於 a17，0 個與 main 相同；main 的差異未發行）

<a id="smd_umbrella_pmf"></a>
## SMD 拉離、傘狀採樣、WHAM／MBAR PMF、bootstrap、ΔPMF／ΔG°

`smd_umbrella_pmf`

**實作**：`md20/sampling/binding.py::run_binding`、`md20/sampling/pmf.py::pmf_from_windows`、`md20/sampling/_mdh_legacy.py`、`md20/sampling/windows.py`、`md20/sampling/cv.py`

**支援的系統類型**：蛋白–小分子（單配體或多配體各自拉離）；NaCl 離子對（測試案例）

**限制**：
- 一維質心距離 PMF：對埋入口袋的配體高估 3 倍以上（3PTB teaching -21 kcal/mol 對實驗約 -6.4，STATUS C），只比較趨勢
- 未做方向／構形限制與標準態校正（漏斗約束設計中）
- PMF 未涵蓋取樣範圍或末端未持平不輸出 ΔG°；research 需 ≥3 條實際完成的 replica
- ΔPMF、ΔG°、路徑特定 PMF 與標準結合自由能是不同量；MBAR 可用不等於完整 FEP/ABFE 流程

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_sampling.py` | unit | `ci.yml:pure-python` |
| `tests/test_mbar_bootstrap.py` | unit | `ci.yml:pure-python` |
| `tests/test_pmf_diagnostics.py` | unit | `ci.yml:pure-python` |
| `tests/test_pmf_plateau.py` | unit | `ci.yml:pure-python` |
| `tests/test_binding_targets.py` | unit | `ci.yml:pure-python` |
| `tests/test_smd_box_sizing.py` | unit | `ci.yml:pure-python` |
| `tests/test_restraint_groups_openmm.py` | real_engine | `ci.yml:openmm-stack` |
| `tests/test_binding_integration.py` | real_engine | `ci.yml:openmm-stack` |
| `tests/test_workflow_integration.py` | real_engine | `ci.yml:heavy[workflow]` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`yes`｜scientifically_benchmarked=`none`｜released_installer=`v0.1.0a17 (older code)`

**最後已知結果**：`pass`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：NaCl PMF（接觸離子對最小值約 0.28 nm 的合理性檢查）與 3PTB 全流程含 binding 成功

**benchmark 範圍**：none（NaCl 位置只是合理性檢查；3PTB 對實驗的偏差見 restrictions）

**已發行安裝程式**：v0.1.0a17 (older code)（a17 含較舊版本：5/5 個實作檔存在於 a17，3 個與 main 相同；main 的差異未發行）

<a id="adaptive_windows"></a>
## 傘狀採樣智慧補窗（由粗到細、每窗各自 k、覆蓋圖、手動補採樣、行動成本報告）

`adaptive_windows`

**實作**：`md20/sampling/adaptive.py::plan_refinement`、`md20/report/auto_actions.py`、`md20/gui/actions.py::resample_range`

**支援的系統類型**：上列傘狀採樣系統

**限制**：
- min_effective_samples=100 會讓補窗成本約 ×5–6，REVIEW #18 門檻待使用者授權
- 合成剖面證明規則有效，不證明真實系統的 PMF 正確
- 補窗邏輯是啟發式，效益標為啟發式

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_adaptive_windows.py` | synthetic | `ci.yml:pure-python` |
| `tests/test_umbrella_manual.py` | synthetic | `ci.yml:pure-python` |
| `tests/test_smd_informed_windows.py` | synthetic | `ci.yml:pure-python` |
| `tests/test_smd_window_starts.py` | unit | `ci.yml:pure-python` |
| `tests/test_auto_actions.py` | unit | `ci.yml:pure-python` |
| `tests/test_workflow_integration.py` | real_engine | `ci.yml:heavy[workflow]` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`yes`｜scientifically_benchmarked=`none`｜released_installer=`v0.1.0a17 (older code)`

**最後已知結果**：`stale`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：3PTB 全流程的補窗（heavy[workflow]）成功。證據之後改動的檔案（現況沒有 CI 結果）：`md20/gui/actions.py`

**benchmark 範圍**：none

**已發行安裝程式**：v0.1.0a17 (older code)（a17 含較舊版本：2/3 個實作檔存在於 a17，0 個與 main 相同；main 的差異未發行）

<a id="smd_contact_release"></a>
## SMD 拉離路徑接觸釋放（D-116，F13）

`smd_contact_release`

**實作**：`md20/analysis/smd_contacts.py`

**支援的系統類型**：已完成 SMD 的蛋白–配體

**限制**：
- 只描述單次拉離；拉力與功不是自由能
- 釋放點取決於拉離速率與路徑

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_smd_contacts.py` | synthetic | `ci.yml:pure-python` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`no`｜scientifically_benchmarked=`none`｜released_installer=`unreleased (main only)`

**最後已知結果**：`pass`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：合成資料

**benchmark 範圍**：none

**已發行安裝程式**：unreleased (main only)（實作檔在 v0.1.0a17 樹中都不存在）

<a id="assessment"></a>
## PMF 結構化評估（執行狀態／科學評估／比較資格三分、overlap graph 連通）

`assessment`

**實作**：`md20/sampling/assessment.py::assess_pmf`、`md20/sampling/assessment.py::eligibility_of`、`md20/sampling/assessment.py::claim_status`

**支援的系統類型**：任何有傘狀採樣窗口的 PMF 結果

**限制**：
- 門檻為保守啟發式，未對外部資料校準
- 沒有專屬真實引擎測試：run_binding 寫入評估的路徑只在全流程間接走過，但測試沒有斷言它
- D-134：證據矩陣、圖說、比較、GUI 讀同一份 claim 評估；舊版結果需重新分析才可能 supported

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_assessment.py` | synthetic | `ci.yml:pure-python` |
| `tests/test_pmf_diagnostics.py` | unit | `ci.yml:pure-python` |
| `tests/test_evidence_assessment.py` | unit | `ci.yml:pure-python` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`no`｜scientifically_benchmarked=`none`｜released_installer=`unreleased (main only)`

**最後已知結果**：`pass`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：合成資料

**benchmark 範圍**：none

**已發行安裝程式**：unreleased (main only)（實作檔在 v0.1.0a17 樹中都不存在）

<a id="interactions_persistence"></a>
## 化學定義的互作（氫鍵、電荷感知鹽橋、多標籤、PBC 感知）與持續性（事件、截尾、Kaplan–Meier）

`interactions_persistence`

**實作**：`md20/analysis/interactions.py::fingerprint`、`md20/analysis/persistence.py::persistence_for_runs`、`md20/analysis/extended.py`、`md20/analysis/persistence.py::EventAccumulator`、`md20/analysis/stream.py::stream_production_persistence`

**支援的系統類型**：蛋白–小分子／胜肽軌跡（有氫與無氫拓撲）

**限制**：
- 配體電荷未知時鹽橋標『帶電接近，配體電荷未知』，不當作中性
- 水橋在無水軌跡時標不可用
- 單一軌跡的持續性估計不含不確定性
- D-135：抽幀時持續性改在全部儲存幀上串流計算；串流失敗則標 limited；真實 mdtraj 串流待 CI

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_interactions.py` | synthetic | `ci.yml:pure-python` |
| `tests/test_interactions_report.py` | synthetic | `ci.yml:pure-python` |
| `tests/test_extended_fingerprint_wiring.py` | unit | `ci.yml:pure-python` |
| `tests/test_extended_analysis.py` | real_engine | `ci.yml:openmm-stack` |
| `tests/test_analysis_resolution.py` | unit | `ci.yml:pure-python` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`partial`｜scientifically_benchmarked=`none`｜released_installer=`v0.1.0a17 (older code)`

**最後已知結果**：`pass`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：test_extended_analysis 用真實 mdtraj；持續性與互作新定義本身以合成軌跡測試

**benchmark 範圍**：none

**已發行安裝程式**：v0.1.0a17 (older code)（a17 含較舊版本：1/3 個實作檔存在於 a17，0 個與 main 相同；main 的差異未發行）

<a id="common_basis_comparison"></a>
## 共同基底系統比較（同軸 PCA、可比性檢查、前後半一致性、ΔRMSF）

`common_basis_comparison`

**實作**：`md20/analysis/common_basis.py::common_basis`、`md20/analysis/common_basis.py::comparability`

**支援的系統類型**：條件可比的多個系統（未知即不可比）

**限制**：
- 短軌跡的投影密度不是自由能地貌
- 不可比時只報告不可比

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_common_basis.py` | synthetic | `ci.yml:pure-python` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`no`｜scientifically_benchmarked=`none`｜released_installer=`unreleased (main only)`

**最後已知結果**：`pass`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：合成軌跡；真實 mdtraj 流程沒有專屬測試

**benchmark 範圍**：none

**已發行安裝程式**：unreleased (main only)（實作檔在 v0.1.0a17 樹中都不存在）

<a id="toolbox_tica_msm"></a>
## 分析工具箱：tICA、MSM、側鏈氫鍵網路、水合位點

`toolbox_tica_msm`

**實作**：`md20/analysis/toolbox.py::tica`、`md20/analysis/toolbox.py::msm`、`md20/analysis/toolbox.py::hbond_network`、`md20/analysis/toolbox.py::hydration_sites`

**支援的系統類型**：MD 軌跡（探索性）

**限制**：
- tICA／MSM 為探索性：單一軌跡不報速率，不宣稱動力學速率；水合密度不是水合自由能；網路中心性只提出可檢驗假說，不是因果殘基
- 尚未做 lag-time 敏感度、轉移覆蓋等驗證

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_toolbox.py` | synthetic | `ci.yml:pure-python` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`no`｜scientifically_benchmarked=`none`｜released_installer=`unreleased (main only)`

**最後已知結果**：`pass`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：合成資料（已知時間尺度與已知結合水）；沒有真實軌跡的驗證

**benchmark 範圍**：none

**已發行安裝程式**：unreleased (main only)（實作檔在 v0.1.0a17 樹中都不存在）

<a id="reports"></a>
## HTML 報告（圖、圖說、方法段落、證據覆蓋、四語）

`reports`

**實作**：`md20/report/html.py`、`md20/report/figures.py`、`md20/report/figure_text.py`、`md20/report/evidence.py::evidence_rows`、`md20/report/workflow_report.py`

**支援的系統類型**：全流程、膜、CG 報告

**限制**：
- report-template 用合成資料，只證明圖會畫出來，不是科學驗證
- 日文與韓文未經母語者校對
- 報告為近似（互作只看距離準則的舊版仍有殘留處，以報告內標示為準）

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_report.py` | synthetic | `ci.yml:pure-python` |
| `tests/test_report_v2.py` | synthetic | `ci.yml:pure-python` |
| `tests/test_report_subsystems.py` | synthetic | `ci.yml:pure-python` |
| `tests/test_figure_rules.py` | unit | `ci.yml:pure-python` |
| `tests/test_figure_text.py` | unit | `ci.yml:pure-python` |
| `tests/test_evidence.py` | unit | `ci.yml:pure-python` |
| `tests/test_i18n_coverage.py` | unit | `ci.yml:pure-python` |
| `tests/test_report_template.py` | synthetic | `report-template.yml:template` |
| `tests/test_workflow_integration.py` | real_engine | `ci.yml:heavy[workflow]` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`partial`｜scientifically_benchmarked=`none`｜released_installer=`v0.1.0a17 (older code)`

**最後已知結果**：`stale`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：3PTB 全流程產出報告並斷言關鍵段落；其餘圖種是合成資料。證據之後改動的檔案（現況沒有 CI 結果）：`md20/report/figures.py`、`tests/test_report_subsystems.py`

**benchmark 範圍**：none

**已發行安裝程式**：v0.1.0a17 (older code)（a17 含較舊版本：4/5 個實作檔存在於 a17，1 個與 main 相同；main 的差異未發行）

<a id="gui_worker"></a>
## GUI（NiceGUI）與獨立計算子程序（worker）、重開接回

`gui_worker`

**實作**：`md20/gui/app.py`、`md20/gui/worker.py::run_worker`、`md20/gui/state.py`、`md20/gui/actions.py`

**支援的系統類型**：Windows／macOS／Linux 瀏覽器介面（127.0.0.1）

**限制**：
- 關 GUI 不中斷計算（D-103，開發者決定，使用者可推翻）
- worker 測試用 MD20_GUI_FAKE_RUN 假計算；真實引擎下的關 GUI→重開→接回沒有 CI 測試
- 筆電上關主控台視窗時子程序是否存活未實測
- 瀏覽器繪圖測試（playwright）在 openmm-stack 為 SKIPPED，只有 gui-preview 的截圖與點擊自測

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_gui_worker.py` | synthetic | `ci.yml:pure-python` |
| `tests/test_gui_stability.py` | unit | `ci.yml:pure-python` |
| `tests/test_gui_logic.py` | unit | `ci.yml:pure-python` |
| `tests/test_gui_views.py` | unit | `ci.yml:pure-python` |
| `tests/test_gui_v2_logic.py` | unit | `ci.yml:pure-python` |
| `tests/test_gui_advanced.py` | unit | `ci.yml:pure-python` |
| `tests/test_gui_server.py` | gui | `ci.yml:openmm-stack` |
| `tests/test_gate_actions.py` | unit | `ci.yml:pure-python` |
| `tools/gui_preview.py` | gui | `gui-preview.yml:screenshots` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`no`｜scientifically_benchmarked=`none`｜released_installer=`v0.1.0a17 (older code)`

**最後已知結果**：`stale`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：test_gui_server 啟動真實 NiceGUI 伺服器並請求每頁（GUI 檢查，不是引擎檢查）；gui-preview 截圖。證據之後改動的檔案（現況沒有 CI 結果）：`md20/gui/actions.py`、`md20/gui/app.py`、`md20/gui/worker.py`

**benchmark 範圍**：none

**已發行安裝程式**：v0.1.0a17 (older code)（a17 含較舊版本：3/4 個實作檔存在於 a17，1 個與 main 相同；main 的差異未發行）

<a id="licence_l1_terms"></a>
## 授權第 1 層：LICENSE 專有條款（D-124）

`licence_l1_terms`

**實作**：`LICENSE`

**支援的系統類型**：整個 repo／發行包

**限制**：
- 條文待法務審閱
- 公開 repo 不等於授權

**測試**：

無。

**狀態**：implemented=`yes`｜synthetic_tested=`no`｜real_engine_tested=`no`｜scientifically_benchmarked=`none`｜released_installer=`unreleased (main only)`

**最後已知結果**：`unverified`。依據：文件，無測試

**benchmark 範圍**：none

**已發行安裝程式**：unreleased (main only)（實作檔在 v0.1.0a17 樹中都不存在）

<a id="licence_l2_l3_verification"></a>
## 授權第 2–3 層：簽章授權驗證、機器碼、等級／功能／席次、撤銷清單、評估版浮水印、輸出授權編號（D-125、D-127、D-128）

`licence_l2_l3_verification`

**實作**：`md20/util/license.py::evaluate`、`md20/util/license.py::signature_ok`、`md20/util/license.py::require`、`md20/util/stamp.py`、`md20/util/owner_pub.pem`

**支援的系統類型**：驗證端；簽發端在私人 repo fstcch-cmd/md-digital-signature（不在本 repo）

**限制**：
- 只驗證不簽發；私鑰不在任何 repo；驗證不得有環境變數／設定／參數後門
- 離線時撤銷要等新清單送達；發行時需放入 revoked.json（目前沒有，等於無撤銷）
- Windows 工具與 GUI 卡片待真機／CI
- 擁有者需確認持有與 owner_pub.pem 成對的私鑰（D-127 未決）

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_license.py` | unit | `ci.yml:pure-python` |
| `tests/test_license_v2.py` | unit | `ci.yml:pure-python` |
| `tests/test_license_vector.py` | unit | `ci.yml:pure-python` |
| `tests/test_license_vector_v2.py` | unit | `ci.yml:pure-python` |
| `tests/test_stamp.py` | unit | `ci.yml:pure-python` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`no`｜scientifically_benchmarked=`none`｜released_installer=`unreleased (main only)`

**最後已知結果**：`stale`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：純 Python（含與簽發端對齊的測試向量）。證據之後改動的檔案（現況沒有 CI 結果）：`md20/util/license.py`、`md20/util/stamp.py`、`tests/test_license.py`、`tests/test_license_v2.py`、`tests/test_license_vector.py`、`tests/test_license_vector_v2.py`、`tests/test_stamp.py`

**benchmark 範圍**：none

**已發行安裝程式**：unreleased (main only)（md20/util/license.py 不存在於 v0.1.0a17 樹中；a17 只有舊版戳記（stamp.py），沒有簽章授權驗證）

<a id="licence_l4_distribution_protection"></a>
## 授權第 4 層：發行版 Cython＋AES-256-GCM（D-125 設計）

`licence_l4_distribution_protection`

**實作**：—

**支援的系統類型**：—

**限制**：
- 未開始；需要使用者建立 GitHub Secret

**測試**：

無。

**狀態**：implemented=`no`｜synthetic_tested=`no`｜real_engine_tested=`no`｜scientifically_benchmarked=`none`｜released_installer=`unreleased (main only)`

**最後已知結果**：`unverified`。依據：未實作

**benchmark 範圍**：none

**已發行安裝程式**：unreleased (main only)（沒有實作檔）

<a id="installer"></a>
## 安裝程式（Windows install.ps1、macOS install.sh、環境檔、啟動檔、doctor）

`installer`

**實作**：`installer/install.ps1`、`installer/install.sh`、`Install-MD20.cmd`、`Install-MD20.command`、`environment/base.yml`、`environment/linux-cuda.yml`、`environment/windows-opencl.yml`、`environment/windows-cuda.yml`、`environment/macos.yml`

**支援的系統類型**：Windows（PowerShell 5.1；NVIDIA／AMD／CPU）；macOS（CPU／OpenCL）

**限制**：
- CI 只測 CPU 路徑與 CUDA 環境 dry-run 求解；GPU 實際執行不在 CI
- 對外 a17 的 zip 對新安裝可能失敗（openmmforcefields 撤回版，D-95 釘選只在 main；STATUS 記載，本代理未重現）
- conda 環境尚未鎖版（CI 匯出 lock 檔為 artifact，但不是強制鎖定）；micromamba 已釘選 2.10.0-0（D-117）
- 乾淨安裝後的續跑／重連流程沒有 CI 專屬測試（R7 驗收項，未完成）
- 發行流程 release-windows.yml 在推 tag 時自動發行；本規格期間不得自動發行

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_installer_paths.py` | unit | `ci.yml:pure-python` |
| `tests/test_installer_pins.py` | unit | `ci.yml:pure-python` |
| `tests/test_stack_present.py` | real_engine | `ci.yml:openmm-stack` |
| `.github/workflows/ci.yml` | real_engine | `ci.yml:installer-windows` |
| `.github/workflows/ci.yml` | real_engine | `ci.yml:installer-macos` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`partial`｜scientifically_benchmarked=`none`｜released_installer=`v0.1.0a17 (older code)`

**最後已知結果**：`stale`，commit `580cbff`，證據 https://github.com/fstcch-cmd/md20-workstation/actions/runs/42374500293。依據：installer-windows、installer-macos 在 580cbff 成功（CPU 路徑 + doctor／demo／pipeline example／桌面啟動檔）。證據之後改動的檔案（現況沒有 CI 結果）：`installer/install.ps1`、`installer/install.sh`

**benchmark 範圍**：none

**已發行安裝程式**：v0.1.0a17 (older code)（a17 含較舊版本：9/9 個實作檔存在於 a17，7 個與 main 相同；main 的差異未發行）

<a id="analysis_cache"></a>
## 分析快取指紋與原子替換（R4，D-135）

`analysis_cache`

**實作**：`md20/analysis/fingerprint.py::analysis_fingerprint`、`md20/analysis/fingerprint.py::reuse_decision`、`md20/workflow.py::Workflow._reuse_analysis_manifest`

**支援的系統類型**：一般軌跡分析（膜-only 分析仍用舊的 PASS 規則）

**限制**：
- analyse_run 每次重算整個 run 的分析；recompute_parts 只供參考
- DCD 以頭尾雜湊辨識，中段改動且大小不變偵測不到

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_analysis_fingerprint.py` | unit | `ci.yml:pure-python` |
| `tests/test_analysis_run_wiring.py` | synthetic | `ci.yml:pure-python` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`no`｜scientifically_benchmarked=`none`｜released_installer=`unreleased (main only)`

**最後已知結果**：`unverified`，commit `-`，證據 。依據：只有容器純 Python 測試；尚無 CI 結果

**benchmark 範圍**：none

**已發行安裝程式**：unreleased (main only)（D-13x，2026-11-07 新增）

<a id="autonomy_ledger"></a>
## 有界自主行動帳本（R8，D-137）

`autonomy_ledger`

**實作**：`md20/autonomy/controller.py`、`md20/autonomy/ledger.py`、`md20/autonomy/cli.py`、`md20/autonomy/executors.py`、`md20/sampling/reassess.py`

**支援的系統類型**：補窗、延長、加重複、重新分析的提案

**限制**：
- 沒有擁有者以 `md20 autonomy policy set` 寫入的政策（核准者、允許動作、預算）就只提建議、不執行
- 傘狀窗口層級延長尚未接上 binding 公開 API
- 尚無真實 OpenMM 整合測試

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_autonomy.py` | unit | `ci.yml:pure-python` |
| `tests/test_autonomy_usable.py` | unit | `ci.yml:pure-python` |
| `tests/test_reassess.py` | unit | `ci.yml:pure-python` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`no`｜scientifically_benchmarked=`none`｜released_installer=`unreleased (main only)`

**最後已知結果**：`unverified`，commit `-`，證據 。依據：只有容器純 Python 測試；尚無 CI 結果

**benchmark 範圍**：none

**已發行安裝程式**：unreleased (main only)（D-13x，2026-11-07 新增）

<a id="funnel_standard_state"></a>
## 漏斗約束與解析標準態 ΔG°（A8，D-140）

`funnel_standard_state`

**實作**：`md20/sampling/funnel.py`、`md20/sampling/binding.py::run_binding`

**支援的系統類型**：單一配體從口袋拉離（restraint: funnel）

**限制**：
- 預設關閉（restraint: none）：真實引擎與筆電 3PTB 驗證前不改預設
- 只有漏斗結果可做親和力排序；徑向 1 M ΔG° 標為近似
- 約束作用在配體質心，長配體為近似

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_funnel.py` | unit | `ci.yml:pure-python` |
| `tests/test_binding_integration.py` | real_engine | `ci.yml:openmm-stack` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`no`｜scientifically_benchmarked=`none`｜released_installer=`unreleased (main only)`

**最後已知結果**：`unverified`，commit `-`，證據 。依據：只有容器純 Python 測試；尚無 CI 結果

**benchmark 範圍**：none

**已發行安裝程式**：unreleased (main only)（2026-11-08 新增）

<a id="metal_water_hydroxide"></a>
## 金屬配位水的 OH⁻ 選項（D-141）

`metal_water_hydroxide`

**實作**：`md20/build/metal.py`、`md20/build/metal.py::hydroxide_template_xml`

**支援的系統類型**：bonded 金屬位點，晶體有一個第一配位殼水，且提供擬合的 site_water 參數

**限制**：
- 預設仍為中性水；沒有擬合電荷時 NEEDS_HUMAN，不憑空給電荷
- LJ 沿用 ff14SB 羥基型態（未擬合）

**測試**：

| 檔案 | 類型 | CI job |
|---|---|---|
| `tests/test_metal_hydroxide.py` | unit | `ci.yml:pure-python` |
| `tests/test_metal_integration.py` | real_engine | `ci.yml:heavy[metal]` |

**狀態**：implemented=`yes`｜synthetic_tested=`yes`｜real_engine_tested=`no`｜scientifically_benchmarked=`none`｜released_installer=`unreleased (main only)`

**最後已知結果**：`unverified`，commit `-`，證據 。依據：只有容器純 Python 測試；尚無 CI 結果

**benchmark 範圍**：none

**已發行安裝程式**：unreleased (main only)（2026-11-08 新增）
