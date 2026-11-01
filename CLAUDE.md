# CLAUDE.md — MD20 單機教學版工作站

**接手前先讀 `docs/HANDOFF.md`(完整交接),再讀 `docs/STATUS.md`(誠實現況)。** 以下是每次都要遵守的重點。

## 這個 repo 是什麼
Docking → 建模 → OpenMM MD → SMD/傘狀採樣的單機教學版,給博士生在自己筆電上跑(Windows 優先)。擁有者 HCC Lab, NKUST。所有成果在本 repo + GitHub Actions CI 上。

## 硬限制(違反會卡住)
- 開發容器**連不到 RCSB 或任意網站**(只有 PyPI/conda/GitHub);需要 PDB 請用 `gh` 或請使用者附上。
- 容器**裝不了 OpenMM/RDKit/OpenFF/Vina**;本地用 `FakeBackend` 測邏輯,**真實測試交給 CI** `openmm-stack` 矩陣,不要在容器裡裝這些。
- 查 CI 用**單次** `gh run view`/`gh api ... comments`,**不要**長 `sleep`+迴圈輪詢,也避免 `rm -rf $VAR` 式語法(會觸發安全中斷)。

## 開發規則(MD20_optimization_brief)
- 不新增 phase/step,只強化既有邏輯。
- 三態閘門 PASS / AUTO_FIXED / NEEDS_HUMAN;每個自動決策寫 `DecisionLog`,`why` 用中文。
- **寧可擋也不要猜**:條件不足就 NEEDS_HUMAN 並給選項。
- `STATUS.md` 要誠實三級;改動要有測試且 CI 綠才算完成。

## Commit 屬名
每次 commit 結尾加(用你自己的 session 連結):
```
Co-Authored-By: Claude <noreply@anthropic.com>
Claude-Session: <本次 session 連結>
```

## 戳記
`md20/util/stamp.py`;公鑰 `md20/util/owner_pub.pem` 在 repo,**私鑰不在 repo 也不該進 repo**(使用者離線保管)。`system.xml` 不可加註解(OpenMM 會讀不了)。

## 第四個 session 之後必知
- 全面審查結果在 `docs/REVIEW_2026-11-01.md`(未修項目從那裡接)。HTS 篩選規格 `docs/specs/hts_screen.md`。
- `pipeline run` 會沿用 workflow config.json 的人工決定(`workflow.DECISION_KEYS`);新增閘門決定鍵要加進去。
- CI main 不取消進行中的 run;看 summary 留言的 **skip 數**,SKIPPED 的整合測試不算通過。
- PDB/PDBQT 的戳記必須純 ASCII(cp950 Windows 會崩)。

## 現況與還沒做
WP5、WP9、WP13、金屬 policy/幾何鍵結模型已實作(真實驗證狀態見 `docs/STATUS.md`)。
GUI 閘門一鍵決定(`md20/gui/actions.py`)、3D 互作/vdW 表面、金屬擬合參數(`md20/build/metal_params.py`:QM Hessian 內建轉換/MCPB.py 轉譯/JSON,附 QM 小模型輸入產生)已實作。
還沒做:配體直接配位金屬的參數化、受體長 loop 等選項的自動處理。細節見 `docs/HANDOFF.md` §6。
