$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'Create .venv and install the project dependencies first. See README.md.'
}
& $taskPython -X utf8 -m empire run
exit $LASTEXITCODE
