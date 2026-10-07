param([switch]$Stop)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $Stop -and (Test-Path -LiteralPath (Join-Path $projectRoot 'data/google-script-active'))) {
    Write-Host 'Google Apps Script is active. Local Windows transfers are disabled to avoid duplicate sends.'
    return
}
$stateDir = Join-Path $projectRoot 'data'
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
$workerPidFile = Join-Path $stateDir 'windows-worker.pid'
$workerPython = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
if (Test-Path -LiteralPath $workerPidFile) {
    $savedWorkerPid = Get-Content -LiteralPath $workerPidFile
    if ($savedWorkerPid -match '^\d+$') {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$savedWorkerPid"
        if ($process -and $process.ExecutablePath -eq $workerPython -and $process.CommandLine.Contains('scripts.windows_worker')) {
            Get-CimInstance Win32_Process -Filter "ParentProcessId=$savedWorkerPid" | Where-Object {
                $_.CommandLine -and $_.CommandLine.Contains('scripts.windows_worker') -and $_.Name -eq 'pythonw.exe'
            } | ForEach-Object { Stop-Process -Id $_.ProcessId }
            Stop-Process -Id $process.ProcessId
        }
    }
    Remove-Item -LiteralPath $workerPidFile
}
if ($Stop) { return }
if (-not (Test-Path -LiteralPath $workerPython)) { throw 'Install the project Python environment first.' }
$workerProcess = Start-Process -FilePath $workerPython -ArgumentList @('-m', 'scripts.windows_worker') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $stateDir 'windows-worker.log') -RedirectStandardError (Join-Path $stateDir 'windows-worker-error.log')
Set-Content -LiteralPath $workerPidFile -Value $workerProcess.Id
Write-Host 'Windows cloud-API worker started. Files remain complete; maximum 50 MB.'
