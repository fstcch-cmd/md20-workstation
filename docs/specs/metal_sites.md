# 金屬位點：policy、幾何鍵結模型、擬合參數、QM 小模型

## 1. Policy（`metal_policy`，依元素 "ZN" 或位點 "ZN:A262"，位點優先）　[已驗證：結構閘門與 pure 測試]
- `remove`：使用者確認非功能必要才移除。
- `keep_nonbonded`：力場非鍵結離子 + 1000 kJ/mol/nm² 位置約束（production 也不解除），報告標註配位幾何不保證。
- `bonded`：鍵結模型（見下）。
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

## 5. 未做
配體直接配位金屬（需配體–金屬 QM 模型）；金屬 LJ 擬合（12-6-4）；RESP 由本程式計算。

## 6. 想請審查者回答
1. 1-4 縮放對金屬是否合適？MCPB.py 的作法是否同時重新指定金屬的 LJ（例如 Li–Merz 12-6 CM 參數）？
2. 幾何模型的力常數（46/25/50 kcal）是否應依金屬種類（Zn/Fe/Cu）不同？
3. Wilson-B 轉換在冗餘內座標下的物理意義（pseudo-inverse 分配）是否可接受？是否應改用 Seminario 鍵 + B 矩陣角的混合？
4. QM 小模型的方法（B3LYP-D3BJ/def2-SVP）對教學是否足夠？
