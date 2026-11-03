@echo off
rem MD20 peptide folding (OmegaFold) - double-click AFTER Install-MD20.cmd has finished (D-85).
rem Downloads PyTorch and the model weights (several GB, 20-60 minutes), then folds one test peptide.
rem Custom install folder:  Install-Folding.cmd D:\MD20
set PYTHONUTF8=1
set "ROOT=%~1"
if "%ROOT%"=="" if defined MD20_ROOT set "ROOT=%MD20_ROOT%"
if "%ROOT%"=="" set "ROOT=%LOCALAPPDATA%\MD20"
if not exist "%ROOT%\md20.cmd" (
  echo MD20 is not installed in %ROOT%. Run Install-MD20.cmd first.
  if not defined MD20_NOPAUSE pause
  exit /b 2
)
call "%ROOT%\md20.cmd" setup-fold --engine omegafold --yes --warmup
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" echo Folding setup stopped with exit code %RC%. Copy the messages above and send them to the teacher.
if "%RC%"=="0" echo Done. Peptide sequences typed in the ligand box are now folded automatically.
if not defined MD20_NOPAUSE pause
exit /b %RC%
