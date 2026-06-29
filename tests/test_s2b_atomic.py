import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_s2b_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "index/producer_sets", "logs", "peers"):
    os.makedirs(os.path.expanduser(f"~/nado/{d}"), exist_ok=True)

import logging
logger = logging.getLogger("s2b"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()
from ops.data_ops import get_home
from ops.sqlite_ops import DbHandler, transaction
from ops.account_ops import create_account, get_account, change_balance, fetch_totals

DB = f"{get_home()}/index/index.db"
def h():
    return DbHandler(db_file=DB)

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e: fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def t1():
    # consolidation: all four tables live in ONE index.db
    tables = {r[0] for r in h().db_fetch(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("acc_index", "totals_index", "tx_index", "block_index"):
        assert t in tables, f"{t} missing from consolidated index.db (have {tables})"
check("consolidated index.db has acc/totals/tx/block tables", t1)

def t2():
    create_account("alice", balance=1000)
    with transaction(DB):
        change_balance("alice", -500, logger=logger)
        change_balance("alice", -100, logger=logger)
    assert get_account("alice")["balance"] == 400, "committed transaction not persisted"
check("transaction commits all statements together", t2)

def t3():
    create_account("bob", balance=1000)
    try:
        with transaction(DB):
            change_balance("bob", -700, logger=logger)   # would leave 300 (uncommitted)
            raise RuntimeError("boom mid-transaction")
    except RuntimeError:
        pass
    assert get_account("bob")["balance"] == 1000, "rolled-back transaction still mutated balance"
check("transaction rolls back ALL on mid-failure (atomic)", t3)

def t4():
    # the real win: one crash rolls back across acc_index + block_index + tx_index + totals
    create_account("carol", balance=2000)
    before_tot = fetch_totals()["produced"]
    try:
        with transaction(DB):
            change_balance("carol", -1000, logger=logger)
            h().db_execute("INSERT OR IGNORE INTO block_index VALUES (?,?)", ("d"*64, 7))
            h().db_execute("INSERT OR IGNORE INTO tx_index VALUES (?,?,?,?)", ("txZ", 7, "carol", "x"))
            h().db_execute("UPDATE totals_index SET produced = produced + ?", (999,))
            raise RuntimeError("crash before commit")
    except RuntimeError:
        pass
    assert get_account("carol")["balance"] == 2000, "acc_index not rolled back"
    assert not h().db_fetch("SELECT 1 FROM block_index WHERE block_hash=?", ("d"*64,)), "block_index not rolled back"
    assert not h().db_fetch("SELECT 1 FROM tx_index WHERE txid=?", ("txZ",)), "tx_index not rolled back"
    assert fetch_totals()["produced"] == before_tot, "totals not rolled back"
check("atomic across ALL tables: incorporate-style crash leaves no partial state", t4)

def t5():
    # and the success path commits across all tables together
    with transaction(DB):
        h().db_execute("INSERT OR IGNORE INTO block_index VALUES (?,?)", ("e"*64, 8))
        h().db_execute("INSERT OR IGNORE INTO tx_index VALUES (?,?,?,?)", ("txY", 8, "carol", "x"))
    assert h().db_fetch("SELECT 1 FROM block_index WHERE block_hash=?", ("e"*64,))
    assert h().db_fetch("SELECT 1 FROM tx_index WHERE txid=?", ("txY",))
check("transaction commits across tables together", t5)

print(f"\n{'ALL S2b CHECKS PASSED' if fails==0 else str(fails)+' S2b CHECK(S) FAILED'}")
sys.exit(1 if fails else 0)
