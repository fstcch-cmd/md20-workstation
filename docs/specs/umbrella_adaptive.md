# 傘狀採樣：智慧補窗（由粗到細）、即時覆蓋圖、手動補採樣

狀態：**[已實作・待 CI]**（2026-11-01，第三個 session）。純 Python 測試 14 個通過（`tests/test_adaptive_windows.py`、
`tests/test_umbrella_manual.py`）；真實 OpenMM 的 SMD＋umbrella 路徑（`test_binding_integration`、全流程）待 CI。

## 1. 問題
Colab 版與本專案舊版的 umbrella sampling 常出現**取樣不連續**：合併所有 window 的 CV 直方圖有空洞，WHAM/MBAR 把兩段
PMF 以任意常數接起來，圖上出現台階或斷點，ΔPMF/ΔG° 失真。

舊版補窗規則（`binding.py` 先前版本）：
- 只看相鄰 window 的重疊，不足就在**兩個中心的中點**插一個 window；
- 所有 window 用**同一個 k**；
- 最多 2 輪、每輪 6 個。

## 2. 原理：為什麼中點補窗會失敗
偏壓 window（中心 c、彈簧 k）在自由能 F(r) 上的平衡位置 μ 滿足

  F′(μ) + k(μ − c) = 0  ⇒  μ − c = −F′/k

也就是 **window 會被自由能斜率往下坡推 F′/k**。在陡的地方（結合口袋出口的牆），k = 1000 kJ/mol/nm²、
斜率 200–500 kJ/mol/nm 時，漂移 0.2–0.5 nm，遠大於 window 寬度 σ = √(kT/k) ≈ 0.05 nm。結果：
- 實際的空洞位在兩個**取樣分佈**之間，而不是兩個中心之間；
- 中點插入、相同 k 的新 window 會滑到同一側，空洞仍在；
- 在能障頂端（F″ < 0），若 k < |F″|，window 會往兩邊滑，形成雙峰分佈——它與兩側鄰居的重疊都「夠」，
  但頂端一個樣本都沒有。**只看相鄰重疊會漏掉這種斷點。**

## 3. 演算法（`md20/sampling/adaptive.py::plan_refinement`）
每一輪：
1. **依實際取樣平均 μ 排序**（不是依中心），每個 window 估計 μ、σ、有效樣本數 n_eff（統計無效率 g）、
   漂移 μ − c、局部斜率 F′ ≈ −k(μ − c)。
2. **延長而不複製**：n_eff 不足的 window 從它的最後一幀接著跑（不重新平衡），不另加 window。
3. **相鄰重疊不足（< 目標 0.2）**：空洞 = μ_L+σ_L 到 μ_R−σ_R。
   - k_new = max(min(k_L,k_R), slope²/(4kT))，上限 k_max = 5000——只硬化到漂移 ≲ 2σ；直線斜坡上漂移後的分佈仍是完整高斯，
     不需要更硬（實測：用「漂移 ≤ σ/2」的規則會把 k 頂到上限、window 數暴增，屬於過度採樣）。
   - 需要的 window 數 n = ⌈(μ_R−μ_L)/Δ⌉ − 1，Δ = 達到目標重疊的間距 = 2σ·Φ⁻¹(1−OVL/2)。**大缺口一輪就補多個**（由粗到細）。
   - 中心預先往上坡移 F′/k_new（每輪 ≤ 1σ；兩點斜率估計放太大會過衝，實測 3σ 會讓陡牆案例失敗）。
4. **合併直方圖才是真相**（`continuity_report`）：120 格、低於中位數 10% 的連續格子 = 斷點
   （取樣密度低 10 倍 ⇒ PMF 額外誤差 ≳ kT·ln10）。對每個斷點：
   - 斷點內已經放過 window（它滑走了）→ k 直接跳到 k_max（不慢慢加倍浪費輪次）；
   - 已在 k_max 仍有斷點 → 標記 `unsamplable`，**不再加 window**，報告「能障曲率比彈簧陡」。
5. **CV 範圍端點**沒被取樣 → 補端點 window。
6. 依缺口大小排序（大的先補），每輪上限 12、總上限 60。
7. 停止：所有相鄰重疊 ≥ 目標、合併直方圖無斷點、所有 window 有效樣本足夠；或預算用盡（列出剩餘缺口）。

新 window 的起始結構（`binding.py::start_for`）：取**實際取樣平均**最接近目標的已完成 window 的最後一幀，或最近的 SMD 幀。

WHAM 與 MBAR 改為接受**每個 window 各自的 k**（`_mdh_legacy._k_column`），PMF、bootstrap、前後半收斂都用 per-window k。

## 4. 實測（合成自由能剖面，精確偏壓取樣；起始 9 個粗 window，0.45–1.6 nm）

| 剖面 | 舊規則 | 新規則 |
|---|---|---|
| 平滑牆（200 kJ/mol/nm，0.3 nm） | 13 window，連續，PMF 最大誤差 1.34 | 20 window，連續，0.63 |
| 陡牆（500 kJ/mol/nm，0.12 nm）——Colab 症狀 | 13 window，**斷點 0.50–0.68 nm**，最大誤差 4.19 | 25 window，連續，0.76 |
| 去溶劑化能障（12 kJ/mol，寬 0.1 nm） | — | 連續，最大誤差 < 1.5 |
| 非物理尖峰（60 kJ/mol 於 0.06 nm，F″≈33000 > k_max） | 斷點 | 斷點，**明確回報補不起來並停止**（≤ 30 window） |

誠實說明：平滑剖面上舊規則其實就夠用；新規則多用約 50% window 換來較小誤差。目標重疊 0.15 時陡牆補不連續，所以預設 0.2。

## 5. 即時覆蓋圖與手動補採樣
- `run_binding` 每完成一個 window 就重寫 `binding/<target>/coverage.json`（`coverage_view`：每個 window 的直方圖、合併計數、斷點、補窗紀錄）。
- GUI「傘狀採樣覆蓋」分頁每 2 秒讀取：面積 = 合併樣本、細線 = 各 window、紅色 = 斷點；摘要列出補窗輪次與補不起來的區段。
- 手動補採樣：使用者輸入「從 a 到 b nm」（可選 k、備註）→ `actions.resample_range` → `plan_range`：
  - k：使用者指定；否則若區間內仍有斷點 → max(2×該處最硬的 k, slope²/4kT)；否則依斜率；
  - 中心預先往上坡移 F′/k（≤ 3σ，因為只有一次機會）；
  - 寫入 `binding.manual_windows[<target>]`，**只重開這個目標**（其他目標的結果保留），已完成 window 不重跑，
    之後自動補窗繼續，PMF 重算；記人工決策。
- PMF 若仍不連續：報告列出斷點、**不輸出 ΔG°**，並提示可手動補採樣或提高 `k_umbrella_max`。

## 5b. 續跑與冪等（D-16）
補窗進度存在 `refine_log.json`（每輪 `completed`）與 `refine_state.json`（`finished`、手動 window 簽章、起始輪次）。
續跑從下一個未完成輪次接續；已結束則不再規劃（否則以擴大後的樣本重規劃會再加 window、改變已完成的 PMF）。
新的手動補採樣請求會重新開啟補窗，給一份新的 `max_refine_rounds` 預算。

## 6. 設定（`binding.config`）
`target_overlap` 0.2、`k_umbrella` 1000、`k_umbrella_max` 5000、`max_refine_rounds` 6、`max_new_per_round` 12、
`max_windows` 40、`window_equil_ps`、`window_prod_ps`、`sample_every_steps`；手動：`binding.manual_windows`。

## 7. 已知限制
- 斜率由相鄰 window 漂移估計；在曲率劇變處（扭結）估計偏差大，靠多輪迭代修正。
- 能障曲率 > k_max 時無法連續；可提高 k_max（σ 變小，需更多 window）或改用其他增強取樣（metadynamics / REST2），本版不做。
- 一維 COM 距離 CV；配體方向／構形變化不在 CV 內（ΔG° 未做方向限制校正，見 STATUS）。
- 延長 window 的樣本與前段直接串接（假設已平衡）；未重新做平衡偵測切割。

## 8. 想請審查者回答
1. 目標重疊 0.2、斷點門檻「中位數 10%」是否合理？有沒有更好的連續性判準（例如以 MBAR 的 overlap matrix 特徵值）？
2. k 的選擇規則 k ≥ slope²/(4kT)（漂移 ≤ 2σ）是否有更好的理論依據？是否應改成依 F″ 估計（需要三個以上 window）？
3. 中心預偏移：自動 ≤1σ、手動 ≤3σ 的上限是經驗值；有沒有更穩的作法（例如以前一輪的 μ(c) 關係做局部線性反解）？
4. 延長 window 時是否應重新做 equilibration detection？
5. 是否應加入「Hamiltonian replica exchange between windows」作為補窗失敗時的後備？
