import os, sys, tempfile, traceback
home = tempfile.mkdtemp(prefix="nado_s41_")
os.environ["HOME"] = home
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "index/producer_sets", "logs", "peers"):
    os.makedirs(f"{home}/nado/{d}", exist_ok=True)

import logging
logger = logging.getLogger("s41"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()
from ops.account_ops import create_account, get_account, reflect_transaction, change_bonded
from ops.transaction_ops import validate_all_spending

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e: fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()
def expect_assert(name, fn):
    global fails
    try:
        fn(); fails += 1; print(f"FAIL  {name}: no AssertionError raised")
    except AssertionError:
        print(f"PASS  {name}: rejected")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: wrong error {e!r}")

create_account("alice", balance=10000)
BOND = {"sender": "alice", "recipient": "bond", "amount": 5000, "fee": 1000}
UNBOND = {"sender": "alice", "recipient": "unbond", "amount": 2000, "fee": 100}

def t1():
    reflect_transaction(BOND, logger=logger, block_height=1)
    a = get_account("alice")
    assert a["balance"] == 4000 and a["bonded"] == 5000, a   # 10000 - 5000 - 1000 fee
check("bond locks stake; fee burned", t1)

def t2():
    reflect_transaction(BOND, logger=logger, block_height=1, revert=True)
    a = get_account("alice")
    assert a["balance"] == 10000 and a["bonded"] == 0, a
check("bond revert is exact identity", t2)

def t3():
    from ops import kv_ops as _kv
    from protocol import BOND_UNLOCK_DELAY as _DELAY
    reflect_transaction(BOND, logger=logger, block_height=1)              # balance 4000 bonded 5000
    reflect_transaction(UNBOND, logger=logger, block_height=2)           # unbond is now a REQUEST (delayed)
    a = get_account("alice")
    # coins STAY bonded (still slashable) until a matured `withdraw`; only a pending unbond is recorded
    assert a["bonded"] == 5000 and a["balance"] == 4000, a
    assert _kv.unbond_get("alice") == {"amount": 2000, "release_block": 2 + _DELAY}, _kv.unbond_get("alice")
    reflect_transaction(UNBOND, logger=logger, block_height=2, revert=True)
    a = get_account("alice")
    assert a["bonded"] == 5000 and a["balance"] == 4000, a
    assert _kv.unbond_get("alice") is None
check("unbond is a delayed request (coins stay bonded/slashable); revert clears pending", t3)

# alice now: balance 4000, bonded 5000
def t4():
    assert validate_all_spending([{"sender": "alice", "recipient": "unbond", "amount": 5000, "fee": 100}])
check("unbond up to full bonded passes spending check", t4)

expect_assert("bond beyond balance rejected",
              lambda: validate_all_spending([{"sender": "alice", "recipient": "bond", "amount": 3500, "fee": 1000}]))
expect_assert("unbond beyond bonded rejected",
              lambda: validate_all_spending([{"sender": "alice", "recipient": "unbond", "amount": 6000, "fee": 100}]))
expect_assert("change_bonded underflow fails closed",
              lambda: change_bonded("alice", -9999, logger=logger))

def t5():
    # a normal spend still only sees spendable balance, never the bonded stake
    assert validate_all_spending([{"sender": "alice", "recipient": "bob", "amount": 4000, "fee": 0}])  # exactly balance
check("normal transfer cannot reach bonded stake", t5)
expect_assert("normal transfer beyond spendable balance rejected",
              lambda: validate_all_spending([{"sender": "alice", "recipient": "bob", "amount": 4000, "fee": 1}]))

print(f"\n{'ALL S4.1 CHECKS PASSED' if fails==0 else str(fails)+' S4.1 CHECK(S) FAILED'}")
sys.exit(1 if fails else 0)
