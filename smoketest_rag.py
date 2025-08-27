# smoketest_rag.py
import argparse, re, time
from backend_core import health_check, rag_answer

QUESTIONS = [
    "Create a curtain wall with grids at 1200 mm, add a curtain wall door, and apply mullions automatically.",
    "Create terrain using a Toposolid, add a building pad at -150 mm, and finish the sketch.",
    "Create a sheet and place both a floor plan and a 3D view on it.",
    "Set up project levels and grids, rename the levels, and make exterior walls attach to the top level.",
    "Create a room schedule listing Name, Number, and Area, sorted by Level."
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="hybrid", choices=["hybrid","bm25","vector"])
    ap.add_argument("--alpha", type=float, default=0.5)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--no-require-citation", action="store_true")
    args = ap.parse_args()

    hc = health_check()
    print(f"Health: Weaviate={hc['weaviate']}  Ollama={hc['ollama']}")
    if not hc['weaviate']:
        print("! Weaviate not reachable. Start it first.")
        return
    if not hc['ollama']:
        print("! Ollama not reachable. Start it first.")
        return

    total = len(QUESTIONS); passed = 0
    for i,q in enumerate(QUESTIONS,1):
        t0 = time.time()
        ans, srcs, diag = rag_answer(
            q, mode=args.mode, alpha=args.alpha, k=args.k,
            require_citation=not args.no_require_citation
        )
        dt = time.time() - t0
        ok = bool(ans and ans.strip() and ans.strip() != "I don't know.")
        if not args.no_require_citation:
            ok = ok and bool(re.search(r"\[\d+\]", ans))
        status = "PASS" if ok else "FAIL"
        if ok: passed += 1

        print("\n" + "="*80)
        print(f"Q{i}: {q}")
        print(f"Mode={diag['mode']} alpha={diag['alpha']} k={diag['k']} hits={diag['hits']} best_conf={diag['best_conf']:.3f}  ({dt:.2f}s)")
        print(f"[{status}] Answer:\n{ans}\n")
        if srcs:
            print("Sources:\n" + srcs)
    print("\n" + "-"*80)
    print(f"Summary: {passed}/{total} passed")

if __name__ == "__main__":
    main()
