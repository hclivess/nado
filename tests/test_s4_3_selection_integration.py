import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_s43_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "index/producer_sets", "logs", "peers"):
    os.makedirs(os.path.expanduser(f"~/nado/{d}"), exist_ok=True)

import logging
logger = logging.getLogger("s43"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()
from protocol import B_MIN, GENESIS_BEACON, EPOCH_LENGTH
from ops.account_ops import create_account, get_bonded_registry
from ops.mining_ops import select_producer, compute_beacon, total_shares
from ops.block_ops import epoch_beacon, get_block_hash_by_number, index_block_number, save_block

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e: fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def t1():
    create_account("a", bonded=B_MIN)
    create_account("b", bonded=B_MIN * 5)
    create_account("c", bonded=B_MIN - 1)   # below the minimum bond -> ineligible
    create_account("d", bonded=0)
    reg = get_bonded_registry()
    assert set(reg) == {"a", "b"}, reg                      # only bonded >= B_MIN
    assert reg["a"]["bonded"] == B_MIN and reg["b"]["bonded"] == B_MIN * 5
    assert reg["a"]["fidelity"] is None                     # v1: no fidelity ramp
    assert total_shares(reg) == 1 + 5                       # split-neutral capped shares
check("get_bonded_registry filters by B_MIN; shares correct", t1)

def t2():
    # epochs 0-1 use the fixed GENESIS_BEACON (no finalized prior epoch yet)
    assert epoch_beacon(0) == GENESIS_BEACON and epoch_beacon(1) == GENESIS_BEACON
    # epoch 2 with no anchor block present -> deterministic fallback to GENESIS_BEACON
    assert epoch_beacon(2) == GENESIS_BEACON
    # index the anchor block at height (2-1)*EPOCH_LENGTH and the chained beacon kicks in
    anchor_h = (2 - 1) * EPOCH_LENGTH
    blk = {"block_number": anchor_h, "parent_hash": "0"*64, "block_hash": "6"*64, "block_timestamp": 1,
           "block_transactions": [], "block_creator": "a", "block_reward": 0, "child_hash": None,
           "cumulative_fees": 0, "chain_id": "x"}
    save_block(blk, logger=logger); index_block_number(blk)
    assert get_block_hash_by_number(anchor_h) == "6"*64
    assert epoch_beacon(2) == compute_beacon(GENESIS_BEACON, ["6"*64])
    assert epoch_beacon(2) != GENESIS_BEACON               # chained, not the constant
check("epoch_beacon: constant for epochs 0-1, chained anchor for epoch>=2", t2)

def t3():
    reg = get_bonded_registry()
    w = select_producer(reg, GENESIS_BEACON, slot=1)
    assert w in reg, w                                      # winner is an eligible bonded address
    assert select_producer(reg, GENESIS_BEACON, slot=1) == w  # deterministic
    winners = {select_producer(reg, GENESIS_BEACON, slot=s) for s in range(60)}
    assert winners and winners <= set(reg), winners        # never an ineligible address
check("select_producer over the registry+beacon is deterministic + only eligible addresses win", t3)

print(f"\n{'ALL S4.3 CHECKS PASSED' if fails==0 else str(fails)+' S4.3 CHECK(S) FAILED'}")
sys.exit(1 if fails else 0)
