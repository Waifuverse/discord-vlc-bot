param([switch]$Interactive)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 'Python 3.11+ is required.')"
if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11+ and add it to PATH, then rerun setup.' }
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required. Install Python, then rerun setup.' }
}
& $taskPython -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if ($Interactive) {
    & $taskPython (Join-Path $PSScriptRoot 'setup_config.py')
} else {
    & $taskPython (Join-Path $PSScriptRoot 'setup_config.py') --prepare
}
if ($LASTEXITCODE -ne 0) { throw 'Setup did not finish.' }
Write-Output 'Edit .env with your bot token, server/channel IDs and media folder. Then run start.ps1.'
