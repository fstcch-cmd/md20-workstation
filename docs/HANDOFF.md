# MD20 開發交接檔(給新的 Claude Code session 接手用)

> 最後更新:2026-11-01(第二個 session,見 §5)。讀完這份就能無縫接續開發與 CI 監看。
> **重點:所有成果都在這個 repo + GitHub Actions 上,不在任何對話容器裡。** 新 session 只要 clone 本 repo 即可完整接手;正在跑的「虛擬機」就是 GitHub Actions CI,與 session 無關,不會因為舊對話結束而消失。

## 0. 新 session 第一步
1. 把 repo 加進 session 並 clone:`fstcch-cmd/md20-workstation`(需要 push 權限)。
2. 讀這幾份:`docs/STATUS.md`(誠實三級現況)、本檔、`MD20_optimization_brief` 的規則(見 §4)、`docs/WORKFLOW.md`、`docs/TEACHING.md`。
3. 看 CI 現況:`gh run list -R fstcch-cmd/md20-workstation -L 3`。**先確認最新一輪 openmm-stack 三個 OS 的結果**(Windows OpenCL 是使用者主力平台,必須綠)。
   - 單次指令:`gh run view <run_id> --json status,conclusion,jobs -q '"\(.status) \(.conclusion)", (.jobs[]|"\(.conclusion // .status) \(.name)")'`
   - 失敗細節 / 論文重現 JSON 在該 commit 留言:`gh api repos/fstcch-cmd/md20-workstation/commits/<sha>/comments --jq '.[].body'`
4. 教學手冊已寫在 claude.ai 文件(非 repo 內):https://claude.ai/artifact/VL3P7wgbQBrPj4Ypd11pCG(九節,用兩篇論文當主線)。要改教材從這份文件改,不是 repo。

## 1. repo 與帳號
- GitHub:`fstcch-cmd/md20-workstation`,分支 `main`,暫時公開僅供 CI(README 已聲明保留權利)。
- 擁有者:HCC Lab, NKUST(Chen-Che Hsieh)。
- Commit 屬名(每次 commit 結尾加):
  ```
  Co-Authored-By: Claude <noreply@anthropic.com>
  Claude-Session: <你這個 session 的連結>
  ```
  (新 session 會有自己的 session 連結,用自己的即可。)

## 2. 開發沙盒的硬限制(務必知道,否則會卡住)
- 容器網路白名單**只有** PyPI/conda/GitHub。**連不到 RCSB、任意網站**(curl/wget 會被擋)。需要 PDB 檔請用 `gh` 或請使用者附上,不要繞道。
- 容器**裝不了 OpenMM/RDKit/OpenFF/Vina**(重環境)。所以:
  - 本地只能用 `FakeBackend` 測邏輯(pure-python 測試)。
  - **真實 OpenMM/Vina 測試一律交給 CI**(`openmm-stack` 矩陣)。不要試圖在容器裡裝這些。
- 不要用長 `sleep`+`for` 輪詢迴圈查 CI,也避免看起來像 `rm -rf $VAR` 的語法——會觸發安全檢查/分類器中斷。**改用單次指令**。

## 3. CI 運作方式(怎麼看結果)
- Workflow:`.github/workflows/ci.yml`,兩類工作:
  - `pure-python`:3 OS × Py3.11/3.12,忽略 5 個重測檔;**這是必綠的門檻**。
  - `openmm-stack`:3 OS 真實 OpenMM+Vina 用 micromamba 建環境;Ubuntu 帶 `MD20_HEAVY=1` 會多跑重測 + 兩篇論文對接重現。
- `concurrency: cancel-in-progress` → **一 push 新 commit,舊 run 還在跑的工作會被 cancel**。所以看到舊 run 的 mac/ubuntu 是 `cancelled` 多半是被新 push 取消,不是失敗。要等完整結果,push 完就別再 push,讓它跑完(Ubuntu 重測約 15–25 分)。
- 看結果(單次指令,不要輪詢):
  ```
  gh run view <run_id> -R fstcch-cmd/md20-workstation --json status,conclusion,jobs \
    -q '"\(.status) \(.conclusion)", (.jobs[]|"\(.conclusion // .status) \(.name)")'
  ```
- 失敗 log / 測試摘要 / 論文驗證 JSON 都由 CI 貼到該 commit 的留言:
  ```
  gh api repos/fstcch-cmd/md20-workstation/commits/<sha>/comments --jq '.[].body'
  ```

## 4. 必守的開發規則(來自 MD20_optimization_brief)
- **不新增 phase/step**,只強化既有邏輯。
- **三態閘門**:`PASS` / `AUTO_FIXED` / `NEEDS_HUMAN`(見 `md20/build/gates.py`)。
- 每個自動決策寫進 `DecisionLog`,`why` 用**中文**講清楚原因(`md20/util/decisions.py`)。
- **寧可擋(block)也不要猜**:條件不足就 `NEEDS_HUMAN`,附可行選項。
- `STATUS.md` 要誠實(真跑過 / 靠 CI / 未完成 三級),不誇大。
- 任何改動都要有測試且 CI 綠才算完成。

## 5. 現在的狀態(2026-11-01,第二個 session 之後)
- 各工作包的真實驗證狀態以 `docs/STATUS.md` 為準(三級)。
- 已完成工作包:WP0, WP2–WP13 全部有實作與測試;另修了「binding/analysis 讀不到配體原子索引」的 bug
  (`build_manifest.json` 被 `build_case` 覆寫後,索引只在 `assembly.ligands`;現在頂層也帶索引,讀取一律走 `workflow.manifest_ligands()`)。
- 第二個 session 新增:
  - **WP5** `md20/docking/pose_screen.py` + `Workflow.choose_poses(screen=...)` / `_screen_pose`:短 MD 篩 pose(結果快取在 `workflows/<name>/pose_screen.json`,暫停可續)。
  - **WP9** `md20/sampling/multi.py`:拉離路徑閘門、`compare_binding`(ΔΔ ± 2σ、共存效應);`Workflow._binding_targets` 把 docked_multi 每個配體列為 `multi:<名>`。
  - **金屬** `md20/build/metal.py`:`metal_policy` 真正套用(remove/keep_nonbonded/bonded);bonded = 晶體幾何鍵/角 + 排除 1-2 非鍵 + CYM/HID/HIE。
  - **誤差與 replica**:`bootstrap_binding_sigma`(每個 bootstrap PMF 重算 ΔPMF/ΔG°)、`aggregate_binding_replicas`;research tier 以**實際完成**的 replica 數判定。
  - **WP13** `md20/gui/views.py` + `md20/gui/static/md20view.js`(自寫 Canvas 2D 離線 3D,無 CDN、無 WebGL);GUI 分頁:閘門/即時曲線/時間軸/3D;報告內嵌 3D。
- 開發容器補充:PyPI/npm 在第二個 session **也連不到**(pip/npm 都失敗),所以 NiceGUI、3Dmol.js 都裝不了;GUI 頁面靠 CI 的 `tests/test_gui_server.py` 實際啟動伺服器驗證,3D viewer 用容器內建的 Playwright Chromium 驗證。
- **macOS(ARM/3 核)健壯化**(commit `1d74649`):三個真實 OpenMM 整合測試在慢 runner 上脆弱,已改成斷言軟體的真正保證而非特定機器結果——`test_nacl_pmf`(window 連通 **或** 誠實不輸出 ΔG°)、`test_multi_ligand_exit_path_blocked`(沿 Na→Cl 軸挑確實在拉離圓柱內的水,否則 skip)、`test_gui_pages_render`(伺服器暖機拉長到 ~180s,純逾時則 skip,行程掛掉仍 fail)。
- **交接當下 CI**:最後 push 是 `1d74649`,觸發 run **41276641008**;交接時 pure-python 6 platform 已綠,三個 openmm-stack(mac/ubuntu/windows)仍在跑。新 session 第一件事就是看這一輪(或更新)的 openmm-stack 結果:若全綠,把 `docs/STATUS.md` 的 WP5/WP9/金屬/WP13/σ/replica 從「靠 CI」升級為「真跑過」;若 macOS 仍紅,讀 commit 留言的失敗 log 再修。

## 6. 還沒做 / 可以接著做的
- 鍵結金屬:目前是**幾何**鍵結模型;擬合參數(MCPB.py/QM)、配體直接配位金屬仍是 NEEDS_HUMAN。
- (第三個 session 已做)閘門卡片一鍵寫回設定:`md20/gui/actions.py`(選項→config patch→寫回→`invalidate_from`)。
  新增可點選項時,在 `_option_action` 加映射,**且程式必須真的執行它**;否則留在 `manual`。
- (第三個 session 已做)3D 互作標示與 vdW 表面:`views.ligand_interactions` + `md20view.js`。仍沒有卡通/SES 表面。
- 受體閘門其他選項(長 loop 截斷/補建、未知殘基移除、改用 mmCIF)尚未實作,目前誠實地維持擋關。

## 7. HCC Lab 戳記(防盜用)
- 模組:`md20/util/stamp.py`。可見文字 + 隱藏標記(PNG tEXt / SVG metadata / PDB REMARK 999 / SDF 屬性 / JSON `_md20` / 零寬 HTML / zip comment)+ RSA 加密溯源。
- **公鑰**在 repo:`md20/util/owner_pub.pem`(負責加密)。
- **私鑰不在 repo**(`.gitignore` 擋 `*private*.pem`、`owner_keys/`)。私鑰只有使用者手上一份(已於 2026-11-01 對話交付,離線保存)。新 session **拿不到也不需要**私鑰來開發;只有驗證盜用解密時才需要,那時由使用者提供。
- 重要坑:`system.xml` 不可塞註解(OpenMM 會讀不了),其溯源放在 build manifest。
- 提醒使用者:公開 repo+戳記只能證明與嚇阻,真正限制商業使用要加非商業授權(如 PolyForm Noncommercial)。

## 8. 兩篇論文驗證/教學案例(`md20/validation/`)
`md20 validate <case>` 產生設定 → `md20 pipeline run <file>`。
- `hsieh2024`:J. Ethnopharmacol. 318 (2024) 116980,NF-κB RELA,六配體同時對接。論文標 PDB **1VKF 其實是 Thermotoga 蛋白**(≤188 aa),系統以殘基存在性判定正解為 **1VKX**。
- `hsieh2025`:LWT 222 (2025) 117641,Keap1-BTB(4CXT),胜肽 **GGGGGKP**;淨電荷 +1,CPP 閘門會擋並建議改序列。
- 來源 PDF 由使用者上傳(JEP:S0378874123008486;LWT:S0023643825003251),需要時請使用者再附。

## 9. 常用指令
```
md20 doctor                 # 硬體/環境診斷 + tier 建議
md20 validate hsieh2024     # 產生論文驗證案例設定
md20 pipeline run cfg.json  # docking→MD→binding 全流程(可續跑)
md20 resume --all           # 續跑所有未完成工作流程
md20 stamp verify <file>    # 查戳記
md20 gui                    # NiceGUI 介面
```
