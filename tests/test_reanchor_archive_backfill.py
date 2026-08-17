"""Wedge recovery must not truncate an ARCHIVE node's history.

WHY THIS FILE EXISTS. On 2026-08-17 this box re-anchored to a height-57000 snapshot to escape a fork and
logged:

    ARCHIVE TRUNCATED BY WEDGE RECOVERY.
      History started at block 49735; it now starts at 56735.
      7000 blocks of bodies are orphaned and can no longer be served.

The node was a genuine archive (`archive: true`), so nothing pruned it — the backfill after a re-anchor
simply walked back a FIXED window (REWARD_WINDOW + 2*EPOCH_LENGTH + FINALITY_DEPTH) and stopped, and
adopt_new_identity had already wiped the segment store. The fork was ABOVE the finality floor, so every
block below the fork point was common to both chains: history the majority chain still vouches for, thrown
away by the recovery.

What is asserted here is the DEPTH DECISION, not the network round-trip: given an anchor height and a
previous earliest, an archive node must choose a backfill deep enough to get back to where it started,
and a rolling node must keep the cheap fixed window. That is the line that regressed, and it is pure
arithmetic, so it can be tested without a donor.

Run: python3 tests/test_reanchor_archive_backfill.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from protocol import EPOCH_LENGTH, FINALITY_DEPTH, REWARD_WINDOW

FAILS = []
SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "loops", "core_loop.py"), encoding="utf8").read()

FIXED = REWARD_WINDOW + 2 * EPOCH_LENGTH + FINALITY_DEPTH


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


def depth(archive, anchor_bn, prev_earliest):
    """The backfill depth the re-anchor path picks.

    THIS IS A COPY OF THE SOURCE'S ARITHMETIC, and a copy proves nothing on its own: the first version of
    this file asserted only against this function, so disabling the real gate in core_loop.py left every
    arithmetic check GREEN. Caught by mutating the source and watching the suite pass. The copy is kept
    because it documents the intended behaviour readably — but the binding checks are the source assertions
    below, which pin the actual gate line, and those are what the mutation test exercises."""
    tail_depth = FIXED
    if archive and prev_earliest > 0:
        want = anchor_bn - prev_earliest + 1
        if want > tail_depth:
            tail_depth = want
    return tail_depth


# ---- the incident, replayed -------------------------------------------------------------------------
def t_the_2026_08_17_truncation_would_not_happen_now():
    """anchor 57000, history began at 49735 -> must walk the whole 7266, not the fixed window."""
    d = depth(True, 57000, 49735)
    assert d == 57000 - 49735 + 1, f"archive backfill depth {d} does not reach block 49735"
    assert d > FIXED, "the fixed window would still have been used — this is the regression"


def t_archive_reaches_exactly_its_previous_earliest():
    for anchor, prev in ((57000, 49735), (60000, 1), (12345, 12000)):
        d = depth(True, anchor, prev)
        assert anchor - d + 1 <= prev, f"depth {d} from {anchor} stops short of {prev}"


# ---- the cost must not be imposed on nodes that did not ask for it ----------------------------------
def t_rolling_node_keeps_the_cheap_fixed_window():
    """A rolling node prunes this range anyway; making it refetch thousands of bodies would be pure cost."""
    assert depth(False, 57000, 49735) == FIXED, "rolling node paid the archive backfill cost"


def t_archive_never_shrinks_below_the_consensus_window():
    """The fixed window is a correctness floor (rollback + lookbacks), never a ceiling to fall under."""
    # previous earliest very close to the anchor -> `want` is tiny and must NOT win
    assert depth(True, 57000, 56990) == FIXED, "archive backfill fell below the consensus floor"
    assert depth(True, 57000, 0) == FIXED, "a node with no recorded earliest must keep the floor"


# ---- the code must actually contain the decision (not just this test's copy of it) -------------------
def t_the_source_gates_on_archive_and_prev_earliest():
    assert "_archive = bool(getattr(self.memserver" in SRC, "the archive flag is gone from the re-anchor path"
    assert "_prev_earliest_bn" in SRC, "the previous-earliest read is gone from the re-anchor path"
    m = re.search(r"want = int\(anchor\.get\(\"block_number\", 0\)\) - _prev_earliest_bn \+ 1", SRC)
    assert m, "the backfill no longer computes a depth that reaches the previous earliest"


def t_the_gate_is_actually_reached_not_just_defined():
    """THE CHECK THAT CAUGHT THE VACUOUS SUITE. Computing `want` is worthless if the branch guarding it can
    never run — disabling the gate (`if False and ...`) left every other assertion here green. Pin the gate
    condition itself, and pin that the depth it computes is the one the loop below actually iterates."""
    assert re.search(r"if _archive and _prev_earliest_bn > 0:", SRC), \
        "the archive backfill gate is no longer reachable on an archive node"
    # `want` must be assigned INTO tail_depth, and tail_depth must be what the backfill loop ranges over.
    assert re.search(r"tail_depth = want", SRC), "the computed depth is never adopted as tail_depth"
    assert re.search(r"for _ in range\(tail_depth\):", SRC), "the backfill loop no longer uses tail_depth"


def t_the_truncation_error_is_now_the_exception_path():
    """It must still exist — a donor that lacks the bodies has to be reported, loudly."""
    assert "ARCHIVE TRUNCATED BY WEDGE RECOVERY." in SRC, "the truncation alarm was removed"
    assert "COULD NOT RESTORE THE WHOLE ARCHIVE" in SRC, \
        "the comment still claims every re-anchor truncates the archive"


for name, fn in list(globals().items()):
    if name.startswith("t_"):
        check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "ARCHIVE SURVIVES WEDGE RECOVERY")
sys.exit(1 if FAILS else 0)
