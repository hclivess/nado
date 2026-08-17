"""An archive node must come out of wedge recovery with every CANONICAL block it went in with.

WHY THIS FILE EXISTS. On 2026-08-17 this box's archive was truncated twice by re-anchoring, with nothing
pruned: history 0 -> 49735 at 01:47, then 49735 -> 56735 at 13:32. Three causes, all in the recovery
path: bodies were wiped wholesale, only a fixed window was re-fetched, and the windowed snapshot import
replaced the deep number<->hash index. The requirement is now explicit: history means the canonical chain,
and an archive node must not lose any of it. Fork blocks are not history; blocks below the fork point are.

The decision lives in ops/canonical_restore.plan, PURE (no LMDB, no network) so this file can exercise
every shape directly. The first version of this test asserted against a COPY of the logic and stayed
green with the real gate disabled — so every check here calls the real planner, and the suite is
mutation-checked against it (see the commit).

Run: python3 tests/test_reanchor_archive_backfill.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops import canonical_restore as CR

FAILS = []


def check(name, fn):
    try:
        fn()
        print("PASS  " + name)
    except AssertionError as e:
        print("FAIL  " + name + " — " + str(e))
        FAILS.append(name)
    except Exception as e:
        print(f"FAIL  {name} — {type(e).__name__}: {e}")
        FAILS.append(name)


def H(chain, h):
    """A fake hash: same chain letter + height -> same hash. Distinct chains differ."""
    return f"{chain}{h:08x}"


def chain(letter, lo, hi):
    return {h: H(letter, h) for h in range(lo, hi + 1)}


def forked(lo, fork, hi_old, hi_new):
    """Our chain 'a' from lo..hi_old, canonical 'a' up to `fork` then 'b' up to hi_new."""
    old = chain("a", lo, hi_old)
    new = chain("a", lo, fork)
    new.update(chain("b", fork + 1, hi_new))
    return old, new


# ---- the incident, replayed -------------------------------------------------------------------------
def t_the_01_47_truncation_would_not_happen():
    """Archive from GENESIS (earliest 0), fork near the tip, donor index windowed. Everything below the
    fork point must be kept, not re-fetched — and 0 is a real earliest, not 'no earliest'."""
    old, new_full = forked(0, 49_700, 49_800, 57_000)
    new = {h: v for h, v in new_full.items() if h >= 57_000 - 50_000}    # windowed import
    have = set(old.values())                                              # we hold our whole chain
    p = CR.plan(old, new, 57_000, lambda bh: bh in have)
    assert p.fork_point == 49_700, f"fork point {p.fork_point}"
    assert p.kept == 49_701, f"kept {p.kept} — every block 0..49700 must be kept, none re-fetched"
    assert all(h > 49_700 for h, _ in p.missing), "a block below the fork point was listed as missing"
    assert len(p.missing) == 57_000 - 49_700, "the canonical blocks above the fork are what is missing"
    assert p.undetermined is None


def t_the_deep_index_the_import_dropped_is_re_put():
    old, new_full = forked(0, 49_700, 49_800, 57_000)
    new = {h: v for h, v in new_full.items() if h >= 7_000}
    p = CR.plan(old, new, 57_000, lambda bh: True)
    reput = dict(p.reput)
    assert set(reput) == set(range(0, 7_000)), "exactly the rows below the imported window are re-put"
    assert all(reput[h] == old[h] for h in reput), "re-put rows must come from our own (canonical) index"


def t_missing_is_highest_first():
    """So an interrupted fetch has filled the rollback window nearest the tip."""
    old, new = forked(0, 100, 150, 300)
    p = CR.plan(old, new, 300, lambda bh: bh in set(old.values()))
    hs = [h for h, _ in p.missing]
    assert hs == sorted(hs, reverse=True), "missing must be ordered highest first"


# ---- fork bodies vs history ------------------------------------------------------------------------
def t_fork_bodies_are_named_and_history_is_not_purged():
    old, new = forked(0, 100, 150, 300)
    p = CR.plan(old, new, 300, lambda bh: True)
    assert p.is_fork_body(120, H("a", 120)), "our block 120 is on the abandoned fork"
    assert not p.is_fork_body(50, H("a", 50)), "our block 50 is canonical — never a fork body"
    assert p.is_fork_body(50, "zzzz"), "at a height we CAN name, a different body is positively a fork body"
    assert not p.is_fork_body(999, "zzzz"), "at a height we CANNOT name, a body is KEPT, not purged"


def t_no_body_below_the_fork_point_is_ever_missing_or_fork():
    old, new = forked(0, 100, 150, 300)
    p = CR.plan(old, new, 300, lambda bh: True)
    for h in range(0, 101):
        assert p.canonical[h] == old[h]
        assert not p.is_fork_body(h, old[h])


# ---- the deep-fork (escalated recovery) shape ------------------------------------------------------
def t_fork_deeper_than_the_donor_index_is_flagged_undetermined_not_guessed():
    """Old and new share NO agreeing height in the window: the plan must not invent a fork point, and
    must hand the gap to the parent-hash walk instead of purging or keeping blindly."""
    old = chain("a", 0, 1_000)
    new = chain("b", 900, 1_100)                       # donor window starts above the (unknown) fork
    p = CR.plan(old, new, 1_100, lambda bh: True)
    assert p.fork_point is None
    assert p.undetermined == (0, 899), f"undetermined {p.undetermined}"
    assert p.notes, "the deep-fork case must be explained in the plan"
    assert not p.is_fork_body(500, H("a", 500)), "an unnamed height is never a fork body"
    assert p.is_fork_body(950, H("a", 950)), "inside the window we CAN name the canonical block"


# ---- rolling donor / previously-truncated archive --------------------------------------------------
def t_previously_truncated_archive_lists_the_hole_as_missing():
    """This box after 01:47: our index knows 49735.., bodies 49735... The plan must want the hole."""
    old = chain("a", 49_735, 60_000)
    new = chain("a", 7_000, 57_000)                    # donor happens to know deeper than we do
    have = {H("a", h) for h in range(49_735, 60_001)}
    p = CR.plan(old, new, 57_000, lambda bh: bh in have)
    assert p.fork_point == 57_000
    holes = [h for h, _ in p.missing]
    assert min(holes) == 7_000 and max(holes) == 49_734, f"missing range {min(holes)}..{max(holes)}"
    assert p.kept == 57_000 - 49_735 + 1


def t_contiguous_floor_means_no_gaps():
    canon = chain("a", 0, 100)
    have = {H("a", h) for h in range(0, 101)} - {H("a", 40)}
    assert CR.contiguous_floor(canon, lambda bh: bh in have, 100) == 41, \
        "history 'from N' must mean every block from N — a gap at 40 makes the floor 41"
    assert CR.contiguous_floor(canon, lambda bh: True, 100) == 0


# ---- degenerate inputs -----------------------------------------------------------------------------
def t_empty_indexes_do_not_crash_and_name_nothing():
    p = CR.plan({}, {}, 10, lambda bh: True)
    assert p.canonical == {} and p.missing == [] and p.reput == []
    p = CR.plan({}, chain("b", 5, 10), 10, lambda bh: False)
    assert p.fork_point is None and len(p.missing) == 6


def t_new_index_rows_above_the_anchor_are_ignored():
    """The tail sync owns everything above C; the plan must not fetch or purge there."""
    old, new = forked(0, 100, 150, 300)
    new[400] = "beyond"
    p = CR.plan(old, new, 300, lambda bh: True)
    assert 400 not in p.canonical


# ---- the executor is wired to the plan and to the retained bodies ------------------------------------
def t_identity_change_no_longer_wipes_bodies():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "ops", "snapshot_ops.py"), encoding="utf8").read()
    fn = src[src.index("def adopt_new_identity"):]
    fn = fn[:fn.index("\ndef ", 10)]
    assert "segment_store.reset(" not in fn, "adopt_new_identity wipes the segment store again"
    kv = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "ops", "kv_ops.py"), encoding="utf8").read()
    assert '{"attest_memo", "block_loc"}' in kv, "wipe_non_carried_dbs drops block_loc again"


def t_core_loop_captures_the_old_index_before_import_and_restores_after():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "loops", "core_loop.py"), encoding="utf8").read()
    cap = src.index("_old_index = dict(kv_ops.block_by_num_items())")
    imp = src.index("snapshot_ops.import_snapshot(manifest, chunks")
    assert cap < imp, "the old index must be captured BEFORE import_snapshot replaces it"
    assert "self._restore_canonical_chain(_old_index, anchor, source)" in src
    assert "def _start_deep_fill(" in src, "archive nodes no longer refill the deep chain"
    assert "self._maybe_advance_earliest()" in src, "the refill can never move earliest_block"


for name, fn in list(globals().items()):
    if name.startswith("t_"):
        check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "ARCHIVE KEEPS THE CANONICAL CHAIN THROUGH RECOVERY")
sys.exit(1 if FAILS else 0)
