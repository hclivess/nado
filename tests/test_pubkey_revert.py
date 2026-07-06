"""
PUBKEY-ONCE revert must NOT cull an established sender's public_key when a reorg reverts a LATER, pubkey-LESS
tx on a ROLLING/pruned node. There tx_of_account reads the pruned history and returns empty even for a
long-established sender, so the old code deleted the pubkey and permanently bricked that sender's validation
("first tx must carry it") — exactly the node-stuck-at-1041 case (a pubkey-less `bond` from an account that
registered ~block 180). Fix: only delete on revert of a tx that actually CARRIED the key.

Run: python3 tests/test_pubkey_revert.py
"""
import os, sys, tempfile, logging, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_pkrev_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "index/producer_sets", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logger = logging.getLogger("pkrev"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from ops import kv_ops
from ops.account_ops import create_account, get_account
from ops.transaction_ops import index_transactions, unindex_transactions
from protocol import CHAIN_ID

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e: fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

PK = "ab" * 656   # a plausible ML-DSA-44 pubkey hex (length irrelevant here)

def _tx(txid, amount, public_key=None):
    """Build a minimal s->r transfer tx, optionally carrying a public_key."""
    t = {"sender": "s", "recipient": "r", "amount": amount, "fee": 0, "txid": txid,
         "nonce": txid, "timestamp": 1, "target_block": 500, "chain_id": CHAIN_ID}
    if public_key:
        t["public_key"] = public_key
    return t


def t1_rolling_revert_of_pubkeyless_tx_keeps_pubkey():
    """Prove reverting a later pubkey-LESS tx on a pruned node keeps the sender's established pubkey (the 1041 bug)."""
    create_account("s", balance=10_000)
    create_account("r", balance=0)
    kv_ops.account_set_field("s", "public_key", PK)          # s established its pubkey long ago
    # a LATER pubkey-LESS tx from s (the bond-at-1041 analogue)
    tx = _tx("t_later", 100)
    blk = {"block_number": 500, "block_transactions": [tx]}
    index_transactions(block=blk, sorted_transactions=[tx], logger=logger)
    assert get_account("r")["balance"] == 100

    # SIMULATE A ROLLING/PRUNED NODE: history is gone -> tx_of_account("s") returns empty
    kv_ops.drop_tx_index()
    assert kv_ops.tx_of_account("s", min_block=0, limit=1) == [], "precondition: pruned history looks empty"

    # reorg reverts that pubkey-less tx
    unindex_transactions(block=blk, logger=logger, block_height=500)
    assert get_account("s").get("public_key") == PK, \
        "established pubkey was WRONGLY culled on a rolling-node revert of a pubkey-less tx (the bug)"
    assert get_account("r")["balance"] == 0, "the transfer itself must still revert"
check("rolling-node revert of a pubkey-LESS tx keeps the sender's established pubkey", t1_rolling_revert_of_pubkeyless_tx_keeps_pubkey)


def t2_revert_of_the_establishing_tx_still_clears_pubkey():
    """Prove reverting the establishing (pubkey-CARRYING) tx still clears the pubkey, preserving symmetry."""
    create_account("s2", balance=10_000)
    create_account("r2", balance=0)
    tx = {"sender": "s2", "recipient": "r2", "amount": 50, "fee": 0, "txid": "t_first",
          "nonce": "n", "timestamp": 1, "target_block": 500, "chain_id": CHAIN_ID, "public_key": PK}
    blk = {"block_number": 501, "block_transactions": [tx]}
    index_transactions(block=blk, sorted_transactions=[tx], logger=logger)   # first tx -> stores pubkey
    assert get_account("s2").get("public_key") == PK
    # reverting the FIRST/establishing tx (which CARRIED the key) with no earlier tx must still clear it
    kv_ops.drop_tx_index()
    unindex_transactions(block=blk, logger=logger, block_height=501)
    assert not get_account("s2").get("public_key"), "reverting the establishing (pubkey-carrying) tx must clear it"
check("revert of the establishing (pubkey-carrying) tx still clears the pubkey (symmetry preserved)", t2_revert_of_the_establishing_tx_still_clears_pubkey)


print(f"\n{'ALL PUBKEY-REVERT CHECKS PASSED' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
