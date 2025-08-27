# src/make_excel_csv.py
import json
from pathlib import Path
import pandas as pd

IN_JSONL = Path("data/processed/tutorials.jsonl")
OUT_CSV  = Path("data/processed/tutorials_excel.csv")

def load_jsonl(p: Path):
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)

def flatten(rec):
    meta = rec.get("meta") or {}
    path = rec.get("path") or []
    vids = rec.get("video_links") or []
    text = (rec.get("text") or "").replace("\r", " ").replace("\n", " ").strip()
    return {
        "toc_title": rec.get("toc_title", ""),
        "title": rec.get("title", ""),
        "url": rec.get("url", ""),
        "breadcrumb": " > ".join(path),
        "category": meta.get("Category", ""),
        "time_required": meta.get("Time Required", ""),
        "tutorial_files_used": meta.get("Tutorial Files Used", ""),
        "n_video_links": len(vids),
        "video_links": "; ".join(vids),
        "error": rec.get("error", ""),
        # keep a short preview so the sheet stays readable
        "text_preview": text[:400],
    }

def main():
    assert IN_JSONL.exists(), f"Missing {IN_JSONL}"
    rows = [flatten(r) for r in load_jsonl(IN_JSONL)]
    df = pd.DataFrame(rows, columns=[
        "toc_title","title","url","breadcrumb",
        "category","time_required","tutorial_files_used",
        "n_video_links","video_links","error","text_preview"
    ])
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig helps Excel render Unicode cleanly
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"Wrote {OUT_CSV} with {len(df)} rows")

if __name__ == "__main__":
    main()
