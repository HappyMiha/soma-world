<#
.SYNOPSIS
Starts the SOMA World headless server.

.DESCRIPTION
Runs cataclysm-tiles in --server mode on an existing world. The world must
already contain a saved character: the server loads it as the world's anchor.
Output goes to server-logs next to the game build.

The password, if any, is read from the SOMA_WORLD_PASSWORD environment variable
and is never written to disk. It is still visible in the local process list.

.EXAMPLE
.\start-server.ps1 -Restart
#>
param(
    [string]$GameDir = $(if ($env:SOMA_WORLD_GAME) { $env:SOMA_WORLD_GAME } else { Join-Path $HOME 'soma-world-server\game\Cddacoop' }),
    [string]$World = 'soma',
    [int]$Port = 8080,
    # Start the server again after it exits, until this window is closed.
    [switch]$Restart
)

$ErrorActionPreference = 'Stop'

$exe = Join-Path $GameDir 'cataclysm-tiles.exe'
if (-not (Test-Path $exe)) {
    throw "Game build not found: $exe"
}
if (-not (Test-Path (Join-Path $GameDir "save\$World"))) {
    throw "World '$World' not found in $GameDir\save. Create it in the game first."
}

$logDir = Join-Path $GameDir 'server-logs'
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
    if ($Restart) {
        Start-Sleep -Seconds 10
    }
} while ($Restart)
