param(
    [Parameter(Mandatory = $true)]
    [string]$QtRoot,

    [Parameter(Mandatory = $true)]
    [string]$MpvRoot,

    [Parameter(Mandatory = $true)]
    [string]$BuildRoot,

    [string]$StageRoot = ""
)

$ErrorActionPreference = "Stop"

$sourceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$buildRootPath = [System.IO.Path]::GetFullPath($BuildRoot)
$qtRootPath = [System.IO.Path]::GetFullPath($QtRoot)
$mpvRootPath = [System.IO.Path]::GetFullPath($MpvRoot)

$vsRoot = "C:\Program Files\Microsoft Visual Studio\2022\Community"
$vsDev = Join-Path $vsRoot "Common7\Tools\VsDevCmd.bat"
$cmake = Join-Path $vsRoot "Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
$ninja = Join-Path $vsRoot "Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe"

foreach ($required in @(
    $vsDev,
    $cmake,
    $ninja,
    (Join-Path $qtRootPath "bin\qmake.exe"),
    (Join-Path $mpvRootPath "include\mpv\client.h"),
    (Join-Path $mpvRootPath "libmpv-2.dll")
)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Missing required pinned build input: $required"
    }
}

New-Item -ItemType Directory -Force -Path $buildRootPath | Out-Null

$command = 'call "' + $vsDev + '" -arch=x64 -host_arch=x64 && "' + $cmake + `
    '" -S "' + $sourceRoot + '" -B "' + $buildRootPath + '" -G Ninja' + `
    ' -DCMAKE_BUILD_TYPE=Release "-DCMAKE_PREFIX_PATH=' + $qtRootPath + `
    '" "-DCMAKE_MAKE_PROGRAM=' + $ninja + '" "-DMPV_ROOT=' + $mpvRootPath + `
    '" && "' + $cmake + '" --build "' + $buildRootPath + '" --config Release --parallel 4'

& cmd.exe /d /s /c $command
if ($LASTEXITCODE -ne 0) {
    throw "The Cinema Paradiso native player build failed."
}

Get-Item -LiteralPath (Join-Path $buildRootPath "cp-player.exe")

if ($StageRoot) {
    $stageRootPath = [System.IO.Path]::GetFullPath($StageRoot)
    $deployTool = Join-Path $qtRootPath "bin\windeployqt.exe"
    if (-not (Test-Path -LiteralPath $deployTool -PathType Leaf)) {
        throw "Missing required pinned deployment tool: $deployTool"
    }
    New-Item -ItemType Directory -Force -Path $stageRootPath | Out-Null
    Copy-Item -LiteralPath (Join-Path $buildRootPath "cp-player.exe") `
        -Destination (Join-Path $stageRootPath "cp-player.exe") -Force
    Copy-Item -LiteralPath (Join-Path $mpvRootPath "libmpv-2.dll") `
        -Destination (Join-Path $stageRootPath "libmpv-2.dll") -Force
    & $deployTool --release `
        --plugindir (Join-Path $stageRootPath "plugins") `
        --qml-deploy-dir (Join-Path $stageRootPath "qml") `
        --qmldir (Join-Path $sourceRoot "qml") `
        (Join-Path $stageRootPath "cp-player.exe")
    if ($LASTEXITCODE -ne 0) {
        throw "Qt runtime deployment failed."
    }
    $licenseSource = Join-Path $sourceRoot "runtime\licenses"
    $licenseDestination = Join-Path $stageRootPath "licenses"
    if (-not (Test-Path -LiteralPath $licenseSource -PathType Container)) {
        throw "Native player license inventory is missing: $licenseSource"
    }
    if (Test-Path -LiteralPath $licenseDestination) {
        Remove-Item -LiteralPath $licenseDestination -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $licenseDestination | Out-Null
    Copy-Item -Path (Join-Path $licenseSource "*") `
        -Destination $licenseDestination -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $sourceRoot "runtime\qt.conf") `
        -Destination (Join-Path $stageRootPath "qt.conf") -Force
    $assetDestination = Join-Path $stageRootPath "assets"
    New-Item -ItemType Directory -Force -Path $assetDestination | Out-Null
    Copy-Item -LiteralPath (Join-Path $sourceRoot "..\..\design\player-theme.json") `
        -Destination (Join-Path $assetDestination "player-theme.json") -Force
    Get-Item -LiteralPath $stageRootPath
}
