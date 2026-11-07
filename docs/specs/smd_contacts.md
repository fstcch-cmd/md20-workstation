# SMD 路徑與接觸釋放（F13，D-116）

狀態：**[已實作・待 CI]**（2026-11-07）。純 numpy 的分析與報告有 22 項合成資料測試；真實 OpenMM 拓撲上的座標記錄待 CI。

## 1. 問題
SMD 報告只有拉力與功對距離的曲線。學生看到力的峰值，不知道峰值那一刻斷了哪些配體–殘基接觸。

## 2. 做法
1. **記錄**（`sampling/binding.py`，不改協定）：拉離迴圈已每 0.2 ps 取一次座標算 CV；每 `ceil(n/200)` 筆多存一幀（含最後一幀），內容是配體重原子與口袋附近、出口路徑上的蛋白殘基重原子（不含水），寫成 `smd_path.npz`。
2. **分析**（`analysis/smd_contacts.py`）：接觸 = 重原子最小映像距離 < 0.40 nm（同 `interactions.SEARCH_NM`），殘基層級。釋放點 = 最後一次存在那一幀的 CV d。力峰值 = 平滑後最大處的配體 d。釋放點在峰值 d ± 0.05 nm 內 → 「峰值時斷開」。
3. **報告**：圖 `smd_contacts`（x = d，一列一個接觸）與「峰值時斷開的接觸」表，四語。

## 3. 結果欄位（`BindingResult.smd_contacts`、`smd_contacts.json`）
`status`（ok／limited／unavailable）、`reason_code`、`peak`（d、時間、力、是否可定位）、`frames`（d、時間）、`contacts[]`（residue、initial、first_d_nm、released、release_d_nm、offset_from_peak_nm、category、runs、closest_pair_at_first）、`at_peak[]`、各類計數、`capture`、`caveat_codes`。

## 4. 誠實界線
- 沒有 `smd_path.npz` 就是「無法進行」，不從力曲線或窗口起始幀推測。
- 只追蹤擷取到的殘基；沿出口直線以外的新接觸看不到；不含水。
- 力峰值與釋放點屬於這一次拉離，隨拉速與彈簧硬度改變；不排序作用力強弱，不是自由能（D-96）。
- 接觸是距離判定，不是氫鍵或鹽橋；與多標籤指紋（`interactions.py`）的對照尚未做。

## 5. 待驗證與審查問題
- CI 真實 binding 路徑是否產生 `smd_path.npz`、分析狀態是否為 ok。
- 擷取半徑 0.8 nm 與路徑邊界 0.6 nm 是否足夠；多個力峰時的逐峰對應；replica 間一致性。
