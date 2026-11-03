<#
.SYNOPSIS
Starts the SOMA World headless server, or asks a running one to stop.

.DESCRIPTION
Runs cataclysm-tiles in --server mode on an existing world. The world must
already contain a saved character: the server loads it as the world's anchor.
Output goes to server-logs next to the game build.

-Stop asks the server that runs this world from this game build to save the
world and exit, and waits for it. The request is an empty file server.stop in
the world's save folder; the server looks for it twice a second and deletes it.
Builds of the co-op fork up to 7cc9d26c8e ignore the file.

The password, if any, is read from the SOMA_WORLD_PASSWORD environment variable
and is never written to disk. It is still visible in the local process list.

.EXAMPLE
.\start-server.ps1 -Restart

.EXAMPLE
.\start-server.ps1 -Stop
#>
param(
    [string]$GameDir = $(if ($env:SOMA_WORLD_GAME) { $env:SOMA_WORLD_GAME } else { Join-Path $HOME 'soma-world-server\game\Cddacoop' }),
    [string]$World = 'soma',
    [int]$Port = 8080,
    # Start the server again after it crashes or fails, until this window is
    # closed. A clean exit (code 0, as after -Stop) is not restarted.
    [switch]$Restart,
    # Ask the running server to save the world and exit, then wait for it.
    [switch]$Stop,
    # How long -Stop waits for the server to exit.
    [int]$StopTimeoutSeconds = 300
)

$ErrorActionPreference = 'Stop'

$exe = Join-Path $GameDir 'cataclysm-tiles.exe'
if (-not (Test-Path $exe)) {
    throw "Game build not found: $exe"
}
$worldDir = Join-Path $GameDir "save\$World"
if (-not (Test-Path $worldDir)) {
    throw "World '$World' not found in $GameDir\save. Create it in the game first."
}

$logDir = Join-Path $GameDir 'server-logs'

if ($Stop) {
    # Only a server started from this build for this world: another game folder
    # may run a world with the same name.
    $exePath = (Resolve-Path $exe).Path
    $worldArg = '(^|\s)--world\s+"?' + [regex]::Escape($World) + '"?(\s|$)'
    $servers = @(Get-CimInstance Win32_Process -Filter "Name = 'cataclysm-tiles.exe'" |
        Where-Object {
            $_.ExecutablePath -eq $exePath -and
            $_.CommandLine -match '(^|\s)--server(\s|$)' -and
            $_.CommandLine -match $worldArg
        })
    if ($servers.Count -eq 0) {
        Write-Host "No server for world '$World' is running from $exePath."
        exit 1
    }
    # Open the processes before asking, so their exit codes can be read later.
    $processes = @($servers | ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue } |
        Where-Object { $_ })
    $processes | ForEach-Object { $null = $_.Handle }
    $stopFile = Join-Path $worldDir 'server.stop'
    New-Item -ItemType File -Force -Path $stopFile | Out-Null
    Write-Host "Asked the server (PID $($processes.Id -join ', ')) to save world '$World' and exit."
    $failed = $false
    foreach ($p in $processes) {
        if (-not $p.WaitForExit($StopTimeoutSeconds * 1000)) {
            Write-Warning "PID $($p.Id) is still running after $StopTimeoutSeconds s. See the newest log in $logDir."
            $failed = $true
        } elseif ($p.ExitCode -ne 0) {
            Write-Warning "PID $($p.Id) exited with code $($p.ExitCode). See the newest log in $logDir."
            $failed = $true
        }
    }
    if ($failed) {
        # The server deletes the file when it sees it. If it is still here, the
        # build does not support it: do not leave it for the next start.
        if (Test-Path $stopFile) {
            Remove-Item -LiteralPath $stopFile
            Write-Warning "The server never picked up $stopFile (builds up to 7cc9d26c8e have no -Stop); removed it."
        }
        exit 1
    }
    Write-Host "Server stopped after saving the world."
    exit 0
}

New-Item -ItemType Directory -Force $logDir | Out-Null
# The server logs every turn (about 24 MB a day with nobody online).
Get-ChildItem $logDir -Filter 'server-*.log' |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-14) } |
    Remove-Item

$gameArgs = @('--server', '--world', $World, '--port', $Port)
if ($env:SOMA_WORLD_PASSWORD) {
    $gameArgs += @('--password', $env:SOMA_WORLD_PASSWORD)
}

do {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $out = Join-Path $logDir "server-$stamp.out.log"
    $err = Join-Path $logDir "server-$stamp.err.log"
    Write-Host "[$stamp] SOMA World server: world=$World port=$Port logs=$logDir"
    $process = Start-Process -FilePath $exe -ArgumentList $gameArgs -WorkingDirectory $GameDir `
        -RedirectStandardOutput $out -RedirectStandardError $err -NoNewWindow -PassThru -Wait
    Write-Host "Server exited with code $($process.ExitCode). See $err"
    $again = $Restart -and $process.ExitCode -ne 0
    if ($again) {
        Start-Sleep -Seconds 10
    }
} while ($again)
