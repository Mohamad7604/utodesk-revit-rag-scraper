# scripts/run.ps1
$proj = Resolve-Path "$PSScriptRoot\.."
Set-Location $proj

# Ensure venv exists
$venvPython = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    python -m venv .venv
}

# Use venv python
& $venvPython -m pip install -r requirements.txt
& $venvPython -m src.main
