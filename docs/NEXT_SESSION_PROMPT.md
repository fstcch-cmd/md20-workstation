# 下一個 session 的開場 prompt

> 複製以下內容給下一個 session。

---

你接手 MD20 單機教學版 MD 工作站（擁有者 HCC Lab/NKUST）。全程用繁體中文回覆。

**有兩個 repo，都要 `add_repo`（push 權限）並 clone：**
1. `fstcch-cmd/md20-workstation`：產品本體（目前公開，之後轉私人）。
2. `fstcch-cmd/md-digital-signature`：**私人**，數位簽章／授權的簽發端（擁有者工具、所有簽出授權的紀錄）。**任何 repo 都不得出現私鑰。**

第一步：照 md20 的 CLAUDE.md，git pull 後依序讀 docs/STATUS.md 開頭、docs/HANDOFF.md §0（2026-11-07 第五個 session 交接，最上面那段）、docs/WORKBOARD.md、docs/DECISIONS.md 最上面幾條（目前到 D-126）；再讀 md-digital-signature 的 README.md 與 CLAUDE.md。授權制度設計文件：https://claude.ai/artifact/222jyPJRrE1Pzspv7shAS6 。

CI 查法（單次，不要 sleep 迴圈）：`gh api "repos/fstcch-cmd/md20-workstation/actions/runs?per_page=5" --jq '.workflow_runs[]|[.id,.name,.status,(.conclusion//"-"),.head_sha[0:7]]|@tsv'` → `gh api ".../actions/runs/<id>/jobs?per_page=40" --jq '.jobs[]|[(.conclusion//.status),.name]|@tsv'`；紅的用單次 `gh api .../jobs/<id>/logs` 判斷程式或 infra。

使用者的工作規則（必守）：
- 開發順序自己決定，不要問；需授權的才問：改協定／科學模型、計算預算（A8、P1A、藍圖第 2–4 階段、F19、鋅參數）、發版、推 tag、改 repo 可見性、LICENSE 條文定稿。
- **push 不要太頻繁**：累積在本地，一輪 CI 跑完再一次推。
- 可以開多個 Sonnet（effort high）子代理加速；主 session 分派、審查、整合（做法見 HANDOFF §0）。
- 規矩：不新增 phase／step；三態閘門，寧可擋也不要猜；判斷寫進 docs/DECISIONS.md（新條目在最上面）與 docs/specs/，與程式同一個 commit；改動要有測試；commit 結尾加 Co-Authored-By 與你自己的 Claude-Session；容器裝不了 OpenMM/RDKit/Vina，真實測試交 CI；避免付費 API。

下一步（自行排序）：授權第 2 層（D-125）若尚未合併就完成它 → 簽發端放 md-digital-signature → 第 3 層 → 第 4 層（發行版編譯＋加密，需使用者先建 GitHub Secret）。
