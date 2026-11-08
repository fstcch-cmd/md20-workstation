# 統一科學評估：執行狀態、診斷、說法資格、比較資格（D-134，Evidence-Driven Repair R2）

狀態：**已實作・純 Python 驗證**（`tests/test_evidence_assessment.py`）；真實引擎路徑仍待 CI。前身：`master_iteration_2026-11-07.md` §3.1（D-96 的 `assess_pmf`）。

## 1. 要解決的問題
`md20/report/evidence.py` 原本：MD 只看 `status == COMPLETE` 就標「有證據」；結合自由能只看 `status == PASS` 加 `dG_standard_kj_mol` 非空就標「有證據」。
但 `compare_binding`、圖說用的是 `assess_pmf` 的資格。結果：同一份報告裡，證據矩陣寫「有證據」，比較表卻把同一個結果排除，**徽章互相矛盾**。
另外報告的結合表與 GUI 只要有 ΔG° 數字就顯示成 ΔG°，執行成功＋數字＋取樣失敗的結果仍會被讀成親和力。

## 2. 四件事分開
| 層 | 問什麼 | 資料來源 | 能不能單獨支持科學說法 |
|---|---|---|---|
| 執行狀態 | 計算跑完了嗎 | `status`（PASS／COMPLETE／FAILED…） | **不能**。只是「跑過」 |
| 診斷 | 每一項取樣檢查說什麼 | `assessment.diagnostics`（pass／fail／unknown＋值＋門檻＋門檻出處） | 單項不能；local 通過不代表 global 通過 |
| 說法資格 | 這個結果可以講哪一句話 | `assessment.eligibility` ＋ ΔG° 值是否存在、有沒有被撤回 | 可以，**依說法分開** |
| 比較資格 | 兩個以上結果可不可以放在一起比 | 說法資格＋條件簽章一致＋情境 | `compare_binding`、`comparability` 決定 |

說法（claim）由弱到強：`diagnostic_curve`（只當診斷曲線）→ `path_specific`（沿這條拉離路徑的 PMF 井深，不是內在親和力）→ `dG_standard`（1 M 徑向近似下的標準結合自由能）→ `affinity_ranking`（親和力排序，另需 compare 判定條件相容）。
一個結果可以支持較弱的說法而不支持較強的：例如 ΔG° 被撤回但路徑特定 PMF 合格 → 證據矩陣寫「只有沿這條拉離路徑的 PMF（描述性），不是標準 ΔG°」。

## 3. 唯一的入口：`md20/sampling/assessment.py`
- `resolve_assessment(result, pmf=None)` → `(assessment, source)`：
  - `stored`：run 當時寫下的評估（D-96 起）。
  - `reassessed`：舊結果沒有評估，但報告重建時讀得到 manifest 的 PMF 欄位 → 重算診斷**顯示**，但標 `legacy`，資格一律壓成不成立（沒有人在 run 當時合格化過）。
  - `legacy`：什麼都沒有 → 全部 unknown。
- `claim_status(result, claim, *, pmf=None, overrides=None)` → 版本化紀錄（`schema: md20.assessment.claim/1`）：
  `claim`、`thresholds_version`（評估當時）與 `current_thresholds_version`、`execution_status`／`executed`、`assessment_source`、
  `assessment`（pass／fail／unknown）、`eligible`、`evidence_ids`／`diagnostics`（值、門檻、出處）、`failed`、`unknown`、`conflicts`、`reasons`（原因代碼）、`withheld`、`overrides`。
- `claim_eligible(result, claim)`、`strongest_claim(result)`：薄包裝。
- 規則：
  1. 缺欄位＝unknown，**絕不當 pass**；舊結果＝待重新分析。
  2. `dG_standard`／`affinity_ranking` 另要求 ΔG° 值存在且未被撤回：儲存的旗標不能壓過缺值或撤回。
  3. 沒有執行（`status != PASS`）一律不成立。
  4. overlap 圖不連通不能被 solver 成功旗標、平滑的 PMF 或 ΔG° 數值救回（診斷層就擋，`overlap_graph` fail → `path_specific` 與 `dG_standard` 都不成立）。
  5. **人工 override 只記錄**（`override_record(claim, by, why, at)`，掛在結果的 `overrides` 或呼叫參數），寫進紀錄的 `overrides`，標「recorded decision only」；`eligible` 與 `assessment` 不因此改變，fail 不會變成 pass。
  6. 門檻不變、不放寬（`THRESHOLDS_VERSION` 沿用）。

## 4. 所有輸出讀同一份紀錄
| 輸出 | 怎麼讀 |
|---|---|
| 證據矩陣（`report/evidence.py`） | 結合列：`claim_status(dG_standard)` 成立→`supported`；只有 `path_specific`→`limited`＋`path_specific_only`；兩者都不成立→`limited`＋原因，說法降為 `diagnostic_curve`。每列帶 `execution_status`、`assessment{state, source, thresholds_version, evidence_ids, failed, unknown}`、`claim`、`claim_eligibility`、`requested_claim`／`requested_eligible`。舊鍵 `status` 保留。 |
| MD 列 | `status = "ran"`（已執行）而不是 `supported`；原因 `execution_only`。COMPLETE 是執行狀態，不是科學說法。重複數列沿用條數檢查。 |
| 計畫重複數 | 改用 `engine.replica_plan.configured_replicas(cfg)[0]`（預設 3），不再 `or 1`。 |
| 圖說／重點摘要（`interpret.binding`、`figure_text.classify_assessment`） | ΔG° 的「good」句只在 `dG_standard` 成立時出現；有數字但不成立→caution 句（數值只留作診斷值）。重建的舊資料（有診斷但沒有儲存的評估）列出未通過／無紀錄的診斷，全部讀得到時只說「待重新分析」。 |
| 報告結合表（`workflow_report._binding`） | ΔG° 欄只在成立時顯示數字；否則顯示「不作為 ΔG°」，kcal 欄與各次 ΔG° 欄為「—」。 |
| 比較（`sampling/multi.py`、`report/comparability.py`） | 全部經 `claim_eligible`；舊結果「待重新分析」；ΔΔG° 需所有 ΔG° 成立，否則只列路徑特定順序；共同口袋一律描述性。 |
| GUI 候選表（`gui/actions.binding_candidates`、`gui/app.py`） | 多回傳 `dG_eligible`；不成立的數字顯示成「不作為 ΔG°」。 |

## 5. 四語言
新原因代碼 `execution_only`、`assess_legacy`（評估缺漏或舊版，需重新分析）、`assess_failed`、`assess_unknown`、`path_specific_only`、`no_curve` 與說法表 `C` 在 `report/evidence.py` 的 `R`／`C`，四元組（zh-TW、en、ja、ko），測試檢查每個代碼都有四語且 `claim_status` 能產生的代碼都有文字。

## 6. 已知限制
- 評估的 `thresholds_version` 與目前版本不同時只在紀錄上標示（`current_thresholds_version`），不自動重評；舊門檻版本寫下的資格仍沿用。
- 對接、軌跡分析列的 `supported` 仍由各自的檢查旗標決定（沒有科學門檻評估），只有 MD 與結合列改成本規格的語意。
- 「重新評估並寫回」見 §7（D-143）。仍未做：缺少的欄位（plateau、窗口統計、累積曲線）不會由樣本重算，只用 manifest 已儲存的 PMF 欄位。

## 7. 重新評估並寫回（D-143，`md20/sampling/reassess.py`，`md20 binding reassess <workflow>`）
D-134 的未決項目。舊結果（D-96 之前，沒有儲存評估）原本只能「顯示診斷、資格不成立」。現在可以用**目前的** `assess_pmf` 由已儲存的 PMF 欄位重算並寫回。
- **資料來源**：每個重複的 `binding/<目標>/[repN/]binding_manifest.json` 的 `result.pmf`（不重新取樣、不開模擬）。多個重複依 workflow 原本的規則合併：每個重複都支持，結論才成立（`Workflow._binding_assessment`）。
- **寫回位置**：每個重複的 manifest（`result.assessment`）與 `state.json` 的 `steps.binding.results[目標].assessment`。評估內附 `provenance = {source: "reassessed", thresholds_version, original_version, original_was_legacy, original_eligibility, at, by, basis, backups}`。
  寫回後 `resolve_assessment` 會把它當成儲存的評估（`claim_status.assessment_source == "stored"`）；來源只看 `provenance.source`。
- **備份**：每個被改的檔案先複製成 `<檔名>.pre-reassess-<UTC 時間>`（已存在就加編號，不覆蓋舊備份）。原檔不會在沒有備份的情況下被改。
- **資格**：只由 `assess_pmf` 決定。舊結果只有在目前的診斷全部通過時才成立；診斷不通過就如實存成不通過（原因代碼 `assess_failed`，不再是 `assess_legacy`）；欄位缺少仍是 `unknown`，資格不成立。不推測缺少的欄位。
- **冪等**：已經是目前門檻版本的評估不動。舊門檻版本但非舊資料的評估，要加 `--include-outdated` 才重評（資格可能因此變動，`provenance.original_eligibility` 保留了原本的）。
- **比較表**：有 Workflow 時用新的評估重算 `comparison` 與 `cooperativity`（與 `Workflow.binding` 同一組函式）；否則在 state 標 `comparison_stale`。報告不會自動重建，需在 GUI 重新整理報告或重新執行流程。
- **決策紀錄**：每個目標一筆 `binding.reassess`（`why` 中文，含新成立的結論與仍未知的診斷）。
- `--dry-run` 不寫任何檔案；結果以 `report_lines` 輸出。自主行動的 `reanalysis`（結合變體）呼叫同一個函式。
