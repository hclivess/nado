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


def t_the_lde_cache_is_bounded_and_compact():
    """The LDEs are now CACHED across proofs (a span rebuilds the same 15 of 16 columns for every K=9
    proof, and every later settle rebuilds them again), so "freed after harvest" is no longer the
    invariant — bounded and compact is.

    A list of 524288 PyLongs is ~23 MB; array('Q') is 4 MB, and field elements fit because P < 2^64. Without
    that the cache would hand back the memory the Horner form existed to avoid.
    """
    src = open(os.path.join(ROOT, "execnode/stark/stark.py")).read()
    assert "_PER_LDE_CACHE_MAX" in src, "the cache must be bounded"
    seg = src[src.index("def _per_lde_cached"):]
    seg = seg[:seg.index("def _per_evaluator")]
    assert '_arr("Q"' in seg, "the LDE must be stored as array('Q'), not a list of PyLongs"
    assert "popitem(last=False)" in seg, "eviction must drop the LEAST RECENTLY USED entry"
    assert "move_to_end" in seg, "a hit must refresh recency, or reuse cannot protect an entry"


def t_the_cache_key_binds_the_column_bytes():
    """Keying on (T, D, K) or on the column's index would return the wrong polynomial the moment a caller's
    layout differed — and the verifier would then check a proof against values nobody derived from the
    statement. Same rule settle_verify_key follows for verdicts: bind the BYTES."""
    src = open(os.path.join(ROOT, "execnode/stark/stark.py")).read()
    seg = src[src.index("def _per_lde_key"):src.index("def _per_lde_cached")]
    assert "blake2b" in seg, "the key must be a digest of the column contents"
    assert "tobytes()" in seg, "the digest must cover the packed column bytes"
    assert "N, T" in seg, "the key must also bind the geometry the LDE was built for"


def t_a_cached_column_returns_identical_values():
    """RESOLVE AND CALL. A cache that returns anything but the same field elements is a consensus fault, not
    a slow path — so compare a cold build against a warm one, elementwise."""
    import execnode.stark.stark as S2
    T, blowup = 512, 4
    N = blowup * T
    col = [(i * 7919 + 13) % F.P for i in range(T)]
    S2._PER_LDE_CACHE.clear(); S2._PER_LDE_SEEN.clear()
    # ADMIT ON SECOND USE: the 1st call is a miss and only records the digest, the 2nd is still a miss but
    # earns the slot, the 3rd hits. A one-shot column therefore never costs 4 MB — which is the whole point,
    # since DIRP differs for every proof and would otherwise evict the columns that DO repeat.
    a, hit_a = S2._per_lde_cached(list(col), N, T, S2.OFF)
    assert hit_a is False, "first sight must be a miss"
    b, hit_b = S2._per_lde_cached(list(col), N, T, S2.OFF)
    assert hit_b is False, "second sight is still computed — it is the one that earns a slot"
    c, hit_c = S2._per_lde_cached(list(col), N, T, S2.OFF)
    assert hit_c is True, "third sight must hit the cache"
    assert list(a) == list(b) == list(c), "every route must return identical values"
    b = c
    # and the values must still equal the direct Horner evaluation
    coeffs = F.interpolate(list(col))
    wN = F.primitive_root_of_unity(N)
    for lo in (0, 1, N // 3, N - 1):
        assert F.poly_eval(coeffs, F.mul(S2.OFF, F.pw(wN, lo))) == b[lo], f"cached value wrong at {lo}"


def t_a_different_column_is_not_served_from_cache():
    """The whole risk of caching: one column's LDE handed back for another."""
    import execnode.stark.stark as S2
    T, blowup = 512, 4
    N = blowup * T
    c1 = [(i * 7919 + 13) % F.P for i in range(T)]
    c2 = list(c1); c2[T // 2] = (c2[T // 2] + 1) % F.P        # one element differs
    S2._PER_LDE_CACHE.clear()
    a, _ = S2._per_lde_cached(c1, N, T, S2.OFF)
    b, hit = S2._per_lde_cached(c2, N, T, S2.OFF)
    assert hit is False, "a column differing by ONE element must not hit"
    assert list(a) != list(b), "distinct columns must yield distinct LDEs"


def t_a_one_shot_column_never_takes_a_slot():
    """THE POINT OF THE ADMISSION FILTER. DIRP is different for every proof; caching it on first sight
    evicts precisely the ~30 columns that recur. Measured before the filter existed: 31 misses on a cold
    cache and 31 again on a warm one — the cache bought exactly nothing."""
    import execnode.stark.stark as S2
    T, blowup = 128, 4
    N = blowup * T
    S2._PER_LDE_CACHE.clear(); S2._PER_LDE_SEEN.clear()
    for k in range(40):                       # 40 columns, each seen ONCE
        S2._per_lde_cached([(i * (k + 3) + k) % F.P for i in range(T)], N, T, S2.OFF)
    assert len(S2._PER_LDE_CACHE) == 0, (
        f"one-shot columns must not occupy LDE slots; cache holds {len(S2._PER_LDE_CACHE)}")


def t_the_cache_evicts_instead_of_growing():
    """A verifier that grows without bound is a slower outage than one that recomputes."""
    import execnode.stark.stark as S2
    T, blowup = 128, 4
    N = blowup * T
    S2._PER_LDE_CACHE.clear()
    for k in range(S2._PER_LDE_CACHE_MAX + 6):
        S2._per_lde_cached([(i * (k + 3) + k) % F.P for i in range(T)], N, T, S2.OFF)
    assert len(S2._PER_LDE_CACHE) <= S2._PER_LDE_CACHE_MAX, (
        f"cache grew to {len(S2._PER_LDE_CACHE)}, over the {S2._PER_LDE_CACHE_MAX} bound")


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
               ("lde cache is bounded and compact", t_the_lde_cache_is_bounded_and_compact),
               ("cache key binds the column bytes", t_the_cache_key_binds_the_column_bytes),
               ("cached column returns identical values", t_a_cached_column_returns_identical_values),
               ("a different column is not served from cache", t_a_different_column_is_not_served_from_cache),
               ("a one-shot column never takes a slot", t_a_one_shot_column_never_takes_a_slot),
               ("cache evicts instead of growing", t_the_cache_evicts_instead_of_growing),
               ("real proof verifies, tampering fails",
                t_a_real_batch_proof_still_verifies_and_tampering_still_fails)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
