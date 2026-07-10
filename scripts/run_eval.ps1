[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RunnerArgs
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$python = Join-Path $backend '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) {
    throw 'Python environment not found. Run scripts\setup.ps1 first.'
}

$env:PYTHONPATH = $backend
& $python -m app.memory_arena.runner @RunnerArgs
exit $LASTEXITCODE
