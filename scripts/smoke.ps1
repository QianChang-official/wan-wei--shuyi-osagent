[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://127.0.0.1:8010',
    [string]$ApiKey = 'wanwei-dev-key',
    [double]$Timeout = 10
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Python environment not found. Run scripts\setup.ps1 first.'
}

& $python (Join-Path $PSScriptRoot 'smoke.py') --base-url $BaseUrl --api-key $ApiKey --timeout $Timeout
exit $LASTEXITCODE
