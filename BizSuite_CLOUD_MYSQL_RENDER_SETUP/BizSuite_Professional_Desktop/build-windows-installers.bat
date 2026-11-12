@echo off
setlocal EnableExtensions
chcp 65001 >nul
title BizSuite — Build All Windows Installers
cd /d "%~dp0"
echo Use the role-specific launchers for the recommended first-run setup:
echo   run_admin.bat
 echo  run_manager.bat
 echo  run_employee.bat
echo Each launcher installs its own app and then opens it.
echo To build all three, run the three BAT files one at a time.
pause
