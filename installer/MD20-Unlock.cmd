<# : batch part (cmd sees this; PowerShell treats it as a comment)
@echo off
rem MD20 unlock (student): import the licence file (.md20license) your instructor sent you.
rem Drag the file onto this icon, or double-click and choose the file.  Also shows this computer's machine code.
chcp 65001 >nul
set PYTHONUTF8=1
set "MD20_UNLOCK=%~f0"
set "MD20_UNLOCK_FILE=%~1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "iex (Get-Content -LiteralPath $env:MD20_UNLOCK -Raw)"
echo.
if not defined MD20_NOPAUSE pause
exit /b
: end of batch part #>

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$here = Split-Path -Parent $env:MD20_UNLOCK
$cands = @()
if ($env:MD20_ROOT) { $cands += (Join-Path $env:MD20_ROOT 'md20.cmd') }
$cands += (Join-Path $here 'md20.cmd')
$cands += (Join-Path $here '..\..\md20.cmd')
if ($env:LOCALAPPDATA) { $cands += (Join-Path $env:LOCALAPPDATA 'MD20\md20.cmd') }
$md20 = $cands | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $md20) {
  Write-Host 'MD20 is not installed on this computer. Run Install-MD20.cmd first, then run this again.'
  exit 1
}
$md20 = (Resolve-Path $md20).Path

Write-Host '=== MD20 unlock ==='
$code = ((& $md20 license machine 2>$null | Out-String).Trim())
Write-Host "Machine code of this computer: $code"
try { Set-Clipboard -Value $code; Write-Host '(copied to the clipboard; send it to your instructor when you ask for a licence)' } catch {}
Write-Host ''

$file = $env:MD20_UNLOCK_FILE
if (-not $file) {
  Add-Type -AssemblyName System.Windows.Forms
  $dlg = New-Object System.Windows.Forms.OpenFileDialog
  $dlg.Title = 'Choose the MD20 licence file (.md20license)'
  $dlg.Filter = 'MD20 licence (*.md20license)|*.md20license|All files (*.*)|*.*'
  $dlg.InitialDirectory = [Environment]::GetFolderPath('Desktop')
  if ($dlg.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
    Write-Host 'No file chosen. Nothing was changed.'
    exit 0
  }
  $file = $dlg.FileName
}
Write-Host "Licence file: $file"
& $md20 license install "$file" | Out-Host
if ($LASTEXITCODE -eq 0) { Write-Host ''; Write-Host 'Done. MD20 is unlocked on this computer.' }
else { Write-Host ''; Write-Host 'The licence was NOT installed. Read the message above, or send a photo of this window to your instructor.' }
exit $LASTEXITCODE
