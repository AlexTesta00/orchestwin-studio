param([string]$Configuration = 'var/studio/local-settings.json')
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $repo
$settings = Get-Content -LiteralPath $Configuration -Raw | ConvertFrom-Json
$sourcePort = $null
$sourceConfig = $settings.source_proposal_config_file
if ($null -ne $settings.source_proposal_port) {
    if ([string]$settings.source_proposal_port -notmatch '^[0-9]+$' -or [long]$settings.source_proposal_port -lt 1 -or [long]$settings.source_proposal_port -gt 65535) { throw 'The optional source proposal port must be between 1 and 65535.' }
    $sourcePort = [int]$settings.source_proposal_port
    if ($sourcePort -in @(8000, 8080, 8787, 8788)) { throw 'The source proposal endpoint requires its own port.' }
    if (-not [string]::IsNullOrWhiteSpace($sourceConfig)) { throw 'Select a source adapter port or an external source configuration, not both.' }
    if ([string]::IsNullOrWhiteSpace($settings.proposer_adapter)) { throw 'The source proposal port requires the verified proposer adapter.' }
}
if (-not [string]::IsNullOrWhiteSpace($sourceConfig)) {
    if ($sourceConfig -notmatch '^[A-Za-z]:[\\/]' -or -not (Test-Path -LiteralPath $sourceConfig -PathType Leaf)) { throw 'The external source configuration must be an existing absolute file path.' }
    if (@($settings.proposer_adapter, $settings.proposer_weights_sha256, $settings.proposer_config_sha256 | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count -gt 0) { throw 'An external source configuration keeps the local proposal model unadapted.' }
}
$python = Join-Path $repo '.venv/Scripts/python.exe'
$node = $settings.node
if (-not (Test-Path -LiteralPath $node -PathType Leaf)) { throw 'Configure the Node executable in local-settings.json.' }
$node = (Resolve-Path -LiteralPath $node).ProviderPath
# The API uses this same selected Node binary for syntax-only source validation.
$env:PATH = [IO.Path]::GetDirectoryName($node) + [IO.Path]::PathSeparator + $env:PATH
$tunnelPort = $null
$remoteConfig = $settings.remote_proposal_config_file
$remotePod = $settings.remote_pod
if (-not [string]::IsNullOrWhiteSpace($remoteConfig)) {
    if ($remoteConfig -notmatch '^[A-Za-z]:[\\/]' -or -not (Test-Path -LiteralPath $remoteConfig -PathType Leaf)) { throw 'The remote proposal configuration must be an existing absolute file path.' }
    if ([string]::IsNullOrWhiteSpace($remotePod) -or $remotePod -notmatch '^[A-Za-z0-9_-]+$') { throw 'The remote proposal configuration requires the pod identifier.' }
    if ($null -ne $sourcePort -or -not [string]::IsNullOrWhiteSpace($sourceConfig)) { throw 'The remote proposer replaces the local source configuration.' }
    $remoteRuntime = Get-Content -LiteralPath $remoteConfig -Raw | ConvertFrom-Json
    if ($remoteRuntime.base_url -notmatch '^http://127\.0\.0\.1:([0-9]+)$') { throw 'The remote proposal configuration must target a loopback tunnel port.' }
    $tunnelPort = [int]$Matches[1]
    if ($tunnelPort -in @(8000, 8080, 8787, 8788)) { throw 'The tunnel port must not collide with Studio ports.' }
}
$ports = @(8000, 8080, 8787, 8788)
if ($null -ne $sourcePort) { $ports += $sourcePort }
if ($null -ne $tunnelPort) { $ports += $tunnelPort }
foreach ($port in $ports) {
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
$proposerFields = @($settings.proposer_adapter, $settings.proposer_weights_sha256, $settings.proposer_config_sha256)
if (@($proposerFields | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count -gt 0) {
    if ([string]::IsNullOrWhiteSpace($settings.proposer_adapter) -or $settings.proposer_weights_sha256 -notmatch '^[0-9a-f]{64}$' -or $settings.proposer_config_sha256 -notmatch '^[0-9a-f]{64}$') {
        throw 'The optional proposer adapter requires an explicit path and both SHA-256 hashes.'
    }
    if (-not (Test-Path -LiteralPath $settings.proposer_adapter -PathType Container)) { throw 'The selected proposer adapter directory does not exist.' }
    $modelArgs += @('--proposer-adapter', (Quote-Argument (Convert-ToWslPath $settings.proposer_adapter)), '--proposer-weights-sha256', $settings.proposer_weights_sha256, '--proposer-config-sha256', $settings.proposer_config_sha256)
}
if ($null -ne $sourcePort) { $modelArgs += @('--source-proposal-port', $sourcePort) }
if (-not [string]::IsNullOrWhiteSpace($sourceConfig)) { $modelArgs += @('--source-proposal-config-file', (Quote-Argument (Convert-ToWslPath $sourceConfig))) }
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
    if ($null -ne $tunnelPort) {
        $children += Start-StudioProcess $python @('scripts/cloud_proposer.py', 'tunnel', '--pod', $remotePod) 'tunnel' $repo
        Write-Host "Opening the proposer tunnel on port $tunnelPort."
        $deadline = (Get-Date).AddSeconds(90)
        while (-not (Get-NetTCPConnection -LocalPort $tunnelPort -State Listen -ErrorAction SilentlyContinue)) {
            if (@($children | Where-Object HasExited).Count) { throw 'The proposer tunnel stopped. See var/studio/logs/tunnel.stderr.log.' }
            if ((Get-Date) -gt $deadline) { throw 'The proposer tunnel did not open.' }
            Start-Sleep -Seconds 2
        }
        $manifest = Get-Content -LiteralPath $models -Raw | ConvertFrom-Json
        $models = Join-Path $session 'models-remote.json'
        [ordered]@{
            schema_version = 1
            proposal_config_file = $remoteConfig.Replace('\', '/')
            final_evaluator_config_file = $manifest.final_evaluator_config_file
        } | ConvertTo-Json | Set-Content -LiteralPath $models -Encoding ascii
    }
    & $python scripts/studio_runtime.py check --models $models | Out-File -LiteralPath (Join-Path $session 'readiness.json') -Encoding ascii
    if ($LASTEXITCODE -ne 0) { throw 'Real model readiness failed.' }
    $children += Start-StudioProcess $python @('scripts/studio_runtime.py', 'api', '--models', (Quote-Argument $models)) 'api' $repo
    $children += Start-StudioProcess $node @('node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1', '--port', '8080', '--strictPort') 'frontend' (Join-Path $repo 'frontend')
    $deadline = (Get-Date).AddSeconds(60)
    do {
        Start-Sleep -Seconds 1
        if (@($children | Where-Object HasExited).Count) { throw 'A Studio service stopped. See var/studio/logs.' }
        try { $ready = (Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/v1/health' -TimeoutSec 2 -UseBasicParsing).StatusCode -eq 200 } catch { $ready = $false }
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
