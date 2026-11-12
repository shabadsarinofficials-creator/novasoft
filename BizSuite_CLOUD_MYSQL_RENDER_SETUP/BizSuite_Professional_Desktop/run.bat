@echo off
setlocal EnableExtensions
chcp 65001 >nul
title BizSuite Setup and Launcher
cd /d "%~dp0"

echo.
echo  =====================================================
echo                    BizSuite
echo      Employee access ^| Admin ^| Shared data store
echo  =====================================================
echo.

set "PYTHON_CMD=python"
where py >nul 2>&1
if not errorlevel 1 (
  py -3.12 --version >nul 2>&1
  if not errorlevel 1 set "PYTHON_CMD=py -3.12"
)
if "%PYTHON_CMD%"=="python" (
  where python >nul 2>&1 || (
    echo ERROR: Python 3.12 was not found.
    echo Install Python 3.12 from https://www.python.org/downloads/ and enable "Add Python to PATH".
    pause
    exit /b 1
  )
  python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1 || (
    echo ERROR: This project uses pinned packages tested for Python 3.12.
    echo Install Python 3.12 or enable the Python launcher so that "py -3.12" works.
    pause
    exit /b 1
  )
)
where npm >nul 2>&1 || (
  echo ERROR: Node.js and npm were not found on PATH.
  echo Install the current LTS version from https://nodejs.org/ and reopen this window.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/5] Creating an isolated Python environment...
  %PYTHON_CMD% -m venv .venv || (echo Could not create Python environment.& pause & exit /b 1)
) else (
  echo [1/5] Python environment already exists.
)

echo [2/5] Installing backend dependencies (first run may take a few minutes)...
"%~dp0.venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r "%~dp0backend\requirements.txt" || (
  echo ERROR: Python packages could not be installed. Check your internet connection.
  pause
  exit /b 1
)

if not exist "backend\jwt.secret" (
  "%~dp0.venv\Scripts\python.exe" -c "import secrets; print(secrets.token_hex(32))" > "backend\jwt.secret"
)
set /p JWT_SECRET=<"backend\jwt.secret"

if not exist "backend\bizsuite.db" (
  echo.
  echo First-time setup: create the administrator account.
  set /p ADMIN_EMAIL=Administrator email: 
  set /p ADMIN_PASSWORD=Administrator password: 
)
if not exist "backend\bizsuite.db" if not defined ADMIN_EMAIL (echo Email cannot be blank.& pause & exit /b 1)
if not exist "backend\bizsuite.db" if not defined ADMIN_PASSWORD (echo Password cannot be blank.& pause & exit /b 1)
if not exist "backend\bizsuite.db" (
  %PYTHON_CMD% -c "import os,sys; sys.exit(0 if len(os.environ.get('ADMIN_PASSWORD','')) >= 12 else 1)" >nul 2>&1 || (
    echo ERROR: Choose an administrator password with at least 12 characters.
    pause
    exit /b 1
  )
)

if not exist "admin-app\node_modules\electron" (
  echo [3/5] Installing Admin desktop-app dependencies...
  pushd admin-app
  call npm install || (popd & echo Admin app dependency install failed.& pause & exit /b 1)
  popd
) else (echo [3/5] Admin app dependencies are ready.)

if not exist "employee-app\node_modules\electron" (
  echo [4/5] Installing Employee desktop-app dependencies...
  pushd employee-app
  call npm install || (popd & echo Employee app dependency install failed.& pause & exit /b 1)
  popd
) else (echo [4/5] Employee app dependencies are ready.)

echo [5/5] Starting BizSuite API...
netstat -ano | findstr /C:"127.0.0.1:8000" | findstr LISTENING >nul
if errorlevel 1 (
  start "BizSuite API" /min /d "%~dp0backend" "%~dp0.venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000
) else (
  echo An application is already listening on port 8000. Reusing it.
)

for /l %%i in (1,1,30) do (
  curl -fsS http://127.0.0.1:8000/openapi.json -o nul >nul 2>&1 && goto server_ready
  timeout /t 1 >nul
)
echo ERROR: BizSuite API did not respond on port 8000.
echo Open the minimized "BizSuite API" window to inspect the error.
pause
exit /b 1

:server_ready
rem The API already inherited these values; do not pass credentials into Electron child processes.
set "ADMIN_EMAIL="
set "ADMIN_PASSWORD="
set "JWT_SECRET="
echo Starting the two desktop apps...
start "BizSuite Admin" /d "%~dp0admin-app" cmd /c "npm start"
start "BizSuite Employee" /d "%~dp0employee-app" cmd /c "npm start"
echo.
echo BizSuite is running. Leave the minimized API window open while using the apps.
echo If this is a fresh installation, sign in with the admin email and password you entered above.
echo.
pause
