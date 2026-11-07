# 供應鏈與可重現性：外部執行檔與環境版本

狀態：Vina 執行檔 **[已實作・純 Python 測試；真實下載交 CI]**（D-114）；micromamba **[已實作・純 Python 測試；待 CI installer job 驗證]**（D-117）；conda 環境鎖版 **[未做]**。

## 1. AutoDock Vina 執行檔（Windows；Linux/macOS 用 conda 的 `vina` Python 套件）
- **只用一個釘選版本**：`vina_cli.PINNED_VERSION = "v1.2.7"`。同一班學生一定拿到同一版（D-114 以前：先問 GitHub releases API 拿最新版，被限流才退回 v1.2.5，同一班可能混用兩版）。
- **下載後先驗 sha256**（`KNOWN_SHA256`），不符就刪除、不使用、換下一個來源或報錯；先下載成 `.part`，驗過才換名，不會留下半個檔。
- 雜湊表含 v1.2.7（現行）與 v1.2.5（前一個釘選，用來辨識舊安裝留下的執行檔）。來源：2026-11-07 從 GitHub release 資產下載後計算（`file` 確認 PE32+／ELF／Mach-O）。
- `MD20_VINA_LATEST=1`：先試 releases API 的最新資產（不在雜湊表 → 記為未驗證），再退回釘選版。預設不呼叫 API（也順帶避開每小時 60 次的限流）。
- 每次 docking 在 `params.vina_executable` 記錄執行檔路徑、sha256、對應的官方資產（或「不是已知官方版本」），決策紀錄同步寫一句；`md20 setup-vina` 會印出同樣資訊。使用者以 `MD20_VINA_EXE` 指定的執行檔照用，只記錄不阻擋。
- 已存在於 `<app data>/bin` 的舊執行檔（例如 a17 安裝時拿到的 v1.2.5 或 API 最新版）**不自動替換**，但版本會被記錄。

## 2. micromamba（安裝程式；D-117）
- **只用一個釘選版本**：`mamba-org/micromamba-releases` tag `2.10.0-0`，資產 `micromamba-<platform>`（單一可執行檔；win-64、osx-64、osx-arm64、linux-64、linux-aarch64）。`installer/install.ps1`（`$MambaVersion`、`$MambaSha256`，只有 win-64）與 `installer/install.sh`（`MICROMAMBA_VERSION`、`micromamba_sha256()`，五個平台）各寫一份，`tests/test_installer_pins.py` 檢查一致。
- **下載後先驗 sha256**：下載成 `.part` → 驗雜湊 → 相符才改名；不符刪檔、印中英錯誤並 `exit 4`，下載失敗 `exit 5`，**都不會改抓 latest**。五個雜湊與官方 `.sha256` 資產一致（見 D-117 表格）。
- `MD20_MICROMAMBA_LATEST=1`：走原本的 `micro.mamba.pm/.../latest`，印「未驗證」。
- 已存在的 micromamba 不重抓、不替換、不驗證。
- 升級步驟：改兩個腳本的版本號 → 下載五個資產自算 sha256、與官方 `.sha256` 比對 → 更新兩個腳本的雜湊 → `pytest tests/test_installer_pins.py` → 看 `installer-windows`／`installer-macos` job 綠燈 → DECISIONS 新增條目。
- 狀態：容器內只驗證字串與假 `curl` 的 bash 邏輯；真實下載與 PowerShell 5.1 路徑待 CI。

## 3. 還沒做
- conda 環境檔多為 `>=`，Linux/macOS 的 `vina>=1.2.5` 與 Windows 執行檔的版本可能不同；需要 lock 檔（每個 OS×GPU 一份，例如 `conda-lock`／`micromamba env export --explicit` 的 `@EXPLICIT` 檔含 sha256）與 CI 產生／比對流程。`pip install` 的 `openmmforcefields==0.15.1`、`meeko~=0.5`、`gemmi` 也沒有雜湊鎖定。這是 micromamba 釘選之外最大的重現性缺口，未動。
- 審查問題：舊執行檔與釘選版不同時，要不要在 doctor 給 NEEDS_HUMAN 選項「換成釘選版」？micromamba 同理（顯示版本與是否為釘選版）。
