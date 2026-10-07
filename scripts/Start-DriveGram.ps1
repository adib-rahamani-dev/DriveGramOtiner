param(
    [string]$WslDistribution = 'Ubuntu-22.04',
    [switch]$NoBuild
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.env'))) {
    throw 'Create the private .env file first. See README.md.'
}
$portableRoot = $projectRoot.Replace('\', '/')
$linuxRoot = (& wsl.exe -d $WslDistribution -u root -- wslpath -a $portableRoot | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $linuxRoot.StartsWith('/')) { throw 'Could not resolve the project in WSL.' }
& wsl.exe -d $WslDistribution -u root -- systemctl start docker
if ($LASTEXITCODE -ne 0) { throw 'Docker Engine in WSL is not ready.' }
$keepalivePath = "$linuxRoot/scripts/keepalive.sh"
$running = Get-CimInstance Win32_Process -Filter "Name='wsl.exe'" | Where-Object {
    $_.CommandLine -and $_.CommandLine.Contains($keepalivePath) -and $_.CommandLine.Contains($WslDistribution)
}
if (-not $running) {
    Start-Process -FilePath 'wsl.exe' -ArgumentList @('-d', $WslDistribution, '-u', 'root', '--', 'sh', "`"$keepalivePath`"") -WindowStyle Hidden | Out-Null
}
$composeArgs = @('compose', '--project-directory', $linuxRoot, '-f', "$linuxRoot/compose.yaml", '--env-file', "$linuxRoot/.env")
if (Test-Path -LiteralPath (Join-Path $projectRoot 'test-results/wheels')) {
    $composeArgs += @('-f', "$linuxRoot/compose.wsl.yaml")
}
& wsl.exe -d $WslDistribution -u root -- /usr/bin/docker @composeArgs config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose configuration is invalid; private settings were not printed.' }
$upArgs = @('up', '-d')
if (-not $NoBuild) { $upArgs += '--build' }
& wsl.exe -d $WslDistribution -u root -- /usr/bin/docker @composeArgs @upArgs
if ($LASTEXITCODE -ne 0) { throw 'Startup failed. Inspect service health without printing environment values.' }
& wsl.exe -d $WslDistribution -u root -- /usr/bin/docker @composeArgs ps
Write-Host 'Local services started. Uploads require completed Google/Telegram settings and consent.'
Write-Host 'A local worker uses this computer internet connection. Use a cloud worker to offload transfer traffic.'
