# 軌跡分析工具箱（中期藍圖第 1 階段，D-105）

狀態：**[已實作・待 CI]**（純 numpy 部分容器已測；mdtraj 接線交 CI `openmm-stack`）。

## 盤點：藍圖第 1 階段哪些已經有
藍圖把「PCA、分群、二維自由能面、SASA、DSSP、氫鍵、DCCM」列為缺，實際上 D-58 的 `analysis/extended.py` 早已計算並進報告（PCA＋FEL、GROMOS 分群、DCCM、蛋白 SASA、DSSP、蛋白內氫鍵數、配體氫鍵／指紋／水橋／埋藏度）。真正缺的是下列四項，本次補上（`md20/analysis/toolbox.py`）。

| 功能 | 演算法 | 輸出 | 誠實限制 |
|---|---|---|---|
| tICA | Cα 座標 → PCA 取前 k（≤ 10、≤ 幀數/20）→ 標準化 → 對稱化延遲共變異，C(τ)v = λC(0)v；t = −τ/ln λ | `ext["tica"]`：投影、特徵值、時間尺度（ns）、延遲、FEL | 幀數 < 10τ 或 < 30 → `insufficient`；延遲取候選（0.05–2 ns）中位數 |
| MSM | tICA 前兩維 k-means（k = 幀數/50，5–30，seed 固定）；各延遲計數、最大強連通集合、(C+Cᵀ)/2 對稱化估計；隱含時間尺度 | `ext["tica"]["msm"]`：lags、its、stationary、eligibility、its_flat | `insufficient`（轉換 < 10×狀態或連通 < 90%）、`unresolved`（最慢 > 模擬 1/3）、`exploratory`；**單一軌跡永不報速率**；估計器不是 MLE，已註明 |
| 氫鍵網路 | Wernet–Nilsson 每幀，排除兩端都是骨架原子（N、O、OXT、H）的鍵；殘基對佔幀 ≥ 30% 成邊 | `hbonds_protein.network`：edges、hubs、components（≥ 3 殘基） | 只有 ≤ 100 幀（沿用既有抽樣） |
| 水合位點 | 配體質心 1 nm 球內 0.1 nm 格點水氧密度 ÷ 體相（33.4 nm⁻³）；局部極大 ≥ 2×、0.2 nm 內合併；佔有率 = 有水氧在 0.14 nm 內的幀比例 | `ligands[rn].hydration.sites` | 只存溶質的 DCD → `no_water`，報告寫「無法分析」 |

## 報告
- 圖：`tica_landscape`（軸 tIC1/tIC2，無變異比例）、`msm_its`（灰色＝短於延遲無法解析；虛線＝模擬三分之一）。四語說明見 `report/figure_text.py`；規範見 `report_language.md` F19a/F19b。
- 表：持續的側鏈氫鍵（前 15）＋連結最多的殘基；配體水合位點（密度比、佔有率、離中心距離）＋八成時間有水的位點數。

## 測試
`tests/test_toolbox.py`（tICA 找慢座標而非變異大的座標、短輸入拒絕、k-means 決定性、MSM 還原已知時間尺度 ±25%、罕見事件標為 insufficient/unresolved、網路邊／中心／連通、水合找到結合水且不把體相雜訊當位點）；`tests/test_extended_analysis.py`（CI mdtraj）；報告範本涵蓋所有圖種。

## 審查問題
1. 對稱化計數估計 vs 可逆 MLE：教學版先用簡單、可解釋的版本，是否足夠？
2. 水合位點 2× 體相門檻與 1 nm 半徑是否合適（GIST／WATsite 常用更細格點）？
3. 是否要加 Chapman–Kolmogorov 檢驗（需粗粒化成巨狀態，PCCA+）？

## 系統之間的比較（D-106，A11／F12／F10）
- 可比性欄位：溫度、系綜、正式模擬約束群組、水模型、力場 XML、溶劑、HMR 相同；長度差 ≤ ×1.25；未知即不可比。
- 共同基底：共有 Cα（鏈:殘基號）、迭代 Procrustes、一次 PCA、同一格子；每低谷一個實際代表幀；前後半低谷比例差 > 20% → 「取樣分布，非收斂地形」。
- ΔRMSF：殘基名＋號對應（HID/HIE/HIP→HIS、CYX/CYM→CYS、ASH→ASP、GLH→GLU、LYN→LYS），條件不可比時拒絕。
- 審查問題：20% 的前後半門檻是否太寬？共同基底是否應排除柔性末端（目前不排除，末端擺動可能主導 PC1）？
