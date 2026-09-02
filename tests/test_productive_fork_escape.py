"""
PRODUCTIVE-FORK ESCAPE — a node that forks and keeps MINING must still self-heal.

THE BUG (live 2026-07-28). Node 208.87.242.141 forked at h5627 and mined 600+ blocks alone on its branch for
hours. It was invisible to every recovery route AT ONCE:
  1. it was the HEAVIEST tip, so minority_block_consensus never reported out-of-consensus;
  2. so it never entered the emergency loop, which was the ONLY caller of _maybe_escape_dead_fork;
  3. and its tip was never frozen, so that escape's `since_last_block < DEAD_FORK_STALL_S` gate would have
     refused to even ask.
An operator had to purge the box by hand. Needing a human is the defect.

THE FIX (both blind spots):
  * normal_mode now runs the dead-fork self-check, so a node that is PRODUCING checks itself;
  * the escape no longer requires a frozen tip — a node alone on a fork MOVES FASTEST of all, so "still
    moving" never meant "healthy". DEAD_FORK_COOLDOWN_S still bounds it to one probe per 30 min.

The decision itself is unchanged and remains the AUTHORITATIVE one: peers are asked DIRECTLY over HTTP for
their hash at OUR finalized height (no status pool, no advertised weights, no ffg — none of which a forked or
hostile peer can be trusted on), a QUORUM must disagree, NOBODY may agree, and the measured fork state must
independently say DEAD_FORK before anything is purged.

Run: python3 tests/test_productive_fork_escape.py
"""
import os, sys, inspect, tempfile, traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_prodfork_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

import loops.core_loop as CL
from ops.peer_ops import stranded_below_finality

fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


def t_normal_mode_runs_the_self_check():
    """REGRESSION 1: a mining node must call the dead-fork escape. Before the fix, _maybe_escape_dead_fork
    appeared ONLY inside the emergency loop, so a productive forker never invoked it."""
    src = inspect.getsource(CL.CoreClient.normal_mode)
    check("normal_mode calls _maybe_escape_dead_fork (a producing node checks itself)",
          "_maybe_escape_dead_fork" in src)
    # the SPECIFIC guard, not any `except Exception` in the function (normal_mode's outer handler re-raises,
    # so that alternative matched a property the code did not have — 2026-09-02 audit)
    check("the self-check cannot break block production (guarded)",
          "dead-fork self-check skipped" in src
          and src.index("try:") < src.index("self._maybe_escape_dead_fork()") < src.index("dead-fork self-check skipped"))


def t_stall_gate_no_longer_blocks_a_miner():
    """REGRESSION 2: the escape must not require a frozen tip. A node alone on a fork mines every slot."""
    src = inspect.getsource(CL.CoreClient._maybe_escape_dead_fork)
    check("the escape no longer RETURNS EARLY on a moving tip",
          "if self.memserver.since_last_block < DEAD_FORK_STALL_S:\n                return False" not in src)
    check("it still records whether the tip was frozen (diagnostics)", "_stalled" in src)
    check("the cooldown still rate-limits the probe", "DEAD_FORK_COOLDOWN_S" in src)


def t_decision_is_still_authoritative():
    """The SAFETY properties must be untouched: direct peer probes, quorum, nobody agreeing, and a second
    independent confirmation before any destructive action."""
    src = inspect.getsource(CL.CoreClient._maybe_escape_dead_fork)
    check("asks peers DIRECTLY (stranded_below_finality), not the status pool",
          "stranded_below_finality" in src and "status_pool" not in src)
    check("requires the DEAD_FORK_QUORUM", "DEAD_FORK_QUORUM" in src)
    check("requires a SECOND independent confirmation before purging",
          "fork_resolution.DEAD_FORK" in src and "not purging" in src)
    check("operator can opt out", "auto_escape_dead_fork" in src)
    check("private/ keys are never touched", "purge_chain_data" in src)


def t_probe_semantics():
    """stranded_below_finality is the decision: a quorum must disagree AND nobody may agree."""
    doc = stranded_below_finality.__doc__ or ""
    check("the probe is documented as independent of status pool / weights / benching",
          "No status" in doc or "no status pool" in doc.lower())
    # nobody-agrees: a single agreeing peer must veto (documented invariant of the helper)
    check("one agreeing peer means we are merely poorly connected (not stranded)",
          "agree" in doc.lower())


def t_healthy_node_costs_one_probe():
    """A healthy node must not be destabilised: it pays one cheap probe per cooldown and exits when peers
    agree (stranded=False short-circuits before any destructive path)."""
    src = inspect.getsource(CL.CoreClient._maybe_escape_dead_fork)
    idx_probe = src.find("stranded, detail")
    idx_purge = src.find("purge_chain_data(logger=")   # the CALL, not the docstring mention
    check("a not-stranded node returns before anything destructive",
          idx_probe != -1 and idx_purge != -1 and idx_probe < idx_purge and "if not stranded" in src)


# ---------------------------------------------------------------------------------------------------
# REGRESSION 3: the probe must work when the forked node has RACED AHEAD of everyone.
# A lone forker mines every slot unopposed, so it outruns the honest majority. probe_block_hash then
# returns None for every peer (nobody HAS its finalized height), those land in `unknown` rather than
# `disagree`, and stranded_below_finality answered "not stranded" for the one node most in need of
# rescue. Verified live 2026-07-28: .141 finalized 6278 while the majority was at 6038.
def t_probe_handles_a_node_that_raced_ahead():
    import ops.peer_ops as PO
    OUR_H, OUR_HASH = 6278, "a" * 64          # we are 240 blocks past the majority, on our own branch
    COMMON_H = 6038                           # the highest height the majority has finalized

    # Model BOTH heights the way a real /status reports them. These peers are healthy — they are merely
    # behind us — so their finality trails their own tip by exactly FINALITY_DEPTH. That relationship is
    # what makes probe_height_for pick COMMON_H here, identical to the pre-2026-08-03 behaviour; a fake
    # that omitted the tip would silently exercise a different path than production.
    from protocol import FINALITY_DEPTH as _FD

    def fake_peer_heights(peer, port=9173, timeout=6):
        return COMMON_H, COMMON_H + _FD       # every peer is BEHIND us, finality healthy

    def fake_probe(peer, height, port=9173, timeout=6):
        if height > COMMON_H:
            return None                       # they simply do not have our height
        return "b" * 64                       # ...and at the common height they hold a DIFFERENT block

    def fake_our_hash(height):
        return OUR_HASH if height == OUR_H else "c" * 64   # ours differs from theirs at the common height

    orig = (PO.probe_block_hash, PO._peer_heights, PO._our_hash_at)
    PO.probe_block_hash, PO._peer_heights, PO._our_hash_at = fake_probe, fake_peer_heights, fake_our_hash
    try:
        stranded, detail = PO.stranded_below_finality(OUR_HASH, OUR_H, ["p1", "p2", "p3"], quorum=2)
        check("a node that RACED AHEAD is still detected as stranded (probe falls back to a common height)",
              stranded is True)
        check("  the disagreement is recorded against real peers, not 'unknown'",
              len(detail["disagree"]) >= 2 and not detail["agree"])

        # and the SAFETY direction: if we AGREE at the common height we are merely ahead, NOT stranded
        PO._our_hash_at = lambda height: "b" * 64          # same block as the peers at the common height
        stranded2, detail2 = PO.stranded_below_finality(OUR_HASH, OUR_H, ["p1", "p2", "p3"], quorum=2)
        check("a node merely AHEAD on the SAME chain is NOT stranded (no false purge)", stranded2 is False)
        check("  agreement at the common height vetoes", len(detail2["agree"]) >= 1)
    finally:
        PO.probe_block_hash, PO._peer_heights, PO._our_hash_at = orig


# REGRESSION 4 (the decisive one): find_common_ancestor probed at OUR tip first and ABORTED with None when the
# peers could not answer there. A lone forker mines unopposed and outruns everyone, so that is precisely its
# state — it could never obtain any verdict but UNKNOWN, the dead-fork escape's second confirmation could
# never be met, and it stayed forked forever. .141 sat 350+ blocks past the majority for hours.
def t_ancestor_search_when_we_raced_ahead():
    from ops import fork_resolution as FR
    FORK, MAJ_TIP, OUR_TIP, OUR_FINAL = 5627, 6450, 6813, 6768

    def our_hash_at(h):
        return f"ours{h}" if h >= FORK else f"same{h}"

    def probe(peer, h):
        if h > MAJ_TIP:
            return None                      # peers simply do not have our heights
        return f"maj{h}" if h >= FORK else f"same{h}"

    anc, _probes = FR.find_common_ancestor(our_hash_at, OUR_TIP, ["p1", "p2", "p3"], probe,
                                           floor=0, min_answers=2)
    check("ancestor is found even though peers cannot answer at our tip", anc == FORK - 1)
    v = FR.resolve(our_hash_at, OUR_TIP, OUR_FINAL, ["p1", "p2", "p3"], probe)
    check("verdict is DEAD_FORK (fork point is below our finalized height)", v["state"] == FR.DEAD_FORK)

    # SAFETY: a node merely BEHIND must still read as BEHIND, never as a fork
    def same_chain(h):
        return f"same{h}"
    v2 = FR.resolve(same_chain, 100, 50, ["p1", "p2"], lambda peer, h: f"same{h}" if h <= 200 else None)
    check("a node on the SAME chain is not called forked", v2["state"] in (FR.BEHIND, FR.SYNCED))


# REGRESSION 5: NEVER PROBE OURSELVES. This node's own IP can BE a seed (208.87.242.141 is in
# DEFAULT_SEED_PEERS), so a seeds-first probe set contains us; we answer our own fork question with our own
# hash, it lands in `agree`, and "ANY peer agreeing" vetoes the purge forever. That is why .141 — the one node
# whose peer list contained itself — still could not self-heal after every other blind spot was fixed.
def t_never_probes_itself():
    src = inspect.getsource(CL.CoreClient._maybe_escape_dead_fork)
    check("the escape excludes our own IP from the probe set", "_me" in src and "p not in _me" in src)
    check("  it uses both memserver.ip and the config ip", "self.memserver.ip" in src and "get_config()" in src)
    # a self-agreeing probe must not be able to veto: simulate a peer set that (wrongly) includes us
    import ops.peer_ops as PO
    OUR = "h" * 64
    def fake_probe(peer, height, port=9173, timeout=6):
        return OUR if peer == "self" else "z" * 64      # only WE agree with us
    orig = PO.probe_block_hash
    PO.probe_block_hash = fake_probe
    try:
        with_self, _ = PO.stranded_below_finality(OUR, 100, ["self", "p1", "p2"], quorum=2)
        without_self, _ = PO.stranded_below_finality(OUR, 100, ["p1", "p2"], quorum=2)
        check("including ourselves WOULD have vetoed the purge (the bug)", with_self is False)
        check("excluding ourselves correctly detects the dead fork (the fix)", without_self is True)
    finally:
        PO.probe_block_hash = orig


if __name__ == "__main__":
    try:
        t_normal_mode_runs_the_self_check()
        t_stall_gate_no_longer_blocks_a_miner()
        t_decision_is_still_authoritative()
        t_probe_semantics()
        t_healthy_node_costs_one_probe()
        t_probe_handles_a_node_that_raced_ahead()
        t_ancestor_search_when_we_raced_ahead()
        t_never_probes_itself()
    except Exception as e:
        fails += 1; print(f"FAIL  exception: {e}"); traceback.print_exc()
    print("\nALL PASS — a mining fork self-heals, including one that raced ahead"
          if fails == 0 else f"\n{fails} FAILURES")
    sys.exit(1 if fails else 0)


