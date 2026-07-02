"""
Presence dividend — L1 reward split (doc/presence-dividend.md):
  open block  -> producer TIP (20%) + DIVIDEND_POOL (70%) + treasury (10%)
  bonded block-> producer (70%) + DIVIDEND_POOL (20%) + treasury (10%)   [bonded now shares too]
Plus revert-symmetry: apply then revert returns every balance to its prior value — verified BYTE-IDENTICALLY
across the whole KV env (not just the touched balances), so a rollback can never desync a single unit.

Run: python3 tests/test_dividend.py
"""
import os, sys, tempfile, logging, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_div_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "index/producer_sets", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logger = logging.getLogger("div"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import (split_open_block_reward, split_block_reward, DIVIDEND_POOL, TREASURY_ADDRESS,
                      TREASURY_BPS, OPEN_TIP_BPS, BPS_DENOM, EPOCH_LENGTH)
from ops import kv_ops
from ops.mining_ops import lane_of, epoch_of
from ops.block_ops import epoch_beacon
from ops.reward_ops import credit_block_reward, block_lane
from ops.account_ops import create_account, get_account
from ops.key_ops import generate_keys

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

R = 1_000_000_000        # 0.1 NADO block reward
def bal(a): acc = get_account(a); return acc["balance"] if acc else 0
def prod(a): acc = get_account(a); return acc["produced"] if acc else 0

# find an open slot and a bonded slot in epoch 0/1 (both use GENESIS_BEACON — no anchor needed)
OPEN_SLOT = BONDED_SLOT = None
for n in range(EPOCH_LENGTH):
    ln = lane_of(n, epoch_beacon(epoch_of(n)))
    if ln == "open" and OPEN_SLOT is None: OPEN_SLOT = n
    if ln == "bonded" and BONDED_SLOT is None: BONDED_SLOT = n

def t1_split_math():
    tip, div, tre = split_open_block_reward(R)
    assert tip + div + tre == R, "open split must sum to reward exactly"
    assert tre == R * TREASURY_BPS // BPS_DENOM, "treasury 10%"
    assert tip == R * OPEN_TIP_BPS // BPS_DENOM, "tip 20%"
    assert div == R - tre - tip, "dividend is the remainder (~70%)"
    pc, tc = split_block_reward(R); assert pc + tc == R, "bonded split sums to reward"
    assert OPEN_SLOT is not None and BONDED_SLOT is not None, "found both an open and a bonded slot"

def t2_open_block_credits_pool_and_reverts():
    a = generate_keys()["address"]; create_account(a, balance=0)
    tre0, div0 = bal(TREASURY_ADDRESS), bal(DIVIDEND_POOL)
    tip, div, tre = split_open_block_reward(R)
    block = {"block_number": OPEN_SLOT, "block_creator": a, "block_reward": R}
    assert block_lane(block) == "open"
    with kv_ops.write_txn(): credit_block_reward(block, logger=logger)
    assert bal(a) == tip, "producer gets only the tip on an open block"
    assert bal(DIVIDEND_POOL) == div0 + div, "the dividend accrues to the pool"
    assert bal(TREASURY_ADDRESS) == tre0 + tre, "treasury keeps 10%"
    assert prod(a) == tip, "produced metric tracks the tip"
    with kv_ops.write_txn(): credit_block_reward(block, logger=logger, revert=True)
    assert bal(a) == 0 and prod(a) == 0, "revert returns producer to prior exactly"
    assert bal(DIVIDEND_POOL) == div0 and bal(TREASURY_ADDRESS) == tre0, "revert returns pool + treasury exactly"

def t3_bonded_block_also_funds_the_dividend():
    from protocol import split_bonded_block_reward
    a = generate_keys()["address"]; create_account(a, balance=0)
    div0, tre0 = bal(DIVIDEND_POOL), bal(TREASURY_ADDRESS)
    pc, div, tre = split_bonded_block_reward(R)   # (producer 70%, dividend 20%, treasury 10%)
    block = {"block_number": BONDED_SLOT, "block_creator": a, "block_reward": R}
    assert block_lane(block) == "bonded"
    with kv_ops.write_txn(): credit_block_reward(block, logger=logger)
    assert bal(a) == pc, "bonded producer keeps the majority (70%)"
    assert bal(DIVIDEND_POOL) == div0 + div, "a bonded block now contributes its share to the dividend pool"
    assert bal(TREASURY_ADDRESS) == tre0 + tre, "treasury keeps 10%"
    with kv_ops.write_txn(): credit_block_reward(block, logger=logger, revert=True)
    assert bal(a) == 0, "revert returns the bonded producer to prior"
    assert bal(DIVIDEND_POOL) == div0 and bal(TREASURY_ADDRESS) == tre0, "revert returns pool + treasury exactly"

def t4_block_lane_is_deterministic():
    b = {"block_number": OPEN_SLOT, "block_creator": "x", "block_reward": R}
    assert block_lane(b) == block_lane(b), "same block -> same lane every call"

def _dump_env():
    """Snapshot EVERY (key,value) of EVERY sub-DB as raw bytes, in LMDB sorted order — two dumps compare
    byte-for-byte, so a rollback that leaves ANY unit out of place is caught."""
    env = kv_ops.get_env(); dbs = kv_ops._dbs(); out = {}
    with env.begin() as txn:
        for nm, db in dbs.items():
            with txn.cursor(db=db) as cur:
                out[nm] = [(bytes(k), bytes(v)) for k, v in cur]
    return out

def t5_credit_block_reward_rollback_is_byte_identical():
    # the strong guarantee: for BOTH lanes, credit_block_reward apply->revert returns the WHOLE env to its
    # exact prior bytes (accounts + produced + dividend pool + treasury), not just the balances we happened
    # to assert. Pre-fund every touched account so revert can't leave a fresh zero-row artifact.
    from ops.account_ops import create_account as _mk
    for slot in (OPEN_SLOT, BONDED_SLOT):
        a = generate_keys()["address"]
        _mk(a, balance=123); _mk(DIVIDEND_POOL, balance=7); _mk(TREASURY_ADDRESS, balance=11)
        block = {"block_number": slot, "block_creator": a, "block_reward": R}
        before = _dump_env()
        with kv_ops.write_txn(): credit_block_reward(block, logger=logger)
        assert _dump_env() != before, f"credit made no change on the {block_lane(block)} block?!"
        with kv_ops.write_txn(): credit_block_reward(block, logger=logger, revert=True)
        assert _dump_env() == before, f"{block_lane(block)} credit rollback is NOT byte-identical"

for name, fn in sorted(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
