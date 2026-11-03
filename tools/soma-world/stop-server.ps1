<#
.SYNOPSIS
Stops the SOMA World server, saving the world first when the build can.

.DESCRIPTION
First asks the server itself to save the world and exit: the script writes an
empty server.stop into the world's save folder, which the server checks twice a
second, deletes, and answers by saving and exiting with code 0. A server that
took the file is never killed, since it may still be saving; if it still runs
after -StopTimeoutSeconds more, the script stops there and says so. Builds of
the co-op fork up to 7cc9d26c8e never read the file: when it is not taken within
-StopTimeoutSeconds, the script removes it and stops the server the hard way,
and the world returns to its last save.

Then it stops everything that keeps the server running, then anything still
running, and waits until they are gone:
1. the scheduled task, but only when it runs this game folder and world;
2. any start-server.ps1 loop for this world, found through its pid file;
3. the server process.
Ending the task stopped the whole process tree in testing on this PC, but
Windows does not promise that for every task, so each step is still explicit.
Ending the task kills the server without saving, which is why the request to
the server comes first.

Start it again with: Start-ScheduledTask -TaskName 'SOMA World server'

.EXAMPLE
.\stop-server.ps1
#>
param(
    [string]$TaskName = 'SOMA World server',
    [string]$GameDir = $(if ($env:SOMA_WORLD_GAME) { $env:SOMA_WORLD_GAME } else { Join-Path $HOME 'soma-world-server\game\Cddacoop' }),
    [string]$World = 'soma',
    # How long to wait for the server to take server.stop, and again to exit.
    [int]$StopTimeoutSeconds = 120
)

$ErrorActionPreference = 'Stop'

$GameDir = [IO.Path]::GetFullPath($GameDir).TrimEnd('\')
$exe = Join-Path $GameDir 'cataclysm-tiles.exe'
$logDir = Join-Path $GameDir 'server-logs'
$stopped = @()

$serverWorldArg = '--world\s+"?' + [regex]::Escape($World) + '"?(\s|$)'
function Get-WorldServer {
    @(Get-CimInstance Win32_Process -Filter "Name='cataclysm-tiles.exe'" | Where-Object {
        $_.ExecutablePath -and [IO.Path]::GetFullPath($_.ExecutablePath) -eq $exe -and
        $_.CommandLine -match '--server' -and $_.CommandLine -match $serverWorldArg
    })
}

# @(): a function unrolls a one-element array, and a lone CIM object has no Count.
$servers = @(Get-WorldServer)
if ($servers.Count -gt 0) {
    # Open the processes before asking, so their exit codes can be read later.
    $processes = @($servers | ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue } |
        Where-Object { $_ })
    $processes | ForEach-Object { $null = $_.Handle }
    $stopFile = Join-Path $GameDir "save\$World\server.stop"
    New-Item -ItemType File -Force -Path $stopFile | Out-Null
    Write-Host "Asked server pid $($processes.Id -join ', ') to save world '$World' and exit."
    $deadline = (Get-Date).AddSeconds($StopTimeoutSeconds)
    while ((Test-Path $stopFile) -and (Get-Date) -lt $deadline -and
        @($processes | Where-Object { -not $_.HasExited }).Count -gt 0) {
        Start-Sleep -Milliseconds 250
    }
    if (Test-Path $stopFile) {
        Remove-Item -LiteralPath $stopFile
        Write-Warning ("The server did not take server.stop within $StopTimeoutSeconds s (builds up to " +
            "7cc9d26c8e have no lossless stop). Stopping it anyway: the world returns to its last save.")
    } else {
        foreach ($p in $processes) {
            if (-not $p.WaitForExit($StopTimeoutSeconds * 1000)) {
                Write-Warning ("Server pid $($p.Id) took server.stop but still runs after another " +
                    "$StopTimeoutSeconds s. Not killing it: it may still be saving, or its save failed " +
                    "(then the newest log in $logDir says so). Check the log and run this again.")
                exit 1
            }
            if ($p.ExitCode -eq 0) {
                Write-Host "Server pid $($p.Id) saved the world and exited."
            } else {
                Write-Warning "Server pid $($p.Id) exited with code $($p.ExitCode). See the newest log in $logDir."
            }
        }
    }
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    $taskArgs = ($task.Actions | ForEach-Object { $_.Arguments }) -join ' '
    $worldArg = '-World\s+"?' + [regex]::Escape($World) + '"?(\s|$)'
    if ($taskArgs.IndexOf($GameDir, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and $taskArgs -match $worldArg) {
        Stop-ScheduledTask -TaskName $TaskName
        Write-Host "Ended scheduled task '$TaskName'."
    } else {
        Write-Host "Scheduled task '$TaskName' runs another folder or world; left it alone."
    }
}

Get-ChildItem $logDir -Filter "wrapper-$World-*.pid" -ErrorAction SilentlyContinue | ForEach-Object {
    $id, $ticks = (Get-Content $_.FullName -Raw).Trim() -split '\s+'
    $wrapper = Get-Process -Id ([int]$id) -ErrorAction SilentlyContinue
    if ($wrapper -and $wrapper.ProcessName -in 'powershell', 'pwsh' -and
        $wrapper.StartTime.ToFileTimeUtc() -eq [long]$ticks) {
        Stop-Process -Id $wrapper.Id -Force
        $stopped += $wrapper.Id
        Write-Host "Stopped start-server.ps1 loop pid $($wrapper.Id)."
    }
    Remove-Item $_.FullName
}

$servers = @(Get-WorldServer)
foreach ($server in $servers) {
    Stop-Process -Id $server.ProcessId -Force
    $stopped += $server.ProcessId
    Write-Host "Stopped server pid $($server.ProcessId)."
}
if ($servers.Count -eq 0) {
    Write-Host "No server process for world '$World' was left to stop."
}

if ($stopped.Count -gt 0) {
    Wait-Process -Id $stopped -Timeout 30 -ErrorAction SilentlyContinue
}
