# 下一個 session 的開場 prompt

> 複製以下內容給下一個 session（連同這個 repo）。

---

你接手 fstcch-cmd/md20-workstation（MD20 單機教學版 MD 工作站，擁有者 HCC Lab/NKUST）。全程用繁體中文回覆。

第一步，照 CLAUDE.md：把 repo 加進 session 並 clone（需 push 權限），git pull 後依序讀 docs/STATUS.md 開頭、docs/HANDOFF.md §0（2026-11-07 第四個 session 交接）、docs/WORKBOARD.md、docs/DECISIONS.md 最上面幾條（目前到 D-110）。本地 repo 優先於 GitHub 歷史。

**⚠ 有 CI 正在 GitHub VM 上跑，接手第一件事是確認它、不要先 push。**
- 驗證 commit 是 `ac5fba5`（HEAD 是其後的 docs-only commit，不觸發 CI）。它含本週全部未驗證的真實引擎改動：D-102 膜 NaN 修復、D-104 建膜即時 3D、D-105 分析工具箱、D-106 系統共同基底、D-107 declash/padding 修正。
- 之前每次 push 都把上一輪排隊的 CI 取代掉，所以 openmm-stack 三 OS／heavy workflow 從沒跑完過。**在確認 `ac5fba5` 的 CI 跑完之前，只改 `docs/**`（不觸發 CI），不要 push 任何程式改動。**
- 單次查（不要 sleep 迴圈輪詢）：
  `gh api "repos/fstcch-cmd/md20-workstation/actions/runs?head_sha=$(git rev-parse ac5fba5)" --jq '.workflow_runs[]|select(.name|startswith("MD20 CI"))|.id'`
  → `gh api ".../actions/runs/<id>/jobs?per_page=40" --jq '.jobs[]|[(.conclusion//.status),.name]|@tsv'`
- 重點看：openmm-stack 三 OS 的膜測試 water overlaps 閘門 PASS/AUTO_FIXED 且 case B 400 步不 NaN（D-102）、live3d 階段 solute→bilayer→declashed（D-104）、toolbox 真 mdtraj（D-105）、共同基底 3PTB apo+複合物可比（D-106）；pure-python 六個與 heavy-metal 應已由 D-107 轉綠；heavy workflow、paper-docking。紅的用單次 `gh api .../jobs/<id>/logs` 判斷是程式還是 infra，當場修（同一 commit 附測試與 DECISIONS/specs）。

**CI 全綠後，向使用者回報，並問下一步做哪個；未經使用者授權不要動需授權的項目。**

待使用者授權／決定：
1. **發行（非必須，別催）**：對外仍是 a17；發行唯一修的是新安裝的 openmmforcefields 釘選。a19（e0a0f77，只含 D-95–D-98）已備好，但 D-99–D-110 也在 main，等 `ac5fba5` CI 全綠後直接發 a20（涵蓋全部）通常更合適。推 tag 需使用者執行,只在使用者要求時做。
2. **D-103 行為改變確認**：現在關掉 GUI 不中斷計算（按「暫停」才停）；問使用者要不要改成「關 GUI＝暫停」。
3. **需授權才能做（屬協定變更或需計算預算）**：A8 漏斗約束 ΔG°／PMF 參考態、P1A 自動補窗；藍圖第 2–4 階段（GaMD／metadynamics、REST2、RBFE/ABFE、恆定 pH、QM/MM、ML 勢能）；F19 MM/GBSA pilot。
4. **需筆電實測（CI 測不到）**：D-72 vina 執行緒、hsieh2024 URI 的實際 SMD/PMF 數值、D-103 關掉 GUI 主控台後子程序是否存活。

規矩（CLAUDE.md，必守）：不新增 phase/step 只強化既有邏輯；三態閘門 PASS/AUTO_FIXED/NEEDS_HUMAN，寧可擋也不要猜；任何專項修改把判斷（理由、取捨、被否決做法、證據）寫進 docs/DECISIONS.md（新條目在最上面）與 docs/specs/，跟程式同一個 commit；改動要有測試；commit 結尾加 Co-Authored-By 與你自己的 Claude-Session。容器裝不了 OpenMM/RDKit/Vina 也連不到 RCSB，只能 FakeBackend 測邏輯，真實測試交 CI；未經使用者授權不跑正式模擬、不改科學模型、不重新發版、不推 tag。**避免使用付費 API**（程式目前只呼叫免費 GitHub API）。repo 開發期間維持公開。

工作方式：一邊開發一邊用 CI 即時驗證、找到問題當場修。先把 `ac5fba5` 的 CI 看完、確認 D-102~D-107 真實路徑綠，再接使用者指定的下一項。
