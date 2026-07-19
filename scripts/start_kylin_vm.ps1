# 麒麟 V11 QEMU 虚拟机管理（Windows）：install 模式创建虚拟机并挂载 ISO 安装，boot 模式日常启动。
[CmdletBinding()]
param(
    [ValidateSet('install', 'boot')]
    [string]$Mode = 'install',
    [string]$IsoPath = 'C:\Users\Administrator\Downloads\Kylin-Desktop-V11-2603-Release-20260228-X86_64.iso',
    [string]$VmRoot = 'C:\VMs\Kylin-V11',
    [ValidateRange(4096, 32768)]
    [int]$MemoryMiB = 16384,
    [ValidateRange(2, 16)]
    [int]$Vcpus = 8,
    [ValidateRange(40, 512)]
    [int]$DiskGiB = 120,
    [ValidateRange(1024, 65535)]
    [int]$QmpPort = 5959,
    [switch]$Headless,
    [switch]$Wait
)

$ErrorActionPreference = 'Stop'

function Find-QemuBinary([string]$Name) {
    $candidates = @()
    if ($env:ProgramW6432) {
        $candidates += Join-Path $env:ProgramW6432 "qemu\$Name"
    }
    if ($env:ProgramFiles) {
        $candidates += Join-Path $env:ProgramFiles "qemu\$Name"
    }
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) {
        $candidates += $command.Source
    }

    return ($candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1)
}

$qemu = Find-QemuBinary 'qemu-system-x86_64.exe'
$qemuImg = Find-QemuBinary 'qemu-img.exe'
$disk = Join-Path $VmRoot 'kylin-v11.qcow2'
$log = Join-Path $VmRoot 'qemu.log'

if (-not (Test-Path -LiteralPath $qemu)) {
    throw 'qemu-system-x86_64.exe was not found. Install the Windows QEMU package before starting the VM.'
}
if (-not (Test-Path -LiteralPath $qemuImg)) {
    throw 'qemu-img.exe was not found. Install the Windows QEMU package before starting the VM.'
}
if ($Mode -eq 'install' -and -not (Test-Path -LiteralPath $IsoPath)) {
    throw "Kylin ISO was not found at $IsoPath."
}
if (Get-Process -Name 'qemu-system-x86_64' -ErrorAction SilentlyContinue) {
    throw 'A QEMU system process is already running. Shut it down before starting another Kylin VM.'
}

New-Item -ItemType Directory -Path $VmRoot -Force | Out-Null

if (-not (Test-Path -LiteralPath $disk)) {
    & $qemuImg create -f qcow2 $disk "${DiskGiB}G"
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to create the Kylin qcow2 disk image.'
    }
}

$arguments = @(
    '-name', 'Kylin-Desktop-V11',
    '-machine', 'q35,accel=whpx',
    # WHPX on the current Windows Hyper-V stack rejects the broad `max` feature
    # set. qemu64 is deliberately conservative and passed the ISO boot probe.
    '-cpu', 'qemu64',
    '-m', $MemoryMiB,
    '-smp', $Vcpus,
    '-drive', "file=$disk,if=virtio,format=qcow2,cache=writeback,discard=unmap",
    '-qmp', "tcp:127.0.0.1:$QmpPort,server=on,wait=off",
    '-vga', 'std',
    '-nic', 'user,model=e1000e',
    '-usb',
    '-device', 'usb-tablet',
    '-boot', $(if ($Mode -eq 'install') { 'order=d,menu=on' } else { 'order=c,menu=on' }),
    '-no-reboot',
    '-D', $log,
    '-d', 'guest_errors'
)

if ($Mode -eq 'install') {
    $arguments += @('-drive', "file=$IsoPath,media=cdrom,readonly=on")
}
if ($Headless) {
    $arguments += @('-display', 'none', '-serial', 'stdio')
}
else {
    # Explicit grab-on-hover makes keyboard input reach the guest in the GTK
    # console when the VM is driven through Windows accessibility automation.
    $arguments += @('-display', 'gtk,grab-on-hover=on')
}

function Quote-QemuArgument([string]$value) {
    if ($value -notmatch '[\s"]') {
        return $value
    }
    return '"' + ($value -replace '"', '\"') + '"'
}

$commandLine = ($arguments | ForEach-Object { Quote-QemuArgument ([string]$_) }) -join ' '
Write-Host "Starting Kylin VM in $Mode mode with $Vcpus vCPU, $MemoryMiB MiB RAM, and $DiskGiB GiB dynamic storage."
Write-Host "Disk: $disk"
Write-Host "Log:  $log"
Write-Host "QMP:  127.0.0.1:$QmpPort"

$process = Start-Process -FilePath $qemu -ArgumentList $commandLine -PassThru
Write-Host "QEMU process started with PID $($process.Id)."

if ($Wait) {
    $process.WaitForExit()
    exit $process.ExitCode
}
