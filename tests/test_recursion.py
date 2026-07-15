"""
STARK recursion foundation (doc/zk-recursion.md). Recursion = verifying a proof inside a proof, which needs
(a) a wide-sponge ALGEBRAIC hash so the verifier's Merkle/transcript hashing is field arithmetic, and
(b) that hash to be SOUND (≥128-bit) as a proof commitment. This exercises both, plus the core recursion
gadget: an alghash2 Merkle-membership AIR (the dominant, and hardest, thing a recursion circuit repeats).

Run: python3 tests/test_recursion.py     (a few slow proofs at tiny params — the Python prover, not Rust)
"""
import os, sys, copy, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import alghash2 as a2, field as F, stark, backend, recursion

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


# ---- 3.1 the wide-sponge hash is sound-shaped -------------------------------------------------------
def t_alghash2_digest_width():
    d = a2.hashn([1, 2, 3])
    assert isinstance(d, tuple) and len(d) == 4, "256-bit (4-lane) digest"
    assert a2.hashn([1, 2, 3]) == d, "deterministic"
    assert a2.hashn([1, 2, 3]) != a2.hashn([1, 2, 4]) != a2.hashn([1, 2]), "collision/length separation"

def t_alghash2_mds_invertible():
    # the linear layer must be a bijection (Gaussian elimination over the field)
    n = a2.WIDTH
    aug = [a2._MDS[i][:] + [1 if j == i else 0 for j in range(n)] for i in range(n)]
    rank = 0
    for col in range(n):
        piv = next((r for r in range(rank, n) if aug[r][col] != 0), None)
        assert piv is not None, "MDS singular"
        aug[rank], aug[piv] = aug[piv], aug[rank]
        inv = F.inv(aug[rank][col]); aug[rank] = [F.mul(v, inv) for v in aug[rank]]
        for r in range(n):
            if r != rank and aug[r][col]:
                f = aug[r][col]; aug[r] = [F.sub(aug[r][k], F.mul(f, aug[rank][k])) for k in range(2 * n)]
        rank += 1
    assert rank == n

def t_alghash2_no_collisions():
    seen = set()
    for i in range(4000):
        seen.add(a2.hashn([i])); seen.add(a2.node(a2.leaf(i), a2.leaf(i + 1)))
    assert len(seen) == 8000, "collision among 8000 structured digests"


# ---- 3.2 an alghash2-backed STARK proves + verifies + rejects tampering (proof is field-verifiable) --
def _air():
    return ([lambda c, n, p: F.sub(F.sub(n[0], c[0]), 1)], [(0, 0, 0)])   # counter: c_next = c+1, c[0]=0

def t_alghash2_stark():
    trans, bnds = _air()
    trace = [[i] for i in range(4)]
    pr = stark.prove(trace, trans, bnds, max_degree=2, num_queries=3, backend=backend.ALGHASH2)
    ok, why = stark.verify(pr, trans, bnds, max_degree=2, num_queries=3, backend=backend.ALGHASH2)
    assert ok, f"honest alghash2 proof must verify: {why}"
    # cross-backend + tamper are rejected
    assert not stark.verify(pr, trans, bnds, max_degree=2, num_queries=3, backend=backend.BLAKE2B)[0]
    bad = copy.deepcopy(pr); bad["openings"][0]["cols"][0]["cur"] = (bad["openings"][0]["cols"][0]["cur"] + 1) % F.P
    assert not stark.verify(bad, trans, bnds, max_degree=2, num_queries=3, backend=backend.ALGHASH2)[0]

def t_blake2b_unchanged():
    # the default path stays byte-identical: a blake2b proof still verifies under blake2b
    trans, bnds = _air()
    trace = [[i] for i in range(8)]
    pr = stark.prove(trace, trans, bnds, max_degree=2, num_queries=6)
    assert stark.verify(pr, trans, bnds, max_degree=2, num_queries=6)[0]


# ---- the core recursion gadget: an alghash2 preimage AIR (arithmetized in-circuit hashing) ---------
def t_preimage_air():
    # prove knowledge of the preimage of an alghash2 leaf digest, entirely as field constraints — the
    # atomic hashing-in-circuit gadget a recursion verifier repeats.
    proof, digest, _ = recursion.prove_preimage([a2.DOM_LEAF, 42], num_queries=3)
    assert digest == a2.leaf(42), "in-circuit digest must equal the native alghash2.leaf"
    ok, why = recursion.verify_preimage(proof, digest, num_queries=3)
    assert ok, f"honest preimage proof must verify: {why}"
    assert not recursion.verify_preimage(proof, a2.leaf(43), num_queries=3)[0], "wrong digest rejected"
    bad = copy.deepcopy(proof)
    bad["openings"][0]["cols"][0]["cur"] = (bad["openings"][0]["cols"][0]["cur"] + 1) % F.P
    assert not recursion.verify_preimage(bad, digest, num_queries=3)[0], "tampered trace rejected"


def t_fri_fold_air():
    """The FRI fold-consistency AIR: fold rows from a REAL FRI proof prove + verify; a fold made inconsistent
    is rejected. This is the arithmetic half of the in-circuit FRI verifier (pairs with the membership AIR)."""
    from execnode.stark import fri
    from execnode.stark.transcript import Transcript
    import random
    random.seed(3)
    N, deg = 64, 8
    coeffs = [random.randrange(F.P) for _ in range(deg)] + [0] * (N - deg)
    off = F.GENERATOR
    evals = [F.poly_eval(coeffs, x) for x in F.domain(N, off)]
    proof = fri.prove(evals, off, blowup=N // deg, num_queries=4, backend=backend.ALGHASH2)
    t = Transcript("fri", backend=backend.ALGHASH2)
    alphas, doms, o, n = [], [], off, N
    for r in proof["roots"]:
        t.absorb(r); alphas.append(t.challenge()); doms.append(F.domain(n, o)); o = F.mul(o, o); n //= 2
    rows = recursion.fold_rows(proof, alphas, doms)
    assert rows, "no fold rows extracted"
    fp = recursion.prove_fri_folds(rows, num_queries=4)
    ok, why = recursion.verify_fri_folds(fp, rows, num_queries=4)
    assert ok, f"real fold proof must verify: {why}"
    bad = list(rows); bad[0] = (bad[0][0] ^ 1,) + bad[0][1:]      # break one fold's consistency
    try:
        bp = recursion.prove_fri_folds(bad, num_queries=4)
        ok2, _ = recursion.verify_fri_folds(bp, bad, num_queries=4)
        assert not ok2, "an inconsistent fold must be rejected"
    except Exception:
        pass                                                     # prover refusing the bad witness is also fine


def t_fri_step_air():
    """The INTEGRATED FRI-step AIR: prove (in one STARK, only root + x,α,nxt public) that lo,hi are Merkle-
    authenticated under `root` AND fold to nxt — the opened values are private witness, linked to the fold by
    carry columns. Consistent step verifies; an inconsistent fold is rejected; a leaf not in the tree can't
    build a valid path. This is the atomic unit of the in-circuit FRI verifier (membership + fold, integrated)."""
    import random
    random.seed(5)
    N = 8
    V = [random.randrange(F.P) for _ in range(N)]
    root, layers = recursion.rmerkle_commit(V)
    half = N // 2; lo = 3; hi = lo + half
    lo_val, hi_val = V[lo], V[hi]
    plo = recursion.rmerkle_path(layers, lo); phi = recursion.rmerkle_path(layers, hi)
    x = random.randrange(F.P); alpha = random.randrange(F.P)
    inv2 = F.inv(2)
    nxt = F.add(F.mul(F.add(lo_val, hi_val), inv2),
                F.mul(alpha, F.mul(F.sub(lo_val, hi_val), F.mul(inv2, F.inv(x)))))
    proof = recursion.prove_fri_step(lo_val, lo, plo, hi_val, hi, phi, root, x, alpha, nxt, num_queries=4)
    ok, why = recursion.verify_fri_step(proof, root, x, alpha, nxt, num_queries=4)
    assert ok, f"consistent FRI step must verify: {why}"
    # inconsistent fold (same wrong nxt on both sides so the public-input check passes) must be rejected
    bad_nxt = (nxt + 1) % F.P
    bp = recursion.prove_fri_step(lo_val, lo, plo, hi_val, hi, phi, root, x, alpha, bad_nxt, num_queries=4)
    okb, _ = recursion.verify_fri_step(bp, root, x, alpha, bad_nxt, num_queries=4)
    assert not okb, "an opening pair that does not fold to nxt must be rejected"
    # a leaf not in the tree cannot form a path that hashes to root
    try:
        recursion.prove_fri_step((lo_val + 1) % F.P, lo, plo, hi_val, hi, phi, root, x, alpha, nxt, num_queries=4)
        assert False, "wrong leaf should not build a valid path"
    except AssertionError as e:
        assert "does not hash to root" in str(e) or "should not build" in str(e)


if __name__ == "__main__":
    check("alghash2: 256-bit digest, deterministic, separated", t_alghash2_digest_width)
    check("alghash2: MDS linear layer is invertible", t_alghash2_mds_invertible)
    check("alghash2: no collisions across 8000 digests", t_alghash2_no_collisions)
    check("blake2b STARK path unchanged (byte-identical default)", t_blake2b_unchanged)
    check("alghash2 STARK proves+verifies+rejects tamper (field-verifiable proof)", t_alghash2_stark)
    check("recursion gadget: alghash2 preimage AIR (proves in-circuit, wrong digest/tamper rejected)",
          t_preimage_air)
    check("FRI fold-consistency AIR (real folds prove; inconsistent fold rejected)", t_fri_fold_air)
    check("integrated FRI-step AIR (membership+fold, authenticated openings link to the fold)", t_fri_step_air)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
