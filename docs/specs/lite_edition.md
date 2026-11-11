# Spec: MD20 Lite（導流版）（D-181）

狀態：**[開發中]** 核心契約 `md20/edition.py` 已實作並有測試（`tests/test_edition.py`）。報告（第 7 節）已實作並有測試（`tests/test_edition_report.py`）。打包剝除、流程掛點、GUI 分頭實作中，
各節標示實際狀態。真實引擎驗證依 D-180 在使用者本機做（目標機：GTX 1060 4 GB 筆電）。

## 1. 目的與原則（使用者 2026-11-11 指定）
Lite 是交付給實驗室以外的人用的版本。它存在的理由是**把使用者帶到完整版**：用過 Lite 的人會想接著用完整版。

1. **流程完整，規模受限**。docking、分子動力學、快速 PMF、報告全部走得完，讓人完整體驗一次。限制的是系統大小、配體數、模擬長度、重複次數。
2. **Lite 的結果在它的範圍內是對的**。不故意弄壞、藏起或模糊結果來逼人升級。重複不足時照既有規則標成描述性結果、不排名（D-96），這是誠實，不是手段。
3. **升級不用重做**。Lite 專案的格式與完整版完全相同，完整版直接打開、從上一個 chunk 接著跑。
4. **完整版的程式碼不交出去**。Lite 安裝包裡沒有完整版功能的原始碼，不是鎖起來，是不存在。
5. **通則**。所有上限與功能歸屬只寫在 `md20/edition.py`，其他地方不准寫死 `if lite`。

## 2. 使用者的五個決定
| # | 問題 | 決定 |
|---|---|---|
| 1 | 程式碼形式 | 同一份源碼，打包 Lite 時把完整版模組實際移除 |
| 2 | 限制方式 | 限規模，流程完整 |
| 3 | 升級提示 | 報告內附對照，加上碰到上限時提示 |
| 4 | 取得方式 | 免費，但需擁有者簽發的授權檔 |
| 5 | 隱式溶劑快速預覽 | 提供，報告加註限制 |

## 3. 規模上限（`edition.LIMITS["lite"]`，可集中調整）
| 項目 | Lite | 完整版 | 檢查時機 |
|---|---|---|---|
| 每個系統的原子數（顯式水） | 30,000 | 不限 | 建模後 `check_system` |
| 每個系統的原子數（GBn2） | 6,000 | 不限 | 建模後 |
| 蛋白殘基數 | 400 | 不限 | 建模後 |
| 同一流程的配體數 | 2 | 不限 | 入口 `check_config` |
| 一次篩選的化合物數 | 10 | 不限 | 讀完化合物庫後 `check_library` |
| 正式模擬長度 | 10 ns | 不限（微秒級） | 入口 |
| `md.tier` | classroom、teaching | 全部 | 入口 |
| 每個系統的獨立重複 | 1 | 依分析需要自動決定 | 入口 |
| 每個配體的獨立拉離 | 1 | 不限 | 入口 |
| 傘狀採樣窗口 | 12 個，每個 500 ps，不自動補窗 | 自動補到重疊足夠 | 入口 |

數字的理由：3 萬原子涵蓋一般單一結構域蛋白加配體加最小水盒（3PTB 在 0.8 nm 邊距約 1.5 萬原子），學生筆電跑得完。
多配體同時對接與篩選是擁有者最常用、也最有價值的功能，所以開放小規模讓人試到，大規模留給完整版。
數字是開發者先訂的預設，**未經實測校準**，筆電驗證後可能調整（另記決策）。

## 4. 只有完整版才有的功能（`edition.PRO_FEATURES`）
膜系統、胜肽序列摺疊、粗粒化、微秒級長時間模擬、獨立重複與不確定度、完整結合自由能（自動補窗、多次拉離、ΔG° 誤差）、
大型化合物庫篩選、三個以上配體、進階分析工具箱（tICA、MSM、氫鍵網路、水合、共同主成分）、自動檢查與補跑、大型系統。

每個功能在登錄表有四語標題、一句「完整版會多給你什麼」、以及要從 Lite 安裝包移除的原始檔清單。
介面的鎖定標示、報告的對照、碰到上限的說明都從這張表產生，所以 Lite 沒有那些程式碼也能說明完整版有什麼。

## 5. 版本怎麼決定
1. **安裝包**。`tools/build_lite.py` 在 Lite 安裝包寫入 `md20/_edition.json` 並移除完整版模組。有這個標記的安裝包就是 Lite，裝什麼授權都一樣，因為程式碼不在裡面。標記壞掉或被改也算 Lite（標記只存在於 Lite 安裝包）。
2. **授權**。有效授權的 `features` 含 `lite` 這個字時，完整安裝包也照 Lite 的上限執行。

沒有任何環境變數、設定或參數可以改版本（測試檢查原始碼）。

### 為什麼 Lite 授權用 `features` 而不是新的 `tier`
原本想在 `license.TIERS` 加 `lite`。實作時發現 `tests/test_license_vector_v2.py` 要求每個等級在簽發端的測試向量裡都有一份，
而向量是私人 repo `md-digital-signature` 的逐位元組副本、測試私鑰已丟棄。加等級等於要改授權格式與兩個 repo。**否決**。

改用既有欄位：格式 v2 的 `features` 本來就是字串清單，驗證端保留不認得的字，功能閘門只問四個真功能。
所以 Lite 授權簽成 `features: ["lite", "binding", "hts"]` 即可：
- 授權格式、驗證端、已發行的版本都不用改。
- `membrane` 與 `cg` 不在清單裡，既有的功能閘門（D-128）本來就會擋，雙重保險。
- 舊版 MD20 讀到這份授權只會當成「有 binding 和 hts」，不會出錯。

**待確認（簽發端，私人 repo）**：`md20sign` 是否接受 `features` 裡有 `lite`。若簽發端有白名單，需要加一個字。本 session 沒有該 repo 的存取權。

## 6. 檢查與提示
- **入口**：`check_config(cfg)` 只看設定檔，與 `required_features` 同一個位置（`Workflow.run`、`pipeline run`、`resume`、GUI 啟動）。不動任何科學邏輯。
- **建模後**：`check_system(n_atoms, n_protein_residues, solvent)`。
- **讀完化合物庫後**：`check_library(n)`。
- 每個超出項是一個 `Hit`：代碼、種類（規模或功能）、要求值、上限、對應的完整版功能、能不能自動縮小、四語說明。

碰到上限時走既有的三態閘門，NEEDS_HUMAN，三個選項：
1. **自動縮小設定後繼續**（`clamp_config`）。只縮規模：等級、長度、重複、窗口。每一項改動寫進 DecisionLog。
2. **匯出專案給完整版接著跑**。
3. **了解完整版**。

`clamp_config` 不會替使用者拿掉功能或刪配體。要留哪兩個配體、要不要放棄膜系統，是使用者的決定（寧可擋也不要猜）。
同一個上限在同一個專案只提示一次。啟動時不跳廣告。

### 6.1 流程與命令列（FLOW，已實作，`tests/test_edition_workflow.py`）
流程、命令列與 GUI 只問 `md20/edition.py`，不自己判斷版本。所有停下來都走既有的三態閘門：步驟 `edition`（`edition.STEP`）設為 NEEDS_HUMAN，
閘門名稱 `edition limit`（`edition.GATE_NAME`），命中項存在 `state["edition"]`。完整版沒有任何命中，所以沒有 `state["edition"]`、沒有閘門，設定檔與輸出不變。

| 時機 | 位置 | 做什麼 |
|---|---|---|
| 入口 | `Workflow.run`，授權與 `required_features` 檢查之後、拿到鎖之後 | `check_config`。無命中就放行。 |
| 建模後 | `build_cases`，每個案例（含先前已建好的案例） | 用 build 的真實原子數與蛋白殘基數呼叫 `check_system`。 |
| 讀完化合物庫 | `run_screen_library`，`read_library` 之後、任何 3D 下載之前 | `check_library(讀到的列數)`。 |
| 篩選挑選後 | `apply_screen`，`screen_selection` 合併之後 | 明列配體加上挑選的化合物超過上限就停下，不刪任何配體。 |
| 安全網 | `Workflow.run` | 漏出來的 `UpgradeRequired`（Lite 安裝包裡完整版模組是空殼）變成同一個閘門，不給 traceback。 |

放在拿到鎖之後，是因為停下來要寫 state；授權檢查只丟例外，所以仍在它前面。

**入口的處理**
1. 命中且 `edition.accept_clamp` 為真：呼叫 `clamp_config`，把縮小後的值寫進工作流程自己的 `config.json` 與記憶體中的設定，
   每項改動寫一筆 DecisionLog（`edition.clamp`，`kind: auto_fixed`，中文 `why`），並存進 `state["edition"]["clamped"]`。
   縮小後還有命中（功能、配體數）就停下，閘門只列剩下的項目，因此不會出現一個按了沒用的「自動縮小」選項。
2. 命中但沒有 `accept_clamp`：停下，閘門第一個選項是自動縮小。`edition.accept_clamp` 在 `DECISION_KEYS`，所以 `pipeline run` 用原始檔重跑時會沿用。
3. 同一項縮小（鍵、原值、新值相同）只記一次 DecisionLog，所以用原始檔重跑不會重複記錄。

**`md.replicas` 沒寫的情況**：預設是 3（D-131），高於 Lite 的 1。`edition.check_config` 只看設定檔有寫的數字，所以流程在 `_edition_hits` 補上這一項
（沒有重複上限的版本不會多出任何命中），縮小時把 `md.replicas` 明確寫成 1。建議之後把這一項移到 `edition.check_config`，流程端的補丁會自動失效（以代碼去重）。

**建模後的案例**：超過上限的案例在 `md_cases` 標成 NEEDS_HUMAN（`blocking: edition`），下一次執行會重新建模並重新檢查，不會被當成已建好而跳過。
舊的 build manifest 沒有 `n_protein_residues` 時，從 `topology.pdb` 的前 `n_protein_atoms` 個原子數蛋白殘基。build 現在記錄
`BuildResult.n_protein_residues`（只數序列殘基，不含 ACE、NME、金屬、水與配體），不動任何科學。

**化合物庫算列數**：用 `read_library` 讀到的列數（空白列已略過），在篩選條件與下載之前。篩選條件可以把化合物濾到上限以下，
若算濾完的數目，就能用條件規避上限，也要先下載才知道。先前讀過的庫（步驟已完成）每次執行也會再判斷一次。

**`state["edition"]` 的形狀**（`edition.state_record`）：`{"edition": "lite", "hits": [...], "clamped": [...], "at": "..."}`。
`hits` 每個代碼一筆（取最新值），含 `code, kind, value, limit, feature, can_clamp, text{zh,en,ja,ko}`；`clamped` 是已套用的縮小
（`key, from, to, code`）。各階段都合併進同一筆：入口只有設定檔命中；縮小後多了 `clamped`；建模後多了 `system.*`；讀庫後多了 `screen.compounds`。
使用者自己改好設定而不是接受縮小時，命中仍留在紀錄裡（它們真的發生過），`clamped` 為空；被擋住的 `edition` 步驟則會移除。

**縮小後不走的路徑**：自動補窗口（`max_refine_rounds` 為 0，`range(first, base_round + 0)` 不執行）、第二次重複（`md.replicas` 為 1）、
長時間規劃（`_plan_long_run` 在有正式模擬上限的版本直接返回，超過上限或有 `md.long_run` 時丟 `UpgradeRequired`，由安全網接住）、
自主補跑（`autonomy` 是不可縮小的功能命中）。GUI 的「加做第二次拉離」「手動補窗口」「重複數設成大於 1」「篩選挑選超過配體上限」在動手前就以
`EditionLimit`（`ValueError` 的子類別，帶四語 `texts`）拒絕。

**命令列**
- `pipeline run` 與 `resume` 把版本上限當成一般的 NEEDS_HUMAN：印 `[NEEDS_HUMAN] …`，結束碼 **3**（既有的慣例，`run`、`pipeline run`、`resume` 相同），
  並印出選項與 `edition.accept_clamp` 的寫法，不再印 `pose_choices` 的提示。沒有新增旗標：既有的閘門決定都是設定檔鍵，沒有對應的旗標。
- `md20 edition` 印版本名、上限對照表，Lite 還印只有完整版才有的功能與升級方式；`md20 edition --json` 印 `edition.summary()`。不能改版本。
- 其他命令在 Lite 安裝包裡碰到完整版模組（空殼丟 `UpgradeRequired`）以結束碼 **14** 離開，stderr 印四語說明。`md20 autonomy` 在 Lite 安裝包保留命令名稱並回這段說明；
  Lite 授權裝在完整安裝包時，也以同樣方式擋掉（`edition.is_lite()`）。
- 結束碼總表：0 完成或暫停；3 需要人決定（含版本上限）；13 沒有授權或授權不含功能；14 Lite 呼叫了完整版功能；其餘各命令自己的碼不變。

**GUI**：`gui/actions.py` 把「自動縮小設定後繼續」註冊成一鍵，補丁是 `edition.accept_clamp: true`，只移除 `edition` 這一個停下的步驟，不讓已完成的步驟重跑。
`gui/gate_text.py` 有四語標題與說明，選項文字直接取自 `edition.OPT_*`。

**快速預覽**：`md20/edition_preview.py::quick_preview_available(result)` 接受平台結果或 Doctor 結果，只有 CUDA、HIP、Metal，
或裝置不是 CPU 的 OpenCL 才回 True；CPU、Reference、裝置不明的 OpenCL 都回 False。它不改任何閘門：GBn2 下的結合自由能與金屬位點照舊被擋。

## 7. 報告
- 頁尾標示 MD20 Lite。
- 「完整版會多給你什麼」一節**依這次結果實際缺的條件產生**，資料來自 D-96 的評估物件與本次的 Hit，不是固定文案。
  例如只跑了一次重複，就寫完整版會安排三次以上並附上差異；PMF 重疊不足，就寫完整版會自動補窗口。沒有缺的項目就不寫。
- 附 Lite 與完整版的對照表（`comparison_rows`）。
- 文字守 `writing_style.md`，四種語言。
## 7. 報告（已實作，`md20/report/edition_section.py`，測試 `tests/test_edition_report.py`）
報告是 Lite 使用者決定要不要升級的地方，所以必須誠實：只寫**這次執行缺了什麼**，以及完整版**針對那一項**會多給什麼。資料來自這次執行自己的紀錄，沒有固定文案。
- **位置**：附錄 D「這次執行與完整版的差別」，放在報告最後，附錄 C（設定檔）之後、頁尾戳記之前。理由：這樣既有的章節編號、附錄字母與表號都不動（Lite 只多一個表號 20 之類的最後一張表），
  完整版的頁面也不會有任何差異。頁尾另有一行「由 MD20 Lite 產生」（`footer_mark`）。單次執行報告（`report/html.py`）只加這一行頁尾標示。
- **何時出現**：該次執行的版本是 Lite。版本取 `state["edition"]["edition"]`，沒有才問 `edition.current()`。完整版不呼叫這個模組，頁面與今天逐字相同（測試比對兩個版本的頁面，只差附錄與頁尾標示）。
- **項目的形狀**：`gains(state, cfg, assessments, lang)` 回傳 `[{"feature": PRO_FEATURES id, "kind": "limit"|"note", "observed": 一句帶真實數字的話, "gain": 登錄表那一句, "evidence": {...}}]`。
  同一功能的項目在頁面上共用一句 `gain`。沒有觀察到的就沒有項目；整份清單是空的時候只寫一句「這次執行沒有碰到 Lite 的任何限制」。
- **資料來源與對應**：
  | 來源 | 讀什麼 | 項目（對應功能） |
  |---|---|---|
  | a 碰到的上限 | `state["edition"]["hits"]`、`["clamped"]` | 正式模擬從 100 ns 縮短為 10 ns（`long_run`）；重複 3 減為 1（`replicas`）；窗口、拉離、補窗口的縮小（`binding_full`）；配體數、化合物數、原子數、功能（各自對應的功能） |
  | b MD 重複 | `replica_section.replica_counts`、重複集合的 `single_replica` 旗標 | 幾個系統只有一次 MD 重複，結果只能描述（`replicas`） |
  | c 結合評估 | 儲存的 `assessment` 與 `claim_status`、拉離次數、`dG_withheld`、`compare_binding` 的 `INSUFFICIENT` | 重疊低於門檻（圖未連通、MBAR 矩陣、相鄰最小值與 0.03）；必要檢查無紀錄；只拉離 1 次；ΔG° 沒有輸出；合格的配體太少無法比較（都是 `binding_full`） |
  | d 隱式溶劑 | `md.solvent == "gbn2"` | 說明，不是升級項目 |
  | e 分析工具箱 | 分析步驟寫出的 `extended_file` 與共同基底檔 | 缺 tICA 與 MSM、氫鍵網路、水合、共同主成分時列一次（`analysis_toolbox`）；完全沒有 MD 分析時不寫 |
- **刻意不寫的**（完整版會得到同樣的結果，寫了就是誤導）：
  1. 比較被標成 `DESCRIPTIVE`。共同口袋的拉離在兩個版本都只描述不排名（D-96 的設計）。**這裡與開發任務書的初稿不同**，任務書把它對應到 `binding_full` 或 `replicas`，實作時判斷這會承諾完整版做不到的事。
  2. D-96 之前的舊結果因為沒有儲存評估而全部「無紀錄」的診斷。那是等重新分析，不是 Lite 的限制。只有 `assessment_source == "stored"` 才列「必要檢查無紀錄」。
  3. 隱式溶劑下被閘門擋掉的 ΔG°。那是 GBn2 的閘門（第 8 節），Lite 與完整版相同。
- 附 Lite 與完整版的對照表（`comparison_rows`）與升級說明（`HOW_TO_UPGRADE`）。對照表在沒有項目時也保留。
- 文字守 `writing_style.md`，四種語言；用語規則見 `report_language.md` 的「Lite 附錄」。
- `tools/report_template.py --lite` 用同一份合成資料產生 Lite 版範本（`MD20_report_template_lite_{en,zh}.html`），預設輸出不變。
- 未驗證：日文與韓文尚未經母語者校對（同 `writing_style.md` §7）；附錄對真實引擎產生的 `assessment` 只用合成資料測過。

## 7b. 介面（GUI）
狀態：**[已實作，純邏輯測試通過；NiceGUI 頁面尚未在真實瀏覽器看過]**。程式：`md20/gui/edition_ui.py`（純邏輯，不依賴 NiceGUI），接線在 `app.py`、`pages_v2.py`、`advanced.py`。測試：`tests/test_gui_edition.py`；
瀏覽器自查：`python tools/gui_preview.py lite OUT_DIR`（CI 用，本機容器沒有 NiceGUI）。

三件事要成立，而且不能吵：使用者隨時知道這是 Lite；看得到完整版有什麼；設定超出 Lite 的那一刻就知道，並有路可走。啟動時沒有廣告、沒有彈窗、沒有倒數。完整版的介面與今天完全一樣：沒有徽章、沒有鎖、沒有新頁面（`edition_ui` 每個函式在完整版都回傳空值，接線處只在 Lite 加元素）。

| 要件 | 做法 | 位置 |
|---|---|---|
| 一直知道是 Lite | 頁首標題旁一個小徽章「Lite」，點了進版本比較頁 | `app._header` |
| 看得到完整版有什麼 | `/edition` 版本比較頁：`comparison_rows` 表、只有完整版才有的功能與一句話好處、`HOW_TO_UPGRADE`（不放價格與連結）。`preview=True` 的功能（膜系統、胜肽序列摺疊）另有說明頁 `/edition/{id}`：它做什麼（二到四句）、你要提供什麼、你會得到什麼、要知道的限制、取得完整版的一句話。範例圖留了具名的位置（`md20/gui/static/edition/<id>.png`），檔案存在才顯示，沒有就什麼也不畫，不捏造結果圖或數字 | `pages_v2.editions`、`edition_feature` |
| 專業版裡的入口 | 「膜系統」「胜肽摺疊」兩個群組標題下掛小標籤「完整版」，群組內第一行是說明頁連結；選了就在合理性檢查面板出現一則警告（不是錯誤，不擋「建立並開始」，因為開始後的限制卡片才有出路） | `pages_v2.build_advanced`、`edition_ui.advanced_issues` |
| 欄位旁的限制 | 有 Lite 上限的欄位（正式模擬長度、模擬等級、獨立重複、配體數、篩選庫筆數、窗口取樣時間、結合自由能開關底下的窗口數與補窗口）在欄位下方有一行淡色說明；值超過時改成琥珀色加 ◆，內容是 `Hit.text`（措辭只存在 `edition.py`） | `edition_ui.field_limits`、`validate_setting` |
| 起始值 | 建議值超過上限時（建議的重複是 3，研究目標是研究等級），欄位從 Lite 上限開始，旁邊寫「Lite 上限，建議值 3」。使用者看得到、改得回去，所以預設流程不會每次都被限制卡片攔下。限縮的值由 `edition.clamp_config` 算，不在介面裡另訂 | `edition_ui.lite_value` |
| 超出時的限制卡片 | 按開始時 `config_hits(cfg)` 不是空的，就**不啟動**，在流程頁上方顯示限制卡片：每一項的說明，以及「可以自動縮小」（◐ 藍）或「需要你決定」（◆ 琥珀）。選項：自動縮小設定後繼續（寫 `edition.accept_clamp: true` 再啟動，縮小由流程執行並記錄）、修改設定（回到表單）、用完整版打開（說明專案資料夾原樣打開並顯示資料夾路徑與複製鈕）、完整版有什麼（連到 `/edition`） | `app._start`、`_edition_card_fill` |
| 快速預覽（隱式溶劑） | 只在 Lite 的快速模式、且偵測到可用的 GPU 平台時才顯示一個開關，說明寫明只看結構與動態、結果只作描述、結合自由能需要顯式水。開關只改 `md.solvent`；既有檢查在隱式溶劑加結合時報錯，不另處理 | `edition_ui.gbn2_preview_offer`、`pages_v2.render_gbn2` |

### 決定與理由
1. **開始的檢查放在 `_start`**。所有開始的入口（表單建立、教學頁、流程頁、確認進入 MD、結合自由能面板）都經過它，所以一處就夠；卡片顯示在流程頁，表單建立後本來就會導向那裡（與授權卡片、功能卡片同一個做法）。被擋下的流程已經建立、尚未開始，「修改設定」回到表單重建，舊的留在最近的流程列表，狀態是「尚未開始」。
2. **自動縮小只在能一次解決時提供**。若還有數量、功能類的項目（配體數、膜系統）是縮小解決不了的，卡片只給修改設定與用完整版打開，並說明為什麼。理由：提供一個按了還是會再被攔一次的按鈕是誤導。`edition.gate` 的選項表仍照 `can_clamp` 提供縮小，兩者的差別留給整合時統一。
3. **表單沒有欄位的結合自由能設定**（窗口數上限、自動補窗口輪數）：Lite 建立流程時，若結合自由能開著，表單把 Lite 上限寫進 `binding.config`，並記一則 `gui.edition` 的決策紀錄。欄位旁已說明。理由：這兩項沒有欄位可改，不寫的話每個開著結合的 Lite 流程都會被攔下，而「修改設定」又無從改起。這是 Lite 的上限寫進設定檔，完整版打開同一專案時會照這個設定執行（與自動縮小一樣），要用完整版的自動補窗口須把 `config.json` 的 `binding.config.max_windows` 與 `max_refine_rounds` 改回去（完整版的介面沒有這兩個欄位）。
4. **說明頁與限制卡片只用 `edition` 的資料與措辭**，介面檔不寫任何上限數字（測試檢查原始碼沒有這些數字，也沒有 `if lite`）。
5. **穩定性（D-103）**：卡片、徽章、說明頁都是伺服器端依狀態畫出的元素，不碰計算程序；換語言是重新載入頁面，卡片隨新語言重畫，計算不會因此重啟（`gui_preview.py lite` 檢查換語言後沒有啟動任何東西）。

### 被否決的做法
- 把鎖定的功能全放進頁首選單：十個項目太吵，改成徽章加一頁，專業版的兩個相關群組各掛一個小標籤。
- 啟動時或每頁顯示完整版介紹、彈窗、倒數：違反「不吵」。
- 用對話框顯示限制：改用頁內卡片，沿用授權卡片的位置與樣式（◆ 琥珀條）。
- 在表單內悄悄把使用者填的值縮小：只對「建議值」做（見「起始值」），使用者自己輸入的值一律保留，超過就說並擋在開始前。
- 在 Lite 的 CPU 機器上顯示隱式溶劑開關：D-25 實測 GBn2 在 CPU 上比顯式水慢很多，所以只在有 GPU 時提供。

### 未驗證與待整合
- NiceGUI 頁面只用假的 `nicegui` 物件跑過頁面函式（找 NameError 與呼叫錯誤），沒有在真實瀏覽器看過版面；CI 的 `gui-preview` Lite 版會產生四種語言的截圖並檢查卡片行為。
- 隱式溶劑開關需要平台探測；Lite 的快速表單第一次開啟時在背景呼叫 `choose_platform`（一個 GUI 程序一次），探測完才出現開關。沒有 OpenMM 或沒有 GPU 就不顯示。
- `advisor.py` 在沒有 GPU 時建議 `solvent: gbn2`（「課堂示範可以改用隱式溶劑縮短時間」），與 D-25 的更正互相矛盾。本工作包不動 advisor，列為待整合。
- FLOW 開發者另有類似的隱式溶劑判斷，這裡的 `gbn2_preview_offer` 刻意自成一體，整合時統一。

## 8. 隱式溶劑快速預覽
用既有的 `md.solvent: gbn2`（D-20，`implicit_solvent.md`），不新增科學模型。**以下更正 11/11 早上專案文件 06 的初稿**：
- 初稿寫「低配筆電幾分鐘看到結果、PMF 當描述性參考」。兩點都不對。
- GBn2 只在 GPU 上快；CPU 上 3PTB 反而很慢（D-25 實測）。所以快速預覽**只在 Doctor 偵測到可用 GPU 時提供**，純 CPU 機器不顯示。
- 既有閘門在 GBn2 下**擋掉結合自由能**（去溶劑化能障在連續介質下失真）與金屬位點。Lite 不改這個閘門。快速預覽只做分子動力學與結構分析，要做 PMF 請改顯式水。
- 報告加註：隱式溶劑的結果只供描述，不能與顯式水或文獻值直接比較。

## 9. 打包（`tools/build_lite.py`）
複製乾淨的源碼樹，移除 `edition.pro_modules()` 列的檔案，換成同名的空殼模組：匯出原模組的公開名稱，呼叫時丟 `UpgradeRequired`（帶四語說明）。
寫入 `md20/_edition.json`。然後在這棵樹上跑測試（CI `lite-build`），確認少了這些模組仍可 import、基本流程可跑。
哪些模組可以乾淨移除，以「空殼替換後全套 import 通過」為準；移不乾淨的留在 Lite 並記在本節。
Lite 發行建議同時開 `compiled_core`（`licensing.md` §13），把 `edition.py` 一起編譯。

## 10. 誠實限制
- 規模上限是 `edition.py` 裡的數字。原始碼發行時改得掉，所以 Lite 應搭配核心編譯。編譯不是不可破。
- 真正拿不回來的是完整版功能的程式碼，因為沒有出貨。
- 用 `features` 帶 `lite` 的授權裝在**完整安裝包**上時，完整版程式碼在對方手上，保護等同 D-125。要給外部的人，請給 Lite 安裝包。
- 上限數字尚未在目標筆電校準。

## 11. 想請審查者回答
1. 3 萬原子與 400 殘基的上限，對「讓人試到又不夠用」是否合適？
2. Lite 開放快速 PMF（12 窗口、單次拉離、不補窗）是否會讓人誤以為那是可排名的結合自由能？目前靠 D-96 的資格標示擋。
3. 進階分析工具箱整個留給完整版，還是開放其中一項當引子？
