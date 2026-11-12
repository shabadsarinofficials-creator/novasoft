@echo off
setlocal EnableExtensions
chcp 65001 >nul
title BizSuite Shared Server
cd /d "%~dp0"
echo =====================================================
echo           BizSuite Shared Company Server
echo =====================================================
echo This computer stores the shared BizSuite database and uploads.
echo Keep this computer on while other employees are using BizSuite.
echo Do NOT expose port 8000 directly to the public internet.
echo.
set "PYTHON_CMD=py -3.12"
%PYTHON_CMD% --version >nul 2>&1 || set "PYTHON_CMD=python"
%PYTHON_CMD% --version >nul 2>&1 || (echo Python 3.12 is required. Install it from https://www.python.org/downloads/ & pause & exit /b 1)
if not exist ".venv\Scripts\python.exe" %PYTHON_CMD% -m venv .venv
"%~dp0.venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "%~dp0backend\requirements.txt" || (echo Dependency install failed.& pause & exit /b 1)
if not exist "backend\jwt.secret" "%~dp0.venv\Scripts\python.exe" -c "import secrets; print(secrets.token_hex(32))" > "backend\jwt.secret"
set /p JWT_SECRET=<"backend\jwt.secret"
if not exist "backend\bizsuite.db" (
  echo First-time server setup: create the administrator account.
  set /p ADMIN_EMAIL=Administrator email: 
  set /p ADMIN_PASSWORD=Administrator password, 12 or more characters: 
)
echo.
echo Starting API on all private network interfaces, port 8000.
echo If Windows Firewall asks, allow access on Private networks only.
echo Find this computer's LAN IPv4 address using ipconfig.
echo Employees should configure their app to http://SERVER-IP:8000
pushd backend
"%~dp0.venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000
popd
pause
