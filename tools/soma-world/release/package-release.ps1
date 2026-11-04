<#
.SYNOPSIS
Packs a SOMA World client folder into the release archive.

.DESCRIPTION
The archive holds one folder, named like the client folder, and its paths use
forward slashes. HOW-TO-JOIN.txt from this folder goes next to
cataclysm-tiles.exe as UTF-8 with a BOM and CRLF line ends, so Notepad shows it
right on any Windows. README-header.txt goes in front of the co-op fork's
README.txt.

data\cache stays out of the archive. The game keeps parsed JSON there in files
named after each source file's modification time, as the file clock of the build
that wrote them counts it: the co-op fork's published Windows build counts
milliseconds from 2174, an MSVC build such as 9f50a6140a from 1601. A cache from
another build never matches, and neither does one from another machine if
unpacking changed the files' times. The game then shows a "Stale game data"
message for every cached file. Without the folder it writes its own cache on
the first start.

The script refuses a folder that has config or save in it. The game writes
those while it runs, and they hold the settings, logs and worlds of whoever ran
it.

.EXAMPLE
.\package-release.ps1 -ClientDir C:\build\SomaWorld-8352fc80c6 -Destination soma-world-8352fc80c6-windows-x64.zip
#>
param(
    [Parameter(Mandatory)] [string]$ClientDir,
    [Parameter(Mandatory)] [string]$Destination
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$paths = $ExecutionContext.SessionState.Path
$ClientDir = $paths.GetUnresolvedProviderPathFromPSPath($ClientDir).TrimEnd('\')
$Destination = $paths.GetUnresolvedProviderPathFromPSPath($Destination)
foreach ($name in 'cataclysm-tiles.exe', 'README.txt', 'data') {
    if (-not (Test-Path -LiteralPath (Join-Path $ClientDir $name))) {
        throw "$ClientDir has no $name"
    }
}
foreach ($name in 'config', 'save') {
    if (Test-Path -LiteralPath (Join-Path $ClientDir $name)) {
        throw "$ClientDir has $name in it, so the game has run there. Pack a fresh copy of the build."
    }
}
if (Test-Path -LiteralPath $Destination) {
    throw "$Destination already exists"
}

# Git may check these texts out with either line end.
$utf8 = New-Object Text.UTF8Encoding($false)
$howToJoin = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'HOW-TO-JOIN.txt'), $utf8).Replace("`r`n", "`n").Replace("`n", "`r`n")
$howToJoinBytes = [byte[]](@(0xEF, 0xBB, 0xBF) + $utf8.GetBytes($howToJoin))
$header = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'README-header.txt'), $utf8).Replace("`r`n", "`n")
$headerBytes = $utf8.GetBytes($header)

$top = Split-Path -Leaf $ClientDir
$cache = Join-Path $ClientDir 'data\cache'
$isCache = { param($path) $path -eq $cache -or $path.StartsWith("$cache\", [StringComparison]::OrdinalIgnoreCase) }
$files = @(Get-ChildItem -LiteralPath $ClientDir -Recurse -File | Where-Object { -not (& $isCache $_.FullName) } | Sort-Object FullName)
$emptyDirs = @(Get-ChildItem -LiteralPath $ClientDir -Recurse -Directory | Where-Object {
        -not (& $isCache $_.FullName) -and -not (Get-ChildItem -LiteralPath $_.FullName -Force | Select-Object -First 1)
    })

$packed = 0
$zip = [IO.Compression.ZipFile]::Open($Destination, [IO.Compression.ZipArchiveMode]::Create)
try {
    $entry = $zip.CreateEntry("$top/HOW-TO-JOIN.txt", [IO.Compression.CompressionLevel]::Optimal)
    $out = $entry.Open()
    try { $out.Write($howToJoinBytes, 0, $howToJoinBytes.Length) } finally { $out.Dispose() }
    $packed++

    foreach ($file in $files) {
        $relative = $file.FullName.Substring($ClientDir.Length + 1).Replace('\', '/')
        if ($relative -eq 'HOW-TO-JOIN.txt') { continue }
        $entry = $zip.CreateEntry("$top/$relative", [IO.Compression.CompressionLevel]::Optimal)
        $entry.LastWriteTime = $file.LastWriteTime
        $out = $entry.Open()
        try {
            if ($relative -eq 'README.txt') {
                $readme = [IO.File]::ReadAllBytes($file.FullName)
                # A README.txt unpacked from an earlier release has the header already.
                if ($utf8.GetString($readme, 0, [Math]::Min($readme.Length, $headerBytes.Length)) -ne $header) {
                    $out.Write($headerBytes, 0, $headerBytes.Length)
                }
                $out.Write($readme, 0, $readme.Length)
            } else {
                $in = $file.OpenRead()
                try { $in.CopyTo($out) } finally { $in.Dispose() }
            }
        } finally { $out.Dispose() }
        $packed++
    }
    foreach ($dir in $emptyDirs) {
        $entry = $zip.CreateEntry("$top/" + $dir.FullName.Substring($ClientDir.Length + 1).Replace('\', '/') + '/')
        $entry.LastWriteTime = $dir.LastWriteTime
    }
} finally {
    $zip.Dispose()
}

$leftOut = 0
if (Test-Path -LiteralPath $cache) {
    $leftOut = @(Get-ChildItem -LiteralPath $cache -Recurse -File).Count
}
$hash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash
Write-Host ("Packed {0} files and {1} empty folders into {2}: {3:N0} bytes, SHA-256 {4}. Left out {5} files of data\cache." -f
    $packed, $emptyDirs.Count, $Destination, (Get-Item -LiteralPath $Destination).Length, $hash, $leftOut)
