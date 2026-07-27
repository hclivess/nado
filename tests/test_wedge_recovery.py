"""
PARTITION-WEDGE fix (loops/core_loop.py) — the universal rules that keep a node from finalizing itself onto
a minority fork and, if it ever is wedged, guarantee it recovers:

  * CORROBORATED DEPTH FINALITY (majority_on_our_canonical): the depth floor (tip - FINALITY_DEPTH) advances
    only while the peer-majority tip lies on OUR canonical chain. Lagging peers (our recent ancestor) still
    corroborate; a majority tip we don't have, or that we hold only as an orphan of another fork, blocks the
    advance. This is what used to let a starved node self-finalize a solo fork and wedge permanently.
  * ESCALATED RE-ANCHOR (reanchor_candidates): normal wedge recovery only accepts a heavier-chain snapshot
    ABOVE the local finality floor. (The old escalation ladder that dropped the floor restriction is
    (floor=0) — a wedge persisting across weight-selected attempts proves the floor itself is on a minority
    fork, and waiting for donors' snapshot cadence to cross it (observed live: ~25 min stuck) is the bug.

(Run: python3 tests/test_wedge_recovery.py — pure logic, no node, fast.)
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from loops.core_loop import majority_on_our_canonical, reanchor_candidates

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


# ---- corroboration: a tiny two-fork world ------------------------------------------------------------
# canonical chain:  h100 (A) -> h101 (B) -> h102 (C, our tip)
# orphaned fork:    h101 (X) — stored but not canonical
_STORE = {"A": {"block_number": 100}, "B": {"block_number": 101}, "C": {"block_number": 102},
          "X": {"block_number": 101}}
_CANON = {100: "A", 101: "B", 102: "C"}


def _get_block(h):
    return _STORE.get(h, False)


def _canon_at(n):
    return _CANON.get(n)


def t_majority_at_our_tip_corroborates():
    assert majority_on_our_canonical("C", _get_block, _canon_at)


def t_majority_lagging_ancestor_corroborates():
    """Peers one or two blocks behind a healthy producer still corroborate its chain."""
    assert majority_on_our_canonical("B", _get_block, _canon_at)
    assert majority_on_our_canonical("A", _get_block, _canon_at)


def t_majority_unknown_blocks_advance():
    """The majority tip is a block we don't have -> we are behind another chain -> no self-finalizing."""
    assert not majority_on_our_canonical("Z", _get_block, _canon_at)


def t_majority_on_other_fork_blocks_advance():
    """The majority tip is in our store but only as an ORPHAN of a different fork -> not corroborated.
    This is the exact wedge geometry: a starved node kept finalizing its own branch while the network's
    majority hash pointed at the other 14689+ branch."""
    assert not majority_on_our_canonical("X", _get_block, _canon_at)


# ---- escalated re-anchor candidates -------------------------------------------------------------------
# CORROBORATION IS REQUIRED. latest_block_weight is peer-ASSERTED and unverifiable at this point, and
# whatever checkpoint we adopt defines the state the tail is then "re-verified" against — so a lone
# responder must never be able to pick it. reanchor_candidates now demands SNAPSHOT_MIN_PEERS distinct
# peers advertising the IDENTICAL (snapshot_height, snapshot_hash) before weight ranks anything, with a
# lone-operator-seed exception for weak subjectivity. These fixtures therefore give each surviving
# candidate a corroborating partner; the lighter chain still never qualifies at any headcount.
_PEERS = ["p1", "p2", "p3", "p4", "p5", "p6"]
_ST = [
    {"protocol": 99, "latest_block_weight": 500, "snapshot_height": 14000, "snapshot_hash": "s1"},   # heavier, below floor
    {"protocol": 99, "latest_block_weight": 900, "snapshot_height": 14000, "snapshot_hash": "s2"},   # heaviest, below floor
    {"protocol": 99, "latest_block_weight": 400, "snapshot_height": 15000, "snapshot_hash": "s3"},   # lighter (never)
    None,                                                                            # dead peer
    {"protocol": 99, "latest_block_weight": 500, "snapshot_height": 14000, "snapshot_hash": "s1"},   # corroborates s1
    {"protocol": 99, "latest_block_weight": 900, "snapshot_height": 14000, "snapshot_hash": "s2"},   # corroborates s2
]
_OUR_WEIGHT, _FLOOR = 450, 14913


def t_normal_recovery_respects_floor():
    """Every heavier peer's snapshot sits below our floor -> no candidates -> the old permanent wedge."""
    assert reanchor_candidates(_PEERS, _ST, _OUR_WEIGHT, _FLOOR) == []


def t_escalated_recovery_crosses_floor():
    cand = reanchor_candidates(_PEERS, _ST, _OUR_WEIGHT, 0)
    # both CORROBORATED heavier checkpoints qualify (s1 and s2, two advertisers each); the lighter
    # chain never does, at any headcount.
    assert len(cand) == 4, cand
    assert {c[2] for c in cand} == {"s1", "s2"}, cand
    weight, height, shash, ip = max(cand)
    assert (shash, ip) == ("s2", "p6"), "heaviest corroborated chain must win the weight selection"


def t_lighter_majority_can_never_pin():
    """Headcount is irrelevant: any number of lighter peers yields no candidate at any floor."""
    light = [{"protocol": 99, "latest_block_weight": 449, "snapshot_height": 15000, "snapshot_hash": "sL"}] * 4
    assert reanchor_candidates(_PEERS, light, _OUR_WEIGHT, 0) == []


def t_malformed_statuses_skipped():
    broken = [{"protocol": 99, "latest_block_weight": 999}, {"snapshot_hash": "x", "snapshot_height": 1},
              {"protocol": 99, "latest_block_weight": 999, "snapshot_hash": "", "snapshot_height": 15000}, None]
    assert reanchor_candidates(_PEERS, broken, _OUR_WEIGHT, 0) == []


def t_foreign_protocol_donor_excluded():
    """A protocol-2 straggler's heavier dead fork must never be picked as a re-anchor donor
    (observed live 2026-07-18: donor 103.236.77.164, protocol 2, snapshot 49000)."""
    foreign = [{"protocol": 2, "latest_block_weight": 10**9, "snapshot_height": 49000, "snapshot_hash": "sF"}] * 2
    assert reanchor_candidates(["1.2.3.4", "1.2.3.5"], foreign, _OUR_WEIGHT, 0, min_protocol=3) == [], \
        "a foreign-protocol fork is excluded even when corroborated"
    ours = [{"protocol": 3, "latest_block_weight": 10**9, "snapshot_height": 49000, "snapshot_hash": "sO"}] * 2
    assert len(reanchor_candidates(["1.2.3.4", "1.2.3.5"], ours, _OUR_WEIGHT, 0, min_protocol=3)) == 2
    # ...and a SINGLE same-protocol responder is still refused: one peer can never pick our checkpoint.
    assert reanchor_candidates(["1.2.3.4"], ours[:1], _OUR_WEIGHT, 0, min_protocol=3) == [], \
        "a lone uncorroborated donor must never be selectable"



if __name__ == "__main__":
    check("majority at our tip corroborates", t_majority_at_our_tip_corroborates)
    check("majority lagging our chain corroborates", t_majority_lagging_ancestor_corroborates)
    check("unknown majority tip blocks the depth floor", t_majority_unknown_blocks_advance)
    check("majority on ANOTHER fork blocks the depth floor (the wedge geometry)", t_majority_on_other_fork_blocks_advance)
    check("normal recovery respects the finality floor", t_normal_recovery_respects_floor)
    check("ESCALATED recovery crosses the floor, heaviest chain wins", t_escalated_recovery_crosses_floor)
    check("a lighter fork majority can never pin us", t_lighter_majority_can_never_pin)
    check("malformed peer statuses are skipped", t_malformed_statuses_skipped)
    check("a foreign-protocol donor is never selected", t_foreign_protocol_donor_excluded)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
