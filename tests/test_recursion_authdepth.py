"""
AUTHORITATIVE recursion depth (execnode/stark/recursion_authdepth.py) — a recursion bundle re-verified INSIDE a
recursion bundle. A RECURSION-committed bundle {fold_0, comp_0} (recursive_verify.prove out_backend=RECURSION)
is re-verified by prove_level; the root {rv_fold, rv_comps} attests "the bundle verifies," checkable in a way
independent of K.

DEFAULT (fast): validate the NEW logic — fri_verify.fold_air / comp_verify.comp_air reconstruct EXACTLY the
schedule verify_fold / verify_comp build (so the reconstructed AIR verifies the gadget proof via stark.verify),
and a tampered bundle-public is rejected. This is the correctness-critical piece; the RV.prove wrapping around
it is recursive_verify, covered by test_recursive_verify.

NADO_HEAVY=1 (~minutes): the full prove_level → verify_level end-to-end (the depth level RE-VERIFIES fold_0 and
comp_0 via recursive_verify — a comp over the W=21 fold AIR, the recursion throughput wall, now memory-feasible
with the holistic prover).

SCOPE (see recursion_authdepth docstring): this makes the fold/comp CRYPTO O(1); the io-replay + per-segment
statement rebuild remain O(K) — true O(1) settlement needs the in-circuit state-root binding + statement
commitment on top. This file tests the building block.

Run: python3 tests/test_recursion_authdepth.py   (NADO_HEAVY=1 python3 … for the full depth level)
"""
import os, sys, copy, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import (field as F, stark, backend as B, recursive_verify as RV, fri_verify,
                            comp_verify, air_ir, recursion_authdepth as AD)

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

P = F.P
SEED = 123456789 % P
TRANS_X2 = [lambda c, n, p: F.sub(n[0], F.mul(c[0], c[0]))]
T, K, NQ, NQO = 8, 2, 2, 2


def _chain():
    proofs, bnds, seed = [], [], SEED
    for _ in range(K):
        col = [seed]
        for i in range(T - 1):
            col.append(F.mul(col[-1], col[-1]))
        pr = stark.prove([[v] for v in col], TRANS_X2, [(0, 0, seed)], max_degree=2, num_queries=NQ,
                         backend=B.RECURSION)
        proofs.append(pr); bnds.append([(0, 0, seed)]); seed = F.mul(col[-1], col[-1])
    return proofs, bnds


_PROOFS, _BNDS = _chain()
# depth-ready: fold_0 + comp_0 are RECURSION-committed, hence themselves recursively verifiable
_BUNDLE = RV.prove(_PROOFS, TRANS_X2, _BNDS, num_queries_outer=NQO, out_backend=B.RECURSION)
_PUBS = [RV.public_part(p) for p in _PROOFS]


def t_recursion_committed_bundle_verifies():
    """The RECURSION-committed bundle still verifies the normal way (out_backend threaded through)."""
    ok, why = RV.verify(_PUBS, TRANS_X2, _BNDS, _BUNDLE, num_queries_outer=NQO, out_backend=B.RECURSION)
    assert ok, f"RECURSION-committed bundle must verify: {why}"


def t_fold_air_reconstructs():
    """fri_verify.fold_air rebuilds fold_0's AIR from its PUBLIC part so stark.verify accepts fold_0 — i.e. the
    reconstruction the depth level feeds recursive_verify is EXACTLY the schedule verify_fold builds."""
    nt = len(TRANS_X2)
    mks = [RV._fs(pub, 0, nt + len(bl), B.RECURSION)[0] for pub, bl in zip(_PUBS, _BNDS)]
    ft, fb, fp = fri_verify.fold_air(_BUNDLE["fold_public"], mks, NQ)
    ok = stark.verify(_BUNDLE["fold"], ft, fb, periodic=fp, max_degree=8, num_queries=NQO, backend=B.RECURSION)[0]
    assert ok, "reconstructed fold_air must verify fold_0"


def t_comp_air_reconstructs():
    """comp_verify.comp_air rebuilds comp_0's AIR from its PUBLIC part so stark.verify accepts comp_0."""
    prog = air_ir.build_program(TRANS_X2, 1, 0, 0)
    ct, cb, cp, cmd = comp_verify.comp_air(prog, 1, _BNDS[0], _BUNDLE["comp_public"])
    ok = stark.verify(_BUNDLE["comp"], ct, cb, periodic=cp, max_degree=cmd, num_queries=NQO, backend=B.RECURSION)[0]
    assert ok, "reconstructed comp_air must verify comp_0"


def t_tampered_public_rejected():
    """A tampered bundle public (swap a segment FRI root) makes the reconstructed schedule reject fold_0 —
    the reconstruction is verifier-authoritative, so a lied statement cannot pass."""
    nt = len(TRANS_X2)
    mks = [RV._fs(pub, 0, nt + len(bl), B.RECURSION)[0] for pub, bl in zip(_PUBS, _BNDS)]
    bad = copy.deepcopy(_BUNDLE["fold_public"])
    bad["publics"][0]["roots"][0] = [(int(x) + 1) % P for x in bad["publics"][0]["roots"][0]]
    try:
        ft, fb, fp = fri_verify.fold_air(bad, mks, NQ)
        ok = stark.verify(_BUNDLE["fold"], ft, fb, periodic=fp, max_degree=8, num_queries=NQO, backend=B.RECURSION)[0]
    except Exception:
        ok = False
    assert not ok, "a tampered bundle public must be rejected"


def t_full_depth_level():
    """OPT-IN (NADO_HEAVY=1): the full authoritative level — prove_level RE-VERIFIES fold_0 + comp_0 via
    recursive_verify, verify_level checks the root attests the bundle verifies, and a tampered root is rejected."""
    if os.environ.get("NADO_HEAVY") != "1":
        print("SKIP  full authoritative depth level (set NADO_HEAVY=1; minutes — recursion throughput wall)")
        return
    root = AD.prove_level(_BUNDLE, _PUBS, TRANS_X2, _BNDS, W=1, num_queries_inner=NQ, num_queries_level=NQO)
    ok, why = AD.verify_level(root, _BUNDLE, _PUBS, TRANS_X2, _BNDS, W=1, num_queries_inner=NQ, num_queries_level=NQO)
    assert ok, f"authoritative depth root must verify: {why}"
    bad = copy.deepcopy(root)
    q = bad["rv_fold"]["fold"]["queries"][0]
    q["steps"][0]["lo"] = (int(q["steps"][0]["lo"]) + 1) % P
    ok2, _ = AD.verify_level(bad, _BUNDLE, _PUBS, TRANS_X2, _BNDS, W=1, num_queries_inner=NQ, num_queries_level=NQO)
    assert not ok2, "a tampered authoritative root must be rejected"


if __name__ == "__main__":
    check("RECURSION-committed bundle verifies (out_backend threaded)", t_recursion_committed_bundle_verifies)
    check("fold_air reconstructs fold_0's schedule (verifies via stark.verify)", t_fold_air_reconstructs)
    check("comp_air reconstructs comp_0's schedule (verifies via stark.verify)", t_comp_air_reconstructs)
    check("tampered bundle public rejected (verifier-authoritative)", t_tampered_public_rejected)
    check("full authoritative depth level (opt-in)", t_full_depth_level)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
