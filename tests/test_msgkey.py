"""
On-chain messaging key (msgkey identity tx): binds the sender's ML-KEM-768 pubkey to their account so peers
can DM by address/alias with NO off-chain prekey publish. Consensus-critical property: apply -> revert is
BYTE-IDENTICAL, including under key ROTATION (a naive delete-on-revert would lose the prior key and desync).

Run: python3 tests/test_msgkey.py
"""
import os, sys, tempfile, logging, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_msgkey_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logger = logging.getLogger("msgkey"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from ops import kv_ops
from ops.account_ops import create_account, get_account, reflect_transaction
from ops.transaction_ops import construct_msgkey_tx, create_txid
from Curve25519 import generate_keydict

KEM1 = "aa" * 1184     # 2368 hex chars = a well-formed ML-KEM-768 pubkey length
KEM2 = "bb" * 1184

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e: fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def _acc(a):
    """Snapshot address a's account doc as a plain dict (empty dict if absent)."""
    return dict(get_account(a) or {})


def t1_builder_shape_and_signed_kempub():
    """Prove construct_msgkey_tx builds a fee-exempt tx whose txid commits to kem_pub but excludes public_key."""
    kd = generate_keydict()
    tx = construct_msgkey_tx(kd, KEM1, target_block=100)
    assert tx["recipient"] == "msgkey" and tx["amount"] == 0 and tx["fee"] == 0
    assert tx["kem_pub"] == KEM1 and tx["sender"] == kd["address"]
    # the txid preimage is the body WITHOUT txid/signature (those are added after)
    body = {k: v for k, v in tx.items() if k not in ("txid", "signature")}
    assert create_txid(body) == tx["txid"], "txid recompute sanity"
    # kem_pub is COMMITTED by the txid (signed); public_key is NOT (pubkey-once #19)
    rotated = dict(body); rotated["kem_pub"] = KEM2
    assert create_txid(rotated) != tx["txid"], "kem_pub must be covered by the txid (signed)"
    nopub = dict(body); nopub["public_key"] = "deadbeef"
    assert create_txid(nopub) == tx["txid"], "public_key must be EXCLUDED from the txid (pubkey-once)"
check("construct_msgkey_tx: fee-exempt shape + kem_pub signed, public_key excluded from txid", t1_builder_shape_and_signed_kempub)


def t2_apply_sets_kem_pub():
    """Prove applying a msgkey tx binds kem_pub onto the sender's account."""
    kd = generate_keydict(); A = kd["address"]
    create_account(A)
    reflect_transaction(construct_msgkey_tx(kd, KEM1, 100), logger=logger, block_height=100)
    assert get_account(A).get("kem_pub") == KEM1, "kem_pub not bound on the account after apply"
check("apply binds kem_pub onto the account", t2_apply_sets_kem_pub)


def t3_revert_byte_identical_first_publish():
    """Prove apply->revert of a FIRST kem_pub publish deletes the field and leaves the account byte-identical."""
    kd = generate_keydict(); A = kd["address"]
    create_account(A)
    before = _acc(A)
    tx = construct_msgkey_tx(kd, KEM1, 100)
    reflect_transaction(tx, logger=logger, block_height=100)
    assert get_account(A).get("kem_pub") == KEM1
    reflect_transaction(tx, logger=logger, block_height=100, revert=True)
    assert "kem_pub" not in get_account(A), "revert of a first publish must DELETE the field"
    assert _acc(A) == before, f"account doc not byte-identical after apply->revert: {before} vs {_acc(A)}"
check("apply -> revert of a FIRST publish is byte-identical (field deleted)", t3_revert_byte_identical_first_publish)


def t4_rotation_revert_restores_prior_key():
    """Prove reverting a key ROTATION restores the prior kem_pub byte-identically instead of deleting it."""
    kd = generate_keydict(); A = kd["address"]
    create_account(A)
    reflect_transaction(construct_msgkey_tx(kd, KEM1, 100), logger=logger, block_height=100)
    snap = _acc(A)                                   # has KEM1
    tx2 = construct_msgkey_tx(kd, KEM2, 101)         # ROTATE to KEM2 (distinct txid via nonce/target_block)
    reflect_transaction(tx2, logger=logger, block_height=101)
    assert get_account(A).get("kem_pub") == KEM2, "rotation did not overwrite kem_pub"
    reflect_transaction(tx2, logger=logger, block_height=101, revert=True)
    assert get_account(A).get("kem_pub") == KEM1, "rotation revert must RESTORE the prior key, not delete it"
    assert _acc(A) == snap, "account doc not byte-identical after rotation revert"
check("key ROTATION revert restores the prior key byte-identically", t4_rotation_revert_restores_prior_key)


def t5_validate_gate():
    """Prove validate_transaction accepts a well-formed msgkey tx and rejects a wrong-length kem_pub."""
    from ops.transaction_ops import validate_transaction
    kd = generate_keydict()
    good = construct_msgkey_tx(kd, KEM1, target_block=2)
    validate_transaction(good, logger=logger, block_height=0)      # well-formed -> must NOT raise
    bad = construct_msgkey_tx(kd, "aa" * 10, target_block=2)        # kem_pub too short (still validly signed)
    try:
        validate_transaction(bad, logger=logger, block_height=0)
        raise RuntimeError("a malformed kem_pub was accepted")
    except AssertionError as e:
        assert "kem_pub" in str(e) or "2368" in str(e), f"rejected for the wrong reason: {e}"
check("validate_transaction accepts a well-formed msgkey + rejects a malformed kem_pub", t5_validate_gate)


print(f"\n{'ALL MSGKEY CHECKS PASSED' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
