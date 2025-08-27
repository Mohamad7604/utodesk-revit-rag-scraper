# src/rag_weaviate_ingest_embedded.py
import json
from pathlib import Path
import pandas as pd
from tqdm import tqdm
import weaviate
from weaviate.embedded import EmbeddedOptions

DATA = Path("data/processed/tutorials.jsonl")
assert DATA.exists(), f"Missing {DATA}"

# Start embedded Weaviate with huggingface + bm25 enabled
client = weaviate.Client(
    embedded_options=EmbeddedOptions(
        hostname="127.0.0.1",
        port=8079,
        persistence_data_path="./weaviate-embedded-data",
        additional_env_vars={
            "ENABLE_MODULES": "text2vec-huggingface,bm25",
            "DEFAULT_VECTORIZER_MODULE": "text2vec-huggingface",
        },
    )
)

# Recreate class
if client.schema.contains({"classes": [{"class": "TutorialChunk"}]}):
    client.schema.delete_class("TutorialChunk")

class_obj = {
  "class": "TutorialChunk",
  "description": "Autodesk Revit 2024 tutorial pages (left-nav chunks).",
  "vectorizer": "text2vec-huggingface",
  "moduleConfig": {
    "text2vec-huggingface": {
      "model": "sentence-transformers/all-MiniLM-L6-v2",
      "options": {"waitForModel": True}
    }
  },
  "invertedIndexConfig": { "bm25": { "k1": 1.2, "b": 0.75 } },
  "properties": [
    {"name":"toc_title","dataType":["text"]},
    {"name":"title","dataType":["text"]},
    {"name":"url","dataType":["text"], "indexInverted": False},
    {"name":"breadcrumb","dataType":["text"]},
    {"name":"category","dataType":["text"]},
    {"name":"time_required","dataType":["text"]},
    {"name":"tutorial_files_used","dataType":["text"]},
    {"name":"n_video_links","dataType":["int"]},
    {"name":"video_links","dataType":["text[]"]},
    {"name":"error","dataType":["text"]},
    {"name":"text","dataType":["text"]},
  ]
}
client.schema.create_class(class_obj)

# Load jsonl
rows = []
with DATA.open("r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            rows.append(json.loads(line))

# Batch import
with client.batch as batch:
    batch.batch_size = 64
    for r in tqdm(rows, desc="Importing"):
        props = {
            "toc_title": r.get("toc_title") or "",
            "title": r.get("title") or "",
            "url": r.get("url") or "",
            "breadcrumb": " > ".join(r.get("path") or []),
            "category": (r.get("meta") or {}).get("Category", ""),
            "time_required": (r.get("meta") or {}).get("Time Required", ""),
            "tutorial_files_used": (r.get("meta") or {}).get("Tutorial Files Used", ""),
            "n_video_links": len(r.get("video_links") or []),
            "video_links": r.get("video_links") or [],
            "error": r.get("error") or "",
            "text": (r.get("text") or "").strip(),
        }
        batch.add_data_object(data_object=props, class_name="TutorialChunk")

print("Done. Count:",
      client.query.aggregate("TutorialChunk").with_fields("meta { count }").do())
client.close()
