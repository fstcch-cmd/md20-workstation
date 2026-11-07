> **2026-11-07（D-102）**：膜（與一般溶劑）建模在建立 System 前加入「去水碰撞」步驟（`assemble.remove_overlapping_waters`）：OpenMM 溶劑化偶爾放出 O–O < 0.18 nm 的重疊水，最小化壓不下、MD 前幾步 NaN（Linux／Windows 皆會，依建構而定）。閘門 water overlaps：刪＝AUTO_FIXED、乾淨＝PASS、無法修＝NEEDS_HUMAN。詳見 DECISIONS D-102。

# Spec: 膜系統（建膜、膜蛋白、膜表面接觸）

狀態：**[部分實作，未在真實引擎驗證]**（2026-11-03，D-80）。使用者要求：專業版建膜功能要完備；也要支援「胜肽或藥物只在膜表面接觸、不穿膜」的情境。
程式：`md20/build/membrane.py`（定向、組成、建膜、表面擺放）、`md20/analysis/membrane.py`（分析與平衡驗收）、
`md20/engine/protocol.py`（`membrane_protocol`、`StageSpec.barostat`）、`md20/engine/backend.py`（`MonteCarloMembraneBarostat`）。
測試：`tests/test_membrane.py`（純邏輯，容器內通過）、`tests/test_membrane_integration.py`（CI openmm-stack，沒有 openmm 就 skip）。

誠實現況：
- **已驗證（容器內，純 numpy）**：疏水帶掃描在合成螺旋束上找回法線（< 8°）、在疏水核心＋極性表面的水溶性球狀蛋白上回 NEEDS_HUMAN；組成解析與閘門；表面擺放；離子位置選擇；格點排列；全部分析函式；協定切換不改舊協定的 hash。
- **只讀過原始碼、未執行**：所有呼叫 OpenMM 的程式（`add_membrane`、`build_bilayer`、`_grid_membrane`、頭基約束、膜壓力耦合）。第一次真正執行是 CI 的 `test_membrane_integration.py`。
- **格點排列器**（混合膜、非對稱膜）：CI 測試標為 xfail（strict=False），第一次在 CI 跑出結果前不當作可用。

## 1. 要解決的問題
目前所有系統都放在水盒中。膜蛋白（例如葡萄糖轉運蛋白 GLUT1 4PYP、GLUT3 4ZW9）、抗菌胜肽或抗生素與細菌膜的作用、胜肽在膜表面的吸附，
都需要脂雙層。缺少膜時，膜蛋白的跨膜區會在水中變形，結果沒有意義。

## 2. 三種膜系統（同一套建模與閘門）
| 情境 | `md.membrane.type` | 內容 | 典型大小 |
|---|---|---|---|
| A. 膜蛋白 | `protein` | 蛋白嵌入脂雙層，依膜中方向擺放 | 10–15 萬原子 |
| B. 膜表面接觸 | `surface` | 只有一片膜，胜肽或小分子放在膜上方指定距離（預設上葉磷原子平面外 1.0 nm），不要求穿膜 | 3–6 萬原子 |
| C. 純膜 | `bilayer` | 只有脂雙層（教學：膜的性質、相變） | 2–4 萬原子 |

設定（workflow config 的 `md.membrane`，預設值在 `membrane.DEFAULTS`）：
```json
"md": {"membrane": {"type": "protein", "lipids": "mammalian", "oriented": false,
                    "surface_distance_nm": 1.0, "surface_orientation": "as_is",
                    "temperature_k": null, "lateral_padding_nm": 1.5, "water_nm": 2.0,
                    "templates_dir": null, "size_nm": null, "seed": 2026}}
```
- `lipids`：預設名稱（`mammalian`、`bacterial`、`gram_positive`）、`{脂質: 比例}`（對稱）、或 `{"upper": {...}, "lower": {...}}`（非對稱）。比例總和不是 1 會換算成分率（AUTO_FIXED）。
- `surface_orientation`：`as_is`、`random`、`parallel`（長軸平躺在膜面，兩親性螺旋常用的起點）、`normal`（長軸沿法線）。
- `temperature_k`：未設時用預設組成的溫度（三個預設都是 310 K），否則 310 K。

進入點：
- 情境 A 走一般 workflow：`build_case(..., membrane=...)` → `assemble_system(..., membrane=...)`，膜取代水盒；`run_md` 在 `md.membrane` 有值時套用 `membrane_protocol`。
- 情境 B、C：`membrane.build_membrane_system(out_dir, spec, receptor_pdb=None, ligands=..., peptide_sequence=...)`，內部呼叫 `assemble_system(receptor_pdb=None, ...)`。
  目前 workflow（以對接為中心）還沒有 B、C 的步驟；GUI 也還沒有建膜頁（`md20/gui/` 屬其他 session）。
- 膜系統的 SMD／傘狀採樣先擋下（閘門 `membrane binding`，NEEDS_HUMAN）：拉離方向可能穿過脂雙層，拉離時也沒有膜壓力耦合。

## 3. 脂質組成（預設與可選）
| 預設 | 組成 | 溫度 | 出處 |
|---|---|---|---|
| `mammalian` | POPC 1.0 | 310 K | 最簡單的哺乳類細胞膜模型（規格原文）；可自己加膽固醇，例如 `{POPC: 0.7, CHOL: 0.3}` |
| `bacterial` | POPE 0.75、POPG 0.25 | 310 K | 大腸桿菌內膜的常用 3:1 PE:PG 模型（抗菌胜肽 MD 慣例） |
| `gram_positive` | POPG 0.55、lysyl-PG 0.35、心磷脂 0.10 | 310 K | 金黃色葡萄球菌類的細胞膜；**比例待確認**（文獻隨生長期變化，PG 約 50–60%、Lys-PG 約 30–40%、CL 約 5–10%，需要列出出處） |

- 溫度預設 310 K（不是 300 K）：生理溫度，也比 POPE 的相轉變溫度（約 298 K）高 12 K。主要脂質（比例 ≥ 0.5）在 Tm + 5 K 以下 → `membrane phase` NEEDS_HUMAN。
- 膽固醇 > 50 mol% → NEEDS_HUMAN（會析出）。
- 格蘭氏陽性菌的**肽聚醣細胞壁**沒有標準全原子參數，第一版不做；報告明寫「只模擬細胞膜，不含細胞壁」。粗粒化路徑（§7）較可行。
- `gram_positive` 目前一定擋下（`membrane force field`）：心磷脂與 lysyl-PG 在 Amber 脂質力場沒有參數（見 §4.2）。

### 3.1 參考值（平衡驗收用）**待確認**
開發者依記憶整理，實作時沒有查到原文。審查時請對照論文確認（Kučerka 等人的 PC 系列 2005–2011、Pan 等人 2012 的 POPG、POPE 的 X 光數據）。
| 脂質 | APL (nm²) | D_HH ≈ P–P (nm) | Tm (K) |
|---|---|---|---|
| POPC | 0.643 | 3.70 | 271 |
| POPE | 0.58 | 3.95 | 298 |
| DOPC | 0.674 | 3.67 | 256 |
| DPPC | 0.631（323 K） | 3.80 | 314 |
| DMPC | 0.606 | 3.44 | 297 |
| DLPC | 0.632 | 3.08 | 271 |
| DLPE | 0.56 | 3.30 | 302 |
| POPG | 0.661 | 3.65 | 269 |
| CHOL、CL、LYSPG | 無（膽固醇會讓膜變緊，不能加權平均） | 無 | — |

混合膜用比例加權平均；任一成分沒有值時該項不檢查，閘門文字會寫「未檢查」。

## 4. 建模
### 4.1 方向（情境 A）
1. **使用者已定向**（`oriented: true`；OPM／PDBTM 下載或 CHARMM-GUI 輸出，膜中心 z = 0、法線 z）：照原樣使用。仍跑一次掃描，法線差 > 15° 或疏水帶中心 |z| > 0.5 nm 時以提醒卡片列出差異（AUTO_FIXED、advisory，不擋）。
   OPM 檔裡的 DUM 假原子要在受體整理時去掉（未驗證 `prepare_receptor` 是否會刪；待確認）。
2. **自動**（`scan_orientation`）：每個 Cα 一個權重（Leu/Ile/Val/Phe/Met +1、Ala/Cys +0.5、Trp/Tyr +0.25、Asp/Glu/Lys/Arg −1、Asn/Gln −0.5），
   Cα 鄰居數（1.0 nm 內）在前 30% 的殘基視為埋在蛋白內部，權重乘 0.4。在半球上 2000 個方向（Fibonacci）各找 3.0 nm 厚、權重和最大的平板，最佳方向附近 6° 內再細掃 400 個方向。
   旋轉使法線為 z、平板中心為 z = 0（`orientation_transform`）。膜的內外側由疏水帶判斷不了，閘門文字要求以 OPM 或文獻確認。
3. **可信度門檻**（全部成立才 PASS，否則 NEEDS_HUMAN，不猜方向）：
   - 帶內「外露」殘基的疏水比例 ≥ 0.55；
   - 比帶外外露殘基高 ≥ 0.20（只算外露殘基：水溶性蛋白的內核也是疏水的，用全部殘基會誤判）；
   - 最佳方向的分數比任何相差 > 45° 的方向高 ≥ 20%（25° 太近：細長螺旋束傾斜 25° 仍有 88% 的分數，實測合成螺旋束）；
   - 帶內外露殘基 ≥ 12；蛋白在平板兩側各伸出 ≥ 0.5 nm（真的穿膜）。
   門檻用合成資料校準，**真實蛋白（GLUT1 4PYP 與 OPM 比較）尚未驗證**。

### 4.2 已查證的 OpenMM 事實（讀 openmm/openmm master 原始碼，commit ef4294d，2026-11-02）
- `Modeller.addMembrane(forcefield, lipidType='POPC', membraneCenterZ=0, minimumPadding=1 nm, positiveIon, negativeIon, ionicStrength, neutralize, residueTemplates, platform)`。
  內建 `lipidType`：**POPC、POPE、DLPC、DLPE、DMPC、DOPC、DPPC**（`openmm/app/data/<NAME>.pdb` 的預平衡膜片）；其他脂質要自己提供可平鋪的膜片（PDBFile 物件）。
- 演算法（Wolf 等 2010）：平鋪整數份膜片、蛋白在 xy 縮成 50%、刪掉離縮小蛋白 0.22 nm 內的脂質（上下葉刪一樣多），再跑短 MD 讓蛋白慢慢長回原大小。蛋白要**事先定向好**，膜放在 xy 平面。
- 盒高：模型已有單位晶格時 = max(膜片高, 晶格 z + 2 × padding)，否則 max(膜片高, 蛋白 z 範圍 + 2 × padding)。MD20 用這一點控制情境 B 溶質上方的水層厚度（先設定 `setUnitCellDimensions`）。
- 膜片高度以外需要的水由 `addSolvent` 補，膜片 z 範圍內新加的水會刪掉；離子取代離脂質 0.25 nm 以外的水。只支援一價離子。
- 膜片放置：膜片包圍盒（含水）的中心對到 `membraneCenterZ`；雙層本身的中心可偏 0.0–0.3 nm（實測 POPE 0.23、DLPE 0.29），所以 MD20 一律以實際磷原子量膜中心。
- 力場：`amber14-all.xml` 包含 `amber14/lipid17.xml`；master 另有 `amber19/lipid21.xml`（`amber19-all.xml` = ff19SB + Lipid21）。Lipid17 與 Lipid21 都有 POPC、POPE、POPG、POPS、DOPC、DPPC、DMPC、DLPC、DLPE、CHL1 等單一殘基樣板，**沒有心磷脂與 lysyl-PG**。
  `charmm36.xml` 有 TOCL2（心磷脂 2−）、PVCL2；`charmm36_2024.xml` 另有 DPPGK（lysyl-DPPG）。CI 裝的 OpenMM 版本（`openmm>=8.1`）是否已有 `amber19/` 未查證。
- 預平衡膜片（直接讀 PDB 量得；residue 名稱為 4 字截成 3 字，例如 POPC → `POP`；有 CONECT）：

| 膜片 | 晶格 (nm) | 原子 | 脂質（每葉） | 盒面積/脂質 (nm²) | P–P (nm) |
|---|---|---|---|---|---|
| POPC | 6.37 × 6.69 × 7.31 | 32,512 | 64 | 0.666 | 3.66 |
| POPE | 6.15 × 5.87 × 8.40 | 31,360 | 64 | 0.564 | 4.07 |
| DOPC | 6.21 × 6.66 × 7.64 | 33,024 | 64 | 0.646 | 3.97 |
| DPPC | 5.59 × 5.69 × 8.10 | 28,160 | 64 | **0.497（凝膠相）** | 4.30 |
| DMPC | 6.29 × 6.33 × 6.36 | 26,624 | 64 | 0.622 | 3.50 |
| DLPC | 6.25 × 6.55 × 5.84 | 25,088 | 64 | 0.640 | 3.11 |
| DLPE | 5.93 × 5.92 × 7.71 | 27,776 | 64 | 0.549 | 3.38 |

  DPPC 膜片是凝膠相，正好說明 `membrane phase` 閘門的必要：在 310 K 用 DPPC 會被擋下，要 ≥ 324 K。
- `MonteCarloMembraneBarostat(defaultPressure, defaultSurfaceTension [bar·nm], defaultTemperature, xymode, zmode, frequency=25)`；
  `XYIsotropic = 0`、`ZFree = 0`；Context 參數名是 `MembraneMonteCarloPressure`、`MembraneMonteCarloSurfaceTension`、`MembraneMonteCarloTemperature`（和 `MonteCarloBarostat` 的 `MonteCarloPressure` 不同，backend 依實際的壓力耦合類別取名稱）。

### 4.3 建膜方式（`plan_membrane` 決定，不猜）
| 條件 | 方式 | 狀態 |
|---|---|---|
| 對稱、單一、OpenMM 有膜片的脂質，有溶質（A、B） | `openmm_addmembrane` | 程式完成，CI 驗證 B |
| 同上，沒有溶質（C） | `openmm_patch_tile`：直接平鋪膜片 n×n 份（`size_nm`），離子取代水 | 程式完成，CI 驗證 |
| 混合、非對稱、或沒有膜片的脂質 | `grid`：每種脂質一個模板 | 程式完成，**未驗證**（CI xfail） |

格點排列器：
1. 模板：7 種膜片脂質從 OpenMM 膜片取上葉第一個完整分子（依鍵結連通）；其他脂質（POPG、CHOL 等）要 `templates_dir/<NAME>.pdb`（含 CONECT 與磷原子或 O3），沒有就 NEEDS_HUMAN（`membrane builder`），不猜構形。模板旋轉使「重原子質心 → 頭基原子」為 +z，頭基原子在原點。
2. 盒子 xy = 溶質範圍 + 2 × `lateral_padding_nm`（無溶質時邊長 √(64 × APL) 或 `size_nm`）；每葉格點數 = 面積 / 參考 APL。
3. 每葉在頭基 z 範圍內，側向 0.5 nm 內有蛋白重原子的格點刪除；**刪完才依比例分配脂質種類**（最大餘數法），所以組成精確。下葉翻轉 180°；每個脂質繞 z 隨機旋轉、格點 ±10% 抖動。
4. `addSolvent` 填水後刪掉 |z| < P–P/2 − 0.2 nm 的水；離子取代頭基區以外（|z| ≥ P–P/2 + 0.7 nm）的水，彼此 ≥ 0.5 nm，含溶質與脂質淨電荷的中和。
5. 沒有 addMembrane 的鬆弛 MD：靠 minimize 階段與頭基約束解開重疊。這是最可能失敗的地方。

### 4.4 情境 B 的擺放（`place_on_surface`）
溶質最低重原子放在上葉磷原子平面上方 `surface_distance_nm`（預設 1.0 nm，< 0.3 nm → NEEDS_HUMAN：從頭基裡開始就無法說是自己吸附的）。
addMembrane 路徑用膜片自己的磷平面（`patch_geometry`），格點路徑用 ±P–P/2。盒高保證溶質頂端到下葉頭基的週期影像之間至少 `water_nm`（預設 2.0 nm，截斷半徑 1.0 nm 的兩倍）。
側向位置：純函式支援在盒內隨機（固定 seed）；addMembrane 會把膜片中心對到溶質中心，所以這條路徑的側向位置等於固定。流體膜在 xy 週期延伸，起始側向位置不影響結果。

### 4.5 大小
蛋白到盒邊的側向距離 ≥ 1.5 nm（`lateral_padding_nm`）；水層每側 ≥ 2.0 nm（`water_nm`）。addMembrane 只加整數份膜片，所以實際盒子常比要求大（GLUT1 約 2×2 份 POPC，約 12.7 nm）。原子數寫在 build_manifest。

## 5. 模擬流程（膜專用）
- 壓力：NPT 階段 `StageSpec.barostat = "membrane"` → backend 建立 `MonteCarloMembraneBarostat`（xy 等向、z 獨立、表面張力 0）。預設 `"isotropic"` 不寫進協定字典，舊協定 hash 不變。
  system.xml 已含另一種壓力耦合時拒絕執行（不猜）。
- 約束（沿用 D-23 分組）：新增 `msw_lipid_head_restraints`（只約束脂質磷原子與膽固醇 O3 的 z，k = 1000 kJ mol⁻¹ nm⁻²，參數 `msw_rs_lipid_head`，同樣乘 `msw_restraint_scale`）。
  排程：minimize 全約束 → NVT [1, 1] → NPT [1, 0]（和蛋白一起解除）→ production 0。
  **和原規格不同**：原規格寫「蛋白重原子、頭基 z、脂尾二面角各自分組，共六段」。依開發規則不新增 phase/step，所以放進既有的 NVT／NPT；脂尾二面角約束沒有做（addMembrane 的膜片已平衡；格點路徑若 CI 證明需要再加）。
- 溫度：`membrane_protocol(proto, temperature_k=...)` 把所有非 minimize 階段設為膜溫度（預設 310 K）。
- 拉離（`sampling/binding.build_pulling_system`）時頭基約束關掉（參考座標是建模時的，NPT 後已過時）；目前膜系統的 binding 整步先擋下。
- 平衡驗收（`analysis.membrane.assess_equilibration`，閘門 `membrane equilibration`）：
  每脂質面積在參考值 ±6%、P–P 厚度在參考值 ±0.3 nm、疏水核心（膜中心 ±0.5 nm，排除蛋白側向 0.6 nm 內的孔道水）平均水分子 ≤ max(1, 1% 脂質數)、蛋白疏水帶偏離膜中心 ≤ 1.0 nm。
  第一次不合 → AUTO_FIXED（`evidence.action = "extend_equilibration"`，延長 NPT 一次）；延長後仍不合 → NEEDS_HUMAN。
  **尚未接到 runner**：函式與閘門已完成，需要協調 session 在 NPT 之後讀軌跡呼叫（engine 屬共用檔）。含蛋白時面積要扣蛋白截面積，目前不檢查面積。

## 6. 分析（`md20/analysis/membrane.py`，純 numpy，輸入 nm 座標與 (F, 3) 盒長）
- 膜：每脂質面積 `area_per_lipid`、P–P 厚度 `thickness_pp`、密度剖面 `density_profile`（相對膜中心，可用質量加權並換成 g/cm³）、
  氘序參數 `order_parameter`／`scd_profile`（CHARMM 命名：sn-2 C2n 配 HnR/HnS/HnT，sn-1 C3n 配 HnX/HnY/HnZ，`scd_groups_from_names`）、疏水核心水 `water_in_core`。
  膜中心用頭基 z 的圓周平均（盒子包裹後仍正確）。脂質側向擴散尚未做。
- 膜表面接觸（情境 B）：插入深度 `insertion_depth`（質心與最深重原子相對所在那一葉的磷平面，正值 = 進入膜內；並回報是否穿過膜中心）、
  與頭基接觸的殘基 `headgroup_contacts`（0.4 nm）、比例與停留時間 `residence_times`（最後一幀仍接觸的事件以觀察長度計，是下限）、胜肽傾角 `helix_tilt`（主軸與 z，90° = 平躺）。
- 膜蛋白：`protein_offset`（蛋白疏水帶偏離膜中心）。跨膜螺旋個別傾角、孔道水與孔徑剖面、配體沿孔道軸位置、膜局部厚度圖尚未做。
- 自由能：沿膜法線的 PMF（沿用傘狀採樣，CV 為配體質心到膜中心的 z 距離，加側向圓柱約束；與 `binding_funnel_restraints.md` 共用）尚未做。
- 四種語言的指標名稱：`METRIC_LABELS`；閘門標題與說明在 `md20/gui/gate_text.py`。報告與圖表還沒有接上。

## 6a2. 建模後去碰撞（D-102、D-115）
- 建 System 前：水對水（O–O < 0.21、跨分子 O–H < 0.14 nm）刪較大索引的水；**離子對水**（`ION_O_MIN_NM`，約第一殼峰值 80%；陰離子另查 H）刪水、留離子；兩個離子 < 0.22 nm → NEEDS_HUMAN。同一個閘門「water overlaps」。
- D-102 原本認為水重疊是 NaN 根因；診斷資料顯示每個建構都有水重疊、只有離子貼水的建構會爆（D-115，待下一輪診斷直接證實）。

## 6b. 建膜即時 3D（D-104）
狀態：**[已實作・待 CI]**。
- 建模寫 `<build>/live3d/NN_<stage>.json`＋`index.json`：`solute`（定向／放置後，附兩個磷原子目標平面）、`bilayer`（加膜後）、`declashed`（去水碰撞後）。workflow 在建每個 case 前寫 `<wf>/live3d_current.json`。
- 場景：水、氫不畫；頭基（P、N、膽固醇 O3）全畫；尾鏈原子等距抽樣使總原子 ≤ 9000；離子小點；≤ 60 殘基胜肽全重原子，否則 Cα 骨架；盒子線框；座標 Å（`md20view.js` 的單位）。
- GUI 3D 分頁每 3 秒重讀目標清單，「建膜中（即時）」排第一，新階段寫入即重畫（不必重新整理頁面）。
- 快照失敗不影響建模。
- `summary.n_lipid_heads` 是**頭基原子數**，不是脂質數（POPC 每個 P＋N 兩個；D-112 更正了把它當成脂質數的測試與中日文說明）。CI 28e87aa macOS 已確認情境 C 的 water overlaps 閘門與 bilayer→declashed 階段在真實 OpenMM 上成立。
- 審查問題：9000 原子上限在一般筆電瀏覽器是否流暢？是否需要在 MD 平衡（膜 NPT）時也每個 chunk 更新一張？

## 7. 與長時間模擬的關係
見 `long_timescale.md`：全原子膜蛋白在 RTX 4060 筆電估計每天 50–150 ns（未實測）；微秒級以上的膜現象（抗生素破壞膜、脂質重排）走粗粒化 Martini 3。

## 8. 驗證計畫（CI 與實機）
| 項目 | CI（`tests/test_membrane_integration.py`） | 筆電 |
|---|---|---|
| 純 POPC 膜 | 建模（128 脂質、頭基約束 128、淨電荷 0）、minimize、300 步膜壓力耦合；x/y 比例不變；厚度 3.2–4.3 nm、面積 0.55–0.75 nm² | 20 ns：面積與厚度落在 §3.1 範圍 |
| 膜表面胜肽 KLAKLAK | 建模、最深重原子在磷平面上方 1.0 ± 0.25 nm、200 步 | melittin 或 magainin 2（序列公開）：吸附、不穿膜，插入深度合理 |
| POPC:POPE 1:1 格點 | xfail（第一次執行） | 視 CI 結果 |
| GLUT1（4PYP） | 未做（需要 PDB 檔，容器連不到 RCSB） | 方向自動判定與 OPM 比較；10 ns 內跨膜螺旋穩定 |

筆電驗證指令見協調 session 的回報。

## 9. 想請審查者回答
- 力場組合：ff14SB＋Lipid17（目前預設，和 addMembrane 膜片同一年代）、ff19SB＋Lipid21，還是 CHARMM36m＋CHARMM36（才有心磷脂、lysyl-PG）？教學與研究是否用同一套？
- 格蘭氏陽性菌膜的預設比例與出處；§3.1 參考值的出處。
- 自動定向的可信度門檻（§4.1，只用合成資料校準）。
- 平衡驗收的容許範圍（±6% 面積、±0.3 nm 厚度）對 64–256 脂質的短模擬是否合理。
- 是否需要脂尾二面角約束與第六段平衡（§5 和原規格的差異）。

## 10. 未決與下一步
- 接上 runner：NPT 後呼叫 `assess_equilibration`，AUTO_FIXED 時延長一次。
- workflow 與 GUI：情境 B、C 的步驟與建膜頁、報告的膜分析圖。
- 格點排列器 CI 結果；POPG、CHOL 模板來源（可否由 Lipid17 樣板＋已平衡構形產生）。
- 膜系統的 SMD／傘狀採樣（膜壓力耦合下的拉離、沿法線的 PMF）。
- OPM 的 DUM 原子處理；蛋白截面積估計（面積閘門）。
