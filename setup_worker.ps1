param([string]$BasePython = 'python', [switch]$SkipModel)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
function Run-Step([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Exe $Arguments" }
}
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    Run-Step $BasePython @('-m','venv','.venv')
}
$DemoPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
Run-Step $DemoPython @('-m','pip','install','--no-cache-dir','--timeout','120','--retries','4','torch==2.7.1','--index-url','https://download.pytorch.org/whl/cpu')
Run-Step $DemoPython @('-m','pip','install','--no-cache-dir','--timeout','120','--retries','4','-r','requirements-worker.txt')
Run-Step $DemoPython @('tools\download_source.py')
if (-not $SkipModel) { Run-Step $DemoPython @('tools\download_model.py') }
Write-Host 'Dependencies installed. Check RAM before running worker/watch.py.'
