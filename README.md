# Autodesk Revit RAG Scraper (CLI-only)

Local RAG pipeline for **Revit 2024 docs**  
**Flow:** scrape (out of scope here) → **hierarchical chunking** → ingest to **Weaviate** → query via **Ollama** → smoke tests (no UI).

**What’s included**
- Hierarchical chunker (`src/chunk_hierarchical.py`) with breadcrumb context (H1/H2/H3).
- Weaviate class **`TutorialChunk`** (arrays like `breadcrumb` & `tutorial_files_used` are `text[]`).
- Hybrid / BM25 / vector search; guardrails for OOD answers.
- DeepSeek R1-friendly prompting (no stop tokens, strip `<think>`, short retry on empty answer).
- Scripted ingestion and smoke tests (PowerShell).

**What’s not included**
- Gradio UI (removed). Run via scripts/CLI.

## Requirements
- Python 3.10+ (tested on 3.12)
- Weaviate @ `http://localhost:8080` with `text2vec-transformers`
- Ollama @ `http://localhost:11434` with a local model (default: `deepseek-r1:1.5b`)

## Quick Start (Windows PowerShell)

```powershell
# 1) Setup
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install requests weaviate-client

# 2) Infra
# Weaviate (ensure text2vec-transformers module is enabled)
# Ollama
ollama serve
ollama pull deepseek-r1:1.5b

# 3) Put docs under .\data\ (md/html/json/txt…)

# 4) Ingest (drop+recreate class, chunk hierarchically, batch ingest)
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\reingest-hierarchical.ps1 -Wipe

# 5) Verify count
.\scripts\weaviate-count.ps1

# 6) Smoke tests
.\scripts\smoke.ps1
