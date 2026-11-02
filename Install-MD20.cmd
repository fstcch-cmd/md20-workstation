@echo off
rem MD20 Windows installer - double-click this file (no git, no PowerShell knowledge needed).
rem Options are passed through, e.g.:  Install-MD20.cmd -Gpu opencl   or   Install-MD20.cmd -Root D:\MD20
set PYTHONUTF8=1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1" %*
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" echo Installation stopped with exit code %RC%. Copy the messages above and send them to the developer.
if "%RC%"=="0" echo Done. Double-click MD20-GUI.cmd on the desktop to start.
if not defined MD20_NOPAUSE pause
exit /b %RC%
