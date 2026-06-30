"""
Beacon fail-loud unit checks (#18, security step 4).

epoch_beacon: epochs 0-1 legitimately use GENESIS_BEACON; epoch>=2 chains it with the FINALIZED
anchor (first block of the prior epoch); and a MISSING anchor now RAISES (never silently substitutes
GENESIS_BEACON, which would fork the producer set for a whole epoch).
"""
import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_b4_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(os.path.expanduser(f"~/nado/{d}"), exist_ok=True)

from genesis import create_indexers
create_indexers()

from ops import kv_ops
from ops.block_ops import epoch_beacon
from ops.mining_ops import compute_beacon
from protocol import GENESIS_BEACON, EPOCH_LENGTH

fails = 0
def check(name, fn):
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def t1():
    assert epoch_beacon(0) == GENESIS_BEACON
    assert epoch_beacon(1) == GENESIS_BEACON
check("epochs 0-1 use GENESIS_BEACON (no finalized prior epoch yet)", t1)


def t2():
    anchor_height = (2 - 1) * EPOCH_LENGTH  # 60
    anchor_hash = "a" * 64
    kv_ops.block_index_put(anchor_height, anchor_hash)
    assert epoch_beacon(2) == compute_beacon(GENESIS_BEACON, [anchor_hash]), "epoch>=2 must chain the anchor"
check("epoch>=2 chains GENESIS_BEACON with the finalized anchor hash", t2)


def t3():
    # epoch 3's anchor is block (3-1)*60 = 120, which we never indexed -> must RAISE, not substitute
    raised = False
    try:
        epoch_beacon(3)
    except ValueError:
        raised = True
    assert raised, "a missing finalized anchor must RAISE (fail-loud), never return GENESIS_BEACON"
check("epoch>=2 with a MISSING anchor raises (fail-loud, no silent fallback)", t3)


print(f"\n{'ALL BEACON CHECKS PASSED' if not fails else str(fails) + ' FAILURE(S)'}")
sys.exit(1 if fails else 0)
