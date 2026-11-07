# MD20 開發交接檔(給新的 Claude Code session 接手用)

> 最後更新:2026-11-03(v0.1.0a3 發行後同步;§5–§6 為 2026-11-01 第三、四個 session 的紀錄)。讀完這份就能無縫接續開發與 CI 監看。
> **重點:所有成果都在這個 repo + GitHub Actions 上,不在任何對話容器裡。** 新 session 只要 clone 本 repo 即可完整接手;正在跑的「虛擬機」就是 GitHub Actions CI,與 session 無關,不會因為舊對話結束而消失。

## 0. 新 session 第一步

> **2026-11-07 第四個 session（session_016gcJz7pQmKkZzkUxg6SqVs）交接。本 session 以 Opus 5.5 開始，中途切換為 Opus 4.8；commit 屬名現在用 `Claude Opus 4.8`。**
>
> **⚠ 第一件事：有 CI 正在 GitHub VM 上跑，別急著 push。**
> - 驗證 commit 是 **`ac5fba5`**（`ac5fba5`，HEAD 是其後的 docs-only commit，不觸發 CI）。它含本週全部未驗證的真實引擎改動（D-102 膜、D-104 建膜 3D、D-105 工具箱、D-106 共同基底、D-107 declash 修正）。
> - 之前每次 push 都把上一輪排隊中的 CI 取代掉，所以 openmm-stack 三 OS／heavy workflow **從沒跑完過**。本 session 已停手讓 `ac5fba5` 跑完。**在確認它跑完之前，只改 `docs/**`（paths-ignore，不觸發 CI），不要 push 任何程式改動。**
> - 查法（單次，不要輪詢）：`gh api "repos/fstcch-cmd/md20-workstation/actions/runs?head_sha=ac5fba5332983223982ef59b3bb31c458444c41f" --jq '.workflow_runs[]|select(.name|startswith("MD20 CI"))|.id'` → `gh api ".../actions/runs/<id>/jobs?per_page=40" --jq '.jobs[]|[(.conclusion//.status),.name]|@tsv'`。
> - 重點看：openmm-stack 三 OS 的膜測試 **water overlaps 閘門 PASS/AUTO_FIXED 且 case B 400 步不 NaN**（D-102）、**live3d 階段 solute→bilayer→declashed**（D-104）、**toolbox 真 mdtraj**（D-105）、**共同基底 3PTB apo+複合物可比**（D-106）；pure-python 六個與 heavy-metal 應已由 D-107 轉綠；heavy workflow、paper-docking。紅的用單次 `gh api .../jobs/<id>/logs` 判斷是程式還是 infra，當場修（同一 commit 附測試與 DECISIONS）。
> - 本 session 已用 send_later 排了一個 `ac5fba5` CI 檢查（約 2026-11-07 11:53 UTC 觸發）；若它在你接手時觸發，照本段做即可，不需重做。更早排的 `f61f305`／`77480b1` 檢查已過時，忽略。
>
> **本 session 做了（全部已 push main；a20，未發行；容器 770 passed）：**
> - **D-103 GUI 穩定性**：計算改獨立子程序 `md20/gui/worker.py`（不 import NiceGUI），狀態／進度／即時曲線從 `<workflow>/_gui_job/` 檔案讀回；GUI 斷線或重開後接回同一計算、不重啟；報告重建移出事件迴圈。**行為改變**：關掉 GUI 不再中斷計算（按「暫停」才停）——需使用者確認是否要改成「關 GUI＝暫停」。規格 `docs/specs/gui_stability.md`。
> - **D-104 建膜即時 3D**：`md20/build/live3d.py` 建模每步寫場景（solute＋目標磷平面、bilayer、declashed），GUI 3D 分頁每 3 秒重讀、新階段自動重畫、除非學生自己選過否則跟著建模走。
> - **D-105 分析工具箱**：`md20/analysis/toolbox.py`——tICA、MSM（資格三級，單一軌跡永不報速率）、側鏈氫鍵網路、水合位點；接 `extended.py` 與報告。**盤點更正**：藍圖列為缺的 PCA/FEL/分群/SASA/DSSP/DCCM 其實 D-58 早有。
> - **D-106 系統比較**：`md20/analysis/common_basis.py`——先查可比性（溫度／系綜／約束／水模型／力場 XML／溶劑／HMR／長度 ×1.25，未知即不可比），再放到同一組 PCA 軸、低谷代表幀、前後半一致性、殘基對應的 ΔRMSF。
> - **D-107**：修 CI 第一次真跑 D-99~D-102 抓到的兩紅——declash 沒 SciPy 時漏查 O–H（加 numpy 後備）、金屬／real-case 測試 padding 0.8 低於截斷（改 1.0，閘門不動）。
> - **D-108 證據覆蓋矩陣**：`md20/report/evidence.py`，報告開頭列 計畫／執行／支持什麼（三級，讀不到不算有證據）。
> - **D-109**：移除無呼叫者 `sampling/runner.py`，`binding_summary` 搬到 `pmf.py`。
> - **D-110**：docking 拒絕理由四語化（理由帶 params，報告依語言渲染）。
>
> **待使用者（接手可問或先做好等審）：**
> 1. **a19 發行**：`e0a0f77`（D-95~D-98）CI 全綠、`docs/releases/v0.1.0a19.md` 已寫好。推 tag 是公開動作、**本 session 權限被擋，需使用者執行**：`git tag -a v0.1.0a19 e0a0f77 -m "MD20 v0.1.0a19" && git push origin v0.1.0a19`。a19 只含 D-95~D-98；D-99~D-110 屬 a20。
> 2. **需授權才能做（屬協定變更或需計算預算，別自行動工）**：A8 漏斗約束 ΔG°／PMF 參考態、P1A 自動補窗迴圈（`adaptive.py` 可接）；藍圖第 2–4 階段——GaMD／well-tempered metadynamics、REST2/H-REMD、RBFE/ABFE（OpenFE）、恆定 pH、QM/MM、ML 勢能。F19 MM/GBSA pilot 也需計算預算授權。
> 3. **F11 口袋體積／水合事件**：需 fpocket／P2Rank（Windows 可行性待查）。
> 4. **使用者的既有需求**：D-72 筆電實測、hsieh2024 URI 的實際 SMD/PMF 數值、D-103 關掉 GUI 主控台後計算是否存活（CI 測不到，需筆電）。
>
> **規矩提醒（CLAUDE.md）**：不新增 phase 只強化；三態閘門；判斷寫 DECISIONS（最上面）＋ specs、與程式同 commit；改動要有測試、真實路徑交 CI；**未經授權不跑正式模擬、不改科學模型、不發版、不推 tag**。使用者 11/07 另交代：**避免使用付費 API**（目前程式只呼叫免費的 GitHub API 查 Vina）、已掃過工作樹與全部 git 歷史無金鑰洩漏（只有公鑰 `owner_pub.pem`）。repo 目前公開（開發期間；關回私人則 CI 計費、release 需登入）。
>
> ---
>

> **2026-11-07 第三個 session（session_016gcJzAV8UjRW4ixPZLxddG）交接。**
>
> **本 session 做了（全部已 push main，HEAD 見 git log；容器測試通過，真實引擎路徑交 CI）：**
> - **D-99／D-100 水盒**：要拉離 SMD 的案例在建模時就依 SMD 規則算水盒大小（修好 GRP 教學案例「水盒太小做不了 SMD」）；通則化——任何含配體案例都事先檢查（`md.box_for_smd`：auto 便宜先加大／貴則 MD 前提醒、always、never）。**更正 padding 意義**：OpenMM 的 padding 是「溶質到自己影像的距離」只加一次，不是「到盒邊」；依使用者決定 **padding 預設全部 2.0 nm**。
> - **D-101 傘狀採樣**：第一批 window 改用 SMD 力曲線規劃（陡處加密加硬）；每個 window 後即時偵測斷點並在進度列／GUI 提示原因（被斜坡推走／能障雙峰／間距／k 上限）；覆蓋圖每個 window 後都輸出（紅斷點、橘警示），報告指名這張圖、空白時說明「SMD 拉離中」。
> - **D-102 膜 NaN 根因修復**：診斷確認是**建構缺陷、平台無關**（Linux 也會 NaN）——OpenMM 溶劑化放出重疊水（O–O 0.178 nm）最小化壓不下、MD 前幾步 NaN。加入缺少的「去水碰撞」步驟（建 System 前，閘門 water overlaps）。
> - **中期開發藍圖**（對標市面軟體）：Claude Doc https://claude.ai/artifact/X7GWyffsMwTL2r9fr3SX6B （四階段：分析工具箱→增強取樣→定量自由能→進階；見 DECISIONS）。
>
> **待使用者／下一個 session：**
> 1. **a19 發行**：`e0a0f77`（D-95–D-98）CI 全綠，發行說明 `docs/releases/v0.1.0a19.md` 已寫好。推 tag 是公開動作、**本 session 權限被擋，需使用者執行**：`git tag -a v0.1.0a19 e0a0f77 -m "MD20 v0.1.0a19" && git push origin v0.1.0a19`（或 Actions → Release Windows 填 tag）。**注意 a19 只含 D-95–D-98；D-99～D-102 是之後的版本（a20），不要混入 a19。**
> 2. **確認 CI**：HEAD（`f61f305`）會觸發新 CI，確認 D-99/100/101/102 的真實引擎路徑（heavy workflow、openmm-stack 三 OS、膜測試 water overlaps 閘門與 NaN 歸零）全綠。膜診斷工作流程 run 42355183065 的 Windows build 與交叉實驗結果也可一併看（佐證 D-102）。
> 3. **新功能需求（使用者 11/07，見 DECISIONS「新功能需求」）**：(a) **GUI 穩定性**——UI 容易斷線，需增強（WebSocket 重連、計算不阻塞 UI、斷線後從檔案回復狀態）；(b) **建膜即時 3D 顯示**。
> 4. 中期藍圖審閱後決定先開發哪一階段。
> 5. repo 11/07 已改回公開（開發期間）；若要關回私人，記得 release 需登入下載、CI 計費。
> 6. 本 session 用 send_later 排了幾個檢查 check-in（膜診斷、CI）；D-102 已解決膜問題，若它們在新 session 觸發，讀本交接即可，不需重做。

> **2026-11-07 第三個 session（session_016gcJzAV8UjRW4ixPZLxddG）接手。** 查到：**a18 從未發行**（GitHub 最新 release 是 a17）；repo 11/07 改為私人（CI 計費、release 需登入）。下一版用 a19。進度見 `docs/WORKBOARD.md`。
>
> **2026-11-07 第二次交接（session_016gcJzASwmZ7ZUPX5BewTyo）。** 已 push 到 main，HEAD **`ba4d7da`**，決策到 **D-97**，**未發行**。本 session 做了整合規格（`MD20_Claude_Code_Master_Iteration_Prompt_EN.md`）的 P0 兩批：
>
> **接手第一件事：確認 `ba4d7da` 的 CI（run `42330665732`）。**
> - `gh api "repos/fstcch-cmd/md20-workstation/actions/runs/42330665732/jobs?per_page=60" --jq '.jobs[]|[.name,.status,(.conclusion//"-")]|@tsv'`
> - 期待：pure-python 六個綠（前一輪 `2979908` 因 `from tests.` import bug 全紅，已於 `ba4d7da` 修正）；openmm-stack 三 OS 的真實 mdtraj 路徑（新 fingerprint／ligand_state／動態接觸／persistence／`run_binding` assessment）。**D-95 的安裝步驟已在 `2979908` 確認成功**（「Install md20」step success），不必再擔心 openmmforcefields 撤回。
> - 若 openmm-stack 紅，先用單次 `gh api .../jobs/<id>/logs` 看是真實數值問題還是環境問題，別跑輪詢。
>
> **待使用者授權（下次開機可問）：** ① a18 安裝程式重新發行（install.ps1/sh 已含 D-95 釘選，但已上架的 a18 zip 是舊的，學生新安裝才會成功）；② 下一批要先做哪個（A7/A8/A11、P1A 自動行動迴圈、或 F19 MM/GBSA pilot——F19 需計算預算授權）。
>
> **本 session 做的（P0 兩批）：**
> - **D-95**：發現 `5561dd7` CI 紅燈真正原因是 **openmmforcefields 0.15.1 在 PyPI 被上游撤回**（唯一版本，理由「Missing deps」），不是前次判斷的 infra flake。CI 三處＋安裝程式兩處改成 `==0.15.1`。**a18 安裝程式新安裝也會壞**，修好需重新發行。
> - **D-96**：A1/A2（執行狀態／科學評估／比較資格分開，`sampling/assessment.py`）、A9（replica 起點語意）、A3（結構限制不算修正）、A10（決策依流程分開、摘要不截斷）。
> - **D-97**：A5（互作化學統一，`analysis/interactions.py`）、A6（完整動態接觸）、A4（配體狀態不靠單一 RMSD）、F09/A12（互作持續性與節奏契約，`analysis/persistence.py`）、F07（初始 vs 新接觸）。
>
> **接手第一件事：** ① 若使用者已授權 push，先 push 讓 CI 驗證 D-95（釘選）與 D-96/97 的真實引擎路徑（openmm-stack heavy workflow）；② 讀 `docs/specs/master_iteration_2026-11-07.md`（A1–A12 複核表、F01–F19 盤點、§5 後續精確清單）。
>
> **下一批（未做）：** A7（docking fallback reason code）、A8（PMF 參考態／漏斗約束）、A11（跨系統 PCA 共同基底）；F10/F11/F12、F01/F05 證據矩陣；P1A 自動行動迴圈；F19 MM/GBSA pilot（先決條件見 §5，需使用者授權預算）；配體原子形式電荷寫入 build manifest（讓鹽橋能出現在配體上，需 RDKit）。
>
> **未經使用者授權：不 push、不發版、不跑正式模擬、不改科學模型。**
>
> ---
> **2026-11-07 第一次交接（session_016gcJz9hwPAMieHsNEctkzL 關閉前）。** 目前版本 **v0.1.0a18**，決策到 **D-94**。本週（11/04–11/07）這個 session 做的，全部已 push 到 `main`（HEAD `5561dd7`）：
> - **D-91** zip 內直接執行安裝程式→提示先解壓縮（a16）。
> - **D-92** 多配體拉離路徑被擋→自動改道＋可按的「略過這個配體」（a17）。
> - **D-93** 路徑判定修正（貼著的鄰居不再算擋路，修好筆電 hsieh2024 URI 改道失敗）、「只做 MD」真的清掉 `binding.added`、閘門加「只算單獨結合（`binding.alone`）」與「指定 anchor 殘基（`binding.anchor_residues`）」、`reconnect_timeout` 180 秒（a18）。
> - **D-94** GUI「3D 檢視」分頁空白：NiceGUI 3 的 `ui.html` 會以 DOMPurify 清掉 iframe，改用 `ui.element("iframe")`；gui-preview e2e 加 3D 分頁檢查。報告內嵌的 3D 一直正常。
>
> **接手第一件事：確認 `5561dd7` 重跑後的 CI。** 第一輪（run 42322469948）大量紅燈是 infra flake（PyPI 連不到裝不了 `openmmforcefields`→`md20` 沒裝成；一台 runner 磁碟只剩 15.7 GB），**不是** D-94 的問題，gui-preview 綠。已於 11/07 09:34 重跑失敗 job。查法：`gh api "repos/fstcch-cmd/md20-workstation/actions/runs?head_sha=5561dd7..." --jq ...`（見 §0 下方指令）。
>
> **待筆電確認（使用者下次開機可驗）：** ① hsieh2024_rela_1vkx 裝 a18 後，URI 這個被擋的目標按「開始或繼續」是否直接算（D-93 原方向已淨空），或四個選項是否都能按；② SMD／PMF 實際跑出來的數值；③ 3D 分頁在筆電 NiceGUI 上是否真的畫出來（容器內 Chromium 已驗 e2e）；④ 「連線丟失」是否因 reconnect_timeout 消失。
>
> **使用者的開發主線（11/07 提到、但當下擱置）：** 一份「MD20_Claude_Code_Master_Iteration_Prompt_EN.md」整合規格（涵蓋 A1–A12 問題複核、F01–F19 功能盤點、互作完整偵測、時間取樣完整性、provenance、claim eligibility、opt-in MM/GBSA pilot、6.4/6.5/10/11 節）。**使用者 11/07 說「GPT 這件事情先不用」，所以先不要主動去找那份檔案或照它動工**；等使用者正式提供檔案再接。Project 文件 04 的里程碑 M5 已列 MM/GBSA，可先讀。
>
> ---
> **2026-11-02 之後：先讀 `docs/archive/HANDOFF_2026-11-02.md`**（交接當時的現況與開場指令）；之後的現況以 `docs/STATUS.md` 開頭的「目前版本」、`docs/WORKBOARD.md` 與 `docs/DECISIONS.md`（最新在最上面，目前到 D-94）為準。本檔其餘章節仍是一般說明。

1. 把 repo 加進 session 並 clone:`fstcch-cmd/md20-workstation`(需要 push 權限)。
2. 讀這幾份:`docs/STATUS.md`(誠實三級現況)、本檔、`MD20_optimization_brief` 的規則(見 §4)、`docs/WORKFLOW.md`、`docs/TEACHING.md`。
3. 看 CI 現況:`gh run list -R fstcch-cmd/md20-workstation -L 3`。**先確認最新一輪 openmm-stack 三個 OS 的結果**(Windows OpenCL 是使用者主力平台,必須綠)。
   - 單次指令:`gh run view <run_id> --json status,conclusion,jobs -q '"\(.status) \(.conclusion)", (.jobs[]|"\(.conclusion // .status) \(.name)")'`
   - 失敗細節 / 論文重現 JSON 在該 commit 留言:`gh api repos/fstcch-cmd/md20-workstation/commits/<sha>/comments --jq '.[].body'`
4. 教材（非 repo 內）：v0.1.0a3 的「安裝與使用說明（Windows／macOS）」在 https://claude.ai/artifact/GPVgPN9TzaduFesmUovFoJ （十節）；較早的教學手冊 https://claude.ai/artifact/VL3P7wgbQBrPj4Ypd11pCG （九節，兩篇論文主線）。repo 內給學生的簡易步驟：`docs/students/WINDOWS.md`、`docs/students/MAC.md`。

## 1. repo 與帳號
- GitHub:`fstcch-cmd/md20-workstation`,分支 `main`,暫時公開僅供 CI(README 已聲明保留權利)。
- 擁有者:HCC Lab, NKUST(Chen-Che Hsieh)。
- Commit 屬名(每次 commit 結尾加):
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
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
  - `pure-python`:3 OS × Py3.11/3.12,忽略重測檔;**這是必綠的門檻**。
  - `installer-windows`、`installer-macos`:以 `git archive`(等同發行 ZIP)實際安裝 → doctor／demo／pipeline example。
  - `openmm-stack`:3 OS 真實 OpenMM+Vina 用 micromamba 建環境,跑同一套測試(約 20–30 分)。
  - `heavy`(Ubuntu,平行 3 個 job:workflow / pose-screen / metal,`MD20_HEAVY=1`):每組各自逾時、各自貼留言「CI heavy (<組>)」(D-19)。
  - `paper-docking`:兩篇論文的對接重現(數小時 Vina),獨立、`continue-on-error`,不阻擋;結果 JSON 貼留言。
- main **不取消進行中的 run**(只有排隊中的 run 會被更新的 commit 取代;PR 才 cancel-in-progress)。舊紀錄裡的 `cancelled` 多半是改設定前被新 push 取消,不是失敗。完整一輪約 60–90 分鐘。
- 只改 `docs/` 的 commit 不觸發 CI。
- 發行:Actions →「Release (Windows and macOS installers)」→ Run workflow(tag `v0.1.0aN`),或 `gh workflow run release-windows.yml --ref main -f tag=v0.1.0aN`;先在乾淨 Windows 與 macOS runner 實裝驗證才建立 Release。
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
- **第三個 session 看到的 CI(63d363b)**:Windows OpenCL 124 passed、macOS 126 passed,各僅 `test_gui_pages_render` 失敗(NiceGUI 在子行程讀到 `PYTEST_CURRENT_TEST` 就要求 `NICEGUI_SCREEN_TEST_PORT`);已在 `tests/test_gui_server.py` 把 `PYTEST_*` 從子行程環境移除。新 session 請看最新 commit 的 openmm-stack 三 OS 結果,全綠後把 STATUS 中「見 B」的項目升級。

## 5b. 第四個 session(2026-11-01):全面審查 + 高通量篩選
- **先讀 `docs/archive/REVIEW_2026-11-01.md`**:20 項發現,✅ 已修 14、❌/📝 未修 6(配體配位金屬閘門、pose 對應後備、`sampling/runner.py`、補窗門檻、供應鏈 pin、戳記簽章)。
- **HTS 篩選**(`docs/specs/hts_screen.md`):`md20/docking/library.py`(Excel/CSV → PubChem/ChEMBL/RCSB 3D 下載、去鹽、尺寸過濾、去重)、
  `md20/docking/screen.py`(批次縮減搜尋對接、排名、圖、ECharts)、workflow 步驟 `screen_library → screen_docking → screen_selection`
  在 `docking_preflight` 之前;GUI「篩選」分頁勾選 → `actions.select_screen_ligands` 寫 `screen.select/next_mode`。
  設定範本:`md20 pipeline example --screen`;庫檔範本:`md20 screen template`。
- **CLI 重跑規則**:`pipeline run` 現在會把 workflow 自己的 config.json 裡的人工決定(`DECISION_KEYS`)併回學生的原始檔;新增決定鍵時記得加進 `workflow.DECISION_KEYS`。
- **CI**:main 不再 cancel-in-progress(PR 才會);summary 留言印 skip 數與原因——**SKIPPED 的整合測試不算通過**。

## 6. 還沒做 / 可以接著做的
- **規格與構想全集在 `docs/specs/`**(README 為索引,每份標明 已驗證／待 CI／設計中,並列出想請審查者回答的問題)。使用者會用更強的模型審查後回饋。
- (第三個 session)傘狀採樣智慧補窗 `md20/sampling/adaptive.py` + 即時覆蓋圖 + 手動補採樣:已實作、純測試通過、待 CI。
- (第三個 session)約束分組分階段／凍結／口袋截斷／資源估算:**設計中**(`docs/specs/restraints_freeze_truncation.md`);
  引擎掛鉤 `StageSpec.restraint_groups`、`StageSpec.freeze` 已加但尚無流程使用。
- (第三個 session 已做)金屬擬合參數 `md20/build/metal_params.py`:`metal_params: {"ZN:A262": {"source": "hessian"|"mcpb"|"json", ...}}`。
  原理:仿 MCPB.py——小模型 QM Hessian 給鍵/角力常數、RESP 給電荷、其餘沿用力場;但不依賴 AmberTools:
  Hessian 以 Wilson B 矩陣 pseudo-inverse 轉成位點內座標力常數(比 Seminario 精確,測試對已知模型完全還原),
  MCPB.py 的 frcmod/mol2 只做轉譯。幾何模型建模時會自動在 `build/metal_qm/<site>/` 產生 ORCA/Gaussian 小模型輸入與 README。
  配體直接配位金屬仍 NEEDS_HUMAN(需要配體–金屬的 QM 模型,第一版不做)。
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
- `hsieh2025`:LWT 222 (2025) 117641,Keap1-BTB(4CXT),胜肽 **GGGGGKP**;淨電荷 +1,CPP 科學限制**只提醒、不擋流程**(D-48),並建議替代序列。
- `hsieh2024` 課堂／教學等級對接用 exhaustiveness 8,research 用論文的 32(D-71)。
- 來源 PDF 由使用者上傳(JEP:S0378874123008486;LWT:S0023643825003251),需要時請使用者再附。

## 9. 常用指令
```
md20 doctor                 # 硬體/環境診斷 + tier 建議
md20 validate hsieh2024     # 產生論文驗證案例設定
md20 pipeline run cfg.json  # docking→MD→binding 全流程(可續跑)
md20 resume                 # 續跑所有未完成工作流程(--list 只列出)
md20 --mode background ...  # 資源模式 background／balanced／full(D-68)
md20 stamp verify <file>    # 查戳記
md20 gui                    # NiceGUI 介面
```
