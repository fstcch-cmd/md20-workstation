# 閘門一鍵決定（GUI）

狀態：**[已驗證]**（f879764：Windows OpenCL / macOS 的 `test_gui_pages_render` 實際啟動 NiceGUI 並渲染按鈕）。

## 原則
- 只有**程式真的會執行**的選項才變成按鈕；其他（換結構、改序列、MCPB/QM、補長 loop）列為「需要在程式外處理」。
- 需要理由的選項（結構仍要使用、CPP 實驗證據／仍要繼續、擬肽小分子）必填文字，寫入設定與 DecisionLog。
- 按下後：設定寫回 `config.json` → 記人工決策（含 patch）→ 從該步驟起失效（`STEP_ORDER`），原始結構永不丟棄。

## 選項 → 設定修補（`md20/gui/actions.py::_option_action`）
| 閘門 | 選項 | 修補 | 重跑起點 |
|---|---|---|---|
| resolution / R-free / occupancy | 仍要使用 | `structure_override.<k> = 理由` | structure_gate |
| 口袋金屬 | metal_policy: {ZN: bonded…} | `metal_policy.ZN` | structure_gate |
| 建模金屬位點 | 改用 keep_nonbonded / remove / 改用幾何鍵結模型 | `metal_policy.<site>` / `metal_params.<site> = null` | md_cases |
| 金屬電荷不符 | 不套用電荷 | `metal_params.<site>.charges = false` | md_cases |
| hetero groups | 移除／保留並參數化／保留為參考配體 | `human_choices.receptor.<gate>` | receptor_docking |
| 盲對接 | box.from_residue / allow_blind | `box` | docking_preflight |
| redocking | skip_redock | `docking.skip_redock` | docking_preflight |
| CPP | 標靶位置／實驗證據／仍要繼續 | `ligands[name].target_location / cpp_evidence / cpp_override` | docking_preflight |
| 胜肽偵測 | 確認為小分子 | `peptide_policy.allow_small_molecule = 理由` | md_cases |

## 一併修掉的漏洞
受體閘門的 `human_choices` 以前只要有選擇就把閘門轉為 AUTO_FIXED，但多數選項沒實作（長 loop 選「補建並接受風險」實際仍丟棄 → 主鏈斷裂；
「保留為參考配體」反而留在 MD 受體）。現在 `receptor_choice_action` 只接受 hetero groups 的移除／保留，其他選擇維持擋關並說明。

## 想請審查者回答
長 loop 的「截斷加帽」「PDBFixer 補建」是否值得實作成可點選項？若實作，補建 loop 的品質門檻應是什麼？
