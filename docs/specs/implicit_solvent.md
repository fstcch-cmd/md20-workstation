# 隱式溶劑（GBn2）

狀態：**[已實作・待 CI]**（D-20，會診 §1 Q6）。真實 OpenMM 測試 `test_real_case_integration.py::test_3ptb_gbn2_implicit_solvent_short_md`
在 openmm-stack 三個 OS 執行。

## 為什麼
MD 成本約 80–90% 在水。筆電上唯一「真的快很多」又不需要截斷蛋白的選項是隱式溶劑：不加水與離子、無週期盒、無 PME，
原子數少 80–90%（3PTB：顯式水 0.8 nm padding 約 1.5 萬原子 → GBn2 約 3300 原子）。

## 設定
- `md.solvent: explicit | gbn2`（預設 explicit）。
- `docking.pose_md_screen.solvent`：短 MD 篩 pose 可以單獨用 gbn2（只問 pose 會不會散開，最適合）；未設時跟隨 `md.solvent`。
- 預設**尚未**改成 gbn2：等 CI 在三個 OS 驗證後再決定是否把篩 pose 的預設改為 gbn2（會另記決策）。

## 實作
- 組裝（`build/assemble.py`）：不 `addSolvent`；`createSystem(NoCutoff, HBonds)`；`add_gbn2_force`＝OpenMM 內建
  `GBSAGBn2Force`（Nguyen, Roe & Simmerling 2013，igb=8），半徑 mbondi3 依元素與鍵結指派（`getStandardParameters`），
  所以 OpenFF/GAFF 配體也有參數（`implicit/gbn2.xml` 只涵蓋 Amber 蛋白殘基樣板）；電荷取自 NonbondedForce；表面積項 ACE；鹽 κ = 0。
- `make_nonperiodic`：位置約束的 `periodicdistance` 改寫成一般距離、質心力關閉 PBC，否則 OpenMM 會把系統當週期系統。
- 閘門：總電荷不中和（淨電荷是正常的，只檢查是否為整數）；水比例檢查略過。
- Protocol（`implicit_solvent_protocol`）：NPT stage 改 NVT（約束釋放排程保留），拿掉密度驗收；只在 gbn2 時套用，顯式水的 protocol 雜湊不變。
- 引擎：非週期時記錄器不報體積／密度、DCD 不包裹；分析不做 PBC imaging。

## 擋下的情況（NEEDS_HUMAN，GUI 可一鍵改回顯式水）
- **金屬位點**（非 remove）：沒有水配位與屏蔽，+2 金屬會把位點拉扭。
- **結合自由能（SMD／傘狀採樣）**：去溶劑化能障在連續介質下失真。

## 已知限制
- 摩擦係數沿用 1/ps（構形取樣較快、動力學時間尺度不真實）；GB 結果不能與顯式水結果直接比較。
- 水橋接的結合（口袋結構水）無法表現。
- κ = 0（未模擬鹽屏蔽）。

## 想請審查者回答
1. 篩 pose 預設改 gbn2 的門檻：CI 驗證通過即可，還是要先在 3PTB/幾個案例比對 GB 與顯式水的篩選判定一致率？
2. GB 下的摩擦係數是否應提高（例如 5/ps）以避免過快的構形漂移造成誤判「不穩定」？
