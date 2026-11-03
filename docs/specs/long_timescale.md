# Spec: 微秒級以上的模擬（專業模式）

狀態：全原子長時間模擬 **[已實作・待 CI]**（§6）；粗粒化 Martini 3 **[設計中，只有可驗證的骨架]**（§7）。2026-11-03，D-80。
使用者要求：專業版要能做到微秒級以上。

## 1. 實際可達的時間尺度（RTX 4060 筆電，估計，未實測）
| 系統 | 原子數 | 速度 | 1 µs 需要 |
|---|---|---|---|
| 蛋白＋配體（3PTB） | 約 3 萬 | 約 330 ns/day（實測 classroom） | 約 3 天 |
| 膜表面胜肽 | 約 5 萬 | 約 200 ns/day | 約 5 天 |
| 膜蛋白 | 約 12 萬 | 約 50–150 ns/day | 約 1–3 週 |
| 粗粒化 Martini 3 膜系統 | 約 1–2 萬珠 | 數 µs/day（時間步 20 fs） | 數小時到 1 天 |

## 2. 全原子長時間模擬需要補的功能
- 長度設定：專業模式可設到 10 µs；超過 1 µs 時顯示估計天數與硬碟用量，需要使用者確認。
- 儲存規劃：依長度自動調整存檔間隔（目標軌跡 ≤ 20 GB），可只存溶質；檢查剩餘磁碟空間。
- 中斷續跑：沿用既有的分段封存；加上自動開機續跑（`md20 resume --install-autostart` 已有）與睡眠防止。
- 多份獨立重複並行（多 GPU 或排隊）與合併分析。
- 長軌跡分析：分段串流讀取，不一次載入記憶體；叢集、PCA、MSM（狀態轉移）作為選用分析。
- 加速取樣（選用）：HMR 4 fs（已有）；GaMD 或 metadynamics 需要另寫規格。

## 3. 粗粒化路徑（Martini 3）
- 工具：martinize2（蛋白）、insane（膜）、Martini 3 參數；以 OpenMM 執行（MacCallum et al., Biophys J 2023 的實作）。
- 用途：膜破壞、脂質重排、胜肽聚集等微秒到毫秒現象。小分子用 Auto_Martini 類工具，品質不穩定時 NEEDS_HUMAN。
- 結果是珠子軌跡，不是原子結構；需要原子細節時 backmapping 後短時間全原子模擬。報告明寫解析度。

## 4. 驗證
- 全原子：3PTB 1 µs 筆電實跑，檢查續跑與存檔規劃。
- 粗粒化：純 POPC 膜性質與文獻比較；抗菌胜肽在膜上的已知行為（例如 magainin 2 形成孔洞的文獻條件）。

## 5. 想請審查者回答
- 教學與研究是否需要 GaMD 或 metadynamics？
- 粗粒化結果在報告中的呈現方式與限制說明。


## 6. 實作（2026-11-03）：全原子長時間模擬
程式：`md20/engine/longrun.py`（純 Python 規劃）、`md20/analysis/stream.py`（分段串流分析）。

### 6.1 什麼時候會規劃
- 正式模擬 **> 100 ns**（研究 tier 預設長度以上），或設定裡有 `md.long_run` 區塊時，`Workflow._plan_long_run` 在第一步之前規劃，
  結果寫進 protocol（因此也進 protocol hash）。**≤ 100 ns 的 protocol 與 hash 完全不變**，已在跑的 run 照常續跑。
- 取捨：100 到 1000 ns 之間、在本版之前已開始的 run，hash 會變，會被當成新 run（a8 今天才發行，判斷沒有這種 run；若有，
  設定 `md.long_run` 不會救回，需要人工處理）。

### 6.2 規劃內容（`plan_long_run`）
| 項目 | 規則 | 理由 |
|---|---|---|
| 軌跡存檔間隔 | 從 protocol 的值（20 ps）起，沿 1, 2, 5, 10, 20, 50, 100, 200, 250, 500, 1000 ps 取第一個讓 DCD ≤ `md.long_run.target_gb`（預設 20 GB）的值，上限 1000 ps | 每幀大小 = 56 + 3 × (4N + 8) bytes（讀 OpenMM `dcdfile.py` 確認） |
| 只存溶質 | `md.long_run.solute_only`：true／false／未設定。未設定時，全系統要拉到 > 100 ps 一幀且知道溶質原子數才自動改只存溶質（AUTO_FIXED） | 100 ps 以上一幀，接觸頻率與動態分析太稀疏 |
| 紀錄檔間隔 | 列數 ≤ 250 000（10 µs 時每 50 ps 一列） | 驗收會把整份紀錄檔讀進記憶體 |
| chunk 長度 | max(200 ps, 長度 / 500)，但每段不超過 1 小時計算時間（有效能測試時）；取兩個間隔的公倍數 | 當機最多損失一段；progress.json 不會長到數萬列；幀距跨 chunk 保持均勻 |
| chunk 檔保留 | `StageSpec.keep_chunk_states = 3`：只保留最新 3 段的 State XML 與 checkpoint；軌跡與紀錄檔全部保留 | 每段約 240 bytes／原子（估計）；1 µs、12 萬原子、每小時一段會累積 40 GB 以上 |
| 天數 | 長度 × 份數 ÷ ns/day（doctor 效能測試依原子數與步長換算，同 advisor） | |
| 磁碟 | 軌跡＋chunk 檔＋紀錄檔，乘份數；需要量 × 1.2 必須小於剩餘空間。剩餘空間 = `shutil.disk_usage` ＋ 這個 case 的 runs 資料夾已用量（續跑不會被自己的檔案擋下） | |

### 6.3 閘門（`long run`）
- **> 1 µs**：NEEDS_HUMAN，訊息含估計天數（沒有效能測試就寫「無法估計」，不猜）與硬碟用量。選項
  `md.long_run_confirmed: true`（GUI 一鍵）、`md.production_ns: 1000`。
- **> 10 µs**：NEEDS_HUMAN，選項縮短到 10000 ns 或改用 Martini 3。
- **磁碟不足**：NEEDS_HUMAN，選項只存溶質、`md.long_run.target_gb: N`（N 是放得下的大小）、縮短或搬資料夾。
- build 沒有原子數：擋下（不猜）。
- `DECISION_KEYS` 加入 `("md", "long_run_confirmed")`、`("md", "long_run")`；GUI 一鍵決定在 `md20/gui/actions.py`，四種語言標題與選項在 `gate_text.py`。
- 專業模式長度上限 `advisor.PARAMS["production_ns"]["max"]` 原本就是 10000；`advisor.check` 對 > 100 ns 顯示天數、硬碟與存檔間隔（> 1 µs 為 warning、> 10 µs 為 error），`estimate_hours` 多回傳 `days`、`disk_gb`。

### 6.4 引擎的增修（相容舊 run）
- `StageSpec.trajectory_atoms`（"all"／"solute"）與 `keep_chunk_states`（0 = 全留）；預設值不寫進 dict，舊 protocol hash 不變（測試）。
- `OpenMMBackend(trajectory_atoms="solute")` 用 `DCDReporter(atomSubset=…)`；溶質規則 `longrun.solute_atom_indices`：去掉水（HOH、WAT、TIP3…）與反離子（NA、CL、K…），保留結構金屬（ZN、MG、CA…）與脂質。
  OpenMM 沒有 `atomSubset` 時（TypeError）改存全系統並記在 `backend_info.dcd_atoms`。`backend_info` 記 `dcd_atoms` 與 `dcd_atom_count`。
- `chunks.run_stage`：先寫 progress（舊 chunk 標 `pruned`），再刪檔，所以當機只會多留檔案。`_verify_chunks` 跳過已刪除的 state；最新幾段損壞時退回最後一個還在磁碟上的 state，都沒有就從頭重跑這個 stage。

### 6.5 長軌跡分析
- `analysis/stream.py`：`StreamingMetrics`（Kabsch 疊合、RMSD 對第一幀、RMSF 以一階與二階累加、接觸頻率以殘基彙總），`iter_chunks`（預設 `mdtraj.iterload`，可注入 loader）。純 numpy，測試證明任何 chunk 大小都和整份計算一致。
- `traj.analyse_run`：只存溶質的 DCD 自動切拓樸、重新編號配體與金屬索引；原子數和拓樸算出的不一致就停止（不猜原子對應）。
  估計記憶體（幀數 × 原子 × 12 bytes × 3 份）超過 4 GB（`MD20_ANALYSIS_MEM_GB`）時，一般分析自動加 stride（AUTO_FIXED，寫入決策日誌），
  並以串流讀全部幀寫 `analysis/stream_metrics.json`（主鏈 RMSD、Cα RMSF、口袋接觸頻率）。
- 還沒做：叢集、PCA、MSM 的串流版本；報告尚未顯示 `stream_metrics.json`。

### 6.6 驗證
- 這裡（純 Python）：`tests/test_longrun.py`、`tests/test_stream.py`（規劃數字、閘門、hash 相容、chunk 刪除與續跑、workflow 閘門與一鍵選項、advisor）。
- CI openmm-stack：`tests/test_longrun_integration.py::test_solute_only_dcd_and_pruned_chunks`（6 個溶質原子的 DCD、chunk 檔只留 2 段、mdtraj 讀回、串流 RMSF）。
- 筆電：3PTB 1 µs（§4）。要量的數字：實際 State XML＋checkpoint 每原子大小（目前估 240 bytes）、DCD 大小與規劃是否一致、續跑。

## 7. 粗粒化 Martini 3：骨架（2026-11-03）
程式：`md20/build/martini.py`；指令 `md20 setup-cg`（先列出要安裝的東西，加 `--yes` 才執行，與 `setup-fold` 一致）。

### 7.1 查證過的事實（2026-11-03 讀原始碼）
| 工具 | 套件名 | 進入點 | 授權 | 來源與 commit |
|---|---|---|---|---|
| martinize2 | `vermouth`（pyproject；需要 Python ≥ 3.10，相依 networkx、numpy、scipy） | console script `martinize2 = vermouth.bin.martinize2:entry` | Apache-2.0 | github.com/marrink-lab/vermouth-martinize a9b62ee（2026-09-18） |
| insane | `insane` 1.2.0（setup.py；相依 numpy、simopt ≥ 0.4.0） | console script `insane = insane.cli:cli`；`-ff` 預設 `M3` | GPL-2.0-or-later | github.com/Tsjerk/Insane e23a501（2026-10-19） |
| martini_openmm | `martini_openmm` 0.1（只有 setup.py） | `MartiniTopFile(top, periodicBoxVectors=, defines=, epsilon_r=15).create_system(nonbonded_cutoff=1.1 nm)` | LICENSE 檔是 LGPL-3.0，README 寫 GPL v3（不一致，待問作者） | github.com/maccallumlab/martini_openmm 216e62b（2025-12-10） |
- martini_openmm 教學（tutorial/run.py）：Langevin 310 K、摩擦 10 ps⁻¹、步長 20 fs、ε_r 15、截斷 1.1 nm。README 的限制：Martini 2 膽固醇要換拓樸；itp 裡不能有算式。
- Martini 3 力場檔（`martini_v3.0.0.itp`、`martini_v3.0.0_phospholipids_v1.itp`、`martini_v3.0.0_solvents_v1.itp`、`martini_v3.0.0_ions_v1.itp`）**不在任何 pip 套件裡**；
  檔名與 M3 分子名（W、NA、CL）取自 martini_openmm 的測試系統（tests/popc_m3、tests/1k6u_en_m3）。insane 自己寫的拓樸只 include `martini.itp`，所以 MD20 自己組 `system.top`。
- 安裝用 GitHub 的 archive zip（`…/archive/<commit>.zip`）而不是 `git+https`：學生的 Windows 筆電通常沒有 git。這個容器連不到 PyPI 與 codeload，**安裝本身沒有在這裡驗證**。

### 7.2 計畫（`plan_cg_membrane`，不執行任何東西）
1. `martinize2 -f protein.pdb -x protein_cg.pdb -o protein.top -ff martini3001 -ignh -dssp -elastic -ef 700 -el 0.5 -eu 0.9`（`-dssp` 不給執行檔時用 mdtraj）
2. `insane -f protein_cg.pdb -o system.gro -p insane.top -pbc rectangular -x X -y Y -z Z -center -sol W -l POPC:1 [-salt 0.15]`
3. `compose_topology`：力場 include ＋ martinize2 的 molecule_*.itp ＋ insane 的 [ molecules ]（`Protein` 換成 martinize2 的分子）。
4. `build_openmm_system`：martini_openmm → `system.xml`。
- 沒安裝 → NEEDS_HUMAN（選項：`md20 setup-cg`、改用全原子）。缺力場檔 → NEEDS_HUMAN（選項：`cg.forcefield_dir`）。
- 彈性網路參數 700／0.5／0.9 是 Martini 3 教學常用值，**沒有查到原始出處**，待審查。

### 7.3 還沒做
- 沒有接上 workflow（沒有 `cg` 設定區塊與 CG protocol）；沒有 backmapping；小分子 Auto_Martini 路徑。
- CI 不安裝 vermouth、insane、martini_openmm；`test_martini_openmm_builds_a_system` 需要 `MD20_CG_TEST_DIR`（例如 martini_openmm 的 tests/popc_m3/openmm 複本），目前一律跳過。

## 8. 未決問題
- 1 µs 以上是否也要把 chunk 上限放寬到 2 小時（每段損失換較少檔案）？目前 1 小時。
- 只存溶質時，膜系統的脂質仍會存下（規則只去掉水與反離子）；膜系統要不要另一個「只存蛋白＋配體」選項？
- Martini 3 力場檔要不要由 `setup-cg` 從 martini_openmm 的 GitHub 測試資料夾下載（授權需確認），還是請使用者從 cgmartini.nl 下載？
- martini_openmm 授權 LGPL-3.0 與 GPL v3 的不一致。
