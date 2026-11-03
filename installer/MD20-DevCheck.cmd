<# : batch part (cmd sees this; PowerShell treats it as a comment)
@echo off
rem MD20 developer check (D-81): installs the latest main branch into C:\MD20dev (separate from the normal install)
rem and runs the key real-environment checks: GPU doctor, membrane and long-run engine tests, folding, coarse-grained tools.
rem Double-click.  Log: Desktop\MD20_test\devcheck_<time>.log.  Does not touch %LOCALAPPDATA%\MD20.
set "MD20_SELF=%~f0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set "PATH=%SystemRoot%\system32;%SystemRoot%;%SystemRoot%\System32\Wbem;%SystemRoot%\System32\WindowsPowerShell\v1.0;%ProgramFiles%\NVIDIA Corporation\NVSMI"
powershell -NoProfile -ExecutionPolicy Bypass -Command "iex (Get-Content -LiteralPath $env:MD20_SELF -Raw)"
echo.
echo Developer check finished. The log is in Desktop\MD20_test.
pause
exit /b
: end of batch part #>

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$env:MD20_NOPAUSE = '1'
$env:MD20_NO_DESKTOP = '1'
$base = Join-Path ([Environment]::GetFolderPath('Desktop')) 'MD20_test'
New-Item -ItemType Directory -Force -Path $base | Out-Null
$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$log = Join-Path $base "devcheck_$ts.log"
$out = Join-Path $base "devcheck_$ts"
New-Item -ItemType Directory -Force -Path $out | Out-Null
Start-Transcript -Path $log | Out-Null
$results = [ordered]@{}
function Run([string]$name, [scriptblock]$sb) {
  Write-Host ""; Write-Host ("===== {0}   {1} =====" -f $name, (Get-Date -Format 'HH:mm:ss'))
  $t0 = Get-Date; $global:LASTEXITCODE = 0
  try { & $sb 2>&1 | Out-Host; $rc = $LASTEXITCODE } catch { Write-Host "EXCEPTION: $_"; $rc = -1 }
  $min = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
  $results[$name] = "rc=$rc  $min min"
  Write-Host ("----- {0}: rc={1} ({2} min)" -f $name, $rc, $min)
}
$branch = if ($env:MD20_BRANCH) { $env:MD20_BRANCH } else { 'main' }
$root = 'C:\MD20dev'
$src = Join-Path $env:TEMP "md20dev_src_$ts"
Run 'download source' {
  $zip = "$src.zip"
  Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/fstcch-cmd/md20-workstation/archive/refs/heads/$branch.zip" -OutFile $zip
  Expand-Archive -Path $zip -DestinationPath $src -Force
  Get-ChildItem $src | Select-Object -First 1 | ForEach-Object { $script:srcdir = $_.FullName; Write-Host "source: $($_.FullName)" }
}
Run 'install into C:\MD20dev' { & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $script:srcdir 'installer\install.ps1') -Root $root }
$md20 = Join-Path $root 'md20.cmd'
$mamba = Join-Path $root 'micromamba.exe'
$env:MAMBA_ROOT_PREFIX = $root
$app = Join-Path $root 'app'
Run 'version and doctor' { & $md20 --help | Select-Object -First 3; & $md20 doctor --no-benchmark }
Run 'pytest available' { & $mamba run -p "$root\envs\md20" python -m pip install -q pytest }
Push-Location $app
Run 'membrane and long-run engine tests' {
  & $mamba run -p "$root\envs\md20" python -m pytest -q -rxs tests/test_membrane.py tests/test_membrane_integration.py tests/test_longrun.py tests/test_longrun_integration.py tests/test_stream.py
}
Run 'fold unit tests' { & $mamba run -p "$root\envs\md20" python -m pytest -q -rs tests/test_fold.py }
Pop-Location
Run 'setup-fold omegafold (install)' { & $md20 setup-fold --engine omegafold --yes }
Run 'fold melittin (GPU)' { & $md20 fold GIGAVLKVLTTGLPALISWIKRKRQQ --out (Join-Path $out 'fold_melittin') }
Run 'setup-cg (install)' { & $md20 setup-cg --yes }
Push-Location $app
Run 'martini tests' { & $mamba run -p "$root\envs\md20" python -m pytest -q -rs tests/test_martini.py }
Pop-Location
Run 'nvidia-smi' { nvidia-smi }
Write-Host ""; Write-Host "===== SUMMARY ====="
$results.GetEnumerator() | ForEach-Object { Write-Host ("{0,-40} {1}" -f $_.Key, $_.Value) }
Stop-Transcript | Out-Null
