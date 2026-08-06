"""K merkle updates in ONE STARK — the batched AIR.

WHY IT EXISTS. Proof size is LOGARITHMIC in trace length. Measured, one update per tree depth:

    T=512  6.24 MiB | T=2048  7.91 | T=4096  8.83 | T=8192  9.80 | T=16384  10.82

~1 MiB per doubling, because 88% of a proof is FRI queries and a query costs one Merkle path, which grows
with log N. So K updates in ONE trace cost ~(10.82 + log2 K) MiB instead of K x 10.82 — eight updates are
~13.8 MiB rather than 86.6 MiB.

That is the only lever left for the records half, which needs one update PER PRESENT MINER (20 and rising,
because it tracks fleet size) against a 191.94 MiB tx budget:
  - the K->1 recursion bundle would also collapse the bytes, and OOM-killed at 27.5 GB resident for K=2;
  - dropping NUM_QUERIES would work and costs security bits, which is not a prover-side decision.

THE ONE THING THAT CAN GO WRONG, AND THE REASON THIS FILE IS MOSTLY SOUNDNESS TESTS. Transitions are
evaluated on every row but the last, so the SEAM row — the last row of segment s, whose `nxt` is the first
row of segment s+1 — is evaluated. Round and absorb constraints already vanish there, but the five sib/dir
HOLD constraints were gated on (1 - ACT_A), which is 1 at a seam: they would force segment s's path to carry
into segment s+1. Re-gating them on a periodic HOLD column that is 0 on seams is the entire change.

Get that wrong in the LOOSE direction and a batch proves less than K separate proofs did — a prover could
move a second slot it never pinned. So every check below that matters asks whether a FALSE statement is
REJECTED, not whether a true one is accepted.

Run: python3 tests/test_merkle_update_batch.py
"""
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from execnode.stark import merkle_update as MU, storage_tree as SST, backend as B, field as F  # noqa: E402

fails = 0
D = 5                      # small: T = next_pow2(K * 6 * 55). K=3 -> 1024 rows. Seconds, not minutes.
NQ = 12
KEYS = [1, 2, 3]
INIT = {1: 11, 2: 22, 3: 33}
NEW = {1: 111, 2: 222, 3: 333}


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


def _dirs(key):
    return [(key >> i) & 1 for i in range(D)]


def _build(keys=KEYS):
    """Walk a real SparseStore so each segment's siblings are the ones AFTER the previous update landed —
    the case a batch has to get right and a single proof never exercises."""
    store = SST.SparseStore(D, dict(INIT))
    items = []
    for k in keys:
        items.append((store.get(k), NEW[k], store.path(k), _dirs(k)))
        store.set(k, NEW[k])
    return items


def _public(items):
    return [(o, n, dirs) for (o, n, _s, dirs) in items]


def t_batch_proves_and_verifies():
    items = _build()
    proof, roots = MU.prove_updates(items, num_queries=NQ)
    assert proof["K"] == len(items) and proof["D"] == D, "K and D must be public geometry"
    ok, why = MU.verify_updates(proof, _public(items), roots, num_queries=NQ)
    assert ok, f"an honest batch must verify: {why}"


def t_roots_chain_is_public():
    """roots[i+1] is update i's post AND update i+1's pre. If the chain is not pinned, a batch proves K
    unrelated updates rather than a sequence."""
    items = _build()
    _proof, roots = MU.prove_updates(items, num_queries=NQ)
    store = SST.SparseStore(D, dict(INIT))
    assert roots[0] == store.root(), "roots[0] must be the real pre-state root"
    for k in KEYS:
        store.set(k, NEW[k])
    assert roots[-1] == store.root(), "roots[-1] must be the real post-state root"
    assert len(roots) == len(items) + 1


def t_a_tampered_root_is_rejected():
    items = _build()
    proof, roots = MU.prove_updates(items, num_queries=NQ)
    for i in range(len(roots)):
        bad = list(roots)
        bad[i] = tuple((x + 1) % F.P for x in bad[i])
        ok, _ = MU.verify_updates(proof, _public(items), bad, num_queries=NQ)
        assert not ok, f"root {i} tampered and still accepted"


def t_a_tampered_value_is_rejected():
    items = _build()
    proof, roots = MU.prove_updates(items, num_queries=NQ)
    pub = _public(items)
    for i in range(len(pub)):
        for j in (0, 1):                              # old_val, then new_val
            bad = list(pub)
            t = list(bad[i]); t[j] = (t[j] + 1) % F.P; bad[i] = tuple(t)
            ok, _ = MU.verify_updates(proof, bad, roots, num_queries=NQ)
            assert not ok, f"update {i} field {j} tampered and still accepted"


def t_a_tampered_position_is_rejected():
    """THE SEAM TEST. Every segment must pin its OWN position. If the HOLD gate leaked across a seam, a later
    segment's dirs would be constrained by the earlier one and swapping them could pass."""
    items = _build()
    proof, roots = MU.prove_updates(items, num_queries=NQ)
    pub = _public(items)
    for i in range(len(pub)):
        bad = list(pub)
        o, n, dirs = bad[i]
        bad[i] = (o, n, [1 - d for d in dirs])
        ok, _ = MU.verify_updates(proof, bad, roots, num_queries=NQ)
        assert not ok, f"update {i} position flipped and still accepted"


def t_segments_may_use_different_paths():
    """The defect the HOLD gate fixes, stated positively: consecutive updates at DIFFERENT positions have
    different sibling paths, and the batch must accept that. Keys 1, 2, 3 differ in their low bits, so their
    paths genuinely diverge — if HOLD leaked, this would fail to prove at all."""
    items = _build()
    assert items[0][3] != items[1][3], "the test is vacuous unless the positions differ"
    proof, roots = MU.prove_updates(items, num_queries=NQ)
    ok, why = MU.verify_updates(proof, _public(items), roots, num_queries=NQ)
    assert ok, f"segments with different paths must batch: {why}"


def t_a_declared_K_that_lies_is_rejected():
    items = _build()
    proof, roots = MU.prove_updates(items, num_queries=NQ)
    ok, why = MU.verify_updates(proof, _public(items)[:-1], roots[:-1], num_queries=NQ)
    assert not ok, "a public statement covering fewer updates than K must be refused"
    assert "K=" in why or "geometry" in why, f"say WHY, got: {why}"


def t_batch_of_one_matches_the_single_update_path():
    """K=1 must still be a correct proof — prove_transition chunks, and the last chunk is often 1."""
    items = _build(keys=[1])
    proof, roots = MU.prove_updates(items, num_queries=NQ)
    ok, why = MU.verify_updates(proof, _public(items), roots, num_queries=NQ)
    assert ok, f"K=1 must verify: {why}"


def t_max_batch_is_bounded_by_the_trace_limit():
    from execnode.stark import stark as S
    import protocol
    k = MU.max_batch(protocol.EXEC_TREE_DEPTH)
    seg = (protocol.EXEC_TREE_DEPTH + 1) * MU.BR
    assert MU._next_pow2(k * seg) <= S.MAX_TRACE_ROWS, "max_batch must fit MAX_TRACE_ROWS"
    assert MU._next_pow2((k + 1) * seg) > S.MAX_TRACE_ROWS, "max_batch must be the LARGEST that fits"


def t_single_update_air_is_untouched():
    """Batching is a SEPARATE AIR so proofs already in flight keep verifying bit-identically. If someone
    re-gates the shared _transitions() instead, this is what catches it."""
    sibs = [tuple((7 * i + j + 1) % F.P for j in range(MU.CAP)) for i in range(D)]
    dirs = _dirs(0b10110)
    proof, pre, post = MU.prove_update(11, 12, sibs, dirs, num_queries=NQ)
    ok, why = MU.verify_update(proof, 11, 12, pre, post, dirs, num_queries=NQ)
    assert ok, f"the single-update path must be unchanged: {why}"
    assert "K" not in proof, "a single-update proof must not claim batch geometry"


for nm, fn in [("batch proves and verifies", t_batch_proves_and_verifies),
               ("roots chain is public", t_roots_chain_is_public),
               ("tampered root rejected", t_a_tampered_root_is_rejected),
               ("tampered value rejected", t_a_tampered_value_is_rejected),
               ("tampered position rejected (the seam test)", t_a_tampered_position_is_rejected),
               ("segments may use different paths", t_segments_may_use_different_paths),
               ("a lying K is rejected", t_a_declared_K_that_lies_is_rejected),
               ("batch of one verifies", t_batch_of_one_matches_the_single_update_path),
               ("max_batch is bounded by the trace limit", t_max_batch_is_bounded_by_the_trace_limit),
               ("single-update AIR untouched", t_single_update_air_is_untouched)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
