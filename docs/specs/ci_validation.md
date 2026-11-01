# CI 架構、驗證案例與這幾輪抓到的問題

## CI（`.github/workflows/ci.yml`）
- `pure-python`：Windows/macOS/Linux × Py3.11/3.12，不需 OpenMM；必綠門檻。
- `openmm-stack`：三個 OS 以 micromamba 建真實環境（OpenMM、RDKit、OpenFF、Vina）。Windows = 使用者主力平台（OpenCL/CPU）。
  Ubuntu 帶 `MD20_HEAVY=1` 跑重測（3PTB 全流程含 SMD/umbrella、短 MD 篩 pose、金屬、NaCl PMF）。
  測試步驟上限 100 分（Ubuntu 重測實測約 62 分）；pytest `faulthandler_timeout = 900` 會印出卡住測試的堆疊；`-vv`。
- `heavy`（D-19）：Ubuntu 平行 3 組（workflow／pose-screen／metal），`MD20_HEAVY=1`，各自貼留言。
- `paper-docking`：兩篇論文的對接重現（數小時 Vina），獨立、`continue-on-error`、exhaustiveness 8，結果 JSON 貼 commit 留言。
- 所有結果、失敗 log、驗證 JSON 由 CI 貼到該 commit 的留言。

## 第一次完整跑完 Ubuntu 重測後抓到的真 bug（2026-11-01）
這些重測在第二個 session 寫好，但之前每輪都被取消或被論文對接卡住，**從沒跑完過**：
1. 重複原子名閘門把 altloc A/B 算成重複 → 3KS3 被擋（修：以 (原子名, altloc) 計數）。
2. `DockingResult.load` 讀到戳記欄位 `_md20` 就當掉（修：只取已知欄位）。同類：`windows_k.json`。
3. 2 ps 的篩選 stage 只記 4 筆 log 無法驗收，且引擎用 +0 ps「延長」兩次（修：短 stage 自動加密記錄 ≥ 20 筆；延長無效時直接 NEEDS_HUMAN）。
4. workflow 讀錯鍵 `pull_distance`（實為 `pull_distance_nm`）→ padding 一律 2.0 nm，且套到 apo 與篩選系統（修：只對要拉離的系統、用正確鍵）。
5. 幾何鋅模型守不住配位（見 metal_sites.md）。
6. `setup-vina` 被 GitHub API 未登入限流（403）→ 帶 token + 固定版本 release 直接下載後備；CI 以 HEAD 驗證固定檔名存在。

## 論文驗證案例
- **hsieh2025**（Keap1 4CXT，胜肽 GGGGGKP）：第 1 名 −5.91 kcal/mol（論文 −5.22），接觸殘基 recall 100%。CPP 閘門擋下（淨電荷 +1，胞內標靶）並給替代設計。
- **hsieh2024**（NF-κB，六配體同時對接）：論文印的 PDB 1VKF 是 *Thermotoga* 蛋白；以殘基存在性判定應為 1VKX（11 個報告殘基中 9 個存在）。
  在 1VKX 用論文盒子對接：聯合分數 −11.7（論文 −13.86），但六個配體全落在 563–634 號殘基一帶，與論文殘基 recall 0；
  系統拒絕推薦（口袋約 107 Å³ vs 六配體約 1386 Å³）。
  **不可重現原因（37bc6b1 的 `test_hsieh2024_box_hypotheses` 實測，已確定）**：論文的 Vina 盒子很可能是把
  AutoDockTools 的**格點數 76×92×70 直接填進 Vina 的尺寸欄**（Vina 單位是 Å），實際搜尋 76×92×70 Å——幾乎是盲對接。
  證據：
  | 盒子尺寸解讀 | 1VKX 盒內殘基 | 框到的報告殘基 |
  |---|---|---|
  | 論文 Å 值 28.5×34.5×26.25（= 76×92×70 格 × 0.375） | 74 | 0 / 11 |
  | 格點數當 Å：76×92×70 Å | 500 | 9 / 11（其餘 2 個不在結構中 → 全部） |
  | Å 值又當格點 ×0.375 | 5 | 0 |
  盒子中心在 1VKX 中距最近原子 0.48 Å（B 鏈 Asp597/Phe598），是有效座標；在 1VKF 中距任何原子 39.6 Å（蛋白外），
  所以中心**不是**來自 1VKF（先前「中心來自其他座標系」的推論錯誤，已更正）。報告殘基全在 A 鏈（p65），距中心 29 Å。
  使用者先前提出的「Vina 與 AutoDock 4 格點間距（1 Å vs 0.375 Å）」假設方向正確：混淆的是 ADT 格點數與 Vina 的 Å 尺寸。
  教學含意：同一中心、尺寸差 2.67 倍（體積約 19 倍）就從「口袋對接」變成「近盲對接」，配體落點與分數完全不同；
  MD20 應在盒子任一邊 > 40 Å 時擋關並詢問是否為格點數誤填（待實作，見 REVIEW_QUESTIONS）。

## 想請審查者回答
1. 論文重現用 exhaustiveness 8 是否足以下結論？要不要改成多 seed 的小 exhaustiveness 取最佳？
2. 重測 62 分鐘：是否應拆成多個平行 job（全流程、篩 pose、金屬、PMF 各一）？
