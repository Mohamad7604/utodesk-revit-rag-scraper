$ErrorActionPreference = "Stop"

$pyFile = ".\ui_gradio.py"
$envFile = ".\.env"

if (!(Test-Path $pyFile)) { throw "ui_gradio.py not found in current folder: $(Get-Location)" }

# --- Backup ---
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item $pyFile "$pyFile.bak.$stamp" -Force
Write-Host "Backed up to $pyFile.bak.$stamp" -ForegroundColor Cyan

# --- Load file ---
$text = Get-Content $pyFile -Raw

# 1) Fix escaped triple quotes from a bad patch: \"\"\"  ->  """
$before = $text
$text = $text -replace '\\\"\\\"\\\"', '"""'
if ($text -ne $before) { Write-Host "Fixed escaped triple quotes in ui_gradio.py" -ForegroundColor Green }

# 2) Ensure MIN_OVERLAP is defined (without putting Python in .env)
if ($text -notmatch '(?m)^\s*MIN_OVERLAP\s*=') {
  $text += @"

# --- PATCH: define MIN_OVERLAP ---
try:
    MIN_OVERLAP
except NameError:
    import os
    MIN_OVERLAP = float(os.getenv("MIN_OVERLAP","0.12"))
# --- END PATCH ---

"@
  Write-Host "Added MIN_OVERLAP definition guard" -ForegroundColor Green
}

# 3) Ensure keyword_overlap exists (safe version, no docstring)
if ($text -notmatch '(?m)^\s*def\s+keyword_overlap\(') {
  $text += @"

# --- PATCH: keyword_overlap ---
def keyword_overlap(query: str, hit: dict) -> float:
    # Returns fraction (0..1) of 4+ letter query tokens that appear in the chunk text.
    import re
    text = (hit.get("chunk_text") or "").lower()
    toks = [t for t in re.findall(r"[a-zA-Z]{4,}", (query or "").lower())]
    if not toks:
        return 0.0
    found = sum(1 for t in toks if t in text)
    return found / len(toks)
# --- END PATCH ---

"@
  Write-Host "Added keyword_overlap()" -ForegroundColor Green
}

# 4) Ensure confident_enough has the MIN_OVERLAP safety valve and correct signature
if ($text -notmatch '(?m)^\s*def\s+confident_enough\(\s*hits:\s*list,\s*mode:\s*str,\s*q:\s*str\)') {
  $text += @"

# --- PATCH: confident_enough ---
def confident_enough(hits: list, mode: str, q: str) -> bool:
    # Gate based on best-hit confidence plus keyword-overlap safety valve on top-3.
    if not hits:
        return False
    best = max(hit_confidence(h) for h in hits)
    top3 = hits[:3]
    has_overlap = any(keyword_overlap(q, h) >= MIN_OVERLAP for h in top3)
    if mode in ("hybrid", "bm25"):
        return (best >= OOD_MIN_SCORE) or has_overlap
    return (best >= OOD_MIN_SIM) or has_overlap
# --- END PATCH ---

"@
  Write-Host "Added confident_enough()" -ForegroundColor Green
}

# 5) Save file
Set-Content -Path $pyFile -Value $text -Encoding UTF8
Write-Host "Saved fixes to ui_gradio.py" -ForegroundColor Green

# 6) Clean .env (KEY=VALUE only; ensure MIN_OVERLAP present)
if (!(Test-Path $envFile)) { New-Item -ItemType File -Path $envFile | Out-Null }
$lines = Get-Content $envFile -ErrorAction SilentlyContinue
# Remove any accidental Python lines
$lines = $lines | Where-Object { $_ -notmatch 'MIN_OVERLAP\s*=\s*float\(' }

function Set-KV([string[]]$arr,[string]$key,[string]$val) {
  $others = $arr | Where-Object { $_ -notmatch "^\s*$([regex]::Escape($key))\s*=" }
  return @($others + "$key=$val")
}

$lines = Set-KV $lines "WEAVIATE_URL"   "http://localhost:8080"
$lines = Set-KV $lines "OLLAMA_URL"     "http://localhost:11434"
$lines = Set-KV $lines "OLLAMA_MODEL"   "deepseek-r1:1.5b"
$lines = Set-KV $lines "UI_PORT"        "7860"
$lines = Set-KV $lines "OOD_MIN_SCORE"  "0.35"
$lines = Set-KV $lines "OOD_MIN_SIM"    "0.35"
$lines = Set-KV $lines "MIN_OVERLAP"    "0.12"
$lines = Set-KV $lines "DEBUG_RETRIEVAL" "1"

$lines | Set-Content -Path $envFile -Encoding UTF8
Write-Host "Updated .env" -ForegroundColor Green

Write-Host "`nDone. Start the app with:" -ForegroundColor Cyan
Write-Host "  .\.venv\Scripts\python.exe .\ui_gradio.py" -ForegroundColor Yellow
