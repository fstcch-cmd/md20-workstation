<# : batch part (cmd sees this; PowerShell treats it as a comment)
@echo off
rem MD20 OWNER TOOL: sign licence files for students with your private key.  Do not give this file to students.
rem The private key is only read; it is never copied, and nothing about it is written to disk by this tool.
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
Add-Type -AssemblyName Microsoft.VisualBasic
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
$key = $k.FileName

$out = Join-Path ([Environment]::GetFolderPath('Desktop')) ('MD20_licenses\' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Force -Path $out | Out-Null

$batch = [System.Windows.Forms.MessageBox]::Show("Yes = one person (you type the name)`nNo = many people from a CSV file (name, days or YYYY-MM-DD, machine code)", 'MD20 licence', 'YesNoCancel', 'Question')
if ($batch -eq 'Cancel') { exit 0 }
if ($batch -eq 'Yes') {
  $name = [Microsoft.VisualBasic.Interaction]::InputBox('Student name', 'MD20 licence', '')
  if (-not $name.Trim()) { Write-Host 'No name. Nothing was done.'; exit 0 }
  $days = [Microsoft.VisualBasic.Interaction]::InputBox('Valid for how many days, or an end date YYYY-MM-DD. Leave empty for no expiry.', 'MD20 licence', '365')
  $mach = [Microsoft.VisualBasic.Interaction]::InputBox('Machine code of the student''s computer (from MD20-Unlock). Leave empty for any computer.', 'MD20 licence', '')
  # one CSV row, UTF-8: a Chinese name must not travel through the cmd command line
  $csv = Join-Path $out '_input.csv'
  $line = '"' + $name.Replace('"', '""') + '","' + $days.Trim() + '","' + $mach.Trim() + '"'
  [IO.File]::WriteAllText($csv, $line + "`r`n", (New-Object Text.UTF8Encoding($true)))
} else {
  $c = New-Object System.Windows.Forms.OpenFileDialog
  $c.Title = 'Choose the CSV list (name, days or YYYY-MM-DD, machine code)'
  $c.Filter = 'CSV (*.csv)|*.csv|All files (*.*)|*.*'
  if ($c.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { Write-Host 'No file chosen. Nothing was done.'; exit 0 }
  $csv = $c.FileName
}
& $md20 license issue-batch --key "$key" --csv "$csv" --out "$out" | Out-Host
$rc = $LASTEXITCODE
if ($rc -eq 0) { Write-Host "`nLicence files are in: $out  (issued.csv lists them)"; Start-Process explorer.exe $out }
else { Write-Host "`nNo licence was written (exit $rc). Read the message above." }
exit $rc
