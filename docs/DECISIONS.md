# MD20 決策紀錄

依日期由新到舊。每條：主題｜決定｜理由／取捨｜證據（測試、CI、commit）｜未決問題。
判斷錯誤時在原條目下加「更正」，不刪除原文。子系統細節見 `docs/specs/`。

---

## 2026-11-01（第一個 session，續）

### D-29　鋅鍵結模型測試改為「固定種子、後半段平均」，不再以單一幀判定
- 現象：`test_bonded_zinc_ca2` 在 64166b7 綠、81b72d9 紅（Zn–His119 ND1 2.39 Å vs 2.02），兩者之間 `md20/build` 只改了一行註解——是測試不穩定，不是模型退步。
- 決定：積分器與初始速度固定種子；跑 2 ps 丟掉瞬態，再 2 ps 每 0.1 ps 取樣；**平均**鍵長與 r0 差 < 0.3 Å，且任一幀偏離 < 0.8 Å（真的鬆脫才算）。
- 理由：從晶體座標＋隨機速度起跑，前 2 ps 溶劑未平衡，單一幀是雜訊；鍵結模型的物理主張是「平均幾何守住」，測試要量它主張的東西。容忍值不放寬（0.3 Å 已比 ZAFF 等級的 0.1 Å 寬）。
- 證據：CI heavy (metal)（待這輪）。
- 未決：若平均值也偏 > 0.3 Å，則是模型問題（His119 ND1 的 1-4 或角項），不得再調測試。

### D-27　驅動問題徹底解決：偵測→判定→一鍵下載官方驅動；不自動安裝（使用者要求）
- 決定：`md20/env/drivers.py`：驅動→CUDA 對照表判定 OK/UPDATE/FALLBACK/NONE，NVIDIA 用 nvidia.com 下載頁背後的查詢服務對型號取最新 WHQL 載點，
  只從官方 https 網域下載到 ~/Downloads、不執行；查不到就官方頁面不猜。`md20 drivers`、Doctor finding、GUI 卡片、安裝器 `-Cuda`。
- 被否決：靜默執行驅動安裝器（需管理員與重開機，不該由程式代做）；從非官方鏡像下載；對不到型號時用「最接近」的猜。
- 證據：`tests/test_drivers.py`（11，含查詢服務 fixture）；真機驗證待明早筆電。規格 `docs/specs/drivers.md`。
- 未決：查詢服務非正式 API，變動時退化為官方頁面。

### D-26　Windows 安裝器必須在 Windows PowerShell 5.1 下可跑，且由 CI 真的執行
- 決定：`install.ps1` 移除 PS7 專用的 `?.`／`??`（內建 `powershell.exe` 是 5.1，第一行就語法錯誤）；加 UTF-8 BOM（5.1 讀無 BOM 的 UTF-8 會把中文當 ANSI）；
  設 `PYTHONUTF8=1`；產生 `md20.cmd` 與桌面 `MD20-GUI.cmd` 啟動器。新增 CI job `installer-windows`：用 `shell: powershell`（5.1）跑安裝器，再用 `md20.cmd` 跑 doctor／demo／範本。
- 理由：安裝器是學生與明早測試筆電的第一步，但 CI 用 setup-micromamba 建環境，從未執行過安裝器本身。
- 證據：CI `installer-windows`（待這輪）。文件：`docs/WINDOWS_QUICKSTART.md`（安裝→doctor→demo→GUI→真實案例→回報清單）。
- 未決：CUDA 路徑只能在真機驗證（runner 無 GPU）。

### D-28　f140a49：Ubuntu／macOS openmm-stack 各剩 1 紅（配體連接圖對應）、heavy workflow 1 紅（測試鍵名）
- 事實（run 41320101307）：Ubuntu 342 passed／1 failed（49 分鐘）、macOS 同（68 分鐘）——D-25 的修正生效：質子化教科書案例、HTS 測試、
  縮短後的 GBn2 3PTB、`test_restraint_groups_openmm`（分組約束實算）全過；heavy pose-screen、metal、paper-docking 綠。
  1. `test_shuffled_pose_without_bond_orders_maps_by_graph`：**D-18 我寫的** `_connectivity_match` 用 `AdjustQueryProperties(makeBondsGeneric)` 當查詢，
     但查詢原子仍比對芳香旗標與非零形式電荷；只有座標的 pose 沒有芳香性也沒有電荷 → 苯甲脒的苯環與 NH2+ 對不上。
  2. heavy `test_full_workflow_3ptb`：PBC 檢查以組裝後的配體殘基名（L01）為鍵，測試寫成 BEN（另一 session 的 D-21 測試）。
     實際值顯示功能正確：原始 DCD 看起來 6.95 nm（已解離），歸零後 0.205 nm，並記 AUTO_FIXED。
- 決定：(1) 兩邊都轉成「只剩元素的圖」再比對（`_bare_graph`：電荷 0、非芳香、所有鍵 SINGLE、無立體），仍要求鍵數相同＋完整匹配，
  乙醇／二甲醚的反例照樣被擋；(2) 測試改為檢查每個配體的 `true_nm < 1.0`，不綁輸入名稱。
- 證據：待下一輪 CI（容器沒有 RDKit）。

### D-25　c4b5de6 openmm-stack 三 OS 紅：質子化 SMARTS 寫錯、HTS 純路徑測試遇到 RDKit、GBn2 在 CPU 極慢
- 事實（run 41309973844；Ubuntu 16 failed／239 passed，87 分鐘；Windows／macOS 撞 90 分鐘上限）：
  1. **我寫的** `ionize` 脂肪胺規則 `[NX3;…;!$(N-[!CX4])]`：SMARTS 隱式 AND 比 `!` 緊，`[!CX4]` 是「非脂肪碳 **且** 4 連接」，
     幾乎什麼都不匹配 → 苯胺、乙醯胺、醯基胍、已帶電苯甲脒的 NH2 都被質子化（苯甲脒變 +2）。這是 D-18 的錯，本地沒有 RDKit 所以沒抓到。
  2. `test_ligand_mapping`：numpy.int64 傳給 `Conformer.GetAtomPosition`（Boost 不收），測試本身的錯。
  3. HTS 的 `test_screen_library`／`test_screen_workflow`（另一個 session）：測試用 1 原子的假 SDF，在有 RDKit 的環境被大小篩選
     （5–80 重原子）全部略過。程式行為正確，是測試只為無 RDKit 環境寫。
  4. `test_3ptb_build_and_short_md`／胜肽：D-22 的 `np` 未匯入（D-24 已修）。
  5. **GBn2 3PTB 測試在 Ubuntu CPU 跑了 3921 s（65 分鐘）才通過**；Windows/macOS 因此超時。CustomGBForce＋NoCutoff 是 O(N²)，
     CPU 上每次能量評估約秒級。
- 決定：(1) 規則改為 `!$(N~[#6;!X4])`（任何非 4 連接的碳鄰居都排除），程式內註明這個 SMARTS 陷阱；
  (2) 測試以 `int` 索引；(3) 兩個 HTS 測試檔加 autouse fixture 把 `_rdkit_available` 固定為 False（RDKit 路徑由 `test_screen_integration` 驗證）；
  (4) GBn2 整合測試縮到每 stage 0.4 ps、最小化 100 次（只驗管線，不驗物理）；GBn2 的決策說明改為「**有 GPU 才明顯較快，CPU 上可能比顯式水慢**」。
- 更正 D-20／`implicit_solvent.md`：原寫「筆電上快很多」只對有 GPU 的筆電成立。使用者主力 GTX 1060（OpenCL）適用；純 CPU 筆電不該推薦 GBn2。
- 被否決：把 openmm-stack 步驟上限從 90 分鐘拉長（掩蓋真問題）；預設給 GB 加截斷（改變物理，需另行驗證）。
- 未決：GBn2 在 CPU 平台時應自動 NEEDS_HUMAN 或建議 explicit（需要在 workflow 取得實際平台）；GBn2 截斷（2 nm、CutoffNonPeriodic）的準確度與速度評估；
  NaCl PMF 測試 1190 s 偏長。

### D-24　heavy CI 紅：`np` 未匯入（fc4da13）＋純 Python 靜態未定義名稱檢查；鋅鍵結模型確認修好
- 事實：c4b5de6（run 41309973844）heavy workflow 與 pose-screen 都死在 `build/assemble.py` 溶劑化後的 `np.linalg.det`
  （D-22 新增的盒體積紀錄；模組沒有 `import numpy as np`）。同一輪 **heavy metal 全綠**——`test_bonded_zinc_ca2` 通過，
  另一 session 的經金屬 D–M–D′ 1-3/1-4（9c20327）確實修好 Zn–His 配位漂移（12dcd80 時 2.03→2.56 Å）。
- 決定：模組層補 `import numpy as np`；新增 `tests/test_static_names.py`：以標準庫 `symtable` 檢查每個函式引用的全域名稱
  都在模組層定義或為 builtin（容器與 CI 都沒有 pyflakes，不新增依賴）。已驗證拿掉該 import 時此測試會紅。
- 理由：這類錯誤只在 OpenMM 路徑上執行到才爆，heavy 要 10 分鐘以上才看到；靜態檢查在 6 個純 Python 平台幾秒內擋下。
- 被否決：在 pure-python CI 安裝 pyflakes/ruff（多一個依賴與版本漂移；本檢查只需要未定義名稱這一類）。
- 未決：屬性錯字、參數錯誤仍只能靠整合測試。

### D-23　約束策略修正：分組約束、主要釋放移到 NPT、配體 k ≥ 蛋白、受約束 RMSD 標註（會診 §1 Q1）
- 決定：
  - `add_position_restraints` 改為**單一力、三組**：`msw_position_restraints` 每粒子參數 `k, x0, y0, z0, grp`
    （0 主鏈 N/CA/C/O/OXT、1 蛋白側鏈重原子、2 配體重原子），能量 `0.5·msw_restraint_scale·msw_rs_<grp>·k·d²`；
    各組 `msw_rs_*` 預設 1.0。k：主鏈 1000、側鏈 1000、**配體 1000（原 500）**。水、離子、金屬、輔因子不約束。
  - `make_protocol(restraints=standard|gentle|hold_backbone)`，設定鍵 `md.restraints`（未知值 → NEEDS_HUMAN，選項可一鍵寫回）。
    standard：NVT 主倍率固定 1.0、bb 1→1、sc 1→0.5、lig 1→1（只升溫）；NPT bb 1→0、sc 0.5→0、lig 1→0；production 0。
    gentle：NVT 全 1→1，NPT 全 →0 且 NPT 長度 ×2。hold_backbone：NPT bb 1→0.05，production bb 0.05（50 kJ/mol/nm²）全程。
  - `engine.protocol.production_restraints()` 判斷 production 是否受約束；`analyse_run` 寫入 `restrained_production`，
    圖例與工作流程報告的 RMSD 欄標「受約束；低 RMSD 不代表結構穩定」。
  - SMD／umbrella（`build_pulling_system`）把配體**與側鏈**的 k 設 0，只留主倍率縮放後的主鏈；舊 build（4 參數、無 grp）照舊處理。
- 理由：會診 Q1——Amber／Desmond 都在 NPT 內釋放，NVT 中釋放＝在錯誤密度下鬆弛；k ≤ 1000 的位置約束對 barostat 體積偏差可忽略，
  先前 WP4「約束主要在 NVT 放掉」的顧慮被業界慣例否決。最小化時配體 k 低於蛋白是反的（溶劑未鬆弛前對接 pose 最容易漂）。
  單一力＋`grp` 參數比三個力好：binding、metal 整合測試與舊 system.xml 都只認 `msw_position_restraints` 這個名字。
  側鏈在拉離時必須自由，否則口袋無法重排、PMF 偏高。
- 取捨／影響：預設 protocol 的雜湊改變——**新程式對進行中的舊 run 會從受影響的 stage 重新跑**（identity 不同，這是正確行為：
  約束排程改了，舊平衡不再代表新 protocol）；已 COMPLETE 的 workflow MD 不重跑。側鏈現在也被約束（原本不約束），最小化與 NVT 更穩。
- 被否決：三個分開的力（破壞既有名稱約定）；把主倍率也做斜坡（與各組斜坡重複、難以閱讀）；hold_backbone 直接當預設（低 RMSD 誤導學生）。
- 證據：`tests/test_restraint_strategy.py`（7，純 Python：排程、連續性、gentle/hold、未知策略擋下、GUI 一鍵、報告標註）、
  `tests/test_restraint_groups_openmm.py`（Reference 平台實算各組能量與 binding 釋放側鏈；CI openmm-stack 驗證）。
- 未決：`recommend_restraint_strategy`（依解析度、AlphaFold、補 loop、碰撞、胜肽、金屬自動建議 gentle）尚未做；凍結與截斷仍在規格階段。
  hold_backbone 時 NPT 末段 density 驗收仍在約束下計算（可接受，待真實資料確認）。

## 2026-11-01（第三個 session）

### D-22　水盒不過大：菱形十二面體 + tier padding + 下限閘門（使用者原則）
- 決定：預設 `box_shape=dodecahedron`（立方的 71%）；`padding_nm` 未指定時 classroom／teaching 0.8、research 1.0；< 0.6 nm NEEDS_HUMAN；
  篩 pose 短 MD 用 min(pad, 0.8)；`md.ionic_strength_molar` 可設 0（只中和）。水比例閘門改為說明而非警告。
- 理由：算力在水（80–90% 原子），立方盒以最長軸定三邊對細長蛋白浪費最大；鹽 < 1% 原子，不是成本（誠實告知）。
- 被否決：長方盒貼合蛋白（蛋白旋轉後短邊碰影像）；padding 0（蛋白與影像直接接觸）。
- 證據：`test_binding_raises_padding`；CI `test_3ptb_build_and_short_md` 斷言非對角盒向量且水 < 9000。規格 `docs/specs/solvent_box.md`。
- 未決：0.8 nm 對 teaching 是否太緊；十二面體在 VMD 的顯示。

### D-21　週期邊界歸零：分析層錨定＋歸零 DCD，不在模擬中加力（使用者痛點）
- 決定：`analysis/pbc.py`＋`traj.center_trajectory`：錨＝蛋白鏈＋bonded 金屬（manifest），其他分子以質心最小影像折回，錨質心置盒中心；
  `analyse_run` 一律輸出 `production_centered.dcd`／`production_aligned.dcd`，可重現包含歸零版；viewer 走同一條。
  `apparent_vs_true_distance` 在原始與歸零後差 > 0.5 nm 時記 AUTO_FIXED「視覺性假象」。
- 理由：蛋白擴散是物理，`CMMotionRemover` 只除整體質心；症狀來自 per-molecule 折回與 mdtraj 自猜錨（多鏈／胜肽／金屬是獨立分子）。
- 被否決：模擬中加「歸零」約束（改物理）；把 `enforcePeriodicBox=False` 寫 DCD（原子座標無界、檔案與工具相容性差，且仍需 image）。
- 證據：`tests/test_pbc_centering.py`（6）；CI `test_full_workflow_3ptb` 斷言歸零檔與 `true_nm`。規格 `docs/specs/pbc_centering.md`。
- 未決：多配體互相錨定；三斜盒只靠 mdtraj。
- 另一個 session 留言（GBn2 無週期盒）：已處理——`center_trajectory` 無盒時只置中（質心到原點）、不折影像。

### D-20　隱式溶劑 GBn2（會診 §1 Q6）
- 決定：`md.solvent: explicit|gbn2`、`docking.pose_md_screen.solvent`；細節見 `docs/specs/implicit_solvent.md`。
  GB 力用 OpenMM 內建 `GBSAGBn2Force`（依元素／鍵結指派 mbondi3），因為 `implicit/gbn2.xml` 對 OpenFF/GAFF 配體沒有參數。
  NPT 改 NVT、約束排程保留；金屬位點與結合自由能在 gbn2 下 NEEDS_HUMAN（GUI 一鍵改回 explicit）。
- 取捨：預設仍為 explicit；篩 pose 預設是否改 gbn2 等三個 OS 的 CI 結果再決定。被否決：用 `implicit/gbn2.xml` 加配體樣板（每個配體都要補 GB 參數，不可行）。
- 證據：`tests/test_workflow_gates.py::test_gbn2_protocol_and_binding_gate`（本地）、
  `tests/test_real_case_integration.py::test_3ptb_gbn2_implicit_solvent_short_md`（三 OS CI）。

### D-19　重測拆成平行 job（會診 §5 Q2）
- 決定：`openmm-stack` 三個 OS 跑同一套（不帶 MD20_HEAVY）；新增 `heavy` job（Ubuntu）矩陣 workflow／pose-screen／metal 平行，
  各自 75 分步驟上限、各自貼「CI heavy (<組>)」留言（`tail -c 40000 pytest.log`，含 traceback）。
- 理由：單一 job 時任何一項慢（3e7f941：NaCl PMF 與 3PTB 全流程各 > 15 分）就讓整個步驟在 100 分逾時，被殺掉的 pytest 不印 FAILURES，
  `test_bonded_zinc_ca2` 的失敗原因連續三輪讀不到。
- 取捨：每個 heavy job 各自建環境（多約 3 分 × 3，有下載快取）；換來失敗可診斷與總時間縮短。

### D-18　採納會診 §0：配體依 pH 7.4 主要離子態對接；GUI 預設只本機可連
- 配體質子化：在 `docking/run.py::_ligand_mol`（SMILES 與 SDF 兩條路、HTS 也經過）呼叫 `docking/ionize.py`。
  MD 建模的 SMILES 取自對接結果裡的分子，所以對接、HTS、MD 三邊同一電荷態。
  - 規則只處理 pKa 離 7.4 夠遠的類別（羧酸、磺酸、磷酸第一個 OH、四唑、醯基磺醯胺 → −1；sp3 脂肪胺、脒、胍 → +1）；
    咪唑、羥肟酸、磷酸第二個 OH 等接近 7.4 的不改、只註記；已帶電的基團不動（使用者明寫的電荷態保留）；
    陽離子 3 個鍵內的第二個胺不質子化（piperazine pKa₂ 5.6）；pH 偏離 7.4 超過 1 時規則不套用並註記。
  - 被否決：引入 dimorphite-dl（會診建議）。理由：規則表透明、可教、零新依賴，且 dimorphite 在 pKa 精度窗內會給多個態、仍需選擇規則；
    若之後需要更廣的官能基覆蓋再接 dimorphite 作為可選後端。
  - `docking.protonation: auto|as_given`（全域；每個配體可覆蓋）；HTS `screen.protonation`／`screen.ph` 預設跟隨工作流程。
  - 證據：`tests/test_ionize.py`（23 個教科書 pKa 類別＋SDF 座標保留；需 RDKit，CI）。
- GUI：`md20 gui` 預設 `--host 127.0.0.1`；`0.0.0.0` 需明確指定並印出警告。`tests/test_gui_logic.py::test_gui_listens_on_localhost_by_default`。
- 會診 §0.3（舊規格標示取代）已由另一個 session 完成。

### D-17　REVIEW #15／#16：配體直接配位金屬要擋；pose 對應要比連接圖，不能只比元素順序
- #15 決定：組裝時在配體加入後、溶劑化前，對整個複合物重新找「配體 N/O/S 在金屬配位距離內」（N ≤ 2.45、O/S ≤ 2.6 Å）。
  有 → NEEDS_HUMAN（選項：換 pose、MCPB.py/QM 參數化後匯入、metal_policy remove〔僅限非功能必要，GUI 可一鍵〕）。
  理由：金屬位點原本只在受體上分析，對接 pose 咬住金屬時永遠不會被發現；力場沒有配體–金屬鍵，非鍵結模型下配位會散開或塌陷。
- #16 決定：模板指定鍵級失敗時，不再接受「元素序列逐一相同」的原子順序對應；改為由 pose 座標判斷連接（不計鍵級）、
  與參考分子做「鍵類型不限」的子結構比對，原子順序不同也能對上；鍵數或連接圖不同 → NEEDS_HUMAN。
  理由：乙醇 C–C–O 與二甲醚 C–O–C 可以有相同元素順序，舊後備會把座標貼錯原子且標 AUTO_FIXED。
- 證據：`tests/test_metal.py::test_ligand_coordinating_metal_is_stopped_after_assembly`（本地）；
  `tests/test_ligand_mapping.py`（需 RDKit，openmm-stack CI）。組裝路徑的真實檢查待 CI。

### D-16　補窗必須可續跑且冪等：完成的輪次不重新規劃
- 問題（3e7f941，Windows OpenCL，`test_nacl_pmf`）：第二次呼叫 `run_binding`（續跑）得到不同 ΔPMF（3.518 → 3.396 kJ/mol）。
  續跑時補窗迴圈從第 1 輪重新開始，拿已補過的全部樣本重新規劃，又多補 window，改變了已完成的 PMF。
- 決定：`refine_log.json` 每輪完成時標記 `completed`；`refine_state.json` 記錄是否已結束與手動 window 簽章。
  續跑從下一個未完成輪次接續；已結束則整段略過。只有使用者加入新的手動補採樣區間時才重新開啟，並給一份新的輪次預算。
- 被否決：只比對 window 檔案是否存在（無法區分「中途暫停」與「已結束」）。
- 與第四個 session（21bb0f1）合併：對方的 `finished_result()` 處理「已完成 → 直接回傳儲存結果」，並限制每個 window
  最多延長 2 次（`max_extensions_per_window`，解決同一測試的 15 分鐘逾時）；本條的輪次標記處理「中途暫停／當機後續跑」，
  兩者互補。延長次數改以 `w_<c>_ext*.done` 檔案計數，手動請求重開的輪次也算在內。
- 證據：待 CI（`test_nacl_pmf` 的冪等斷言）。同輪 Windows 其餘 170 個測試通過。

### D-15　決策與規格一律寫進 repo 的 Markdown
- 決定：任何專項修改都把討論結論或判斷寫進 `docs/DECISIONS.md`（本檔）與 `docs/specs/`，與程式碼同一個 commit 推送。規則寫入 `CLAUDE.md`。
- 理由：使用者要能審查、做版本管理，並用其他模型審查規格後回饋。
- 附帶：只改文件的 push 不再觸發 CI（`paths-ignore: docs/**, *.md`），避免文件更新取消正在跑的長時間重測。

### D-14　hsieh2024 無法重現的原因：ADT 格點數被當成 Vina 的 Å
- 決定：以 CI 量測結論更新教學案例；建議新增「盒子過大」防呆閘門（待審查，見 `docs/specs/REVIEW_QUESTIONS.md` 第 5 點）。
- 證據（37bc6b1，`test_hsieh2024_box_hypotheses`）：論文盒子照字面 28.5×34.5×26.25 Å 在 1VKX 框到 0/11 個報告殘基；
  讀成 76×92×70 Å（格點數誤當 Å）框到全部 9 個存在的報告殘基；中心距 1VKX 原子 0.48 Å、在 1VKF 中落於蛋白外 39.6 Å。
- **更正**：先前判斷「主因是中心座標來自另一座標系」是錯的；使用者提出的格點間距混淆假設才正確。

### D-13　傘狀採樣改為由粗到細的智慧補窗，並提供即時覆蓋圖與手動補採樣
- 決定：見 `docs/specs/umbrella_adaptive.md`。依實際取樣分佈找空洞、大缺口一輪補多個、陡處才加硬 k（漂移 ≲ 2σ、上限 5000）、
  中心預先往上坡偏移；以合併直方圖判定連續；樣本不足延長不複製；補不起來時回報並停止；不連續則不輸出 ΔG°。
  手動「從 a 到 b 補採樣」只重開該結合目標。
- 理由：Colab 版 PMF 斷點來自 window 被斜率推離中心，舊的中點同 k 補窗補不到。
- 取捨：平滑剖面上新規則比舊規則多用約 50% window（換較小誤差）；目標重疊 0.15 時陡牆補不連續，所以預設 0.2。
  「漂移 ≤ σ/2」的 k 規則被否決（把 k 頂到上限、過度採樣）；自動補窗的中心偏移上限用 1σ（3σ 在陡牆案例過衝）。
- 證據：`tests/test_adaptive_windows.py`、`tests/test_umbrella_manual.py`（合成剖面、精確偏壓取樣）；commit 3e7f941；真實 OpenMM 路徑待 CI。

### D-12　約束策略、凍結、口袋截斷：先設計、等審查再實作
- 決定：見 `docs/specs/restraints_freeze_truncation.md`（狀態：設計中）。使用者選擇「全部都做」（分組分階段約束＋智慧建議、凍結選項、口袋截斷＋資源估算）。
- 關鍵判斷：OpenMM（及使用 Verlet cutoff 的現代 GROMACS）凍結原子不會減少力的計算，凍結的價值是穩定性與教學隔離；
  真正省資源要靠減少原子數（截斷模型）。已向使用者說明並取得同意。
- 已做：引擎掛鉤 `StageSpec.restraint_groups`、`StageSpec.freeze`（預設值不進 protocol 雜湊，進行中的 run 可續跑）。

### D-11　幾何金屬鍵結模型：金屬–配位原子比照共價鍵處理非鍵作用
- 決定：1-2、1-3 排除，1-4 縮放（靜電 ÷1.2、LJ ÷2），加金屬–配位原子–鄰原子角。
- 理由：CI（12dcd80）中 3KS3 鋅位點 Zn–NE2 由 2.03 被推到 2.56 Å；只排除 1-2 時 Zn²⁺ 與咪唑環 CE1/CD2 及其氫的斥力仍在。
- 狀態：37bc6b1 的 Ubuntu 重測中 `test_bonded_zinc_ca2` 仍失敗，該輪被取消、沒有 traceback；待 3e7f941 的結果。**未解決。**

### D-10　金屬擬合參數：內建 Hessian 轉換＋MCPB.py 轉譯＋JSON，不依賴 AmberTools
- 決定：見 `docs/specs/metal_sites.md`。Hessian 以 Wilson B 矩陣 pseudo-inverse 轉內座標力常數；Seminario 只當交叉檢查。
- 理由：使用者授權「內建或轉譯，自己處理」；Windows 無 AmberTools。modified Seminario 在共用角高估約 30%（測試量到），故不採用。
- 證據：`tests/test_metal_params.py`；JSON 路徑在 Ubuntu 真跑通過（12dcd80）。

### D-9　閘門一鍵決定只給「程式真的會執行」的選項
- 決定：見 `docs/specs/gate_actions.md`。同時修正受體閘門 `human_choices` 會接受未實作選項的漏洞。
- 證據：f879764 Windows/macOS GUI 伺服器測試通過。

### D-8　3D 互作標示採純距離準則並明示近似
- 決定：見 `docs/specs/viewer_interactions.md`。氫鍵不檢查角度、表面為 vdW 球，畫面與報告寫明。

### D-7　論文對接重現移出必綠的重測，改為獨立非阻擋 CI 工作
- 理由：六配體同時對接與 7 胜肽對接在 4 核 runner 上要數小時，讓重測卡死；這兩個重現從未在 CI 跑完過（更正先前文件說法）。
- 做法：`paper-docking` job（exhaustiveness 8，JSON 標明為縮減搜尋）；加 faulthandler 與步驟逾時。

### D-6　第一次完整 Ubuntu 重測抓到的 bug 一律修在產品，不放寬測試
- altloc 被當重複原子名；`_md20` 戳記欄位讓結果檔讀不回；短 stage 記錄太少且「延長 0 ps」；padding 讀錯鍵名且套到不需要的系統；
  setup-vina 遇 GitHub API 限流。細節見 `docs/specs/ci_validation.md`。
