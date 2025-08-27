Param(
  [switch]$Run
)

$ErrorActionPreference = "Stop"

function Test-Http200($Url, $TimeoutSec=3) {
  try {
    $resp = Invoke-WebRequest -Uri $Url -TimeoutSec $TimeoutSec -ErrorAction Stop
    return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300)
  } catch { return $false }
}

# 1) Ensure Docker Desktop is running (best-effort)
if (-not (Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue)) {
  $exe = Join-Path $Env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
  if (Test-Path $exe) {
    Write-Host "Starting Docker Desktop..." -ForegroundColor Yellow
    Start-Process -WindowStyle Minimized -FilePath $exe
    Start-Sleep -Seconds 6
  }
}

# 2) Pick compose file
$composeFile = ".\docker-compose.weaviate.yml"
if (!(Test-Path $composeFile)) { $composeFile = ".\docker-compose.yml" }
if (!(Test-Path $composeFile)) { throw "No compose file found (docker-compose.weaviate.yml or docker-compose.yml)." }

# 3) Bring up services
Write-Host "Starting services via docker compose..." -ForegroundColor Cyan
$useNewCompose = $true
try { docker compose version | Out-Null } catch { $useNewCompose = $false }

if ($useNewCompose) {
  docker compose -f $composeFile up -d
} else {
  docker-compose -f $composeFile up -d
}

Write-Host "Waiting for Weaviate to be ready on http://localhost:8080 ..." -ForegroundColor Cyan
# 4) Wait for readiness (try both endpoints)
$ready = $false
for ($i=1; $i -le 90; $i++) {
  $ok1 = Test-Http200 "http://localhost:8080/v1/.well-known/ready" 2
  $ok2 = Test-Http200 "http://localhost:8080/v1/meta" 2
  if ($ok1 -or $ok2) { $ready = $true; break }
  Start-Sleep -Milliseconds 800
}
if (-not $ready) {
  Write-Host "Weaviate did not report ready in time. Recent logs:" -ForegroundColor Red
  if ($useNewCompose) {
    docker compose -f $composeFile logs --tail=80
  } else {
    docker-compose -f $composeFile logs --tail=80
  }
  exit 1
}
Write-Host "Weaviate is READY " -ForegroundColor Green

# 5) Quick health check for Ollama (optional)
$ollamaOk = Test-Http200 "http://localhost:11434/api/tags" 3
Write-Host ("Ollama:   {0}" -f ($(if ($ollamaOk) {"OK"} else {"NOT REACHABLE"}))) -ForegroundColor ($(if ($ollamaOk) {"Green"} else {"Yellow"}))

# 6) Optionally run the smoketest
if ($Run) {
  $py = ".\.venv\Scripts\python.exe"
  if (!(Test-Path $py)) { $py = "python" }
  if (!(Test-Path .\smoketest_rag.py)) { throw "smoketest_rag.py not found in project root." }

  & $py .\smoketest_rag.py --mode hybrid --alpha 0.5 --k 10
  exit $LASTEXITCODE
} else {
  Write-Host "Tip: re-run with -Run to execute the smoketest." -ForegroundColor Yellow
}
