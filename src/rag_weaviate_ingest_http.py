# src/rag_weaviate_ingest_http.py (v3 client)
import json, sys
from pathlib import Path
import weaviate

WEAVIATE_URL = "http://localhost:8080"
CLASS_NAME = "Tutorial"
DATA = Path("data/processed/tutorials.jsonl")

def ensure_schema(client: weaviate.Client, reset: bool = False):
    schema = client.schema.get()
    existing = {c["class"] for c in schema.get("classes", [])}
    if reset and CLASS_NAME in existing:
        client.schema.delete_class(CLASS_NAME)
        existing.remove(CLASS_NAME)

    if CLASS_NAME not in existing:
        class_obj = {
            "class": CLASS_NAME,
            "description": "Autodesk Revit tutorial page",
            "vectorizer": "text2vec-transformers",
            "moduleConfig": {
                "text2vec-transformers": {
                    "poolingStrategy": "masked_mean",
                    "vectorizeClassName": False
                }
            },
            "properties": [
                {"name": "title",          "dataType": ["text"]},
                {"name": "url",            "dataType": ["string"]},
                {"name": "text",           "dataType": ["text"]},
                {"name": "breadcrumb",     "dataType": ["text[]"]},
                {"name": "n_video_links",  "dataType": ["int"]},
                {"name": "video_links",    "dataType": ["string[]"]},
            ],
        }
        client.schema.create_class(class_obj)

def load_jsonl(p: Path):
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)

def main():
    if not DATA.exists():
        raise SystemExit(f"Missing {DATA}")

    reset = ("--reset" in sys.argv)
    client = weaviate.Client(WEAVIATE_URL)
    ensure_schema(client, reset=reset)

    objs = []
    for rec in load_jsonl(DATA):
        title = rec.get("title") or rec.get("toc_title") or ""
        url = rec.get("url", "")
        text = (rec.get("text") or "").strip()
        path = rec.get("path") or []              # list of crumbs
        vlinks = rec.get("video_links") or []     # list of URLs
        obj = {
            "title": title,
            "url": url,
            "text": text,
            "breadcrumb": path,
            "n_video_links": len(vlinks),
            "video_links": vlinks,
        }
        objs.append(obj)

    client.batch.configure(batch_size=64, dynamic=True)
    with client.batch as batch:
        for o in objs:
            batch.add_data_object(o, class_name=CLASS_NAME)

    # show count
    res = client.query.aggregate(CLASS_NAME).with_meta_count().do()
    count = res["data"]["Aggregate"][CLASS_NAME][0]["meta"]["count"]
    print(f"Ingested {len(objs)} objects; Weaviate now has {count} in {CLASS_NAME} at {WEAVIATE_URL}")

if __name__ == "__main__":
    main()
