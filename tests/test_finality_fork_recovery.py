"""
FINALITY-AWARE FORK CHOICE (loops/core_loop.finality_orphaned) — the fix for a node that forks onto a branch
the network rejects and can NEVER recover on its own.

THE BUG IT FIXES (observed live 2026-07-28). Fork choice was purely (cumulative_weight DESC, block_hash ASC).
Node 208.87.242.141 forked at h5627 and kept MINING its branch, so its weight kept growing and it computed
ITSELF as the canonical tip on every pass — `minority_block_consensus` returned False forever and it never
synced back. Its FFG stayed frozen at 5520 while the 3-node majority finalized past 5700. Recovery required an
operator to hand-run purge_resync + force_sync on that box; nothing in the node could heal it.

THE RULE. Weight measures work done; FINALITY measures agreement. If a quorum of same-protocol peers is
FFG-finalized strictly above us, our branch is an orphan no matter how heavy it is, so we sync back.

Run: python3 tests/test_finality_fork_recovery.py
"""
import os, sys, tempfile, traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_ffgfork_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

from loops.core_loop import finality_orphaned, FINALITY_ORPHAN_MIN_PEERS

fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1

PROTO = 7


def st(ffg, protocol=PROTO):
    return {"ffg_finalized": ffg, "protocol": protocol}


def t_reproduces_the_141_case():
    """The exact live situation: our ffg frozen at 5520, three peers finalized at 5700."""
    peers = [st(5700), st(5700), st(5700)]
    check("a node whose FFG is frozen while 3 peers finalize past it IS orphaned",
          finality_orphaned(peers, our_ffg=5520, min_protocol=PROTO) is True)


def t_healthy_node_not_orphaned():
    """The majority itself must never think it is orphaned."""
    check("a node finalized WITH its peers is not orphaned",
          finality_orphaned([st(5700), st(5700), st(5700)], our_ffg=5700, min_protocol=PROTO) is False)
    check("a node finalized AHEAD of its peers is not orphaned",
          finality_orphaned([st(5600), st(5650)], our_ffg=5700, min_protocol=PROTO) is False)
    check("no peers -> not orphaned (a lone node must keep running)",
          finality_orphaned([], our_ffg=100, min_protocol=PROTO) is False)


def t_lone_peer_cannot_trigger_it():
    """ANTI-SYBIL: one peer advertising a huge ffg must never talk us off our chain."""
    check("a single peer claiming higher finality is NOT enough",
          finality_orphaned([st(999999)], our_ffg=100, min_protocol=PROTO) is False)
    check(f"the quorum floor is {FINALITY_ORPHAN_MIN_PEERS} peers", FINALITY_ORPHAN_MIN_PEERS >= 2)
    check("two peers ARE enough",
          finality_orphaned([st(200), st(200)], our_ffg=100, min_protocol=PROTO) is True)


def t_foreign_protocol_ignored():
    """A peer on another network's finality is meaningless here (same gate the weight comparisons use)."""
    check("foreign-protocol peers do not count",
          finality_orphaned([st(9999, protocol=2), st(9999, protocol=2)], our_ffg=100,
                            min_protocol=PROTO) is False)
    check("one same-protocol + one foreign is still below quorum",
          finality_orphaned([st(9999), st(9999, protocol=2)], our_ffg=100, min_protocol=PROTO) is False)


def t_malformed_statuses_safe():
    check("missing ffg_finalized is treated as 0 (never orphans us)",
          finality_orphaned([{"protocol": PROTO}, {"protocol": PROTO}], our_ffg=100,
                            min_protocol=PROTO) is False)
    check("None ffg is safe", finality_orphaned([st(None), st(None)], our_ffg=0, min_protocol=PROTO) is False)
    check("non-dict entries are ignored",
          finality_orphaned(["junk", None, st(200), st(200)], our_ffg=100, min_protocol=PROTO) is True)
    check("our own None ffg is treated as 0",
          finality_orphaned([st(5), st(5)], our_ffg=None, min_protocol=PROTO) is True)


def t_equal_finality_is_not_orphaned():
    """Only STRICTLY higher finality counts — equal means we are on the same finalized chain."""
    check("equal ffg is not orphaned",
          finality_orphaned([st(5700), st(5700)], our_ffg=5700, min_protocol=PROTO) is False)


if __name__ == "__main__":
    try:
        t_reproduces_the_141_case()
        t_healthy_node_not_orphaned()
        t_lone_peer_cannot_trigger_it()
        t_foreign_protocol_ignored()
        t_malformed_statuses_safe()
        t_equal_finality_is_not_orphaned()
    except Exception as e:
        fails += 1; print(f"FAIL  exception: {e}"); traceback.print_exc()
    print("\nALL PASS — a finality-orphaned node now heals itself instead of needing an operator"
          if fails == 0 else f"\n{fails} FAILURES")
    sys.exit(1 if fails else 0)
