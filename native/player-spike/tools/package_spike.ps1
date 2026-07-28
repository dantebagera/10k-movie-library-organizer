param(
    [Parameter(Mandatory = $true)]
    [string]$QtRoot,

    [Parameter(Mandatory = $true)]
    [string]$BuildRoot,

    [Parameter(Mandatory = $true)]
    [string]$PackageRoot
)

$ErrorActionPreference = "Stop"

$sourceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$qtRootPath = [System.IO.Path]::GetFullPath($QtRoot)
$buildRootPath = [System.IO.Path]::GetFullPath($BuildRoot)
$packageRootPath = [System.IO.Path]::GetFullPath($PackageRoot)
$allowedTemporaryRoot = [System.IO.Path]::GetFullPath(
    (Join-Path ([System.IO.Path]::GetTempPath()) "cp-player-phase0")
)
$vsDev = "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat"

function Get-CompatibleRelativePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BasePath,

        [Parameter(Mandatory = $true)]
        [string]$TargetPath
    )

    $baseWithSeparator = $BasePath.TrimEnd("\") + "\"
    $baseUri = New-Object System.Uri($baseWithSeparator)
    $targetUri = New-Object System.Uri($TargetPath)
    return [System.Uri]::UnescapeDataString(
        $baseUri.MakeRelativeUri($targetUri).ToString()
    ).Replace("/", "\")
}

if (-not $packageRootPath.StartsWith(
    $allowedTemporaryRoot + [System.IO.Path]::DirectorySeparatorChar,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Spike packages may only be written below $allowedTemporaryRoot"
}

$executable = Join-Path $buildRootPath "cp-player-spike.exe"
$mpvDll = Join-Path $buildRootPath "libmpv-2.dll"
$deployTool = Join-Path $qtRootPath "bin\windeployqt.exe"
foreach ($required in @($executable, $mpvDll, $deployTool, $vsDev)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Missing required packaging input: $required"
    }
}

if (Test-Path -LiteralPath $packageRootPath) {
    Remove-Item -LiteralPath $packageRootPath -Recurse -Force
}
New-Item -ItemType Directory -Path $packageRootPath | Out-Null

Copy-Item -LiteralPath $executable, $mpvDll -Destination $packageRootPath
$deployCommand = 'call "' + $vsDev + '" -arch=x64 -host_arch=x64 && "' + `
    $deployTool + '" --release --force --compiler-runtime --no-translations' + `
    ' --skip-plugin-types qmltooling,generic --verbose 0 --qmldir "' + `
    (Join-Path $sourceRoot "qml") + '" "' + `
    (Join-Path $packageRootPath "cp-player-spike.exe") + '"'
& cmd.exe /d /s /c $deployCommand
if ($LASTEXITCODE -ne 0) {
    throw "windeployqt failed."
}

$unusedStyleDirectories = @(
    "qml\QtQuick\Controls\FluentWinUI3",
    "qml\QtQuick\Controls\Imagine",
    "qml\QtQuick\Controls\Material",
    "qml\QtQuick\Controls\Universal",
    "qml\QtQuick\Controls\Windows"
)
$unusedStyleLibraries = @(
    "Qt6QuickControls2FluentWinUI3StyleImpl.dll",
    "Qt6QuickControls2Imagine.dll",
    "Qt6QuickControls2ImagineStyleImpl.dll",
    "Qt6QuickControls2Material.dll",
    "Qt6QuickControls2MaterialStyleImpl.dll",
    "Qt6QuickControls2Universal.dll",
    "Qt6QuickControls2UniversalStyleImpl.dll",
    "Qt6QuickControls2WindowsStyleImpl.dll"
)
foreach ($relativePath in $unusedStyleDirectories) {
    $target = Join-Path $packageRootPath $relativePath
    if (Test-Path -LiteralPath $target -PathType Container) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}
foreach ($relativePath in $unusedStyleLibraries) {
    $target = Join-Path $packageRootPath $relativePath
    if (Test-Path -LiteralPath $target -PathType Leaf) {
        Remove-Item -LiteralPath $target -Force
    }
}

$licenseRoot = Join-Path $packageRootPath "licenses"
New-Item -ItemType Directory -Path $licenseRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $sourceRoot "THIRD_PARTY_REVIEW.md") -Destination $licenseRoot
Copy-Item -LiteralPath (Join-Path $sourceRoot "runtime-lock.json") -Destination $packageRootPath
@"
PHASE 0 TECHNICAL ARTIFACT - DO NOT DISTRIBUTE

The bundled libmpv candidate passed the LGPL configuration and runtime gates.
This spike package still lacks the production dependency inventory, complete
license texts, corresponding source or offer, and relinking material.
"@ | Set-Content -LiteralPath (Join-Path $packageRootPath "DO_NOT_DISTRIBUTE.txt") -Encoding utf8

$forbiddenNames = @(
    "config.json",
    "res_cache.json",
    "providers.json",
    "playback-history.db",
    "canonical_catalog.db"
)
$forbiddenRoots = @("data", "cache", "profiles", "downloads", "test-results")
$files = Get-ChildItem -LiteralPath $packageRootPath -Recurse -File
foreach ($file in $files) {
    if ($file.Name.ToLowerInvariant() -in $forbiddenNames) {
        throw "User-data file entered the spike package: $($file.Name)"
    }
    $relative = Get-CompatibleRelativePath -BasePath $packageRootPath -TargetPath $file.FullName
    $topLevel = $relative.Split(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.StringSplitOptions]::RemoveEmptyEntries
    )[0].ToLowerInvariant()
    if ($topLevel -in $forbiddenRoots) {
        throw "User-data directory entered the spike package: $topLevel"
    }
}

$inventory = foreach ($file in $files) {
    [ordered]@{
        path = (Get-CompatibleRelativePath -BasePath $packageRootPath -TargetPath $file.FullName).Replace("\", "/")
        size = $file.Length
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    }
}
$manifest = [ordered]@{
    schema = "cp-player-phase0-package-v1"
    redistributable = $false
    reason = "Phase 0 technical artifact; production compliance bundle is intentionally incomplete."
    file_count = @($inventory).Count
    total_bytes = ($files | Measure-Object -Property Length -Sum).Sum
    files = $inventory
}
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $packageRootPath "package-manifest.json") -Encoding utf8

Get-Content -LiteralPath (Join-Path $packageRootPath "package-manifest.json") -Raw
