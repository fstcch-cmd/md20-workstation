# 結合自由能：漏斗（funnel）約束與標準態校正 —— 讓一維 PMF 可以和實驗比 **[已實作，待 CI 與筆電驗證]**

> 2026-11-02，session_016gcJz9hwPAMieHsNEctkzL。起因：筆電 3PTB 實測（`docs/archive/runs/2026-11-02_laptop_3ptb/`、D-62–D-65）。
> 2026-11-08（D-140）：使用者授權 A8，選項 A 已實作（§6）；真實引擎路徑（OpenMM 運算式、取樣、檢查）只在純 Python 驗證，**待 CI `openmm-stack` 與筆電 3PTB**。§1–§5 保留為設計原文，與實作不同處列在 §6.3。

## 1. 要解決的問題（證據）
目前結合計算：SMD 拉離 → 傘狀採樣沿**錨點（口袋 Cα 質心）到配體質心的距離** r → WHAM/MBAR → 徑向 PMF w(r)（+2kT ln r Jacobian）→
井深 ΔPMF 與徑向積分 ΔG°（1 M）。筆電 RTX 4060 上胰蛋白酶–苯甲脒：

| 層級 | window | ΔPMF（全範圍） | ΔG° | 實驗 |
|---|---|---|---|---|
| classroom | 50 ps | 134 kJ/mol | −29.5 kcal/mol | ≈ −6.4 kcal/mol |
| teaching | 500 ps | 100 kJ/mol | −21.2 kcal/mol | |

- window 加長 10 倍只把平台由 134 降到 100；**0.2–0.5 nm 段兩次完全重合** → 高估主要不是取樣時間，而是 CV 本身。
- 一維距離 CV 不限制配體**方向**與**離開路徑的側向位置**：配體在口袋外可以貼著蛋白表面走、翻轉卡住，正交自由度（方向、口袋水進入、Asp189 鹽橋重排）
  慢到 500 ps 也平衡不了，結果是遲滯（hysteresis）→ 平台過高。
- 徑向積分 ΔG° 假設離開口袋後各方向均勻（球對稱），埋在 S1 窄口袋的配體不符合，標準態校正錯。

## 2. 選項
| 方法 | 做法 | 成本 | 對 MD20 的適合度 |
|---|---|---|---|
| **A. 漏斗約束（Limongelli 2013；Rizzi 2019 的 funnel 版本）** | 沿拉離軸 z 加一個「圓錐＋圓柱」平底側向約束：口袋內允許較寬（圓錐），出口後側向半徑固定 R_cyl；CV 改為沿軸的投影 z | 一個額外 CustomCentroidBondForce；PMF 與現有流程相同 | **高**：不新增步驟，只換 CV 與加一個力；標準態校正是解析式 |
| B. Woo–Roux 方向／構形約束 | 結合態加配體構形 RMSD、三個方向角、兩個位置角約束，各自另算約束自由能（再各跑一組 window） | 6–8 組額外 window；教學層級跑不完 | 中：最嚴謹，但等於新增好幾個階段（違反「不新增 phase」）；可作 research 層級的後續 |
| C. 雙解耦（ABFE，alchemical） | OpenFE／Yank | 大；Windows 支援待驗證 | 低（已列在工作站佇列 M7） |

**建議：先做 A**，B 留給 research 層級。

## 3. 漏斗約束設計（A）
### 3.1 幾何
- 軸：起點 = 結合態口袋錨點質心 **c**；方向 **u** = 結合態（production 最後一段平均）由 c 指向配體質心的單位向量，**與現在 SMD 拉離方向相同**（沿用 `binding.py` 的錨點與方向，不新增選擇）。
- 配體質心 x 的分解：z = (x − c)·u（沿軸），ρ = |(x − c) − z·u|（離軸距離）。
- 側向允許半徑：ρ_max(z) = R_cyl + (R_cone − R_cyl)·max(0, (z_cc − z)/z_cc)，z ≤ z_cc 為圓錐（口袋內較寬），z > z_cc 為半徑 R_cyl 的圓柱。
- 約束能：U = ½ k_f · max(0, ρ − ρ_max(z))²（平底，範圍內無力）。
- 預設（待審查）：R_cyl = 0.2 nm，R_cone = 1.0 nm，z_cc = 口袋深度 + 0.3 nm（由結合態配體到口袋外緣的距離自動估），k_f = 4000 kJ/mol/nm²。
- 另加 z 下限牆（z ≥ −0.2 nm）避免配體穿到蛋白另一側。

### 3.2 CV 與傘狀採樣
- CV 由三維距離 r 改為沿軸投影 **z**（自適應補窗、WHAM/MBAR、覆蓋檢查、D-65 持平閘門全部沿用，只換 CV 函式與 umbrella 力的表達式）。
- 漏斗約束在 SMD 與每個 window 都開著。
- **Jacobian 不再加 +2kT ln r**（z 是一維直線座標；圓柱內的側向體積由下面的校正處理）。

### 3.3 標準態結合自由能（解析校正）
K_b = π R_cyl² ∫_site exp[−β (W(z) − W_bulk)] dz（site = W 回到 W_bulk 之前的區段；W_bulk 為圓柱段平台）
ΔG° = −kT ln(K_b / V°)，V° = 1.661 nm³（1 M）。
- 若圓錐段漏斗在結合態仍有作用（配體被側向壓到）——檢查：結合態 window 的 ρ 分佈 99% 分位 < ρ_max(z) − 0.05 nm，否則 NEEDS_HUMAN（漏斗太窄，偏壓了結合態）。
- 圓柱段配體已完全溶劑化的檢查：z ≥ z_cc + 0.5 nm 處配體重原子到蛋白最短距離 > 0.6 nm。

### 3.4 閘門與報告（通則）
- `binding.restraint = "none" | "funnel"`；teaching／research 預設 funnel，classroom 預設 none（ΔG° 一律不輸出、只示範流程）。
- PASS 條件：D-62 覆蓋、D-65 持平、上述兩個漏斗檢查、ΔG° bootstrap σ ≤ 4 kJ/mol。
- 報告：漏斗幾何示意圖（軸、圓錐、圓柱、結合態配體）、z–ρ 散佈、PMF(z)、K_b 積分區段、方法段落（引用 Limongelli 2013）。
- 決策日誌：軸方向、R、z_cc 的自動選擇與理由。

## 4. 驗證計畫
1. 純 Python：K_b 積分對解析模型（諧和井＋平台）；ρ、z 分解與最小映像；漏斗能量在範圍內為 0、外為二次。
2. CI（Reference 平台）：NaCl 或 benzene–toluene 小系統，funnel 與無 funnel 的 ΔG° 應在 2 kJ/mol 內一致（球對稱系統不應受漏斗影響——正確性測試）。
3. 筆電：3PTB teaching，比較 none／funnel 的 ΔG° 與實驗 −26.8 kJ/mol（目標：誤差 < 8 kJ/mol，文獻 funnel／ABFE 的典型誤差）。

## 5. 想請審查者回答
1. 軸取「結合態錨點→配體」是否足夠？還是應以 SMD 中「功最小的出口」或口袋開口幾何（例如 CAVER／fpocket 方向）決定？
2. CV 用 z（投影）而非 r（距離）會不會讓口袋內的彎曲出口路徑被強行拉直？圓錐半徑 1.0 nm 是否足以容納？
3. R_cyl 0.2 nm 的選擇：太小會讓圓柱段的取樣窄、平台估計偏差；太大會增加側向熵、平台收斂慢。是否應依配體大小縮放？
4. 結合態構形變化（例如配體在口袋內翻轉）未加 RMSD 約束時，K_b 是否仍可信？是否至少在 research 層級加 B 的構形 RMSD 項？
5. 教學層級時間預算：funnel 讓 window 數略減（圓柱段收斂快）但每個 window 仍需 ≥ 500 ps；整體可否維持 RTX 4060 約 1 小時？

## 6. 實作（D-140，2026-11-08）
程式：`md20/sampling/funnel.py`（幾何、運算式、標準態、檢查）、`md20/sampling/binding.py`（選項、取樣、報告欄位）、`md20/sampling/assessment.py`（說法資格）。不新增 phase／step：仍是既有的 binding 步驟，`binding.config.restraint` 切換。

### 6.1 設定與預設
| 鍵 | 預設 | 說明 |
|---|---|---|
| `restraint` | `"none"` | `"none"`＝距離 CV＋徑向 1 M 積分（近似，**不用於排序**）；`"funnel"`＝軸向 z＋漏斗＋解析標準態 |
| `funnel_r_cyl_nm` | 0.2 | 圓柱半徑 R_cyl |
| `funnel_r_cone_nm` | 1.0 | z = 0 處的圓錐半徑 R_cone |
| `funnel_z_cc_nm` | `None`（自動） | 圓錐與圓柱交界；自動＝口袋出口 ＋ 配體半徑 ＋ 0.3 nm |
| `funnel_k` | 4000 | 側向與 z 下限牆的彈簧常數 k_f（kJ/mol/nm²） |
| `funnel_z_min_nm` | −0.2 | z 下限牆 |

**預設（D-151，使用者 2026-11-08 授權）：teaching／research 預設 `funnel`、classroom 預設 `none`**（回到 §3.4 原意）。使用者在 `binding.config.restraint` 明確指定時以其為準。舊的徑向結果（manifest 無 restraint 欄位）一律視為徑向，不被新預設誤判（finished_result）。

### 6.2 公式（單位：長度 nm，能量 kJ/mol，kT = k_B T）
- 軸與座標：c = 口袋 anchor 質心（活的），**u** = 起始結合態 (配體質心 − c)／‖…‖（最小映像）。z = (x − c)·u；ρ = ‖(x − c) − z·u‖。z₀ = ‖x₀ − c‖。
- 允許半徑：ρ_max(z) = R_cyl + (R_cone − R_cyl)·clip((z_cc − z)/z_cc, 0, 1)。
- 約束能：U = ½k_f·max(0, ρ − ρ_max(z))² ＋ ½k_f·max(0, z_min − z)²。
- CV 彈簧（SMD 與每個 window）：½k_cv(z − r0_cv)²，全域參數名與距離版相同。
- OpenMM：兩個 `CustomCentroidBondForce`（`md20_cv_bias`、`md20_funnel`，後者在 force group 31 以便單獨讀能量）。最小映像用 `floor(d/L+0.5)` 逐軸寫在運算式裡（reduced-form 盒子，與 `binding.min_image` 同順序 z、y、x），因為 `distance()` 失去正負號。`tests/test_funnel.py` 用小型 Lepton 求值器證明運算式文字與純 Python 能量一致（含相鄰週期影像、三斜盒子）。
- 側向有效截面積：A_eff = ∫₀^∞ exp[−U_lat(ρ; ρ_max = R_cyl)/kT]·2πρ dρ（數值積分，單位 nm²）；封閉式 πR² + 2π[R·½√(π/a) + 1/(2a)]，a = k_f/(2kT)，測試交叉驗證（k → ∞ 得 πR²）。k_f = 4000、R_cyl = 0.2、300 K 時 A_eff ≈ 0.169 nm²（比 πR² 大 34%，標準態項差 0.7 kJ/mol）。
- 標準態：**ΔG° = −kT ln( A_eff · ∫_site exp[−(W(z) − W_bulk)/kT] dz / V° )**，V° = 1.66054 nm³（1 M）。W(z) 為漏斗約束下 z 的 PMF（**沒有 +2kT ln r**）。
  - W_bulk：PMF 在**取樣範圍內**最後 10%（至少 3 格）的平均；平台檢查沿用 D-65（尾段直線擬合的上升 ≤ 1 kT）。
  - site：[第一格, 最小值之後第一個 W ≥ W_bulk − 0.5kT 的 z]（與徑向積分同一規則）；結果另報 `site_edge_sensitivity_kj_mol`（邊界外移 0.1 nm 時 ΔG° 的變化，只報告，沒有門檻）。
  - 解析測試：W ≡ 0、硬圓柱、長度 L → ΔG° = −kT ln(πR²L/V°)。
- 診斷（`pmf["funnel"]["checks"]`，進 assessment 的三個 `funnel_*` 診斷）：
  1. `funnel_bound_state`：結合態 window（中心 ≤ PMF 最小值 z ＋ 0.1 nm，至少第一個）中 ρ − ρ_max(z) 的 99% 分位 < −0.05 nm。不過：PMF 本身被漏斗扭曲，**路徑特定也不成立**。
  2. `funnel_solvation`：z ≥ z_cc + 0.5 nm 的樣本，配體重原子到蛋白重原子最短距離的 **1% 分位** > 0.6 nm（沿用規格 99% 慣例；只在 z 夠大時才計算）。
  3. `funnel_bulk_cylinder`：PMF 末端平台下緣 ≥ z_cc。
  2、3 不過或沒資料：ΔG° 不輸出（`dG_withheld`，DecisionLog 寫 NEEDS_HUMAN 與選項），`dG_standard` 與 `affinity_ranking` 都不成立。缺資料＝unknown，不當 pass。

### 6.3 與設計原文的差異（實作時的判斷）
1. 預設 `restraint: none`（見 6.1、D-140）。
2. 軸方向用起始狀態（`start_state_xml`）的瞬時向量，而非「production 最後一段平均」（`run_binding` 只拿到終點狀態；SMD 方向本來就是這個向量）。軸固定在實驗室座標，蛋白朝向由既有的骨架位置限制（×0.1）維持。
3. z_cc 自動值多加**配體半徑**：原式 z_cc = 口袋深度 + 0.3 nm 時，大配體在 z_cc + 0.5 nm 處最近原子距蛋白仍 < 0.6 nm，規格自己的溶劑化檢查達不到。口袋出口＝軸附近 0.5 nm 管內蛋白重原子沿軸**第一個 ≥ 0.35 nm 的缺口**（啟發式，可用 `funnel_z_cc_nm` 覆蓋；規格 §5 問 1 仍未決）。
4. 拉離範圍不足時**自動加長**（AUTO_FIXED，寫 DecisionLog）：需要 z_cc + 0.5 + 0.3 − z₀ nm；盒子放不下時由既有的盒子檢查擋下並給 padding（NEEDS_HUMAN）。
5. ρ_max 在 z < 0 夾住於 R_cone（原式會無限變寬）。
6. W_bulk 取取樣範圍內的尾段，而非整條格點的最後 10%（徑向版把取樣範圍之外的邊緣格也平均進去；軸向版不沿用這個缺點）。徑向版未改。
7. 同一輸出資料夾不可混用兩種座標：`restraint.json` 記錄，不一致即 NEEDS_HUMAN。
8. 驗證計畫 §4 的 2（NaCl 有／無漏斗 ΔG° 在 2 kJ/mol 內一致）**未做**：CI 的 NaCl 測試（`test_nacl_funnel`）只驗證力與記錄，window 2 ps 不足以比較 ΔG°。3（筆電 3PTB）未做。

### 6.4 說法資格（assessment）
`THRESHOLDS_VERSION` 2026-11-08.1（門檻沒動，改的是說法規則）；claim 紀錄 schema `md20.assessment.claim/2`（加 `reference_state`）。
| 說法 | 條件 |
|---|---|
| `dG_standard` | 既有診斷全過 ＋ 有 ΔG° 值且未撤回 ＋（若為漏斗）三個 `funnel_*` 全 pass。徑向 1 M 結果仍成立，但文字一律是「近似，不用於親和力排序」 |
| `affinity_ranking` | 上列全成立 ＋ assessment 的 `reference_state` 與結果的 `condition` **兩邊都**記錄 `cv = axial_projection_z`、`funnel_restraint = True`、`standard_state = funnel_cylinder_analytic`。缺紀錄＝不成立 |
`compare_binding` 的 ΔΔG°（`context_basis.use_dG`）、證據矩陣、圖說、比較矩陣全部讀 `affinity_ranking`；徑向結果只剩路徑特定井深順序（`order`），矩陣的 limits 說明原因（`radial_not_ranked`）。舊的儲存評估沒有 `reference_state`，自動變成「不用於排序」。

### 6.5 未決
- 規格 §5 的 5 個審查問題仍待審查者回答。
- 預設何時改為 funnel：CI `test_nacl_funnel` 綠（OpenMM 運算式在三個 OS 都能建 Context 並與純 Python 能量一致）＋筆電 3PTB teaching 的 ΔG° 與實驗 −26.8 kJ/mol 誤差 < 8 kJ/mol（§4.3）之後，由使用者決定。
- 報告的 PMF 圖橫軸標籤仍寫「距離」（`workflow_report`／`figures.pmf` 不在本次範圍）；funnel 結果的 `pmf["cv"]` 已記錄。
- 配體多原子 ρ 取質心；很長的配體在圓柱段可能轉動超出 R_cyl（質心受限不代表原子受限），這是標準 funnel 的既有近似。
