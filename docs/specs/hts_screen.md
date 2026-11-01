# 高通量前期篩選（HTS screen）— 規格

> 角色：在正式對接之前，讓使用者一次拿 100–500 個化合物做快速對接，看圖挑出要進 MD 或多配體同時對接的配體。
> 原則不變：不新增 phase，篩選是 **docking 步驟的前置過濾**；每個自動決策都進 `DecisionLog`；寧可擋也不要猜。

## 1. 輸入：化合物庫（Excel / CSV）

`screen.library` 指向一個 `.xlsx`／`.xls`／`.csv`／`.tsv`。欄名不分大小寫，接受別名：

| 欄位 | 別名 | 說明 |
|---|---|---|
| `name` | id, compound, ligand, 名稱 | 必填；會經 `safe_name` 轉成檔名，**轉換後不可重複** |
| `smiles` | smi | 2D → RDKit ETKDG 建 3D（與現有 `dock()` 相同路徑） |
| `pubchem_cid` | cid, pubchem | PubChem PUG-REST 3D SDF（`record_type=3d`；沒有 3D 時退回 2D SDF 再由 RDKit 建 3D，並記錄） |
| `inchikey` | inchi_key | PubChem 以 InChIKey 查 CID → 同上 |
| `chembl_id` | chembl | ChEMBL API 取 canonical SMILES |
| `ccd` | pdb_ligand, ligand_id, het | RCSB 配體辭典 ideal SDF（`<CCD>_ideal.sdf`） |
| `sdf` | file, path | 本機 SDF／MOL（相對路徑以庫檔所在資料夾為準） |

每列至少要有一個識別欄；**來源優先序** `sdf > smiles > pubchem_cid > inchikey > chembl_id > ccd`。
以「化合物名稱」查 PubChem 是可能查錯分子的操作，預設**不做**；`screen.allow_name_lookup: true` 才啟用，且每筆都記 decision（kind=human）並在報告標註。

下載：`urllib`、逾時 30 s、失敗重試 3 次（指數退避、尊重 `Retry-After`）、PubChem 每秒 ≤ 4 次請求、固定 User-Agent。
所有下載結果快取在 `<workflow>/screen/library/<name>.sdf`，重跑不重抓；`library_manifest.json` 逐筆記錄 `status`（`OK` / `FAILED` / `SKIPPED`）、來源、錯誤訊息。

下載後檢查（有 RDKit 時）：可解析、取最大片段（去鹽，記 decision）、重原子數與分子量落在 `screen.filters`
（預設 heavy 5–80、MW 100–900，超出 → `SKIPPED` 並說明）、以 InChIKey 偵測重複（重複 → `SKIPPED`，指向保留的那筆）。
沒有 RDKit 時只存檔、`checked: false`。

## 2. 篩選對接

對每個 `OK` 的化合物呼叫既有 `dock(mode="independent")`，受體 PDBQT 只轉一次（`dock(..., receptor_pdbqt=...)`）。
預設 `exhaustiveness 8`、`n_poses 3`（**縮減搜尋**，報告與 JSON 標明）。
單一化合物失敗（Meeko 拒絕、Vina 錯誤…）→ 記 `FAILED` 與例外訊息，**繼續**下一個；
每做完一個就原子寫入 `screen_results.json`，所以中斷後重跑只做還沒做的。`progress_cb` 回報 `i/n`、平均秒數與 ETA。

## 3. 排名與圖

`rank_screen()` 產生 `screen_ranking.csv` 與圖（PNG 300 dpi + SVG；GUI 用 ECharts 同資料）：

* `score`：該化合物最佳 pose 的 Vina 分數；`ligand_efficiency = −score / 重原子數`；
* `cluster_size`、`contacts`、系統推薦狀態（沿用保守推薦規則）；
* `indistinguishable`：與第 1 名差距 < 1.0 kcal/mol 的化合物標記「在 Vina 誤差內，排名順序無統計意義」。

圖：分數分佈直方圖；分數 vs 重原子數散點（LE 參考線 0.3 kcal/mol/重原子）；前 N 名長條（著色為推薦狀態）。
**誠實標註**：篩選分數是縮減搜尋的 Vina 分數，不是結合自由能，只能用來「剔除」而不是「證明」。

## 4. 選擇閘門（三態）

* 任何 `FAILED`／`SKIPPED` 且 `screen.allow_partial` 不為 true → `screen_docking` **NEEDS_HUMAN**，列出失敗清單，選項：修正庫檔重跑／`screen.allow_partial: true`（報告標註缺漏）。
* `screen.select` 為空 → `screen_selection` **NEEDS_HUMAN**：GUI「篩選」分頁勾選化合物，按「進入 MD（各自對接）」或「多配體同時對接」，寫回
  `screen.select` 與 `screen.next_mode`，並自 `docking_preflight` 起失效重跑。
* 有選擇 → 選中的化合物以 `{name, sdf, smiles}` 併入 `ligands`（保留使用者原本明列的配體，例如共晶參考配體），`docking.mode = next_mode`，
  之後走**原本**的 docking → pose 選擇 → MD。`simultaneous` 至少 2 個，否則擋。

## 5. 續跑與失效

* `screen_library` 完成紀錄以庫檔的 `cheap_fingerprint` 為鍵；檔案改了就重讀（已下載的 SDF 仍重用）。
* `screen_docking` 以 library 指紋 + box + 篩選參數為鍵。
* `STEP_ORDER`：`screen_library, screen_docking, screen_selection` 排在 `docking_preflight` 之前。

## 6. 測試

純 Python：庫檔解析（別名、缺識別欄、重名）、假 `fetch` 的下載器（成功／503 重試／失敗記錄／快取重用／名稱查詢預設關閉）、
排名與圖檔產生、workflow 以假 `dock` 跑完 篩選→擋在選擇→設定 select 後 ligands 正確合併、GUI 動作寫回與失效。
CI（openmm-stack，有 vina/rdkit/網路）：3PTB + 5 個 PubChem CID 真下載真對接（exhaustiveness 2）。

## 想請審查者回答

1. 篩選排名只用最佳 pose 的 Vina 分數是否足夠？要不要加 cluster 共識或簡單的 consensus（vina + vinardo）？
2. 去鹽只取最大片段：對季銨鹽／金屬配合物類化合物是否會誤刪？
3. 1.0 kcal/mol 的「不可區分」門檻是否合理（Vina 文獻誤差約 1–2 kcal/mol）？
