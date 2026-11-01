# MD20 單機教學版 — 狀態報告（2026-11-01，第四個 session）

本檔誠實分成三級:**(A) 真實跑過並通過** /（B）**寫好、靠 CI 驗證** /（C）**已知限制與未完成**。
原則:寧可標「未驗證」，不誇大。每次 push 後，CI 會把各 OS 的測試結果貼到該 commit 的留言。

CI 依據(`fstcch-cmd/md20-workstation`):
- **63d363b（第二個 session 最終版）openmm-stack**:**Windows OpenCL 124 passed、macOS 126 passed**,各只有 1 個失敗——`test_gui_pages_render`,原因是 NiceGUI 在子行程看到 pytest 環境變數就切到它自己的測試模式(非 GUI 本身問題),本 session 已修;Ubuntu `MD20_HEAVY=1` 重測結果見該 commit 留言。
- **f879764(第三個 session:閘門一鍵決定、3D 互作、金屬擬合參數、GUI server 測試修正)openmm-stack**:**Windows OpenCL 與 macOS 全綠**(含 `test_gui_pages_render`);Ubuntu `MD20_HEAVY=1` 重測卡在論文對接重現(已移出)。**ef32b48 的 Ubuntu 重測跑完:151 passed、4 failed,全是從未在 Ubuntu 跑完過的重測抓到的真 bug**,已修:(1)重複原子名閘門把 altloc A/B 同名原子算成重複(3KS3 被擋,兩個金屬整合測試因此失敗);(2)`DockingResult.load` 讀到戳記 `_md20` 欄位就當掉(全流程續跑時);(3)短 MD 篩 pose 的 2 ps stage 只記 4 筆 log → 無法驗收,且引擎用 +0 ps「延長」兩次白跑——現在短 stage 自動加密記錄、無法靠延長解決的直接 NEEDS_HUMAN;(4)workflow 讀 `pull_distance`(實際鍵名 `pull_distance_nm`),padding 一律被拉到 2.0 nm,且套到 apo 與篩選系統——全流程測試因此跑了 51 分鐘。
- **12dcd80 Ubuntu 重測:158 passed、1 failed**。全流程(3PTB,含 binding)、短 MD 篩 pose、金屬擬合參數(JSON)整合測試**在 Ubuntu 真跑通過**。唯一失敗:**幾何鍵結的鋅模型守不住配位**——最小化+2 ps MD 後 Zn–His94 NE2 由 2.03 Å 拉到 2.56 Å。原因:只排除了金屬–配位原子(1-2)非鍵作用,+2 的鋅仍與咪唑環上 CE1/CD2(1-3)及其氫有完整靜電斥力。已改成與一般共價鍵相同的處理:1-2、1-3 排除,1-4 依 Amber 縮放(靜電 ÷1.2、LJ ÷2),並加金屬–配位原子–鄰原子角項;待下一輪 CI 確認。Windows OpenCL 該輪因 `setup-vina` 遇 GitHub API 限流在測試前失敗(已修:token + 固定版本後備下載)。
- **第四個 session（審查 + HTS）**:純 Python 測試 **220 個本地全過**;以下皆 **待 CI**:(1)金屬鍵結模型補上經金屬的 1-3/1-4(37bc6b1 之後 CI 仍紅,見下);(2)引擎三個 watchdog/延長缺陷修正;(3)HTS 篩選整合測試;(4)缺口補建後主鏈連續性檢查。
  **更正先前聲稱**:「3D viewer 在 headless Chromium 實際繪圖」在 CI 三個 OS 都是 SKIPPED(playwright 不在環境裡),降為 B 級。
  37bc6b1 那輪 Ubuntu heavy 被下一個 push 取消前已印出 `test_bonded_zinc_ca2 FAILED`,所以「1-3 排除」並沒有修好鋅配位;本 session 加了 donor–donor 排除,待這輪確認。
  全部發現與處置見 `docs/REVIEW_2026-11-01.md`。
- 測試函式:約 220 個(pure-python 部分本地全過)。

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
| **金屬擬合參數** | test_metal_params | QM Hessian(Gaussian fchk / ORCA hess)→ 內座標轉換擬合鍵/角力常數(對已知諧和模型**完全還原**,含共用角);cluster 與蛋白位點以元素+最佳置換疊合對應;MCPB.py frcmod/mol2/pdb 轉譯(鍵角查表、RESP 電荷、原子名一致性);JSON 匯入;檢查閘門(r0 與晶體差、力常數範圍、電荷整數與力場一致);QM 小模型輸入產生(Cα 封端、電荷/多重度、開殼層擋關) |
| **GUI 檢視(WP13)** | test_gui_views、test_gui_logic | 閘門卡片、時間軸、即時曲線、3D 場景資料;pose 表顯示短 MD 結果。(headless Chromium 繪圖測試在 CI 恆 SKIPPED,見 B) |
| **HTS 篩選** | test_screen_library、test_screen_workflow | 化合物庫解析(別名、缺識別欄、重名)、假網路下載(重試/限速/快取/失敗記錄/名稱查詢預設關)、批次對接續跑與失敗隔離、排名/LE/誤差內標記、圖檔、篩選閘門(部分失敗、未選擇)、GUI 勾選寫回與失效、庫檔改變重篩 |
| **重跑正確性** | test_workflow_rerun | CLI 重跑沿用人工決定、config.json 相同不重寫、metal_params null、舊 case 的 MD 不沿用、RCSB 下載驗證、PDB ID 驗證 |
| **引擎(修正後)** | test_engine_fake | dt 減半仍跑滿模擬時間、retry 以 ramp 目標溫度重生、延長不重收緊約束 |
| **閘門一鍵決定** | test_gate_actions | 選項→設定修補(structure_override、metal_policy、human_choices、box、skip_redock、CPP、peptide_policy);需理由的選項必填;寫回 config.json、記 human 決策、自該步驟起失效重跑;**沒實作的選項不給按鈕、閘門維持擋關**(受體長 loop/未知殘基等) |
| **傘狀採樣智慧補窗** | test_adaptive_windows、test_umbrella_manual | 合成自由能剖面＋精確偏壓取樣:陡牆案例舊規則留斷點、新規則補成連續且 PMF 誤差較小;每 window 各自 k 的 WHAM/MBAR;極端能障明確回報補不起來;覆蓋圖資料、手動區間補採樣只重開單一目標(真實 OpenMM 路徑待 CI) |
| **3D 互作標示** | test_gui_views | 逐幀幾何互作(氫鍵候選 N/O ≤3.5 Å 未檢查角度、疏水 C–C ≤4.0 Å、配體–金屬 ≤2.8 Å)+ 殘基佔有率表;vdW 球表面近似 |
| 工作流程閘門 | test_workflow_gates | 共晶盒必做 redocking、盲對接需同意、結合計算加大 padding、**binding 讀取組裝後原子索引(L01 迴歸)** |
| 胜肽/CPP、結構可信度、續跑/鎖、資源模式、PMF/採樣、專案/佇列/報告/doctor/stamp | 各檔 | 同前版 |

### A2. 真實 OpenMM + Vina(CI openmm-stack)
| 測試檔 | 內容 | 狀態 |
|---|---|---|
| test_openmm_integration | 平台選擇、HMR、benchmark、doctor | 三平台綠(a72ba6b:mac/win) |
| test_real_case_integration | 3PTB 建模 + 短 MD;胜肽 | 同上 |
| test_docking_integration | 苯甲脒 redocking RMSD<2Å;多配體 | 同上 |
| test_binding_integration | NaCl PMF;水盒過小擋關;**拉離路徑被擋(WP9)** | **f879764:Windows OpenCL / macOS 真跑通過** |
| test_workflow_integration | 3PTB 全流程(含 binding);**短 MD 篩 pose(WP5)** | Ubuntu 重測,見 B |
| test_binding_integration / test_real_case / test_docking / test_openmm | NaCl PMF、拉離路徑閘門(WP9)、3PTB 建模與胜肽、redocking、平台/HMR/doctor | **63d363b:Windows OpenCL 與 macOS 真跑通過** |
| test_metal_integration | **CA II(3KS3)Zn–His3 鍵結模型**:建模、互變異構體、力項、最小化+MD 後鍵長維持;**JSON 擬合參數套用與 r0 偏差擋關**;QM 小模型輸入產生 | Ubuntu 重測,見 B |
| test_gui_server | **啟動 `md20 gui` 並請求每個頁面與 /viewer**(含閘門一鍵按鈕) | **f879764:Windows OpenCL / macOS 真跑通過** |

### A3. 使用者實機(先前回報)
- Windows 10 + GTX 1060 → OpenCL,約 200 ns/day。
- HCC Lab 戳記端到端驗證:私鑰可解開 demo 輸出的加密溯源。

---

## B. 寫好、靠 CI 驗證(開發容器裝不了 OpenMM/NiceGUI,也連不到 PyPI/npm/RCSB)
- **3D viewer headless 繪圖**(`test_viewer_renders_in_headless_browser`):需要 playwright,CI 環境沒有 → 從未執行過;只有純資料層測試是 A 級。
- **HTS 真下載＋真 Vina**(`test_screen_integration.py`,3PTB + PubChem/RCSB):待 openmm-stack。
- **金屬 1-3/1-4 經金屬排除**是否讓 3KS3 的 Zn–His 守住:待 Ubuntu heavy(現在 main 不再被取消)。
- **受體缺口**:無 SEQRES 時擋關、補建後 CA–CA 檢查,真實 PDBFixer 路徑待 CI。
- 第二個 session 加入的真實路徑測試(上表粗體)以最新 commit 的 CI 留言為準;若某項紅,留言含失敗 log,會在下一個 commit 修正並更新本檔。
- **兩篇論文的對接重現從未在 CI 跑完過**(更正先前說法):六配體同時對接(28×34×26 Å 盒)與 7 胜肽對接(36×51×45 Å 盒、exhaustiveness 32)在 4 核 runner 上要數小時,之前每輪都被取消或在更早處失敗。已移到獨立、不阻擋的 CI 工作 `paper-docking`(exhaustiveness 8,JSON 標明為縮減搜尋)。PDB 判定(1VKF→1VKX)、殘基存在性、結構閘門這幾項**輕量**驗證則每輪都有跑、有 JSON。

---

## C. 已知限制與未完成(誠實交代)

### C1. 論文驗證案例(教學背景用)
- **hsieh2024**(NF-κB RELA,六配體同時對接):論文標 PDB 1VKF,但 1VKF 是 *Thermotoga* 蛋白;系統判定正解為 **1VKX**。
- **hsieh2025**(Keap1-BTB 4CXT,胜肽 GGGGGKP):胞內標靶但淨電荷 +1,**CPP 閘門擋下並給替代設計**;「covalent bonding」實為凡得瓦接觸;盒子比整個 domain 還大(等同盲對接)。
目的是示範把關流程,不是逐位重現論文數字。

**論文對接重現(CI `paper-docking`,ef32b48,exhaustiveness 8 縮減搜尋)——第一次跑完**:
- **hsieh2025**(4CXT,GGGGGKP,91 s):第 1 名 −5.91 kcal/mol(論文 −5.22);第 1 名 pose 與論文報告的接觸殘基 recall **100%**,第 2–5 名 0–100%。
- **hsieh2024**(1VKX,六配體同時對接,38 分):聯合分數 −11.7(論文 −13.86),但六個配體與論文殘基的 recall **全為 0**——落點在論文口袋之外;系統**拒絕推薦任何 pose**:口袋可用體積約 107 Å³、六配體總體積約 1386 Å³,建議改 independent 對接。這正是要教的:分數接近不代表結合模式對,而同時塞六個配體進一個口袋在幾何上就不成立。
- **hsieh2024 不可重現的原因已確定(37bc6b1 盒子幾何檢查)**:論文盒子尺寸若照字面 28.5×34.5×26.25 Å,框不到任何報告殘基(0/11);
  若是把 AutoDockTools 的**格點數 76×92×70 直接當 Vina 的 Å 填**,盒子 76×92×70 Å 會框到全部 9 個存在的報告殘基。盒子中心是 1VKX 的有效座標
  (距原子 0.48 Å),在 1VKF 中則落在蛋白外 39.6 Å——先前「中心來自其他座標系」的推論錯誤,已更正。

### C0. 審查發現但本 session 未修(細節見 `docs/REVIEW_2026-11-01.md` §2)
- 對接配體直接配位金屬不會被擋(金屬 policy 在配體加入前執行);`map_pose_onto_reference` 的 order 後備可能錯配;
  `sampling/runner.py` 未被使用但有錯(勿用);自適應補窗端點碰撞「假新增」與 `min_effective_samples` 門檻;
  Vina/micromamba 下載無 pin、無 sha256,環境未鎖定;戳記第三層是加密不是簽章,證明不了作者。
- **HTS 篩選**:分數只用最佳 pose 的 Vina 分數(縮減搜尋),去鹽取最大片段可能誤刪季銨鹽/金屬配合物;名稱查 PubChem 預設關閉。

### C2. 刻意簡化或未做
- **短 MD 篩 pose**只排除會散開的 pose,不以短 MD 排名結合強度;非 research tier 預設關閉。
- **金屬鍵結模型**預設是晶體幾何的諧和鍵/角(電荷沿用力場)。**擬合參數**可由三種來源匯入(`metal_params`):QM Hessian(內建轉換,電荷仍沿用力場)、MCPB.py 輸出(含 RESP 電荷;二面角與金屬 LJ 不轉譯)、JSON。QM 計算本身(ORCA/Gaussian)在程式外執行;程式負責產生小模型輸入與檢查結果。配體直接配位金屬、少於 3 個蛋白配位原子一律 NEEDS_HUMAN。配位水被移除(位置開放,報告標註)。開殼層金屬的 QM 電荷/自旋不猜,需使用者指定。
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
