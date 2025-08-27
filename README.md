# Autodesk Revit RAG Scraper

Local RAG pipeline for Revit 2024 docs (Selenium scraper + Weaviate + Ollama).

## Quick start
1. Create & activate venv: .venv\Scripts\activate
2. pip install -r requirements.txt
3. Start Weaviate (docker-compose) and Ollama.
4. Run ingestion in src/ then start the UI.

> Do **not** commit .env, models/, weaviate-*/ — they’re ignored.
