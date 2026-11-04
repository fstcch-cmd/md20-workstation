@echo off
rem MD20 Windows installer - double-click this file (no git, no PowerShell knowledge needed).
rem Options are passed through, e.g.:  Install-MD20.cmd -Gpu opencl   or   Install-MD20.cmd -Root D:\MD20
rem D-91: Windows lets you double-click a file inside a ZIP without extracting it; it then copies only this one file
rem to a Temp folder and installer\install.ps1 is missing.  Stop with a clear message instead of a PowerShell error.
if exist "%~dp0installer\install.ps1" goto :install
chcp 65001 >nul
echo.
echo ============================================================
echo  請先解壓縮 ZIP，再執行安裝。
echo  1. 關掉這個視窗。
echo  2. 在下載的 MD20-Windows-*.zip 上按右鍵，選「解壓縮全部」。
echo  3. 打開解壓出來的資料夾，雙擊裡面的 Install-MD20.cmd。
echo.
echo  Please extract the ZIP first: right-click MD20-Windows-*.zip,
echo  choose "Extract All", then double-click Install-MD20.cmd in the
echo  extracted folder. (Running it from inside the ZIP does not work.)
echo ============================================================
echo.
if not defined MD20_NOPAUSE pause
exit /b 3
:install
set PYTHONUTF8=1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1" %*
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" echo Installation stopped with exit code %RC%. Copy the messages above and send them to the developer.
if "%RC%"=="0" echo Done. Double-click MD20-GUI.cmd on the desktop to start.
if not defined MD20_NOPAUSE pause
exit /b %RC%
