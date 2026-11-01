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

## 內建驗證／教學案例（HCC Lab 論文）

用 `md20 validate <case>` 產生設定檔，再 `md20 pipeline run <file>` 跑完整流程。兩個案例刻意各自示範一個常見錯誤，正好對應 MD20 的閘門。

| 案例 | 論文 | 標的 (PDB) | 配體 | 示範重點 |
|---|---|---|---|---|
| `hsieh2024` | J. Ethnopharmacol. 318 (2024) 116980 | NF-κB RELA/p65 | 六個水萃代謝物（多配體同時對接） | 論文標註 1VKF，但 1VKF 其實是 *Thermotoga* 甘油操縱子蛋白；MD20 以座標比對判定正解為 **1VKX**（結構可信度閘門） |
| `hsieh2025` | LWT 222 (2025) 117641 | Keap1-BTB (4CXT) | 胜肽 GRP = GGGGGKP | 胞內標靶但胜肽淨電荷僅 +1，**CPP 閘門擋下**並提出替代設計；論文稱的「covalent bonding」其實是凡得瓦接觸 |

重點：這些案例的目的不是「重現論文數字」（exhaustiveness、質子化、亂數種子未公開，無法逐位重現），而是示範**先把科學假設與結構品質把關做好，再談對接分數**。

### CPP（穿膜胜肽）無法通過時

對胞內標靶，若胜肽依序列特徵預測無法穿膜，MD20 會擋下流程並視為**科學假設問題**（不是計算設定問題），同時提出三類具體替代設計，並以同一啟發式評分排序：

1. **縮短為帶電核心**：去掉 Gly 填充，保留帶電殘基（如 GGGGGKP → `GKP`、`KP`）。
2. **富集 Arg/Lys**：把填充 Gly 換成 K/R，使淨電荷 ≥ +3（如 `GGGKKKP`）。
3. **接穿膜載體**：N 端融合 TAT／R8／penetratin。

報告並列出外部 CPP 預測工具（BIOPEP-UWM、CellPPD、CPPpred、MLCPP 2.0）供交叉確認——內建評分只是初篩，不能取代實驗或外部預測。要在未驗證穿膜性的情況下仍繼續，於該配體設定 `cpp_override` 並說明理由（報告會標註）。
