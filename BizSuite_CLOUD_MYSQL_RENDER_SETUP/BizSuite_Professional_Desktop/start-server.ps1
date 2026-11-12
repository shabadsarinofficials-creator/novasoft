$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backend = Join-Path $root 'backend'
$python = Join-Path $root '.venv\Scripts\python.exe'
$secretFile = Join-Path $backend 'jwt.secret'
$dbFile = Join-Path $backend 'bizsuite.db'
$logFile = Join-Path $backend 'server.log'
if (!(Test-Path $python) -or !(Test-Path $secretFile)) {
  Add-Content -Path $logFile -Value "[$(Get-Date -Format o)] BizSuite server prerequisites are missing. Launch run_admin.bat to complete first-time setup."
  exit 2
}
try {
  $health = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/openapi.json' -TimeoutSec 2 -UseBasicParsing
  if ($health.StatusCode -eq 200) { exit 0 }
} catch {}
$env:JWT_SECRET = (Get-Content -Raw $secretFile).Trim()
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
Set-Location $backend
Add-Content -Path $logFile -Value "[$(Get-Date -Format o)] Starting BizSuite API on port 8000."
& $python -m uvicorn main:app --host 0.0.0.0 --port 8000 *>> $logFile
