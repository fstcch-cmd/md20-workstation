# 工作看板（多個開發 session 協調用）

同時有多個 Claude session 在推進本 repo。**開工前先 `git pull` 讀本檔，在「進行中」認領（寫 session 連結與時間），完成後移到「完成」並註明 commit。**
不要動別人認領中的檔案／主題；需要時在該列下方留言。決策理由寫在 `docs/DECISIONS.md`，規格寫在 `docs/specs/`。

## 進行中
| 項目 | 來源 | 認領 session | 開始 | 備註 |
|---|---|---|---|---|
| 配體直接配位金屬永遠不會被擋：配體加入後再 `find_sites`，`foreign` 非空 → NEEDS_HUMAN | REVIEW #15 | session_016gcJz8q2F6515MWPncJEZu | 2026-11-01 20:50 | 需 OpenMM 實跑（CI） |
| `map_pose_onto_reference` 只比元素序列的後備 → 改比對鄰接矩陣，否則 NEEDS_HUMAN | REVIEW #16 | session_016gcJz8q2F6515MWPncJEZu | 2026-11-01 20:50 | |
| 監看 CI：3e7f941 / c016a08 的 Ubuntu 重測（鋅模型、補窗、NaCl 冪等） | — | session_016gcJz8q2F6515MWPncJEZu | 2026-11-01 | 結果記入 STATUS / DECISIONS |

## 待認領（依重要性）
| 項目 | 來源 |
|---|---|
| 約束分組分階段／凍結／口袋截斷／資源估算（**等使用者審查規格後才實作**） | `docs/specs/restraints_freeze_truncation.md` |
| 對接盒子過大防呆閘門（任一邊 > 40 Å 或盒內殘基 > 300，提示格點數 ×0.375） | DECISIONS D-14、REVIEW_QUESTIONS #6 |
| Vina 執行檔 sha256 表、micromamba 與環境版本鎖定 | REVIEW #19 |
| 戳記改為私鑰簽章（目前只有公鑰加密，不能證明來源） | REVIEW #20 |
| `sampling/runner.py`（無呼叫者）移除或修正 | REVIEW #17 |

## 完成
| 項目 | session | commit |
|---|---|---|
| 補窗續跑冪等：已完成直接回傳（finished_result）＋中途暫停從未完成輪次接續 | 第四個 session ＋ session_016gcJz8q2F6515MWPncJEZu | 21bb0f1、c016a08 |
| 經金屬的 1-3/1-4 處理 | 第四個 session | 9c20327（待 Ubuntu 驗證） |
