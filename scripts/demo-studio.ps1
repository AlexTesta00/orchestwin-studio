param([switch]$Stop, [int]$IdleMinutes = 90)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$python = Join-Path $repo '.venv/Scripts/python.exe'
$controller = Join-Path $repo 'scripts/cloud_proposer.py'
$logs = Join-Path $repo 'var/studio/logs'
$tunnelLog = Join-Path $logs 'public-tunnel.stderr.log'
New-Item -ItemType Directory -Force -Path $logs | Out-Null

if ($Stop) {
    Get-Process -Name cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo 'scripts/stop-studio.ps1') -StopPod
    Write-Host 'Demo stopped: public tunnel closed, Studio stopped, proposer pod stopping.'
    return
}

foreach ($name in @('ORCHESTWIN_RUNPOD_API_KEY', 'ORCHESTWIN_SMTP_USER', 'ORCHESTWIN_SMTP_PASSWORD', 'ORCHESTWIN_NOTIFY_TO')) {
    $current = [Environment]::GetEnvironmentVariable($name)
    if ([string]::IsNullOrEmpty($current)) {
        $value = [Environment]::GetEnvironmentVariable($name, 'User')
        if ([string]::IsNullOrEmpty($value)) { throw "Missing user environment variable $name" }
        Set-Item -Path "Env:$name" -Value $value
    }
}
if ($null -eq (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    throw 'Install cloudflared first: winget install --id Cloudflare.cloudflared -e'
}
$settings = Get-Content -Raw -LiteralPath (Join-Path $repo 'var/studio/local-settings.json') | ConvertFrom-Json
$pod = $settings.remote_pod
if ([string]::IsNullOrEmpty($pod)) { throw 'Set remote_pod in var/studio/local-settings.json.' }

& docker compose --env-file compose.env -f compose.yaml -f compose.local.yaml up -d database
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL did not start.' }

function Invoke-Controller {
    param([string[]]$Arguments)
    & $python $controller @Arguments
    if ($LASTEXITCODE -ne 0) { throw "cloud_proposer.py $($Arguments[0]) failed for pod $pod" }
}

Write-Host "Starting the proposer pod $pod; the model takes several minutes to load."
Invoke-Controller @('start', '--pod', $pod)
Invoke-Controller @('wait', '--pod', $pod)
Invoke-Controller @('sync', '--pod', $pod)
Invoke-Controller @('bootstrap', '--pod', $pod)
Invoke-Controller @('serve', '--pod', $pod, '--engine', 'vllm', '--failure-hold-minutes', '30', '--idle-minutes', "$IdleMinutes")

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo 'scripts/start-studio.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Studio did not start.' }

Get-Process -Name cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
if (Test-Path -LiteralPath $tunnelLog) { Remove-Item -LiteralPath $tunnelLog -Force }
$tunnel = Start-Process -FilePath 'cloudflared' -ArgumentList @('tunnel', '--url', 'http://127.0.0.1:8080', '--http-host-header', '127.0.0.1:8080') -WindowStyle Hidden -PassThru -RedirectStandardError $tunnelLog
$url = $null
$deadline = (Get-Date).AddSeconds(90)
while ($null -eq $url -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    if ($tunnel.HasExited) { throw "cloudflared stopped. See $tunnelLog" }
    if (Test-Path -LiteralPath $tunnelLog) {
        $match = Select-String -LiteralPath $tunnelLog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1
        if ($null -ne $match) { $url = $match.Matches[0].Value }
    }
}
if ($null -eq $url) { throw "The public tunnel did not report its address. See $tunnelLog" }
Write-Host "Demo ready for the supervisors: $url"
Write-Host "The proposer pod stops by itself after $IdleMinutes idle minutes; stop everything with ./scripts/demo-studio.ps1 -Stop"
