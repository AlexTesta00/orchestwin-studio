param([string]$Configuration = 'var/studio/local-settings.json')
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $repo
$settings = Get-Content -LiteralPath $Configuration -Raw | ConvertFrom-Json
$python = Join-Path $repo '.venv/Scripts/python.exe'
$node = $settings.node
if (-not (Test-Path -LiteralPath $node -PathType Leaf)) { throw 'Configure the Node executable in local-settings.json.' }
$node = (Resolve-Path -LiteralPath $node).ProviderPath
# The API uses this same selected Node binary for syntax-only source validation.
$env:PATH = [IO.Path]::GetDirectoryName($node) + [IO.Path]::PathSeparator + $env:PATH
$access = [string]$settings.access
if ([string]::IsNullOrWhiteSpace($access)) { $access = 'accounts' }
if ($access -cnotin @('local', 'accounts')) { throw 'The access setting must be local or accounts.' }
$accessArgs = @()
$localOwner = [string]$settings.local_owner_email
if ($access -ceq 'local') { $accessArgs = @('--access', 'local') }
if ($access -ceq 'local' -and -not [string]::IsNullOrWhiteSpace($localOwner)) { $accessArgs += @('--local-owner', $localOwner) }
function Test-DotenvKey([string]$path, [string]$name) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }
    $present = $false
    $pattern = '^\s*(?:export\s+)?' + [regex]::Escape($name) + '\s*=(.*)$'
    foreach ($line in [IO.File]::ReadLines($path)) {
        if ($line -match $pattern) {
            $present = $Matches[1].Trim().Trim('"').Trim("'").Trim().Length -gt 0
        }
    }
    return $present
}
$providersConfig = $settings.providers_config_file
$hosted = -not [string]::IsNullOrWhiteSpace($providersConfig)
$providers = $null
if ($hosted) {
    if ($providersConfig -notmatch '^[A-Za-z]:[\\/]' -or -not (Test-Path -LiteralPath $providersConfig -PathType Leaf)) { throw 'The providers configuration must be an existing absolute file path.' }
    $providersConfig = [IO.Path]::GetFullPath($providersConfig)
    $providers = Get-Content -LiteralPath $providersConfig -Raw | ConvertFrom-Json
    $dotenv = Join-Path $repo '.env'
    $keyNames = @($providers.providers | Where-Object { $_.kind -notin @('OPENAI_COMPATIBLE_LOCAL', 'CLAUDE_CODE_CLI') } | ForEach-Object { [string]$_.api_key_env } | Sort-Object -Unique)
    foreach ($name in $keyNames) {
        if ($name -cnotmatch '^ORCHESTWIN_[A-Z0-9_]{1,48}_API_KEY$') { throw 'The providers configuration names an invalid API key variable.' }
        if (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, 'Process'))) { continue }
        if (Test-DotenvKey $dotenv $name) { continue }
        if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, 'User'))) {
            throw "Missing API key $name. Add it to the .env file of the repository or to the user environment variables."
        }
        [Environment]::SetEnvironmentVariable($name, [Environment]::GetEnvironmentVariable($name, 'User'), 'Process')
    }
}
$tunnelPort = $null
$remoteConfig = $settings.remote_proposal_config_file
$remotePod = $settings.remote_pod
$useTunnel = -not [string]::IsNullOrWhiteSpace($remoteConfig)
if ($hosted -and $useTunnel) {
    $remoteFull = [IO.Path]::GetFullPath($remoteConfig)
    $useTunnel = @($providers.providers | Where-Object { $_.kind -eq 'OPENAI_COMPATIBLE_LOCAL' -and [IO.Path]::GetFullPath([string]$_.config_file) -eq $remoteFull }).Count -gt 0
}
if ($useTunnel) {
    if ($remoteConfig -notmatch '^[A-Za-z]:[\\/]' -or -not (Test-Path -LiteralPath $remoteConfig -PathType Leaf)) { throw 'The remote proposal configuration must be an existing absolute file path.' }
    if ([string]::IsNullOrWhiteSpace($remotePod) -or $remotePod -notmatch '^[A-Za-z0-9_-]+$') { throw 'The remote proposal configuration requires the pod identifier.' }
    $remoteRuntime = Get-Content -LiteralPath $remoteConfig -Raw | ConvertFrom-Json
    if ($remoteRuntime.base_url -notmatch '^http://127\.0\.0\.1:([0-9]+)$') { throw 'The remote proposal configuration must target a loopback tunnel port.' }
    $tunnelPort = [int]$Matches[1]
    if ($tunnelPort -in @(8000, 8080, 8787, 8788)) { throw 'The tunnel port must not collide with Studio ports.' }
}
$ports = @(8000, 8080, 8787, 8788)
if ($null -ne $tunnelPort) { $ports += $tunnelPort }
foreach ($port in $ports) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is already in use. Stop the previous Studio session first."
    }
}
function Quote-Argument([string]$value) {
    if ($value.Contains('"')) { throw 'Quotes in paths are unsupported.' }
    return '"' + $value + '"'
}
$session = Join-Path $repo ('var/studio/session-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$logs = Join-Path $repo 'var/studio/logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
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
try {
    if ($null -ne $tunnelPort) {
        $children += Start-StudioProcess $python @('scripts/cloud_proposer.py', 'tunnel', '--pod', $remotePod) 'tunnel' $repo
        Write-Host "Opening the proposer tunnel on port $tunnelPort."
        $deadline = (Get-Date).AddSeconds(90)
        while (-not (Get-NetTCPConnection -LocalPort $tunnelPort -State Listen -ErrorAction SilentlyContinue)) {
            if (@($children | Where-Object HasExited).Count) { throw 'The proposer tunnel stopped. See var/studio/logs/tunnel.stderr.log.' }
            if ((Get-Date) -gt $deadline) { throw 'The proposer tunnel did not open.' }
            Start-Sleep -Seconds 2
        }
        if (-not $hosted) {
            $manifest = Get-Content -LiteralPath $models -Raw | ConvertFrom-Json
            $models = Join-Path $session 'models-remote.json'
            $remoteManifest = [ordered]@{
                schema_version = 1
                proposal_config_file = $remoteConfig.Replace('\', '/')
                final_evaluator_config_file = $manifest.final_evaluator_config_file
            }
            $remoteManifest | ConvertTo-Json | Set-Content -LiteralPath $models -Encoding ascii
        }
    }
    if ($hosted) {
        New-Item -ItemType Directory -Force -Path $session | Out-Null
        $models = Join-Path $session 'models-hosted.json'
        $hostedManifest = [ordered]@{
            schema_version = 2
            providers_config_file = $providersConfig.Replace('\', '/')
            final_evaluator_config_file = $null
        }
        $hostedManifest | ConvertTo-Json | Set-Content -LiteralPath $models -Encoding ascii
        Write-Host 'Hosted model providers selected; no local proposer is required.'
    }
    & $python scripts/studio_runtime.py check --models $models @accessArgs | Out-File -LiteralPath (Join-Path $session 'readiness.json') -Encoding ascii
    if ($LASTEXITCODE -ne 0) { throw 'Real model readiness failed.' }
    $children += Start-StudioProcess $python (@('scripts/studio_runtime.py', 'api', '--models', (Quote-Argument $models)) + @($accessArgs | ForEach-Object { Quote-Argument $_ })) 'api' $repo
    $children += Start-StudioProcess $node @('node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1', '--port', '8080', '--strictPort') 'frontend' (Join-Path $repo 'frontend')
    $deadline = (Get-Date).AddSeconds(60)
    do {
        Start-Sleep -Seconds 1
        if (@($children | Where-Object HasExited).Count) { throw 'A Studio service stopped. See var/studio/logs.' }
        try { $ready = (Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/v1/health' -TimeoutSec 2 -UseBasicParsing).StatusCode -eq 200 } catch { $ready = $false }
    } until ($ready -or (Get-Date) -gt $deadline)
    if (-not $ready) { throw 'API startup timed out.' }
    [ordered]@{session = $session; processes = @($children | ForEach-Object { @{id = $_.Id; started = $_.StartTime.ToUniversalTime().ToString('o')} })} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath 'var/studio/active-session.json'
    if ($access -ceq 'local') { Write-Host 'Local access: the Studio works with the account of this computer, without sign-in.' }
    Write-Host 'Studio ready: http://127.0.0.1:8080. Stop with ./scripts/stop-studio.ps1.'
} catch {
    foreach ($child in $children) { if (-not $child.HasExited) { & taskkill.exe /PID $child.Id /T /F | Out-Null } }
    throw
}
