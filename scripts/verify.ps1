# 交付验收（Windows）：运行后端 compileall+pytest、前端构建与可复现性校验；venv 缺失时明确提示先跑 setup.ps1。
[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [switch]$IncludeArena
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
$frontend = Join-Path $root 'frontend\console-vue'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Python environment not found. Run scripts\setup.ps1 first.'
}

Push-Location $root
try {
    if (-not $SkipInstall) {
        & $python -m pip install -r backend\requirements-dev.txt
        if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
        Push-Location $frontend
        try {
            npm ci
            if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
        }
        finally { Pop-Location }
    }

    & $python -m compileall -q backend\app
    if ($LASTEXITCODE -ne 0) { throw 'Python compilation failed.' }
    $tmp = Join-Path $root 'tmp'
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    & $python -m pytest --basetemp .\tmp\pytest-verify -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'Backend test suite failed.' }
    $verifyDist = Join-Path $tmp 'frontend-verify-dist'
    $verifyDistForVite = $verifyDist.Replace('\', '/')
    Push-Location $frontend
    try {
        npm run build -- --outDir $verifyDistForVite
        if ($LASTEXITCODE -ne 0) { throw 'Frontend production build failed.' }
        $distDigestFirst = & $python (Join-Path $PSScriptRoot 'tree_digest.py') $verifyDist
        npm run build -- --outDir $verifyDistForVite
        if ($LASTEXITCODE -ne 0) { throw 'Second frontend production build failed.' }
    }
    finally { Pop-Location }
    $distDigestSecond = & $python (Join-Path $PSScriptRoot 'tree_digest.py') $verifyDist
    if ($distDigestFirst -ne $distDigestSecond) { throw 'Frontend production build is not reproducible.' }
    if ($IncludeArena) {
        $env:PYTHONPATH = Join-Path $root 'backend'
        & $python -m app.memory_arena.runner --output-dir (Join-Path $root 'tmp\arena-verify')
        if ($LASTEXITCODE -ne 0) { throw 'MemoryArena evaluation failed.' }
    }
    Write-Host 'Delivery verification passed.' -ForegroundColor Green
}
finally { Pop-Location }
