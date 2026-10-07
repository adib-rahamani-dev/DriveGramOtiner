param([string]$WslDistribution = 'Ubuntu-22.04')
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
& (Join-Path $PSScriptRoot 'Windows-Worker.ps1') -Stop
$portableRoot = $projectRoot.Replace('\', '/')
$linuxRoot = (& wsl.exe -d $WslDistribution -u root -- wslpath -a $portableRoot | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $linuxRoot.StartsWith('/')) { throw 'Could not resolve the project in WSL.' }
& wsl.exe -d $WslDistribution -u root -- /usr/bin/docker compose --project-directory $linuxRoot -f "$linuxRoot/compose.yaml" --env-file "$linuxRoot/.env" stop
if ($LASTEXITCODE -ne 0) { throw 'Could not stop the project services.' }
$keepalivePath = "$linuxRoot/scripts/keepalive.sh"
Get-CimInstance Win32_Process -Filter "Name='wsl.exe'" | Where-Object {
    $_.CommandLine -and $_.CommandLine.Contains($keepalivePath) -and $_.CommandLine.Contains($WslDistribution)
} | ForEach-Object { Stop-Process -Id $_.ProcessId }
Write-Host 'DriveGram stopped. Persistent database and files were preserved.'
