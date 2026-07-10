[CmdletBinding()]
param(
    [switch]$SkipFrontendBuild
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend\console-vue'
$venvPython = Join-Path $backend '.venv\Scripts\python.exe'

$python = (Get-Command python -ErrorAction Stop).Source
Get-Command node -ErrorAction Stop | Out-Null
Get-Command npm -ErrorAction Stop | Out-Null

& $python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.10 or newer is required.'
}

$nodeVersion = [version]((node --version).Trim() -replace '^v', '')
if ($nodeVersion -lt [version]'20.0.0') {
    throw "Node.js 20 or newer is required; found $nodeVersion."
}
$npmVersion = [version]((npm --version).Trim())
if ($npmVersion -lt [version]'10.0.0') {
    throw "npm 10 or newer is required; found $npmVersion."
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    & $python -m venv (Join-Path $backend '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the Python virtual environment.' }
}

$pipCache = Join-Path $root '.cache\pip'
New-Item -ItemType Directory -Force -Path $pipCache | Out-Null
$env:PIP_CACHE_DIR = $pipCache
& $venvPython -m pip install -r (Join-Path $backend 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Failed to install Python dependencies.' }

$npmCache = Join-Path $root '.cache\npm'
New-Item -ItemType Directory -Force -Path $npmCache | Out-Null
$env:npm_config_cache = $npmCache

Push-Location $frontend
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw 'Failed to install frontend dependencies.' }
    if (-not $SkipFrontendBuild) {
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Failed to build the frontend.' }
    }
}
finally {
    Pop-Location
}

$runtimeDir = Join-Path $root 'data\runtime'
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
$env:WANWEI_MEMORY_DB = Join-Path $runtimeDir 'memory.db'
$env:PYTHONPATH = $backend
& $venvPython -m app.init_db
if ($LASTEXITCODE -ne 0) { throw 'Failed to initialize the SQLite database.' }

Write-Host ''
Write-Host 'Setup complete.' -ForegroundColor Green
Write-Host 'Start:   powershell -ExecutionPolicy Bypass -File .\scripts\run_dev.ps1'
Write-Host 'Console: http://127.0.0.1:8010/console/'
