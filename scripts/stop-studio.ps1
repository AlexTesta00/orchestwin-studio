param([switch]$StopPod)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
if ($StopPod) {
    $settings = Get-Content -LiteralPath (Join-Path $repo 'var/studio/local-settings.json') -Raw | ConvertFrom-Json
    if ([string]::IsNullOrWhiteSpace($settings.remote_pod)) { throw 'No remote pod is configured in local-settings.json.' }
    $env:ORCHESTWIN_RUNPOD_API_KEY = [Environment]::GetEnvironmentVariable('ORCHESTWIN_RUNPOD_API_KEY', 'User')
    & (Join-Path $repo '.venv/Scripts/python.exe') (Join-Path $repo 'scripts/cloud_proposer.py') stop --pod $settings.remote_pod
    if ($LASTEXITCODE -ne 0) { throw 'The remote pod could not be stopped. Check the Runpod console.' }
}
$statePath = Join-Path $repo 'var/studio/active-session.json'
if (-not (Test-Path -LiteralPath $statePath)) { Write-Host 'No managed Studio session.'; exit }
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$session = [IO.Path]::GetFullPath($state.session)
$allowed = [IO.Path]::GetFullPath((Join-Path $repo 'var/studio')) + [IO.Path]::DirectorySeparatorChar
if (-not $session.StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid Studio session path.' }
if (Test-Path -LiteralPath $session) {
    New-Item -ItemType File -Force -Path (Join-Path $session 'stop.request') | Out-Null
    Start-Sleep -Seconds 3
}
foreach ($entry in $state.processes) {
    $process = Get-Process -Id $entry.id -ErrorAction SilentlyContinue
    if ($process -and $process.StartTime.ToUniversalTime().Ticks -eq ([datetime]$entry.started).ToUniversalTime().Ticks) {
        & taskkill.exe /PID $process.Id /T /F | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not stop Studio process $($process.Id). Session state retained for retry." }
    }
}
Remove-Item -LiteralPath $statePath
Write-Host 'Studio processes stopped. PostgreSQL and all saved projects are retained.'
