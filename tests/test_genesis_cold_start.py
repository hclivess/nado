"""THE REROLL RACE — a node must not mine block 1 of a fresh chain while it is merely EARLY.

This is the defect that split alphanet-13, reproduced as a unit test so the alphanet-14 reroll cannot repeat
it. At a reroll every node purges and restarts, but not at the same instant. On 2026-07-28 185.100.232.5 came
back roughly four minutes ahead of the rest, found an empty peer table, and began mining from the shared
genesis alone. Four minutes was enough to carry it past the 45-block finality depth, so neither branch could
roll back to the other and the fleet stayed split until the next reroll.

What makes this worth its own gate is that EVERY other production gate is blind to it by construction:

  * the caught-up gate (peer_claims_heavier_tip) refuses to mint while a peer advertises a heavier tip — but
    at a reroll every node is at height 0 and no tip is heavier than any other;
  * the peer-count gate (len(peers) >= min_peers) is exactly the one an operator sets to 0 to allow solo
    production, and min_peers = 0 is the live setting on more than one fleet node. With it, an EMPTY peer
    table passes.

So both gates say "go" precisely when the node is least entitled to. The distinction the new gate draws is
between "no peers configured" (genuinely standalone — produce) and "peers configured, none reached yet"
(early — wait), and it applies at height 0 only.

The checks below pin BOTH directions. A gate that only ever blocks would stop the chain from ever starting,
which is a worse outage than the fork it prevents — so the release path (mesh up) and the bounded escape
(quiet period expired) matter just as much as the block.
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol as P
from loops.core_loop import CoreClient

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


class _Log:
    def warning(self, *a, **k): pass
    def info(self, *a, **k): pass
    def error(self, *a, **k): pass


def _node(height, peers, waited_s, ip="10.0.0.9"):
    """A stand-in carrying only the fields the gate reads — the real CoreClient is a Thread with a live
    memserver, and instantiating one would test the harness rather than the rule."""
    ms = types.SimpleNamespace(
        latest_block={"block_number": height},
        start_time=_NOW - waited_s,
        ip=ip,
    )
    return types.SimpleNamespace(memserver=ms, logger=_Log())


from config import get_timestamp_seconds
_NOW = get_timestamp_seconds()

gate = CoreClient._genesis_cold_start_blocked

# ---------------------------------------------------------------- THE RACE ITSELF
# height 0, seeds baked in (DEFAULT_SEED_PEERS is non-empty), nobody reached, restarted seconds ago.
check(gate(_node(0, [], 5), []) is True,
      "at height 0 with NO peers reached and seeds configured, the first block is NOT minted "
      "(this is the exact state 185.100.232.5 was in when it forked alphanet-13)")

check(gate(_node(0, ["1.2.3.4"], 5), ["1.2.3.4"]) is True,
      f"one peer is still not a mesh — {P.GENESIS_QUIET_MIN_PEERS} are required to release the gate early")

# ---------------------------------------------------------------- THE RELEASE PATHS (must not stall a fleet)
peers2 = ["1.2.3.4", "5.6.7.8"]
check(gate(_node(0, peers2, 5), peers2) is False,
      f"{P.GENESIS_QUIET_MIN_PEERS} contacted peers release the gate immediately — the normal reroll path, "
      f"where every node starts together within seconds")

check(gate(_node(0, [], P.GENESIS_QUIET_S + 1), []) is False,
      f"after GENESIS_QUIET_S ({P.GENESIS_QUIET_S}s) a node with no peers produces anyway — a genuinely "
      f"isolated node must never be bricked, only delayed once")

# ---------------------------------------------------------------- SCOPE: height 0 ONLY
for h in (1, 2, 45, 5000):
    check(gate(_node(h, [], 5), []) is False,
          f"at height {h} the gate is inert — once the chain has a block, fork choice and the caught-up "
          f"gate govern normally")

# ---------------------------------------------------------------- a standalone deployment is not "early"
_real_seeds = P and None
import ops.peer_ops as PO
_saved = PO.DEFAULT_SEED_PEERS
try:
    PO.DEFAULT_SEED_PEERS = []
    os.environ.pop("NADO_SEED_PEERS", None)
    check(gate(_node(0, [], 5), []) is False,
          "with NO seed peers configured at all, a node is standalone rather than early and produces at once")
finally:
    PO.DEFAULT_SEED_PEERS = _saved

# ---------------------------------------------------------------- a node must never be blocked by ITSELF
# This node's own IP can BE a seed (208.87.242.141 is in DEFAULT_SEED_PEERS). If the gate counted that as
# "a seed I have not reached", such a node would wait out the full quiet period at every single reroll.
_self_ip = _saved[0] if _saved else "10.0.0.9"
try:
    PO.DEFAULT_SEED_PEERS = [_self_ip]
    check(gate(_node(0, [], 5, ip=_self_ip), []) is False,
          "a node whose only configured seed is ITSELF is standalone, not early (a seed node must not wait "
          "for itself at every reroll)")
finally:
    PO.DEFAULT_SEED_PEERS = _saved

# ---------------------------------------------------------------- the gate must never stop a healthy chain
broken = types.SimpleNamespace(memserver=None, logger=_Log())
check(gate(broken, []) is False,
      "a gate that raises internally allows production rather than halting the node")

# ---------------------------------------------------------------- the constant must actually cover the event
check(P.GENESIS_QUIET_S >= 300,
      f"GENESIS_QUIET_S ({P.GENESIS_QUIET_S}s) exceeds the ~4 min restart stagger that caused the split")

print()
if fails:
    print(f"{len(fails)} CHECK(S) FAILED:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("ALL GENESIS COLD-START CHECKS PASSED")
