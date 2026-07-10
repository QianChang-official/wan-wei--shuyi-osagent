[CmdletBinding()]
param(
    [ValidateSet('create', 'verify', 'restore')]
    [string]$Action = 'create',
    [string]$Path,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Python environment not found. Run scripts\setup.ps1 first.'
}

$env:PYTHONPATH = Join-Path $root 'backend'
if ($Action -eq 'create') {
    $arguments = @('-m', 'app.operations.backup', 'create')
    if ($Path) { $arguments += @('--output', $Path) }
}
elseif ($Action -eq 'verify') {
    if (-not $Path) { throw 'Verify requires -Path.' }
    $arguments = @('-m', 'app.operations.backup', 'verify', '--input', $Path)
}
else {
    if (-not $Path) { throw 'Restore requires -Path.' }
    if (-not $Force) { throw 'Restore requires -Force after the service has been stopped.' }
    $arguments = @('-m', 'app.operations.backup', 'restore', '--input', $Path, '--force')
}

& $python @arguments
exit $LASTEXITCODE
