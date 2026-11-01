# MD20 Windows installer (PowerShell).  Downloads micromamba, creates the md20 env, installs the package.
# Usage:  powershell -ExecutionPolicy Bypass -File installer\install.ps1 [-Gpu cuda|opencl|cpu]
param([ValidateSet("auto","cuda","opencl","cpu")] [string]$Gpu = "auto", [string]$Root = "")
$ErrorActionPreference = "Stop"
if (-not $Root) { $Root = if ($env:MD20_ROOT) { $env:MD20_ROOT } else { Join-Path $env:LOCALAPPDATA "MD20" } }
$env:MAMBA_ROOT_PREFIX = $Root
$drive = (Get-Item $Root -ErrorAction SilentlyContinue)?.PSDrive ?? (Get-PSDrive -Name ($Root.Substring(0,1)))
$freeGB = [math]::Round($drive.Free / 1GB)
Write-Host "安裝位置：$Root（可用空間 $freeGB GB；環境約需 6 GB）"
if ($freeGB -lt 8) { Write-Host "!! 可用空間不足 8 GB。請清出空間，或改裝到其他磁碟：  .\installer\install.ps1 -Root D:\MD20"; exit 2 }
$Mamba = Join-Path $Root "micromamba.exe"
New-Item -ItemType Directory -Force -Path $Root | Out-Null
if (-not (Test-Path $Mamba)) {
  Write-Host "[1/4] 下載 micromamba ..."
  Invoke-WebRequest -Uri "https://micro.mamba.pm/api/micromamba/win-64/latest" -OutFile "$Root\micromamba.tar.bz2"
  tar -xjf "$Root\micromamba.tar.bz2" -C $Root
  Copy-Item "$Root\Library\bin\micromamba.exe" $Mamba -Force
}
if ($Gpu -eq "auto") { $Gpu = if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { "cuda" } else { "opencl" } }
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Base = Join-Path $Here "..\environment\base.yml"
$GpuYml = Join-Path $Here ("..\environment\windows-" + ($(if ($Gpu -eq "cpu") {"opencl"} else {$Gpu})) + ".yml")
$Prefix = Join-Path $Root "envs\md20"
if ($Gpu -eq "cuda") {
  # pick cuda-version from what the installed driver supports (nvidia-smi "CUDA Version: X.Y")
  $smi = (& nvidia-smi 2>$null | Out-String)
  $m = [regex]::Match($smi, "CUDA Version:\s*([0-9]+\.[0-9]+)")
  if ($m.Success) {
    $drv = [double]$m.Groups[1].Value
    if ($drv -lt 11.8) { Write-Host "!! 驅動只支援 CUDA $drv（< 11.8）：改用 OpenCL。更新 NVIDIA 驅動後可重跑本安裝器改用 CUDA。"; $Gpu = "opencl"; $env:CONDA_OVERRIDE_CUDA = "12.4"; $GpuYml = Join-Path $Here "..\environment\windows-opencl.yml" }
    else {
      $cv = if ($drv -lt 12.0) { "11.8" } elseif ($drv -ge 12.4) { "12.4" } else { $m.Groups[1].Value }
      $tmpYml = Join-Path $Root "windows-cuda-$cv.yml"
      (Get-Content $GpuYml) -replace "cuda-version=[0-9.]+", "cuda-version=$cv" | Set-Content -Encoding UTF8 $tmpYml
      $GpuYml = $tmpYml
      Write-Host "驅動支援 CUDA $drv → 使用 cuda-version=$cv"
    }
  }
}
if ($Gpu -ne "cuda") { $env:CONDA_OVERRIDE_CUDA = "12.4" }   # win-64 openmm builds are CUDA-linked; override the virtual package
New-Item -ItemType Directory -Force -Path (Join-Path $Root "tmp") | Out-Null
$env:TMP = Join-Path $Root "tmp"; $env:TEMP = $env:TMP; $env:PIP_CACHE_DIR = Join-Path $Root "pipcache"
if (Test-Path (Join-Path $Prefix "conda-meta")) {
  Write-Host "[2/4] 環境已存在，補齊套件 ($Gpu) ..."; & $Mamba install -y -p $Prefix -f $Base -f $GpuYml
} else {
  Write-Host "[2/4] 建立環境 ($Gpu) ..."; & $Mamba create -y -p $Prefix -f $Base -f $GpuYml
}
Write-Host "[3/4] 安裝 md20 ..."
& $Mamba run -p $Prefix pip install --no-cache-dir "openmmforcefields>=0.14" "meeko>=0.5" -e (Join-Path $Here "..")
& $Mamba run -p $Prefix md20 setup-vina
Write-Host "[4/4] Doctor ..."
& $Mamba run -p $Prefix md20 doctor
Write-Host "`n完成。之後執行：  $Mamba run -p $Prefix md20 <command>"
