"""A node still catching up builds no system transaction (ops.peer_ops.behind_network).

h193750, 2026-09-22: a propagation guard built from a tip eight blocks stale was already in the past for the
rest of the network, so the tx was eligible on arrival wherever it landed first and five nodes rolled back
a block. The periodic system-tx slot (duty, auto-bond, auto-collect, announce) now waits until the node is
within `slack` blocks of the highest tip any peer advertises. Production is not gated: a lone node mints.

Run: python3 tests/test_behind_network.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_behind_")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops.peer_ops import behind_network

fails = []
def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond: fails.append(label)

pool = {"a": {"latest_block_height": 1000}, "b": {"latest_block_height": 1008}, "c": {"latest_block_height": "junk"}, "d": {}}
check(behind_network(pool, 1000), "eight blocks behind the best peer: catching up, no system tx")
check(not behind_network(pool, 1006), "within the slack (2) of the best peer: not behind")
check(not behind_network(pool, 1008), "at the best peer's tip: not behind")
check(not behind_network(pool, 1020), "ahead of every peer (lone producer, or peers lagging): not behind")
check(not behind_network({}, 1000), "no peers at all: not behind (a solo node keeps its duties)")
check(not behind_network({"c": {"latest_block_height": "junk"}, "d": {}}, 1000), "unreadable heights are skipped, not treated as ahead")
check(behind_network(pool, 1005, slack=2) and not behind_network(pool, 1005, slack=3), "slack is honoured exactly")

src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "loops", "core_loop.py")).read()
i = src.index("if behind_network(self.consensus.status_pool.copy(), _tip_h):")
block = src[i:src.index("self.maybe_prune_history()", i)]      # the gated slot, up to the first ungated call
for name in ("maybe_epoch_duty", "maybe_auto_bond", "maybe_auto_collect", "maybe_tpm_ready", "maybe_auto_register"):
    check(f"self.{name}()" in block, f"core_loop: {name} sits behind the catching-up gate")
check("self.maybe_prune_history()" not in block.split("self.maybe_tpm_ready()")[0], "core_loop: housekeeping is not gated")

print(("\nFAILED: " + "; ".join(fails)) if fails else "\nall checks passed")
sys.exit(1 if fails else 0)
