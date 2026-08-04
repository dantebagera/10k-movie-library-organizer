$ErrorActionPreference = 'Stop'

$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project '.venv\Scripts\python.exe'
$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$samples = @()

try {
    for ($index = 0; $index -lt 10; $index += 1) {
        $port = 5121 + $index
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
            throw "Startup benchmark port $port is already in use."
        }
        $root = Join-Path $temporaryRoot ('cp-gate8-startup-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $root | Out-Null
        $stdout = Join-Path $root 'stdout.log'
        $stderr = Join-Path $root 'stderr.log'
        $server = $null
        $env:CP_TEST_MODE = '1'
        $env:CP_TEST_ROOT = $root
        $env:CP_PORT = [string]$port
        try {
            $clock = [Diagnostics.Stopwatch]::StartNew()
            $server = Start-Process -FilePath $python -ArgumentList 'app.py' `
                -WorkingDirectory $project -WindowStyle Hidden `
                -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
            $response = $null
            for ($attempt = 0; $attempt -lt 120; $attempt += 1) {
                try {
                    $response = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/startup/status" -TimeoutSec 2
                    break
                } catch {
                    Start-Sleep -Milliseconds 100
                }
            }
            $clock.Stop()
            if ($null -eq $response) {
                throw "Startup sample $index failed: $(Get-Content -LiteralPath $stderr -Raw)"
            }
            $samples += [pscustomobject]@{
                sample = $index
                test_root = $root
                external_ready_ms = [math]::Round($clock.Elapsed.TotalMilliseconds, 3)
                internal_api_ready_ms = [double]$response.api_ready_ms
                database_open_ms = [double]$response.database_open_ms
                migration_check_ms = [double]$response.migration_check_ms
            }
        } finally {
            $owner = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
                Select-Object -First 1 -ExpandProperty OwningProcess
            if ($owner) {
                Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
                Wait-Process -Id $owner -Timeout 10 -ErrorAction SilentlyContinue
            }
            if ($server -and -not $server.HasExited) {
                Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
                Wait-Process -Id $server.Id -Timeout 10 -ErrorAction SilentlyContinue
            }
            for ($attempt = 0; $attempt -lt 20; $attempt += 1) {
                try {
                    Remove-Item -LiteralPath $root -Recurse -Force
                    break
                } catch {
                    if ($attempt -eq 19) { throw }
                    Start-Sleep -Milliseconds 100
                }
            }
        }
    }
} finally {
    Remove-Item Env:CP_TEST_MODE, Env:CP_TEST_ROOT, Env:CP_PORT -ErrorAction SilentlyContinue
}

$internal = @($samples.internal_api_ready_ms | Sort-Object)
$external = @($samples.external_ready_ms | Sort-Object)
[pscustomobject]@{
    samples = $samples
    internal_p50_ms = ($internal[4] + $internal[5]) / 2
    internal_p95_ms = $internal[9]
    external_p50_ms = ($external[4] + $external[5]) / 2
    external_p95_ms = $external[9]
    gate0_internal_ms = 29.551
    budget_limit_ms = 279.551
    passed = [double]$internal[9] -le 279.551
} | ConvertTo-Json -Depth 5
