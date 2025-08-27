$ErrorActionPreference = "Stop"

# Project root = parent of the scripts folder
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# --- Settings ---
$WEAVIATE = "http://localhost:8080"
$OLLAMA   = "http://localhost:11434"
$MODEL    = "deepseek-r1:1.5b"

function Test-Endpoint($url,$sec=3){ try { iwr $url -TimeoutSec $sec | Out-Null; return $true } catch { return $false } }

# Ensure ui_gradio.py exists at project root
$py = Join-Path $root "ui_gradio.py"
if (!(Test-Path $py)) { throw "ui_gradio.py not found at $py" }

# Start/verify services
if (-not (Test-Endpoint "$WEAVIATE/v1/meta")) {
  Write-Host "Weaviate not reachable at $WEAVIATE. Start it (docker compose) then re-run this script." -ForegroundColor Yellow
}

if (-not (Test-Endpoint "$OLLAMA/api/tags")) {
  Write-Host "Starting Ollama..." -ForegroundColor Yellow
  Start-Process -WindowStyle Minimized -FilePath "ollama" -ArgumentList "serve"
  Start-Sleep -Seconds 2
}

# Make sure your generation model exists (optional for UI launch)
try {
  if (-not (ollama list | Select-String -SimpleMatch $MODEL)) {
    Write-Host "Pulling $MODEL ..." -ForegroundColor Yellow
    ollama pull $MODEL | Out-Null
  }
} catch {
  Write-Host "Ollama CLI not found or not running; install/launch Ollama if you use it for generation." -ForegroundColor Red
}

# Launch the app
$pyexe = ".\.venv\Scripts\python.exe"
if (!(Test-Path $pyexe)) { throw "Venv python missing at $pyexe" }
& $pyexe $py
