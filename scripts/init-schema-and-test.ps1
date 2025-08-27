$ErrorActionPreference = "Stop"

function Ready($u){ try { (Invoke-WebRequest $u -TimeoutSec 3 -UseBasicParsing).StatusCode -ge 200 } catch { $false } }

# 0) Make sure Weaviate is reachable
if (-not (Ready "http://localhost:8080/v1/meta")) {
  Write-Host "Weaviate not reachable on http://localhost:8080. Start your compose and retry." -ForegroundColor Red
  exit 1
}

# 1) Create TutorialChunk class if missing
$schema = Invoke-RestMethod http://localhost:8080/v1/schema -UseBasicParsing
$exists = $false
if ($schema -and $schema.classes) {
  foreach ($c in $schema.classes) { if ($c.class -eq "TutorialChunk") { $exists = $true; break } }
}

if (-not $exists) {
  Write-Host "Creating schema class: TutorialChunk ..." -ForegroundColor Cyan
  $cls = @{
    class       = "TutorialChunk"
    description = "Autodesk Revit tutorial chunks"
    vectorizer  = "text2vec-transformers"
    moduleConfig = @{
      "text2vec-transformers" = @{
        vectorizeClassName = $false
      }
    }
    properties = @(
      @{ name="page_title";          dataType=@("text")   },
      @{ name="toc_title";           dataType=@("text")   },
      @{ name="chunk_text";          dataType=@("text")   },
      @{ name="page_url";            dataType=@("text")   },
      @{ name="breadcrumb";          dataType=@("text[]") },
      @{ name="chunk_index";         dataType=@("int")    },
      @{ name="video_links";         dataType=@("text[]") },
      @{ name="category";            dataType=@("text")   },
      @{ name="time_required";       dataType=@("text")   },
      @{ name="tutorial_files_used"; dataType=@("text[]") }
    )
  } | ConvertTo-Json -Depth 6
  Invoke-RestMethod -Method Post -Uri http://localhost:8080/v1/schema/classes -ContentType "application/json" -Body $cls | Out-Null
  Write-Host "Class created." -ForegroundColor Green
} else {
  Write-Host "Schema class TutorialChunk already exists." -ForegroundColor Green
}

# 2) Ingest your scraped data (rebuilds objects)
$py = ".\.venv\Scripts\python.exe"
if (!(Test-Path $py)) { $py = "python" }
if (!(Test-Path ".\src\rag_chunk_and_ingest.py")) { throw "Missing src\rag_chunk_and_ingest.py" }

Write-Host "Ingesting data into Weaviate..." -ForegroundColor Cyan
& $py .\src\rag_chunk_and_ingest.py
if ($LASTEXITCODE -ne 0) { throw "Ingestion script failed with exit code $LASTEXITCODE" }

# 3) Show count
$gql = @{ query = "{ Aggregate { TutorialChunk { meta { count } } } }" } | ConvertTo-Json
$agg = Invoke-RestMethod -Method Post -Uri http://localhost:8080/v1/graphql -ContentType "application/json" -Body $gql
$count = $agg.data.Aggregate.TutorialChunk.meta.count
Write-Host ("Objects in TutorialChunk: {0}" -f $count) -ForegroundColor Cyan

# 4) Run 5-question smoketest (backend only)
if (Test-Path .\smoketest_rag.py) {
  Write-Host "Running smoketest..." -ForegroundColor Cyan
  & $py .\smoketest_rag.py --mode hybrid --alpha 0.5 --k 10
} else {
  Write-Host "smoketest_rag.py not found; skip test." -ForegroundColor Yellow
}
