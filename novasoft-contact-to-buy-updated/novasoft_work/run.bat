@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title NovaSoft - Setup and Start

echo.
echo  ================================================
echo       NovaSoft - Automatic Setup and Launcher
echo  ================================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON=py"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo ERROR: Python 3.11 or newer was not found.
        echo Install Python from https://www.python.org/downloads/windows/
        echo During installation, tick "Add Python to PATH".
        pause
        exit /b 1
    )
    set "PYTHON=python"
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creating Python virtual environment...
    %PYTHON% -m venv .venv
    if errorlevel 1 goto :failed
) else (
    echo [1/4] Python virtual environment already exists.
)

echo [2/4] Installing required packages...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo [3/4] Checking runtime configuration...
".venv\Scripts\python.exe" setup_wizard.py
if errorlevel 1 goto :failed

echo [4/4] Starting NovaSoft...
echo Website: http://127.0.0.1:5000
echo Admin setup/login: http://127.0.0.1:5000/admin/login
echo First launch will ask you to create an admin username and password in your browser.
echo Press CTRL+C to stop the server.
echo.
start "" http://127.0.0.1:5000/admin/login
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo Setup or startup failed. Read the error above.
echo If packages could not be downloaded, check your internet connection and run run.bat again.
pause
exit /b 1
