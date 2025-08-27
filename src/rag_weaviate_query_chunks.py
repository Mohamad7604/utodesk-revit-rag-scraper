import sys, json
import weaviate

CLASS_NAME = "TutorialChunk"

def client():
    return weaviate.Client("http://127.0.0.1:8080", timeout_config=(10,120))

def search(query: str, k=5, hybrid=False):
    cli = client()
    fields = [
        "page_title", "toc_title", "page_url", "breadcrumb",
        "chunk_text", "chunk_index", "video_links",
        "_additional { distance score }",
    ]
    base = cli.query.get(CLASS_NAME, fields).with_limit(k)
    res = base.with_hybrid(query=query, alpha=0.5).do() if hybrid \
          else base.with_near_text({"concepts":[query]}).do()
    if "errors" in res: print(json.dumps(res["errors"], indent=2)); return []
    return res.get("data",{}).get("Get",{}).get(CLASS_NAME, [])

def main():
    if len(sys.argv) < 2:
        print('Usage: python -m src.rag_weaviate_query_chunks "your query" [--hybrid]'); sys.exit(1)
    q = sys.argv[1]; hybrid = ("--hybrid" in sys.argv)
    hits = search(q, k=5, hybrid=hybrid)
    for i, h in enumerate(hits, 1):
        title = h.get("toc_title") or h.get("page_title") or "(untitled)"
        url   = h.get("page_url") or ""
        idx   = h.get("chunk_index")
        prev  = (h.get("chunk_text") or "").replace("\n"," ")[:240]
        addl  = h.get("_additional") or {}
        # try to coerce to float (hybrid score often a string)
        metric = ""
        score_raw = addl.get("score")
        dist_raw  = addl.get("distance")
        for label, val, better in [("score", score_raw, "higher"), ("distance", dist_raw, "lower")]:
            if val is not None:
                try:
                    valf = float(val)
                    metric = f"{label}={valf:.4f} ({better} is better)"
                    break
                except Exception:
                    metric = f"{label}={val}"; break
        tag = f" [chunk #{idx}]" if isinstance(idx,int) else ""
        print(f"{i}. {title}{tag}  ({metric})")
        if url: print(f"   {url}")
        if prev: print(f"   preview: {prev}")
        print()

if __name__ == "__main__":
    main()
