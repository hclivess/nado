"""THE NATIVE PROVER PRODUCES PROOFS THAT VERIFY.

This replaces tests/test_holistic_wired.py, which proved every AIR TWICE — once natively, once with the
holistic path disabled — and asserted the two were byte-identical.

WHY THAT WAS THE WRONG TEST, in the project owner's words: *"why do you need to python verify what you rust
computed? you computed."* Exactly right, and worth stating precisely because it is easy to get backwards:

  Python is not the specification. Neither is Rust. **The specification is what the verifier accepts.**

A proof that verifies is self-validating. Agreeing byte-for-byte with the Python prover only established
compatibility with an implementation that is now deleted — it never established correctness, and once the
Python side is gone the comparison cannot even be made. Meanwhile the old test paid for a second, pure-Python
proof of every case: the file's own docstring measured a level-1 fold at ~19 minutes that way.

The Python prover DID earn its keep during the port, but as a BUG LOCALISER rather than an oracle. Comparing
intermediate values is what pinpointed two real defects that would otherwise have surfaced only as "the proof
does not verify", with nothing pointing at the cause:
  * the Rust transcript omitted the length prefix that alghash2.py's hashn prepends;
  * sp_fri_size counted nl*3 per-layer lanes against the serializer's nl*2.
That value expires the moment the port is finished. Correctness evidence is verification.

So these checks prove ONCE, natively, and assert the verifier accepts the result — the property the chain
actually depends on. Same shapes as the test it replaces: a fold proof and a full recursion bundle, both on
the RECURSION backend.
"""
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.stark import field as F, fri, fri_verify, backend as B, stark, recursive_verify as RV

fails = 0


def check(name, fn):
    global fails
    t0 = time.time()
    print(f"....  {name}", flush=True)
    try:
        fn()
        print(f"PASS  {name}  [{time.time() - t0:.0f}s]", flush=True)
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}", flush=True)
        traceback.print_exc()


def _lowdeg(seed, N=8, DEG=4):
    import random
    random.seed(seed)
    c = [random.randrange(F.P) for _ in range(DEG)] + [0] * (N - DEG)
    off = F.GENERATOR
    ev = [F.poly_eval(c, x) for x in F.domain(N, off)]
    return fri.prove(ev, off, blowup=N // DEG, num_queries=2, backend=B.RECURSION)


def t_fold_verifies():
    """A real fri_verify fold proof, produced natively, is accepted by verify_fold."""
    inner = _lowdeg(1)
    proof, pub = fri_verify.prove_fold([inner], num_queries_inner=2, num_queries_outer=2,
                                       out_backend=B.RECURSION)
    ok, why = fri_verify.verify_fold(proof, pub, expect_inner=2, expect_outer=2, out_backend=B.RECURSION)
    assert ok, f"natively-proved fold must verify: {why}"


def t_fold_rejects_tampering():
    """...and the verifier is not simply permissive. A fold whose public statement has been altered must be
    REFUSED — otherwise "it verifies" would say nothing at all, which is the trap a comparison test at least
    could not fall into."""
    inner = _lowdeg(2)
    proof, pub = fri_verify.prove_fold([inner], num_queries_inner=2, num_queries_outer=2,
                                       out_backend=B.RECURSION)
    ok, _ = fri_verify.verify_fold(proof, pub, expect_inner=2, expect_outer=2, out_backend=B.RECURSION)
    assert ok, "control: the untampered fold must verify"
    import copy
    bad = copy.deepcopy(pub)
    seam = bad.get("seam_lo0")
    assert seam, "expected a layer-0 seam in the fold public statement"
    # Bump the first limb. A layer-0 seam is an extension TUPLE at D>1, so `int(v) + 1` raises before the
    # assert is ever reached — that shape has produced seven defects in this codebase and is linted against
    # by tests/test_tamper_helpers_field_agnostic.py.
    v = seam[0]
    seam[0] = ((int(v[0]) + 1) % F.P,) + tuple(v[1:]) if isinstance(v, tuple) else (int(v) + 1) % F.P
    ok2, _ = fri_verify.verify_fold(proof, bad, expect_inner=2, expect_outer=2, out_backend=B.RECURSION)
    assert not ok2, "a tampered fold public statement must be REJECTED"


def t_recursion_bundle_verifies():
    """A full recursion bundle over a real inner STARK proof verifies from its public parts alone."""
    import random
    random.seed(7)
    T, W = 8, 2
    trace = [[random.randrange(F.P) for _ in range(W)] for _ in range(T)]
    trans = [lambda cur, nxt, per: F.sub(F.mul(cur[0], 1), cur[0])]        # trivially satisfied
    bnds = []
    inner = stark.prove(trace, trans, bnds, num_queries=2, backend=B.RECURSION, row_commit=True)
    bundle = RV.prove(inner, trans, bnds, num_queries_outer=2)
    # boundaries are PER PROOF on the verify side (_as_lists pairs them with the proof list), so a single
    # proof still takes [bnds], not bnds. Passing the bare list reports "need one boundary list per proof".
    ok, why = RV.verify([RV.public_part(inner)], trans, [bnds], bundle, num_queries_outer=2,
                        num_queries_inner=2)
    assert ok, f"natively-proved recursion bundle must verify: {why}"


if __name__ == "__main__":
    check("native fold proof VERIFIES", t_fold_verifies)
    check("tampered fold public statement is REJECTED", t_fold_rejects_tampering)
    check("native recursion bundle VERIFIES", t_recursion_bundle_verifies)
    print()
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
