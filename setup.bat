@echo off
rem today-board setup (double-click this file). No admin rights required.
rem All the work is done by setup.ps1 in the same folder.
chcp 65001 >nul 2>nul
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
set RC=%ERRORLEVEL%

echo.
pause
exit /b %RC%
