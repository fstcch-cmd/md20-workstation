# MD20 Windows installer (PowerShell).  Downloads micromamba, creates the md20 env, installs the package.
# Usage:  powershell -ExecutionPolicy Bypass -File installer\install.ps1 [-Gpu cuda|opencl|cpu]
param([ValidateSet("auto","cuda","opencl","cpu")] [string]$Gpu = "auto", [string]$Root = "",
      [ValidateSet("","11.8","12.0","12.4")] [string]$Cuda = "",   # -Cuda 11.8: keep an old driver, install the matching OpenMM build
      [switch]$WithFold)   # -WithFold: also install peptide folding (OmegaFold, several GB) and fold one test peptide (D-85)
$ErrorActionPreference = "Stop"
if (-not $Root) { $Root = if ($env:MD20_ROOT) { $env:MD20_ROOT } else { Join-Path $env:LOCALAPPDATA "MD20" } }
$env:MAMBA_ROOT_PREFIX = $Root
# Windows PowerShell 5.1 (the built-in `powershell.exe`) has no `?.` / `??` operators: keep this file 5.1-compatible.
$drive = Get-PSDrive -Name ($Root.Substring(0,1))
$freeGB = [math]::Round($drive.Free / 1GB)
Write-Host "安裝位置：$Root（可用空間 $freeGB GB；環境約需 6 GB）"
if ($freeGB -lt 8) { Write-Host "!! 可用空間不足 8 GB。請清出空間，或改裝到其他磁碟：  .\installer\install.ps1 -Root D:\MD20"; exit 2 }
$Mamba = Join-Path $Root "micromamba.exe"
New-Item -ItemType Directory -Force -Path $Root | Out-Null
# D-117: micromamba is pinned to one release and its sha256 is checked before use (the old URL .../latest gave every student
# whatever was newest that day, unverified).  Source: GitHub mamba-org/micromamba-releases, asset "micromamba-win-64"
# (a single .exe; its official .sha256 asset matches the hash below).  Keep in sync with install.sh (tests/test_installer_pins.py).
# MD20_MICROMAMBA_LATEST=1 is the explicit, unverified escape hatch (the previous behaviour).
$MambaVersion = "2.10.0-0"
$MambaSha256 = @{ "win-64" = "f8b4284bd4eb1134122eaf93b3ea6c7be567e596de5829e1a6f478e34e41974a" }
if (-not (Test-Path $Mamba)) {
  if ($env:MD20_MICROMAMBA_LATEST -eq "1") {
    Write-Host "[1/4] 下載最新版 micromamba（MD20_MICROMAMBA_LATEST=1，未驗證 sha256 / UNVERIFIED: latest micromamba, no sha256 check）..."
    Invoke-WebRequest -Uri "https://micro.mamba.pm/api/micromamba/win-64/latest" -OutFile "$Root\micromamba.tar.bz2"
    tar -xjf "$Root\micromamba.tar.bz2" -C $Root
    Copy-Item "$Root\Library\bin\micromamba.exe" $Mamba -Force
  } else {
    Write-Host "[1/4] 下載 micromamba $MambaVersion（釘選版本，驗證 sha256 / pinned, sha256 verified）..."
    $MambaUrl = "https://github.com/mamba-org/micromamba-releases/releases/download/$MambaVersion/micromamba-win-64"
    $MambaPart = "$Mamba.part"
    $ProgressPreference = "SilentlyContinue"   # Windows PowerShell 5.1 downloads very slowly with the progress bar
    try { Invoke-WebRequest -UseBasicParsing -Uri $MambaUrl -OutFile $MambaPart }
    catch {
      if (Test-Path $MambaPart) { Remove-Item -Force $MambaPart }
      Write-Host "!! 下載 micromamba 失敗 / Download of micromamba failed: $MambaUrl"; Write-Host "   $_"
      Write-Host "   請檢查網路後重跑安裝器（不會改抓未驗證的最新版）。 / Check the network and rerun; the installer does not fall back to an unverified latest build."
      exit 5
    }
    $MambaGot = (Get-FileHash -Algorithm SHA256 -Path $MambaPart).Hash.ToLower()
    if ($MambaGot -ne $MambaSha256["win-64"]) {
      Remove-Item -Force $MambaPart
      Write-Host "!! micromamba 的 sha256 與釘選值不符，已刪除該檔，未使用。 / micromamba sha256 does not match the pinned value; the file was deleted and not used."
      Write-Host "   版本 version: $MambaVersion"
      Write-Host "   預期 expected: $($MambaSha256['win-64'])"
      Write-Host "   實際 got:      $MambaGot"
      Write-Host "   可能是下載被中斷或被代理／防毒改寫；請換網路重試並回報開發者。 / The download may be truncated or rewritten by a proxy or antivirus; retry on another network and tell the developer."
      exit 4
    }
    Move-Item -Force -Path $MambaPart -Destination $Mamba
  }
}
if ($Gpu -eq "auto") { $Gpu = if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { "cuda" } else { "opencl" } }
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Src = (Resolve-Path (Join-Path $Here "..")).Path
# Release ZIP (no .git): the unzipped folder is usually in Downloads and may be deleted later, so the program is copied
# to $Root\app and installed from there.  A git checkout stays where it is (developers keep editing it).  D-33
if (-not (Test-Path (Join-Path $Src ".git"))) {
  $App = Join-Path $Root "app"
  if ($Src.TrimEnd("\") -ne $App.TrimEnd("\")) {
    Write-Host "複製程式到 $App ..."
    if (Test-Path $App) {
      # never delete (user rule, D-36): move the previous copy aside; the user decides when to remove _to_delete
      $Old = Join-Path $Root ("_to_delete\app-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Old) | Out-Null
      Move-Item -Path $App -Destination $Old
      Write-Host "舊版程式已移到 $Old（未刪除；確認新版可用後可自行刪除）"
    }
    New-Item -ItemType Directory -Force -Path $App | Out-Null
    Copy-Item -Recurse -Force (Join-Path $Src "*") $App
  }
  $Src = $App
  $Here = Join-Path $App "installer"
}
function Assert-Ok([string]$what) {
  if ($LASTEXITCODE -ne 0) { Write-Host "!! $what 失敗（exit $LASTEXITCODE）。請把上面的訊息貼給開發者；修正後重跑安裝器會續裝。"; exit $LASTEXITCODE }
}
$Base = Join-Path $Here "..\environment\base.yml"
$GpuYml = Join-Path $Here ("..\environment\windows-" + ($(if ($Gpu -eq "cpu") {"opencl"} else {$Gpu})) + ".yml")
$Prefix = Join-Path $Root "envs\md20"
if ($Gpu -eq "cuda") {
  # D-172: do NOT pin cuda-version.  windows-cuda.yml leaves it free, so conda reads the driver's real __cuda
  # (via nvidia-smi) and picks an openmm build whose cuda-version fits.  If the user forces -Cuda, honour it.
  $smi = (& nvidia-smi 2>$null | Out-String)
  $m = [regex]::Match($smi, "CUDA Version:\s*([0-9]+\.[0-9]+)")
  if ($m.Success) { Write-Host ("驅動支援 CUDA " + $m.Groups[1].Value + " → 由 conda 依驅動挑對應的 OpenMM GPU 建置（cuda-version 不釘死）") }
  if ($Cuda) {
    $tmpYml = Join-Path $Root "windows-cuda-$Cuda.yml"
    $lines = (Get-Content $GpuYml) + "  - cuda-version=$Cuda"
    $lines | Set-Content -Encoding UTF8 $tmpYml
    $GpuYml = $tmpYml
    Write-Host "（手動指定 -Cuda $Cuda）"
  }
}
if ($Gpu -ne "cuda") { $env:CONDA_OVERRIDE_CUDA = "12.9" }   # win-64 openmm builds are CUDA-linked; fake a modern __cuda so the OpenCL/CPU build solves
New-Item -ItemType Directory -Force -Path (Join-Path $Root "tmp") | Out-Null
$env:TMP = Join-Path $Root "tmp"; $env:TEMP = $env:TMP; $env:PIP_CACHE_DIR = Join-Path $Root "pipcache"
# Package cache vs. Windows 260-character paths (D-38).  micromamba caches as <pkgs>\https\conda.anaconda.org\conda-forge\
# win-64\<pkg>\...; the deepest file in pytorch (pulled by openff-nagl) adds 226 characters, so <Root>\pkgs only fits
# when Root is <= 28 characters.  %LOCALAPPDATA%\MD20 is longer for every real user name -> use <drive>:\MD20pkgs.
$PkgTail = 226
$Pkgs = Join-Path $Root "pkgs"
if (($Pkgs.Length + $PkgTail) -ge 260) {
  $Pkgs = $Root.Substring(0, 2) + "\MD20pkgs"
  try { New-Item -ItemType Directory -Force -Path $Pkgs -ErrorAction Stop | Out-Null }
  catch { Write-Host "!! 安裝路徑太長（$Root），套件快取需要放在 $Pkgs，但無法建立：$_"; Write-Host "   請改用較短的位置重跑：Install-MD20.cmd -Root C:\MD20"; exit 3 }
  Write-Host "套件快取改放 $Pkgs（安裝路徑 $Root 太長，會超過 Windows 260 字元路徑限制；安裝完成後可刪除此資料夾）"
}
$env:CONDA_PKGS_DIRS = $Pkgs
$env:PYTHONUTF8 = "1"   # Traditional-Chinese consoles default to cp950; every md20 text file is UTF-8
# D-171: build the env; if the CUDA solve fails (driver's CUDA version has no matching OpenMM GPU build), fall back
# to OpenCL/CPU once instead of crashing.  With the relaxed openmm range this rarely triggers, but it keeps a student
# whose driver is too old for any GPU build from being left with a failed install.
$built = $false
foreach ($attempt in @("primary", "fallback")) {
  if (Test-Path (Join-Path $Prefix "conda-meta")) {
    Write-Host "[2/4] 環境已存在，補齊套件 ($Gpu) ..."; & $Mamba install -y -p $Prefix -f $Base -f $GpuYml
  } else {
    Write-Host "[2/4] 建立環境 ($Gpu) ..."; & $Mamba create -y -p $Prefix -f $Base -f $GpuYml
  }
  if ($LASTEXITCODE -eq 0) { $built = $true; break }
  if ($Gpu -ne "cuda") { break }
  Write-Host "!! CUDA 環境無法解析（驅動的 CUDA 版本配不到可用的 OpenMM GPU 建置）。改用 OpenCL/CPU 重試；更新 NVIDIA 驅動後重跑本安裝器即可改用 CUDA。"
  $Gpu = "opencl"; $env:CONDA_OVERRIDE_CUDA = "12.4"; $GpuYml = Join-Path $Here "..\environment\windows-opencl.yml"
}
if (-not $built) { Assert-Ok "建立環境" }
Write-Host "[3/4] 安裝 md20 ..."
& $Mamba run -p $Prefix pip install --no-cache-dir "openmmforcefields==0.15.1" "meeko~=0.5" gemmi -e $Src
Assert-Ok "安裝 md20"
& $Mamba run -p $Prefix md20 setup-vina
if ($LASTEXITCODE -ne 0) { Write-Host "!! Vina 下載失敗（多半是 GitHub 限流）；稍後執行 md20.cmd setup-vina 即可，其餘安裝繼續。" }
# launchers: md20.cmd (command line) and MD20-GUI.cmd (double-click → browser GUI), both next to micromamba.exe.
# D-77: both start from a short PATH.  `micromamba run` prepends the environment's folders to PATH inside a cmd script;
# on a computer whose PATH is already long (conda, MGLTools, PyMOL …) the result exceeds cmd's 8191-character line limit
# and fails with "The input line is too long" before MD20 starts.  MD20 needs nothing from the user's PATH.
$Cmd = Join-Path $Root "md20.cmd"
Set-Content -Encoding ASCII -Path $Cmd -Value @(
  "@echo off",
  "set MAMBA_ROOT_PREFIX=%~dp0",
  "set PYTHONUTF8=1",
  "set `"PATH=%SystemRoot%\system32;%SystemRoot%;%SystemRoot%\System32\Wbem;%SystemRoot%\System32\WindowsPowerShell\v1.0;%ProgramFiles%\NVIDIA Corporation\NVSMI`"",
  "`"%~dp0micromamba.exe`" run -p `"%~dp0envs\md20`" md20 %*")
$Gui = Join-Path $Root "MD20-GUI.cmd"
Set-Content -Encoding ASCII -Path $Gui -Value @(
  "@echo off",
  "set MAMBA_ROOT_PREFIX=%~dp0",
  "set PYTHONUTF8=1",
  "set `"PATH=%SystemRoot%\system32;%SystemRoot%;%SystemRoot%\System32\Wbem;%SystemRoot%\System32\WindowsPowerShell\v1.0;%ProgramFiles%\NVIDIA Corporation\NVSMI`"",
  "echo MD20 GUI: http://127.0.0.1:8020  (close this window to stop)",
  "`"%~dp0micromamba.exe`" run -p `"%~dp0envs\md20`" md20 gui",
  "pause")
$Desktop = [Environment]::GetFolderPath("Desktop")
# D-76: the desktop launcher must point at the installed one by absolute path.  A copy of $Gui does not work there:
# its %~dp0 would then mean the Desktop folder, where micromamba.exe and envs\md20 do not exist (the window closes at once).
# -Encoding Default (the ANSI code page cmd.exe reads) keeps a non-ASCII user name in the path intact.
# MD20_NO_DESKTOP=1 (developer check, D-81): a side install must not repoint the user's desktop shortcut
if ((Test-Path $Desktop) -and -not $env:MD20_NO_DESKTOP) {
  Set-Content -Encoding Default -Path (Join-Path $Desktop "MD20-GUI.cmd") -Value @(
    "@echo off",
    "call `"$Gui`"")
}
# D-125: the student's unlock tool (import the licence file).  Licence signing tools are not part of this package (D-127).
$UnlockSrc = Join-Path $Here "MD20-Unlock.cmd"
if (Test-Path $UnlockSrc) {
  Copy-Item -Force $UnlockSrc (Join-Path $Root "MD20-Unlock.cmd")
  if ((Test-Path $Desktop) -and -not $env:MD20_NO_DESKTOP) {
    Set-Content -Encoding Default -Path (Join-Path $Desktop "MD20-Unlock.cmd") -Value @(
      "@echo off",
      "call `"$Root\MD20-Unlock.cmd`" %*")
  }
}
Write-Host "[4/4] Doctor ..."
& $Mamba run -p $Prefix md20 doctor
if ($WithFold) {
  Write-Host "[+] 胜肽摺疊工具（OmegaFold，數 GB，約 20–60 分鐘）..."
  & $Mamba run -p $Prefix md20 setup-fold --engine omegafold --yes --warmup
  if ($LASTEXITCODE -ne 0) { Write-Host "!! 摺疊工具沒有裝好；MD20 本身已可使用。之後雙擊 Install-Folding.cmd 或在 GUI 電腦狀態頁按一鍵安裝。" }
}
Write-Host ""
Write-Host "完成。"
Write-Host "  圖形介面：雙擊桌面的 MD20-GUI.cmd（或 $Gui）"
Write-Host "  命令列：  $Cmd doctor | demo | pipeline ... （可把 $Root 加進 PATH）"
Write-Host "  授權：    真正的計算需要 HCC Lab 簽發的授權檔。把授權檔拖到桌面的 MD20-Unlock.cmd 上，或雙擊它。 / Real calculations need a licence file from HCC Lab: drag it onto MD20-Unlock.cmd on the desktop, or double-click that file."
