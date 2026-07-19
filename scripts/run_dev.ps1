# 本地开发启动（Windows）：以 backend\.venv 运行 uvicorn，默认 127.0.0.1:8010；venv 缺失时明确提示先跑 setup.ps1。
[CmdletBinding()]
param(
    [int]$Port = 8010,
    [string]$BindAddress = '127.0.0.1',
    [switch]$Production
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$python = Join-Path $backend '.venv\Scripts\python.exe'
$dist = Join-Path $root 'frontend\console-vue\dist\index.html'

if (-not (Test-Path -LiteralPath $python)) {
    throw 'Python environment not found. Run scripts\setup.ps1 first.'
}
if (-not (Test-Path -LiteralPath $dist)) {
    throw 'Frontend build not found. Run scripts\setup.ps1 first.'
}

if ([string]::IsNullOrWhiteSpace($env:WANWEI_MEMORY_DB)) {
    $runtimeDir = Join-Path $root 'data\runtime'
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    $env:WANWEI_MEMORY_DB = Join-Path $runtimeDir 'memory.db'
}

if ($Production) {
    $env:WANWEI_PRODUCTION = '1'
    if ([string]::IsNullOrWhiteSpace($env:WANWEI_API_KEY)) {
        throw 'Production mode requires WANWEI_API_KEY.'
    }
}

Write-Host "Starting API and console at http://${BindAddress}:$Port/console/" -ForegroundColor Cyan
& $python -m uvicorn app.main:app --app-dir $backend --host $BindAddress --port $Port --no-proxy-headers
exit $LASTEXITCODE
