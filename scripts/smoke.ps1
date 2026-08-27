# 交付冒烟入口（Windows）：调用 scripts\smoke.py 对运行中的服务做 HTTP 冒烟（覆盖范围见 smoke.py 头部注释）。
[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://127.0.0.1:8010',
    [string]$ApiKey = $env:WANWEI_API_KEY,
    [double]$Timeout = 10
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ApiKey)) {
    throw 'API key is required. Pass -ApiKey or set WANWEI_API_KEY.'
}
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Python environment not found. Run scripts\setup.ps1 first.'
}

& $python (Join-Path $PSScriptRoot 'smoke.py') --base-url $BaseUrl --api-key $ApiKey --timeout $Timeout
exit $LASTEXITCODE
