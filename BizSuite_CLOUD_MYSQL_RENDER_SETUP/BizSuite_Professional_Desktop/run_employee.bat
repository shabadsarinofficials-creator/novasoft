@echo off
setlocal EnableExtensions
chcp 65001 >nul
title BizSuite Employee Setup and Launcher
cd /d "%~dp0"
echo =====================================================
echo        BizSuite Professional Desktop 1.3.0
echo        First run performs setup automatically
echo =====================================================
echo Keep this window open while the first-time checks run.
echo The first setup can take a while and needs internet access.
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0first-run-setup.ps1" -App employee
if errorlevel 1 (
  echo.
  echo BizSuite setup did not finish. Read the error above, then run this BAT again.
  pause
  exit /b 1
)
exit /b 0
