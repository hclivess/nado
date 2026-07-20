"""
CORROBORATED DEPTH FINALITY — which peer signal is allowed to freeze this node's finality floor.

WHY THIS EXISTS (live, 2026-07-20): `_depth_floor_corroborated` gated the depth floor on
`consensus.majority_block_hash`. consensus_loop.py describes that field, in its own words, as "the
Sybil-swingable plurality … replaced [for] the BLOCK chain [by] OBJECTIVE heaviest-cumulative_weight
fork-choice … (Plurality is kept for the tx-pool / block-producer pools, WHICH ARE NOT THE CHAIN
FORK-CHOICE)". Finality is a chain decision, so it was reading precisely the signal that had been retired
for chain decisions.

The fleet fragmented: seven peers advertising seven DISTINCT tips, six on chains this node holds no blocks
for. The "majority" was a ONE-VOTE plurality (14%) on a foreign chain, corroboration failed, and the floor
sat frozen for hours while the tip advanced normally. Cheap to do on purpose, too: one peer advertising a
tip nobody else shares could freeze any node's finality.

Fixed by reading `heaviest_block_hash` — objective, weight-argmax, already excluding benched peers and
rejected tips, always including our own tip. These tests pin BOTH directions: the fragmentation case must
finalize, and a genuinely heavier foreign chain must still block it (that guard is what stops a node alone
on a minority fork from self-finalizing it).

Run: python3 tests/test_finality_corroboration.py
"""
import os
import sys
import traceback

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


class _Cons:
    def __init__(self, pool, heaviest, majority):
        self.block_hash_pool = pool
        self.heaviest_block_hash = heaviest
        self.majority_block_hash = majority


def corroborated(pool, heaviest, majority="ignored"):
    """Drive the real method with our own chain-lookup functions patched in."""
    import loops.core_loop as CL
    real_gb, real_gh = CL.get_block, CL.get_block_hash_by_number
    CL.get_block = lambda h: ({"block_number": CHAIN[h]} if h in CHAIN else None)
    CL.get_block_hash_by_number = lambda n: CANON.get(n)
    try:
        c = CoreClient.__new__(CoreClient)
        c.consensus = _Cons(pool, heaviest, majority)
        return c._depth_floor_corroborated()
    finally:
        CL.get_block, CL.get_block_hash_by_number = real_gb, real_gh


def t_no_peers_is_solo():
    assert corroborated({}, None) is True, "solo/bootstrap must still advance"


def t_we_are_heaviest():
    assert corroborated({"p1": "F"}, "C") is True, "our own tip as heaviest must corroborate"


def t_heavier_foreign_chain_still_blocks():
    """THE GUARD. A strictly heavier chain we do not hold means we are the minority fork — refusing to
    finalize is the entire point, and this must not regress."""
    assert corroborated({"p1": "F", "p2": "F"}, "F") is False


def t_orphan_heaviest_blocks():
    """We HAVE the block but it is not canonical for us — a different fork, not a lagging peer."""
    assert corroborated({"p1": "O"}, "O") is False


def t_lagging_peers_still_corroborate():
    """An ancestor of our tip is a peer one block behind a healthy producer, not a disagreement."""
    assert corroborated({"p1": "B"}, "B") is True
    assert corroborated({"p1": "A"}, "A") is True


def t_THE_FRAGMENTED_FLEET_MUST_NOT_FREEZE_US():
    """THE REGRESSION. Seven peers, seven distinct tips, six of them foreign; the plurality is one vote on
    a chain we do not hold, while OUR tip is objectively heaviest. Old behaviour: frozen finality. It must
    now finalize."""
    pool = {"p1": "F", "p2": "G", "p3": "H", "p4": "F2", "p5": "G2", "p6": "C", "p7": "H2"}
    assert corroborated(pool, heaviest="C", majority="G2") is True, "a 14% plurality froze the floor"


def t_a_single_stranger_cannot_freeze_us():
    """The DoS shape: one peer advertising a tip nobody shares. With plurality it could deny corroboration;
    with weight it cannot, because it is not heaviest."""
    assert corroborated({"lone": "F"}, heaviest="C", majority="F") is True


def t_unknown_heaviest_does_not_block():
    """No weight opinion yet (fresh pool) — same as having no peers, rather than freezing by default."""
    assert corroborated({"p1": "F"}, heaviest=None, majority="F") is True


if __name__ == "__main__":
    check("no peers is solo", t_no_peers_is_solo)
    check("we are heaviest", t_we_are_heaviest)
    check("a heavier foreign chain STILL blocks", t_heavier_foreign_chain_still_blocks)
    check("an orphan heaviest blocks", t_orphan_heaviest_blocks)
    check("lagging peers still corroborate", t_lagging_peers_still_corroborate)
    check("THE fragmented fleet must not freeze us", t_THE_FRAGMENTED_FLEET_MUST_NOT_FREEZE_US)
    check("a single stranger cannot freeze us", t_a_single_stranger_cannot_freeze_us)
    check("unknown heaviest does not block", t_unknown_heaviest_does_not_block)
    print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
    sys.exit(1 if fails else 0)
