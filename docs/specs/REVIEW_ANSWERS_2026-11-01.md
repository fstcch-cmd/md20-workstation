# 開發文件會診（2026-11-01）— 審查者回答與需要補強的地方

審查對象：`docs/` 全部（HANDOFF、STATUS、WORKFLOW、TEACHING、COMPATIBILITY）與 `docs/specs/` 全部。
角度：資深軟體工程師＋蛋白質科學家。每一條標明**信心**：〔確定〕有文獻／原理支撐；〔建議〕專業判斷；〔待查〕需要查證或實測。
程式缺陷不在此（見 `../REVIEW_2026-11-01.md`）；這份只談設計與文件。

---

## 0. 先改的三件事（影響最大、成本最低）

1. **HTS 與對接的配體質子化是空白**〔確定〕。PubChem 3D／ChEMBL 給的是**中性**分子；胺基酸、羧酸、脒基、胍基在 pH 7.4 多半帶電，
   以中性型對接會系統性低估或高估分數與氫鍵，受體卻是依 pH 加氫的——兩邊不對稱。500 個化合物裡這會是最大的系統誤差來源，
   比 exhaustiveness 大得多。最小做法：規則式離子化（dimorphite-dl，純 Python、MIT）在 pH 7.4 產生主要質子化態 → AUTO_FIXED 並記錄
   「以 pH 7.4 主要離子態對接」；多個態時選 pKa 最接近的一個、其餘記在 notes。沒有離子化器時，至少在篩選表標記「含可離子化基團、以中性型對接」。
2. **GUI 預設綁 0.0.0.0**〔確定，`app.py` `ui.run` 未指定 host；NiceGUI 預設 0.0.0.0〕。教室 Wi-Fi 上任何人都能開別人的 GUI、按「開始／暫停」、
   改 config、下載專案檔（`/file` 只擋在 projects 根目錄之外）。改為預設 `127.0.0.1`，`--host 0.0.0.0` 才對外，README 寫明。
3. **`docs/specs/docking.md` 與 `gui.md` 是第一個 session 的舊規格，和現在的程式不符**（沒有 `ligands.py`／`select.py`／`handoff.py`／Meeko 受體；
   GUI 不是七頁 drawer）。會誤導下一個 session。在檔頭標「**已被取代**，現況見 WORKFLOW.md 與 hts_screen.md」或直接刪除。

---

## 1. `restraints_freeze_truncation.md`（設計中，最該在實作前改）

### 回答審查問題
**Q1 預設數值與藥廠慣例**〔確定〕
- 主鏈 1000 kJ/mol/nm² 是 GROMACS `posre` 慣例（≈2.4 kcal/mol/Å²）。Amber 教學流程用 10 → 5 → 2 → 1 → 0.5 kcal/mol/Å²（4184 → 209 kJ/mol/nm²）
  **在 NPT 中分階段釋放**；Desmond 預設鬆弛也是在 NPT 保留溶質重原子約束。所以「絕對位置約束＋barostat 會偏壓體積」這個顧慮
  （§1 WP4）**全業界都接受**：k ≤ 1000 且體積變化 < 5% 時偏差可忽略。建議把釋放的主要階段移回 NPT（NVT 只升溫、約束全程 1.0），
  因為在 NVT 裡釋放約束＝在錯的密度下讓蛋白鬆弛；`standard` 改為 NVT bb 1→1、sc 1→0.5，NPT bb 1→0、sc 0.5→0、lig 1→0。
- `hold_backbone` 全程 50 kJ/mol/nm²：可以，但**報告的 RMSD／RMSF 驗收必須標註「受約束」**，否則學生會把低 RMSD 當成穩定。
  現在 acceptance 以 RMSD 判定的地方要帶這個旗標。
- 配體在最小化階段的 k（500）低於蛋白（1000）是反的：最小化是對接 pose 最容易漂走的時候（溶劑還沒鬆弛）。建議最小化時配體 ≥ 蛋白。

**Q2 殼層：約束 vs 凍結、4 Å 夠不夠**〔建議〕
- 約束殼層優於凍結（凍結殼層的原子與移動原子之間的鍵／角項會把邊界處拉出高能量，且與 NPT 不相容）。
- 4 Å 只有一層原子，殼層外的「失去堆積」會往內傳 2–3 層。建議：**R−4…R 強約束（1000）＋ R−8…R−4 主鏈弱約束（100–200）**，
  口袋 8 Å 內完全自由。這才是「截斷模型」文獻（Desmond FEP+ 的 solute restraints、CHARMM SBMD）的做法。

**Q3 帽與淨電荷**〔確定〕
- ACE/NME 正確（Amber 標準、OpenFF/GAFF 無關）。中性 NH2/COOH 末端在 Amber 力場裡會多出帶電末端樣板的問題，不要。
- 反離子中和**總**電荷夠，但真正的問題是**截面上暴露的埋藏帶電殘基**（原本在蛋白核心的 Asp/Glu/Lys/Arg 突然泡進水）。
  規則：選 R 時以「殘基完整」為單位，**不要把二級結構切半**（整條 helix／strand 要嘛全留要嘛全丟），並把截面上的帶電側鏈列入 `shell` 約束組。

**Q4 截斷模型做 SMD／umbrella**〔確定〕
- 拉離距離預設 1.5 nm > R = 1.2 nm，一定要閘門：`pull_distance_nm ≤ (R − 4 Å)/10`。
- 更根本：截斷後「bulk」參考態是假的（配體在出口處看到的是人造截面），**ΔG° 禁止輸出**，ΔPMF 只允許「同一截斷模型內配體間比較」，報告標「truncated」。

**Q5 凍結後 NVT 的體積**〔確定〕取 NPT 末段 50% 的平均體積，**挑最接近平均體積的那一幀**（不要平均座標）。

**Q6 更好的省資源方案**〔建議，這題最重要〕
- MD 成本 ≈ 80–90% 在水。**先試「padding 1.0 → 0.8 nm」與「只約束外圍、不截斷」**：物理正確、零新程式。
- **隱式溶劑（OpenMM 內建 `GBn2`）**：原子數直接少 80–90%、無 PME，是筆電上唯一「真的快很多」且不需要截斷的選項。
  適合：**WP5 短 MD 篩 pose**（只問 pose 會不會散）、classroom tier 的教學 MD。
  不適合：金屬位點、以水橋接的結合、SMD/umbrella（溶劑化能障會失真）。建議做成 `md.solvent: explicit|gbn2`，GBn2 時 binding 閘門擋下。
- 截斷模型留作第三順位；`資源估算表`加一列 GBn2。

### 文件沒寫、但實作前必須處理
- **溫度估算的自由度**：`backend.summary()` 用 3N 算溫度；凍結（質量 0）或 TIP4P 虛擬位點時 watchdog 的溫度會錯（審查已指出）。凍結上線前必修。
- 凍結原子與 `CMMotionRemover`、`LangevinMiddleIntegrator`（會跳過質量 0）相容；但 `MonteCarloBarostat` 不相容已寫，**還有 `AndersenThermostat`**（若未來用到）同樣不相容。
- 資源估算公式：水分子數估算用 0.018 nm³/重原子可接受；PME 時間 ~ N log N 近似線性可接受；但 benchmark 用 24k 原子，外推到 100k 以上時 GPU 記憶體可能先爆，表格要列預估記憶體。

---

## 2. `umbrella_adaptive.md`

**Q1 連續性判準**〔確定〕
- 「合併直方圖低於中位數 10%」是實用的，但正式判準應該是 **MBAR overlap matrix**（pymbar `compute_overlap`）：相鄰 window 重疊 < 0.03 即不可靠
  （Klimovich, Shirts & Mobley 2015, *J. Comput.-Aided Mol. Des.* 29:397 的 guideline）。程式已有 `graph_connected`；建議把 overlap matrix 最小相鄰值寫進報告，
  並以它（而不是直方圖）作為「ΔG° 可輸出」的門檻。直方圖判準保留給 GUI 即時顯示。
- 最終判準應是**PMF 的 bootstrap 誤差**：連續但誤差 > 2 kJ/mol 的 PMF 一樣沒用。建議停止條件加「ΔPMF bootstrap σ < 門檻（教學 2、研究 1 kJ/mol）」。

**Q2 k 的規則**〔確定〕k ≥ F′²/(4kT) ⇔ 漂移 ≤ 2σ，推導正確。曲率條件（k > |F″| 才單峰）可以用三個相鄰 window 的 μ(c) 二階差分估 F″；
有三個以上 window 時用它，否則維持現在的 k_max 跳升。

**Q3 預偏移**〔建議〕用前一輪的 μ(c) 關係做局部線性反解（c_new = c + (μ_target − μ(c))·dc/dμ）比固定 ≤1σ 穩；資料不足時退回現在的規則。

**Q4 延長 window 的平衡偵測**〔確定〕延長是從最後一幀接著跑，**不需要**重新平衡；但 `detect_equilibration` 應對**合併後**的序列只做一次（丟掉開頭），不要對每段各丟 10%。

**Q5 補不起來的後備**〔確定，強烈建議〕不要做 HREX（工程量大）。**OpenMM 內建 `openmm.app.Metadynamics`**（well-tempered，7.5+），
同一個 COM 距離 CV、同一個 `CustomCentroidBondForce`，幾十行就能做「umbrella 補不起來 → 改跑 1D 井式 metadynamics」，
而且可以直接重用現有 window 的起始幀。這是最符合「不加 phase、強化既有邏輯」的後備。

### 文件沒寫的科學缺口
- **一維 COM PMF 的 ΔG°（REVIEW_QUESTIONS 第 4 題）**〔確定〕：教學 tier 保持現狀＋caveat 沒問題；研究 tier 建議**不要**做完整 Woo–Roux
  （六個方向／構形約束、六段解除積分，學生做不完），改用 **funnel 約束**（Limongelli, Bonomi & Parrinello 2013, *PNAS* 110:6358）：
  一個圓柱＋圓錐的 flat-bottom 約束（`CustomCentroidBondForce` 幾行），bulk 段被限制在半徑 R_cyl 的圓柱內，
  ΔG° = −kT·ln(C°·πR_cyl²·∫_bulk→bound e^{−W(z)/kT}dz) 的校正是**解析的**。這同時解決「配體在遠端飄出盒子」與「方向自由度」兩個問題，
  與現有 1D 流程相容。
- **胜肽的 CV**：7-mer 的 COM 距離不代表結合／解離（會先部分解開）。胜肽目標的 binding 應閘門為「只給 ΔPMF 定性」或改 CV（接觸數）。
- **replica 誤差**：n = 3 時標準誤的不確定度很大；報 95% CI 時要乘 t(0.975, 2) ≈ 4.3，或至少在報告寫「3 個 replica 的 SE 本身誤差約 ±50%」。

---

## 3. `metal_sites.md`

**Q1 1-4 縮放與金屬 LJ**〔確定〕1-2/1-3 排除＋1-4 縮放正是 tleap 對 MCPB.py/ZAFF 鍵結模型的處理，正確（含本 session 補的經金屬 D–M–D′）。
MCPB.py 本身**不擬合**金屬 LJ，而是沿用 Li & Merz 的 12-6 參數（對鍵結模型通常取 **IOD 組**，依水模型選）。建議 `bonded` 模式時明確把金屬 LJ 設為
Li–Merz IOD（TIP3P）值並寫進 decision；現在沿用力場的離子參數是 HFE 組還是 IOD 組要查（〔待查〕openmmforcefields 的 Amber 離子集）。

**Q2 力常數依金屬／配位原子**〔確定〕應該分。ZAFF 的量級：Zn–N(His) ≈ 40–60、Zn–S(Cys) ≈ 70–90、Zn–O(Asp/Glu) ≈ 80–100 kcal/mol/Å²；
Fe/Cu 的 M–N 偏低、M–O 偏高。做一張 `{元素}×{N,S,O}` 的小表當預設，QM 擬合覆蓋。單一 46 太粗。

**Q3 Wilson-B pseudo-inverse**〔建議〕在冗餘內座標下 pseudo-inverse 是最小範數解，物理意義是「耦合項平均分配」；對 M–D 鍵通常可接受，
對共用角會比 Seminario 低、比 modified Seminario 準（你們的測試正是這個結論）。兩點要補：
(a) **Cβ 固定的 Opt+Freq 會產生對應約束自由度的假模式**，投影前必須把 Cβ 的列／行從 Hessian 移除（確認 `metal_params.py` 有做）；
(b) 與 Seminario 鍵值差 > 30% 時應 NEEDS_HUMAN 而非只記 log。

**Q4 QM 方法**〔確定〕Zn（閉殼層 d¹⁰）B3LYP-D3BJ/def2-SVP 教學夠用；**Fe/Cu/Mn/Co/Ni 不行**：def2-SVP 對過渡金屬太小、B3LYP 自旋態能量不可靠。
最低建議：金屬 def2-TZVP、其餘 def2-SVP（混合基組），泛函 TPSSh 或 ωB97X-D，並要求使用者給自旋多重度（已做）。

### 文件沒寫
- **配位水被移除、位點開放**：CA II 的 Zn–OH⁻ 是催化中心，拿掉等於 3 配位的鋅；幾何模型只有 3 個鍵角，四面體會變形。
  建議：配位水保留為 TIP3P 並以 M–O 鍵納入鍵結模型（或讓使用者指定 OH⁻），至少要在閘門問。
- **配體直接配位金屬**（審查 #15）：這是 Zn 金屬酶藥物（hydroxamate、sulfonamide）的常態，不只是「未做」，是教學案例裡最常遇到的情境；
  第一版可以做「非鍵結＋距離約束（M–配體原子 flat-bottom）」而不擬合參數，誠實標註。

---

## 4. `gate_actions.md`：長 loop 的可點選項

值得做〔建議〕，而且截斷模型要寫的「ACE/NME 加帽」程式可以直接重用：
- `≤ 6 殘基且有 SEQRES` → PDBFixer 補建（現狀）＋補建後**約束短 MD**（loop 以外 1000、loop 自由，20 ps）檢查 loop RMSF < 3 Å；
- `7–12 殘基` → 兩個按鈕：「截斷加帽（loop 兩端變 NME/ACE）」與「PDBFixer 補建並接受風險」；
- **loop 任何一端在口袋 8 Å 內 → 一律 NEEDS_HUMAN**，不給一鍵（補出來的 loop 會直接影響對接與 PMF）；
- 門檻：補建後 loop 與鄰近殘基無 < 2.0 Å 重原子接觸、主鏈 C–N 全部 < 1.6 Å（本 session 已加後者的檢查）。

---

## 5. `ci_validation.md`

- **Q1 exhaustiveness 8 不足以對六配體同時對接下結論**〔確定〕；但加大 exhaustiveness 也救不了口袋 107 Å³ 塞 1386 Å³ 的幾何矛盾——
  結論已經成立，不需要更多算力。建議改成**3 個 seed × exhaustiveness 8 取最佳**只為了讓 hsieh2025 的分數有誤差棒。
- **Q2 拆 job**〔確定〕拆：`heavy-workflow`（3PTB 全流程）、`heavy-metal`、`heavy-pmf`（NaCl）、`heavy-screen`（HTS）。四個平行 job 各 ~20 分，
  失敗時 traceback 也不會被別的測試淹沒。
- **環境鎖定**：CI 每輪都匯出 lock 檔卻從不 commit。至少把「某 commit 綠」那次的 `md20-lock-<os>.txt` commit 進 `environment/locks/`，
  installer 加 `--locked` 用它；否則 STATUS 的「已驗證」在三個月後就不可重現。

---

## 6. `hts_screen.md`（本 session 新增）— 自我審查

- 第 0 節的質子化問題是這份規格最大的洞。
- 排名只用最佳 pose 的 Vina 分數：教學目的可接受，但加兩個便宜的穩健性指標：**cluster_size ≥ 2**（搜尋重複找到）與
  **Vina + Vinardo 排名的一致性**（兩個函數都在前 20% 才標「穩健」）——第二個要多跑一次對接，可做成選項。
- 去鹽取最大片段：季銨鹽、金屬配合物、雙價藥物鹽（如 co-crystal）會被誤處理；規則改為「只移除已知反離子清單（Na, K, Cl, Br, I, acetate, mesylate…）」，
  不在清單的多片段 → SKIPPED 並說明。
- 1 kcal/mol 門檻：Vina 對 PDBbind 的 RMSE ≈ 2 kcal/mol，1 已經偏寬鬆；可以，但報告要寫「誤差內」是**下限**。

---

## 7. 跨文件的一致性與缺口

| 項目 | 現況 | 建議 |
|---|---|---|
| `target_overlap` 預設 | WORKFLOW.md 寫 0.25，程式與 umbrella spec 是 0.2 | 改 WORKFLOW.md |
| WORKFLOW.md 欄位表 | 沒有 `screen`、`md.restraints`、`md.freeze`、`md.truncate`、`metal_params` 的完整欄位 | 補表；每個欄位附預設值 |
| TEACHING.md | 沒有 HTS；第 4 週對接前應加「高通量篩選與配體效率」（學生最需要的直覺：分數隨分子大小增加） | 加 4b 週 |
| TEACHING.md | 沒有任何一週談**質子化與互變異構**，這是對接結果最常錯的原因 | 第 3 週加 |
| STATUS A 級定義 | 「真實跑過」包含 GitHub runner 的 CPU；使用者機器（GTX 1060 OpenCL）只跑過 doctor 與戳記 | 加「A3 使用者實機」的範圍說明，全流程在學生筆電上還沒跑過要寫明 |
| 戳記 | HANDOFF §7 稱「防盜用」，但第三層是加密非簽章（審查 #20），且公開 repo 無授權 = 預設全權保留，CI 公開反而讓程式碼可被複製 | 文件改口「溯源標記」；加 PolyForm-Noncommercial 或 CC-BY-NC（HANDOFF 已自知） |
| 決策日誌規模 | HTS 一次 500 個化合物、每個對接的 `docking.pose` 決策都寫一行 → 時間軸分頁會爆 | screen 對接的 pose 決策改彙總（已部分做），GUI 時間軸預設摺疊 `screen.*` |
| 受體彈性 | 全程單一受體構形、口袋水全移除 | 文件明寫「剛性受體、無結構水」為已知限制，並在 TEACHING 第 4 週討論 |
| 實驗值校準 | 沒有任何一個案例拿計算 ΔG 對實驗值 | 3PTB 苯甲脒 ΔG_exp ≈ −6.4 kcal/mol（Kd ≈ 20 µM 量級）〔待查精確值〕，作為研究 tier 的「校準檢查點」寫進 TEACHING 第 11 週，不進 CI |

---

## 8. 給下一個開發 session 的優先順序

1. 配體質子化（HTS 與對接共用）、GUI 綁 localhost、刪／標舊規格 — 半天。
2. `md.solvent: gbn2` 給 WP5 篩 pose 與 classroom tier — 一天，立刻讓筆電快 5–10 倍，比截斷模型更該先做。
3. 約束策略：釋放移到 NPT、最小化配體 ≥ 蛋白、hold_backbone 的 RMSD 標註 — 半天。
4. 金屬：力常數表、配位水納入鍵結、配體配位金屬的距離約束後備 — 一天。
5. umbrella：overlap matrix 門檻＋ metadynamics 後備＋ funnel 約束（研究 tier）— 兩天。
6. CI 拆 job＋lock 檔 — 半天。
截斷模型放在這些之後。


---

## 實作採納紀錄（開發 session 填寫）
| 條目 | 採納 | 說明 | 決策／commit |
|---|---|---|---|
| §0.1 配體質子化 | ✅（改用自建規則表，不引入 dimorphite-dl） | 規則透明可教、零依賴；接近 pKa 的基團不猜、只註記 | DECISIONS D-18 |
| §0.2 GUI 預設 127.0.0.1 | ✅ | `--host 0.0.0.0` 才對外並警告 | D-18 |
| §0.3 舊規格標示取代 | ✅（另一 session） | | — |
| §1 Q6 `md.solvent: gbn2` | ✅（預設仍 explicit，待 CI 後再議篩 pose 預設） | GBSAGBn2Force 涵蓋配體；金屬與 binding 擋下 | D-20 |
| §5 Q2 CI 拆平行 heavy job | ✅ | workflow／pose-screen／metal 三組 | D-19 |
