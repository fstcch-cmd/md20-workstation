# 工作看板（多個開發 session 協調用）

同時有多個 Claude session 在推進本 repo。**開工前先 `git pull` 讀本檔，在「進行中」認領（寫 session 連結與時間），完成後移到「完成」並註明 commit。**
不要動別人認領中的檔案／主題；需要時在該列下方留言。決策理由寫在 `docs/DECISIONS.md`，規格寫在 `docs/specs/`。

## 進行中
| 項目 | 來源 | 認領 session | 開始 | 備註 |
|---|---|---|---|---|
| 巡檢 #1（01:00）：`installer-windows` **綠**（PS 5.1 真跑：環境、Vina、doctor、demo、範本）；pure-python 6/6 綠；heavy(metal) 紅＝測試不穩定（D-29 已修）；openmm-stack 三 OS 與 heavy(workflow) 仍在跑 | — | session_016gcJzBDnGh3heY9HLWnva3 | 2026-11-02 01:10 | 下一次 04:30 |
| **里程碑：11/02 09:00 使用者在獨顯 Windows 筆電上安裝並跑起來**——目標 main 全綠（含 `installer-windows`），之後所有 push 不得讓 Windows 紅 | 使用者 | 全部 session | 2026-11-01 23:40 | 本 session 夜間巡檢 CI；紅了修到綠優先於新功能 |
| 約束策略修正：分組約束（backbone/sidechain/ligand 單一力 grp 參數）、主要釋放移到 NPT、配體 k 1000、`md.restraints` standard/gentle/hold_backbone、受約束 RMSD 標註（D-23、specs/restraints_freeze_truncation.md §3.1） | session_016gcJz8q2F6515MWPncJEZu | 本 commit（CI 待驗） |
| 監看 CI 並修紅（每 30 分鐘巡檢；里程碑 11/02 09:00 Windows 全綠優先於新功能）：f140a49 起的 openmm-stack 三 OS、heavy、paper-docking | — | session_016gcJz8q2F6515MWPncJEZu | 2026-11-01 | 結果記入 STATUS / DECISIONS（D-24、D-25） |

## 待認領（依重要性）
| 項目 | 來源 |
|---|---|
| 金屬：力常數依元素×配位原子表、配位水納入鍵結、配體配位金屬的距離約束後備 | 同上 §3 |
| umbrella：MBAR overlap matrix 門檻、OpenMM 內建 metadynamics 後備、funnel 約束（研究 tier ΔG°） | 同上 §2 |
| 約束策略智慧建議 `recommend_restraint_strategy`；凍結／口袋截斷／資源估算（分組分階段已完成 D-23；其餘依會診 §1 Q2–Q6） | `docs/specs/restraints_freeze_truncation.md` |
| 對接盒子過大防呆閘門（任一邊 > 40 Å 或盒內殘基 > 300，提示格點數 ×0.375） | DECISIONS D-14、REVIEW_QUESTIONS #6 |
| Vina 執行檔 sha256 表、micromamba 與環境版本鎖定 | REVIEW #19 |
| 戳記改為私鑰簽章（目前只有公鑰加密，不能證明來源） | REVIEW #20 |
| `sampling/runner.py`（無呼叫者）移除或修正 | REVIEW #17 |

## 完成
| 項目 | session | commit |
|---|---|---|
| 驅動偵測→判定→一鍵下載（`md20 drivers`、Doctor、GUI 卡片、安裝器 `-Cuda`；D-27、specs/drivers.md） | session_016gcJzBDnGh3heY9HLWnva3 | 本 commit（NVIDIA 查詢待真機） |
| Windows 安裝器 5.1 相容＋啟動器＋CI `installer-windows`＋`docs/WINDOWS_QUICKSTART.md`（明早 09:00 筆電測試用；D-26） | session_016gcJzBDnGh3heY9HLWnva3 | 本 commit |
| 水盒不過大：十二面體、tier padding、下限閘門、離子強度可調（D-22、specs/solvent_box.md） | session_016gcJzBDnGh3heY9HLWnva3 | 本 commit（CI 待驗） |
| PBC 歸零／錨定（`analysis/pbc.py`、`center_trajectory`、歸零 DCD、視覺性解離閘門；D-21、specs/pbc_centering.md；GBn2 無盒情況已處理） | session_016gcJzBDnGh3heY9HLWnva3 | 本 commit（CI 待驗） |
| 會診 §1 Q6 隱式溶劑 GBn2（D-20，待 CI） | session_016gcJz8q2F6515MWPncJEZu | 見 git log |
| CI 重測拆成平行 heavy job（會診 §5 Q2，D-19） | session_016gcJz8q2F6515MWPncJEZu | 見 git log |
| 會診 §0.1 配體質子化（pH 7.4 規則表）、§0.2 GUI 預設本機（D-18，ionize 測試待 CI） | session_016gcJz8q2F6515MWPncJEZu | 見 git log |
| 開發文件會診（所有規格的審查問題回答＋未寫到的科學缺口＋優先順序）；此 session（ND20 審查）只做會診，不認領實作 | session_016gcJzBDnGh3heY9HLWnva3 | 6a1a833 |
| REVIEW #15 配體直接配位金屬 → NEEDS_HUMAN；REVIEW #16 pose 對應改連接圖（D-17，待 CI） | session_016gcJz8q2F6515MWPncJEZu | 見 git log |
| 補窗續跑冪等：已完成直接回傳（finished_result）＋中途暫停從未完成輪次接續 | 第四個 session ＋ session_016gcJz8q2F6515MWPncJEZu | 21bb0f1、c016a08 |
| 經金屬的 1-3/1-4 處理 | 第四個 session | 9c20327（待 Ubuntu 驗證） |
