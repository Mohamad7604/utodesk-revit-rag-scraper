$ErrorActionPreference = "Stop"

$py = ".\ui_gradio.py"
if (!(Test-Path $py)) { throw "ui_gradio.py not found in $(Get-Location)" }

# Backup
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item $py "$py.bak.$stamp" -Force
Write-Host "Backup: $py.bak.$stamp" -ForegroundColor Cyan

# Load file
$txt = Get-Content $py -Raw

# Only append once (look for our marker)
if ($txt -notmatch '# --- RUNTIME OVERRIDES: DISABLE OVERLAP GATE ---') {
  $override = @"
# --- RUNTIME OVERRIDES: DISABLE OVERLAP GATE ---
# These override any earlier definitions to remove the MIN_OVERLAP/keyword gate.

MIN_OVERLAP = 1.0  # keep defined so legacy code won't crash; set high so it never passes

def keyword_overlap(query: str, hit: dict) -> float:
    # Neutralized: never contributes to gating
    return 0.0

def confident_enough(hits: list, mode: str, q: str) -> bool:
    # Simple score-only gate (no MIN_OVERLAP, no keyword_overlap)
    if not hits:
        return False
    best = max(hit_confidence(h) for h in hits)
    if mode in ("hybrid", "bm25"):
        return best >= OOD_MIN_SCORE
    return best >= OOD_MIN_SIM
# --- END RUNTIME OVERRIDES ---
"@

  # Append with a blank line
  $txt = $txt.TrimEnd() + "`r`n`r`n" + $override
  Set-Content -Path $py -Value $txt -Encoding UTF8
  Write-Host "Appended runtime overrides to ui_gradio.py" -ForegroundColor Green
}
else {
  Write-Host "Overrides already present; no changes made." -ForegroundColor Yellow
}

# Also ensure .env has no stray Python code for MIN_OVERLAP
$envf = ".\.env"
if (Test-Path $envf) {
  $lines = Get-Content $envf
  $lines = $lines | Where-Object { $_ -notmatch 'MIN_OVERLAP\s*=\s*float\(' } # strip bad python lines
  $lines = $lines | Where-Object { $_ -notmatch '^\s*MIN_OVERLAP\s*=' }       # remove old MIN_OVERLAP env
  $lines | Set-Content -Path $envf -Encoding UTF8
  Write-Host "Cleaned .env (removed MIN_OVERLAP lines)" -ForegroundColor Green
}
