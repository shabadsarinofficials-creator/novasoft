$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$db = Join-Path $root 'backend\bizsuite.db'
$secret = Join-Path $root 'backend\jwt.secret'
if (!(Test-Path $python) -or !(Test-Path $db) -or !(Test-Path $secret)) {
  Write-Host 'Run run_admin.bat once and finish the first administrator setup before enabling auto-start.' -ForegroundColor Yellow
  exit 1
}
$wrapper = Join-Path $root 'start-server-hidden.vbs'
$action = New-ScheduledTaskAction -Execute "$env:WINDIR\System32\wscript.exe" -Argument ('"' + $wrapper + '"')
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'BizSuite Shared Server' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Starts the shared BizSuite company API in the background when this user signs in.' -Force | Out-Null
Write-Host 'BizSuite Shared Server will now start in the background whenever you sign in to Windows.' -ForegroundColor Green
Write-Host 'To start it now, run start-server-hidden.vbs once or sign out and sign back in.'
