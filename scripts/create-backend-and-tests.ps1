Param([switch]$Run)

$ErrorActionPreference = "Stop"

# pick Python
$py = ".\.venv\Scripts\python.exe"
if (!(Test-Path $py)) { $py = "python" }

Write-Host "=== Backend smoke test ===" -ForegroundColor Cyan

# health checks
$w = $false; $o = $false
try { Invoke-WebRequest http://localhost:8080/v1/.well-known/ready -TimeoutSec 5 | Out-Null; $w = $true } catch {}
try { Invoke-WebRequest http://localhost:11434/api/tags -TimeoutSec 5 | Out-Null; $o = $true } catch {}

$wMsg   = if ($w) { "OK" } else { "NOT REACHABLE" }
$wColor = if ($w) { "Green" } else { "Yellow" }
Write-Host ("Weaviate: {0}" -f $wMsg) -ForegroundColor $wColor

$oMsg   = if ($o) { "OK" } else { "NOT REACHABLE" }
$oColor = if ($o) { "Green" } else { "Yellow" }
Write-Host ("Ollama:   {0}" -f $oMsg) -ForegroundColor $oColor

if ($Run) {
  if (Test-Path .\smoketest_rag.py) {
    & $py .\smoketest_rag.py --mode hybrid --alpha 0.5 --k 10
    exit $LASTEXITCODE
  } else {
    Write-Host "smoketest_rag.py not found in project root." -ForegroundColor Red
    exit 1
  }
} else {
  Write-Host "Tip: re-run with -Run to execute the smoketest." -ForegroundColor Yellow
}
