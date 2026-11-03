<#
.SYNOPSIS
Starts the SOMA World headless server and keeps it running.

.DESCRIPTION
Runs cataclysm-tiles in --server mode on an existing world. The world must
already contain a saved character: the server loads it as the world's anchor.

The script supervises the server instead of waiting on it. A healthy headless
server has no window and writes a log line every turn, so a window (the game's
crash dialog) or a log that stops growing means it is stuck: the script keeps
the crash dump and stops the process. With -Restart it starts the server again,
waiting longer after repeated quick exits, but not after a requested stop: a
server stopped through server.stop (stop-server.ps1) exits with code 0 after
logging "STOP: world saved", and a new start would undo the stop. The game also
exits with code 0 when it fails to start, so a code 0 without that line is
restarted like a crash. A server.stop found before a start is left over from a
request no server took, and is removed, or it would stop the new server right
after it loads.

It refuses to start while anything else uses this build's saves (a GUI or
another server from this folder, or a build pointed at it) or holds the port.
Only one copy of this script runs per world and port.

Logs, in server-logs next to the game build: server-<time>.out.log (game
output) and wrapper.log (this script). The game also appends to
%USERPROFILE%\cdda-mp-server.log, which every build of the fork shares.

The password, if any, is read from the SOMA_WORLD_PASSWORD environment variable
and is never written to disk. It is still visible in the local process list.

.EXAMPLE
.\start-server.ps1 -Port 38080 -Restart
#>
param(
    [string]$GameDir = $(if ($env:SOMA_WORLD_GAME) { $env:SOMA_WORLD_GAME } else { Join-Path $HOME 'soma-world-server\game\Cddacoop' }),
    [string]$World = 'soma',
    [int]$Port = 38080,
    # Start the server again after it exits, unless the exit was a requested stop.
    [switch]$Restart,
    # Seconds without new game output before the server counts as stuck.
    [int]$StallSeconds = 180
)

$ErrorActionPreference = 'Stop'

$GameDir = [IO.Path]::GetFullPath($GameDir).TrimEnd('\')
$exe = Join-Path $GameDir 'cataclysm-tiles.exe'
if (-not (Test-Path $exe)) {
    throw "Game build not found: $exe"
}
if (-not (Test-Path (Join-Path $GameDir "save\$World"))) {
    throw "World '$World' not found in $GameDir\save. Create it in the game first."
}

$logDir = Join-Path $GameDir 'server-logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
$wrapperLog = Join-Path $logDir 'wrapper.log'

function Write-Log([string]$Message) {
    $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Write-Host $line
    Add-Content -Path $wrapperLog -Value $line -Encoding UTF8
}

# One copy of this script per world and port.
$mutex = New-Object System.Threading.Mutex($false, "Local\SomaWorldServer-$World-$Port")
try {
    $owned = $mutex.WaitOne(0)
} catch [System.Threading.AbandonedMutexException] {
    $owned = $true
}
if (-not $owned) {
    Write-Log "Another start-server.ps1 already runs world '$World' on port $Port; exiting."
    exit 0
}
# stop-server.ps1 uses this to find the loop. The start time guards against a
# reused process id.
$self = Get-Process -Id $PID
Set-Content -Path (Join-Path $logDir "wrapper-$World-$Port.pid") -Value "$PID $($self.StartTime.ToFileTimeUtc())"

$gameArgs = @('--server', '--world', $World, '--port', $Port)
if ($env:SOMA_WORLD_PASSWORD) {
    $gameArgs += @('--password', $env:SOMA_WORLD_PASSWORD)
}

# Processes that read or write this build's saves: a GUI or server started from
# this folder without its own user dir, or any build whose arguments point here.
# A process that cannot be inspected counts as a conflict.
function Get-SaveUser {
    Get-CimInstance Win32_Process -Filter "Name='cataclysm-tiles.exe'" | Where-Object {
        if (-not $_.ExecutablePath -or -not $_.CommandLine) {
            return $true
        }
        $rest = $_.CommandLine -replace '^\s*("[^"]*"|\S+)', ''
        $sameBuild = [IO.Path]::GetFullPath($_.ExecutablePath) -eq $exe
        $ownUserDir = $rest -match '--(userdir|basepath|savedir)\b'
        $pointsHere = $rest.IndexOf($GameDir, [StringComparison]::OrdinalIgnoreCase) -ge 0
        ($sameBuild -and -not $ownUserDir) -or $pointsHere
    }
}

# A plain .NET query: Get-NetTCPConnection goes through CIM and has hung here
# for over a minute.
function Test-PortBusy {
    [bool]([System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() |
        Where-Object { $_.Port -eq $Port })
}

# True when the game's log ends with a completed stop request. Only the tail is
# read: with a player connected the log grows by tens of megabytes a day.
function Test-StopCompleted([string]$Path) {
    $stream = [IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite')
    try {
        $start = [Math]::Max(0, $stream.Length - 262144)
        [void]$stream.Seek($start, 'Begin')
        $tail = New-Object byte[] ($stream.Length - $start)
        $read = $stream.Read($tail, 0, $tail.Length)
        [Text.Encoding]::UTF8.GetString($tail, 0, $read).Contains('[cdda-mp] STOP: world saved')
    } finally {
        $stream.Close()
    }
}

$quickExits = 0
do {
    try {
        Get-ChildItem $logDir -Filter 'server-*' |
            Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-14) } |
            Remove-Item

        $users = @(Get-SaveUser)
        $portBusy = Test-PortBusy
        if ($users.Count -gt 0 -or $portBusy) {
            if ($users.Count -gt 0) {
                $reason = "this build's saves are in use by pid $($users.ProcessId -join ', ')"
            } else {
                $owners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
                    Select-Object -ExpandProperty OwningProcess -Unique)
                $reason = "port $Port is held by pid $($owners -join ', ')"
            }
            Write-Log "Not starting: $reason."
            if (-not $Restart) {
                exit 1
            }
            Start-Sleep -Seconds 60
            continue
        }

        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $out = Join-Path $logDir "server-$stamp.out.log"
        $err = Join-Path $logDir "server-$stamp.err.log"
        $stopFile = Join-Path $GameDir "save\$World\server.stop"
        if (Test-Path $stopFile) {
            Remove-Item -LiteralPath $stopFile
            Write-Log "Removed a server.stop left from before this start."
        }
        Write-Log "Starting server: world=$World port=$Port log=$out"
        $started = Get-Date
        $process = Start-Process -FilePath $exe -ArgumentList $gameArgs -WorkingDirectory $GameDir `
            -RedirectStandardOutput $out -RedirectStandardError $err -NoNewWindow -PassThru
        # Keep the handle open so the exit code survives the process.
        $null = $process.Handle
        $lastSize = -1
        $lastGrowth = Get-Date
        while (-not $process.WaitForExit(5000)) {
            $process.Refresh()
            if ($process.MainWindowHandle -ne [IntPtr]::Zero) {
                Copy-Item (Join-Path $GameDir '.core') (Join-Path $logDir "server-$stamp.core.dmp") -ErrorAction SilentlyContinue
                Write-Log "Server pid $($process.Id) opened a window, which means its crash dialog; kept the dump and stopped it."
                Stop-Process -Id $process.Id -Force
                break
            }
            $size = (New-Object IO.FileInfo $out).Length
            if ($size -ne $lastSize) {
                $lastSize = $size
                $lastGrowth = Get-Date
            } elseif (((Get-Date) - $lastGrowth).TotalSeconds -gt $StallSeconds) {
                Write-Log "Server pid $($process.Id) wrote nothing for $StallSeconds s; stopped it."
                Stop-Process -Id $process.Id -Force
                break
            }
        }
        $process.WaitForExit()
        $ran = ((Get-Date) - $started).TotalSeconds
        Write-Log ('Server exited with code {0} after {1:N0} s. See {2}' -f $process.ExitCode, $ran, $err)
        if ($process.ExitCode -eq 0 -and (Test-StopCompleted $out)) {
            # A stop through server.stop: do not undo it.
            Write-Log 'Stopped on request; not starting the server again.'
            break
        }
        if ($process.ExitCode -eq 0) {
            Write-Log 'Exit code 0 without a requested stop (a failed start exits the same way); restarting.'
        }
        $quickExits = if ($ran -lt 120) { $quickExits + 1 } else { 0 }
    } catch {
        Write-Log "Error: $($_.Exception.Message)"
        $quickExits++
    }
    if ($Restart) {
        # 10 s normally, doubling after each quick exit up to 5 minutes.
        Start-Sleep -Seconds ([Math]::Min(300, 10 * [Math]::Pow(2, [Math]::Min($quickExits, 5))))
    }
} while ($Restart)
