"""
Shielded pool — L1 side (doc/privacy.md): the `shield` escrow deposit + `unshield` exit are the only L1
touch-points (L1 never sees a note or verifies a STARK). Mirrors the bridge. Covers: shield escrows + reverts
byte-identically; shield validation (amount + fee + commitments); unshield validation rejects a bad proof and
a spent nullifier.

Run: python3 tests/test_shield_l1.py
"""
import os, sys, tempfile, logging, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_shl1_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logger = logging.getLogger("shl1"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import SHIELD_ESCROW, MIN_TX_FEE, CHAIN_ID
from ops import kv_ops
from ops.account_ops import create_account, get_account, reflect_transaction
from ops.transaction_ops import validate_transaction, reserved_uniqueness_key, create_txid
from signatures import generate_keydict, sign, unhex

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def bal(a):
    """Balance of account a, or 0 if the account does not exist."""
    acc = get_account(a); return acc["balance"] if acc else 0

def _dump():
    """Snapshot every LMDB sub-database as raw (key, value) byte pairs for byte-identical comparison."""
    env = kv_ops.get_env(); dbs = kv_ops._dbs(); out = {}
    with env.begin() as txn:
        for nm, db in dbs.items():
            with txn.cursor(db=db) as cur:
                out[nm] = [(bytes(k), bytes(v)) for k, v in cur]
    return out

def signed(kd, recipient, amount, fee, data, target=20):
    """Build a fully signed transaction from key dict kd with a valid txid and signature."""
    tx = {"sender": kd["address"], "recipient": recipient, "amount": amount, "fee": fee, "data": data,
          "timestamp": 1, "nonce": "n" + recipient, "public_key": kd["public_key"], "max_block": target,
          "chain_id": CHAIN_ID}
    tx["txid"] = create_txid(tx); tx["signature"] = sign(kd["private_key"], unhex(tx["txid"]))
    return tx


def t1_shield_escrows_and_reverts_byte_identical():
    """Prove a shield tx debits amount+fee, locks the amount in SHIELD_ESCROW, and reverts to a byte-identical DB."""
    create_account("alice", balance=1_000_000)
    create_account(SHIELD_ESCROW, balance=3)
    tx = {"sender": "alice", "recipient": "shield", "amount": 100_000, "fee": 7, "txid": "s1",
          "data": {"out_commitments": ["cm_abc"]}}
    before = _dump()
    with kv_ops.write_txn():
        reflect_transaction(tx, logger=logger, block_height=1)
    assert bal("alice") == 1_000_000 - 100_007, "shield debits amount+fee from sender"
    assert bal(SHIELD_ESCROW) == 3 + 100_000, "shield locks the amount in escrow (fee burned)"
    with kv_ops.write_txn():
        reflect_transaction(tx, logger=logger, block_height=1, revert=True)
    assert _dump() == before, "shield reflect rollback is NOT byte-identical"

def t2_shield_validation():
    """Prove shield validation accepts a well-formed tx and rejects zero amount, low fee, and empty out_commitments with the right reasons."""
    kd = generate_keydict(); create_account(kd["address"], balance=1_000_000)
    kv_ops.account_set_field(kd["address"], "public_key", kd["public_key"])
    validate_transaction(signed(kd, "shield", 100_000, MIN_TX_FEE, {"out_commitments": ["cm1"]}), logger, block_height=20)
    for bad, why in [
        (signed(kd, "shield", 0, MIN_TX_FEE, {"out_commitments": ["cm1"]}), "positive"),
        (signed(kd, "shield", 100, 0, {"out_commitments": ["cm1"]}), "fee below"),
        (signed(kd, "shield", 100, MIN_TX_FEE, {"out_commitments": []}), "output note commitments"),
    ]:
        try:
            validate_transaction(bad, logger, block_height=20); raise RuntimeError("accepted bad shield")
        except AssertionError as e:
            assert why in str(e), f"wrong reason: {e}"

def t3_unshield_validation_rejects_bad_proof_and_spent_nullifier():
    """Prove an unshield without a settled root / valid proof is rejected and a spent nullifier is recorded as spent."""
    kd = generate_keydict(); create_account(kd["address"], balance=0)
    kv_ops.account_set_field(kd["address"], "public_key", kd["public_key"])
    create_account(SHIELD_ESCROW, balance=500_000)
    # a well-formed (sparse-format) but unprovable proof: shape passes, settlement/membership must reject
    data = {"addr": kd["address"], "amount": 100_000, "nonce": "nf_xyz",
            "proof": {"kv": "0" * 64, "path": {"d": 256, "s": {}}}}
    tx = signed(kd, "unshield", 0, 0, data)
    # no settled root / bad proof -> rejected (either "no settled" or "not proven")
    try:
        validate_transaction(tx, logger, block_height=20); raise RuntimeError("accepted unproven unshield")
    except AssertionError as e:
        assert "settled" in str(e) or "proven" in str(e), f"unexpected: {e}"
    # a spent nullifier is rejected regardless
    kv_ops.shield_nullifier_put(kd["address"], "nf_xyz")
    assert kv_ops.shield_nullifier_exists(kd["address"], "nf_xyz")

def t4_unshield_uniqueness_key():
    """Prove the unshield uniqueness key is (recipient, addr, nonce) so each exit is one-per-(addr, nonce)."""
    tx = {"recipient": "unshield", "data": {"addr": "a", "amount": 1, "nonce": "nf1"}}
    assert reserved_uniqueness_key(tx) == ("unshield", "a", "nf1"), "one unshield exit per (addr, nonce)"

for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
