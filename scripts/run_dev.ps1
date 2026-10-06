# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

# 本地单端口启动（Windows）：只起后端，由后端直出已构建的控制台 dist，默认 127.0.0.1:8010。
#
# 与 scripts/dev.ps1 的分工：
#   - run_dev.ps1：单端口、生产式形态（后端直出 dist），适合验证打包结果
#   - dev.ps1     ：开发式形态（前后端分离 + 热更新），日常开发用这个
#
# 解释器按优先级探测 .venv-agent -> backend\.venv -> .venv -> PATH，
# 而不是假定 backend\.venv 一定存在（该目录在很多工作副本里并不存在）。
[CmdletBinding()]
param(
    [int]$Port = 8010,
    [string]$BindAddress = '127.0.0.1',
    [switch]$Production
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$dist = Join-Path $root 'frontend\console-vue\dist\index.html'

# ---------------------------------------------------------------- 解释器探测
$python = $null
foreach ($candidate in @(
    @{ Path = (Join-Path $root '.venv-agent\Scripts\python.exe'); Label = '.venv-agent' },
    @{ Path = (Join-Path $backend '.venv\Scripts\python.exe'); Label = 'backend\.venv' },
    @{ Path = (Join-Path $root '.venv\Scripts\python.exe'); Label = '.venv' })) {
    if (-not (Test-Path -LiteralPath $candidate.Path)) { continue }
    & $($candidate.Path) -c 'import uvicorn' 2>$null
    if ($LASTEXITCODE -eq 0) {
        $python = $candidate.Path
        Write-Host "Python：$($candidate.Label)" -ForegroundColor DarkGray
        break
    }
    Write-Host "跳过 $($candidate.Label)：依赖不全（缺 uvicorn）" -ForegroundColor DarkGray
}
if (-not $python) {
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($onPath -and $onPath.Source) {
        & $($onPath.Source) -c 'import uvicorn' 2>$null
        if ($LASTEXITCODE -eq 0) { $python = $onPath.Source }
    }
}
if (-not $python) {
    throw '找不到「已安装 uvicorn」的 Python。请先运行 scripts\setup.ps1。'
}

if (-not (Test-Path -LiteralPath $dist)) {
    throw '前端构建产物不存在。请运行 scripts\setup.ps1（会执行 npm run build），或改用 scripts\dev.ps1 走开发模式。'
}

if ([string]::IsNullOrWhiteSpace($env:WANWEI_MEMORY_DB)) {
    $runtimeDir = Join-Path $root 'data\runtime'
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    $env:WANWEI_MEMORY_DB = Join-Path $runtimeDir 'memory.db'
}

# 本地回环请求不应走代理：http_proxy 会劫持 127.0.0.1（本项目已确认过的坑）
foreach ($proxyVar in @('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY')) {
    if (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($proxyVar))) {
        [Environment]::SetEnvironmentVariable($proxyVar, $null)
    }
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
