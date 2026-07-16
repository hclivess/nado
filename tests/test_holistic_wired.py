"""
Holistic prover WIRING gate: stark.prove routes RECURSION-backend proving through the native arena
(execnode/stark/stark_native.prove). This proves the wiring is SOUND on the REAL recursion AIRs — a
fri_verify fold proof and a recursive_verify K→1 bundle (fold + composition over the two-phase row gadget) —
by producing each BOTH ways (holistic default, and Python-forced via NADO_NO_HOLISTIC=1) and asserting the
proofs are BYTE-IDENTICAL, then verifying the holistic one. If native/starkprove isn't built, SKIP.

Run: python3 tests/test_holistic_wired.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import field as F, fri, fri_verify, backend as B, recursive_verify as RV, stark_native as SN

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def deep_eq(a, b, path="proof"):
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        assert len(a) == len(b), f"{path}: len {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            deep_eq(x, y, f"{path}[{i}]")
    elif isinstance(a, dict) and isinstance(b, dict):
        assert set(a) == set(b), f"{path}: keys differ"
        for k in a:
            deep_eq(a[k], b[k], f"{path}.{k}")
    else:
        assert a == b, f"{path}: {a} != {b}"


def _forced_python(fn):
    """Run fn() with the holistic prover disabled (pure-Python stark.prove)."""
    os.environ["NADO_NO_HOLISTIC"] = "1"
    try:
        return fn()
    finally:
        os.environ.pop("NADO_NO_HOLISTIC", None)


def _lowdeg(seed, N=8, DEG=4):
    import random
    random.seed(seed)
    c = [random.randrange(F.P) for _ in range(DEG)] + [0] * (N - DEG)
    off = F.GENERATOR
    ev = [F.poly_eval(c, x) for x in F.domain(N, off)]
    return fri.prove(ev, off, blowup=N // DEG, num_queries=2, backend=B.RECURSION)


def t_fold_proof_identical():
    """A real fri_verify fold proof (RECURSION, single-phase column) is byte-identical holistic vs Python."""
    inner = _lowdeg(1)
    holistic, pub_h = fri_verify.prove_fold([inner], num_queries_inner=2, num_queries_outer=2,
                                            out_backend=B.RECURSION)
    python, pub_p = _forced_python(lambda: fri_verify.prove_fold([inner], num_queries_inner=2,
                                                                 num_queries_outer=2, out_backend=B.RECURSION))
    deep_eq(holistic, python)
    ok, why = fri_verify.verify_fold(holistic, pub_h, expect_inner=2, expect_outer=2, out_backend=B.RECURSION)
    assert ok, f"holistic-proved fold must verify: {why}"


def t_recursive_bundle_identical():
    """A real recursive_verify K→1 bundle (fold + row-mode composition over the two-phase row gadget) is
    byte-identical holistic vs Python — this exercises BOTH recursion gadgets (fri_verify + rowcomp_verify)
    on real inner proofs — and verifies."""
    from execnode.stark import stark
    T, SEED, K, NQ, NQO = 8, 123456789 % F.P, 2, 2, 4
    PER0 = {"period": 4, "base": [3, 1, 4, 1]}
    PD = [PER0["base"][i % 4] for i in range(T)]
    TRANS = [lambda c, n, p, ch: F.sub(n[0], F.add(F.mul(c[0], c[0]), p[0])),
             lambda c, n, p, ch: F.sub(c[1], F.mul(c[0], c[0])),
             lambda c, n, p, ch: F.sub(n[2], F.add(c[2], F.mul(ch[0], n[0])))]
    def build_aux(trace, chals):
        g = chals[0]; acc = 0; out = []
        for i, row in enumerate(trace):
            if i > 0:
                acc = F.add(acc, F.mul(g, row[0]))
            out.append(acc)
        return [out]
    SPEC = {"num_challenges": 1, "num_aux": 1, "build": build_aux}
    proofs, bnds, seed = [], [], SEED
    for _ in range(K):
        col = [seed]
        for i in range(T - 1):
            col.append(F.add(F.mul(col[-1], col[-1]), PD[i]))
        trace = [[v, F.mul(v, v)] for v in col]
        bl = [(0, 0, seed), (0, 2, 0)]
        pr = stark.prove(trace, TRANS, bl, periodic=[PER0], max_degree=2, num_queries=NQ,
                         aux_spec=SPEC, backend=B.RECURSION, row_commit=True)
        proofs.append(pr); bnds.append(bl); seed = F.add(F.mul(col[-1], col[-1]), PD[(T - 1) % 4])

    def _bundle():
        return RV.prove(proofs, TRANS, bnds, num_queries_outer=NQO, periodic=[PER0], num_challenges=1, num_aux=1)
    holistic = _bundle()
    python = _forced_python(_bundle)
    deep_eq(holistic, python)
    pubs = [RV.public_part(p) for p in proofs]
    ok, why = RV.verify(pubs, TRANS, bnds, holistic, num_queries_outer=NQO, periodic=[PER0],
                        num_challenges=1, num_aux=1)
    assert ok, f"holistic-proved recursion bundle must verify: {why}"


if __name__ == "__main__":
    if not SN.available():
        print("SKIP  native/starkprove not built — stark.prove uses the pure-Python path (still correct).")
        sys.exit(0)
    check("real fold proof byte-identical holistic vs Python (+ verifies)", t_fold_proof_identical)
    check("real recursion bundle byte-identical holistic vs Python (+ verifies)", t_recursive_bundle_identical)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
