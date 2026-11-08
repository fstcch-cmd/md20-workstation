# 金屬位點：policy、幾何鍵結模型、擬合參數、QM 小模型

## 1. Policy（`metal_policy`，依元素 "ZN" 或位點 "ZN:A262"，位點優先）　[已驗證：結構閘門與 pure 測試]
- `remove`：使用者確認非功能必要才移除。
- `keep_nonbonded`：力場非鍵結離子 + 1000 kJ/mol/nm² 位置約束（production 也不解除），報告標註配位幾何不保證。
- `bonded`：鍵結模型（見下）。**D-133 起**：晶體中直接配位在該金屬上的水（O ≤ 2.6 Å）一併保留並鍵結，配位數與晶體一致。**D-141**：該水可改為氫氧根（`metal_water_state`，需擬合參數，§4e）。
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
幾何模型建模時自動在 `build/metal_qm/<site>/` 產生（D-141 起 cluster 也含配位水 H₂O，見 §4e）：金屬 + 配位側鏈（Cα→Cβ 切、H 封端 1.09 Å）、`cluster.xyz`、
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
- **D-139**：只鍵結第一配位殼的水：金屬–O ≤ Harding 目標距離＋0.25 Å（Zn 2.34 Å）；3KS3 的第二個水（2.57 Å）只回報、不鍵結、不加回。
- **限制**：配位水以中性 TIP3P 表示；CA II 鋅水 pKa ≈ 7，實際可能是 OH⁻（淨電荷不同），報告標註。**D-141 起可選 OH⁻（需擬合參數），見 §4e。**

## 4e. 配位水的質子化選項：氫氧根 OH⁻（D-141，2026-11-08）　[已實作・純邏輯測試；真實引擎待 CI]
擁有者於 2026-11-08 授權加入選項。CA II 鋅水 pKa ≈ 7，兩種狀態都合理；X 光看不到質子，所以**程式永遠不自動決定**，預設仍是中性 TIP3P 水（§4d），報告標註照舊。

**設定**：`metal_water_state: {"ZN:A262": "hydroxide"}`（鍵可用位點或元素，位點優先；值 `water`（預設）或 `hydroxide`）。已列入 `workflow.DECISION_KEYS`，`pipeline run` 會沿用。

**一定要有擬合參數**：OH⁻ 結合金屬時的電荷與 M–O 鍵不在 amber14／OpenMM 樣板裡，程式不憑空設定。`metal_params` 新增選用區塊 `site_water`
（任何來源皆可；json 放在檔案或 data 內，hessian／mcpb 放在 `source` 旁）：
```json
"site_water": {"state": "hydroxide",
               "charges": {"O": <RESP 的 O>, "H": <RESP 的 H>},          // 必填（mcpb 可由 mol2 讀）
               "metal_charge": <選填>,
               "bond": {"k_kcal_A2": k, "r0_A": r},                       // json；hessian 由 QM cluster 擬合，mcpb 由 frcmod 查表
               "angles": {"default": {"k_kcal_rad2": k}},                 // json：D–M–O 角（也可沿用全域 angles）
               "angle_MOH": {"k_kcal_rad2": k, "theta0_deg": θ},          // 選填；沒有就不加 M–O–H 角
               "residue": "OH1", "O_atom": "O", "H_atom": "H"}            // 只有 mcpb：OH 殘基在 MCPB mol2 的名稱
```
- **檢查（純函式，`check_site_water_block`、`site_water_charge_problems`）**：state 必須是 hydroxide；O 與 H 都要有（缺 H、多一個 H 都擋）；未知欄位擋；
  列出的電荷總和必須是整數；只列 O、H 時要等於 −1（總和 0 是水不是氫氧根）；加了金屬電荷時要等於氧化態 − 1（Zn／Cd／Mg／Ca：+1）；
  另外列了殘基電荷（MCPB RESP）時只檢查整數，與力場是否同一個整數由 `add_metal_forces` 在 System 建好後檢查（既有的 `metal charges` 閘門）。M–O 的 r0 與晶體差 ≤ 0.25 Å、k 在 10–400 kcal/mol/Å² 內，與其他配位原子同一套檢查。
- **M–O 鍵與 D–M–O 角**：氫氧根的 O 就是第四個配位原子。json 讀 `site_water.bond`；hessian 把 O 放進一起擬合（QM cluster 含 OH⁻，見下）；mcpb 查 frcmod（`M-oh`、`D-M-oh`、選填 `ho-oh-M`）。
- **D-133 的調整**：擬合參數原本不加回水；有 `site_water` 區塊且 `metal_water_state: hydroxide` 時才加回並以擬合參數鍵結。沒有區塊時行為不變。

**決定流程（`decide_water_mode`）**
| `metal_water_state` | policy | `site_water` | 結果 |
|---|---|---|---|
| 未設／`water` | `bonded`，無 `metal_params` | — | 中性水（現況） |
| 未設／`water` | `bonded`，有 `metal_params` | 無 | 不加水（D-133） |
| 未設 | `bonded` | **有** | NEEDS_HUMAN：衝突，請明確選 hydroxide 或 water |
| `water` | `bonded` | 有 | 忽略區塊並在 caveats 說明 |
| `hydroxide` | `bonded`，有區塊 | 有 | 氫氧根（AUTO_FIXED） |
| `hydroxide` | `bonded`，無區塊 | 無 | NEEDS_HUMAN「metal water state」（下） |
| `hydroxide` | `bonded_open`／`keep_nonbonded`／無 | — | NEEDS_HUMAN（氫氧根是鍵結模型的第四配位） |
晶體第一殼（§4d 的 Harding 上限）沒有水、或有多個水時也擋（不憑空放氧、不猜哪一個是氫氧根）。

**閘門 `metal water state <位點>`**（四語標題與說明在 `gui/gate_text.py`）：選項 (1) `metal_water_state: {…: water}` 一鍵維持中性水；
(2) 產生含氫氧根的 QM 小模型輸入；(3) 在 `metal_params` 提供 `site_water`。(2)(3) 是程式外的工作，只留文字提示，不做假按鈕。
閘門出現時程式已把含 OH⁻ 的 QM 輸入寫到 `build/metal_qm/<位點>_hydroxide/`（`evidence.qm_input_dir`）。

**拓樸與樣板**（`apply_metal_policy`，需要 OpenMM，容器無法執行）：水 O 加回、`Modeller.addHydrogens` 之後，刪掉一個氫（M–O–H 角較大、即朝離開金屬方向的那個；`choose_hydroxide_h`），
殘基改名 `OHM`、氫改名 `H1`；在 `createSystem`（包含 `Modeller.addSolvent` 內部建的 System）之前，用 `hydroxide_template_xml`（純函式，回傳 XML 文字）產生只含 `<Residues>` 的樣板並 `ForceField.loadFile`
（同時寫成 `metal_qm/<位點>/hydroxide_template.xml` 供審查）。電荷來自擬合；原子型態是 Amber ff14SB 的羥基 `protein-OH`／`protein-HO`（Ser／Thr／Tyr 的 OG/HG，與 GAFF `oh`/`ho` 相同），
**LJ 與 O–H 鍵長沿用該型態，沒有擬合**，這是明講的假設，報告 caveats 也寫。力場缺這兩個型態時擋下。
Zn–H 為 1-3 排除；**沒有 M–O–H 角**，除非擬合參數給了 `angle_MOH`（此時 θ0、k 用擬合值，不用晶體角，因為 H 的位置是任意的）。

**QM 小模型輸入（D-133 未決 2 的處理）**：`write_qm_cluster(…, waters=[{"rid", "state"}])` 把配位水放進 cluster：H₂O（O＋2 H，電荷 0）或 OH⁻（O＋1 H，電荷 −1 加進總電荷；`qm_charge` 仍是金屬氧化態）。
幾何鍵結位點（水狀態）的 cluster 現在也含水，否則 QM 會把四面體位點最佳化成三配位。README 寫明水／氫氧根、為什麼程式不決定、以及 hessian 路徑要自己填 RESP 電荷。拓樸裡的氫數與要求的狀態不符（H₂O 要 2 個、OH⁻ 要 1 個）時 NEEDS_HUMAN。

**限制與誠實等級**
- [已驗證：純邏輯測試] 設定解析、閘門、`site_water` 檢查、鍵／角／電荷計畫、樣板 XML、QM 輸入、hessian 與 mcpb 的合成資料往返。
- [未驗證：待 heavy-metal CI] Modeller 實際刪氫與改名、`ForceField.loadFile` 載入樣板、`protein-OH`／`protein-HO` 型態名稱、System 建構與電荷、NVT 穩定性。`tests/test_metal_integration.py` 的兩個新測試（需 OpenMM）只驗證流程，用的電荷是**測試值**，不是任何真實研究的參數。
- mcpb 的氫氧根轉譯只用合成 mol2／frcmod 驗證過，**沒有真實 MCPB.py 輸出**；殘基名稱靠 `site_water.residue` 指定。
- 氫氧根的 O–H 氫在 MD 中以 HBonds 約束，M–O–H 沒有擬合時氫可自由轉動。分析模組仍把 OHM 當一般小分子殘基（不當水也不當配體）。
- 兩個以上位點各自設定時，每個位點各有一個 OHM（同殘基名，用鏈與編號區分）。

## 5. 未做
配體直接配位金屬（需配體–金屬 QM 模型）；金屬 LJ 擬合（12-6-4）；RESP 由本程式計算。

## 6. 想請審查者回答
1. 1-4 縮放對金屬是否合適？MCPB.py 的作法是否同時重新指定金屬的 LJ（例如 Li–Merz 12-6 CM 參數）？
2. 幾何模型的力常數（46/25/50 kcal）是否應依金屬種類（Zn/Fe/Cu）不同？
3. Wilson-B 轉換在冗餘內座標下的物理意義（pseudo-inverse 分配）是否可接受？是否應改用 Seminario 鍵 + B 矩陣角的混合？
4. QM 小模型的方法（B3LYP-D3BJ/def2-SVP）對教學是否足夠？
