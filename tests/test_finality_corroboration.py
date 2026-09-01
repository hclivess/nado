"""
CORROBORATED DEPTH FINALITY — which peer signal is allowed to freeze this node's finality floor, driven
through the REAL CoreClient._depth_floor_corroborated (tests/test_depth_floor_corroboration.py pins the
same rules through a pure mirror; this one proves the method itself still implements them).

HISTORY, because every rule here was paid for live:
  * 2026-07-20: the guard read `majority_block_hash`, the Sybil-swingable plurality. Seven peers, seven
    distinct tips, a 14% "majority" on a foreign chain froze the floor for hours. Fixed by reading the
    objective `heaviest_block_hash`.
  * 2026-07-29 (betanet-13 h5924): a node alone on a fork mined unopposed, was its own heaviest, and
    corroborated ITSELF 50 blocks past the fork. Rule: an INDEPENDENT peer must advertise a tip on our
    canonical chain — our own tip is not evidence about our own tip. (This REVERSED the 2026-07-20 test's
    "a single stranger cannot freeze us": with no honest witness the floor now stays put, which is the
    safe direction — it only widens the honest-reorg window.)
  * 2026-07-30 (betanet-14): a minority clique corroborated itself. Rule: a peer claiming strictly MORE
    cumulative weight on a tip not on our chain — or one we cannot locate — vetoes.
  * 2026-08-19: a merely SLOW node never holds anyone's tip. Rule: a signed peer claim that its hash at
    OUR height equals our tip (the `_extends_us` probe) corroborates / lifts the veto.

Run: python3 tests/test_finality_corroboration.py
"""
import os
import sys
import traceback
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from loops.core_loop import CoreClient

fails = 0


def check(name, fn):
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


# our canonical chain: A(1) <- B(2) <- C(3), tip C. "F"/"G"/"H" are foreign, "O" is an orphan we hold.
CHAIN = {"A": 1, "B": 2, "C": 3, "O": 2}
CANON = {1: "A", 2: "B", 3: "C"}
ME = "10.0.0.1"


class _Cons:
    def __init__(self, pool, heaviest, weight_pool):
        self.block_hash_pool = pool
        self.heaviest_block_hash = heaviest
        self.weight_pool = weight_pool


def corroborated(pool, heaviest, weight_pool=None, our_weight=100, extends_us=False):
    """Drive the real method with our own chain lookups, config and prefix probes patched in.
    `extends_us` is what the (network) `_extends_us` probe would answer for every peer."""
    import loops.core_loop as CL
    real = (CL.get_block, CL.get_block_hash_by_number, CL.get_config)
    CL.get_block = lambda h: ({"block_number": CHAIN[h]} if h in CHAIN else None)
    CL.get_block_hash_by_number = lambda n: CANON.get(n)
    CL.get_config = lambda: {"ip": ME}
    try:
        c = CoreClient.__new__(CoreClient)
        c.consensus = _Cons(pool, heaviest, weight_pool or {})
        c.memserver = SimpleNamespace(latest_block={"cumulative_weight": our_weight}, ip=ME)
        c._same_genesis = lambda peer: True
        c._extends_us = lambda peer, budget: extends_us
        return c._depth_floor_corroborated()
    finally:
        CL.get_block, CL.get_block_hash_by_number, CL.get_config = real


def t_no_peers_is_solo():
    assert corroborated({}, None) is True, "solo/bootstrap must still advance"


def t_unknown_heaviest_does_not_block():
    """No weight opinion yet (fresh pool) — same as having no peers, rather than freezing by default."""
    assert corroborated({"p1": "F"}, heaviest=None) is True


def t_our_own_tip_is_not_evidence():
    """THE 2026-07-29 RULE. We are heaviest (mining alone on a fork) and no peer is on our chain: frozen."""
    assert corroborated({"p1": "F"}, "C") is False, "a lone forker corroborated itself"
    assert corroborated({ME: "C"}, "C") is False, "our own pool entry is not an independent witness"


def t_one_independent_witness_is_enough():
    """A single honest peer on our chain corroborates — a healthy node is not frozen by a stray forker."""
    assert corroborated({"lone": "F", "p2": "B"}, "C") is True


def t_lagging_peers_still_corroborate():
    """An ancestor of our tip is a peer one block behind a healthy producer, not a disagreement."""
    assert corroborated({"p1": "B"}, "B") is True
    assert corroborated({"p1": "A"}, "A") is True


def t_heavier_foreign_chain_still_blocks():
    """THE GUARD. A strictly heavier chain we do not hold means we are the minority fork — refusing to
    finalize is the entire point, and this must not regress."""
    assert corroborated({"p1": "F", "p2": "F"}, "F") is False


def t_orphan_heaviest_blocks():
    """We HAVE the block but it is not canonical for us — a different fork, not a lagging peer."""
    assert corroborated({"p1": "O"}, "O") is False


def t_THE_FRAGMENTED_FLEET_MUST_NOT_FREEZE_US():
    """THE 2026-07-20 REGRESSION. Seven peers, seven distinct tips, six foreign; OUR tip is objectively
    heaviest and one peer (p6) is on our chain. It must finalize."""
    pool = {"p1": "F", "p2": "G", "p3": "H", "p4": "F2", "p5": "G2", "p6": "C", "p7": "H2"}
    assert corroborated(pool, heaviest="C") is True, "a 14% plurality froze the floor"


def t_heavier_claim_off_our_chain_vetoes():
    """THE 2026-07-30 RULE. A witness on our chain does not help while a peer claims MORE weight on a tip
    that is not on our canonical chain (or that we cannot locate at all)."""
    assert corroborated({"p1": "F", "p2": "B"}, "C", weight_pool={"p1": 500}) is False, "foreign heavier tip"
    assert corroborated({"p2": "B"}, "C", weight_pool={"p9": 500}) is False, "unanswerable heavier claim"
    assert corroborated({"p1": "F", "p2": "B"}, "C", weight_pool={"p1": 50}) is True, "lighter claims never veto"


def t_prefix_probe_lifts_the_veto_and_corroborates_a_lagging_node():
    """THE 2026-08-19 RULE. A signed claim that the heavier peer's hash at OUR height is our tip proves we
    are a prefix of its chain: the veto lifts, and a slow node holding nobody's tip still corroborates."""
    assert corroborated({"p1": "F", "p2": "B"}, "C", weight_pool={"p1": 500}, extends_us=True) is True
    assert corroborated({"p1": "F"}, "F", weight_pool={"p1": 500}, extends_us=True) is True, \
        "behind on the SAME chain is not on a different chain"
    assert corroborated({"p1": "F"}, "F", weight_pool={"p1": 500}, extends_us=False) is False


if __name__ == "__main__":
    check("no peers is solo", t_no_peers_is_solo)
    check("unknown heaviest does not block", t_unknown_heaviest_does_not_block)
    check("our own tip is not evidence (lone forker frozen)", t_our_own_tip_is_not_evidence)
    check("one independent witness is enough", t_one_independent_witness_is_enough)
    check("lagging peers still corroborate", t_lagging_peers_still_corroborate)
    check("a heavier foreign chain STILL blocks", t_heavier_foreign_chain_still_blocks)
    check("an orphan heaviest blocks", t_orphan_heaviest_blocks)
    check("THE fragmented fleet must not freeze us", t_THE_FRAGMENTED_FLEET_MUST_NOT_FREEZE_US)
    check("a heavier claim off our chain vetoes", t_heavier_claim_off_our_chain_vetoes)
    check("the prefix probe lifts the veto / corroborates a lagging node",
          t_prefix_probe_lifts_the_veto_and_corroborates_a_lagging_node)
    print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
    sys.exit(1 if fails else 0)
