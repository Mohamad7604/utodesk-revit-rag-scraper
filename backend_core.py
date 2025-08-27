import os, re, requests
import weaviate

WEAVIATE_URL = os.getenv("WEAVIATE_URL", "http://localhost:8080")
OLLAMA_URL   = os.getenv("OLLAMA_URL",   "http://localhost:11434")
MODEL        = os.getenv("OLLAMA_MODEL", "deepseek-r1:1.5b")
CLASS_NAME   = os.getenv("WEAVIATE_CLASS", "TutorialChunk")

OOD_MIN_SCORE = float(os.getenv("OOD_MIN_SCORE", "0.35"))
OOD_MIN_SIM   = float(os.getenv("OOD_MIN_SIM",   "0.35"))

FIELDS = ["page_title","toc_title","chunk_text","page_url","breadcrumb","chunk_index",
          "video_links","category","time_required","tutorial_files_used"]

def _strip(text: str) -> str:
    s = text or ""
    s = re.sub(r"(?is)<think>.*?(?:</think>|$)", "", s)
    s = re.sub(r"(?ims)\n+Sources?:[\s\S]*\Z", "", s)
    return s.strip()

def _w() -> weaviate.Client: return weaviate.Client(WEAVIATE_URL)

def health_check() -> dict:
    ok_w=ok_o=False
    try: _w().schema.get(); ok_w=True
    except: pass
    try:
        r=requests.get(f"{OLLAMA_URL.rstrip('/')}/api/tags",timeout=5)
        r.raise_for_status(); ok_o=True
    except: pass
    return {"weaviate":ok_w,"ollama":ok_o}

def _query(q: str, k=8, mode="hybrid", alpha=0.5):
    add=["distance","score"]
    qget=_w().query.get(CLASS_NAME, FIELDS).with_additional(add).with_limit(k)
    if mode=="vector":
        qget=qget.with_near_text({"concepts":[q]})
    elif mode=="bm25":
        qget=qget.with_bm25(query=q, properties=["chunk_text","page_title","toc_title"])
    else:
        qget=qget.with_hybrid(query=q, alpha=alpha, properties=["chunk_text","page_title","toc_title"])
    res=qget.do() or {}
    return (res.get("data",{}).get("Get",{}) or {}).get(CLASS_NAME, []) or []

def _conf(h: dict) -> float:
    add=h.get("_additional",{}) or {}
    sc=add.get("score")
    if sc is not None:
        try: return float(sc)
        except: pass
    dist=add.get("distance")
    if dist is not None:
        try: return max(0.0, min(1.0, 1.0-float(dist)))
        except: pass
    return 0.0

def _ok(hits, mode):
    if not hits: return False
    best=max(_conf(h) for h in hits)
    return best >= (OOD_MIN_SCORE if mode in ("hybrid","bm25") else OOD_MIN_SIM)

def _ctx(hits):
    blocks=[]; src_md=[]
    for i,h in enumerate(hits,1):
        title=h.get("page_title") or h.get("toc_title") or "(untitled)"
        url=h.get("page_url") or ""
        idx=h.get("chunk_index")
        crumbs=" > ".join(h.get("breadcrumb") or [])
        text=(h.get("chunk_text") or "").strip()
        blocks.append(f"[{i}] Title: {title}\nURL: {url}\nChunk #{idx}\nBreadcrumb: {crumbs}\n----\n{text}")
        show_idx=f"(chunk {idx})" if isinstance(idx,int) else ""
        src_md.append(f"- [{i}] {title} {show_idx}\n  {url}")
    return "\n\n".join(blocks), ("\n".join(src_md) if src_md else "_No sources_")

def _prompt(q, ctx):
    rules=("You are a helpful Autodesk Revit assistant.\n"
           "Use ONLY the information in SOURCES.\n"
           "If SOURCES do not clearly contain the answer, reply exactly: I don't know.\n"
           "Include bracket citations like [1], [2] tied to SOURCES numbers.\n"
           "Short, step-by-step when useful. No inner monologue. Do NOT print a 'Sources:' section.")
    return f"{rules}\n\nSOURCES:\n{ctx}\n\nUSER QUESTION:\n{q}\n\nYOUR ANSWER (with citations only like [1], [2]):\n"

def _gen(prompt: str, max_tokens=1200) -> str:
    payload={"model":MODEL,"prompt":prompt,"stream":False,
             "options":{"temperature":0.1,"num_predict":int(max_tokens)}}
    r=requests.post(f"{OLLAMA_URL.rstrip('/')}/api/generate", json=payload, timeout=180)
    r.raise_for_status()
    return r.json().get("response","")

def rag_answer(question: str, mode="hybrid", alpha=0.4, k=10, require_citation=True):
    hits = _query(question, k=k, mode=mode, alpha=alpha)
    diag = {
        "hits": len(hits),
        "best_conf": (max([_conf(h) for h in hits]) if hits else 0.0),
        "mode": mode,
        "alpha": alpha,
        "k": k,
    }
    if not _ok(hits, mode):
        return "I don't know.", "", diag

    ctx, src = _ctx(hits)

    try:
        answer = _strip(_gen(_prompt(question, ctx), 1200))
        if not answer.strip():
            brief = _prompt(question, ctx) + "\nReply directly with the final answer only (no <think>, no Sources:). Keep it under 120 words and include [1] style citations."
            answer = _strip(_gen(brief, 400))
    except Exception as e:
        return f"Generation error: {e}", "", diag

    if require_citation and not re.search(r"\[\d+\]", answer):
        if src:
            answer = (answer.rstrip() + " [1]").strip()
        else:
            return "I don't know.", "", diag

    # soft guardrail: reject obvious non-Revit mentions
    if re.search(r"\bautocad\b", answer, re.I):
        return "I don't know.", "", diag

    return answer, src, diag

