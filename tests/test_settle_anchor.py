"""The settle quorum cannot be captured by a small bond after an honest stall (review 2026-09-25).

The activity window counted validators who attested within SETTLE_ACTIVITY_CURSORS of the HIGHEST attested cursor, and
any bonded validator can push that to the block height. Once honest settlers fell a window behind (an exec stall), one
B_MIN bond was the entire active set and justified a fabricated root, which then pays exit claims from the escrows.
The window is anchored at the cursor reached by validators holding more than a third of recently attesting stake
(gen 25 gated this at SETTLE_ANCHOR_HEIGHT; from gen 26 it held from cursor 1 and the gate was deleted after the
betanet-8 reroll — only a namespace whose top cursor is 0 keeps the old window, and no stall can happen there), so the stalled honest committee stays in the denominator. The inactivity leak still works: a validator
that stops attesting while the rest continue drops out; a committee silent past SETTLE_ANCHOR_LONG_CURSORS leaves too.

Run: python3 tests/test_settle_anchor.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-settle-anchor-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import protocol as P
from ops import settlement_ops as SO, kv_ops
from protocol import B_MIN, SETTLE_ACTIVITY_CURSORS as W

fails = []
def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond: fails.append(name)

REG = {"honest1": {"bonded": 600 * B_MIN}, "honest2": {"bonded": 400 * B_MIN}, "attacker": {"bonded": B_MIN}}
FAKE, GOOD = "ff" * 32, "aa" * 32


def justified(att, cursor, root):
    kv_ops.settlement_max_cursor = lambda ns: max(c for c, _, _ in att)
    kv_ops.settlement_validators_since = lambda ns, f: {v for c, v, _ in att if c >= f}
    kv_ops.settlement_last_cursors = lambda ns, f: {v: max(c for c, vv, _ in att if vv == v and c >= f)
                                                    for v in {vv for c, vv, _ in att if c >= f}}
    kv_ops.settlements_for_cursor = lambda ns, c: [(v, r) for cc, v, r in att if cc == c]
    kv_ops.settlement_proven = lambda *x: False
    return SO.settlement_justified("default", cursor, root, REG)


STALL = 500_000
honest = [(STALL - 60, "honest1", GOOD), (STALL, "honest1", GOOD), (STALL, "honest2", GOOD)]
h = STALL + W + 1
att = honest + [(h, "attacker", FAKE)]
check("the anchor has no gate left", not hasattr(P, "SETTLE_ANCHOR_HEIGHT"))
check("THE FINDING, closed: one bond cannot capture the quorum after a stall", not justified(att, h, FAKE))
check("...and stays refused however far the attacker pushes the top",
      not justified(honest + [(STALL + 50_000, "attacker", FAKE)], STALL + 50_000, FAKE))
check("honest settlement at the stall cursor still justifies", justified(honest, STALL, GOOD))
live = [(c, v, GOOD) for c in range(STALL, STALL + 3 * W, 60) for v in ("honest1", "honest2")]
check("normal honest progression justifies at the top", justified(live, STALL + 3 * W - 60, GOOD))
leak = ([(c, "honest1", GOOD) for c in range(STALL, STALL + 3 * W, 60)] + [(STALL, "honest2", GOOD)])
check("the leak still works: honest2 goes dark, honest1 (60% of stake) alone justifies later cursors",
      justified(leak, STALL + 3 * W - 60, GOOD))
far = STALL + P.SETTLE_ANCHOR_LONG_CURSORS + W + 10
_gate = P.SETTLE_STAKE_FLOOR_HEIGHT
P.SETTLE_STAKE_FLOOR_HEIGHT = 1 << 62                   # the gen-27 rule: no stake floor
check("gen 27: a committee silent past SETTLE_ANCHOR_LONG_CURSORS no longer blocks (the documented bound)",
      justified(honest + [(far, "attacker", FAKE)], far, FAKE))
# THE LONE-SETTLER DRAIN (audit 2026-09-25 HIGH): that bound handed the whole quorum to one B_MIN bond. From
# SETTLE_STAKE_FLOOR_HEIGHT (1 at the reroll) the attester also needs 1/16 of ALL bonded stake, which silence cannot
# shrink — tests/test_lone_settler_cannot_settle.py is the end-to-end reproduction.
P.SETTLE_STAKE_FLOOR_HEIGHT = 1
check("from the stake floor: the lone bond past the long silence is refused",
      not justified(honest + [(far, "attacker", FAKE)], far, FAKE))
check("from the stake floor: the honest committee still justifies", justified(honest, STALL, GOOD))
P.SETTLE_STAKE_FLOOR_HEIGHT = _gate
print("ALL PASS" if not fails else f"{len(fails)} FAILURES")
sys.exit(1 if fails else 0)
