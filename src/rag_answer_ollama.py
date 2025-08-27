import os, sys, json, requests, textwrap, traceback
import weaviate
from typing import List

WEAVIATE_URL = os.environ.get("WEAVIATE_URL", "http://localhost:8080")
OLLAMA_URL   = os.environ.get("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "deepseek-r1:1.5b")

CLASS_NAME   = "TutorialChunk"
FIELDS_VEC   = ["toc_title","page_title","page_url","chunk_text","chunk_index","breadcrumb","_additional { distance }"]
FIELDS_HYB   = ["toc_title","page_title","page_url","chunk_text","chunk_index","breadcrumb","_additional { score }"]

def search_chunks(client: weaviate.Client, query: str, k: int = 5, hybrid: bool = True):
    fields = FIELDS_HYB if hybrid else FIELDS_VEC
    if hybrid:
        q = (client.query
             .get(CLASS_NAME, fields)
             .with_hybrid(query, alpha=0.5)
             .with_limit(k)
             .do())
    else:
        q = (client.query
             .get(CLASS_NAME, fields)
             .with_near_text({"concepts":[query]})
             .with_limit(k)
             .do())
    return q.get("data", {}).get("Get", {}).get(CLASS_NAME, []), q

def build_prompt(question: str, hits: List[dict], max_chars: int = 6000) -> str:
    blocks = []
    for idx, h in enumerate(hits, 1):
        title = h.get("toc_title") or h.get("page_title") or ""
        url   = h.get("page_url","")
        idx0  = h.get("chunk_index")
        crumb = " > ".join(h.get("breadcrumb") or [])
        text  = (h.get("chunk_text") or "").strip()
        blocks.append(f"[{idx}] {title} — {url} (chunk {idx0})\n{crumb}\n{text}\n")
    ctx = "\n\n".join(blocks)
    if len(ctx) > max_chars:
        ctx = ctx[:max_chars] + "\n...[truncated]"
    return f"""You are a precise assistant. Use ONLY the context to answer the question.
Cite specific steps and keep it concise & actionable. If the answer is not in the context, say you cannot find it.

QUESTION:
{question}

CONTEXT:
{ctx}

ANSWER:"""

def call_ollama(prompt: str, model: str, temperature: float, num_predict: int) -> str:
    url = f"{OLLAMA_URL}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": num_predict}
    }
    r = requests.post(url, json=payload, timeout=120)
    r.raise_for_status()
    return r.json().get("response","").strip()

def main():
    # Always show some output so we know the script actually ran:
    print(f"[info] Weaviate={WEAVIATE_URL} | Ollama={OLLAMA_URL} | model={OLLAMA_MODEL}", flush=True)

    if len(sys.argv) < 2:
        print('Usage: python -m src.rag_answer_ollama "your question" [--k 6] [--vec] [--bm25] [--temp 0.2] [--max 512]')
        sys.exit(1)

    q       = sys.argv[1]
    k       = 5
    hybrid  = True   # default: hybrid (BM25+vector)
    temp    = 0.2
    max_tok = 512
    if "--vec" in sys.argv:   hybrid = False
    if "--bm25" in sys.argv:  hybrid = True
    if "--k" in sys.argv:
        try: k = int(sys.argv[sys.argv.index("--k")+1])
        except: pass
    if "--temp" in sys.argv:
        try: temp = float(sys.argv[sys.argv.index("--temp")+1])
        except: pass
    if "--max" in sys.argv:
        try: max_tok = int(sys.argv[sys.argv.index("--max")+1])
        except: pass

    print(f"[info] query='{q}' | k={k} | mode={'hybrid' if hybrid else 'vector'}", flush=True)

    try:
        client = weaviate.Client(WEAVIATE_URL)
        client.schema.get()  # ping
    except Exception as e:
        print(f"[ERROR] Cannot reach Weaviate: {e}", flush=True)
        sys.exit(2)

    try:
        hits, raw = search_chunks(client, q, k=k, hybrid=hybrid)
    except Exception as e:
        print("[ERROR] GraphQL query failed:", e, flush=True)
        traceback.print_exc()
        sys.exit(3)

    if not hits:
        errors = raw.get("errors") if isinstance(raw, dict) else None
        if errors:
            print("[GraphQL errors]", json.dumps(errors, indent=2))
        print("[warn] No retrieval results.", flush=True)
        sys.exit(0)

    # Show what we’re about to feed the LLM
    for i, h in enumerate(hits, 1):
        title = h.get("toc_title") or h.get("page_title") or ""
        url   = h.get("page_url","")
        add   = h.get("_additional",{})
        metric = add.get("score", None) if hybrid else add.get("distance", None)
        if isinstance(metric, (int, float)):
            m = f"score={metric:.4f}" if hybrid else f"distance={metric:.4f}"
        else:
            m = ""
        print(f"{i}. {title}  ({m})\n   {url}", flush=True)

    prompt = build_prompt(q, hits)
    print("\n[info] Querying Ollama…", flush=True)
    try:
        ans = call_ollama(prompt, OLLAMA_MODEL, temp, max_tok)
    except Exception as e:
        print(f"[ERROR] Ollama call failed: {e}", flush=True)
        traceback.print_exc()
        sys.exit(4)

    print("\nANSWER:\n" + ans, flush=True)

if __name__ == "__main__":
    # make sure Python never buffers our prints on Windows
    os.environ["PYTHONUNBUFFERED"] = "1"
    main()
