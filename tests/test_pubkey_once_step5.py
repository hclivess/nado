"""
Pubkey-once unit checks (#19, security step 5).

- create_txid EXCLUDES public_key (a tx with or without the 1312-byte key has the same txid).
- The sender's pubkey is STORED on its first indexed tx (so later txs may omit it).
- Storing is REVERT-SYMMETRIC: incorporate then rollback returns the KV env BYTE-IDENTICAL.
"""
import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_pk1_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(os.path.expanduser(f"~/nado/{d}"), exist_ok=True)

import logging
logger = logging.getLogger("pk1"); logger.addHandler(logging.NullHandler())

from genesis import create_indexers
create_indexers()

from ops import kv_ops
from ops.account_ops import create_account, get_account
from ops.transaction_ops import index_transactions, unindex_transactions, create_txid
from Curve25519 import generate_keydict
from protocol import CHAIN_ID

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def dump_env():
    """Dump every LMDB sub-database as {name: [(key, value), ...]} for byte-identical comparison."""
    env = kv_ops.get_env(); dbs = kv_ops._dbs(); out = {}
    with env.begin() as txn:
        for name, db in dbs.items():
            with txn.cursor(db=db) as cur:
                out[name] = [(bytes(k), bytes(v)) for k, v in cur]
    return out


kd = generate_keydict()
sender = kd["address"]
body = {"sender": sender, "recipient": "register", "amount": 0, "timestamp": 1, "data": "",
        "nonce": "abc123", "public_key": kd["public_key"], "max_block": 5,
        "chain_id": CHAIN_ID, "fee": 0, "epoch": 0}


def t1():
    """Prove create_txid excludes public_key: a lean tx keeps the same txid."""
    body_no_pk = {k: v for k, v in body.items() if k != "public_key"}
    assert create_txid(body) == create_txid(body_no_pk), "public_key must be excluded from the txid"
check("create_txid excludes public_key (lean tx keeps the same txid)", t1)


def t2_and_t3():
    """Prove the pubkey is stored on first indexed use and incorporate->rollback leaves the KV env byte-identical."""
    create_account(sender)                 # pre-state: account exists, NO pubkey
    before = dump_env()

    tx = dict(body); tx["txid"] = create_txid(tx)
    block = {"block_number": 5, "block_transactions": [tx]}

    with kv_ops.write_txn():
        index_transactions(block=block, sorted_transactions=[tx], logger=logger)
    assert get_account(sender).get("public_key") == kd["public_key"], "pubkey not stored on first use"

    with kv_ops.write_txn():
        unindex_transactions(block=block, logger=logger, block_height=5)
    assert "public_key" not in get_account(sender), "pubkey not cleared on revert"

    after = dump_env()
    assert before == after, "incorporate->rollback must leave the env BYTE-IDENTICAL (revert-symmetric)"
check("pubkey stored on first use + revert returns env BYTE-IDENTICAL", t2_and_t3)


print(f"\n{'ALL PUBKEY-ONCE CHECKS PASSED' if not fails else str(fails) + ' FAILURE(S)'}")
sys.exit(1 if fails else 0)
