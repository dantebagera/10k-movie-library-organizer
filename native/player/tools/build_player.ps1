param(
    [Parameter(Mandatory = $true)]
    [string]$QtRoot,

    [Parameter(Mandatory = $true)]
    [string]$MpvRoot,

    [Parameter(Mandatory = $true)]
    [string]$BuildRoot
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
