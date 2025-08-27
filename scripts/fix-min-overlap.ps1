$ErrorActionPreference = "Stop"

$py = ".\ui_gradio.py"
$envf = ".\.env"
if (!(Test-Path $py)) { throw "ui_gradio.py not found." }

# --- backup ---
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item $py "$py.bak.$stamp" -Force
Write-Host "Backup: $py.bak.$stamp" -ForegroundColor Cyan

# --- load file ---
$txt = Get-Content $py -Raw

# 1) If MIN_OVERLAP not defined, insert right after OOD_MIN_SIM line
if ($txt -notmatch '(?m)^\s*MIN_OVERLAP\s*=') {
  $txt = $txt -replace '(?m)(^\s*OOD_MIN_SIM\s*=\s*.*?$)',
    '$1' + "`r`n" + 'MIN_OVERLAP = float(os.getenv("MIN_OVERLAP", "0.12"))  # fraction 0..1 used in overlap gate'
  Write-Host "Inserted MIN_OVERLAP definition" -ForegroundColor Green
}

# 2) Ensure confident_enough signature uses q and references MIN_OVERLAP
#    Replace any old definition block with a safe one.
$pattern = '(?s)^\s*def\s+confident_enough\([^)]*\):.*?^\s*$'
$replacement = @"
def confident_enough(hits: list, mode: str, q: str) -> bool:
    \"\"\"Gate using best retrieval score plus a keyword-overlap safety valve.\"\"\"
    if not hits:
        return False
    best = max(hit_confidence(h) for h in hits)
    top3 = hits[:3]
    try:
        thr = float(MIN_OVERLAP)
    except Exception:
        import os
        thr = float(os.getenv("MIN_OVERLAP", "0.12"))
    has_overlap = any(keyword_overlap(q, h) >= thr for h in top3)
    if mode in ("hybrid", "bm25"):
        return (best >= OOD_MIN_SCORE) or has_overlap
    return (best >= OOD_MIN_SIM) or has_overlap

"@

if ($txt -match $pattern) {
  $txt = [regex]::Replace($txt, $pattern, $replacement, 'Multiline, Singleline')
  Write-Host "Replaced confident_enough() with safe version" -ForegroundColor Green
}
elseif ($txt -notmatch '(?m)^\s*def\s+confident_enough\(') {
  $txt += "`r`n$replacement"
  Write-Host "Added confident_enough() (was missing)" -ForegroundColor Green
}

# 3) Ensure keyword_overlap exists (idempotent)
if ($txt -notmatch '(?m)^\s*def\s+keyword_overlap\(') {
  $txt += @"

def keyword_overlap(query: str, hit: dict) -> float:
    \"\"\"Return fraction (0..1) of 4+ letter query tokens that appear in the chunk text.\"\"\"
    import re
    text = (hit.get("chunk_text") or "").lower()
    toks = [t for t in re.findall(r"[A-Za-z]{4,}", (query or "").lower())]
    if not toks:
        return 0.0
    found = sum(1 for t in toks if t in text)
    return found / len(toks)

"
  Write-Host "Added keyword_overlap()" -ForegroundColor Green
}

# 4) Save file
Set-Content -Path $py -Value $txt -Encoding UTF8
Write-Host "Saved ui_gradio.py" -ForegroundColor Green

# 5) Clean .env (KEY=VALUE only; add MIN_OVERLAP=0.12)
if (!(Test-Path $envf)) { New-Item -ItemType File -Path $envf | Out-Null }
$lines = Get-Content $envf -ErrorAction SilentlyContinue

# strip any accidental Python code lines
$lines = $lines | Where-Object { $_ -notmatch 'MIN_OVERLAP\s*=\s*float\(' }

function Set-KV([string[]]$arr, [string]$k, [string]$v) {
  $others = $arr | Where-Object { $_ -notmatch "^\s*$([regex]::Escape($k))\s*=" }
  return @($others + "$k=$v")
}

$lines = Set-KV $lines "WEAVIATE_URL"   "http://localhost:8080"
$lines = Set-KV $lines "OLLAMA_URL"     "http://localhost:11434"
$lines = Set-KV $lines "OLLAMA_MODEL"   "deepseek-r1:1.5b"
$lines = Set-KV $lines "UI_PORT"        "7860"
$lines = Set-KV $lines "OOD_MIN_SCORE"  "0.35"
$lines = Set-KV $lines "OOD_MIN_SIM"    "0.35"
$lines = Set-KV $lines "MIN_OVERLAP"    "0.12"
$lines = Set-KV $lines "DEBUG_RETRIEVAL" "1"

$lines | Set-Content -Path $envf -Encoding UTF8
Write-Host "Updated .env" -ForegroundColor Green

Write-Host "`nDone. Start the app:" -ForegroundColor Cyan
Write-Host "  .\.venv\Scripts\python.exe .\ui_gradio.py" -ForegroundColor Yellow
