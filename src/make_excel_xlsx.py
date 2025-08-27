# src/make_excel_xlsx.py
import json
from pathlib import Path
import pandas as pd

IN_JSONL = Path("data/processed/tutorials.jsonl")
OUT_XLSX = Path("data/processed/tutorials_excel.xlsx")

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
        "text_preview": text[:600],
    }

def main():
    rows = [flatten(r) for r in load_jsonl(IN_JSONL)]
    df = pd.DataFrame(rows, columns=[
        "toc_title","title","url","breadcrumb",
        "category","time_required","tutorial_files_used",
        "n_video_links","video_links","error","text_preview"
    ])
    OUT_XLSX.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(OUT_XLSX, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Tutorials")
        ws = writer.sheets["Tutorials"]
        # Set column widths
        widths = {
            "A": 28, "B": 34, "C": 70, "D": 36, "E": 14, "F": 12, "G": 28,
            "H": 12, "I": 70, "J": 12, "K": 80
        }
        for col, width in widths.items():
            ws.set_column(f"{col}:{col}", width, writer.book.add_format({"text_wrap": True}))
        # Freeze header row and turn on filters
        ws.freeze_panes(1, 0)
        ws.autofilter(0, 0, len(df), len(df.columns)-1)
    print(f"Wrote {OUT_XLSX} with {len(df)} rows")

if __name__ == "__main__":
    main()
