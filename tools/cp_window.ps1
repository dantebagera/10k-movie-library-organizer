param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Launch', 'Close')]
    [string]$Action,

    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [int]$Port = 5000,
    [int]$ReadyTimeoutSeconds = 45
)

$ErrorActionPreference = 'Stop'

$resolvedRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$runtimeDir = Join-Path $resolvedRoot 'data\runtime'
$statePath = Join-Path $runtimeDir 'cp-window.json'
$stopPath = Join-Path $runtimeDir 'cp-window.stop'
$appUrl = "http://localhost:$Port/"
$readyUrl = "http://127.0.0.1:$Port/"
$appWindowTitle = 'Cinema Paradiso'

function Test-PathWithinRoot([string]$Path, [string]$Root) {
    $resolvedPath = [System.IO.Path]::GetFullPath($Path)
    $resolvedBoundary = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    return $resolvedPath.StartsWith($resolvedBoundary, [System.StringComparison]::OrdinalIgnoreCase)
}

if (-not (Test-PathWithinRoot -Path $statePath -Root $resolvedRoot)) {
    throw 'Cinema Paradiso window state resolved outside the project root.'
}

if (-not ('CinemaParadisoWindowNative' -as [type])) {
    Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class CinemaParadisoWindowNative {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    public const uint WM_CLOSE = 0x0010;

    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool IsWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern int GetWindowTextLength(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int maxCount);

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

    [DllImport("user32.dll")]
    public static extern bool PostMessage(IntPtr hWnd, uint message, IntPtr wParam, IntPtr lParam);

}
'@
}

function ConvertTo-EdgeAppId([string]$ManifestId) {
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $firstHash = $sha256.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($ManifestId))
        $secondHash = $sha256.ComputeHash($firstHash)
    } finally {
        $sha256.Dispose()
    }
    $alphabet = 'abcdefghijklmnop'
    $builder = [System.Text.StringBuilder]::new(32)
    foreach ($value in $secondHash[0..15]) {
        $builder.Append($alphabet[[int]$value -shr 4]) | Out-Null
        $builder.Append($alphabet[[int]$value -band 15]) | Out-Null
    }
    return $builder.ToString()
}

function Get-InstalledEdgeAppProfile([string]$AppId) {
    $userDataRoot = Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\User Data'
    if (-not (Test-Path -LiteralPath $userDataRoot -PathType Container)) {
        return $null
    }
    $profiles = Get-ChildItem -LiteralPath $userDataRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq 'Default' -or $_.Name -like 'Profile *' } |
        Sort-Object LastWriteTime -Descending
    foreach ($profile in $profiles) {
        $manifestResources = Join-Path $profile.FullName "Web Applications\Manifest Resources\$AppId"
        if (Test-Path -LiteralPath $manifestResources -PathType Container) {
            return $profile.Name
        }
    }
    return $null
}

function Get-EdgeExecutable {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'),
        ((Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe' -ErrorAction SilentlyContinue).'(default)')
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    throw 'Microsoft Edge is required to open the Cinema Paradiso app window.'
}

function Get-EdgeWindows {
    $windows = [System.Collections.Generic.List[object]]::new()
    $callback = [CinemaParadisoWindowNative+EnumWindowsProc]{
        param([IntPtr]$windowHandle, [IntPtr]$unused)
        if (-not [CinemaParadisoWindowNative]::IsWindowVisible($windowHandle)) {
            return $true
        }
        [uint32]$processId = 0
        [CinemaParadisoWindowNative]::GetWindowThreadProcessId($windowHandle, [ref]$processId) | Out-Null
        $process = Get-Process -Id ([int]$processId) -ErrorAction SilentlyContinue
        if (-not $process -or $process.ProcessName -ne 'msedge') {
            return $true
        }
        $length = [CinemaParadisoWindowNative]::GetWindowTextLength($windowHandle)
        $title = ''
        if ($length -gt 0) {
            $builder = [System.Text.StringBuilder]::new($length + 1)
            [CinemaParadisoWindowNative]::GetWindowText($windowHandle, $builder, $builder.Capacity) | Out-Null
            $title = $builder.ToString()
        }
        $windows.Add([pscustomobject]@{
            handle = [long]$windowHandle
            pid = [int]$processId
            title = $title
        })
        return $true
    }
    [CinemaParadisoWindowNative]::EnumWindows($callback, [IntPtr]::Zero) | Out-Null
    return @($windows)
}

function Test-CinemaParadisoAppWindowTitle([string]$Title) {
    if ([string]::IsNullOrWhiteSpace($Title)) {
        return $false
    }
    return $Title.Equals($appWindowTitle, [System.StringComparison]::OrdinalIgnoreCase) -or
        $Title.StartsWith(($appWindowTitle + ' - localhost'), [System.StringComparison]::OrdinalIgnoreCase)
}

function Remove-WindowState {
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        if (-not (Test-PathWithinRoot -Path $statePath -Root $resolvedRoot)) {
            throw 'Refusing to remove a window state file outside the project root.'
        }
        Remove-Item -LiteralPath $statePath -Force
    }
}

function Get-OwnedWindowFromState {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return $null
    }
    try {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $handleValue = [long]$state.window_handle
        if ($handleValue -le 0) {
            return $null
        }
        $window = Get-EdgeWindows | Where-Object { $_.handle -eq $handleValue } | Select-Object -First 1
        if (-not $window) {
            return $null
        }
        return $window
    } catch {
        return $null
    }
}

function Close-OwnedWindow {
    $window = Get-OwnedWindowFromState
    if (-not $window) {
        return $false
    }
    $handle = [IntPtr]([long]$window.handle)
    [CinemaParadisoWindowNative]::PostMessage(
        $handle,
        [CinemaParadisoWindowNative]::WM_CLOSE,
        [IntPtr]::Zero,
        [IntPtr]::Zero
    ) | Out-Null
    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    while ([DateTime]::UtcNow -lt $deadline -and [CinemaParadisoWindowNative]::IsWindow($handle)) {
        Start-Sleep -Milliseconds 100
    }
    return -not [CinemaParadisoWindowNative]::IsWindow($handle)
}

if ($Action -eq 'Close') {
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    [System.IO.File]::WriteAllText($stopPath, 'stop', [System.Text.UTF8Encoding]::new($false))
    Start-Sleep -Milliseconds 1000
    $closed = Close-OwnedWindow
    Remove-WindowState
    [pscustomobject]@{ action = 'closed'; window_closed = $closed } | ConvertTo-Json -Compress
    exit 0
}

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
if (Test-Path -LiteralPath $stopPath -PathType Leaf) {
    Remove-Item -LiteralPath $stopPath -Force
}
Close-OwnedWindow | Out-Null
Remove-WindowState

$deadline = [DateTime]::UtcNow.AddSeconds([Math]::Max(1, $ReadyTimeoutSeconds))
$ready = $false
while ([DateTime]::UtcNow -lt $deadline) {
    if (Test-Path -LiteralPath $stopPath -PathType Leaf) {
        exit 0
    }
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $readyUrl -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {
        Start-Sleep -Milliseconds 200
    }
}
if (-not $ready) {
    throw "Cinema Paradiso server did not become ready at $readyUrl"
}
if (Test-Path -LiteralPath $stopPath -PathType Leaf) {
    exit 0
}

$existingHandles = [System.Collections.Generic.HashSet[long]]::new()
foreach ($window in (Get-EdgeWindows)) {
    $existingHandles.Add([long]$window.handle) | Out-Null
}

$edge = Get-EdgeExecutable
$edgeAppId = ConvertTo-EdgeAppId -ManifestId $appUrl
$installedProfile = Get-InstalledEdgeAppProfile -AppId $edgeAppId
$launchMode = if ($installedProfile) { 'installed_web_app' } else { 'url_app_fallback' }
$existingInstalledWindow = if ($installedProfile) {
    Get-EdgeWindows | Where-Object { Test-CinemaParadisoAppWindowTitle -Title $_.title } | Select-Object -First 1
} else {
    $null
}
$arguments = @(
    '--start-maximized',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-session-crashed-bubble'
)
if ($installedProfile) {
    $arguments += '--profile-directory="' + $installedProfile + '"'
    $arguments += "--app-id=$edgeAppId"
} else {
    # Required until the user installs CP as an Edge app. The served web app
    # manifest provides that installation path without changing CP's URL.
    $arguments += "--app=$appUrl"
}
Start-Process -FilePath $edge -ArgumentList $arguments | Out-Null

$windowWaitSeconds = if ($existingInstalledWindow) { 2 } else { 12 }
$windowDeadline = [DateTime]::UtcNow.AddSeconds($windowWaitSeconds)
$ownedWindow = $null
while ([DateTime]::UtcNow -lt $windowDeadline) {
    $ownedWindow = Get-EdgeWindows | Where-Object {
        -not $existingHandles.Contains([long]$_.handle) -and
        $_.title.IndexOf($appWindowTitle, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
    } | Select-Object -First 1
    if ($ownedWindow) {
        break
    }
    if (Test-Path -LiteralPath $stopPath -PathType Leaf) {
        exit 0
    }
    Start-Sleep -Milliseconds 100
}
if (-not $ownedWindow) {
    if ($installedProfile) {
        $ownedWindow = Get-EdgeWindows | Where-Object {
            $existingHandles.Contains([long]$_.handle) -and
            (Test-CinemaParadisoAppWindowTitle -Title $_.title)
        } | Select-Object -First 1
    }
    if (-not $ownedWindow) {
        throw 'Cinema Paradiso could not establish ownership of its Edge app window.'
    }
}
if (Test-Path -LiteralPath $stopPath -PathType Leaf) {
    $temporaryState = [ordered]@{ window_handle = [long]$ownedWindow.handle }
    [System.IO.File]::WriteAllText($statePath, ($temporaryState | ConvertTo-Json), [System.Text.UTF8Encoding]::new($false))
    Close-OwnedWindow | Out-Null
    Remove-WindowState
    exit 0
}

$state = [ordered]@{
    schema_version = 2
    window_handle = [long]$ownedWindow.handle
    browser_pid = [int]$ownedWindow.pid
    window_title = [string]$ownedWindow.title
    url = $appUrl
    launch_mode = $launchMode
    edge_app_id = $edgeAppId
    profile_directory = $installedProfile
    started_at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
}
$temporaryState = Join-Path $runtimeDir ('.cp-window.' + [Guid]::NewGuid().ToString('N') + '.tmp')
[System.IO.File]::WriteAllText($temporaryState, ($state | ConvertTo-Json -Depth 3), [System.Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $temporaryState -Destination $statePath -Force
$state | ConvertTo-Json -Compress
