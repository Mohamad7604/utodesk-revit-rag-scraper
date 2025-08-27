# ui_gradio.py
# RevitGPT — a lightweight Gradio UI for querying your Weaviate-backed Revit RAG
from html import escape
import markdown as md

import os
import re
import requests
from typing import List, Literal, Tuple

import gradio as gr
import weaviate
from dotenv import load_dotenv

load_dotenv()

# ---------------------- CONFIG ----------------------
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "http://localhost:8080")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "deepseek-r1:1.5b")
UI_PORT = int(os.getenv("UI_PORT", "7860"))

CLASS_NAME = "TutorialChunk"
FIELDS = [
    "page_title",
    "toc_title",
    "chunk_text",
    "page_url",
    "breadcrumb",
    "chunk_index",
    "video_links",
    "category",
    "time_required",
    "tutorial_files_used",
]

# -------- Guardrail thresholds (tweak via .env if you want) ----------
# Lowered defaults to reduce unnecessary "I don't know" for small corpora
OOD_MIN_SCORE = float(os.getenv("OOD_MIN_SCORE", "0.35"))   # for ._additional.score (hybrid/BM25), 0..1
OOD_MIN_SIM   = float(os.getenv("OOD_MIN_SIM", "0.35"))     # for 1 - distance (vector), 0..1
DEBUG_RETRIEVAL = os.getenv("DEBUG_RETRIEVAL", "0") == "1"  # show retrieval metrics in Sources

REVIT_KEYWORDS = {
    "revit","wall","curtain","sheet","view","family","dimension","floor","plan",
    "elevation","schedule","parameter","model","project","tag","room","door",
    "window","stairs","railing","section","detail","levels","grid"
}

# ---------------------- HELPERS ----------------------
def md_to_html(text: str) -> str:
    """Render markdown to HTML (bullets, headings, tables, code)."""
    return md.markdown(
        text or "",
        extensions=["fenced_code", "tables", "sane_lists"]  # keep built-ins for reliability
    )

def strip_think(text: str) -> str:
    """Remove <think> blocks and any 'inner monologue' preface."""
    cleaned = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL | re.IGNORECASE)
    # If the model still prefaced with planning text, keep from first heading/list/numbered item.
    m = re.search(r"(?:^|\n)(###\s.+|[-*]\s+.+|\d+\.\s+.+)", cleaned)
    if m:
        cleaned = cleaned[m.start():]
    return cleaned.strip()

def force_minimal_markdown(ans: str) -> str:
    """
    Ensure concise Markdown and at least one citation [n].
    If no citation is present, treat as unsafe and return 'I don't know.'
    """
    a = (ans or "").strip()
    if not re.search(r"\[\d+\]", a):
        return "I don't know."
    a = re.sub(r"\n{3,}", "\n\n", a)  # collapse excess blank lines
    return a


def wclient() -> weaviate.Client:
    """Return a Weaviate client (v3-style)."""
    return weaviate.Client(WEAVIATE_URL)

def query_weaviate(q: str, k: int, mode: Literal["hybrid", "vector", "bm25"], alpha: float = 0.5):
    """Run a hybrid/vector/bm25 query against Weaviate and return hits."""
    add = ["distance", "score"]
    qget = wclient().query.get(CLASS_NAME, FIELDS).with_additional(add).with_limit(k)

    if mode == "vector":
        qget = qget.with_near_text({"concepts": [q]})
    elif mode == "bm25":
        qget = qget.with_bm25(query=q, properties=["chunk_text", "page_title", "toc_title"])
    else:
        qget = qget.with_hybrid(query=q, alpha=alpha, properties=["chunk_text", "page_title", "toc_title"])

    res = qget.do() or {}
    return (res.get("data", {}).get("Get", {}) or {}).get(CLASS_NAME, []) or []

def metric_str(hit: dict) -> str:
    """Human-readable retrieval metrics for a single hit."""
    add = (hit or {}).get("_additional", {}) or {}
    sc = add.get("score")
    dist = add.get("distance")
    parts = []
    if sc is not None:
        try:
            parts.append(f"score={float(sc):.3f}")
        except Exception:
            parts.append(f"score={sc}")
    if dist is not None:
        try:
            sim = 1.0 - float(dist)
            parts.append(f"sim={sim:.3f}")
        except Exception:
            parts.append(f"distance={dist}")
    return " | ".join(parts)

def short_title(hit: dict) -> str:
    return hit.get("page_title") or hit.get("toc_title") or "(untitled)"

def build_context(hits: list) -> Tuple[str, str]:
    """Compose a plain-text context block and a Markdown sources list from hits."""
    blocks: List[str] = []
    src_md: List[str] = []
    for i, h in enumerate(hits, 1):
        title = short_title(h)
        url   = h.get("page_url") or ""
        idx   = h.get("chunk_index")
        crumbs = " > ".join(h.get("breadcrumb") or [])
        text  = (h.get("chunk_text") or "").strip()
        blocks.append(f"[{i}] Title: {title}\nURL: {url}\nChunk #{idx}\nBreadcrumb: {crumbs}\n----\n{text}")

        metr = metric_str(h)
        metr = f" — {metr}" if metr else ""
        show_idx = f"(chunk {idx})" if isinstance(idx, int) else ""
        line = f"- **[{i}] {title}** {show_idx}{metr}  \n  {url}"

        vids = h.get("video_links") or []
        if isinstance(vids, list) and vids:
            vlist = ", ".join(f"[video]({v})" for v in vids if isinstance(v, str) and v.startswith("http"))
            if vlist:
                line += f"\n  Videos: {vlist}"

        src_md.append(line)
    return "\n\n".join(blocks), ("\n".join(src_md) if src_md else "_No sources_")


def build_prompt(question: str, context_block: str) -> str:
    """
    Strict RAG format:
    - Use ONLY SOURCES.
    - If SOURCES don't clearly contain the answer, reply exactly: I don't know.
    - Put a citation like [1] [2] at the END OF EVERY SENTENCE.
    - No preface, no chain-of-thought. Return clean Markdown only.
    - Prefer a short bullet list of steps when appropriate.
    """
    rules = (
        "You are a helpful Autodesk Revit assistant.\n"
        "Answer ONLY from SOURCES.\n"
        "If the SOURCES do not clearly contain the answer, reply exactly: I don't know.\n"
        "Put a citation like [1] [2] at the END OF EVERY SENTENCE you write.\n"
        "Do NOT describe your reasoning or process. No prefaces like 'I need to figure out'.\n"
        "Return clean Markdown only. Prefer a short bulleted 'Steps' section when appropriate."
    )
    return f"{rules}\n\nSOURCES:\n{context_block}\n\nUSER QUESTION:\n{question}\n\nYOUR ANSWER:\n"


def call_ollama(model: str, prompt: str, max_tokens: int = 600) -> str:
    """Call Ollama generate endpoint and return text response."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": int(max_tokens)},
    }
    r = requests.post(f"{OLLAMA_URL.rstrip('/')}/api/generate", json=payload, timeout=180)
    r.raise_for_status()
    return r.json().get("response", "")

def health_check() -> str:
    """Check Weaviate and Ollama connectivity."""
    try:
        client = weaviate.Client(WEAVIATE_URL)
        client.schema.get()
        w = "✅ **Weaviate Connected**"
    except Exception as e:
        w = f"❌ **Weaviate Error**: {str(e)[:200]}..."

    try:
        r = requests.get(f"{OLLAMA_URL.rstrip('/')}/api/tags", timeout=5)
        r.raise_for_status()
        o = "✅ **Ollama Connected**"
    except Exception as e:
        o = f"❌ **Ollama Error**: {str(e)[:200]}..."

    return f"{w}\n\n{o}"
def simple_tokens(s: str) -> List[str]:
    return [t for t in re.findall(r"[a-zA-Z]{4,}", (s or "").lower())]

def keyword_overlap(query: str, hit: dict) -> float:
    """Jaccard-ish overlap using query tokens vs. title/toc/breadcrumb/chunk_text (first 300 chars)."""
    qset = set(simple_tokens(query))
    meta = " ".join([
        hit.get("page_title") or "",
        hit.get("toc_title") or "",
        " ".join(hit.get("breadcrumb") or []) or "",
        (hit.get("chunk_text") or "")[:300],
    ])
    hset = set(simple_tokens(meta))
    if not qset or not hset:
        return 0.0
    return len(qset & hset) / max(1, len(qset))

# ---------------------- CHAT HISTORY ----------------------
chat_history: List[dict] = []

def format_chat_history() -> str:
    """Render chat history into HTML for the chat pane."""
    if not chat_history:
        return """
        <div class="welcome-message">
            <div class="logo-container">
                <div class="logo">🏗️</div>
                <h2>RevitGPT</h2>
                <p>Your intelligent Autodesk Revit assistant</p>
            </div>
            <div class="example-questions">
                <p><strong>Try asking:</strong></p>
                <div class="examples">
                    <span>How do I create a curtain wall?</span>
                    <span>What are Revit families?</span>
                    <span>How to set up project parameters?</span>
                </div>
            </div>
        </div>
        """

    html = ""
    for msg in chat_history:
        if msg["role"] == "user":
            html += f"""
            <div class="message user-message">
                <div class="message-content">
                    <div class="user-avatar">👤</div>
                    <div class="message-text">{escape(msg["content"])}</div>
                </div>
            </div>
            """
        else:
            html += f"""
            <div class="message assistant-message">
                <div class="message-content">
                    <div class="assistant-avatar">🏗️</div>
                    <div class="message-text">{md_to_html(msg["content"])}</div>
                </div>
            </div>
            """
    return html

def is_capabilities_question(q: str) -> bool:
    ql = q.lower().strip()
    return any(p in ql for p in [
        "how can you help", "how can u help", "what can you do", "what can u do",
        "help me with revit", "what do you do"
    ])

CAPABILITIES_MD = """### How I can help 🧰

I’m a **Revit RAG assistant** grounded on Autodesk’s official tutorials.

**Things I do well**
- Answer “how to” questions (e.g., *create sheets*, *place a curtain wall*).  
- Give **step-by-step** instructions with **citations** like [1], [2].  
- Compare similar tools/workflows (when covered by the sources).  
- Suggest next steps or checks after a procedure.

**Ask me**
- *“Create a sheet and place two views”*  
- *“Add dimensions between walls”*  
- *“Place a curtain wall door”*

> I only answer from the local knowledge base. If it’s not there, I’ll say **“I don’t know.”**
"""

def detect_smalltalk(q: str):
    """Return (is_smalltalk, name_or_None)."""
    ql = (q or "").strip().lower()
    if not ql:
        return False, None
    # greetings
    if re.fullmatch(r"(hi|hello|hey|yo|sup|good (morning|afternoon|evening))[!. ]*", ql):
        return True, None
    # introductions like: "hi my name is mohamad", "i'm mohamad", "i am mohamad"
    m = re.search(r"(?:my name is|i am|i'm)\s+([a-z][a-z\-' ]{1,30})", ql)
    if m:
        name = m.group(1).strip().split()[0].title()
        return True, name
    # very short non-domain messages -> treat as small talk
    if len(ql.split()) <= 3 and not any(w in ql for w in REVIT_KEYWORDS):
        return True, None
    return False, None

def hit_confidence(hit: dict) -> float:
    """Return a 0..1 confidence. Prefer score; else invert distance; else 0."""
    add = hit.get("_additional", {}) or {}
    sc = add.get("score")
    if sc is not None:
        try:
            return float(sc)
        except Exception:
            pass
    dist = add.get("distance")
    if dist is not None:
        try:
            return max(0.0, min(1.0, 1.0 - float(dist)))
        except Exception:
            pass
    return 0.0

def keyword_overlap_ok(query: str, hit: dict) -> bool:
    """Allow borderline hits when ≥2 query tokens (≥4 chars) appear in the chunk."""
    text = (hit.get("chunk_text") or "").lower()
    toks = [t for t in re.findall(r"[a-zA-Z]{4,}", (query or "").lower())]
    found = sum(1 for t in toks if t in text)
    return found >= 2

def confident_enough(hits: list, mode: str, query: str) -> bool:
    """Gate based on best hit confidence OR sufficient token overlap (top 3)."""
    if not hits:
        return False
    best_conf = max(hit_confidence(h) for h in hits)
    top3 = hits[:3]
    has_overlap = False  # Overlap check disabled
    if mode in ("hybrid", "bm25"):
        return (best_conf >= OOD_MIN_SCORE) or has_overlap
    # vector mode
    return (best_conf >= OOD_MIN_SIM) or has_overlap


def ask(question: str, mode: str, alpha: float, k: int):
    """Main handler: smalltalk -> friendly greeting; else RAG with confidence gating + fallbacks."""
    global chat_history
    q = (question or "").strip()
    if not q:
        return gr.update(), gr.update(value=""), gr.update(value="")
    if is_capabilities_question(q):
        chat_history.append({"role": "user", "content": q})
        chat_history.append({"role": "assistant", "content": CAPABILITIES_MD})
        return gr.update(value=format_chat_history()), gr.update(value=""), gr.update(value="")
    
    # 1) Small-talk / greeting path (no retrieval)
    is_small, name = detect_smalltalk(q)
    if is_small:
        msg = f"Hi {name}, how can I help you with Revit today?" if name else "Hi! How can I help you with Revit today?"
        chat_history.append({"role": "user", "content": q})
        chat_history.append({"role": "assistant", "content": msg})
        return gr.update(value=format_chat_history()), gr.update(value=""), gr.update(value="")

    # 2) Retrieval path
    chat_history.append({"role": "user", "content": q})

    def try_search(m: str, top_k: int):
        try:
            return query_weaviate(q, k=top_k, mode=m, alpha=alpha)
        except Exception:
            return []

    modes_to_try = [mode] + [m for m in ("hybrid", "bm25", "vector") if m != mode]

    hits = []
    used_mode = None
    for m in modes_to_try:
        # First pass with user-selected K
        hits = try_search(m, k)
        if hits and confident_enough(hits, m, q):
            used_mode = m
            break
        # If not confident, try larger K once for this mode
        hits = try_search(m, min(2 * k, 15))
        if hits and confident_enough(hits, m, q):
            used_mode = m
            break

    dbg = f"_debug: mode={used_mode or 'none'} | topK={len(hits)}_" if DEBUG_RETRIEVAL else ""

    if not hits or not used_mode:
        msg = "I don't know."
        chat_history.append({"role": "assistant", "content": msg})
        return gr.update(value=format_chat_history()), gr.update(value=""), gr.update(value="")

    # 3) Build prompt with sources and ask the model
    ctx, src_md = build_context(hits)
    if DEBUG_RETRIEVAL and src_md:
        src_md = dbg + "\n\n" + src_md

    prompt = build_prompt(q, ctx)
    try:
        raw = call_ollama(DEFAULT_MODEL, prompt, 600)
        answer = strip_think(raw).strip()
    except Exception as e:
        answer = f"I encountered an error while generating the response: {str(e)}"
        src_md = ""

    # 4) Post-check: must have a citation like [1]
    if not re.search(r"\[\d+\]", answer):
        answer = "I don't know."
        src_md = ""

    chat_history.append({"role": "assistant", "content": answer})
    return gr.update(value=format_chat_history()), gr.update(value=""), gr.update(value=src_md)

def clear_chat():
    """Clear the chat history and reset panels."""
    global chat_history
    chat_history = []
    return gr.update(value=format_chat_history()), gr.update(value="")

# ---------------------- UI ----------------------
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

* { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }

.gradio-container {
    max-width: 1400px !important;
    margin: 0 auto !important;
}

/* Dark theme colors */
:root {
    --bg-primary: #0f0f23;
    --bg-secondary: #1a1b3e;
    --bg-tertiary: #2a2b5e;
    --text-primary: #ffffff;
    --text-secondary: #a0a0c0;
    --accent: #6366f1;
    --accent-hover: #5855eb;
    --border: #2a2b5e;
    --success: #10b981;
    --error: #ef4444;
}

body, .gradio-container {
    background: linear-gradient(135deg, var(--bg-primary) 0%, var(--bg-secondary) 100%) !important;
    color: var(--text-primary) !important;
}
.assistant-message .message-text ul,
.assistant-message .message-text ol { margin: 0.25rem 0 0.75rem 1.25rem; }
.assistant-message .message-text h3 { margin: 0.5rem 0 0.25rem; }
.assistant-message .message-text code { padding: 0.1rem 0.3rem; background: rgba(255,255,255,0.08); border-radius: 6px; }

/* Main layout */
#main-container {
    background: rgba(26, 27, 62, 0.3) !important;
    backdrop-filter: blur(20px) !important;
    border: 1px solid var(--border) !important;
    border-radius: 24px !important;
    padding: 0 !important;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5) !important;
}

#chat-container {
    background: transparent !important;
    border: none !important;
    min-height: 600px !important;
    max-height: 600px !important;
    overflow-y: auto !important;
    padding: 24px !important;
}

#input-container {
    background: rgba(42, 43, 94, 0.5) !important;
    border-top: 1px solid var(--border) !important;
    padding: 20px 24px !important;
    border-radius: 0 0 24px 24px !important;
}

#settings-panel {
    background: rgba(26, 27, 62, 0.8) !important;
    backdrop-filter: blur(20px) !important;
    border: 1px solid var(--border) !important;
    border-radius: 20px !important;
    padding: 24px !important;
}

/* Welcome message */
.welcome-message {
    text-align: center;
    padding: 60px 20px;
    color: var(--text-secondary);
}

.logo-container .logo {
    font-size: 4rem;
    margin-bottom: 16px;
    filter: drop-shadow(0 0 20px rgba(99, 102, 241, 0.3));
}

.logo-container h2 {
    font-size: 2.5rem;
    font-weight: 700;
    margin: 0 0 8px 0;
    background: linear-gradient(135deg, var(--accent), #8b5cf6);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

.logo-container p {
    font-size: 1.1rem;
    margin-bottom: 40px;
    opacity: 0.8;
}

.example-questions p {
    font-weight: 600;
    margin-bottom: 16px;
    color: var(--text-primary);
}

.examples {
    display: flex;
    flex-direction: column;
    gap: 8px;
    align-items: center;
}

.examples span {
    background: rgba(99, 102, 241, 0.1);
    border: 1px solid rgba(99, 102, 241, 0.3);
    padding: 8px 16px;
    border-radius: 20px;
    font-size: 0.9rem;
    cursor: pointer;
    transition: all 0.2s ease;
}

.examples span:hover {
    background: rgba(99, 102, 241, 0.2);
    border-color: rgba(99, 102, 241, 0.5);
    transform: translateY(-1px);
}

/* Chat messages */
.message {
    margin-bottom: 24px;
    animation: slideIn 0.3s ease-out;
}

@keyframes slideIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}

.message-content {
    display: flex;
    gap: 12px;
    align-items: flex-start;
}

.user-message .message-content { flex-direction: row-reverse; }

.user-avatar, .assistant-avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 16px;
    flex-shrink: 0;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.user-avatar { background: linear-gradient(135deg, #6366f1, #8b5cf6); }
.assistant-avatar { background: linear-gradient(135deg, #f59e0b, #d97706); }

.message-text {
    max-width: 80%;
    padding: 16px 20px;
    border-radius: 20px;
    line-height: 1.6;
    font-size: 0.95rem;
}

.user-message .message-text {
    background: linear-gradient(135deg, var(--accent), #8b5cf6);
    color: white;
    border-bottom-right-radius: 6px;
    box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.assistant-message .message-text {
    background: rgba(42, 43, 94, 0.6);
    border: 1px solid var(--border);
    border-bottom-left-radius: 6px;
    backdrop-filter: blur(10px);
}

/* Input styling */
.input-row { display: flex; gap: 12px; align-items: flex-end; }

#question textarea {
    background: rgba(255, 255, 255, 0.05) !important;
    border: 2px solid var(--border) !important;
    border-radius: 16px !important;
    color: var(--text-primary) !important;
    padding: 16px 20px !important;
    font-size: 0.95rem !important;
    resize: none !important;
    transition: all 0.2s ease !important;
    backdrop-filter: blur(10px) !important;
}

#question textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1) !important;
    outline: none !important;
}

#question textarea::placeholder { color: var(--text-secondary) !important; opacity: 0.8 !important; }

/* Buttons */
.btn-primary {
    background: linear-gradient(135deg, var(--accent), #8b5cf6) !important;
    border: none !important;
    border-radius: 12px !important;
    padding: 12px 24px !important;
    font-weight: 600 !important;
    color: white !important;
    cursor: pointer !important;
    transition: all 0.2s ease !important;
    box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3) !important;
}

.btn-primary:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 16px rgba(99, 102, 241, 0.4) !important;
}

.btn-secondary {
    background: rgba(255, 255, 255, 0.05) !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
    padding: 12px 24px !important;
    font-weight: 500 !important;
    color: var(--text-primary) !important;
    cursor: pointer !important;
    transition: all 0.2s ease !important;
}

.btn-secondary:hover {
    background: rgba(255, 255, 255, 0.1) !important;
    transform: translateY(-1px) !important;
}

/* Settings panel */
.setting-group { margin-bottom: 24px; }
.setting-label { font-weight: 600; margin-bottom: 8px; color: var(--text-primary); font-size: 0.9rem; }

/* Radio buttons */
.radio-group { display: flex; gap: 8px; flex-wrap: wrap; }

.radio-item {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px 16px;
    cursor: pointer;
    transition: all 0.2s ease;
    font-size: 0.85rem;
    font-weight: 500;
}

.radio-item:hover { background: rgba(255, 255, 255, 0.1); }
.radio-item.selected { background: var(--accent); border-color: var(--accent); color: white; }

/* Sliders */
input[type="range"] {
    width: 100% !important;
    height: 6px !important;
    border-radius: 3px !important;
    background: var(--border) !important;
    outline: none !important;
    -webkit-appearance: none !important;
}

input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none !important;
    width: 18px !important;
    height: 18px !important;
    border-radius: 50% !important;
    background: var(--accent) !important;
    cursor: pointer !important;
    box-shadow: 0 2px 6px rgba(99, 102, 241, 0.3) !important;
}

/* Sources panel */
#sources-panel {
    background: rgba(42, 43, 94, 0.3) !important;
    border: 1px solid var(--border) !important;
    border-radius: 16px !important;
    padding: 20px !important;
    margin-top: 20px !important;
    backdrop-filter: blur(10px) !important;
}

/* Scrollbar styling */
::-webkit-scrollbar { width: 8px; }
::-webkit-scrollbar-track { background: rgba(42, 43, 94, 0.3); border-radius: 4px; }
::-webkit-scrollbar-thumb { background: var(--accent); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: var(--accent-hover); }

/* Status indicators */
.status-good { color: var(--success); }
.status-error { color: var(--error); }
"""

theme = gr.themes.Soft(
    primary_hue="indigo",
    secondary_hue="purple",
    neutral_hue="slate",
).set(
    body_background_fill="var(--bg-primary)",
    body_text_color="var(--text-primary)",
    block_background_fill="transparent",
    block_border_color="var(--border)",
    block_title_text_color="var(--text-primary)",
    button_primary_background_fill="var(--accent)",
    button_primary_text_color="white",
    input_background_fill="rgba(255,255,255,0.05)",
    input_border_color="var(--border)",
)

with gr.Blocks(title="RevitGPT - AI Assistant", theme=theme, css=CSS) as demo:
    with gr.Row():
        with gr.Column(scale=8, elem_id="main-container"):
            # Chat interface
            chat_display = gr.HTML(value=format_chat_history(), elem_id="chat-container")

            # Input area
            with gr.Row(elem_id="input-container"):
                with gr.Column(scale=8):
                    question = gr.Textbox(
                        label="",
                        placeholder="Ask me anything about Autodesk Revit...",
                        lines=2,
                        elem_id="question",
                        show_label=False,
                    )
                with gr.Column(scale=1, min_width=100):
                    ask_btn = gr.Button("Send", variant="primary", elem_classes=["btn-primary"])
                with gr.Column(scale=1, min_width=100):
                    clear_btn = gr.Button("Clear", elem_classes=["btn-secondary"])

        with gr.Column(scale=4, elem_id="settings-panel"):
            gr.Markdown("### ⚙️ **Search Settings**")

            with gr.Group():
                mode = gr.Radio(
                    choices=["hybrid", "vector", "bm25"],
                    value="hybrid",
                    label="🔍 **Search Mode**",
                    info="Hybrid combines keyword and semantic search",
                )

                alpha = gr.Slider(
                    0,
                    1,
                    value=0.5,
                    step=0.05,
                    label="🎯 **Hybrid Balance**",
                    info="0 = keyword focus, 1 = semantic focus",
                )

                k = gr.Slider(
                    1,
                    15,
                    value=6,
                    step=1,
                    label="📚 **Results Count**",
                    info="Number of knowledge chunks to retrieve",
                )

            gr.Markdown("---")
            gr.Markdown("### 🏥 **System Status**")

            check_btn = gr.Button("Check Connection", elem_classes=["btn-secondary"])
            status_display = gr.Markdown("Click to check system status")

            # Sources display
            with gr.Accordion("📖 **Sources**", open=False):
                sources_display = gr.Markdown("_No sources yet_", elem_id="sources-panel")

    # Event handlers
    ask_btn.click(fn=ask, inputs=[question, mode, alpha, k], outputs=[chat_display, question, sources_display])
    question.submit(fn=ask, inputs=[question, mode, alpha, k], outputs=[chat_display, question, sources_display])
    clear_btn.click(fn=clear_chat, outputs=[chat_display, sources_display])
    check_btn.click(fn=health_check, outputs=[status_display])

if __name__ == "__main__":
    # Tip: Gradio 4.44.1 is suggested; you can upgrade with:
    # python -m pip install -U gradio==4.44.1
    demo.launch(server_port=UI_PORT, inbrowser=True)
# --- PATCH: overlap & confidence ---
try:
    1.0
except NameError:
    import os

def keyword_overlap(query: str, hit: dict) -> float:
    """Return fraction (0..1) of 4+ letter query tokens that appear in the chunk text."""
    import re
    text = (hit.get("chunk_text") or "").lower()
    toks = [t for t in re.findall(r"[a-zA-Z]{4,}", (query or "").lower())]
    if not toks:
        return 0.0
    found = sum(1 for t in toks if t in text)
    return found / len(toks)

def confident_enough(hits: list, mode: str, q: str) -> bool:
    # Simple score-only gate (no 1.0, no keyword_overlap)
    if not hits:
        return False
    best = max(hit_confidence(h) for h in hits)
    if mode in ("hybrid", "bm25"):
        return best >= OOD_MIN_SCORE
    return best >= OOD_MIN_SIM

# --- RUNTIME OVERRIDES: DISABLE OVERLAP GATE ---
# These override any earlier definitions to remove the MIN_OVERLAP/keyword gate.

MIN_OVERLAP = 1.0  # keep defined so legacy code won't crash; set high so it never passes

def keyword_overlap(query: str, hit: dict) -> float:
    # Neutralized: never contributes to gating
    return 0.0

def confident_enough(hits: list, mode: str, q: str) -> bool:
    # Simple score-only gate (no 1.0, no keyword_overlap)
    if not hits:
        return False
    best = max(hit_confidence(h) for h in hits)
    if mode in ("hybrid", "bm25"):
        return best >= OOD_MIN_SCORE
    return best >= OOD_MIN_SIM
# --- END RUNTIME OVERRIDES ---



