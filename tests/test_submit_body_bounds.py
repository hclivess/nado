"""/submit_transaction cannot be made to hold unbounded large bodies (audit 2026-09-25, HIGH/MED).

A chunked upload carries no Content-Length, and the handler read `content_length or 0` — so it was judged SMALL: it
skipped the strict 6/min large-body bucket, and from a linked peer skipped every bucket, while still delivering up to
the 192 MiB body cap. Pins: an unknown length is judged LARGE; large bodies are capped node-wide at _LARGE_SUBMIT_MAX
in flight (the per-IP bucket bounds one source, not many); the cap is released in a `finally`; and the body is read
only after both decisions. The source is read, not imported: importing nado.py opens the node's database.

Run: python3 tests/test_submit_body_bounds.py
"""
import ast, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "nado.py")).read()
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


tree = ast.parse(SRC)
h = next((ast.get_source_segment(SRC, n) for n in tree.body
          if isinstance(n, ast.AsyncFunctionDef) and n.name == "submit_transaction"), "")
code = "\n".join(l for l in h.splitlines() if not l.strip().startswith("#"))
check("the handler is found", bool(h))
check("a body with NO Content-Length is judged large",
      re.search(r"_large = request\.content_length is None or request\.content_length > ", code) is not None)
check("no path still reads `content_length or 0` (the bypass)", "content_length or 0" not in code)
i_cap, i_read = code.find("_large_inflight >= _LARGE_SUBMIT_MAX"), code.find("await request.read()")
check("the node-wide in-flight cap is checked before a large body is read", 0 < i_cap < i_read, (i_cap, i_read))
check("...and released in a finally, so an error cannot leak a slot",
      re.search(r"_large_inflight \+= 1\s*\n\s*try:[\s\S]*?finally:\s*\n\s*_large_inflight -= 1", code) is not None)
m = re.search(r"^_LARGE_SUBMIT_MAX = (\d+)", SRC, re.M)
check("the cap is a small fixed number", bool(m) and 1 <= int(m.group(1)) <= 8, m and m.group(1))
i_rl = code.find("_rate_limited(request, 6)")
check("the strict per-IP bucket applies to every large body before it is read", 0 < i_rl < i_read, (i_rl, i_read))

print("ALL PASS — large and unknown-length submits are bounded per IP and node-wide" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
