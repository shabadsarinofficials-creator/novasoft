@echo off
setlocal EnableExtensions
chcp 65001 >nul
title BizSuite Server Connection Setup
echo =====================================================
echo          BizSuite Shared Server Configuration
echo =====================================================
echo Enter the shared API address provided by the administrator.
echo Example: http://192.168.1.25:8000
echo.
set /p SERVER_URL=Server URL: 
if "%SERVER_URL%"=="" (echo No server URL entered.& pause & exit /b 1)
set "SERVER_URL=%SERVER_URL: =%"
set "URL_PREFIX=%SERVER_URL:~0,7%"
if /i "%URL_PREFIX%"=="http://" goto url_valid
set "URL_PREFIX=%SERVER_URL:~0,8%"
if /i "%URL_PREFIX%"=="https://" goto url_valid
echo URL must start with http:// or https://.
pause
exit /b 1
:url_valid
if not "%SERVER_URL:~-1%"=="/" goto url_ok
set "SERVER_URL=%SERVER_URL:~0,-1%"
:url_ok
for %%D in ("BizSuite Admin" "BizSuite Manager" "BizSuite Employee" "BizSuite Workspace") do if not exist "%APPDATA%\%%~D" mkdir "%APPDATA%\%%~D"
>"%APPDATA%\BizSuite Admin\config.json" echo {"apiBase":"%SERVER_URL%"}
>"%APPDATA%\BizSuite Manager\config.json" echo {"apiBase":"%SERVER_URL%"}
>"%APPDATA%\BizSuite Employee\config.json" echo {"apiBase":"%SERVER_URL%"}
>"%APPDATA%\BizSuite Workspace\config.json" echo {"apiBase":"%SERVER_URL%"}
echo.
echo All BizSuite apps are now configured to use:
echo %SERVER_URL%
echo Restart BizSuite apps to apply the setting.
pause
