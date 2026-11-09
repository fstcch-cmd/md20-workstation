# Spec: 簽章授權（第 2 層 D-125；分工 D-127；第 3 層 D-128）

對象：要審查授權設計的人。條文層（第 1 層）是 `LICENSE`（D-124）；本檔是程式層。

**分工（D-127）**：本 repo（md20）只**驗證**授權；產生金鑰、簽發、授權紀錄都在 HCC Lab 的私人簽發端 repo，學生拿到的套件不含簽發程式碼。
兩邊靠本檔的格式（§2、§9）與測試向量 `tests/data/license_vector_v1.json`、`license_vector_v2.json` 對齊。
**第 3 層（D-128）**：格式升為 v2（等級、功能、單位、席次、最高版本、簽發金鑰指紋），功能閘門、評估版浮水印、輸出授權編號、簽章撤銷清單。見 §9–§12；v1 授權照樣有效。

## 1. 要解決的問題
repo 必須公開（CI 費用），但擁有者（HCC Lab, NKUST）不允許別人任意使用。需要一個**擁有者可以逐人發放、逐人收回（到期）**的機制，
不需要伺服器，學生離線也能用，並且讓每份輸出都能追溯到哪一份授權。

## 2. 原理
- 擁有者持有 RSA 私鑰（離線保管，不在任何公開 repo）。套件內 `md20/util/owner_pub.pem` 是對應公鑰。
- 授權檔 `*.md20license`＝JSON `{"payload", "sig"}`。簽章是對 `b"md20-license-v1\n"` ＋ canonical JSON(payload) 的 RSA-PSS（SHA-256、MGF1-SHA256、最大 salt）。
- 程式只信任 `license.TRUSTED_KEYS` 裡的公鑰（預設一把；換鑰時可兩把並存）。

### payload 欄位
| 欄位 | 意義 |
|---|---|
| `schema` | `md20-license/1` |
| `id` | 隨機 16 位十六進位，輸出戳記用它追溯 |
| `licensee` | 被授權人姓名 |
| `issued_at` | UTC 簽發時間 |
| `expires` | `YYYY-MM-DD`，含當天；`null`＝不到期 |
| `machines` | 機器碼清單；空＝不綁機器 |
| `scope` | `use`（受期限與機器限制）或 `all`（不檢查機器，擁有者簽，供將來開源） |
| `note`、`issuer` | 備註與簽發單位 |

### 機器碼
`3F9A-07C2-B15D-6E48`：OS machine id（Windows MachineGuid、Linux machine-id、macOS IOPlatformUUID，取不到用主機名稱）＋OS＋CPU 架構，
加鹽 SHA-256 取前 64 位。不含可讀個資，不隨使用者帳號改變。`md20 license machine` 印出。

（§2 描述 v1 的九個欄位；v2 的選填欄位與簽章前綴見 §9。）

## 3. 判定流程（`license.status()`）
1. 在 `<app data>/license/` 與套件內 `md20/util/licenses/` 找 `*.md20license`（單檔上限 64 KB）。
2. 每份：簽章 → payload 結構 → 撤銷清單 → 期限 → 版本上限（`max_version`）→ 機器。任何一份通過就是「有效」。
3. 都不通過時回報最有資訊的一個：過期 ＞ 版本超出 ＞ 機器不符 ＞ 已撤銷 ＞ 簽章錯誤 ＞ 沒有授權。
4. 結果依檔案的修改時間、大小、可信金鑰與日期快取，檔案一變就重算。

## 4. 閘門
| 擋（真正的計算） | 不擋 |
|---|---|
| `Workflow.run`（含 FakeBackend 時，因為對接與建模是真的）、`make_backend_factory(fake=False)` | `demo`、`doctor`、`drivers`、`status`、`report`、`stamp`、`project` |
| CLI：`build`、`run`、`queue run`、`pipeline run`、`resume`（有東西要續跑）、`fold` | `setup-vina`、`setup-fold`、`setup-cg`、`validate`、`screen template`、`pipeline example`、`queue add|list`、`resume --list`、`license ...` |
| GUI：`Runner.start_process`（啟動子程序前）、`gui.worker._real_run`（子程序內） | GUI 開啟與瀏覽、報告重新整理、`MD20_GUI_FAKE_RUN` 假計算、`run --fake`／`queue run --fake` |

CLI 沒有授權時以結束碼 13 離開，stderr 印四語說明、機器碼與匯入方式。GUI 每頁頂端顯示授權卡片（說明、機器碼、複製鈕、`.md20license` 上傳匯入），
按開始時另跳通知；子程序若仍被啟動，`worker` 會以四語把原因寫進 `job.json`。

功能閘門（D-128）另見 §10：在上表的入口再多檢查「授權含不含這個功能」，不含時同樣以結束碼 13 離開。

## 5. 不可從外部關掉
`license.py` 不讀環境變數、設定檔、命令列參數（測試檢查原始碼）。沒有「略過授權」的開關，因為公開原始碼裡的開關就是教所有人怎麼繞過。
測試與 CI 的行程內測試由 `tests/conftest.py` 的 autouse fixture 用 monkeypatch 改 `TRUSTED_KEYS`、`license_dir`，並安裝以測試金鑰簽的授權。
真實擁有者私鑰不在 repo，測試金鑰只存在於記憶體與暫存目錄。

## 6. 簽發端（不在本 repo）
簽發（金鑰產生、單人與整班簽發、替本機簽並安裝、授權紀錄）由 HCC Lab 的私人簽發端 repo 負責；md20 不含這些程式碼，`md20 license` 只有：
```
md20 license status           # 四語狀態
md20 license machine          # 印出本機機器碼
md20 license install FILE     # 驗證通過才複製進 app data
md20 license update-revocations FILE   # 匯入簽章撤銷清單（D-128，§11）
```
`md20 stamp keygen` 只印出「金鑰產生已移到 HCC Lab 的私人工具」（結束碼 1）。`stamp decrypt` 仍在（需要擁有者私鑰，屬讀取）。
CSV 名單、`--scope all`、機器碼綁定等簽發選項的定義見簽發端 repo；本檔 §2 的 payload 是兩邊共同遵守的契約。

### 格式測試向量
`tests/data/license_vector_v1.json` 是簽發端 `test_vectors/v1.json` 的逐位元組副本：一把**測試**公鑰與三組固定 payload 的簽章（私鑰在產生向量後已丟棄）。
`tests/test_license_vector.py` 驗證：驗證器接受每組向量、任何欄位或簽章被改就拒絕、向量金鑰沒被信任時一律拒絕、向量檔不含私鑰且不同於套件內 `owner_pub.pem`。
這把測試公鑰只在測試中用 monkeypatch 放進 `TRUSTED_KEYS`，**絕不加入**真正的清單。格式變更必須兩個 repo 同時改（規格、向量、測試）。

### 測試如何取得授權
測試要有授權可驗證，所以 `tests/_license_testkit.py` 放一個最小的測試用簽章 helper（用 `tests/conftest.py` 產生的拋棄式金鑰）。
測試程式不隨套件發行（`pyproject.toml` 只打包 `md20*`），所以這不是簽發端；`tests/test_license.py` 檢查 `md20.util.license` 沒有任何簽章／讀私鑰的公開函式。

## 7. 誠實限制
- 原始碼公開：能改程式的人可以移除檢查。這一層是門檻與證據，不是防拷。規避即違反 D-124 條款。
- 函式庫層不擋（`build_case`、`run_protocol` 等可被直接呼叫），只擋入口。
- 改電腦時鐘可延長期限；改 machine id 可規避機器綁定。
- 未綁機器的授權檔可被複製給別人用；要防止，簽發時帶機器碼。
- 同一把 RSA 金鑰做 OAEP 加密（戳記）與 PSS 簽章（授權）：用不同填充與訊息前綴，未知跨用途攻擊；換成獨立金鑰需要擁有者另行保管，被否決（見 D-125）。
- 第 3 層補充：撤銷清單只在使用者收到新清單後生效，且可被刪掉 app data 的檔案退回套件內那份；評估版浮水印、授權編號都是程式寫入的，改程式的人可以拿掉。功能閘門同樣只在入口。

## 8. 想請審查者回答
1. 同一把 RSA 金鑰兼用，是否值得為了「乾淨」而換成獨立的 Ed25519 金鑰？
2. 報告 HTML 頁尾、PDB REMARK、圖 metadata 現在都印授權 id（D-128）；姓名也印在 HTML 頁尾是否合適？
3. `scope: all` 的內建授權（`md20/util/licenses/`）放進哪個版本、由誰決定開源時機？
4. 私鑰遺失或外洩時的換鑰流程（`TRUSTED_KEYS` 雙鑰並存，舊鑰在所有舊授權到期後移除）是否足夠？
5. 撤銷清單與授權共用同一把私鑰（用不同前綴區分）；是否值得另立撤銷專用金鑰？
6. `tier` 除了 `evaluation` 與 `site` 目前沒有行為差異，是否要讓 `teaching` 預設限制某些功能？

## 9. 格式 v2（D-128）
schema `md20-license-v2`，簽章前綴 `b"md20-license-v2\n"`（v1 仍是 `md20-license-v1\n`）。驗證端依 payload 自己的 `schema` 選前綴：v2 payload 只在 v2 前綴下驗得過，v1 payload 只在 v1 前綴下驗得過，
所以改 `schema` 無法把一種當成另一種；測試向量有跨前綴的負例。v2 保留 v1 的九個欄位，另加下列**選填**欄位；**缺少時依 v1 行為**，所以沒有這些欄位的 v2 授權、以及全部舊授權，照樣完整有效。

| 欄位 | 型別／規則 | 缺少時 |
|---|---|---|
| `tier` | `teaching｜research｜evaluation｜commercial｜site` | 無等級（不影響任何行為） |
| `features` | 字串清單，目前可用 `binding`、`membrane`、`hts`、`cg`；含 `all` 表示全部；空清單＝一個功能都沒有 | 全部功能 |
| `org` | 單位名稱（字串） | 空 |
| `seats` | 正整數；可綁機器數，`machines` 長度不得超過它 | 不限制 |
| `max_version` | PEP 440 版本；MD20 版本比它新就視為超出維護期（`version_limit`）。`0.1.0a19` 早於 `0.1.0`；`0.1.0.post1` 晚於 `0.1.0`；無法解析目前版本時擋，不猜 | 不限制 |
| `issuer_key` | 簽發公鑰指紋（SubjectPublicKeyInfo DER 的 SHA-256，64 位小寫十六進位）；必須等於實際驗過簽章的那把金鑰的指紋 | 不檢查 |

- `tier: site`：綁**單位**而不綁機器。必須有 `org` 且 `machines` 為空，否則視為格式錯誤。
- `tier: evaluation`：見 §10 的浮水印；其他等級目前沒有行為差異（等級是紀錄與條款用）。
- 簽章有效但欄位格式錯誤（等級不認得、`seats` 不是正整數、`issuer_key` 與簽章金鑰不符、機器數超過席次…）一律拒絕。未知的額外欄位忽略（簽章涵蓋它們）。
- v1 payload 即使帶了 v2 欄位也**不生效**（v1 只有九個欄位）。

## 10. 功能閘門與評估版（D-128）
`require("…", feature="binding")` 除了要有效授權，還檢查授權的 `features`。不含時丟 `FeatureNotLicensed`（`LicenseRequired` 的子類別），
CLI 結束碼 13（與沒有授權相同），stderr 四語「你的授權不含 X」，並列出目前等級與已含功能。GUI 在被擋的啟動後顯示卡片（`feature-card`）。
功能由**設定檔本身**決定（`workflow.required_features(cfg)`），只在計算入口擋，不動任何科學邏輯：

| 功能 | 設定檔條件 | 入口 |
|---|---|---|
| `binding`（SMD／傘狀採樣，結合自由能） | `binding.enabled`、`binding.added` 有值、或 `binding.alone` 有開 | `Workflow.run`、`pipeline run`、`resume`、GUI `start_process`／worker |
| `membrane`（膜系統） | `md.membrane` 有設定 | 同上 |
| `hts`（HTS 篩選） | 有 `screen` 區塊 | 同上 |
| `cg`（粗粒化） | `md.resolution: cg`（粗粒化不計算結合自由能，所以不要求 `binding`） | 同上 |

`pipeline run` 在建立專案之前就檢查；`resume` 對缺功能的工作流程印出訊息並略過，其餘照跑，最後以 13 結束。沒有環境變數、設定或參數可以放行（測試檢查原始碼）。
不擋的指令不變（§4）。函式庫層（直接呼叫 `build_case` 等）和以前一樣不擋。

**評估版（`tier: evaluation`）**：輸出加四語「評估版，不得用於決策」（zh／en／ja／ko 四句以 ` / ` 連接）：HTML 報告頁尾（`html_footer`，含繪圖的 plotly 頁）、圖檔 metadata（PNG `Disclaimer`、SVG `dc:title`、PDF `Title`）、
圖上的淡色斜向浮水印（只畫英文，因為預設字型沒有 CJK 字形；四語版在 metadata）、PDB／PDBQT `REMARK 999`（純 ASCII 英文）、JSON 戳記（`_md20.eval`）。
目前沒有 PDF 報告產生器，所以「PDF」指圖的 PDF 輸出與其 metadata。

## 11. 簽章撤銷清單（D-128）
擁有者用**同一把私鑰**簽 `revoked.json`：`{"payload": {"schema": "md20-revocations-v1", "issued_at": "YYYY-MM-DDTHH:MM:SSZ", "ids": ["<16 位十六進位授權編號>", …]}, "sig": base64}`，
簽章前綴 `b"md20-revocations-v1\n"`，與授權的前綴不同：授權簽章不會被當成撤銷清單，反之亦然（向量有負例）。

- 驗證端讀兩處：`<app data>/license/revoked.json`（`md20 license update-revocations` 匯入）與套件內 `md20/util/licenses/revoked.json`（發行時隨附）。
  只採用簽章有效、格式正確的清單；兩處都有效時取**較新**的 `issued_at`（相同時合併編號）。簽章錯誤或格式錯誤的檔案當作不存在。
- 清單內的授權編號視為**無效**（狀態 `revoked`，四語說明），v1、v2 授權都適用；`install` 也不會安裝被撤銷的授權。優先於過期等其他狀態。
- `md20 license update-revocations FILE`：簽章有效且 `issued_at` **嚴格比目前使用的新**才寫入（防止退回舊清單）；否則四語說明並保留現狀。
- 清單是累積的：簽發端每次撤銷都在原清單加編號並重簽，`issued_at` 只增不減。
- **不做線上更新**；使用者要拿到新清單（隨新版安裝包，或擁有者寄出 `revoked.json`）才生效。
- 限制：使用者可刪掉 app data 的 `revoked.json`（回到套件內那份）；離線時撤銷要等新清單送達；撤銷只針對授權編號，改程式的人仍可繞過（§7）。
- 簽發端：`python -m md20sign revoke --key K ID…`（私人 repo）。

## 12. 測試向量 v2
`tests/data/license_vector_v2.json` 是簽發端 `test_vectors/v2.json` 的逐位元組副本（SHA-256 `e05050cd2bd2849e4dabbba096451a8d1438beb8335b1d18533df8c11817efff`，測試檢查）。內容：一把**測試**公鑰（私鑰已丟棄，絕不加入 `TRUSTED_KEYS`）、
七份 v2 授權（各等級、功能、席次、`max_version`、站點、中文）及驗證端應讀出的值、兩份撤銷清單（第二份較新且累積）、五個跨前綴負例。
`tests/test_license_vector_v2.py` 驗證；v1 向量與測試（`test_license_vector.py`）不變。

## 13. 第 4 層：出貨 build 的核心編譯（D-166，方案一「只編譯、不加密」）
使用者 2026-11-09 在三方案中選「只做 Cython 編譯、不加密」。這一層**不碰金鑰、不加密、不做執行期解密、不動態 exec**，因此不需要任何 GitHub Secret。

- 工具 `tools/build_protected.py`：`CORE_MODULES` 明列核心模組（`util/license.py`、`util/stamp.py`、`workflow.py`、`build/assemble.py`、`build/metal.py`、`build/metal_params.py`、`build/pipeline.py`、`sampling/binding.py`、`sampling/funnel.py`、`sampling/_mdh_legacy.py`）。刻意不含 i18n、report、gui、cli、advisor，以及各 package 的 `__init__.py`（編譯 `__init__.py` 會破壞 import 與 package data）。
- `plan_build` 純函式決定「編譯＋移除 .py」清單，永不列入 `__init__.py`；`strip_sources` 只有在對應 `.pyd`／`.so` 已存在時才移除該 `.py`（fail-safe，不出缺模組的 build）；`compile_core` lazy import Cython，缺則丟 RuntimeError（fail closed）、就地 `build_ext --inplace`。
- 發行：`release-windows.yml` 的 `compiled_core` 輸入**預設 false**。false＝現行 `git archive` 原始碼發行逐位元不變；true＝裝 Cython、對乾淨出貨樹編譯核心、移除核心 `.py`、改打包 staging 樹，並斷言 `md20/util/license.py` 不在 ZIP。
- **誠實限制**：編譯成 C 擴充比讀 `.py` 難得多，但不是不可破（擴充仍可逆向）。真正的護城河是「出貨 build 不含核心原始碼」本身（D-128 §6），編譯是手段不是加密；驗證邏輯（§1–§7）內容完全不變，只是改以編譯形式出貨。端到端（真編譯＋乾淨機安裝仍可跑）需 opt-in 發行 run 驗證。
