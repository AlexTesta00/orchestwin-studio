param([string]$Configuration = 'var/studio/local-settings.json')
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $repo
$settings = Get-Content -LiteralPath $Configuration -Raw | ConvertFrom-Json
$python = Join-Path $repo '.venv/Scripts/python.exe'
$node = $settings.node
if (-not (Test-Path -LiteralPath $node)) { throw 'Configure the Node executable in local-settings.json.' }
foreach ($port in @(8000, 8080, 8787, 8788)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is already in use. Stop the previous Studio session first."
    }
}
function Convert-ToWslPath([string]$value) {
    $full = [IO.Path]::GetFullPath($value)
    if ($full -notmatch '^([A-Za-z]):[\\/](.*)$') { throw 'A local Windows drive path is required.' }
    return '/mnt/' + $Matches[1].ToLowerInvariant() + '/' + $Matches[2].Replace('\', '/')
}
function Quote-Argument([string]$value) {
    if ($value.Contains('"')) { throw 'Quotes in paths are unsupported.' }
    return '"' + $value + '"'
}
$session = Join-Path $repo ('var/studio/session-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
# The model server creates the session directory after validating the adapter.
$logs = Join-Path $repo 'var/studio/logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$linuxRepo = Convert-ToWslPath $repo
$linuxSession = Convert-ToWslPath $session
$models = Join-Path $session 'models.json'
$children = @()
function Start-StudioProcess($executable, $arguments, $name, $workingDirectory) {
    $process = Start-Process -FilePath $executable -ArgumentList $arguments -WorkingDirectory $workingDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs "$name.stdout.log") -RedirectStandardError (Join-Path $logs "$name.stderr.log")
    return $process
}
& docker compose --env-file compose.env -f compose.yaml -f compose.studio.yaml up -d --wait database
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL could not start. Check Docker Desktop.' }
& $python scripts/studio_runtime.py migrate
if ($LASTEXITCODE -ne 0) { throw 'Database migrations failed.' }
Push-Location (Join-Path $repo 'frontend')
try {
    & $node node_modules/vite/bin/vite.js build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
$modelArgs = @('--exec', (Quote-Argument "$linuxRepo/environments/training/.venv/bin/python"), (Quote-Argument "$linuxRepo/environments/training/serve_studio_models.py"), '--adapter', (Quote-Argument (Convert-ToWslPath $settings.adapter)), '--weights-sha256', $settings.weights_sha256, '--config-sha256', $settings.config_sha256, '--output', (Quote-Argument $linuxSession))
if ($settings.weights_sha256 -notmatch '^[0-9a-f]{64}$' -or $settings.config_sha256 -notmatch '^[0-9a-f]{64}$') { throw 'Expected adapter hashes are required.' }
try {
    $model = Start-StudioProcess 'wsl.exe' $modelArgs 'models' $repo
    $children += $model
    Write-Host 'Loading real local models. This can take several minutes; logs: var/studio/logs.'
    $deadline = (Get-Date).AddMinutes(15)
    while (-not (Test-Path -LiteralPath $models)) {
        if ($model.HasExited) { throw 'Model startup failed. See models.stderr.log.' }
        if ((Get-Date) -gt $deadline) { throw 'Model startup timed out.' }
        Start-Sleep -Seconds 3
    }
    & $python scripts/studio_runtime.py check --models $models > (Join-Path $session 'readiness.json')
    if ($LASTEXITCODE -ne 0) { throw 'Real model readiness failed.' }
    $children += Start-StudioProcess $python @('scripts/studio_runtime.py', 'api', '--models', (Quote-Argument $models)) 'api' $repo
    $children += Start-StudioProcess $node @('node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1', '--port', '8080', '--strictPort') 'frontend' (Join-Path $repo 'frontend')
    $deadline = (Get-Date).AddSeconds(60)
    do {
        Start-Sleep -Seconds 1
        if (@($children | Where-Object HasExited).Count) { throw 'A Studio service stopped. See var/studio/logs.' }
        try { $ready = (Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/v1/health' -TimeoutSec 2).StatusCode -eq 200 } catch { $ready = $false }
    } until ($ready -or (Get-Date) -gt $deadline)
    if (-not $ready) { throw 'API startup timed out.' }
    [ordered]@{session = $session; processes = @($children | ForEach-Object { @{id = $_.Id; started = $_.StartTime.ToUniversalTime().ToString('o')} })} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath 'var/studio/active-session.json'
    Write-Host 'Studio ready: http://127.0.0.1:8080. Stop with ./scripts/stop-studio.ps1.'
} catch {
    if (Test-Path -LiteralPath $session) {
        New-Item -ItemType File -Force -Path (Join-Path $session 'stop.request') | Out-Null
        Start-Sleep -Seconds 3
    }
    foreach ($child in $children) { if (-not $child.HasExited) { & taskkill.exe /PID $child.Id /T /F | Out-Null } }
    throw
}
