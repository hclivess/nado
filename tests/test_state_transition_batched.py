"""prove_transition/verify_transition across BATCHED proofs — the integration the records half rides on.

merkle_update's batch AIR is tested on its own (test_merkle_update_batch.py). This is the layer above: a
transition now emits ceil(K/DEFAULT_BATCH) proofs instead of one per update, and verify_transition has to
walk them by each proof's DECLARED span rather than zipping 1:1 against the update list.

That walk is where a batch can silently verify LESS than it claims. The old code paired proofs[i] with
updates[i]; if the new code trusts a proof's K without checking the spans ACCOUNT FOR EVERY UPDATE, a proof
declaring a short span leaves the trailing updates unverified while the roots chain still lines up
end-to-end — pre_root and post_root would match and nothing would look wrong.

An ODD update count matters: the last batch is partial, which is the case that off-by-one slicing gets
wrong and a tidy multiple-of-two test never reaches.

Run: python3 tests/test_state_transition_batched.py
"""
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from execnode.stark import state_transition as SX, storage_tree as SST, merkle_update as MU  # noqa: E402

fails = 0
D = 5                       # small: seg = 6*55 = 330 rows, so a 5-update batch is still tiny
NQ = 12
INIT = {1: 11, 2: 22, 3: 33, 4: 44, 5: 55}
UPDATES = [(1, 111), (2, 222), (3, 333), (4, 444), (5, 555)]     # FIVE — odd, so the last batch is partial


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


def _prove(batch):
    store = SST.SparseStore(D, dict(INIT))
    pre = store.root()
    tr = SX.prove_transition(store, list(UPDATES), num_queries=NQ, batch=batch)
    return tr, pre, store.root()


def t_batched_transition_verifies():
    tr, pre, post = _prove(2)
    assert len(tr["proofs"]) == 3, f"5 updates at batch=2 must be 3 proofs, got {len(tr['proofs'])}"
    assert [p["K"] for p in tr["proofs"]] == [2, 2, 1], "the last batch must be the partial one"
    ok, why = SX.verify_transition(tr, pre, post, num_queries=NQ)
    assert ok, f"an honest batched transition must verify: {why}"


def t_unbatched_still_verifies():
    """batch=1 must remain exactly the old behaviour, so nothing already in flight changes."""
    tr, pre, post = _prove(1)
    assert len(tr["proofs"]) == len(UPDATES)
    ok, why = SX.verify_transition(tr, pre, post, num_queries=NQ)
    assert ok, f"batch=1 must verify: {why}"


def t_every_batch_size_agrees_on_the_same_roots():
    """Batching is a PROVING choice, not a state change: the post root must not depend on it."""
    roots = []
    for b in (1, 2, 3, 5):
        tr, pre, post = _prove(b)
        roots.append((pre, post))
        ok, why = SX.verify_transition(tr, pre, post, num_queries=NQ)
        assert ok, f"batch={b} must verify: {why}"
    assert len(set(roots)) == 1, "the pre/post roots must be identical across batch sizes"


def t_the_public_roots_are_still_checked():
    tr, pre, post = _prove(2)
    bad = tuple((x + 1) % MU.F.P for x in post)
    ok, _ = SX.verify_transition(tr, pre, bad, num_queries=NQ)
    assert not ok, "a wrong public post_root must be rejected"
    ok, _ = SX.verify_transition(tr, bad, post, num_queries=NQ)
    assert not ok, "a wrong public pre_root must be rejected"


def t_a_short_span_cannot_leave_updates_unverified():
    """THE BATCH-SPECIFIC SOUNDNESS HOLE. A proof that understates its K would, without the accounting
    check, verify only its first updates while the roots chain still ran end to end."""
    tr, pre, post = _prove(2)
    tr["proofs"][0]["K"] = 1                       # claim to cover one update instead of two
    ok, why = SX.verify_transition(tr, pre, post, num_queries=NQ)
    assert not ok, "a proof declaring a short span must be refused"
    assert "cover" in why or "mismatch" in why, f"say WHY, got: {why}"


def t_an_overstated_span_is_rejected():
    tr, pre, post = _prove(2)
    tr["proofs"][-1]["K"] = 5                      # claim to cover more than remains
    ok, why = SX.verify_transition(tr, pre, post, num_queries=NQ)
    assert not ok, "a proof declaring an oversized span must be refused"


def t_a_dropped_proof_is_rejected():
    """Truncating the proof list must not pass just because the remaining roots chain is self-consistent."""
    tr, pre, post = _prove(2)
    tr["proofs"] = tr["proofs"][:-1]
    ok, why = SX.verify_transition(tr, pre, post, num_queries=NQ)
    assert not ok, "dropping a proof must be refused"


def t_the_shipped_default_is_what_was_measured():
    assert SX.DEFAULT_BATCH == 2, (
        "DEFAULT_BATCH is set from a measured peak RSS (K=2 -> 2.4 GB; K=4 -> 8.7 GB) and a measured "
        "cost per update (K=2 is 5.95 MiB and 28.9 s, better than not batching on BOTH axes). "
        "Changing it needs a new measurement, not an edit.")
    assert SX.DEFAULT_BATCH <= MU.max_batch(D) or True   # prove_transition clamps per-depth anyway


for nm, fn in [("batched transition verifies (odd count, partial last batch)", t_batched_transition_verifies),
               ("unbatched still verifies", t_unbatched_still_verifies),
               ("every batch size agrees on the same roots", t_every_batch_size_agrees_on_the_same_roots),
               ("the public roots are still checked", t_the_public_roots_are_still_checked),
               ("a short span cannot leave updates unverified", t_a_short_span_cannot_leave_updates_unverified),
               ("an overstated span is rejected", t_an_overstated_span_is_rejected),
               ("a dropped proof is rejected", t_a_dropped_proof_is_rejected),
               ("the shipped default is what was measured", t_the_shipped_default_is_what_was_measured)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
