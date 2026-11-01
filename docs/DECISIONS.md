# MD20 決策紀錄

依日期由新到舊。每條：主題｜決定｜理由／取捨｜證據（測試、CI、commit）｜未決問題。
判斷錯誤時在原條目下加「更正」，不刪除原文。子系統細節見 `docs/specs/`。

---

## 2026-11-01（第三個 session）

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
