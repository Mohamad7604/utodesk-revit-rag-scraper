# Autodesk Revit RAG Scraper

Local RAG pipeline for **Revit 2024** docs: Selenium scraper → chunk & ingest into **Weaviate** → query via **Ollama** → optional **Gradio** UI.

> ⚠️ Secrets are stored in .env and are **not committed**. Heavy/runtime folders (weaviate-data, models) are ignored.

---

## Features
- Selenium scraper for Autodesk Revit tutorials/docs
- Chunking (hierarchical / by tokens) and quality checks
- Weaviate ingestion (HTTP or embedded)
- Retrieval (hybrid or semantic) + LLM answer with sources
- Simple Gradio UI (ui_gradio.py) and CLI utilities

## Repo layout

