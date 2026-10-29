@echo off
rem today-board uninstaller (double-click this file). No admin rights required.
rem All the work is done by uninstall.ps1 in the same folder.
chcp 65001 >nul 2>nul
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
set RC=%ERRORLEVEL%

echo.
pause
exit /b %RC%
