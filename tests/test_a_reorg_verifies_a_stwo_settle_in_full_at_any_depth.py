"""A REORG VERIFIES A STWO SETTLE IN FULL AT ANY DEPTH (loops/core_loop.settle_proof_relaxed; zk audit 2026-11-02).

The settle-proof depth gate (protocol.SETTLE_PROOF_DEPTH_GATED) lets a node skip verifying a Stwo settle buried more than
FINALITY_DEPTH below the chain it knows exists, so catching up never replays every historic span. Apply marks the root
proven either way, and that marker lets settlement_justified accept the root with no quorum. Measured against peers alone,
a heavier fork — or the peers of a node they eclipse — could therefore bury a settle whose bundle nobody can verify under
46 blocks and have it marked proven on every node that reorged onto it. The relaxation is now for NEW territory only:

  * a block above every height this node has held, far below the reference, is relaxed (catch-up is unchanged);
  * a block at or below the high-water mark is never relaxed, however deep: it replaces chain this node judged itself;
  * a block near the reference is never relaxed, held or not (the old depth rule still applies on top);
  * the high-water mark is seeded from the tip the node started on, rises with every incorporated block, and a rollback
    (memserver.latest_block moving back) leaves it where it was;
  * the remote-block path decides depth through settle_proof_relaxed with that mark, and incorporate_block is what raises it.

Run: python3 tests/test_a_reorg_verifies_a_stwo_settle_in_full_at_any_depth.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-reorg-depth-")        # never the live database (assign, not setdefault)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from protocol import FINALITY_DEPTH                                          # noqa: E402
from loops.core_loop import CoreClient, settle_proof_relaxed as relaxed      # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


H = 150000
far = H + FINALITY_DEPTH + 500
check("catch-up: a block above every held height, far below the reference, is relaxed", relaxed(far, H, H - 1))
check("a reorg: a block at a height this node held is verified, however deep", not relaxed(far, H, H))
check("a reorg: a block well below the high-water mark is verified", not relaxed(far, H, H + 300))
check("a new block near the reference is verified (the depth rule still applies)", not relaxed(H + 10, H, H - 1))
check("exactly FINALITY_DEPTH below is not deep", not relaxed(H + FINALITY_DEPTH, H, H - 1))
check("no reference at all: never relaxed", not relaxed(0, H, 0))


class _Mem:
    latest_block = {"block_number": 9000}


c = CoreClient.__new__(CoreClient)
c.memserver = _Mem()
check("the high-water mark is seeded from the tip the node started on", c._held_high_water() == 9000)
c._held_hw = max(c._held_high_water(), 9001)                 # what incorporate_block does on block 9001
_Mem.latest_block = {"block_number": 8960}                   # a rollback of 41 blocks
check("a rollback does not lower the high-water mark", c._held_high_water() == 9001)
check("so the fork's blocks over the rolled-back range are verified in full",
      not any(relaxed(9001 + 10 * FINALITY_DEPTH, h, c._held_high_water()) for h in range(8961, 9002)))
check("and the first block past the old tip is new territory again", relaxed(9002 + 10 * FINALITY_DEPTH, 9002,
                                                                           c._held_high_water()))

src = open(os.path.join(ROOT, "loops", "core_loop.py")).read()
inc = src[src.index("    def incorporate_block("):]
inc = inc[:inc.index("\n    def ", 10)]
check("incorporate_block raises the high-water mark after it advances the tip",
      "self._held_hw = max(self._held_high_water(), int(block[\"block_number\"]))" in inc
      and inc.index("set_latest_block_info(latest_block=block") < inc.index("self._held_hw = max("))
check("only incorporate_block and the seed ever assign the mark",
      src.count("self._held_hw =") == 2)
check("the remote-block depth decision goes through settle_proof_relaxed with the high-water mark",
      "_deep = bool(remote) and settle_proof_relaxed(" in src and "int(block[\"block_number\"]), self._held_high_water())" in src)

print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILURES")
sys.exit(1 if FAILED else 0)
