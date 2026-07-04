"""
Snapshot must carry the block_by_num / block_by_hash INDEX so a snapshot-synced node can resolve
get_block_hash_by_number for the epoch-beacon anchor ((epoch-1)*EPOCH_LENGTH), FFG/PoSW boundaries that sit
BEFORE the snapshot height. Before this fix those indexes were in _HISTORY_DBS (excluded), so a joined node
raised "epoch_beacon: finalized anchor block #N missing" and could not produce/verify a single block.

Run: python3 tests/test_snapshot_beacon.py
"""
import os, sys, tempfile, logging, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _fresh_home(p):
    h = tempfile.mkdtemp(prefix=p)
    os.environ["HOME"] = h
    for d in ("index", "blocks", "index/producer_sets", "logs", "peers"):
        os.makedirs(f"{h}/nado/{d}", exist_ok=True)
    return h

logger = logging.getLogger("snapbeacon"); logger.addHandler(logging.NullHandler())
fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok: fails += 1

# ---- DONOR: a chain with block_by_num populated past 2 epochs, plus some account state ----
_fresh_home("nado_snap_donor_")
from ops import kv_ops
from genesis import create_indexers
create_indexers()
from ops.snapshot_ops import build_snapshot, import_snapshot
from ops.block_ops import get_block_hash_by_number
from ops.account_ops import create_account, get_account
from protocol import EPOCH_LENGTH

TIP = 3 * EPOCH_LENGTH + 5                       # ~3 epochs of blocks
ANCHOR = (3 - 1) * EPOCH_LENGTH                  # beacon anchor for epoch 3 — sits BELOW the tip
for n in range(0, TIP + 1):
    kv_ops.block_index_put(n, f"{n:064x}")       # num -> hash
create_account("acct", balance=777)

manifest, chunks = build_snapshot(TIP, block_hash=f"{TIP:064x}", protocol=2, version="v")
donor_anchor = get_block_hash_by_number(ANCHOR)
check("donor resolves the beacon anchor hash", donor_anchor == f"{ANCHOR:064x}")

# ---- JOINER: fresh empty DB, import the snapshot, must now resolve the SAME anchor ----
_fresh_home("nado_snap_joiner_")
try:
    kv_ops._ENV = None  # force re-open against the new HOME
except Exception:
    pass
create_indexers()
check("joiner starts WITHOUT the anchor (no history yet)", get_block_hash_by_number(ANCHOR) is None)

ok = import_snapshot(manifest, chunks, logger=logger)
check("import_snapshot succeeded", ok)
check("joiner resolves the beacon anchor hash AFTER import (was the fork-causing failure)",
      get_block_hash_by_number(ANCHOR) == f"{ANCHOR:064x}")
check("joiner also has the tip index + carried account state",
      get_block_hash_by_number(TIP) == f"{TIP:064x}" and get_account("acct")["balance"] == 777)
# block BODIES / tx history are still excluded (only the num<->hash index is carried)
check("tx history DB still excluded from the snapshot", "tx" not in kv_ops.SNAPSHOT_DBS)

print(f"\n{'ALL SNAPSHOT-BEACON CHECKS PASSED' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
