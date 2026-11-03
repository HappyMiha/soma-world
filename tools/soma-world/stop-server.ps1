<#
.SYNOPSIS
Stops the SOMA World server.

.DESCRIPTION
Stops everything that keeps the server running, then the server itself, and
waits until they are gone:
1. the scheduled task, but only when it runs this game folder and world;
2. any start-server.ps1 loop for this world, found through its pid file;
3. the server process.
Ending the task stopped the whole process tree in testing on this PC, but
Windows does not promise that for every task, so each step is still explicit.

In build 7cc9d26c8e the headless server never saves the world, so stopping it
returns the world to the last save made in the game itself.

Start it again with: Start-ScheduledTask -TaskName 'SOMA World server'

.EXAMPLE
.\stop-server.ps1
#>
param(
    [string]$TaskName = 'SOMA World server',
    [string]$GameDir = $(if ($env:SOMA_WORLD_GAME) { $env:SOMA_WORLD_GAME } else { Join-Path $HOME 'soma-world-server\game\Cddacoop' }),
    [string]$World = 'soma'
)

$ErrorActionPreference = 'Stop'

$GameDir = [IO.Path]::GetFullPath($GameDir).TrimEnd('\')
$exe = Join-Path $GameDir 'cataclysm-tiles.exe'
$logDir = Join-Path $GameDir 'server-logs'
$stopped = @()

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

$worldArg = '--world\s+"?' + [regex]::Escape($World) + '"?(\s|$)'
$servers = @(Get-CimInstance Win32_Process -Filter "Name='cataclysm-tiles.exe'" | Where-Object {
    $_.ExecutablePath -and [IO.Path]::GetFullPath($_.ExecutablePath) -eq $exe -and
    $_.CommandLine -match '--server' -and $_.CommandLine -match $worldArg
})
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
