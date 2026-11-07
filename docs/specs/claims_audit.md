# 宣稱稽核：PMF、ΔG°、進階描述子與機制文字（R6，D-138）

規格來源：`docs/specs/evidence_driven_repair_prompt.md` §3 R6。本檔記錄 2026-11-07 對本地程式（`63e8c71` 之後）逐項核對的結果；只改文字與標註，**不改任何物理協定或科學模型**。

## 1. PMF／ΔG°／共存結果（核對結果）
| 項目 | 現況（檔案） | 判定 |
|---|---|---|
| 反應座標 | 錨點（口袋 Cα）COM 到配體重原子 COM 的距離，PBC（`sampling/binding.py` 開頭） | 已據實標註 |
| Jacobian | `+2kT·ln r` 校正後才取井深與積分（`binding.py` `radial_pmf_summary` 一帶） | 已做 |
| 標準態 | 1 M（`V0_NM3`）徑向積分，**沒有方向／構形約束校正，沒有漏斗**；`binding_condition` 記 `funnel_restraint: False`、`standard_state: "1 M radial integral (no orientational correction)"`；assessment 的 `permitted` 寫明「under the 1 M radial approximation」 | 已據實標註；正式的參考態處理＝A8，需使用者授權（屬協定變更），**未動** |
| 端點 | 末端未持平 → ΔG° 不輸出（`plateau`，D-65） | 已做 |
| 重疊連通 | 完整重疊圖＋MBAR overlap matrix（D-96、D-113）；不連通時 solver 成功也不合格 | 已做；R2 子代理（D-134）把證據矩陣接到同一套評估 |
| 有效樣本、半分、累積漂移 | `assessment.py` 必要診斷 | 已做 |
| 重複敏感度 | `combine_assessments`：每個重複都支持才合格 | 已做 |
| 共存（co-occupancy）與協同 | 熱力學循環需閉合（D-61）；`prohibited` 含「intrinsic affinity from a co-occupancy pull」 | 已做 |
| SMD 功／峰值力 | `prohibited` 含「SMD work or peak force as binding free energy」；圖說寫「功不是自由能」 | 已做 |

**未決（需授權）**：ΔG° 的 `affinity_ranking` 目前跟著「1 M 徑向近似」的合格與否走。若要求「合格的標準態 ΔG°」必須有漏斗／方向約束與解析校正，屬 A8 方法設計＋參考系統測試，需使用者授權後才做。

## 2. 進階描述子
- tICA／MSM：`analysis/toolbox.py` 單一軌跡永不報速率，資格三級（D-105）——維持保守限制。
- 水合位點：密度與佔有率，**不是水合自由能**。報告的「取代或保留會改變結合」改為假說措辭（本條）。
- 網路／相關：DCCM 長距離相關的「配體改變了協同運動」改為觀察＋「相關不是因果」（本條）。

## 3. 本條改的文字（四語同步，同一限制）
| 位置 | 原本 | 改為 |
|---|---|---|
| `report/figure_text.py` `classify_rmsf` | 結合讓蛋白整體變得較不穩定 | 有配體時整體柔性較高；觀察到的差異，不是因果結論 |
| 同上 錨點殘基 | 結合由多個作用點穩定住 | 同時維持多個接觸；不代表結合強度或親和力 |
| 同上 氫鍵佔有率判讀 | 代表那裡是關鍵作用位 | 可驗證的假說（例如突變）；佔有率不證明必要 |
| 同上 DCCM | 配體改變了區域之間的協同運動 | 有配體時觀察到的差異；相關不是因果 |
| 同上 頭基接觸／最後一幀仍接觸 | 停留時間（residence） | 接觸佔有率／接觸持續時間（右設限）；不是停留時間或解離速率 |
| `analysis/membrane.py` `METRIC_LABELS["residence"]` | 停留時間 | 接觸持續時間 |
| `report/workflow_report.py` 水合位點 | 取代或保留它們會改變結合 | 設計假說；密度不是水合自由能，需另外計算或實驗 |

保留不改：「在模擬時間內」的描述句（例如 COM 距離維持 → 配體留在原位），它們描述的是觀察，範圍已限定在模擬內。
