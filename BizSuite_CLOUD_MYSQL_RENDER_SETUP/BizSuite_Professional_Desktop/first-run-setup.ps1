param(
  [Parameter(Mandatory=$true)]
  [ValidateSet('admin','manager','employee')]
  [string]$App
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$version = '1.3.0'
$tools = Join-Path $root '.tools'
$downloads = Join-Path $tools 'downloads'
New-Item -ItemType Directory -Force -Path $tools,$downloads | Out-Null
$script:NodeExe = $null
$script:PythonExe = $null

function Say([string]$Message) { Write-Host "`n[$(Get-Date -Format 'HH:mm:ss')] $Message" -ForegroundColor Cyan }
function Fail([string]$Message) { Write-Host "`nSETUP FAILED: $Message" -ForegroundColor Red; Write-Host 'Fix the displayed issue and run this same BAT file again.' -ForegroundColor Yellow; exit 1 }
function Test-Url([string]$Url) { try { Invoke-WebRequest -Uri $Url -TimeoutSec 3 -UseBasicParsing | Out-Null; return $true } catch { return $false } }

function Ensure-Node {
  if ($script:NodeExe -and (Test-Path $script:NodeExe)) { return }
  $localNode = Join-Path $tools 'node\node.exe'
  if (Test-Path $localNode) { $script:NodeExe=$localNode; return }
  try {
    $globalNode = (Get-Command node.exe -ErrorAction Stop).Source
    $major = [int]((& $globalNode -v).Trim().TrimStart('v').Split('.')[0])
    $globalNpm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($major -ge 20 -and $globalNpm) { $script:NodeExe=$globalNode; $env:PATH=(Split-Path $globalNode)+';'+$env:PATH; return }
  } catch {}
  Say 'Node.js was not found (or is too old). Downloading the current Node.js LTS portable runtime...'
  try {
    $index = Invoke-RestMethod -Uri 'https://nodejs.org/dist/index.json' -TimeoutSec 60
    $release = $index | Where-Object { $_.lts -and $_.files -contains 'win-x64-zip' } | Select-Object -First 1
    if (!$release) { throw 'Could not find a Windows x64 LTS build.' }
    $nodeVersion = $release.version
    $zipPath = Join-Path $downloads "node-$nodeVersion-win-x64.zip"
    $url = "https://nodejs.org/dist/$nodeVersion/node-$nodeVersion-win-x64.zip"
    Invoke-WebRequest -Uri $url -OutFile $zipPath -TimeoutSec 600
    $extract = Join-Path $downloads 'node-extract'
    Remove-Item $extract -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive -Path $zipPath -DestinationPath $extract -Force
    $source = Get-ChildItem $extract -Directory | Select-Object -First 1
    if (!$source -or !(Test-Path (Join-Path $source.FullName 'node.exe'))) { throw 'The Node.js archive did not contain node.exe.' }
    $target = Join-Path $tools 'node'
    Remove-Item $target -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    Copy-Item (Join-Path $source.FullName '*') $target -Recurse -Force
    $script:NodeExe = Join-Path $target 'node.exe'
    $env:PATH = "$target;$env:PATH"
    Write-Host "Node.js $nodeVersion is ready." -ForegroundColor Green
  } catch { Fail "Could not install Node.js automatically. $($_.Exception.Message) Check internet access and retry." }
}
function Ensure-Npm {
  Ensure-Node
  $nodeDir = Split-Path $script:NodeExe
  $npmCmd = Join-Path $nodeDir 'npm.cmd'
  if (!(Test-Path $npmCmd)) { $npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source }
  if (!$npmCmd -or !(Test-Path $npmCmd)) { Fail 'npm.cmd is missing. The Node.js setup is incomplete.' }
  $script:NpmCmd = $npmCmd
  $env:PATH = "$nodeDir;$env:PATH"
}
function Ensure-Python {
  if ($script:PythonExe -and (Test-Path $script:PythonExe)) { return }
  $localPy = Join-Path $tools 'python312\python.exe'
  if (Test-Path $localPy) { $script:PythonExe=$localPy; return }
  try {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
      $candidate = (& $launcher.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null | Select-Object -First 1)
      if ($candidate -and (Test-Path $candidate.Trim())) { $script:PythonExe=$candidate.Trim(); return }
    }
  } catch {}
  Say 'Python 3.12 was not found. Downloading and installing a private Python runtime for BizSuite...'
  $installer = Join-Path $downloads 'python-3.12.10-amd64.exe'
  try {
    if (!(Test-Path $installer)) { Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $installer -TimeoutSec 600 }
    $target = Join-Path $tools 'python312'
    $args = "/quiet InstallAllUsers=0 TargetDir=`"$target`" Include_pip=1 Include_launcher=0 Include_test=0 Include_doc=0 PrependPath=0 Shortcuts=0"
    $p = Start-Process -FilePath $installer -ArgumentList $args -Wait -PassThru
    if ($p.ExitCode -notin @(0,3010)) { throw "Python installer returned exit code $($p.ExitCode)." }
    if (!(Test-Path (Join-Path $target 'python.exe'))) { throw 'python.exe was not found after installation.' }
    $script:PythonExe=Join-Path $target 'python.exe'
    Write-Host 'Python 3.12 is ready.' -ForegroundColor Green
  } catch { Fail "Could not install Python 3.12 automatically. $($_.Exception.Message) Check internet access and available disk space." }
}
function Ensure-Backend {
  Ensure-Python
  $venvPy = Join-Path $root '.venv\Scripts\python.exe'
  if (!(Test-Path $venvPy)) {
    Say 'Creating the private BizSuite Python environment...'
    & $script:PythonExe -m venv (Join-Path $root '.venv')
    if ($LASTEXITCODE -ne 0 -or !(Test-Path $venvPy)) { Fail 'Could not create the BizSuite Python environment.' }
  }
  $marker = Join-Path $root '.venv\.bizsuite-dependencies-1.3.0'
  if (!(Test-Path $marker)) {
    Say 'Installing and checking backend packages. First run can take several minutes...'
    & $venvPy -m pip install --disable-pip-version-check --upgrade pip
    if ($LASTEXITCODE -ne 0) { Fail 'Could not update pip. Check internet access.' }
    & $venvPy -m pip install --disable-pip-version-check -r (Join-Path $root 'backend\requirements.txt')
    if ($LASTEXITCODE -ne 0) { Fail 'Backend package installation failed. Check internet access and retry.' }
    & $venvPy -c 'import fastapi, uvicorn, sqlalchemy, bcrypt, jwt, pandas, openpyxl, multipart; print("Backend dependency check passed.")'
    if ($LASTEXITCODE -ne 0) { Fail 'One or more backend dependencies failed their import check.' }
    Set-Content -Path $marker -Value $version -Encoding ASCII
  } else {
    & $venvPy -c 'import fastapi, uvicorn, sqlalchemy, bcrypt, jwt, pandas, openpyxl, multipart' 2>$null
    if ($LASTEXITCODE -ne 0) {
      Remove-Item $marker -Force -ErrorAction SilentlyContinue
      Ensure-Backend
      return
    }
  }
  $secretFile = Join-Path $root 'backend\jwt.secret'
  if (!(Test-Path $secretFile)) {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $secret = [BitConverter]::ToString($bytes).Replace('-','').ToLowerInvariant()
    Set-Content -Path $secretFile -Value $secret -NoNewline -Encoding ASCII
  }
  $dbFile = Join-Path $root 'backend\bizsuite.db'
  if (!(Test-Url 'http://127.0.0.1:8000/openapi.json')) {
    $env:JWT_SECRET = (Get-Content -Raw $secretFile).Trim()
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    if (!(Test-Path $dbFile)) {
      Write-Host ''
      Write-Host 'FIRST-TIME COMPANY SETUP' -ForegroundColor Yellow
      Write-Host 'Create the initial administrator. Use a strong password of 12-72 UTF-8 bytes.' -ForegroundColor Yellow
      $email = (Read-Host 'Administrator email').Trim().ToLowerInvariant()
      if ($email -notmatch '^[^\s@]+@[^\s@]+\.[^\s@]+$') { Fail 'The administrator email address is not valid.' }
      $secure = Read-Host 'Administrator password (input hidden)' -AsSecureString
      $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
      try { $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
      $bytes = [Text.Encoding]::UTF8.GetByteCount($password)
      if ($bytes -lt 12 -or $bytes -gt 72) { Fail 'The administrator password must be between 12 and 72 UTF-8 bytes.' }
      $env:ADMIN_EMAIL = $email
      $env:ADMIN_PASSWORD = $password
    }
    Say 'Starting the shared BizSuite API in the background...'
    $ps = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $serverScript = Join-Path $root 'start-server.ps1'
    Start-Process -FilePath $ps -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',("`"$serverScript`"")) -WorkingDirectory $root -WindowStyle Hidden | Out-Null
    Remove-Item Env:ADMIN_EMAIL -ErrorAction SilentlyContinue
    Remove-Item Env:ADMIN_PASSWORD -ErrorAction SilentlyContinue
    $ready = $false
    for ($i=0; $i -lt 60; $i++) {
      Start-Sleep -Seconds 2
      if (Test-Url 'http://127.0.0.1:8000/openapi.json') { $ready=$true; break }
    }
    if (!$ready) {
      $log = Join-Path $root 'backend\server.log'
      if (Test-Path $log) { Get-Content $log -Tail 35 | ForEach-Object { Write-Host $_ } }
      Fail 'The API did not become ready. Check backend\server.log. If Windows Firewall prompts, allow Private networks.'
    }
    Write-Host 'Shared BizSuite API is running.' -ForegroundColor Green
    if (Test-Path (Join-Path $root 'install-server-autostart.ps1')) {
      try { & $ps -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'install-server-autostart.ps1') | Out-Host } catch { Write-Host 'Could not register server auto-start automatically; run install-server-autostart.bat later.' -ForegroundColor Yellow }
    }
  } else { Write-Host 'BizSuite API is already running.' -ForegroundColor Green }
  # On the host PC, default Admin to the local API unless a connection was already configured.
  $adminConfig = Join-Path $env:APPDATA 'BizSuite Admin\config.json'
  if (!(Test-Path $adminConfig)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $adminConfig) | Out-Null
    Set-Content -Path $adminConfig -Value '{"apiBase":"http://127.0.0.1:8000"}' -Encoding UTF8
  }
}
function Get-AppInfo {
  switch ($App) {
    'admin' { return @{ Dir='admin-app'; ExeName='BizSuite Admin.exe'; InstallDir=(Join-Path $env:LOCALAPPDATA 'Programs\BizSuite Admin'); Installer='BizSuite-Admin-Setup-1.3.0.exe' } }
    'manager' { return @{ Dir='manager-app'; ExeName='BizSuite Manager.exe'; InstallDir=(Join-Path $env:LOCALAPPDATA 'Programs\BizSuite Manager'); Installer='BizSuite-Manager-Setup-1.3.0.exe' } }
    'employee' { return @{ Dir='employee-app'; ExeName='BizSuite Employee.exe'; InstallDir=(Join-Path $env:LOCALAPPDATA 'Programs\BizSuite Employee'); Installer='BizSuite-Employee-Setup-1.3.0.exe' } }
  }
}
function Get-InstalledExe($info) { $candidate=Join-Path $info.InstallDir $info.ExeName; if (Test-Path $candidate) { return $candidate }; return $null }
function Is-ExpectedVersion($exe) {
  try { $v=[System.Diagnostics.FileVersionInfo]::GetVersionInfo($exe).ProductVersion; return ($v -and $v.StartsWith($version)) } catch { return $false }
}
function Build-And-Install($info) {
  Ensure-Npm
  $appDir = Join-Path $root $info.Dir
  $installerPath = Join-Path (Join-Path $appDir 'dist') $info.Installer
  if (!(Test-Path $installerPath)) {
    Say "Installing desktop dependencies for $App. This may take a while on the first run..."
    Push-Location $appDir
    try {
      & $script:NpmCmd install --no-audit --no-fund
      if ($LASTEXITCODE -ne 0) { Fail "$App npm dependency installation failed." }
      & $script:NpmCmd rebuild electron
      if ($LASTEXITCODE -ne 0) { Write-Host 'Electron rebuild reported a warning; continuing to the build check.' -ForegroundColor Yellow }
      Say "Building the branded Windows installer for $App..."
      & $script:NpmCmd run build
      if ($LASTEXITCODE -ne 0) { Fail "$App installer build failed. Review the build error above. Symbolic-link errors should be avoided by signAndEditExecutable=false in this release." }
    } finally { Pop-Location }
  }
  if (!(Test-Path $installerPath)) { Fail "The build did not produce $($info.Installer)." }
  Say "Installing $App quietly. Follow any Windows security prompt if shown..."
  $p = Start-Process -FilePath $installerPath -ArgumentList '/S' -Wait -PassThru
  if ($p.ExitCode -ne 0) { Fail "The $App installer returned exit code $($p.ExitCode)." }
  $exe = Get-InstalledExe $info
  if (!$exe) { Fail "Installer finished, but the app was not found at $($info.InstallDir). Check the installer output folder." }
  return $exe
}

try {
  Say "BizSuite Professional Desktop $version — $App setup and launcher"
  if (!(Test-Path (Join-Path $root 'backend\main.py'))) { Fail 'Run this BAT from the extracted BizSuite project folder; backend\main.py is missing.' }
  if ($App -eq 'admin') { Ensure-Backend }
  $info = Get-AppInfo
  $exe = Get-InstalledExe $info
  if (!$exe -or !(Is-ExpectedVersion $exe)) {
    $exe = Build-And-Install $info
  } else {
    Write-Host "$App desktop app is already installed at the current version." -ForegroundColor Green
  }
  if ($App -eq 'manager') {
    $managerConfig = Join-Path $env:APPDATA 'BizSuite Manager\config.json'
    if (!(Test-Path $managerConfig)) { Write-Host 'First launch will ask you to connect to the company server.' -ForegroundColor Yellow }
  }
  if ($App -eq 'employee') {
    $employeeConfig = Join-Path $env:APPDATA 'BizSuite Employee\config.json'
    if (!(Test-Path $employeeConfig)) { Write-Host 'First launch will ask you to connect to the company server.' -ForegroundColor Yellow }
  }
  Say "Launching the installed BizSuite $App app. You can pin its taskbar icon."
  Start-Process -FilePath $exe -WorkingDirectory (Split-Path $exe) | Out-Null
  exit 0
} catch {
  Write-Host "`nSETUP ERROR: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host 'The window will stay open so you can read the error. Fix the issue and run the BAT again.' -ForegroundColor Yellow
  exit 1
}
