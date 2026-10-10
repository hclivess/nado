"""/tpm_proof_drop cannot be used to fill the node's memory (audit 2026-09-25, HIGH), and keeps no store of its own.

The handler once stored every drop in a private _TPM_PROOFS dict keyed by any address string, with a TTL as its only
limit — and nothing read that dict (the wallet polls /node_attest_pickup). The private store and its /tpm_proof_pickup
were deleted on 2026-10-10; a drop now lands only in node_attest's bounded store, which the wallet actually reads.
Pins: the endpoint is throttled per IP before it reads the body; it keeps no module-level store; a proof the mirror
refuses is answered as refused, and a failing mirror is not reported as success.

The handler is read from nado.py's source: importing nado.py opens the node's database.
Run: python3 tests/test_tpm_proof_drop_bounded.py
"""
import ast, os, sys

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
check("it keeps no store of its own (the private _TPM_PROOFS dict and /tpm_proof_pickup are gone)",
      "_TPM_PROOFS" not in SRC and "async def tpm_proof_pickup" not in SRC and '"/tpm_proof_pickup"' not in SRC)
i_refuse = h.find('if not _mirror.get("ok"):')
check("a proof the mirror refuses is answered as refused", i_refuse > 0 and "return _resp({\"ok\": False" in h[i_refuse:])
i_exc = h.find("except Exception as _e:")
check("a failing mirror is not reported as success", i_exc > 0 and "return _resp({\"ok\": False" in h[i_exc:h.find("return _resp({\"ok\": True})", i_exc)])
routes = [n for n in ("/tpm_enrol_challenge", "/tpm_enrol_reveal", "/get_richest") if f'"{n}"' in SRC]
check("the dead relay-held enrolment and richest routes stay deleted", not routes, routes)

print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
