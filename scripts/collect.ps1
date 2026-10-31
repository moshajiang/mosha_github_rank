param(
    [ValidateSet('all','repositories','news','releases')][string]$Mode = 'all',
    [switch]$NoDiscovery,
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$taskArguments = @('-m','github_rank.cli','collect','--mode',$Mode)
if ($NoDiscovery) { $taskArguments += '--no-discovery' }
if ($Force) { $taskArguments += '--force' }
& $projectPython @taskArguments
exit $LASTEXITCODE
