@echo off
rem MD20 isolated check of the integration-spec P0 batch (D-96, D-97, D-98).
rem Put this file and MD20-DevCheck.cmd in an empty folder and double-click this one.
rem Installs the latest main branch into <this folder>\MD20dev (separate from %LOCALAPPDATA%\MD20 and C:\MD20dev),
rem runs the P0 tests and the full 3PTB workflow on this computer's GPU, and writes the log next to this file.
set "MD20_DEVCHECK=p0"
set "MD20_DEVCHECK_DIR=%~dp0"
if "%MD20_DEVCHECK_DIR:~-1%"=="\" set "MD20_DEVCHECK_DIR=%MD20_DEVCHECK_DIR:~0,-1%"
if not exist "%~dp0MD20-DevCheck.cmd" (
  echo MD20-DevCheck.cmd was not found next to this file.
  pause
  exit /b 1
)
call "%~dp0MD20-DevCheck.cmd"
