# src/rag_weaviate_query_http.py
import sys
import weaviate

WEAVIATE_URL = "http://localhost:8080"
CLASS_NAME = "Tutorial"

def _to_float(x):
    try:
        return float(x)
    except Exception:
        return None

def search(q: str, k: int = 5, use_hybrid: bool = False):
    client = weaviate.Client(WEAVIATE_URL)
    props = ["title", "url", "breadcrumb", "video_links", "n_video_links", "text"]

    if use_hybrid:
        res = (
            client.query.get(CLASS_NAME, props)
            .with_hybrid(q, alpha=0.5)
            .with_additional(["score", "distance"])
            .with_limit(k)
            .do()
        )
    else:
        res = (
            client.query.get(CLASS_NAME, props)
            .with_near_text({"concepts": [q]})
            .with_additional(["distance"])
            .with_limit(k)
            .do()
        )

    return res["data"]["Get"].get(CLASS_NAME, [])

def main():
    if len(sys.argv) < 2:
        print('Usage: python -m src.rag_weaviate_query_http "your query" [--hybrid]')
        sys.exit(1)

    q = sys.argv[1]
    hybrid = ("--hybrid" in sys.argv)

    hits = search(q, k=5, use_hybrid=hybrid)
    if not hits:
        print("No results.")
        return

    for i, h in enumerate(hits, 1):
        if not isinstance(h, dict):
            continue

        title = h.get("title","")
        url   = h.get("url","")
        add   = h.get("_additional") or {}

        score_f = _to_float(add.get("score"))
        dist_f  = _to_float(add.get("distance"))

        metric = ""
        if hybrid:
            if score_f is not None:
                metric = f"score={score_f:.4f} (higher is better)"
            elif add.get("score") is not None:
                metric = f"score={add['score']} (higher is better)"
        # Also show distance if present (useful when we asked for both)
        if not metric and dist_f is not None:
            metric = f"distance={dist_f:.4f} (lower is better)"

        links = h.get("video_links") or []
        crumbs = " > ".join(h.get("breadcrumb") or [])

        line1 = f"{i}. {title}"
        if metric:
            line1 += f"  ({metric})"
        print(line1)
        print(f"   {url}")
        print(f"   links: {len(links)} -> {links[:4]}{' ...' if len(links)>4 else ''}")
        if crumbs:
            print(f"   breadcrumb: {crumbs}")
        print()

if __name__ == "__main__":
    main()
