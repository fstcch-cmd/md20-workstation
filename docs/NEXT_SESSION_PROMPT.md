# 下一個 session 交接 prompt

> 最後更新：2026-11-09（第八個 session，session_016gcJz6aoRW5kLP9Jzbi7kj 收尾）。
> 直接把下面整段貼給新的 Claude Code session 即可無縫接手。詳細現況見 `docs/STATUS.md` 開頭與 `docs/HANDOFF.md` §0。

---

你要接手 MD20 單機教學版分子動力學工作站的開發。這是 HCC Lab, NKUST 的專案。

第一步（照規矩做）：
1. add_repo（push 權限）並 clone 兩個 repo：
   - fstcch-cmd/md20-workstation（產品／驗證端）
   - fstcch-cmd/md-digital-signature（私人，數位簽章簽發端）
2. 讀 md20-workstation 的 docs/STATUS.md 開頭（已更新到 2026-11-09）、
   docs/HANDOFF.md §0 最上面的「2026-11-09 第八個 session」交接塊、
   docs/DECISIONS.md 最上面幾條（D-161→D-155），再讀兩個 repo 的 CLAUDE.md。
3. git pull 並讀 docs/WORKBOARD.md，認領項目後才動手。

現況：
- 對外最新發行＝v0.1.0a20（2026-11-09 prerelease）；main 為開發中 a21.dev0。
- 本環境代理封鎖建 git tag（403）。要發行用繞法：推 release/<tag> 分支指向
  release commit，再 gh workflow run release-windows.yml -f tag=<tag>，由
  workflow 自己的 token 建 tag。細節見 DECISIONS D-160。

⚠ 最重要的待辦：docs/specs/llm_orchestration.md（LLM 編排規格）是草案，
  未實作。使用者規則是「規格先給使用者與其他模型審查、收到回饋後才動工」。
  不要自行開始實作 LLM 編排；等使用者指派或回饋，並把回饋採納/不採納記進
  該規格檔與 DECISIONS。

安全紅線（不可退讓）：
- 私鑰永不進任何 repo／log／對話；驗證端不得有任何 env／設定／參數後門。
- 不要為了測試方便換公鑰或加旁路（上個 session 試過，被安全分類器正確擋下）。
- commit 前在 md-digital-signature 跑 python3 tools/check_no_private_keys.py。

工作規則：
- 全程繁體中文。開發順序自己決定，但改協定／科學模型、計算預算、發版、
  推 tag、改 repo 可見性要先問使用者。
- push 要批次（一輪 CI 約 1 小時跑完再推）；可用 Sonnet 子代理平行開發。
- 查 CI 用單次 gh run view／gh run list，不要 sleep 迴圈輪詢。
- 任何專項修改，結論＋理由＋證據寫進 docs/DECISIONS.md（新條目在最上面）
  與 docs/specs/，與程式碼同一個 commit 推上去。
- commit 結尾加 Co-Authored-By 與你自己的 Claude-Session 連結。

其他待做（使用者決定或自排）：D-128 加密發行層、鋅配體直接配位參數化、
鋅擬合/OH⁻ 競爭羧基塌陷（D-150/D-152 科學模型變更待使用者決定）、
漏斗 ΔG° 預設關閉待驗證（D-140）、D-72 筆電實測、MD20_LLM_GUIDE.md 規則檔範本。
