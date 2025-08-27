import sys, re
import weaviate

CLASS = "TutorialChunk"

def client():
    return weaviate.Client("http://127.0.0.1:8080", timeout_config=(10,120))

def retrieve(query, k=8, alpha=0.5):
    fields = [
        "page_title","toc_title","page_url","chunk_text","chunk_index",
        "_additional { score distance }"
    ]
    res = client().query.get(CLASS, fields)\
        .with_limit(k)\
        .with_hybrid(query=query, alpha=alpha)\
        .do()
    return res.get("data",{}).get("Get",{}).get(CLASS, [])

def extractive_answer(q, chunks):
    # simple extractive summary from top chunks
    terms = [t for t in re.findall(r"[a-zA-Z]{3,}", q.lower())]
    picked = []
    for c in chunks:
        text = (c.get("chunk_text") or "")
        sents = re.split(r"(?<=[.!?])\s+", text)
        scored = []
        for s in sents:
            low = s.lower()
            hits = sum(1 for t in terms if t in low)
            if hits:
                scored.append((hits, len(s), s))
        scored.sort(key=lambda x: (-x[0], x[1]))
        for _,_,s in scored[:2]:
            if s and s not in picked:
                picked.append(s)
        if len(picked) >= 8:
            break
    return " ".join(picked[:10]) or "No direct answer found in the top passages."

def main():
    if len(sys.argv) < 2:
        print('Usage: python -m src.rag_answer "your question"'); return
    q = sys.argv[1]
    hits = retrieve(q, k=8, alpha=0.5)
    ans = extractive_answer(q, hits)
    print("\nANSWER:\n", ans, "\n")
    print("SOURCES:")
    seen = set()
    for h in hits:
        u = h.get("page_url"); idx = h.get("chunk_index")
        if not u or (u,idx) in seen: continue
        seen.add((u,idx))
        addl = h.get("_additional") or {}
        sc = addl.get("score") or addl.get("distance")
        title = h.get("toc_title") or h.get("page_title") or ""
        print(f"- {title} — {u}  (chunk {idx}, score={sc})")

if __name__ == "__main__":
    main()
