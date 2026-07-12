[CmdletBinding()]
param(
    [string]$Path,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $Path) { $Path = Join-Path $root 'secrets\wanwei_api_key.txt' }
$resolvedParent = Split-Path -Parent $Path
if (Test-Path -LiteralPath $Path) {
    if (-not $Force) { throw "Secret already exists: $Path. Use -Force to rotate it." }
}
else {
    New-Item -ItemType Directory -Force -Path $resolvedParent | Out-Null
}

$bytes = [byte[]]::new(48)
[System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
$key = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
$encoding = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($Path, $key + [Environment]::NewLine, $encoding)

# Restrict file to owner-only (mirrors chmod 600 on Linux)
$acl = Get-Acl -LiteralPath $Path
$acl.SetAccessRuleProtection($true, $false)
$rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
    [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
    'FullControl', 'Allow'
)
$acl.SetAccessRule($rule)
Set-Acl -LiteralPath $Path -AclObject $acl

Write-Host "Secret created at $Path. The value was not printed." -ForegroundColor Green
