@echo off
setlocal
chcp 65001 >nul
title BizSuite Server Auto-start Setup
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-server-autostart.ps1"
if errorlevel 1 (
  echo.
  echo Setup did not complete. Check that the first server setup has been completed.
  pause
  exit /b 1
)
echo.
pause
