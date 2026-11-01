# 課程使用建議（博士班，12 週）

| 週 | 主題 | 指令／頁面 | 繳交（自動產生） |
|---|---|---|---|
| 1 | 環境與硬體：為什麼 GPU 重要 | `md20 doctor` | Doctor 報告、ns/day 與 tier 選擇理由 |
| 2 | 結構準備：PDB 為什麼會壞 | `md20 build`（閘門） | 閘門報告：每個 AUTO_FIXED 的 diff 與理由 |
| 3 | 力場與參數化：OpenFF / NAGL / GAFF | 配體煙霧測試 | 參數覆蓋與電荷檢查 |
| 4 | Docking 原理與驗證 | `pipeline`（independent） | redocking RMSD、pose 推薦理由 |
| 5 | 多配體：simultaneous vs independent | `pipeline`（simultaneous） | joint pose 與碰撞判斷 |
| 6 | MD 流程：最小化→NVT→NPT→production | `md20 run` | run 報告（方法段落、驗收表） |
| 7 | 收斂與重複：為什麼要 ≥ 3 replica | `queue add --replicas 3` | replica 彙總 mean ± SD |
| 8 | 軌跡分析：RMSD/RMSF/接觸/氫鍵 | workflow 分析 | apo vs holo 疊圖、口袋接觸頻率 |
| 9 | SMD：不可逆功與拉力 | binding（SMD） | 力–距離曲線，討論拉速影響 |
| 10 | 傘狀採樣與 WHAM/MBAR | binding（umbrella） | overlap 直方圖、PMF ± 誤差 |
| 11 | 自由能的層級與限制 | 報告 caveats | ΔPMF vs ΔG° vs 實驗值的討論 |
| 12 | 專題 | 全流程 | 可重現包 + workflow 報告 |

教學 tier 在 GTX 1060 級筆電（約 200 ns/day 水盒基準）上，一個蛋白–配體系統的 10 ns 約 2–4 小時；純 CPU 筆電建議 classroom tier 並排夜間佇列（`md20 queue run --hours 22-7`）。
