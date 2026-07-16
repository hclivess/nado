"""
DEEP out-of-domain evaluation (execnode/stark/deep_eval.py) — the primitive the fold-layer io binding rests on.
Prove P(z)=v for a committed column P at an out-of-domain z, in O(polylog): commit q=(P−v)/(x−z), FRI-prove it
low-degree, and check q·(x−z)=P−v at the query points. A low-degree q obeying that relation forces P(z)=v.

Checks: an honest eval verifies and v equals the native poly_eval; a tampered v, a wrong z, and a wrong pinned
P_root are rejected; commit_column reproduces P_root (the tie a caller uses); and — the binding property — two
columns evaluate to the SAME v at a shared z iff they're equal (different data ⇒ different v, whp).

Run: python3 tests/test_deep_eval.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import deep_eval as DE, field as F, backend as B

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

T, N, NQ = 8, 32, 6
VALUES = [(i * 7 + 3) % F.P for i in range(T)]
Z = 999999901
b = B.DEFAULT


def t_eval_verifies_and_correct():
    p = DE.prove_eval(VALUES, Z, N, num_queries=NQ, backend=b)
    ok, why = DE.verify_eval(p, Z, num_queries=NQ, backend=b)
    assert ok, f"honest eval must verify: {why}"
    coeffs = F.interpolate([v % F.P for v in VALUES])
    assert p["v"] == F.poly_eval(coeffs, Z), "proven v must equal the native P(z)"


def t_tampered_v_rejected():
    p = DE.prove_eval(VALUES, Z, N, num_queries=NQ, backend=b)
    bad = dict(p); bad["v"] = (int(p["v"]) + 1) % F.P
    ok, _ = DE.verify_eval(bad, Z, num_queries=NQ, backend=b)
    assert not ok, "a wrong claimed v must be rejected"


def t_wrong_z_rejected():
    p = DE.prove_eval(VALUES, Z, N, num_queries=NQ, backend=b)
    ok, _ = DE.verify_eval(p, Z + 1, num_queries=NQ, backend=b)
    assert not ok, "verifying at a different z must be rejected"


def t_root_tie():
    root = DE.commit_column(VALUES, N, backend=b)
    p = DE.prove_eval(VALUES, Z, N, num_queries=NQ, backend=b)
    assert p["P_root"] == root, "prove_eval's P_root must equal commit_column (the tie)"
    ok, _ = DE.verify_eval(p, Z, num_queries=NQ, backend=b, expect_P_root=root)
    assert ok, "pinning the correct root must verify"
    other = DE.commit_column([(v + 1) % F.P for v in VALUES], N, backend=b)
    ok2, _ = DE.verify_eval(p, Z, num_queries=NQ, backend=b, expect_P_root=other)
    assert not ok2, "pinning a different column's root must be rejected"


def t_binding_property():
    a = DE.prove_eval(VALUES, Z, N, num_queries=NQ, backend=b)
    same = DE.prove_eval(list(VALUES), Z, N, num_queries=NQ, backend=b)
    assert a["v"] == same["v"], "equal columns ⇒ equal P(z)"
    diff = list(VALUES); diff[3] = (diff[3] + 12345) % F.P
    other = DE.prove_eval(diff, Z, N, num_queries=NQ, backend=b)
    assert a["v"] != other["v"], "different columns ⇒ different P(z) (whp) — the binding"


if __name__ == "__main__":
    check("honest eval verifies + v == native P(z)", t_eval_verifies_and_correct)
    check("tampered v rejected", t_tampered_v_rejected)
    check("wrong z rejected", t_wrong_z_rejected)
    check("commit_column reproduces P_root (the tie)", t_root_tie)
    check("binding: equal columns ⇔ equal v at shared z", t_binding_property)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
