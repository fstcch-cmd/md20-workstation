# 金屬位點：policy、幾何鍵結模型、擬合參數、QM 小模型

## 1. Policy（`metal_policy`，依元素 "ZN" 或位點 "ZN:A262"，位點優先）　[已驗證：結構閘門與 pure 測試]
- `remove`：使用者確認非功能必要才移除。
- `keep_nonbonded`：力場非鍵結離子 + 1000 kJ/mol/nm² 位置約束（production 也不解除），報告標註配位幾何不保證。
- `bonded`：鍵結模型（見下）。**D-133 起**：晶體中直接配位在該金屬上的水（O ≤ 2.6 Å）一併保留並鍵結，配位數與晶體一致。
- `bonded_open`（D-133）：舊的鍵結模型，不加回配位水、位點開放；只在配體要佔該位置時使用。
- 口袋 6 Å 內的過渡金屬沒有 policy → 結構閘門 NEEDS_HUMAN（WP6），GUI 一鍵選擇。
- 擋關：< 3 個蛋白配位原子、配體直接配位、His 兩個氮同時配位、未知 policy、缺力場樣板。

## 2. 幾何鍵結模型　[已實作・修正待 CI]
- 金屬–配位原子諧和鍵（晶體距離，k = 2×46 kcal/mol/Å²）、配位原子–金屬–配位原子角（晶體角，k = 2×25 kcal/mol/rad²）。
- 配位殘基質子化：Cys SG → CYM；His NE2 配位 → HID、ND1 配位 → HIE。
- **2026-11-01 修正（CI 抓到）**：原本只排除金屬–配位原子（1-2）非鍵作用；3KS3 鋅位點在最小化 + 2 ps 後 Zn–NE2 由 2.03 拉到 2.56 Å。
  原因：Zn²⁺ 與咪唑環上 CE1/CD2（1-3，約 3 Å）及其氫仍有完整靜電斥力。現在比照一般共價鍵與 MCPB.py/ZAFF：
  1-2、1-3 排除，1-4 縮放（靜電 ÷1.2、LJ ÷2），並加金屬–配位原子–鄰原子角（晶體角，50 kcal/mol/rad²）。
  純邏輯 `bonded_metal_terms` 有單元測試；鍵長是否守住待 Ubuntu 重測（`test_bonded_zinc_ca2`，容許 0.3 Å）。

## 3. 擬合參數（`metal_params`）　[已實作；JSON 路徑已在 Ubuntu 真跑通過（12dcd80）]
三種來源 → 同一內部格式（OpenMM ½k 慣例），覆蓋幾何模型的常數：
- `hessian`（內建，不需 AmberTools）：讀 Gaussian `.fchk` 或 ORCA `.hess` → cluster 以「元素＋最佳置換 Kabsch 疊合」對應到蛋白位點（不靠原子順序）→
  笛卡爾 Hessian 以 **Wilson B 矩陣 pseudo-inverse** 轉成位點內座標力常數（金屬–配位鍵、配位–金屬–配位角，並納入配位原子自己的鍵角以吸收耦合）。
  測試：對已知諧和模型完全還原（含共用角；modified Seminario 在共用角會高估約 30%，所以不用它；Seminario 鍵值只當交叉檢查）。
- `mcpb`（轉譯 MCPB.py 輸出）：frcmod 鍵角依原子型態查表；mol2 RESP 電荷套用到金屬與配位殘基（原子名一致性、電荷總和必須是整數且等於力場原本的整數）；二面角與金屬 LJ 不轉譯。
- `json`：手填或其他工具，鍵可用 `HIS94:NE2`／原子名／元素為鍵。
- 共同檢查：每個配位原子都要有鍵；r0 與晶體差 ≤ 0.25 Å；θ0 差 ≤ 15°；k 在合理範圍；否則 NEEDS_HUMAN，GUI 可一鍵改回幾何模型或 keep_nonbonded。

## 4. QM 小模型輸入　[已實作・待 CI]
幾何模型建模時自動在 `build/metal_qm/<site>/` 產生：金屬 + 配位側鏈（Cα→Cβ 切、H 封端 1.09 Å）、`cluster.xyz`、
`orca.inp`（B3LYP-D3BJ/def2-SVP Opt+Freq，Cβ 固定）、`gaussian.gjf`、中文 README。電荷由質子化變體算出；
**開殼層金屬（Fe/Cu/Mn/Co/Ni）不猜氧化態與自旋**，需 `qm_charge`、`qm_multiplicity`。

## 4b. 配體直接配位金屬（D-17）　[已實作・待 CI]
組裝時配體加入後重新掃描：配體 N/O/S 在金屬配位距離內 → NEEDS_HUMAN（換 pose／MCPB.py 參數化後匯入／移除金屬）。
本版不自動處理配體–金屬鍵。

## 4c. 鋅平均鍵長偏 0.3 Å 的修正計畫（D-34，2026-11-02）　[H1 已證實並修正，D-133；待 heavy-metal CI]
現象：3KS3（CA II）幾何鍵結模型，2 ps 後平均 Zn–His94 NE2 2.34 Å（r0 2.03、σ ≈ 0.08 Å）——系統性外移，不是雜訊。
`K_BOND` 46 kcal/mol/Å² 已在 ZAFF Zn–N(His) 40–60 範圍內，單靠加大 k 至 60 只能減少約 25% 的偏移，所以先找推力來源：
- **H1 第四配位（水／氫氧根）**：CA II 的 Zn 是 His₃ + OH⁻/H₂O。建模移除了晶體水，溶劑水會以純非鍵方式擠進第四位，
  +2 與 O 的強靜電把 Zn 拉離三個 His。修法：晶體中距金屬 ≤ 2.3 Å 的水保留並納入鍵結（M–O 鍵＋角），或明確閘門要求使用者決定。
- **H2 力常數表**：依元素×配位原子（會診 §3 Q2：Zn–N 40–60、Zn–S 70–90、Zn–O 80–100 kcal/mol/Å²），QM 擬合覆蓋。
- **H3 金屬 LJ**：鍵結模型應用 Li–Merz IOD（TIP3P）12-6 參數，目前沿用力場離子參數（HFE 或 IOD 待查）。
步驟：(1) heavy metal 測試在失敗訊息附上「3 Å 內非鍵重原子與平均距離」診斷（本次）；(2) 依證據實作 H1／H2／H3，各自記決策；
(3) 依 D-29 約定不放寬測試。

### 4d. D-133 結果（2026-11-07）
- **證據**：CI job 128427389578（`58d81bc`）診斷：GLU106:OE1 距 Zn **1.74 Å**（20/20 幀）、CD 2.48 Å；三個 Zn–N 全部被拉長（2.30／2.25／2.36 Å，r0 2.03／2.04／2.02）。
  是附近帶負電的羧基，不是溶劑水，塌陷到開放的第四位點（12-6 點電荷下 Zn²⁺–O⁻ 沒有足夠排斥）。H1 成立；H2 加大 k 也無法阻止整個位點被拉走，H3 不是主因。
- **程式缺陷查核**（無）：原子對應（`find_sites` 以距離與殘基名，三個 His 正確）、質子化（HID/HID/HIE 依配位氮，測試斷言）、1-2／1-3 排除與 1-4 縮放（`bonded_metal_terms` 單元測試）、
  參數來源（K_BOND 46 kcal/mol/Å² 在 ZAFF 範圍）都正確；缺的是模型的第四個配位。
- **修正**：`receptor.prepare_receptor` 把配位在保留金屬上的晶體水另存 `metal_site_waters.pdb`（**不放進對接用受體**）；`assemble_system` 只對 policy 為 `bonded`、沒有 `metal_params` 的位點把它加回（O＋自動加氫，TIP3P），
  `plan_site` 把它當第四個鍵結配位（晶體距離、同 K_BOND、D–M–D 角含水共 6 個；不加 M–O–H 角，水可轉動；Zn–H 為 1-3 排除）。
  配體重原子距該水 O < 2.2 Å → NEEDS_HUMAN「metal site water vs ligand」（選項：`bonded_open`、改選 pose、`keep_nonbonded`）。
- **未改**：Zn–N 的 k 與 r0（證據不支持）、測試門檻 0.03 nm（不放寬）、擬合參數路徑（只涵蓋擬合過的配位原子，不加水）。
- **限制**：配位水以中性 TIP3P 表示；CA II 鋅水 pKa ≈ 7，實際可能是 OH⁻（淨電荷不同），本版不提供 OH⁻ 模型，報告標註。

## 5. 未做
配體直接配位金屬（需配體–金屬 QM 模型）；金屬 LJ 擬合（12-6-4）；RESP 由本程式計算。

## 6. 想請審查者回答
1. 1-4 縮放對金屬是否合適？MCPB.py 的作法是否同時重新指定金屬的 LJ（例如 Li–Merz 12-6 CM 參數）？
2. 幾何模型的力常數（46/25/50 kcal）是否應依金屬種類（Zn/Fe/Cu）不同？
3. Wilson-B 轉換在冗餘內座標下的物理意義（pseudo-inverse 分配）是否可接受？是否應改用 Seminario 鍵 + B 矩陣角的混合？
4. QM 小模型的方法（B3LYP-D3BJ/def2-SVP）對教學是否足夠？
