# src/qa_validate.py
import json
from pathlib import Path
import pandas as pd
import requests

IN = Path("data/processed/tutorials.jsonl")
assert IN.exists(), f"Missing {IN}"

# --- load JSONL -> DataFrame ---
rows = []
with IN.open("r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            rows.append(json.loads(line))
df = pd.json_normalize(rows)

# Ensure expected columns exist
for col, default in [
    ("toc_title", ""), ("title", ""), ("url", ""),
    ("video_links", []), ("error", ""), ("text", "")
]:
    if col not in df.columns:
        df[col] = default

# --- derive fields used in checks ---
def safe_len_list(x):
    return len(x) if isinstance(x, list) else 0

df["n_video_links"] = df["video_links"].apply(safe_len_list)

# Treat missing/NaN error as empty; avoid "nan" string counting as an error
df["error"] = (
    df["error"]
    .where(df["error"].notna(), "")
    .astype(str)
    .replace({"nan": "", "None": ""})
    .str.strip()
)
df["has_error"] = df["error"].ne("")

# Robust empty-title detection
df["title"] = df["title"].where(df["title"].notna(), "").astype(str).str.strip()
empty_titles = df.index[df["title"].eq("")].tolist()

# Identify "Video:" and "Part N:" pages for stricter expectations
df["is_video_page"] = (
    df["toc_title"].astype(str).str.match(r"^Video\b", case=False, na=False)
    | df["title"].astype(str).str.match(r"^Video\b", case=False, na=False)
    | df["toc_title"].astype(str).str.contains(r"\bVideo Gallery\b|\bTutorial Videos\b", case=False, na=False)
)
df["is_part_page"] = df["toc_title"].astype(str).str.match(r"^Part\s*\d+\b", case=False, na=False)

# URL normalization for duplicate detection (lightweight)
def norm_url(u):
    if not isinstance(u, str):
        return ""
    u = u.strip()
    # remove trailing slash (but keep query/fragment intact):
    if len(u) > 1 and u.endswith("/"):
        u = u[:-1]
    return u

df["url_norm"] = df["url"].apply(norm_url)
unique_urls = df["url_norm"].nunique()
dup_mask = df["url_norm"].duplicated(keep=False)
dup_urls_df = df.loc[dup_mask].sort_values("url_norm")

# --- core checks ---
total = len(df)
errors_count = int(df["has_error"].sum())
video_without_links = df.loc[df["is_video_page"] & (df["n_video_links"] == 0), ["toc_title", "title", "url"]]
part_without_links  = df.loc[df["is_part_page"]  & (df["n_video_links"] == 0), ["toc_title", "title", "url"]]

print("== QA SUMMARY ==")
print(f"Total rows:               {total}")
print(f"Unique URLs:              {unique_urls}")
print(f"Rows with errors:         {errors_count}")
print(f"Duplicate URLs (rows):    {len(dup_urls_df)}")
print(f"Video pages w/o links:    {len(video_without_links)}")
print(f"Part pages w/o links:     {len(part_without_links)}")
print(f"Empty titles:             {len(empty_titles)}")

# --- write reports ---
out_cols = ["toc_title", "title", "url", "n_video_links", "has_error", "error"]
df[out_cols].sort_values(["has_error", "n_video_links"], ascending=[False, True]) \
  .to_csv("data/processed/qa_summary.csv", index=False, encoding="utf-8-sig")

video_without_links.to_csv("data/processed/qa_video_pages_without_links.csv", index=False, encoding="utf-8-sig")
part_without_links.to_csv("data/processed/qa_part_pages_without_links.csv", index=False, encoding="utf-8-sig")

if len(dup_urls_df):
    dup_urls_df[out_cols + ["url_norm"]].to_csv("data/processed/qa_duplicate_urls.csv", index=False, encoding="utf-8-sig")

# Optional: light HTTP sample (just to see 200s)
sample = df["url"].dropna().sample(min(10, len(df)), random_state=42).tolist()
def ping(u):
    try:
        r = requests.get(u, timeout=15, allow_redirects=True)
        return r.status_code
    except Exception as e:
        return str(e)
pd.DataFrame([(u, ping(u)) for u in sample], columns=["url", "status"]) \
  .to_csv("data/processed/qa_http_sample.csv", index=False, encoding="utf-8-sig")

print("Wrote:")
print(" - data/processed/qa_summary.csv")
print(" - data/processed/qa_video_pages_without_links.csv")
print(" - data/processed/qa_part_pages_without_links.csv")
if len(dup_urls_df):
    print(" - data/processed/qa_duplicate_urls.csv")
print(" - data/processed/qa_http_sample.csv  (optional)")
