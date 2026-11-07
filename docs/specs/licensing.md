# Spec: 簽章授權（第 2 層，D-125）

對象：要審查授權設計的人。條文層（第 1 層）是 `LICENSE`（D-124）；本檔是程式層。

## 1. 要解決的問題
repo 必須公開（CI 費用），但擁有者（HCC Lab, NKUST）不允許別人任意使用。需要一個**擁有者可以逐人發放、逐人收回（到期）**的機制，
不需要伺服器，學生離線也能用，並且讓每份輸出都能追溯到哪一份授權。

## 2. 原理
- 擁有者持有 RSA 私鑰（離線保管，不在 repo）。套件內 `md20/util/owner_pub.pem` 是對應公鑰。
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

## 3. 判定流程（`license.status()`）
1. 在 `<app data>/license/` 與套件內 `md20/util/licenses/` 找 `*.md20license`（單檔上限 64 KB）。
2. 每份：簽章 → payload 結構 → 期限 → 機器。任何一份通過就是「有效」。
3. 都不通過時回報最有資訊的一個：過期 ＞ 機器不符 ＞ 簽章錯誤 ＞ 沒有授權。
4. 結果依檔案的修改時間、大小、可信金鑰與日期快取，檔案一變就重算。

## 4. 閘門
| 擋（真正的計算） | 不擋 |
|---|---|
| `Workflow.run`（含 FakeBackend 時，因為對接與建模是真的）、`make_backend_factory(fake=False)` | `demo`、`doctor`、`drivers`、`status`、`report`、`stamp`、`project` |
| CLI：`build`、`run`、`queue run`、`pipeline run`、`resume`（有東西要續跑）、`fold` | `setup-vina`、`setup-fold`、`setup-cg`、`validate`、`screen template`、`pipeline example`、`queue add|list`、`resume --list`、`license ...` |
| GUI：`Runner.start_process`（啟動子程序前）、`gui.worker._real_run`（子程序內） | GUI 開啟與瀏覽、報告重新整理、`MD20_GUI_FAKE_RUN` 假計算、`run --fake`／`queue run --fake` |

CLI 沒有授權時以結束碼 13 離開，stderr 印四語說明、機器碼與匯入方式。GUI 每頁頂端顯示授權卡片（說明、機器碼、複製鈕、`.md20license` 上傳匯入），
按開始時另跳通知；子程序若仍被啟動，`worker` 會以四語把原因寫進 `job.json`。

## 5. 不可從外部關掉
`license.py` 不讀環境變數、設定檔、命令列參數（測試檢查原始碼）。沒有「略過授權」的開關，因為公開原始碼裡的開關就是教所有人怎麼繞過。
測試與 CI 的行程內測試由 `tests/conftest.py` 的 autouse fixture 用 monkeypatch 改 `TRUSTED_KEYS`、`license_dir`，並安裝以測試金鑰簽的授權。
真實擁有者私鑰不在 repo，測試金鑰只存在於記憶體與暫存目錄。

## 6. 擁有者操作
```
md20 license issue --key md20_owner_private.pem --name "王小明" --days 365 --machine 3F9A-07C2-B15D-6E48 --out wang.md20license
md20 license issue-batch --key md20_owner_private.pem --csv 名單.csv --out 授權資料夾
```
CSV 欄位：姓名、天數或 `YYYY-MM-DD`、機器碼（可空）；UTF-8。`--scope all` 簽全開授權（不能同時綁機器）。
Windows：`installer\owner\MD20-Issue-License.cmd`（單人或批次）與 `MD20-Unlock-This-PC.cmd`（替本機簽並安裝）。

## 7. 誠實限制
- 原始碼公開：能改程式的人可以移除檢查。這一層是門檻與證據，不是防拷。規避即違反 D-124 條款。
- 函式庫層不擋（`build_case`、`run_protocol` 等可被直接呼叫），只擋入口。
- 改電腦時鐘可延長期限；改 machine id 可規避機器綁定。
- 未綁機器的授權檔可被複製給別人用；要防止，簽發時帶機器碼。
- 同一把 RSA 金鑰做 OAEP 加密（戳記）與 PSS 簽章（授權）：用不同填充與訊息前綴，未知跨用途攻擊；換成獨立金鑰需要擁有者另行保管，被否決（見 D-125）。

## 8. 想請審查者回答
1. 同一把 RSA 金鑰兼用，是否值得為了「乾淨」而換成獨立的 Ed25519 金鑰？
2. 是否要在報告 HTML 頁尾也印授權 id（目前只在 JSON 戳記與加密紀錄）？
3. `scope: all` 的內建授權（`md20/util/licenses/`）放進哪個版本、由誰決定開源時機？
4. 私鑰遺失或外洩時的換鑰流程（`TRUSTED_KEYS` 雙鑰並存，舊鑰在所有舊授權到期後移除）是否足夠？
