"""
L1 data-availability blob channel (execution-layer Phase 1): a `blob` reserved-recipient tx carries an
opaque payload that L1 orders + stores + fee-burns but never decodes. Checks envelope validation
(size cap, zero amount, paid fee), fee burn on apply, and revert-symmetry.

Run: python3 tests/test_blob.py
"""
import os, sys, tempfile, traceback, logging
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_blob_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "index/producer_sets", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

logger = logging.getLogger("blob"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import MIN_TX_FEE, BLOB_MAX_BYTES
from ops import kv_ops
from ops.account_ops import create_account, get_account, reflect_transaction
from ops.transaction_ops import construct_blob_tx, validate_transaction, blob_payload_size
from ops.key_ops import generate_keys

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()
def raises(fn):
    try: fn(); return False
    except Exception: return True

def _key(bal):
    kd = generate_keys(); create_account(kd["address"], balance=bal); return kd
def _bal(a): return get_account(a)["balance"]

A = _key(1_000_000 + MIN_TX_FEE * 10)

def t1_valid_blob_validates_and_burns_fee():
    tx = construct_blob_tx(A, {"op": "deploy", "code": {"constructor": []}}, target_block=1, fee=MIN_TX_FEE)
    validate_transaction(tx, logger, 1)
    before = _bal(A["address"])
    reflect_transaction(tx, logger, 1)
    assert _bal(A["address"]) == before - MIN_TX_FEE, "DA fee burned, nothing else moved"

def t2_revert_unburns_fee():
    tx = construct_blob_tx(A, "some-opaque-string", target_block=1, fee=MIN_TX_FEE)
    before = _bal(A["address"])
    reflect_transaction(tx, logger, 1)
    assert _bal(A["address"]) == before - MIN_TX_FEE
    reflect_transaction(tx, logger, 1, revert=True)
    assert _bal(A["address"]) == before, "revert un-burns the DA fee"

def t3_oversize_payload_rejected():
    big = "x" * (BLOB_MAX_BYTES + 100)
    tx = construct_blob_tx(A, big, target_block=1, fee=MIN_TX_FEE)
    assert blob_payload_size(big) > BLOB_MAX_BYTES
    assert raises(lambda: validate_transaction(tx, logger, 1)), "oversize blob must reject"

def t4_nonzero_amount_rejected():
    tx = construct_blob_tx(A, "x", target_block=1, fee=MIN_TX_FEE)
    tx["amount"] = 5   # tamper (txid/sig now stale, but the amount assert fires first)
    assert raises(lambda: validate_transaction(tx, logger, 1)), "blob with amount>0 must reject"

def t5_empty_payload_rejected():
    tx = construct_blob_tx(A, "", target_block=1, fee=MIN_TX_FEE)
    assert raises(lambda: validate_transaction(tx, logger, 1)), "empty blob payload must reject"

def t6_below_min_fee_rejected():
    tx = construct_blob_tx(A, "x", target_block=1, fee=0)
    assert raises(lambda: validate_transaction(tx, logger, 1)), "blob below min DA fee must reject"

for name, fn in list(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)

print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
