"""
Which height the dead-fork probe compares at (ops/peer_ops.probe_height_for).

WHY THIS EXISTS. `stranded_below_finality` asks peers directly for their block hash at a height we both
hold. If that height is chosen badly the whole check becomes decorative: below the fork point the two
chains share all history, so the probe can only ever answer "agree", and agreement VETOES the dead-fork
escape. A test that cannot fail carries no information, and neither does a probe that cannot disagree.

THE BUG THIS PINS, measured live on alphanet-15 on 2026-08-03. A 2-2 split opened at h=7143 and never
healed; the gap passed 290 blocks while every node cheerfully reported `stranded: false`. The cause was an
interaction between two individually-correct behaviours:

  1. A forked node REFUSES to self-finalize while the peer-majority tip is not on its chain. So .131's
     finalized height froze at 7107 — the last height it agreed on, necessarily BELOW the fork.
  2. _common_probe_height compared at the peer's FINALIZED height. Because of (1) that is guaranteed to sit
     on shared history, where agreement is structurally certain.

Measured on the running nodes:

    .131 finalized 7107 (frozen), tip 7430, fork point 7143, our finalized 7675
    probe at 7107  ->  ours 7674b0e9af9bdd00 == theirs 7674b0e9af9bdd00   AGREE    (vetoes the escape)
    probe at 7264  ->  ours e698a5192d4c56fd != theirs ba68e6bce9c84dc3   DISAGREE (fork is visible)

Every number below is one of those MEASURED values, not a value invented to match the code — the previous
fix in this area passed 15 tests and was inert in production precisely because its fake was built from the
same assumption as the code under test.

THE SAFETY PROPERTY, which is what makes this shippable: for a HEALTHY peer finalized == tip -
FINALITY_DEPTH, so max(finalized, tip - margin) is exactly the old value. The behaviour changes ONLY for a
peer whose finality has fallen further than `margin` behind its own tip — the frozen-finality fork this is
meant to catch. Ordinary reorg churn is bounded by max_rollbacks (40) < FINALITY_DEPTH (45), so it cannot
push a peer into the changed region or manufacture a false disagreement.

Run: python3 tests/test_probe_height.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_probeh_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops.peer_ops import probe_height_for
from protocol import FINALITY_DEPTH

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


M = FINALITY_DEPTH                      # the settle margin the caller passes

# ---- the exact live configuration that stayed wedged ------------------------------------------------
FORK = 7143                             # measured fork point
THEIR_FIN, THEIR_TIP, OUR_H = 7107, 7430, 7675      # measured from the running nodes

h = probe_height_for(THEIR_FIN, THEIR_TIP, OUR_H, M)
check("the wedged peer is probed ABOVE the fork point, where disagreement can show",
      h is not None and h > FORK)
check("...and NOT at its frozen finalized height, where agreement was guaranteed", h != THEIR_FIN)
check("the height is one the peer actually holds (at or below its tip)", h <= THEIR_TIP)
check("the height is one WE hold (at or below our own height)", h <= OUR_H)

# ---- THE SAFETY PROPERTY: a healthy peer is probed exactly where it always was -----------------------
# finalized trails the tip by FINALITY_DEPTH on a node whose finality is advancing normally.
for tip in (7720, 6420, 512):
    fin = tip - FINALITY_DEPTH
    check("a HEALTHY peer (tip=%d) is probed at its finalized height, unchanged behaviour" % tip,
          probe_height_for(fin, tip, tip + 100, M) == fin)

# ---- a peer BEHIND us is still capped at a height we can answer --------------------------------------
check("a peer far behind us is probed at its own settled height, not ours",
      probe_height_for(3000, 3045, 9999, M) == 3000)
check("our_height caps the choice when WE are the one behind",
      probe_height_for(7107, 7430, 7200, M) == 7200)

# ---- a fork SHALLOWER than the margin is deliberately NOT surfaced here ------------------------------
# That case is the ordinary reorg path's job (max_rollbacks=40 can bridge it); the destructive purge must
# not be armed by routine churn.
shallow_fin, shallow_tip = 7400, 7430   # finality only 30 behind: normal-ish, fork would be < margin deep
check("a peer whose finality trails by LESS than the margin is probed at its finalized height",
      probe_height_for(shallow_fin, shallow_tip, 9999, M) == shallow_fin)

# ---- degraded inputs must never raise or invent a height --------------------------------------------
check("both heights missing -> no usable probe height", probe_height_for(None, None, 7675, M) is None)
check("only a tip known -> tip minus the margin", probe_height_for(None, 7430, 9999, M) == 7430 - M)
check("only a finalized height known -> that height", probe_height_for(7107, None, 9999, M) == 7107)
check("a tip below the margin cannot yield a positive height",
      probe_height_for(None, M - 1, 9999, M) is None)
check("a zero/negative our_height yields nothing", probe_height_for(7107, 7430, 0, M) is None)
check("genesis-era peer is handled", probe_height_for(0, 0, 100, M) is None)

# ---- the choice is the MAXIMUM of the candidates, never the minimum ----------------------------------
# Picking the lower one is exactly the old bug; pin the direction explicitly.
check("frozen finality never wins over a settled tip-derived height",
      probe_height_for(THEIR_FIN, THEIR_TIP, OUR_H, M) == THEIR_TIP - M)

print()
print("ALL PASS — the probe compares where a fork can actually be seen, and healthy peers are untouched"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
