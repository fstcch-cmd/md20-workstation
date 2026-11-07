<# : batch part (cmd sees this; PowerShell treats it as a comment)
@echo off
rem MD20 OWNER TOOL: sign a licence for THIS computer with your private key and install it (one click for your own PC).
rem Do not give this file to students.  The private key is only read.
chcp 65001 >nul
set PYTHONUTF8=1
set "MD20_TOOL=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "iex (Get-Content -LiteralPath $env:MD20_TOOL -Raw)"
echo.
if not defined MD20_NOPAUSE pause
exit /b
: end of batch part #>

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
Add-Type -AssemblyName System.Windows.Forms
$here = Split-Path -Parent $env:MD20_TOOL
$cands = @()
if ($env:MD20_ROOT) { $cands += (Join-Path $env:MD20_ROOT 'md20.cmd') }
$cands += (Join-Path $here '..\..\..\md20.cmd')
if ($env:LOCALAPPDATA) { $cands += (Join-Path $env:LOCALAPPDATA 'MD20\md20.cmd') }
$md20 = $cands | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $md20) { Write-Host 'MD20 is not installed on this computer. Run Install-MD20.cmd first.'; exit 1 }
$md20 = (Resolve-Path $md20).Path

$k = New-Object System.Windows.Forms.OpenFileDialog
$k.Title = 'Choose your PRIVATE key (md20_owner_private.pem)'
$k.Filter = 'PEM key (*.pem)|*.pem|All files (*.*)|*.*'
if ($k.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { Write-Host 'No key chosen. Nothing was done.'; exit 0 }
$code = ((& $md20 license machine 2>$null | Out-String).Trim())
if (-not $code) { Write-Host 'Could not read the machine code.'; exit 1 }
Write-Host "Machine code of this computer: $code"
$who = 'Owner_' + ($env:COMPUTERNAME -replace '[^A-Za-z0-9_-]', '_')
$out = Join-Path ([Environment]::GetFolderPath('Desktop')) ('MD20_licenses\own_pc_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.md20license')
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $out) | Out-Null
& $md20 license issue --key "$($k.FileName)" --name "$who" --days 3650 --machine "$code" --out "$out" | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Host 'No licence was written. Read the message above.'; exit 1 }
& $md20 license install "$out" | Out-Host
exit $LASTEXITCODE
