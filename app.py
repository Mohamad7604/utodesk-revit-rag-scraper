# app.py  Revit 2024 Tutorials Browser (with "Open both" + mapping export)

import json, re, ast, io
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import requests
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Revit 2024 Tutorials  Scraped Browser", layout="wide")

# ----------------------------
# Data loading helpers
# ----------------------------
DEF_JSONL = Path("data/processed/tutorials.jsonl")
DEF_CSV   = Path("data/processed/tutorials.csv")

def load_jsonl(p: Path) -> pd.DataFrame:
    rows = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return pd.json_normalize(rows)

def load_csv(p: Path) -> pd.DataFrame:
    df = pd.read_csv(p, encoding="utf-8")
    return df

def coerce_list_from_cell(x: Any) -> List[str]:
    """CSV may have video_links as a stringified Python list, JSONL as a real list."""
    if isinstance(x, list):
        return x
    if pd.isna(x):
        return []
    s = str(x).strip()
    if not s:
        return []
    # Try JSON
    try:
        j = json.loads(s)
        if isinstance(j, list):
            return [str(u) for u in j]
    except Exception:
        pass
    # Try Python-literal list (what pandas often writes to CSV)
    try:
        j = ast.literal_eval(s)
        if isinstance(j, list):
            return [str(u) for u in j]
    except Exception:
        pass
    # Fallback: split by comma if someone pasted a CSV of URLs
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    return [t.strip().strip("'").strip('"') for t in s.split(",") if t.strip()]

# ----------------------------
# GUID / mapping helpers
# ----------------------------
GUID_RX = re.compile(r"guid=([A-Za-z0-9-]+)")

def get_guid_from_url(u: str) -> Optional[str]:
    if not isinstance(u, str):
        return None
    m = GUID_RX.search(u)
    return m.group(1) if m else None

def extract_all_guids(text: str) -> List[str]:
    if not isinstance(text, str):
        return []
    return [m.group(1) for m in GUID_RX.finditer(text)]

STOPS = set("a an the and of to in on for with at by from into about as is are be this that".split())

def norm_tokens(s: str) -> List[str]:
    if not isinstance(s, str):
        return []
    s2 = re.sub(r"^Part\s+\d+\s*:\s*","", s, flags=re.I)
    s2 = re.sub(r"^Video\s*:\s*","", s2, flags=re.I)
    s2 = re.sub(r"[^a-z0-9\s]+"," ", s2.lower())
    toks = [t for t in s2.split() if t and t not in STOPS]
    return toks

def score_overlap(a: List[str], b: List[str]) -> int:
    return len(set(a) & set(b))

def build_part_to_video_map(df: pd.DataFrame) -> pd.DataFrame:
    """Return DataFrame mapping each 'Part N:' to its stable 'Video:' page via GUID."""
    # Normalize columns that might differ between CSV/JSONL
    if "toc_title" not in df.columns and "toc_title" in df.columns:
        pass  # just a guard
    # Video index: GUID -> row
    video_rows = df[df["toc_title"].str.match(r"^Video\b", case=False, na=False)].copy()
    video_rows["guid"] = video_rows["url"].apply(get_guid_from_url)
    video_rows = video_rows[video_rows["guid"].notna()]

    video_index: Dict[str, Dict[str, Any]] = {
        r["guid"]: r for _, r in video_rows.iterrows()
    }

    # Precompute tokens for each video
    vid_tokens: Dict[str, List[str]] = {
        r["guid"]: norm_tokens(str(r["toc_title"])) for _, r in video_rows.iterrows()
    }

    out_rows = []

    part_rows = df[df["toc_title"].str.match(r"^Part\s+\d+\s*:", case=False, na=False)].copy()
    for _, part in part_rows.iterrows():
        part_title = str(part["toc_title"])
        part_url   = str(part["url"])
        part_tokens = norm_tokens(part_title)

        # Gather candidate GUIDs from the part's video_links
        vid_links = coerce_list_from_cell(part.get("video_links"))
        all_text  = " ".join(vid_links)
        guids = extract_all_guids(all_text)
        candidate_guids = [g for g in guids if g in video_index]

        chosen_guid = None
        chosen_title = None
        chosen_url = None

        if len(candidate_guids) == 1:
            chosen_guid = candidate_guids[0]
        elif len(candidate_guids) >= 2:
            best, best_guid = -1, None
            for g in candidate_guids:
                sc = score_overlap(part_tokens, vid_tokens.get(g, []))
                if sc > best:
                    best, best_guid = sc, g
            chosen_guid = best_guid

        if chosen_guid:
            chosen_title = str(video_index[chosen_guid]["toc_title"])
            chosen_url   = str(video_index[chosen_guid]["url"])

        out_rows.append({
            "part_title": part_title,
            "part_url": part_url,
            "video_title": chosen_title or "",
            "video_url": chosen_url or "",
            "guid": chosen_guid or "",
            "candidates": ", ".join(candidate_guids) if candidate_guids else "",
        })

    return pd.DataFrame(out_rows)

def http_status(u: str, timeout: int = 15) -> str:
    if not u:
        return "N/A"
    try:
        r = requests.get(u, timeout=timeout, allow_redirects=True)
        return f"{r.status_code}"
    except Exception as e:
        return f"ERR: {e.__class__.__name__}"

# ----------------------------
# UI
# ----------------------------
st.title("Revit 2024 Tutorials  Scraped Browser")

with st.sidebar:
    st.header("Data source")
    fmt = st.radio("Choose file", ["JSONL (recommended)", "CSV"], index=0)
    default_path = DEF_JSONL if fmt.startswith("JSONL") else DEF_CSV
    custom = st.text_input("Or custom path", str(default_path))
    path = Path(custom.strip()) if custom.strip() else default_path

# Load
if not path.exists():
    st.error(f"File not found: {path}")
    st.stop()

df = load_jsonl(path) if path.suffix.lower() == ".jsonl" else load_csv(path)

# Derive conveniences
if "video_links" not in df.columns:
    df["video_links"] = [[] for _ in range(len(df))]
df["n_video_links"] = df["video_links"].apply(lambda x: len(coerce_list_from_cell(x)))
df["is_video"] = df["toc_title"].str.match(r"^Video\b", case=False, na=False)
df["is_part"]  = df["toc_title"].str.match(r"^Part\s+\d+:", case=False, na=False)

# Counters
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total pages", f"{len(df)}")
c2.metric("Unique URLs", f"{df['url'].nunique()}")
c3.metric("Video rows", f"{int(df['is_video'].sum())}")
c4.metric("Part rows",  f"{int(df['is_part'].sum())}")

# Build partvideo map (once)
map_df = build_part_to_video_map(df)

# Export mapping button
csv_bytes = map_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
st.download_button(
    label=" Export partvideo map (CSV)",
    data=csv_bytes,
    file_name="part_to_video_map.csv",
    mime="text/csv",
    help="Stable mapping via GUIDs; avoids the broken 'Watch the video' anchors."
)

# ------------- Filters -------------
st.sidebar.header("Filters")

q = st.sidebar.text_input("Search title/toc/text", "")
only_parts = st.sidebar.checkbox("Only show Part pages", value=False)
only_videos = st.sidebar.checkbox("Only show Video pages", value=False)
only_has_video_link = st.sidebar.checkbox("Only rows with 1 video link", value=False)

# Category (works for either source)
cat_col = None
for c in ["category", "meta.Category", "meta.CategoryNew UsersTime Required10 minutesTutorial Files UsedNone - new project"]:
    if c in df.columns:
        cat_col = c
        break

cat_choice = None
if cat_col:
    cats = sorted([c for c in df[cat_col].dropna().unique().tolist() if str(c).strip()])
    cat_choice = st.sidebar.selectbox("Category", ["(All)"] + cats, index=0)

# Apply filters
view = df.copy()
if q.strip():
    ql = q.lower()
    def has_q_row(r):
        hay = " ".join([
            str(r.get("toc_title","")),
            str(r.get("title","")),
            str(r.get("text","")),
            str(r.get("text_preview","")),
            str(r.get("url","")),
        ]).lower()
        return ql in hay
    view = view[view.apply(has_q_row, axis=1)]

if only_parts:
    view = view[view["is_part"]]
if only_videos:
    view = view[view["is_video"]]
if only_has_video_link:
    view = view[view["n_video_links"] >= 1]
if cat_col and cat_choice and cat_choice != "(All)":
    view = view[view[cat_col].astype(str) == str(cat_choice)]

# Show results
st.subheader("Results")
show_cols = [c for c in ["toc_title","title","url",cat_col,"n_video_links"] if c in view.columns]
st.dataframe(view[show_cols].reset_index(drop=True), use_container_width=True, height=420)

# Pick a row to inspect
choices = view["toc_title"].tolist()
sel = st.selectbox("Pick a row to inspect", choices, index=0 if choices else None)
if choices:
    row = view[view["toc_title"] == sel].iloc[0].to_dict()

    left, right = st.columns([1,1])
    with left:
        st.markdown("### Page")
        st.write(f"**TOC title:** {row.get('toc_title','')}")
        st.write(f"**Title:** {row.get('title','')}")
        st.write(f"**URL:** {row.get('url','')}")
        st.write(f"**# video links found on page:** {row.get('n_video_links',0)}")

        # HTTP check
        if st.button("Check page status (HTTP)"):
            st.info(f"Status: {http_status(row.get('url',''))}")

    # Lookup mapped video for this part
    mapped = None
    if re.match(r"^Part\s+\d+\s*:", str(row.get("toc_title","")), flags=re.I):
        m = map_df[map_df["part_title"] == row["toc_title"]]
        if len(m):
            mapped = m.iloc[0].to_dict()

    with right:
        st.markdown("### Mapped Video (stable)")
        if mapped:
            st.write(f"**Video title:** {mapped.get('video_title','')}")
            st.write(f"**Video URL:** {mapped.get('video_url','')}")
            st.caption(f"GUID: {mapped.get('guid','')}")
            # HTTP check
            if st.button("Check video status (HTTP)"):
                st.info(f"Status: {http_status(mapped.get('video_url',''))}")
        else:
            st.info("No mapped video (this row is not a 'Part ' page or no GUID could be resolved).")

    # -------- Open both buttons --------
    st.markdown("### Quick open")
    cA, cB = st.columns(2)
    with cA:
        if row.get("url"):
            st.markdown(f"[ Open Part Page]({row['url']})", unsafe_allow_html=True)
    with cB:
        if mapped and mapped.get("video_url"):
            st.markdown(f"[ Open Video Page]({mapped['video_url']})", unsafe_allow_html=True)

