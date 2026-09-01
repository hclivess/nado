"""RELAY PATCHES 0001/0002 (2026-09-01).

0002 — the loopback shortcut behind a reverse proxy: /terminate, /log, /force_sync, /health and the submit
rate-limit exemption authorized on client_ip == 127.0.0.1. A proxy's socket peer IS loopback, so an operator
who published a node through nginx without `trusted_proxies` exposed all of them. `nado._is_local_request`
now requires loopback AND no forwarding header. 0001 — /da read handlers answered 500 (+ a journal traceback)
on a malformed commitment; they answer 400 at the edge now (`execnode._bad_commitment`), the DaStore backstop
raise untouched, h_da_announce's inline expression untouched (tests/test_da_announce.py pins its text)."""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def t1_is_local_request():
    src = open(os.path.join(ROOT, "nado.py")).read()
    ns = {}
    seg = src[src.index("def _is_local_request"):src.index("def _is_local(request)")]
    exec(seg, ns)
    f = ns["_is_local_request"]
    check("plain local call (no headers) is local", f("127.0.0.1", {}) and f("::1", {}))
    check("proxied loopback with X-Forwarded-For is NOT local", not f("127.0.0.1", {"X-Forwarded-For": "1.2.3.4"}))
    check("proxied loopback with X-Real-IP is NOT local", not f("127.0.0.1", {"X-Real-IP": "1.2.3.4"}))
    check("proxied loopback with RFC 7239 Forwarded is NOT local", not f("127.0.0.1", {"Forwarded": "for=1.2.3.4"}))
    check("a resolved remote IP is never local", not f("1.2.3.4", {}) and not f("1.2.3.4", {"X-Forwarded-For": "127.0.0.1"}))
    check("even an XFF claiming loopback does not make a remote local", not f("5.6.7.8", {"X-Forwarded-For": "127.0.0.1"}))


def t2_handlers_use_it():
    src = open(os.path.join(ROOT, "nado.py")).read()
    for fn in ("async def health", "async def log", "async def force_sync", "async def terminate", "async def submit_transaction"):
        i = src.index(fn); body = src[i:i + 2500]
        check(f"{fn.split()[-1]} authorizes via _is_local", "_is_local(request)" in body)
        check(f"{fn.split()[-1]} has no raw loopback compare left", 'client_ip == "127.0.0.1"' not in body.split("def _work")[0] or fn.endswith("force_sync"))


def t3_da_reads_400():
    src = open(os.path.join(ROOT, "execnode", "execnode.py")).read()
    for fn in ("h_da_meta", "h_da_have", "h_da_shard", "h_da_get"):
        i = src.index(f"async def {fn}(request):"); body = src[i:i + 3000]
        code = "\n".join(l for l in body.splitlines() if not l.strip().startswith("#"))   # ignore comment mentions
        store = code.index("DA.get" if fn == "h_da_get" else "DA.")
        check(f"{fn}: 400 on a bad commitment before touching the store",
              "_bad_commitment(" in code and code.index("_bad_commitment(") < store)
    i = src.index("def _bad_commitment"); seg = src[i:i + 900]
    check("shape check matches announce's inline expression",
          'len(c) > 128' in seg and '"/" in c' in seg and '"\\\\" in c' in seg and 'c in (".", "..")' in seg)
    ns = {}; exec(src[i:src.index("async def h_da_meta")], ns); f = ns["_bad_commitment"]
    check("rejects empty / traversal / long, accepts a hex commitment",
          f("") and f("../../etc") and f("a" * 129) and f(".") and f("..") and f("x\\y") and not f("00ff") and not f("ab" * 32))
    ann = src[src.index("async def h_da_announce"):src.index("async def h_da_announce") + 2500]
    check("announce keeps its inline expression (test_da_announce pins it)", 'not c or len(c) > 128 or "/" in c' in ann)


if __name__ == "__main__":
    for name in ("t1_is_local_request", "t2_handlers_use_it", "t3_da_reads_400"):
        try:
            globals()[name]()
        except Exception:
            import traceback; traceback.print_exc(); _fails.append(name)
    print("ALL PASS" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    raise SystemExit(1 if _fails else 0)
