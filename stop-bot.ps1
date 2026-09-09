$ErrorActionPreference = 'Stop'
$taskPidFile = Join-Path $PSScriptRoot '.state\bot.pid'
if (-not (Test-Path -LiteralPath $taskPidFile)) {
    Write-Output 'No background process marker exists. If running in a console, press Ctrl+C there.'
    exit 0
}
$taskBotPid = [int](Get-Content -LiteralPath $taskPidFile -Raw).Trim()
$taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $taskBotPid"
if ($null -eq $taskProcess) {
    Write-Output 'The recorded bot process has already stopped.'
    exit 0
}
$taskScript = Join-Path $PSScriptRoot 'bot.py'
if ($taskProcess.Name -ne 'python.exe' -or $taskProcess.CommandLine -notmatch [regex]::Escape($taskScript)) {
    throw 'The saved PID belongs to another process; no process was stopped.'
}
Stop-Process -Id $taskBotPid
Write-Output 'GroupVid stopped. VLC remains open.'
