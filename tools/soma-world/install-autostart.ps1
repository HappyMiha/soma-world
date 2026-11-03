<#
.SYNOPSIS
Registers a scheduled task that starts the SOMA World server at logon.

.DESCRIPTION
The task runs start-server.ps1 -Restart for the current user, only while that
user is signed in, so no password is stored. Windows signs the user in again by
itself after update restarts; after a shutdown or sign-out the server returns
only with the next sign-in.

The task has no time limit (the default would end it after 72 hours), runs at
normal priority, ignores a second start while one is running and is retried
every minute if it fails. The game folder, world and port are fixed in the task,
so environment variables cannot move it. Running this again replaces the task.

Stop the server with stop-server.ps1. Remove the task with:
Unregister-ScheduledTask -TaskName 'SOMA World server'

.EXAMPLE
.\install-autostart.ps1 -Port 38080
#>
param(
    [string]$TaskName = 'SOMA World server',
    [string]$ServerDir = (Join-Path $HOME 'soma-world-server'),
    [string]$GameDir = (Join-Path $HOME 'soma-world-server\game\Cddacoop'),
    [string]$World = 'soma',
    [int]$Port = 38080
)

$ErrorActionPreference = 'Stop'

$script = Join-Path $ServerDir 'start-server.ps1'
if (-not (Test-Path $script)) {
    throw "start-server.ps1 not found in $ServerDir"
}
$GameDir = [IO.Path]::GetFullPath($GameDir).TrimEnd('\')
if (-not (Test-Path (Join-Path $GameDir 'cataclysm-tiles.exe'))) {
    throw "Game build not found in $GameDir"
}

$user = "$env:USERDOMAIN\$env:USERNAME"
$arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -File `"$script`" " +
    "-GameDir `"$GameDir`" -World $World -Port $Port -Restart"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $ServerDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
# Give the network and the playit service a moment after sign-in.
$trigger.Delay = 'PT30S'
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
# Priority 4 is normal for CPU, I/O and memory; the game process inherits it.
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew -RestartCount 255 -RestartInterval (New-TimeSpan -Minutes 1) `
    -Priority 4

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force `
    -Description "Starts the SOMA World headless server (world $World, port $Port) at sign-in." | Out-Null
Write-Host "Registered scheduled task '$TaskName' for ${user}: world=$World port=$Port."
