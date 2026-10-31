# MD20 Windows installer (PowerShell).  Downloads micromamba, creates the md20 env, installs the package.
# Usage:  powershell -ExecutionPolicy Bypass -File installer\install.ps1 [-Gpu cuda|opencl|cpu]
param([ValidateSet("cuda","opencl","cpu")] [string]$Gpu = "auto")
$ErrorActionPreference = "Stop"
$Root = Join-Path $env:LOCALAPPDATA "MD20"
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
Write-Host "[2/4] 建立環境 ($Gpu) ..."
& $Mamba create -y -p $Prefix -f $Base -f $GpuYml
Write-Host "[3/4] 安裝 md20 ..."
& $Mamba run -p $Prefix pip install -e (Join-Path $Here "..")
Write-Host "[4/4] Doctor ..."
& $Mamba run -p $Prefix md20 doctor
Write-Host "`n完成。之後執行：  $Mamba run -p $Prefix md20 <command>"
