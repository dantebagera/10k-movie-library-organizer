$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$isolatedRoot = [IO.Path]::GetFullPath(
    (Join-Path $temporaryRoot ('cinema-paradiso-playwright-' + [guid]::NewGuid().ToString('N')))
)
if (-not $isolatedRoot.StartsWith($temporaryRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to create Playwright data outside the operating-system temporary directory: $isolatedRoot"
}

New-Item -ItemType Directory -Path $isolatedRoot | Out-Null
$stdoutPath = Join-Path $isolatedRoot 'server.stdout.log'
$stderrPath = Join-Path $isolatedRoot 'server.stderr.log'
$isolatedDist = Join-Path $isolatedRoot 'dist'
$server = $null
$testExitCode = 1

$env:CP_PORT = '5117'
$env:CP_TEST_MODE = '1'
$env:CP_TEST_ROOT = $isolatedRoot
$env:CP_TEST_QBT_MODE = 'system'
$env:CP_TEST_DIST_DIR = $isolatedDist
Write-Output "CP_TEST_ROOT=$isolatedRoot"

try {
    $python = Join-Path $projectRoot '.venv\Scripts\python.exe'
    & $python -m tests.seed_iptv_e2e $isolatedRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create isolated IPTV provider fixtures."
    }
    & npm.cmd run build -- --outDir $isolatedDist
    if ($LASTEXITCODE -ne 0) {
        throw "Could not build the isolated Playwright frontend."
    }
    $server = Start-Process `
        -FilePath $python `
        -ArgumentList 'app.py' `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru

    $ready = $false
    for ($attempt = 0; $attempt -lt 120; $attempt += 1) {
        if ($server.HasExited) {
            throw "Isolated Playwright server exited before becoming ready."
        }
        try {
            $response = Invoke-WebRequest `
                -Uri 'http://127.0.0.1:5117/api/library/status' `
                -UseBasicParsing `
                -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
    if (-not $ready) {
        throw "Isolated Playwright server did not become ready within 30 seconds."
    }

    $playwright = Join-Path $projectRoot 'node_modules\.bin\playwright.cmd'
    & $playwright test @args
    $testExitCode = $LASTEXITCODE
} catch {
    Write-Error $_
    $testExitCode = 1
} finally {
    if ($server) {
        $trackedIds = [System.Collections.Generic.List[int]]::new()
        $trackedIds.Add([int]$server.Id)
        for ($index = 0; $index -lt $trackedIds.Count; $index += 1) {
            $parentId = $trackedIds[$index]
            Get-CimInstance Win32_Process -Filter "ParentProcessId=$parentId" -ErrorAction SilentlyContinue |
                ForEach-Object {
                    if (-not $trackedIds.Contains([int]$_.ProcessId)) {
                        $trackedIds.Add([int]$_.ProcessId)
                    }
                }
        }
        for ($index = $trackedIds.Count - 1; $index -ge 0; $index -= 1) {
            $processId = $trackedIds[$index]
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            Wait-Process -Id $processId -Timeout 10 -ErrorAction SilentlyContinue
        }
    }

    if ($testExitCode -eq 0) {
        $resolvedRoot = [IO.Path]::GetFullPath($isolatedRoot)
        if (-not $resolvedRoot.StartsWith($temporaryRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove an unverified Playwright directory: $resolvedRoot"
        }
        for ($attempt = 0; $attempt -lt 20; $attempt += 1) {
            try {
                Remove-Item -LiteralPath $resolvedRoot -Recurse -Force
                break
            } catch {
                if ($attempt -eq 19) { throw }
                Start-Sleep -Milliseconds 250
            }
        }
    } else {
        Write-Output "Playwright failure data retained at $isolatedRoot"
        if (Test-Path -LiteralPath $stderrPath) {
            Get-Content -LiteralPath $stderrPath -Tail 40
        }
    }
}

exit $testExitCode
