# 下一個 session 的開場 prompt

> 複製以下內容給下一個 session（連同兩個 repo）。

---

你接手 MD20 單機教學版 MD 工作站（擁有者 HCC Lab/NKUST）。全程用繁體中文。

**兩個 repo，都要 add_repo（push）並 clone：**
1. `fstcch-cmd/md20-workstation`：產品本體（目前公開，之後轉私人）。HEAD 應為 `650bc65` 或更新。
2. `fstcch-cmd/md-digital-signature`：**私人**，數位簽章／授權的簽發端。

第一步（照 md20 CLAUDE.md）：git pull 後依序讀 `docs/STATUS.md` 開頭、`docs/HANDOFF.md` §0 最上面那段（2026-11-07 第六個 session 交接）、`docs/WORKBOARD.md`、`docs/DECISIONS.md` 最上面幾條（到 D-132）；再讀私人 repo 的 README/CLAUDE.md。**本地 repo 優先於 GitHub 歷史。**

**主線任務：使用者上傳的規格「MD20: Evidence-Driven Repair and Next-Generation Development」，全文存在 `docs/specs/evidence_driven_repair_prompt.md`。** 照它第 1 節「先建立現況真相」，用**目前本地程式**逐項核對 R1–R8（不照抄稽核結論），列優先缺口表，再做第一輪安全修正＋測試。HANDOFF §0 已有本地核對摘要。

**已授權（使用者 2026-11-07 23:01–23:07）：**
- 規格 R1–R8 全部做完，與下列進行中項目並行。
- **改鋅鍵結模型參數**（R5）：依證據調 `md20/build/metal.py` 的 Zn–N 參數並補驗證測試，**不是放寬 `tests/test_metal_integration.py` 的 0.03 nm 門檻**。鋅測試紅：HIS119:ND1≈0.236 nm vs r0 0.202，GLU106 羧基在 3 Å 內把 Zn 拉走（metal.py:363 已註明鍵會被拉長）。先重現、查原子對應/質子化/鍵結項/排除/競爭非鍵/參數來源，分辨程式缺陷與模型不足。
- push 回到「累積到一輪 CI 空檔再批次推」。

**進行中、實作未落地（上個 session 關閉時三個子代理分支無 commit → 照規格重做）：**
- **D-128 授權第 3 層**：tier/features/seats/max_version/簽章撤銷清單/評估版浮水印/輸出蓋授權編號；同時改 md20（驗證）與私人 repo（簽發），格式升 v2、v1 仍可驗、測試向量兩邊逐位元組相同。設計文件 https://claude.ai/artifact/222jyPJRrE1Pzspv7shAS6 。
- **D-130/D-131 重複分析**：完整規格 `docs/specs/replicas.md`（D-129）。核心＝`Workflow.analyse` 只讀 `run_ids[0]`，需逐條分析、跨重複彙總、報告呈現不確定性、開始前告知使用者會多花時間（預設 3 條）。

**本地未修的真缺口（可安全做，不碰科學模型）：**
- **R2**：`md20/report/evidence.py` 以執行狀態（COMPLETE／PASS+非空ΔG）標 supported，和 `md20/sampling/assessment.py` 的 `assess_pmf` 嚴格資格不一致 → 全部路徑走同一套版本化評估；缺證據一律 unknown，不得轉 supported。
- **R4**：`workflow.analyse` 以 `analysis_manifest status==PASS` 驅動重用 → 加依賴指紋（input hash／topology／protocol／schema 版本／門檻），只重算受影響分析、不重跑 MD，atomic 替換，保留舊結果與 provenance。
- **R3 查核**：確認 extended 分析與 persistence 走全解析度、common_basis 250 幀上限據實標註。
- **R7**：capability manifest（功能/位置/系統類型/限制/測試型態/commit/證據/benchmark/已發行安裝程式）。

**規則（CLAUDE.md，必守）：**
- 開發順序自己決定；需授權才問：改協定/科學模型（鋅除外，已授權）、計算預算（A8/P1A/F19/藍圖 2–4 階段）、發版、推 tag、改 repo 可見性、LICENSE 條文定稿。
- push 批次（一輪 CI 跑完再推）；**但 session 要關閉前務必先把所有已審查 commit push 上 GitHub，否則隨容器遺失。**
- 不新增 phase/step；三態閘門，寧可擋也不要猜；判斷寫 `docs/DECISIONS.md`（新條目在最上面）＋`docs/specs/`，與程式同 commit；改動要有測試、真實路徑交 CI；容器裝不了 OpenMM/RDKit/Vina；避免付費 API。
- 可用 Sonnet（effort high）子代理並行；主 session 分派/審查/整合（做法見 HANDOFF §0）。worktree 隔離工具被禁 → 自己 `git worktree add -b agent/<名> /home/claude/wt-<名> HEAD`，事先分好檔案範圍與 DECISIONS 編號。
- **私鑰永不進任何 repo**；授權驗證不得有任何環境變數/設定/參數後門。
- commit 結尾用當下模型的屬名與 `Claude-Session`。

**CI 查法（單次，不輪詢）：** `gh api "repos/fstcch-cmd/md20-workstation/actions/runs?per_page=5" --jq '.workflow_runs[]|[.id,.name,.status,(.conclusion//"-"),.head_sha[0:7]]|@tsv'` → `.../runs/<id>/jobs?per_page=40`；紅的用 `.../jobs/<id>/logs` 判斷程式或 infra。已知邊緣紅：heavy-metal 鋅鍵長（現已授權修）。

決策編號接續 **D-133**（D-128–D-131 若重做沿用原號並註明重做）。
