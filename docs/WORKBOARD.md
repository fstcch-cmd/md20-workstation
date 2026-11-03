# 工作看板（多個開發 session 協調用）

同時有多個 Claude session 在推進本 repo。**開工前先 `git pull` 讀本檔，在「進行中」認領（寫 session 連結與時間），完成後移到「完成」並註明 commit。**
不要動別人認領中的檔案／主題；需要時在該列下方留言。決策理由寫在 `docs/DECISIONS.md`，規格寫在 `docs/specs/`。

## 進行中
> 2026-11-02 20:40：session_016gcJz8q2F6515MWPncJEZu 關閉，以下由它認領的項目**全部釋出**，下一個 session 可直接接手（見 `docs/archive/HANDOFF_2026-11-02.md` §6）。
> 新增待辦：MBAR bootstrap 加速（承諾使用者，未開始）；發行 v0.1.0a3（等 617658e CI）。

| 項目 | 來源 | 認領 session | 開始 | 備註 |
|---|---|---|---|---|
| **D-85 胜肽直接貼序列自動摺疊＋一鍵安裝＋教學文件，發行 v0.1.0a12**（使用者 11/03 23:15）：完成，待筆電實測 `Install-Folding.cmd` | 使用者 | session_016gcJz9hwPAMieHsNEctkzL | 2026-11-03 23:20 | 見 DECISIONS D-85 |
| **D-80 專業版：建膜、一鍵摺疊、微秒級**（使用者 11/03 14:32）：規格已寫（membrane、structure_prediction、long_timescale），等使用者看方向後實作 | 使用者 | session_016gcJz9hwPAMieHsNEctkzL | 2026-11-03 14:40 | 其他 session 勿動這三份規格與未來的 md20/build/fold.py、md20/build/membrane.py |
| **D-74 去 AI 感改寫＋日文、韓文＋發行 v0.1.0a4**（使用者 11/03 09:31、09:50）：**已發行 v0.1.0a4**（release run 41579558389）；發行點 49e2eae CI 15 個 job 全綠 | 使用者 | session_016gcJz9hwPAMieHsNEctkzL | 2026-11-03 09:40 | 其他 session 勿動 md20/i18n.py、md20/gui/、md20/report/ |
| **D-73 全部文件與 v0.1.0a3 同步**（使用者 11/03 09:03）：完成，見 DECISIONS D-73 | 使用者 | session_016gcJz9hwPAMieHsNEctkzL | 2026-11-03 09:05 | 只改文件 |
| **D-72 調查 vina.exe 只用約 4 執行緒**（使用者 11/03 08:35）：原始碼確認 Vina 不限制；Windows QoS→HighQoS 標記＋每次執行量測；已隨 v0.1.0a3 發行（使用者決定不做筆電實測） | 使用者 | session_016gcJz9hwPAMieHsNEctkzL | 2026-11-03 08:40 | 其他 session 勿動 md20/docking/vina_cli.py、md20/env/winfix.py |
| **接手（HANDOFF_2026-11-02 §0）＋週二交付**：D-62–D-71 完成；c868014 全綠；Windows＋macOS 發行流程與學生說明（docs/students/）；**a3 發行待使用者按 Run workflow**（本 session 無發行權限）；未決：vina.exe 多配體只用約 4 執行緒 | HANDOFF_2026-11-02／使用者 | session_016gcJz9hwPAMieHsNEctkzL | 2026-11-02 20:45 | 可讀筆電檔案 |
| **待判斷：預設拉離速度 0.01 → 0.005 nm ps⁻¹？**（使用者 11/02 14:58 指示：等筆電 teaching 重跑結果出來後由本 session 判斷並記錄）判斷依據：重跑的 SMD 振盪指標（D-45 smd_ringing）、窗口起始幀是否仍落在反彈點、PMF 井深是否回到合理範圍；降速代價為 SMD 時間加倍 | 使用者 | session_016gcJz8q2F6515MWPncJEZu | 2026-11-02 14:58 | 結論寫入 DECISIONS（新條目）並更新 BindingConfig 預設 |
| **週二交付（使用者 11/02 15:04）：GUI v2 四種模式（教學一、教學二、快速、專業）＋教學頁＋依個案建議參數＋雙語介面與報告**（D-47–D-52 已推；待 CI 與筆電實測，之後發行 v0.1.0a3） | 使用者 | session_016gcJz8q2F6515MWPncJEZu | 2026-11-02 15:04 | 其他 session 請勿動 md20/gui/、md20/advisor.py、md20/report/ |
| **筆電實機測試（Windows 獨顯筆電 "msi"）**：安裝 → doctor（須 CUDA/OpenCL）→ demo → GUI → classroom 3PTB；結果寫 `docs/COMPATIBILITY.md`，失敗就修／發行新版（`docs/archive/LAPTOP_SESSION.md`） | 使用者 | session_016gcJz9hwPAMieHsNEctkzL | 2026-11-02 09:35 | 刪除前一律先問使用者 |
| 鋅鍵結模型平均鍵長偏 0.3 Å（D-32/D-34）：先診斷（heavy metal 測試輸出 3 Å 內非鍵原子）→ 依證據選修法（配位水入鍵結／元素×配位原子力常數／Li–Merz IOD LJ） | D-32、會診 §3 | session_016gcJz8q2F6515MWPncJEZu | 2026-11-02 08:55 | 不擋 Windows（只在 Ubuntu heavy） |
| 巡檢 #3（07:45）：**bb36a4b 全綠且 Windows 不再假綠**（367 passed、5 skipped 全為「在別的 job 跑」或 playwright；對接與 HTS 整合測試在 Windows PASSED）。里程碑 CI 端達成；真機（CUDA、驅動查詢、ns/day）等使用者筆電 | — | session_016gcJzBDnGh3heY9HLWnva3 | 2026-11-02 07:50 | 交付狀態已發給使用者 |
| 巡檢 #2（04:30）：99c8b64 全綠屬實，但 Windows 的 meeko 因缺 gemmi 而 import 失敗 → 對接／HTS 整合測試在 Windows 全被 SKIPPED（D-30 已修：gemmi + MD20_STACK 守門）；等這輪確認 | — | session_016gcJzBDnGh3heY9HLWnva3 | 2026-11-02 04:45 | 下一次 07:45 |
| 巡檢 #1（01:00）：`installer-windows` **綠**（PS 5.1 真跑：環境、Vina、doctor、demo、範本）；pure-python 6/6 綠；heavy(metal) 紅＝測試不穩定（D-29 已修）；openmm-stack 三 OS 與 heavy(workflow) 仍在跑 | — | session_016gcJzBDnGh3heY9HLWnva3 | 2026-11-02 01:10 | 下一次 04:30 |
| **里程碑：11/02 09:00 使用者在獨顯 Windows 筆電上安裝並跑起來**（1634916：Windows openmm-stack 366 passed、skip 全為設計內、對接／HTS 真跑——CI 條件達成；macOS／heavy 另有紅，見 D-32）——目標 main 全綠（含 `installer-windows`），之後所有 push 不得讓 Windows 紅 | 使用者 | 全部 session | 2026-11-01 23:40 | 本 session 夜間巡檢 CI；紅了修到綠優先於新功能 |
| 監看 CI 並修紅（每 30 分鐘巡檢；里程碑 11/02 09:00 Windows 全綠優先於新功能）：f140a49 起的 openmm-stack 三 OS、heavy、paper-docking | — | session_016gcJz8q2F6515MWPncJEZu | 2026-11-01 | 結果記入 STATUS / DECISIONS（D-24、D-25） |

## 待認領（依重要性）
| 項目 | 來源 |
|---|---|
| 金屬：力常數依元素×配位原子表（鋅偏移部分已認領，見進行中）、配位水納入鍵結、配體配位金屬的距離約束後備 | 同上 §3 |
| umbrella：MBAR overlap matrix 門檻、OpenMM 內建 metadynamics 後備、funnel 約束（研究 tier ΔG°） | 同上 §2 |
| 約束策略智慧建議 `recommend_restraint_strategy`；凍結／口袋截斷／資源估算（分組分階段已完成 D-23；其餘依會診 §1 Q2–Q6） | `docs/specs/restraints_freeze_truncation.md` |
| Vina 執行檔 sha256 表、micromamba 與環境版本鎖定 | REVIEW #19 |
| 戳記改為私鑰簽章（目前只有公鑰加密，不能證明來源） | REVIEW #20 |
| `sampling/runner.py`（無呼叫者）移除或修正 | REVIEW #17 |

## 完成
| 項目 | session | commit |
|---|---|---|
| D-60 未決三項：主鏈穿環、軟核鬆弛第二層修復、協同自由能熱力學循環＋拉離時保持其他配體（D-61） | session_016gcJz8q2F6515MWPncJEZu | 本 commit |
| 多配體同時對接進 MD：穿環／重疊／漂浮檢查、自動改選與微調、指名排除、力場一致性、報告版型 F38–F41（D-60） | session_016gcJz8q2F6515MWPncJEZu | 本 commit |
| 對接多 5 種圖（姿勢相似度、漏斗、位置、接觸殘基、配體比較）＋報告範本（所有圖種，合成資料，CI `report-template` 分支）（D-59） | session_016gcJz8q2F6515MWPncJEZu | 本 commit |
| 圖表豐富度：延伸分析與 32 種圖進結案報告與 GUI 圖表分頁（D-58） | session_016gcJz8q2F6515MWPncJEZu | 9aa78d1 |
| 命令列進度剩餘時間與 ns/day（D-57） | session_016gcJz8q2F6515MWPncJEZu | 04f8a9a |
| 對接盒子過大提醒（D-56；不擋流程） | session_016gcJz8q2F6515MWPncJEZu | 本 commit |
| 發行 **v0.1.0a2**（D-36／37／38／39；verify-windows 含 CUDA dry-run） | session_016gcJz8q2F6515MWPncJEZu | release run 41391866636（5f0945e） |
| Windows 安裝程式發行 **v0.1.0a1**（GitHub Release，prerelease：`MD20-Windows-v0.1.0a1.zip`＋SHA256SUMS；雙擊 `Install-MD20.cmd`；D-33） | session_016gcJz8q2F6515MWPncJEZu | 0bf6954；release run 41365326632（Windows PS 5.1 解壓實裝、刪除解壓資料夾後 doctor/demo 通過才發行） |
| 約束策略修正：分組約束（backbone/sidechain/ligand 單一力 grp 參數）、主要釋放移到 NPT、配體 k 1000、`md.restraints` standard/gentle/hold_backbone、受約束 RMSD 標註（D-23、specs/restraints_freeze_truncation.md §3.1） | session_016gcJz8q2F6515MWPncJEZu | 5cc9295（CI：81b72d9／99c8b64 heavy workflow 與 openmm-stack 三 OS 綠） |
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
