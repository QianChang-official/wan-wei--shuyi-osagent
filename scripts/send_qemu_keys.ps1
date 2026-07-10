[CmdletBinding()]
param(
    [Parameter(Mandatory, ParameterSetName = 'Text')]
    [string]$Text,
    [Parameter(Mandatory, ParameterSetName = 'SpecialKey')]
    [ValidateSet('Enter', 'Tab', 'Space', 'Backspace', 'Escape', 'Left', 'Right', 'Up', 'Down')]
    [string]$SpecialKey,
    [ValidateRange(1024, 65535)]
    [int]$QmpPort = 5959,
    [ValidateRange(20, 1000)]
    [int]$DelayMilliseconds = 80
)

$ErrorActionPreference = 'Stop'

function Get-QemuKeyCodes([char]$Character) {
    if ($Character -cmatch '^[a-z]$') {
        return @(@{ type = 'qcode'; data = [string]$Character })
    }
    if ($Character -cmatch '^[A-Z]$') {
        return @(
            @{ type = 'qcode'; data = 'shift' },
            @{ type = 'qcode'; data = ([string]$Character).ToLowerInvariant() }
        )
    }
    if ($Character -cmatch '^[0-9]$') {
        return @(@{ type = 'qcode'; data = [string]$Character })
    }

    $symbols = @{
        '-' = 'minus'
        '_' = 'shift-minus'
        '.' = 'dot'
        '@' = 'shift-2'
        '!' = 'shift-1'
    }
    if (-not $symbols.ContainsKey([string]$Character)) {
        throw "Unsupported QEMU key character: '$Character'."
    }
    $symbol = $symbols[[string]$Character]
    if ($symbol.StartsWith('shift-')) {
        return @(
            @{ type = 'qcode'; data = 'shift' },
            @{ type = 'qcode'; data = $symbol.Substring(6) }
        )
    }
    return @(@{ type = 'qcode'; data = $symbol })
}

function Get-QemuSpecialKeyCodes([string]$Key) {
    $qcodes = @{
        Enter     = 'ret'
        Tab       = 'tab'
        Space     = 'spc'
        Backspace = 'backspace'
        Escape    = 'esc'
        Left      = 'left'
        Right     = 'right'
        Up        = 'up'
        Down      = 'down'
    }
    return @{ type = 'qcode'; data = $qcodes[$Key] }
}

$client = [System.Net.Sockets.TcpClient]::new('127.0.0.1', $QmpPort)
try {
    $stream = $client.GetStream()
    # QMP expects raw JSON. StreamWriter's default UTF-8 encoder emits a BOM,
    # which QEMU rejects as a stray character before the JSON document.
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    $reader = [System.IO.StreamReader]::new($stream, $utf8, $false, 4096, $true)
    $writer = [System.IO.StreamWriter]::new($stream, $utf8, 4096, $true)
    $writer.AutoFlush = $true

    $greeting = $reader.ReadLine() | ConvertFrom-Json
    if (-not $greeting.QMP) {
        throw 'QMP greeting was not received from the VM.'
    }

    $writer.WriteLine('{"execute":"qmp_capabilities"}')
    $capabilities = $reader.ReadLine() | ConvertFrom-Json
    if ($null -eq $capabilities.return) {
        throw 'QMP capabilities negotiation failed.'
    }

    $keySequences = [System.Collections.ArrayList]::new()
    if ($PSCmdlet.ParameterSetName -eq 'Text') {
        foreach ($character in $Text.ToCharArray()) {
            # Keep each QMP event as an array, including single-key events.
            [void]$keySequences.Add(@(Get-QemuKeyCodes $character))
        }
    }
    else {
        [void]$keySequences.Add(@(Get-QemuSpecialKeyCodes $SpecialKey))
    }

    foreach ($keys in $keySequences) {
        $payload = @{
            execute = 'send-key'
            arguments = @{ keys = $keys }
        } | ConvertTo-Json -Compress -Depth 4
        $writer.WriteLine($payload)
        $response = $reader.ReadLine() | ConvertFrom-Json
        if ($null -eq $response.return) {
            throw 'QMP rejected a key event.'
        }
        Start-Sleep -Milliseconds $DelayMilliseconds
    }
}
finally {
    if ($reader) { $reader.Dispose() }
    if ($writer) { $writer.Dispose() }
    if ($client) { $client.Dispose() }
}
