"""One sync donor cannot switch off settle-proof verification (loops/core_loop.settle_depth_reference).

The depth gate (protocol.SETTLE_PROOF_DEPTH_GATED) skips the STARK check for blocks more than FINALITY_DEPTH below the
reference height. The reference used to be max(fetched-batch height, mesh median): the batch height is one donor's claim,
recorded before any of its blocks is verified, so a donor advertising tall blocks made every block "deep".

  * a donor's tall claim alone never opens the gate (the honest mesh median caps it);
  * a lying mesh majority alone never opens it while the donor's batch says the chain is short;
  * when both agree the chain is far ahead, a block that far behind is deep (catch-up still skips the re-verification);
  * with no batch height the mesh median alone decides, as before;
  * the depth decision in the remote-block path goes through this function.

Run: python3 tests/test_one_donor_cannot_skip_settle_proof_checks.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-depth-ref-")       # never the live database (assign, not setdefault)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from protocol import FINALITY_DEPTH                                    # noqa: E402
from loops.core_loop import settle_depth_reference as ref              # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


def deep(known, median, h):
    return ref(known, median) - h > FINALITY_DEPTH


H = 150000
check("a donor claiming a tall chain alone does not make a block deep", not deep(10 ** 9, H + 3, H))
check("a lying mesh alone does not make it deep while the donor's batch is short", not deep(H + 5, 10 ** 9, H))
check("donor and mesh both far ahead: the block is deep (catch-up keeps skipping)", deep(H + 500, H + 480, H))
check("no batch height: the mesh median decides, as before", deep(0, H + 500, H) and not deep(0, H + 10, H))
check("no information at all: never deep", not deep(0, 0, H))

src = open(os.path.join(ROOT, "loops", "core_loop.py")).read()
check("the remote-block depth decision uses settle_depth_reference, not max()",
      "settle_depth_reference(getattr(self, \"_known_tip_height\", 0), _best_peer)" in src
      and "max(int(getattr(self, \"_known_tip_height\", 0)), _best_peer)" not in src)

print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILURES")
sys.exit(1 if FAILED else 0)
