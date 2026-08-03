"""
SUSTAINED ISOLATION overrides the "heavier side does not yield" veto (loops/core_loop).

A node that forks alone is ALWAYS the heavier side — it wins every slot unopposed — so the weight
tie-break, which exists to stop both halves of an even split purging each other, systematically protects
the one node that most needs to yield. The `unanimous` escape exists for that, but it requires EVERY peer
asked to disagree, so a single peer that never answers makes it permanently False.

Both hatches then shut at once. Measured live on alphanet-15 (2026-08-03), node 185.100.232.131:

    stranded=True  fork_state=dead_fork  agree=[]  disagree=2  peers_asked=3
    unanimous=False        our_weight=1003275 > their_weight=984218

It had been forked for hours with its lead WIDENING, and would never have recovered.

The fix is time, not a looser quorum: require the SAME isolated verdict continuously for
DEAD_FORK_ALONE_S. This file pins the two properties that make that safe.

Run: python3 tests/test_dead_fork_isolation.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_dfiso_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loops.core_loop import isolation_holds, isolation_since
from protocol import DEAD_FORK_QUORUM, DEAD_FORK_ALONE_S, DEAD_FORK_COOLDOWN_S

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


Q = DEAD_FORK_QUORUM

# ---- isolation_holds: only ANSWERS count ------------------------------------------------------------
check("alone when a quorum disagrees and nobody agrees",
      isolation_holds([], ["a", "b"], Q) is True)
check("NOT alone when even one peer agrees (this is the symmetric-split guard)",
      isolation_holds(["c"], ["a", "b"], Q) is False)
check("NOT alone below the disagree quorum", isolation_holds([], ["a"], Q) is False)

# THE BUG THIS FIXES: silence is not agreement. The live node had 3 peers asked, 2 disagreeing, 0 agreeing
# and 0 unknown — the third simply never answered, and counting it against unanimity vetoed recovery.
check("a peer that never answered does NOT count as agreement",
      isolation_holds([], ["a", "b"], Q) is True)

# ---- isolation_since: the clock must be CONTINUOUS ---------------------------------------------------
t0 = 1_000_000
check("clock starts on first isolated probe", isolation_since(None, True, t0) == t0)
check("clock is KEPT (not restarted) while isolation holds",
      isolation_since(t0, True, t0 + DEAD_FORK_COOLDOWN_S) == t0)
check("clock CLEARS the moment any peer agrees", isolation_since(t0, False, t0 + 10) is None)
check("and must start over afterwards — a broken run cannot be resumed",
      isolation_since(None, True, t0 + 99) == t0 + 99)

# ---- the override fires only after a sustained window ------------------------------------------------
def sustained(since, now):
    return bool(since) and (now - since) >= DEAD_FORK_ALONE_S


check("does NOT fire immediately (a single probe is never decisive)",
      sustained(isolation_since(None, True, t0), t0) is False)
check("does NOT fire one probe later", sustained(t0, t0 + DEAD_FORK_COOLDOWN_S) is False)
check(f"DOES fire once isolation has held for DEAD_FORK_ALONE_S ({DEAD_FORK_ALONE_S}s)",
      sustained(t0, t0 + DEAD_FORK_ALONE_S) is True)

# A transient partition: isolated, then someone answers, then isolated again. The window restarts, so the
# node does not purge on the strength of two disconnected episodes.
_since = isolation_since(None, True, t0)
_since = isolation_since(_since, False, t0 + DEAD_FORK_COOLDOWN_S)          # a peer agreed -> reset
_since = isolation_since(_since, True, t0 + 2 * DEAD_FORK_COOLDOWN_S)      # isolated again, fresh clock
check("a transient partition cannot accumulate toward the override",
      sustained(_since, t0 + DEAD_FORK_ALONE_S) is False)
check("...and the fresh window still fires on its own merits later",
      sustained(_since, t0 + 2 * DEAD_FORK_COOLDOWN_S + DEAD_FORK_ALONE_S) is True)

# ---- the window must be long enough to span several independent probes -------------------------------
check(f"the window spans multiple probes ({DEAD_FORK_ALONE_S // DEAD_FORK_COOLDOWN_S} at "
      f"{DEAD_FORK_COOLDOWN_S}s cadence), so one bad round cannot trigger a purge",
      DEAD_FORK_ALONE_S >= 2 * DEAD_FORK_COOLDOWN_S)

print()
print("ALL PASS — silence is not agreement, and only UNBROKEN isolation overrides the weight veto"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
