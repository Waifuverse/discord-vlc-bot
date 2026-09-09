$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run setup.ps1 first.' }
& $taskPython (Join-Path $PSScriptRoot 'vlc_tools.py') check
exit $LASTEXITCODE
