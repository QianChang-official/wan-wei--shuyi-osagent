# 生成 API key 密钥文件（secrets\wanwei_api_key.txt）并写入 .env 引用；已存在时拒绝覆盖，除非 -Force。
[CmdletBinding()]
param(
    [string]$Path,
    [string]$EnvPath,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $Path) { $Path = Join-Path $root 'secrets\wanwei_api_key.txt' }
if (-not $EnvPath) { $EnvPath = Join-Path $root '.env' }
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

function Set-EnvValue {
    param(
        [string]$TargetPath,
        [string]$Name,
        [string]$Value
    )

    $parent = Split-Path -Parent $TargetPath
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $lines = if (Test-Path -LiteralPath $TargetPath) {
        [System.IO.File]::ReadAllLines($TargetPath)
    }
    else {
        [string[]]@()
    }
    $updated = [System.Collections.Generic.List[string]]::new()
    $replaced = $false
    $escapedName = [System.Text.RegularExpressions.Regex]::Escape($Name)
    foreach ($line in $lines) {
        if ($line -match "^\s*$escapedName\s*=") {
            if (-not $replaced) {
                $updated.Add("$Name=$Value")
                $replaced = $true
            }
            continue
        }
        $updated.Add($line)
    }
    if (-not $replaced) { $updated.Add("$Name=$Value") }
    [System.IO.File]::WriteAllLines($TargetPath, $updated, $encoding)
}

function Get-EnvValue {
    param(
        [string]$TargetPath,
        [string]$Name
    )

    if (-not (Test-Path -LiteralPath $TargetPath)) { return $null }
    $escapedName = [System.Text.RegularExpressions.Regex]::Escape($Name)
    $value = $null
    foreach ($line in [System.IO.File]::ReadAllLines($TargetPath)) {
        if ($line -match "^\s*$escapedName\s*=") {
            $candidate = $line.Substring($line.IndexOf('=') + 1).Trim()
            if ($candidate) { $value = $candidate }
        }
    }
    return $value
}

function Set-OwnerOnlyAcl {
    param([string]$TargetPath)

    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls $TargetPath /reset | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Unable to reset ACL for $TargetPath." }
    & icacls $TargetPath /inheritance:r /grant:r "${identity}:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Unable to restrict ACL for $TargetPath." }
}

$encryptionKey = Get-EnvValue -TargetPath $EnvPath -Name 'WANWEI_ENCRYPTION_KEY'
if (-not $encryptionKey) {
    $encryptionBytes = [byte[]]::new(32)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($encryptionBytes)
    $encryptionKey = [Convert]::ToBase64String($encryptionBytes).Replace('+', '-').Replace('/', '_')
}
Set-EnvValue -TargetPath $EnvPath -Name 'WANWEI_ENCRYPTION_KEY' -Value $encryptionKey
Set-OwnerOnlyAcl -TargetPath $Path
Set-OwnerOnlyAcl -TargetPath $EnvPath

Write-Host "API secret created at $Path; encryption key ensured in $EnvPath. The values were not printed." -ForegroundColor Green
