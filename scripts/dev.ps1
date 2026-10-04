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

<#
.SYNOPSIS
    一键拉起「后端 + 前端」本地开发环境。

.DESCRIPTION
    这个脚本存在的唯一理由：消除「我该在哪个文件夹执行这条命令」的猜测成本。

    - 仓库根目录由脚本自身位置推导，**在任意目录执行都能跑**，无需先 cd。
    - Python 解释器按优先级自动探测（.venv-agent -> backend\.venv -> 系统 python），
      不再假设某个固定路径存在。
    - 同时启动 uvicorn(8010) 与 vite(5173)，并打印两个可直接点击的地址。
    - Ctrl+C 一次性停掉两个进程，不留孤儿进程占端口。

.PARAMETER BackendPort
    后端端口。默认 8010。注意 vite 的开发代理硬编码指向 8010，
    改这个端口需要同步改 frontend/console-vue/vite.config.ts。

.PARAMETER FrontendPort
    前端端口。默认 5173。

.PARAMETER BackendOnly
    只启动后端（等价于旧run_dev.ps1 的行为，但解释器探测更宽松）。

.PARAMETER FrontendOnly
    只启动前端。

.EXAMPLE
    pwsh scripts\dev.ps1
    描述：以前后端分离的开发模式启动。

.EXAMPLE
    pwsh scripts\dev.ps1 -BackendPort 8011
    描述：后端换到 8011（同时需改 vite.config.ts 的 backend 常量）。
#>
[CmdletBinding()]
param(
    [int]$BackendPort = 8010,
    [int]$FrontendPort = 5173,
    [string]$BindAddress = '127.0.0.1',
    [switch]$BackendOnly,
    [switch]$FrontendOnly
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------- 路径推导
# 关键：$PSScriptRoot 指向 scripts\，其父目录即仓库根。无论从哪个 cwd 调用都成立。
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot 'backend'
$frontendDir = Join-Path $repoRoot 'frontend\console-vue'

if (-not (Test-Path -LiteralPath $backendDir)) {
    throw "找不到 backend 目录：$backendDir`n当前脚本被解析到：$PSScriptRoot"
}

Write-Host ''
Write-Host '宛委·枢忆 · 本地开发环境' -ForegroundColor Cyan
Write-Host "仓库根目录：$repoRoot" -ForegroundColor DarkGray
Write-Host ''

# ------------------------------------------------------- Python 解释器探测
function Resolve-Python {
    <#
      按优先级探测「真的能import uvicorn」的Python。
      只判断文件存在是不够的：半残的 venv 会让启动失败，
      并给出与真实原因无关的报错（实测Git Bash 下会选到无 uvicorn 的 python3）。
    #>
    $candidates = @(
        @{ Path = (Join-Path $repoRoot '.venv-agent\Scripts\python.exe'); Label = '.venv-agent' },
        @{ Path = (Join-Path $backendDir '.venv\Scripts\python.exe'); Label = 'backend\.venv' },
        @{ Path = (Join-Path $repoRoot '.venv\Scripts\python.exe'); Label = '.venv' }
    )
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate.Path)) { continue }
        & $($candidate.Path) -c 'import uvicorn' 2>$null
        if ($LASTEXITCODE -eq 0) {
            return [pscustomobject]@{ Path = $candidate.Path; Label = $candidate.Label }
        }
        Write-Host "跳过 $($candidate.Label)：依赖不全（缺 uvicorn）" -ForegroundColor DarkGray
    }
    # 退回 PATH 上的 python，同样要求依赖齐全
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($onPath -and $onPath.Source) {
        & $($onPath.Source) -c 'import uvicorn' 2>$null
        if ($LASTEXITCODE -eq 0) {
            return [pscustomobject]@{ Path = $onPath.Source; Label = 'PATH:python' }
        }
    }
    return $null
}

$python = Resolve-Python
if (-not $python) {
    Write-Host '找不到「已安装 uvicorn」的 Python 解释器。' -ForegroundColor Red
    throw '请先运行 scripts\setup.ps1 创建 backend\.venv 并安装依赖。'
}

# 注意用$() 包住属性访问：& 后直接跟$obj.Path 会被解析成参数的一部分，
# 路径里含点号（如 .venv-agent）时必然出错。
$pythonVersion = (& $($python.Path) -c 'import platform;print(platform.python_version())' |Out-String).Trim()
Write-Host "Python：$($python.Label)  ($pythonVersion)" -ForegroundColor Gray
Write-Host "        $($python.Path)" -ForegroundColor DarkGray

# ---------------------------------------------------------------- 运行时目录
if ([string]::IsNullOrWhiteSpace($env:WANWEI_MEMORY_DB)) {
    $runtimeDir = Join-Path $repoRoot 'data\runtime'
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    $env:WANWEI_MEMORY_DB = Join-Path $runtimeDir 'memory.db'
    Write-Host "运行时数据：$($env:WANWEI_MEMORY_DB)" -ForegroundColor DarkGray
}

# 明确禁用代理：本地回环请求被http_proxy 劫持是本项目已确认过的坑，
# 且vite 开发代理同样会被劫持，直接在进程级清掉最省事。
foreach ($proxyVar in @('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY')) {
    if (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($proxyVar))) {
        Write-Host "已清空 $proxyVar（本地回环不应走代理）" -ForegroundColor DarkGray
        [Environment]::SetEnvironmentVariable($proxyVar, $null)
    }
}

$started = New-Object System.Collections.Generic.List[System.Diagnostics.Process]

function Stop-Children {
    if ($null -eq $started -or $started.Count -eq 0) { return }
    Write-Host ''
    Write-Host '正在停止子进程...' -ForegroundColor Yellow
    foreach ($proc in $started) {
        if ($null -eq $proc) { continue }
        try {
            if (-not $proc.HasExited) {
                # 杀掉整个进程树：vite 会派生 esbuild 子进程，只杀父进程会留孤儿占端口
                & taskkill.exe /PID $proc.Id /T /F 2>&1 | Out-Null
            }
        } catch {
            # 进程可能已自行退出，忽略
        }
    }
    $started.Clear()
}

# ---------------------------------------------------------------- 启动后端
if (-not $FrontendOnly) {
    $backendLog = Join-Path $repoRoot 'data\runtime\dev-backend.log'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backendLog) | Out-Null

    Write-Host "启动后端  http://${BindAddress}:$BackendPort" -ForegroundColor Green
    $backendArgs = @(
        '-m', 'uvicorn', 'app.main:app',
        '--app-dir', $backendDir,
        '--host', $BindAddress,
        '--port', "$BackendPort",
        '--no-proxy-headers'
    )
    $backendProc = Start-Process -FilePath $($python.Path) `
        -ArgumentList $backendArgs `
        -WorkingDirectory $backendDir `
        -RedirectStandardOutput $backendLog `
        -RedirectStandardError "$backendLog.err" `
        -PassThru `
        -NoNewWindow
    $started.Add($backendProc)

    # 等后端真正可用再放前端起来，否则 vite 代理首屏全部 502
    Write-Host '等待后端就绪...' -ForegroundColor DarkGray
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        if ($backendProc.HasExited) {
            Write-Host "后端进程已退出（code $($backendProc.ExitCode)）。日志尾部：" -ForegroundColor Red
            if (Test-Path -LiteralPath "$backendLog.err") {
                Get-Content -LiteralPath "$backendLog.err" -Tail 20 | ForEach-Object {
                    Write-Host "  $_" -ForegroundColor Red
                }
            }
            Stop-Children
            exit 1
        }
        try {
            $resp = Invoke-WebRequest -Uri "http://${BindAddress}:$BackendPort/health" `
                -Proxy $null -TimeoutSec 2 -UseBasicParsing
            if ($resp.StatusCode -eq 200) { $ready = $true; break }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if ($ready) {
        Write-Host "后端就绪  http://${BindAddress}:$BackendPort/health" -ForegroundColor Green
    } else {
        Write-Host '后端在 20 秒内未就绪，仍继续启动前端（可稍后手动访问检查）。' -ForegroundColor Yellow
    }
}

# ---------------------------------------------------------------- 启动前端
if (-not $BackendOnly) {
    if (-not (Test-Path -LiteralPath $frontendDir)) {
        throw "找不到前端目录：$frontendDir"
    }
    # Windows 上真正的可执行体是 npm.cmd；Get-Command npm 在不同shell 下
    # 可能只返回别名而非路径，因此显式找 .cmd，找不到再退回 npm。
    $npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npmCmd) { $npmCmd = Get-Command npm -ErrorAction SilentlyContinue }
    if (-not $npmCmd -or -not $npmCmd.Source) {
        Write-Host '找不到 npm，跳过前端。请先安装 Node.js 22.12+。' -ForegroundColor Yellow
    } elseif (-not (Test-Path -LiteralPath (Join-Path $frontendDir 'node_modules'))) {
        Write-Host '前端依赖未安装，正在执行 npm install...' -ForegroundColor Yellow
        Push-Location $frontendDir
        try {
            & $npmCmd.Source install
            if ($LASTEXITCODE -ne 0) {
                Write-Host 'npm install 失败，跳过前端。' -ForegroundColor Red
                $npmCmd = $null
            }
        } finally {
            Pop-Location
        }
    }

    if ($npmCmd -and $npmCmd.Source) {
        $frontendLog = Join-Path $repoRoot 'data\runtime\dev-frontend.log'
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $frontendLog) | Out-Null
        Write-Host "启动前端  http://${BindAddress}:$FrontendPort/console/" -ForegroundColor Green
        # --host 127.0.0.1：vite 默认只绑 localhost，跨环境行为不一致
        $frontendProc = Start-Process -FilePath $($npmCmd.Source) `
            -ArgumentList @('run', 'dev', '--', '--host', $BindAddress, '--port', "$FrontendPort", '--strictPort') `
            -WorkingDirectory $frontendDir `
            -RedirectStandardOutput $frontendLog `
            -RedirectStandardError "$frontendLog.err" `
            -PassThru `
            -NoNewWindow
        $started.Add($frontendProc)
    }
}

# ---------------------------------------------------------------- 收尾
Write-Host ''
Write-Host '────────────────────────────────────────────' -ForegroundColor DarkGray
if (-not $FrontendOnly) {
    Write-Host "API    http://${BindAddress}:$BackendPort/health" -ForegroundColor Cyan
}
if (-not $BackendOnly) {
    Write-Host "控制台 http://${BindAddress}:$FrontendPort/console/" -ForegroundColor Cyan
}
Write-Host "日志   $(Join-Path $repoRoot 'data\runtime\dev-backend.log')" -ForegroundColor DarkGray
Write-Host "       $(Join-Path $repoRoot 'data\runtime\dev-frontend.log')" -ForegroundColor DarkGray
Write-Host '按 Ctrl+C 停止全部进程。' -ForegroundColor Yellow
Write-Host '────────────────────────────────────────────' -ForegroundColor DarkGray
Write-Host ''

try {
    if ($started.Count -eq 0) {
        Write-Host '没有任何进程被启动，请检查上方错误提示。' -ForegroundColor Red
    } else {
        # 阻塞在前台，让 Ctrl+C 触发 finally
        while ($true) {
            $alive = @($started | Where-Object { $null -ne $_ -and -not $_.HasExited })
            if ($alive.Count -eq 0) {
                Write-Host '所有子进程均已退出。' -ForegroundColor Yellow
                break
            }
            Start-Sleep -Seconds 2
        }
    }
} finally {
    Stop-Children
    Write-Host '已停止。' -ForegroundColor Green
}