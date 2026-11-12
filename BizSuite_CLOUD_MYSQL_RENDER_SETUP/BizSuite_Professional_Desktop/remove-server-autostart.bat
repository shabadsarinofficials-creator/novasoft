@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Unregister-ScheduledTask -TaskName 'BizSuite Shared Server' -Confirm:$false -ErrorAction SilentlyContinue; Write-Host 'BizSuite server auto-start task removed.'"
pause
