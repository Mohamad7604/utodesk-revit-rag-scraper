$ErrorActionPreference = "Stop"

$py   = ".\ui_gradio.py"
$envf = ".\.env"
if (!(Test-Path $py)) { throw "ui_gradio.py not found in $(Get-Location)" }

# Backup
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item $py "$py.bak.$stamp" -Force
Write-Host "Backup: $py.bak.$stamp" -ForegroundColor Cyan

# Load file
$txt = Get-Content $py -Raw

# 1) Remove any MIN_OVERLAP definitions in ui_gradio.py
$txt = [regex]::Replace($txt, '(?m)^\s*MIN_OVERLAP\s*=.*\r?\n', '')

# 2) Remove keyword_overlap(...) function if present
$patternKO = '(?ms)^\s*def\s+keyword_overlap\([^)]*\):.*?(?=^\s*(def|class)\s|\Z)'
$txt = [regex]::Replace($txt, $patternKO, '')

# 3) Replace confident_enough(...) with a simple, score-only gate
$patternCE = '(?ms)^\s*def\s+confident_enough\([^)]*\):.*?(?=^\s*(def|class)\s|\Z)'
$replacementCE = @"
def confident_enough(hits: list, mode: str, q: str) -> bool:
    # Gate only by retrieval score; no keyword overlap, no MIN_OVERLAP.
    if not hits:
        return False
    best = max(hit_confidence(h) for h in hits)
    if mode in ("hybrid", "bm25"):
        return best >= OOD_MIN_SCORE
    return best >= OOD_MIN_SIM

"@
if ($txt -match $patternCE) {
  $txt = [regex]::Replace($txt, $patternCE, $replacementCE)
} else {
  # If no function found, just append the clean one
  $txt += "`r`n$replacementCE"
}

# Save file
Set-Content -Path $py -Value $txt -Encoding UTF8
Write-Host "Patched ui_gradio.py" -ForegroundColor Green

# 4) Clean .env  remove any MIN_OVERLAP line
if (Test-Path $envf) {
  $envLines = Get-Content $envf -ErrorAction SilentlyContinue
  $envLines = $envLines | Where-Object { $_ -notmatch '^\s*MIN_OVERLAP\s*=' }
  $envLines | Set-Content -Path $envf -Encoding UTF8
  Write-Host "Removed MIN_OVERLAP from .env (if present)" -ForegroundColor Green
}

Write-Host "`nRestart with:" -ForegroundColor Cyan
Write-Host "  .\.venv\Scripts\python.exe .\ui_gradio.py" -ForegroundColor Yellow
