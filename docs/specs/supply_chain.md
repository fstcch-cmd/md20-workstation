# 供應鏈與可重現性：外部執行檔與環境版本

狀態：Vina 執行檔 **[已實作・純 Python 測試；真實下載交 CI]**（D-114）；micromamba 與 conda 環境鎖版 **[未做]**。

## 1. AutoDock Vina 執行檔（Windows；Linux/macOS 用 conda 的 `vina` Python 套件）
- **只用一個釘選版本**：`vina_cli.PINNED_VERSION = "v1.2.7"`。同一班學生一定拿到同一版（D-114 以前：先問 GitHub releases API 拿最新版，被限流才退回 v1.2.5，同一班可能混用兩版）。
- **下載後先驗 sha256**（`KNOWN_SHA256`），不符就刪除、不使用、換下一個來源或報錯；先下載成 `.part`，驗過才換名，不會留下半個檔。
- 雜湊表含 v1.2.7（現行）與 v1.2.5（前一個釘選，用來辨識舊安裝留下的執行檔）。來源：2026-11-07 從 GitHub release 資產下載後計算（`file` 確認 PE32+／ELF／Mach-O）。
- `MD20_VINA_LATEST=1`：先試 releases API 的最新資產（不在雜湊表 → 記為未驗證），再退回釘選版。預設不呼叫 API（也順帶避開每小時 60 次的限流）。
- 每次 docking 在 `params.vina_executable` 記錄執行檔路徑、sha256、對應的官方資產（或「不是已知官方版本」），決策紀錄同步寫一句；`md20 setup-vina` 會印出同樣資訊。使用者以 `MD20_VINA_EXE` 指定的執行檔照用，只記錄不阻擋。
- 已存在於 `<app data>/bin` 的舊執行檔（例如 a17 安裝時拿到的 v1.2.5 或 API 最新版）**不自動替換**，但版本會被記錄。

## 2. 還沒做
- micromamba 安裝程式仍抓 `latest`（`installer/install.ps1`、`install.sh`）。
- conda 環境檔多為 `>=`，Linux/macOS 的 `vina>=1.2.5` 與 Windows 執行檔的版本可能不同；需要 lock 檔（每個 OS×GPU 一份）與 CI 產生／比對流程。
- 審查問題：舊執行檔與釘選版不同時，要不要在 doctor 給 NEEDS_HUMAN 選項「換成釘選版」？
