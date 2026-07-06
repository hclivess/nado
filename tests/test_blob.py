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
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()
def raises(fn):
    """True if fn raises."""
    try: fn(); return False
    except Exception: return True

def _key(bal):
    """Fund a fresh keypair with balance bal and return its key dict."""
    kd = generate_keys(); create_account(kd["address"], balance=bal); return kd
def _bal(a):
    """Spendable balance of address a."""
    return get_account(a)["balance"]

A = _key(1_000_000 + MIN_TX_FEE * 10)

def t1_valid_blob_validates_and_burns_fee():
    """Prove a valid blob tx validates and applying it burns only the DA fee."""
    tx = construct_blob_tx(A, {"op": "deploy", "code": {"constructor": []}}, target_block=1, fee=MIN_TX_FEE)
    validate_transaction(tx, logger, 1)
    before = _bal(A["address"])
    reflect_transaction(tx, logger, 1)
    assert _bal(A["address"]) == before - MIN_TX_FEE, "DA fee burned, nothing else moved"

def t2_revert_unburns_fee():
    """Prove reverting a blob tx refunds the burned DA fee (revert-symmetry)."""
    tx = construct_blob_tx(A, "some-opaque-string", target_block=1, fee=MIN_TX_FEE)
    before = _bal(A["address"])
    reflect_transaction(tx, logger, 1)
    assert _bal(A["address"]) == before - MIN_TX_FEE
    reflect_transaction(tx, logger, 1, revert=True)
    assert _bal(A["address"]) == before, "revert un-burns the DA fee"

def t3_oversize_payload_rejected():
    """Prove a payload over BLOB_MAX_BYTES fails validation."""
    big = "x" * (BLOB_MAX_BYTES + 100)
    tx = construct_blob_tx(A, big, target_block=1, fee=MIN_TX_FEE)
    assert blob_payload_size(big) > BLOB_MAX_BYTES
    assert raises(lambda: validate_transaction(tx, logger, 1)), "oversize blob must reject"

def t4_nonzero_amount_rejected():
    """Prove a blob tx with amount>0 fails validation."""
    tx = construct_blob_tx(A, "x", target_block=1, fee=MIN_TX_FEE)
    tx["amount"] = 5   # tamper (txid/sig now stale, but the amount assert fires first)
    assert raises(lambda: validate_transaction(tx, logger, 1)), "blob with amount>0 must reject"

def t5_empty_payload_rejected():
    """Prove an empty blob payload fails validation."""
    tx = construct_blob_tx(A, "", target_block=1, fee=MIN_TX_FEE)
    assert raises(lambda: validate_transaction(tx, logger, 1)), "empty blob payload must reject"

def t6_below_min_fee_rejected():
    """Prove a blob tx paying below the minimum DA fee fails validation."""
    tx = construct_blob_tx(A, "x", target_block=1, fee=0)
    assert raises(lambda: validate_transaction(tx, logger, 1)), "blob below min DA fee must reject"

def t7_per_block_blob_cap():
    """Prove an over-cap blob set is rejected and cap_block_blobs trims it under MAX_BLOB_BYTES_PER_BLOCK."""
    from protocol import MAX_BLOB_BYTES_PER_BLOCK
    from ops.transaction_ops import assert_block_blob_cap, cap_block_blobs, block_blob_bytes
    # one ~10KB blob per tx; enough of them to exceed the per-block cap
    per = 10 * 1024
    n = MAX_BLOB_BYTES_PER_BLOCK // per + 2
    blobs = [construct_blob_tx(A, "x" * per, target_block=1, fee=MIN_TX_FEE) for _ in range(n)]
    assert raises(lambda: assert_block_blob_cap(blobs)), "over-cap block must be rejected"
    kept = cap_block_blobs(blobs)
    assert block_blob_bytes(kept) <= MAX_BLOB_BYTES_PER_BLOCK, "assembly must trim blobs under the cap"
    assert_block_blob_cap(kept)                                   # trimmed set now passes
    assert len(kept) < n, "some blobs were dropped"

def t8_non_blob_txs_never_dropped_by_cap():
    """Prove cap_block_blobs never drops a non-blob tx, whatever the blob pressure."""
    from ops.transaction_ops import cap_block_blobs
    # a normal (non-blob) tx is always kept regardless of blob pressure
    normal = {"recipient": "ndoxxxx", "txid": "aa", "data": ""}
    big = construct_blob_tx(A, "x" * (BLOB_MAX_BYTES), target_block=1, fee=MIN_TX_FEE)
    kept = cap_block_blobs([normal, big] + [construct_blob_tx(A, "y" * (BLOB_MAX_BYTES), 1, MIN_TX_FEE) for _ in range(20)])
    assert normal in kept, "non-blob tx must never be dropped by the blob cap"

for name, fn in list(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)

print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
