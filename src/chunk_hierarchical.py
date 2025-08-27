import os, re, glob, json, pathlib, requests
from typing import List, Dict, Tuple, Optional
try:
    import weaviate
except Exception as e:
    raise SystemExit(f"Weaviate client not installed: {e}")

WEAVIATE_URL = os.getenv("WEAVIATE_URL", "http://localhost:8080")
CLASS_NAME   = os.getenv("WEAVIATE_CLASS", "TutorialChunk")

def _html_unescape(s: str) -> str:
    try:
        import html as _html
        return _html.unescape(s)
    except:
        return s

def _strip_tags(html: str) -> str:
    html = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    html = re.sub(r"(?is)<style.*?>.*?</style>",  " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = _html_unescape(text)
    text = re.sub(r"[ \t\u00A0]+", " ", text)
    return re.sub(r"\s+\n", "\n", text).strip()

def _to_markdown_headings(html: str) -> str:
    def repl(m):
        level = int(m.group(1))
        title = _strip_tags(m.group(2)).strip()
        return "\n" + ("#"*level) + " " + title + "\n"
    return re.sub(r"(?is)<h([1-6])[^>]*>(.*?)</h\1>", repl, html)

def _sentence_split(s: str):
    parts = re.split(r"(?<=[\.\!\?])\s+(?=[A-Z0-9\(])", s.strip())
    return [p.strip() for p in parts if p.strip()]

def _extract_urls(s: str):
    return re.findall(r"https?://[^\s\)\]]+", s)

def _video_links_from_text(s: str):
    vids=[]
    for u in _extract_urls(s):
        if re.search(r"(youtube\.com|youtu\.be|vimeo\.com|autodesk\.com)", u, re.I):
            vids.append(u)
    out=[]; seen=set()
    for v in vids:
        if v not in seen:
            out.append(v); seen.add(v)
    return out

class Node:
    def __init__(self, level:int, title:str):
        self.level = level
        self.title = title
        self.text_parts = []
        self.children = []

def _parse_markdown(md: str, fallback_title: str):
    lines = md.splitlines()
    top_title = None
    roots = []
    stack = []
    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if m:
            level = len(m.group(1)); title = m.group(2).strip()
            if level == 1 and not top_title: top_title = title
            while stack and stack[-1].level >= level: stack.pop()
            node = Node(level, title)
            (stack[-1].children if stack else roots).append(node)
            stack.append(node)
        else:
            if not stack:
                if not top_title: top_title = fallback_title
                node = Node(1, top_title); roots.append(node); stack.append(node)
            stack[-1].text_parts.append(line)
    if not top_title: top_title = fallback_title
    return top_title, roots

def _json_obj_to_md(obj: dict):
    title = obj.get("title") or obj.get("page_title") or obj.get("toc_title") or ""
    url   = obj.get("url")   or obj.get("page_url")   or ""
    heading = obj.get("heading") or obj.get("toc_title") or obj.get("section") or ""
    body = obj.get("content") or obj.get("text") or obj.get("chunk_text") or obj.get("body") or ""
    md = ""
    if heading: md += f"## {heading}\n"
    if body:    md += str(body).strip() + "\n"
    return (title, url, md)

def _parse_file(path: str):
    p = pathlib.Path(path)
    raw = p.read_text(encoding="utf-8", errors="ignore")
    suf = p.suffix.lower()
    if suf in (".md", ".markdown"):
        return (_html_unescape(p.stem), "", raw)
    if suf in (".htm", ".html"):
        md = _to_markdown_headings(raw) + "\n" + _strip_tags(raw)
        return (_html_unescape(p.stem), "", md)
    if suf in (".txt",):
        return (_html_unescape(p.stem), "", raw)
    if suf in (".json",):
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                title = obj.get("title") or p.stem
                url   = obj.get("url")   or obj.get("page_url") or ""
                body  = obj.get("content") or obj.get("text") or obj.get("chunk_text") or ""
                if re.search(r"<h\d", body or "", re.I):
                    md = _to_markdown_headings(body) + "\n" + _strip_tags(body)
                else:
                    md = f"# {title}\n" + (body or "")
                return (title, url, md)
            if isinstance(obj, list):
                t0, u0, buf = (p.stem, "", f"# {p.stem}\n")
                for o in obj:
                    t,u,md = _json_obj_to_md(o or {})
                    if not u0: u0 = u
                    if t and t != p.stem: buf = f"# {t}\n" + buf
                    buf += md
                return (t0, u0, buf)
        except: pass
    if suf in (".jsonl", ".ndjson"):
        title = p.stem; url=""; buf=f"# {title}\n"
        for line in raw.splitlines():
            line=line.strip()
            if not line: continue
            try:
                o=json.loads(line); t,u,md=_json_obj_to_md(o or {})
                if not url: url=u
                if t and t != title and not buf.startswith(f"# {t}\n"):
                    buf=f"# {t}\n"+buf
                buf+=md
            except:
                buf+=line+"\n"
        return (title, url, buf)
    return (_html_unescape(p.stem), "", raw)

def _walk_chunks(page_title, page_url, roots, max_chars=1400):
    chunks=[]; idx=0
    def dfs(node, trail):
        nonlocal idx
        breadcrumb = trail + [node.title]
        text = "\n".join(node.text_parts).strip()
        segments=[]
        if text:
            if len(text) <= max_chars:
                segments=[text]
            else:
                sent=_sentence_split(text); cur=""
                for s in sent:
                    if len(cur)+1+len(s) <= max_chars:
                        cur=(cur+" "+s).strip()
                    else:
                        if cur: segments.append(cur); cur=s
                if cur: segments.append(cur)
        for seg in segments:
            idx+=1
            chunks.append({
                "page_title": page_title,
                "toc_title": node.title,
                "chunk_text": seg,
                "page_url": page_url or "",
                "breadcrumb": breadcrumb,
                "chunk_index": idx,
                "video_links": _video_links_from_text(seg),
                "category": "",
                "time_required": "",
                "tutorial_files_used": []
            })
        for child in node.children:
            dfs(child, breadcrumb)
    for r in roots:
        dfs(r, [page_title])
    return chunks

def _ensure_schema(wipe=False):
    sess = requests.Session()
    base = WEAVIATE_URL.rstrip("/")

    # Optionally drop class first
    try:
        sch = sess.get(f"{base}/v1/schema", timeout=10).json()
    except Exception as e:
        raise RuntimeError(f"Failed to fetch schema: {e}")

    if wipe:
        try:
            sess.delete(f"{base}/v1/schema/{CLASS_NAME}", timeout=15)
        except Exception:
            pass  # ok if it didn't exist

    else:
        # If already exists, we're done
        if isinstance(sch, dict) and "classes" in sch:
            for c in (sch.get("classes") or []):
                if c.get("class") == CLASS_NAME:
                    return

    cls = {
        "class": CLASS_NAME,
        "description": "Autodesk Revit tutorial chunks (hierarchical)",
        "vectorizer": "text2vec-transformers",
        "moduleConfig": {"text2vec-transformers": {"vectorizeClassName": False}},
        "properties": [
            {"name": "page_title",          "dataType": ["text"]},
            {"name": "toc_title",           "dataType": ["text"]},
            {"name": "chunk_text",          "dataType": ["text"]},
            {"name": "page_url",            "dataType": ["text"]},
            {"name": "breadcrumb",          "dataType": ["text[]"]},
            {"name": "chunk_index",         "dataType": ["int"]},
            {"name": "video_links",         "dataType": ["text[]"]},
            {"name": "category",            "dataType": ["text"]},
            {"name": "time_required",       "dataType": ["text"]},
            {"name": "tutorial_files_used", "dataType": ["text[]"]},
        ],
    }
    full = {"classes": [cls]}

    # Try POST /v1/schema (full schema)
    try:
        r = sess.post(f"{base}/v1/schema", json=full, timeout=20)
        if r.status_code in (200, 201): return
        if r.status_code == 422 and "already exists" in (r.text or "").lower(): return
        if r.status_code != 405: r.raise_for_status()
    except Exception:
        pass

    # Try POST /v1/schema/classes (newer API)
    try:
        r = sess.post(f"{base}/v1/schema/classes", json=cls, timeout=20)
        if r.status_code in (200, 201): return
        if r.status_code == 422 and "already exists" in (r.text or "").lower(): return
        if r.status_code != 405: r.raise_for_status()
    except Exception:
        pass

    # Try PUT /v1/schema (older API)
    r = sess.put(f"{base}/v1/schema", json=full, timeout=20)
    if r.status_code in (200, 201): 
        return
    raise RuntimeError(f"Schema create failed: {r.status_code} {r.text}")
def _ingest(chunks, batch_size=200):
    client = weaviate.Client(WEAVIATE_URL)
    client.batch.configure(batch_size=batch_size, dynamic=True)
    with client.batch as b:
        for ch in chunks:
            b.add_data_object(ch, CLASS_NAME)

def main():
    import argparse, pathlib
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="data")
    ap.add_argument("--patterns",
        default="**/*.md,**/*.markdown,**/*.html,**/*.htm,**/*.json,**/*.jsonl,**/*.ndjson,**/*.txt")
    ap.add_argument("--max-chars", type=int, default=1400)
    ap.add_argument("--batch", type=int, default=200)
    ap.add_argument("--wipe", action="store_true")
    args = ap.parse_args()

    _ensure_schema(wipe=args.wipe)

    paths = []
    import glob
    for pat in [p.strip() for p in args.patterns.split(",") if p.strip()]:
        paths.extend(glob.glob(str(pathlib.Path(args.src) / pat), recursive=True))
    paths = sorted(set(paths))

    all_chunks=[]
    for fp in paths:
        title, url, md = _parse_file(fp)
        page_title, nodes = _parse_markdown(md, fallback_title=title or pathlib.Path(fp).stem)
        chunks = _walk_chunks(page_title, url, nodes, max_chars=args.max_chars)
        all_chunks.extend(chunks)

    if not all_chunks:
        print("No chunks produced.")
        return

    _ingest(all_chunks, batch_size=args.batch)
    print(f"Ingested {len(all_chunks)} chunks into class {CLASS_NAME} at {WEAVIATE_URL}")

if __name__ == "__main__":
    main()




