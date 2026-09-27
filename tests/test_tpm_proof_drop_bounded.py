"""/tpm_proof_drop cannot be used to fill the node's memory (audit 2026-09-25, HIGH).

The handler stored every drop in _TPM_PROOFS keyed by any address string BEFORE the proof was checked, with a TTL as
its only limit and no rate limit, so a stream of drops under fresh addresses grew the dict without bound. Pins: the
endpoint is throttled per IP before it reads the body; nothing is stored until the mirror into node_attest ACCEPTS
the proof (a refused proof returns before any store); and the store evicts the oldest entry at _TPM_PROOFS_MAX.

The handler is read from nado.py's source: importing nado.py opens the node's database.
Run: python3 tests/test_tpm_proof_drop_bounded.py
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
          if isinstance(n, ast.AsyncFunctionDef) and n.name == "tpm_proof_drop"), "")
check("the handler is found", bool(h))
i_rl, i_body = h.find("_rate_limited(request"), h.find("await request.json()")
check("it is throttled per IP before it reads the body", 0 < i_rl < i_body, (i_rl, i_body))

stores = [m.start() for m in re.finditer(r"_TPM_PROOFS\[addr\]\s*=", h)]
keep_def = h.find("def _keep()")
check("the ONLY store is inside _keep()", len(stores) == 1 and keep_def >= 0 and stores[0] > keep_def, stores)
i_refuse = h.find('if not _mirror.get("ok"):')
i_keep_ok = h.find("_keep()", i_refuse)
i_refuse_ret = h.find("return _resp(", i_refuse)
check("a proof the mirror refuses returns BEFORE anything is stored",
      0 < i_refuse < i_refuse_ret < i_keep_ok, (i_refuse, i_refuse_ret, i_keep_ok))
check("_keep evicts the oldest entry once _TPM_PROOFS_MAX are held",
      re.search(r"while len\(_TPM_PROOFS\) >= _TPM_PROOFS_MAX:\s*\n\s*_TPM_PROOFS\.pop\(min\(", h) is not None)
m = re.search(r"^_TPM_PROOFS_MAX = (\d+)", SRC, re.M)
check("the cap is a small fixed number", bool(m) and 0 < int(m.group(1)) <= 10000, m and m.group(1))

# ...and the eviction really keeps the dict at the cap: run the same statements on a small cap
store, cap = {}, 3
for t, a in enumerate("abcdef"):
    while len(store) >= cap:
        store.pop(min(store, key=lambda k: store[k][0]), None)
    store[a] = (t, {})
check("eviction holds the store at its cap and drops the OLDEST", sorted(store) == ["d", "e", "f"], sorted(store))

print("ALL PASS — the proof drop is throttled, validated before it is stored, and bounded" if not fails
      else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
