<# : batch part (cmd sees this; PowerShell treats it as a comment)
@echo off
rem MD20 laptop self-test: download latest release -> install -> doctor -> demo -> GUI check -> classroom 3PTB case.
rem Double-click.  Everything is logged to Desktop\MD20_test\selftest_<time>.log.  Only <install root>\app is replaced.
set "MD20_SELF=%~f0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
powershell -NoProfile -ExecutionPolicy Bypass -Command "iex (Get-Content -LiteralPath $env:MD20_SELF -Raw)"
echo.
echo Self-test finished. Send the log file in Desktop\MD20_test to the developer session.
pause
exit /b
: end of batch part #>

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$env:MD20_NOPAUSE = '1'
$base = Join-Path ([Environment]::GetFolderPath('Desktop')) 'MD20_test'
New-Item -ItemType Directory -Force -Path $base | Out-Null
$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$log = Join-Path $base "selftest_$ts.log"
Start-Transcript -Path $log | Out-Null
$results = [ordered]@{}
function Step([string]$n) { Write-Host ""; Write-Host ("===== {0}   {1} =====" -f $n, (Get-Date -Format 'HH:mm:ss')) }
function Run([string]$name, [scriptblock]$sb) {
  Step $name
  $t0 = Get-Date
  $global:LASTEXITCODE = 0
  try { & $sb 2>&1 | Out-Host; $rc = $LASTEXITCODE } catch { Write-Host "EXCEPTION: $_"; $rc = -1 }
  $min = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
  $results[$name] = "rc=$rc  ($min min)"
  Write-Host "--> $name : rc=$rc  ($min min)"
  return $rc
}

Step '0 system info'
Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber | Format-List | Out-Host
Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer, Model, @{n='RAM_GB';e={[math]::Round($_.TotalPhysicalMemory/1GB,1)}} | Format-List | Out-Host
Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors | Format-List | Out-Host
Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, DriverDate | Format-List | Out-Host
Get-PSDrive -PSProvider FileSystem | Select-Object Name, @{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}} | Format-Table | Out-Host
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { & nvidia-smi 2>&1 | Out-Host } else { Write-Host 'nvidia-smi: not found' }
Write-Host "PowerShell $($PSVersionTable.PSVersion)   MD20_ROOT=$env:MD20_ROOT"
$root = if ($env:MD20_ROOT -and ($env:MD20_ROOT -match '^[A-Za-z]:')) { $env:MD20_ROOT } else { Join-Path $env:LOCALAPPDATA 'MD20' }
Write-Host "install root: $root"
$md20 = Join-Path $root 'md20.cmd'

# The installer replaces <root>\app (D-33).  The user allowed MD20-project files to be replaced/deleted (2026-11-02 09:50);
# list what will be replaced so the log shows it.
$existing = @('app', 'envs\md20', 'md20.cmd') | ForEach-Object { Join-Path $root $_ } | Where-Object { Test-Path $_ }
if ($existing) { Write-Host 'Existing MD20 install (app folder will be replaced, environment reused/updated):'; $existing | ForEach-Object { Write-Host "  $_" } }
$inst = $null
$localSrc = Join-Path $base 'local_src.txt'   # developer override: one line = folder that contains Install-MD20.cmd
if (Test-Path $localSrc) {
  $src = (Get-Content $localSrc -Raw).Trim()
  $inst = Get-Item (Join-Path $src 'Install-MD20.cmd') -ErrorAction SilentlyContinue
  Write-Host "local_src.txt -> installing from $src"
  $results['1 download'] = "local source $src"
} else {
  Step '1 download latest release'
  try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $rels = Invoke-RestMethod -Uri 'https://api.github.com/repos/fstcch-cmd/md20-workstation/releases' -Headers @{ 'User-Agent' = 'md20-selftest' }
    $rel = $rels | Where-Object { $_.assets | Where-Object { $_.name -like 'MD20-Windows-*.zip' } } | Select-Object -First 1
    $asset = $rel.assets | Where-Object { $_.name -like 'MD20-Windows-*.zip' } | Select-Object -First 1
    Write-Host "release: $($rel.tag_name)  asset: $($asset.name)"
    $zip = Join-Path $base $asset.name
    if (-not (Test-Path $zip)) { Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing }
    $sumAsset = $rel.assets | Where-Object { $_.name -like 'SHA256SUMS*' } | Select-Object -First 1
    if ($sumAsset) {
      $sums = (Invoke-WebRequest -Uri $sumAsset.browser_download_url -UseBasicParsing).Content
      if ($sums -is [byte[]]) { $sums = [Text.Encoding]::ASCII.GetString($sums) }
      $hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
      if ($sums -match $hash) { Write-Host "sha256 OK $hash" } else { Write-Host "!! sha256 MISMATCH $hash"; throw 'checksum' }
    }
    $dst = Join-Path $base "$($rel.tag_name)_$ts"
    Expand-Archive -Path $zip -DestinationPath $dst
    $inst = Get-ChildItem -Path $dst -Recurse -Filter 'Install-MD20.cmd' | Select-Object -First 1
    $results['1 download'] = "ok $($rel.tag_name)"
  } catch { Write-Host "!! download failed: $_"; $results['1 download'] = "FAILED: $_" }
}
if ($inst) { Run '1 install' { & cmd /c "`"$($inst.FullName)`"" } | Out-Null }

if (-not (Test-Path $md20)) {
  Write-Host "!! $md20 not found - cannot continue."
} else {
  Run '2 doctor' { & $md20 doctor } | Out-Null
  Run '2b drivers plan' { & $md20 drivers plan } | Out-Null
  Run '3 demo' { & $md20 demo } | Out-Null

  Step '4 GUI'
  $gui = Join-Path $root 'MD20-GUI.cmd'
  $p = Start-Process -FilePath $gui -PassThru
  $ok = $false
  for ($i = 0; $i -lt 40 -and -not $ok; $i++) {
    Start-Sleep -Seconds 3
    try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8020' -UseBasicParsing -TimeoutSec 5; if ($r.StatusCode -eq 200) { $ok = $true } } catch {}
  }
  $results['4 GUI'] = $(if ($ok) { "ok http 200 after $(3*$i) s (window left open)" } else { 'FAILED: no http 200 within 120 s' })
  Write-Host "--> 4 GUI : $($results['4 GUI'])"

  Step '5 classroom case (3PTB trypsin + benzamidine)'
  Set-Location $base
  $j = (& $md20 pipeline example 2>$null | Out-String)
  $j = $j.Substring([Math]::Max(0, $j.IndexOf('{')))
  $j = [regex]::Replace($j, '"tier"\s*:\s*"[^"]*"', '"tier": "classroom"')
  $cfg = Join-Path $base 'trypsin.json'
  [IO.File]::WriteAllText($cfg, $j, (New-Object Text.UTF8Encoding($false)))
  Get-Content $cfg | Out-Host
  Run '5 pipeline run' { & $md20 pipeline run $cfg --project laptop_test } | Out-Null
  $projDir = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'MD20_Projects\laptop_test'
  Write-Host "project dir: $projDir"
  Get-ChildItem -Path $projDir -Recurse -Filter 'report.html' -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "report: $($_.FullName)" }
}

Step 'SUMMARY'
$results.GetEnumerator() | ForEach-Object { Write-Host ("{0,-18} {1}" -f $_.Key, $_.Value) }
Write-Host "log: $log"
Stop-Transcript | Out-Null
Start-Process explorer.exe $base
