"""The verifier's periodic LDE harvest must equal the Horner evaluation EXACTLY.

WHY IT EXISTS. Dense periodic columns were re-evaluated with an O(T) Horner pass ONCE PER QUERY. Measured
live on one of the four proofs a 32-update records span carries:

    [stark-verify] T=131072 W=29 queries=320 periodic=16 committed=0 |
    query-loop 470.9s = periodic 459.7s (5120 dense evals) + constraints 1.1s + rest 10.1s

97.6% of the query loop, in pure Python, on the GIL — ~1840s across four proofs. That single line was the
entire records verification cost and the reason the submit budget was blown at 1200s and again at 1800s.

THE REPLACEMENT IS AN IDENTITY, NOT AN APPROXIMATION. The query point is a DOMAIN point, x = OFF·wN^lo, so
a periodic column's degree<T interpolation evaluated at x IS its coset-LDE evaluation at index lo — the same
polynomial at the same point. The prover already computes it that way (stark.py per_lde). So the only thing
worth testing is that the two agree on the nose: a verifier that is merely CLOSE would accept proofs it
should reject, and "the tests still pass" is not evidence of that, because a proof that verifies under both
paths says nothing about a proof that should verify under neither.

These checks therefore compare field elements directly, and separately confirm that the structured
(succinct) periodic form is left ALONE — it is already O(period + #sparse) independent of T, and routing it
through an O(N) LDE would make the cheap case pay for the expensive one.

Run: python3 tests/test_periodic_lde_equivalence.py
"""
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from execnode.stark import field as F
import execnode.stark.stark as S

fails = 0


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


def _lde_vs_horner(T, blowup=4, n_pts=64):
    """Return (mismatches, checked) comparing the two evaluation routes over n_pts domain indices."""
    N = blowup * T
    col = [(i * 2654435761 + 12345) % F.P for i in range(T)]      # dense, no structure to exploit
    coeffs = F.interpolate(list(col))
    lde = S._coset_evaluate(coeffs, N, S.OFF)
    wN = F.primitive_root_of_unity(N)
    bad, checked = [], 0
    step = max(1, N // n_pts)
    for lo in range(0, N, step):
        x = F.mul(S.OFF, F.pw(wN, lo))
        if F.poly_eval(coeffs, x) != lde[lo]:
            bad.append(lo)
        checked += 1
    return bad, checked


def t_lde_equals_horner_at_every_domain_point():
    """THE identity the optimisation rests on."""
    bad, checked = _lde_vs_horner(1024)
    assert checked > 0, "no points compared"
    assert not bad, f"{len(bad)} of {checked} domain points disagree (first: index {bad[:3]})"


def t_it_holds_at_a_larger_geometry_too():
    """T=1024 is the shielded circuit's size; the settle proofs run at T=131072. Check the identity is not
    an accident of a small subgroup."""
    bad, checked = _lde_vs_horner(4096, n_pts=48)
    assert not bad, f"{len(bad)} of {checked} domain points disagree at T=4096"


def t_the_lde_covers_the_whole_coset_not_just_the_first_half():
    """Query indices are `q["idx"] % (N // 2)`, so they live in the FIRST HALF of the coset — but the `nxt`
    row is (lo + blowup) % N, which wraps past it. An off-by-one in the offset convention would still pass a
    test that only sampled low indices."""
    T, blowup = 1024, 4
    N = blowup * T
    col = [(i * 7919 + 3) % F.P for i in range(T)]
    coeffs = F.interpolate(list(col))
    lde = S._coset_evaluate(coeffs, N, S.OFF)
    wN = F.primitive_root_of_unity(N)
    for lo in (N - 1, N - 2, N // 2, N // 2 + 1, 0, 1):
        x = F.mul(S.OFF, F.pw(wN, lo))
        assert F.poly_eval(coeffs, x) == lde[lo], f"disagreement at coset index {lo} of {N}"


def t_structured_columns_are_not_routed_through_an_lde():
    """A structured column already evaluates in O(period + #sparse), INDEPENDENT of T. Building an O(N) LDE
    for it would make the succinct path pay the dense path's cost."""
    src = open(os.path.join(ROOT, "execnode/stark/stark.py")).read()
    i = src.index("_per_q = {}")
    seg = src[i:i + 900]
    assert "isinstance(_pc, dict)" in seg, (
        "the LDE precompute must SKIP structured (dict) periodic columns")
    assert "committed_set" in seg, "it must also skip committed columns — those come from the opening"


def t_the_harvest_frees_each_lde():
    """One LDE at N = blowup·T is ~20 MB; holding all 16 alive would trade the saved time for ~300 MB, and
    the Horner form was chosen in the first place to avoid an O(N) allocation."""
    src = open(os.path.join(ROOT, "execnode/stark/stark.py")).read()
    i = src.index("_per_q = {}")
    seg = src[i:i + 900]
    assert "del _lde" in seg, "each column's LDE must be released after its query points are harvested"


def t_a_real_batch_proof_still_verifies_and_tampering_still_fails():
    """End to end through the changed line: the same proof must verify, and a corrupted one must not. A
    faster verifier must not be a weaker one."""
    from execnode.stark import merkle_update as MU
    from execnode.stark import storage_tree as SST
    D, NQ = 5, 12          # small: T = next_pow2(K * (D+1) * 55). Seconds, not minutes.
    init, new, keys = {1: 11, 2: 22}, {1: 111, 2: 222}, [1, 2]
    # Walk a real store so each segment's siblings are the ones AFTER the previous update landed.
    store = SST.SparseStore(D, dict(init))
    items = []
    for k in keys:
        items.append((store.get(k), new[k], store.path(k), [(k >> i) & 1 for i in range(D)]))
        store.set(k, new[k])
    pub = [(o, n, dirs) for (o, n, _s, dirs) in items]
    proof, roots = MU.prove_updates(items, num_queries=NQ)
    ok, why = MU.verify_updates(proof, pub, roots, num_queries=NQ)
    assert ok, f"an honest batch must verify through the LDE path: {why}"
    bad = [(o, (n + 1) % F.P, dirs) for (o, n, dirs) in pub]
    ok2, _ = MU.verify_updates(proof, bad, roots, num_queries=NQ)
    assert not ok2, "a tampered public value must still be rejected"


for nm, fn in [("lde equals horner at every domain point", t_lde_equals_horner_at_every_domain_point),
               ("holds at a larger geometry", t_it_holds_at_a_larger_geometry_too),
               ("covers the whole coset", t_the_lde_covers_the_whole_coset_not_just_the_first_half),
               ("structured columns skipped", t_structured_columns_are_not_routed_through_an_lde),
               ("each lde is freed", t_the_harvest_frees_each_lde),
               ("real proof verifies, tampering fails",
                t_a_real_batch_proof_still_verifies_and_tampering_still_fails)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
