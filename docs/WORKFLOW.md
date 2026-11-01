# 全流程：docking → MD → 結合強度

```bash
md20 pipeline example > my.json          # 產生範本（3PTB trypsin + benzamidine）
md20 pipeline run my.json --project 課堂A # 執行；可隨時中斷，重跑同一指令即從中斷處接續
md20 gui                                  # 或用圖形介面（瀏覽器 http://127.0.0.1:8020）
```

## 設定檔欄位

| 欄位 | 說明 |
|---|---|
| `receptor` | `{"pdb_id": "3PTB"}`（自動從 RCSB 下載）或 `{"file": "my.pdb"}` |
| `ph` | 質子化 pH（受體） |
| `keep_hetero` | 要保留的輔因子／金屬殘基名，如 `["CA", "ZN", "HEM"]`；其餘 HETATM（緩衝鹽、甘油…）自動移除並記錄 |
| `box` | `{"from_residue": "BEN"}` 以晶體配體定義；`{"center": [x,y,z], "size": [sx,sy,sz]}`（Å）；`{"whole_receptor": true}` 盲對接 |
| `ligands` | `[{"name": "BEN", "smiles": "...", "reference_resname": "BEN"}]`；`reference_resname` 用來計算與晶體 pose 的 RMSD（redocking 驗證） |
| `docking.mode` | `independent`：每個配體各自對接並排名；`simultaneous`：多配體同時放進同一 box（joint pose） |
| `pose_choices` | 覆寫推薦：`{"BEN": 3}`；simultaneous 模式用 `{"joint": 2}`（人工選擇不會被短 MD 篩選覆寫） |
| `md.solvent` | `explicit`（預設，TIP3P 水盒）或 `gbn2`（隱式溶劑：原子少 80–90%、全 NVT；金屬位點與結合自由能會被擋下）。篩 pose 可另設 `docking.pose_md_screen.solvent` |
| `docking.protonation` | `auto`（預設）：配體以 `ph` 下的主要離子態對接（羧酸、磺酸、磷酸第一個 OH、四唑、醯基磺醯胺去質子化；脂肪胺、脒、胍質子化；咪唑、羥肟酸等 pKa 接近 7.4 的不改、只註記；已寫成帶電型的基團不動）。HTS 與 MD 用同一結果。`as_given`：照輸入。每個配體也可設 `protonation` |
| `docking.pose_md_screen` | 短 MD 篩 pose：`{"enabled": true, "top_n": 3, "production_ps": 200, "max_rmsd_A": 2.5, "min_contact_retention": 0.5}`；research tier 預設開，其餘預設關 |
| `metal_policy` | 金屬處理（元素或單一位點，位點優先）：`{"ZN": "bonded"}`、`{"ZN:A301": "keep_nonbonded"}`、`{"MG": "remove"}` |
| `md.systems` | `apo`（原始蛋白）、`docked_single`（每個配體一個系統）、`docked_multi`（多配體同一系統） |
| `md.tier` | `classroom`（2 ns）、`teaching`（10 ns）、`research`（100 ns）；`production_ns` 可直接指定 |
| `md.replicas` | 獨立 seed 的重複數（研究建議 ≥ 3） |
| `binding` | `{"enabled": true, "ligands": ["BEN"], "multi": true, "config": {...}}`；`docked_multi` 系統中每個配體會各自從共同口袋拉離（`multi:<配體>`）；config 見下 |

`binding.config`（`BindingConfig`）：`pull_distance_nm`（1.5）、`pull_velocity_nm_per_ps`（0.01）、`k_pull`、`k_umbrella`（1000）、`target_overlap`（0.2）、`window_equil_ps`（10）、`window_prod_ps`（50）、`max_windows`（40）。

## 智慧化處理（每一項都寫進決策日誌）

- **受體**：一律從原始檔重做；docking 處理過的 PDB 不回流 MD。編號跳號（chymotrypsin numbering）以 CA–CA 距離判斷，不誤判為缺失 loop。
- **配體**：化學（鍵序、電荷）只取自 SMILES／SDF；pose 只提供座標，以子結構比對逐原子對應。對不上就停下來說明哪些原子，不猜。
- **Pose 推薦**：最佳分數 1 kcal/mol 內、所屬 cluster 最大的 pose（Vina 分數誤差約 1–2 kcal/mol，搜尋重複找到的結合模式較可靠）；有晶體配體時同時報告 RMSD。
- **simultaneous**：配體間最短距離 < 2 Å 的 joint pose 視為碰撞、不推薦。
- **docked_multi 由 independent 結果組成**：只有選定 pose 彼此距離 ≥ 2.5 Å 才允許，否則停下來請你改用 simultaneous 或改選 pose。
- **短 MD 篩 pose（WP5）**：推薦 pose ＋ 其他通過對接保守條件、不同 cluster 的 pose 各跑一段短 MD；後段配體 RMSD ≤ 2.5 Å 且接觸殘基保留 ≥ 50% 才算穩定。推薦的穩定 → 維持；推薦的不穩定但別的穩定 → 自動改用並記錄；都不穩定或模擬失敗 → 停下來。短 MD 只排除會散開的 pose，不代表結合較強。
- **金屬**：`bonded` 以晶體幾何建立諧和鍵／角、排除金屬–配位原子間非鍵結作用，並把配位的 Cys 改為 CYM、His 依配位的氮決定互變異構體（這是幾何模型，不是 MCPB.py/ZAFF 擬合參數）。少於 3 個蛋白配位原子、配體直接配位、His 兩個氮同時配位 → 停下來。`keep_nonbonded` 會加一個 production 也不解除的位置限制。
- **MD**：watchdog 自動回滾＋縮小 dt；平衡未達標自動延長；電池／PAUSE 檔／時段在 chunk 邊界暫停。
- **結合強度**：SMD 拉出配體 → 依 k、T、目標 overlap 自動規劃 window → 每個 window 可續跑 → WHAM/MBAR PMF ± bootstrap → ΔPMF（含 σ）與 ΔG° 估計（附限制說明）。
- **多配體（WP9）**：共同口袋拉離前先檢查拉離路徑上有沒有其他配體（有就停下）；配體間比較只在同一情境內做，所有配體都有 tier 允許的 ΔG° 才給 ΔΔG°，否則給定性的 ΔΔPMF；差距 < 2σ 判為不可區分；同一配體「單獨 vs 共同口袋」的差值列為共存效應（趨勢，不是熱力學循環）。

## 金屬位點（`metal_policy` 與 `metal_params`）

```json
"metal_policy": {"ZN": "bonded"},
"metal_params": {"ZN": {"source": "hessian", "file": "qm/orca.hess"}}
```
`bonded` 預設用晶體幾何的諧和鍵／角（通用力常數）。建模時會在 `build/metal_qm/<site>/` 產生 QM 小模型輸入（金屬＋配位側鏈、Cα 封端；ORCA 與 Gaussian 兩種），學生用 ORCA 跑 Opt+Freq 後把 `.hess`（或 `.fchk`）指定給 `metal_params`，程式會把 Hessian 轉成金屬–配位鍵／角的力常數並檢查。其他來源：`{"source": "mcpb", "frcmod": "...", "mol2": ["ZN1.mol2", "HD1.mol2", ...], "pdb": "xxx_mcpbpy.pdb", "charges": true}`（轉譯 MCPB.py 輸出，含 RESP 電荷）、`{"source": "json", "file": "params.json"}`（`bonds` 以 `HIS94:NE2`／原子名／元素為鍵，`angles.default`，`charges`）。相對路徑以工作流程資料夾為準。開殼層金屬要加 `qm_charge`、`qm_multiplicity`。

## 需要人工決定時

流程停在 `NEEDS_HUMAN`，訊息會列出閘門與選項。GUI 的「閘門」分頁對程式能執行的選項提供一鍵按鈕（需要理由的選項要先填理由），按下後設定寫回 `config.json`、決策記入日誌、從該步驟起重跑；換結構、改序列、QM 參數等選項只列為「需要在程式外處理」。CLI 則把選擇寫進設定檔後重跑同一指令（受體閘門目前只接受 `hetero groups` 的移除／保留，其他選擇會維持擋關）：

```json
"human_choices": {"receptor": {"hetero groups": "全部移除（預設）"}},
"pose_choices": {"BEN": 2}
```
