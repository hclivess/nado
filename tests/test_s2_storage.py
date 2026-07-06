import os, sys, tempfile, traceback
home = tempfile.mkdtemp(prefix="nado_s2_")
os.environ["HOME"] = home
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{home}/nado/{d}", exist_ok=True)

import logging
logger = logging.getLogger("s2"); logger.addHandler(logging.NullHandler())

from genesis import create_indexers
create_indexers()

from ops.account_ops import change_balance, increase_produced_count, get_account
from ops.block_ops import set_latest_block_info, set_earliest_block_info, get_block_ends_info, save_block
from rollback import rollback_one_block, MissingParentError

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e: fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def t1():
    """Prove change_balance credits and debits correctly in single statements."""
    change_balance("alice", 1000, logger=logger)
    assert get_account("alice")["balance"] == 1000
    change_balance("alice", -400, logger=logger)
    assert get_account("alice")["balance"] == 600
check("change_balance credit/debit (single-statement)", t1)

def t2():
    """Prove an overdraw raises AssertionError and leaves the balance untouched (fails closed)."""
    try:
        change_balance("alice", -10_000, logger=logger); raise RuntimeError("overdraw accepted")
    except AssertionError:
        pass
    assert get_account("alice")["balance"] == 600, "balance mutated on rejected overdraw"
check("overdraw fails closed with NO mutation", t2)

def t3():
    """Prove change_balance revert=True exactly undoes a debit (symmetric revert)."""
    change_balance("carol", 5000, logger=logger)
    change_balance("carol", -2000, logger=logger)
    acc = get_account("carol"); assert acc["balance"] == 3000, acc
    change_balance("carol", -2000, revert=True, logger=logger)   # revert a debit -> credit back
    acc = get_account("carol"); assert acc["balance"] == 5000, acc
check("change_balance revert is symmetric", t3)

def t4():
    """Prove produced count increments, reverts to zero, and a revert below zero is rejected (underflow guard)."""
    increase_produced_count("dave", 700, logger=logger)
    assert get_account("dave")["produced"] == 700
    increase_produced_count("dave", 700, revert=True, logger=logger)
    assert get_account("dave")["produced"] == 0
    try:
        increase_produced_count("dave", 5, revert=True, logger=logger); raise RuntimeError("underflow accepted")
    except AssertionError:
        pass
check("produced count + underflow guard", t4)

def make_block(num, parent, h):
    """Build a minimal block dict (creator alice, no txs), save it via save_block, and return it."""
    b = {"block_number": num, "parent_hash": parent, "block_hash": h, "block_timestamp": 1,
         "block_transactions": [], "block_creator": "alice", "block_reward": 0, "child_hash": None}
    save_block(b, logger=logger); return b

def t5():
    """Prove block-ends (earliest/latest) set atomically and read back immediately without a readback spin."""
    g = make_block(0, None, "a"*64)
    set_earliest_block_info(g, logger=logger); set_latest_block_info(g, logger=logger)
    ends = get_block_ends_info(logger=logger)
    assert ends["latest_block"]["block_hash"] == "a"*64 and ends["earliest_block"]["block_hash"] == "a"*64
    set_latest_block_info(make_block(1, "a"*64, "b"*64), logger=logger)
    assert get_block_ends_info(logger=logger)["latest_block"]["block_number"] == 1
check("block_ends atomic set/get (no readback spin)", t5)

def t6():
    """Prove rolling back a block whose parent is missing raises MissingParentError instead of spinning or crashing."""
    orphan = {"block_number": 5, "parent_hash": "c"*64, "block_hash": "d"*64,
              "block_creator": "alice", "block_reward": 0, "block_transactions": []}
    try:
        rollback_one_block(logger=logger, block=orphan); raise RuntimeError("orphan rollback did not raise")
    except MissingParentError:
        pass
check("rollback missing-parent raises MissingParentError (no spin/crash)", t6)

print(f"\n{'ALL S2 CHECKS PASSED' if fails==0 else str(fails)+' S2 CHECK(S) FAILED'}")
sys.exit(1 if fails else 0)
