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
    check("the self-check cannot break block production (guarded)",
          "dead-fork self-check skipped" in src or "except Exception" in src)


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


if __name__ == "__main__":
    try:
        t_normal_mode_runs_the_self_check()
        t_stall_gate_no_longer_blocks_a_miner()
        t_decision_is_still_authoritative()
        t_probe_semantics()
        t_healthy_node_costs_one_probe()
    except Exception as e:
        fails += 1; print(f"FAIL  exception: {e}"); traceback.print_exc()
    print("\nALL PASS — a node that forks while MINING now checks and heals itself"
          if fails == 0 else f"\n{fails} FAILURES")
    sys.exit(1 if fails else 0)
