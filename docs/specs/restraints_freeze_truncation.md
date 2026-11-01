# 約束策略、凍結、口袋截斷模型與資源估算

狀態：**§3.1 分組約束＋分階段釋放已實作（D-23，2026-11-01）；§3.1 智慧建議、§3.2–3.4 仍為 [設計中]**。使用者需求（2026-11-01）：約束要隨 minimization → NVT → NPT → production 分階段下降；提供凍結
（整條主鏈、指定殘基）；約束與凍結都要能智慧化建議，讓使用者直觀地降低運算資源；也允許整顆蛋白自由模擬。
已加入的引擎掛鉤（D-23 起由 `make_protocol(restraints=…)` 使用）：`StageSpec.restraint_groups`（每組 [起, 迄] 倍率）、`StageSpec.freeze`，
`chunks._apply_schedule` 會逐批設定 `msw_rs_<group>`；兩個新欄位在預設值時不進入 protocol 雜湊（進行中的 run 可續跑）。

## 1. 現況（已存在）
- `add_position_restraints`：蛋白主鏈重原子 k = 1000、配體重原子 k = 500 kJ/mol/nm²；側鏈不約束。
- 單一全域倍率 `msw_restraint_scale`：minimize 階梯 1.0 → 0.5 → 0；NVT 1.0 → 0.2（升溫同時釋放）；NPT 0.2 → 0；production 0。
- WP4 已處理：絕對位置約束 + MonteCarloBarostat 會偏壓盒子體積，所以約束主要在 NVT 釋放，NPT 只剩 0.2。

## 2. 關鍵事實（決定設計方向）
**在 OpenMM（以及使用 Verlet cutoff 的現代 GROMACS）中，凍結原子幾乎不省運算。**
OpenMM 以質量 0 凍結：積分器不移動它，但所有力（含凍結原子彼此之間的非鍵作用）照算；MD 成本主要在力的計算。
因此：
- 凍結的價值在**穩定性與教學隔離**（例如截斷模型的邊界、低信心區域），不是速度；
- 真正省資源的是**減少原子數** → 口袋截斷模型（使用者已確認要做）。

凍結的技術陷阱：
1. 兩個都是質量 0 的原子之間不能有 constraint（HBonds 下 X–H 若兩者都凍結會出錯）→ 必須移除這些 constraint。
2. MonteCarloBarostat 會縮放所有分子（含凍結原子）的位置 → 凍結與 NPT 不相容 → 凍結只用在 production，且 production 改 NVT（體積取 NPT 平衡末段）。
3. HMR 要先做（把質量從重原子移到 H），再把凍結原子質量設 0。
4. 凍結原子的位置約束沒有意義，從約束力中移除。

## 3. 設計

### 3.1 分組約束 + 分階段釋放
- 約束力拆成數組，各有全域參數 `msw_rs_<group>`，表達式 `0.5·msw_restraint_scale·msw_rs_<group>·k·d²`
  （保留主倍率，舊流程、watchdog、binding 的主倍率控制都不變）：
  `backbone`（N CA C O）、`sidechain`（蛋白其他重原子）、`ligand`（配體重原子）、`shell`（截斷模型邊界殼層，全程不釋放）、
  `prefreeze`（將被凍結的原子，平衡期間強約束、production 改凍結）。
- 預設策略（每組 [起, 迄]，主倍率固定 1.0）——**依會診 §1 Q1 修正後的實作值**（原設計表保留於下方「原設計」）：

| 策略 | minimize | NVT（升溫） | NPT | production |
|---|---|---|---|---|
| standard（預設） | 主倍率階梯 1.0→0.5→0，各組 1 | bb 1→1、sc 1→0.5、lig 1→1 | bb 1→0、sc 0.5→0、lig 1→0 | 0 |
| gentle | 同上 | bb 1→1、sc 1→1、lig 1→1 | 全部 →0，NPT 長度 ×2 | 0 |
| hold_backbone | 同上 | 同 standard | bb 1→0.05、sc 0.5→0、lig 1→0 | bb 0.05（50 kJ/mol/nm²）全程；RMSD／RMSF 標「受約束」 |

- 實作細節：單一力 `msw_position_restraints`，每粒子 `k, x0, y0, z0, grp`（0 主鏈、1 側鏈、2 配體），
  表達式 `0.5·msw_restraint_scale·k·(δ(grp)·msw_rs_backbone + δ(grp−1)·msw_rs_sidechain + δ(grp−2)·msw_rs_ligand)·d²`。
  k 主鏈／側鏈／配體皆 1000 kJ/mol/nm²（配體原 500：最小化時配體 ≥ 蛋白）。`shell`、`prefreeze` 組待截斷／凍結實作時再加（grp 3、4）。
  SMD／umbrella 把側鏈與配體 k 設 0，只留主鏈（主倍率 = `backbone_restraint_scale`）。
- 原設計（被會診修正，保留歷史）：standard NVT bb 1→0.5、sc 1→0.1、lig 1→0.5，NPT 全 →0；理由是 WP4 擔心約束＋barostat 偏壓體積——
  會診指出 Amber／Desmond 都在 NPT 中釋放、k ≤ 1000 時偏差可忽略，因此改為 NVT 只升溫。

- **智慧建議**（`recommend_restraint_strategy`，寫 DecisionLog）：
  - 解析度 > 2.5 Å、AlphaFold 模型或低 pLDDT、PDBFixer 補過 loop、對接 pose 有碰撞、胜肽配體、金屬鍵結模型 → gentle；
  - 短 production（< 1 ns）或截斷模型 → hold_backbone 選項提示；
  - 其餘 → standard。使用者可在 `md.restraints` 指定覆蓋。

### 3.2 凍結選項（`md.freeze`）
- `none`（預設）、`backbone`（蛋白主鏈重原子）、`residues: "A:10-50, A:200"`、`beyond: R`（離任何配體重原子 > R Å 的整個殘基）。
- 建模時算出凍結原子集合寫入 build manifest；engine 在 `spec.freeze` 的 stage 建 backend 時：HMR → 質量 0 → 移除雙凍結 constraint → 移除其位置約束。
- production 自動改 NVT（記錄決策）；平衡期間這些原子屬於 `prefreeze` 約束組。
- 閘門：凍結口袋（配體 6 Å 內）殘基 → NEEDS_HUMAN（會扭曲結合）；凍結 + 結合自由能計算 → 提示 PMF 不含被凍結部分的重排。
- 報告與 GUI 誠實寫明「凍結不會明顯加速」。

### 3.3 口袋截斷模型（`md.truncate`）
- 保留任一重原子距配體（或 docking box 中心，apo 用同一參考點）≤ R（預設 12 Å）的殘基；同鏈相鄰保留段之間缺口 ≤ 3 殘基時一併保留（避免碎片）。
- 截斷處加帽：前一殘基的 CA→ACE CH3、C、O；下一殘基的 N、CA→NME C；刪除帽殘基的其他原子與所有 H，再以 `Modeller.addHydrogens` 補氫（既有殘基沿用原質子化變體，與金屬模組相同作法）。
- 最外 4 Å 殼層（R−4 到 R）的重原子屬 `shell` 約束組（全程，含 production），可選擇改為凍結。
- 溶劑化照常（盒子跟著變小）。截斷 + 結合自由能：拉離距離需小於截斷半徑，否則閘門；報告標註 PMF 為截斷模型近似。
- 先用 3PTB 驗證：原子數、能量最小化、短 MD 下殼層外的 RMSD。

### 3.4 資源估算（`md20/build/resource_plan.py`）
- 原子數估算：盒邊 = 蛋白（或截斷片段）最大跨度 + 2×padding；水分子數 ≈（盒體積 − 0.018 nm³×重原子數）×33.4/nm³。
- 速度：doctor benchmark（ns/day @ N_bench 原子）× N_bench/N（PME ≈ N log N，近似線性）。
- 表格（GUI 與報告）：全蛋白／主鏈凍結（≈ 全蛋白，誠實寫出）／截斷 R=12／截斷 R=15 → 原子數、估計 ns/day、目標長度 ETA。
- 規則：全蛋白 ETA 超過使用者時間預算（預設 24 h）→ 建議截斷（AUTO_FIXED 建議，不自動套用）；GUI 一鍵採用。

## 4. 想請審查者回答
1. 預設策略的數值（各組起迄、NPT 是否仍保留少量主鏈約束）是否合理？藥廠常用的 Amber/Desmond 預設是什麼？
2. 截斷模型用位置約束殼層 vs 凍結殼層，哪個較好？殼層厚度 4 Å 是否足夠？
3. 截斷處用 ACE/NME 帽 vs 中性末端（NH2/COOH）？截斷後淨電荷改變由反離子中和是否足夠？
4. 截斷模型做 SMD/umbrella 的可信度？是否應禁止或只允許定性比較？
5. 凍結 + NVT production 的體積選擇（NPT 末段平均 vs 最後一幀）？
6. 有沒有比截斷更好的「筆電省資源」方案（例如隱式溶劑 GBn2 短跑、較小 padding + 較長截斷距離的權衡）？
