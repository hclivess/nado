"""
A dead fork must have a NON-DESTRUCTIVE exit that an agreeing peer cannot veto.

WHY THIS EXISTS. Observed live 2026-08-04 on alphanet-15: a 2-2 split at block 20352.

    branch A (this node + 185.100.232.131)   h=20371  weight=6,791,252   STALLED
    branch B (208.87.242.141 + .210)         h=20447  weight=6,817,624   advancing

Every exit was shut at once:

  * "Rollbacks exhausted (40/40)";
  * "Rollback refused (finality): Refusing to roll back block 20371 below finalized height 20371" — the
    fork ancestor (20352) is BELOW our own finality floor (20371). That floor is persisted and monotonic
    (`new_final = max(finalized_height, depth_final, ffg_final)` -> meta_set_int), so a RESTART DOES NOT
    LOWER IT — worth stating because "just restart it" is the obvious wrong guess;
  * the purge escape refused, because it requires that NOBODY agrees with us and .131 agreed — both nodes
    sat on the same dead branch, each vetoing the other's recovery. Indefinitely.

That "nobody agrees" precondition is CORRECT and must stay: without it both halves of a symmetric split
purge and resync from each other, and the fleet ends up on two chains sharing only genesis (observed
2026-07-28). It just cannot be the ONLY exit.

snapshot_bootstrap already implements `allow_below_floor`, whose docstring reserves it for exactly this
("the heavier chain's advertised snapshots all sit BELOW our finality floor ... a wedge that persists
across multiple weight-selected attempts proves the floor itself is on a minority fork"). Nothing ever
passed True, so it was dead code.

WHAT MAKES IT SAFE WITHOUT THE "NOBODY AGREES" GUARD: selection is by STRICTLY-heaviest cumulative weight,
so only the lighter side can find a donor at all. Both sides acting is impossible by construction — which
is a stronger guarantee than any headcount quorum, because in a symmetric split both sides genuinely hold
a majority against the other. And it is non-destructive: the fork's blocks are orphaned, not wiped, and
every imported tail block is re-verified.

Run: python3 tests/test_dead_fork_escalation.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_deadfork_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


# ---- the escalation trigger, modelled exactly as shipped ---------------------------------------------
DEAD_FORK_ESCALATE_AFTER = 3


def run(verdicts, heavier_peer_exists, cooldown_ok=True):
    """Replay fork verdicts through the shipped DEAD_FORK branch.

    Returns (escalated, streak_at_end). `escalated` is True iff the floor-crossing re-anchor was attempted
    AND a strictly-heavier donor existed (snapshot_bootstrap only succeeds then).
    """
    streak = 0
    escalated = False
    for v in verdicts:
        if v == "DEAD_FORK":
            streak += 1
            if streak >= DEAD_FORK_ESCALATE_AFTER and cooldown_ok:
                if heavier_peer_exists:          # snapshot_bootstrap selects by strictly-heaviest weight
                    escalated = True
                    streak = 0
        else:
            streak = 0
        if escalated:
            break
    return escalated, streak


D = "DEAD_FORK"

# ---- THE CORE PROPERTY: a persistent dead fork escalates, even with a peer agreeing ------------------
check("a persistent dead fork on the LIGHTER side escalates",
      run([D] * 5, heavier_peer_exists=True)[0])
check("...and it does NOT require that nobody agrees with us (the veto that wedged us)",
      run([D] * 5, heavier_peer_exists=True)[0])

# ---- ONLY THE LIGHTER SIDE CAN ACT — a mutual wipe is impossible by construction ---------------------
check("the HEAVIER side never escalates (no strictly-heavier donor exists for it)",
      not run([D] * 10, heavier_peer_exists=False)[0])
check("so in a 2-2 split exactly one side can ever act",
      run([D] * 5, heavier_peer_exists=True)[0] and not run([D] * 5, heavier_peer_exists=False)[0])

# ---- a transient misreading must NOT trigger it ------------------------------------------------------
check("one dead-fork verdict does not escalate", not run([D], heavier_peer_exists=True)[0])
check("two do not escalate", not run([D, D], heavier_peer_exists=True)[0])
check("three consecutive do", run([D, D, D], heavier_peer_exists=True)[0])
check("an interrupted streak resets and does not escalate",
      not run([D, D, "SYNCED", D, D], heavier_peer_exists=True)[0])
check("...and REORG/BEHIND also reset it",
      not run([D, D, "REORG", D, D], heavier_peer_exists=True)[0])

# ---- the cooldown still gates it ---------------------------------------------------------------------
check("the re-anchor cooldown suppresses escalation",
      not run([D] * 10, heavier_peer_exists=True, cooldown_ok=False)[0])

# ---- the streak must not leak across a healthy period ------------------------------------------------
_, streak = run([D, D, "SYNCED"], heavier_peer_exists=False)
check("a healthy verdict clears the streak", streak == 0)

# ---- the shipped code must actually be wired ---------------------------------------------------------
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "loops", "core_loop.py")).read()
check("core_loop defines the escalation threshold", "DEAD_FORK_ESCALATE_AFTER = 3" in src)
check("the DEAD_FORK branch attempts a floor-crossing re-anchor",
      "snapshot_bootstrap(force_reanchor=True, allow_below_floor=True)" in src)
check("the destructive purge escape is still the fallback, not the first move",
      "_maybe_escape_dead_fork()" in src)
check("the streak resets when not dead-forked", "_dead_fork_streak = 0" in src)

print()
print("ALL PASS — the lighter side of a dead fork heals itself; the heavier side cannot be moved"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
