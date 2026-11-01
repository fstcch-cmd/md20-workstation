# 週期邊界歸零（立體歸零）：錨定、影像校正、視覺性解離閘門

狀態：**[已實作・待 CI]**（2026-11-01）。純 numpy 核心 `md20/analysis/pbc.py` 有 6 個本地測試；mdtraj 路徑由 `test_full_workflow_3ptb` 驗證。

## 1. 問題（使用者痛點）
MD 跑完後「中心跑掉、看起來跑出盒子、配體像是解離了」。成因是三件互不矛盾的事：
- `CMMotionRemover` 只移除**整個系統**的質心運動；蛋白在水裡擴散是物理，長時間可以穿過整個盒子。**不能用力把它拉回來**，那是改物理。
- `DCDReporter(enforcePeriodicBox=True)` 把**每個分子各自**折回主盒：蛋白跨過邊界時會「跳到另一邊」，貼在它邊上的配體／第二條鏈／胜肽被折到對面。
- 舊分析用 `mdtraj.image_molecules()` 不指定錨：mdtraj 以「鍵連通」定義分子並自己猜錨（最大者），**多鏈蛋白的第二條鏈、胜肽配體、金屬離子都是獨立分子**，可能被放到錯的影像 → 接觸數歸零、RMSD 暴增、`stays_bound=False`。分析錯，模擬沒錯。

## 2. 規則（`center_trajectory` / `recenter_frame`）
1. **錨 = 所有蛋白鏈 ＋ bonded 金屬**（從 build manifest `restraints.metals.plans` 取 `metal_index`，不讓程式猜）。錨分子各自補完整，並以第一條鏈為準聚攏（只平移整數個盒向量）。
2. **其他分子**（配體、胜肽、離子、水）補完整後，移到**質心離錨質心最近**的影像（用質心做最小影像，不是逐原子）。
3. 錨質心平移到盒中心；分析版再做 Cα superpose。
4. 輸出兩個檔：`analysis/production_centered.dcd`（＋ `.pdb`；只歸零不旋轉，給 VMD／學生）與 `production_aligned.dcd`（Cα 對齊，RMSD 用）。可重現包含前者。
5. **誠實閘門** `apparent_vs_true_distance`：最後一幀配體–口袋質心距離，原始 vs 歸零後差 > 0.5 nm → 決策日誌記「視覺性 PBC 假象，已修正」（AUTO_FIXED）；歸零後仍遠才是真解離，由既有 `stays_bound` 判。

## 3. 不做的事
- 不在模擬中加任何約束或「歸零力」。
- 非正交盒：純 numpy 版只取對角；mdtraj 路徑（實際使用）處理三斜盒。

## 4. 驗證
- 本地（合成座標）：蛋白跨邊界補完整並置中；第二條鏈與胜肽被折到對面後回到 0.4／0.1 nm；真解離（1.8 nm）不被遮掩；bonded 金屬屬於錨；分支分子補完整。
- CI：3PTB 全流程每個 run 都有 `production_centered.dcd`，`BEN` 的 `true_nm < 1.0`。

## 想請審查者回答
1. 「差 > 0.5 nm 判為假象」門檻是否合理？
2. 多配體系統裡，配體彼此是否也該互相錨定（目前各自以蛋白為準，兩個配體若跨邊界相鄰會各自正確）？
