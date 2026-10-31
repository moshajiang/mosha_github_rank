param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) { throw 'Create the project virtual environment first. See README.md.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend\dist\index.html'))) { throw 'Build frontend first: cd frontend; npm ci; npm run build' }
& $projectPython -m uvicorn github_rank.api:create_app --factory --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
