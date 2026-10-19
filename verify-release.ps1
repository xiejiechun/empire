param([switch]$Recover)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Create .venv and install requirements.lock before release verification.'
}
$arguments = @((Join-Path $projectRoot 'scripts\release.py'))
if ($Recover) { $arguments += '--recover' }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Release gate failed; the publication journal describes any required recovery.' }
