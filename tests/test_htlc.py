"""
HTLC (Hash Time-Locked Contracts) for cross-chain atomic swaps — consensus tests.

Covers: lock escrows funds under a SHA-256 hashlock + block-height timelock; claim with the CORRECT
preimage releases to the claimant (and publishes the preimage); refund after expiry returns to the sender;
every guard (wrong preimage, expired claim, early refund, wrong caller, non-open HTLC); in-block
double-settle prevention; and EXACT revert-symmetry of lock / claim / refund.

Run: python3 tests/test_htlc.py
"""
import os, sys, tempfile, logging, hashlib, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_htlc_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logger = logging.getLogger("htlc"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import HTLC_ESCROW, HTLC_MIN_TIMELOCK, MIN_TX_FEE
from ops import kv_ops
from ops.account_ops import create_account, get_account, reflect_transaction
from ops.transaction_ops import validate_transaction, reserved_uniqueness_key
from Curve25519 import generate_keydict, sign, unhex
from ops.transaction_ops import create_txid
from protocol import CHAIN_ID

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

AK = generate_keydict(); ALICE = AK["address"]     # locker / sender
BK = generate_keydict(); BOB = BK["address"]       # claimant
create_account(ALICE, balance=1_000_000)
create_account(BOB, balance=0)
kv_ops.account_set_field(ALICE, "public_key", AK["public_key"])
kv_ops.account_set_field(BOB, "public_key", BK["public_key"])

PRE = "aa" * 32                                     # 32-byte preimage (hex)
HASH = hashlib.sha256(bytes.fromhex(PRE)).hexdigest()
AMT = 100_000

def bal(a):
    """Return the current balance of address a (0 if unset)."""
    return get_account(a).get("balance", 0)

# --- bare tx dicts for REFLECT (state) tests (reflect does not verify signatures) ---
def lock(txid, amount=AMT, fee=MIN_TX_FEE):
    """Build a bare htlc_lock tx dict (Alice locks amount for Bob under HASH, expiry 100)."""
    return {"sender": ALICE, "recipient": "htlc_lock", "amount": amount, "fee": fee, "txid": txid,
            "max_block": 10, "data": {"claimant": BOB, "hashlock": HASH, "expiry": 100}}
def claim(hid, preimage=PRE):
    """Build a bare htlc_claim tx dict (Bob claims HTLC hid with preimage)."""
    return {"sender": BOB, "recipient": "htlc_claim", "amount": 0, "fee": 0, "txid": "c_" + hid,
            "max_block": 20, "data": {"htlc_id": hid, "preimage": preimage}}
def refund(hid):
    """Build a bare htlc_refund tx dict (Alice reclaims HTLC hid after expiry)."""
    return {"sender": ALICE, "recipient": "htlc_refund", "amount": 0, "fee": 0, "txid": "r_" + hid,
            "max_block": 200, "data": {"htlc_id": hid}}

# --- signed envelopes for VALIDATION tests ---
def signed(kd, recipient, data, amount=0, fee=0, target=20):
    """Build a fully signed tx envelope (txid + signature) from keydict kd for validation tests."""
    tx = {"sender": kd["address"], "recipient": recipient, "amount": amount, "fee": fee, "data": data,
          "timestamp": 1, "nonce": "n" + recipient + str(target), "public_key": kd["public_key"],
          "max_block": target, "chain_id": CHAIN_ID}
    tx["txid"] = create_txid(tx); tx["signature"] = sign(kd["private_key"], unhex(tx["txid"]))
    return tx


def t1_lock_escrows():
    """Prove lock debits amount+fee from the sender, escrows the amount, and records an open HTLC."""
    a0, e0 = bal(ALICE), bal(HTLC_ESCROW)
    reflect_transaction(lock("H1"), logger, block_height=10)
    assert bal(ALICE) == a0 - (AMT + MIN_TX_FEE), "lock debits amount+fee from sender"
    assert bal(HTLC_ESCROW) == e0 + AMT, "lock escrows the amount"
    doc = kv_ops.htlc_get("H1")
    assert doc and doc["status"] == "open" and doc["claimant"] == BOB and doc["amount"] == AMT, "HTLC recorded"

def t2_claim_pays_claimant_and_reveals():
    """Prove claim releases the escrow to the claimant and records status=claimed plus the published preimage."""
    b0, e0 = bal(BOB), bal(HTLC_ESCROW)
    reflect_transaction(claim("H1"), logger, block_height=20)
    assert bal(BOB) == b0 + AMT, "claim releases escrow to the claimant"
    assert bal(HTLC_ESCROW) == e0 - AMT, "escrow drained"
    doc = kv_ops.htlc_get("H1")
    assert doc["status"] == "claimed" and doc["preimage"] == PRE, "claim records status + published preimage"

def t3_refund_after_expiry_returns_to_sender():
    """Prove refund after expiry returns the escrowed amount to the sender and marks the HTLC refunded."""
    reflect_transaction(lock("H2"), logger, block_height=10)
    a0, e0 = bal(ALICE), bal(HTLC_ESCROW)
    reflect_transaction(refund("H2"), logger, block_height=200)
    assert bal(ALICE) == a0 + AMT, "refund returns escrow to the sender"
    assert bal(HTLC_ESCROW) == e0 - AMT
    assert kv_ops.htlc_get("H2")["status"] == "refunded"

def t4_revert_symmetry_lock_and_claim():
    """Prove reverting claim then lock (mirror order) restores accounts byte-identical and removes the HTLC row."""
    before = dict(get_account(ALICE)); e_before = bal(HTLC_ESCROW)
    reflect_transaction(lock("H3"), logger, block_height=10)
    reflect_transaction(claim("H3"), logger, block_height=20)
    # revert in mirror order
    reflect_transaction(claim("H3"), logger, block_height=20, revert=True)
    reflect_transaction(lock("H3"), logger, block_height=10, revert=True)
    assert get_account(ALICE) == before, "sender doc restored byte-identical after lock+claim revert"
    assert bal(HTLC_ESCROW) == e_before, "escrow restored"
    assert kv_ops.htlc_get("H3") is None, "HTLC row removed on lock revert"

def t5_revert_symmetry_refund():
    """Prove reverting a refund restores balances byte-identical and sets the HTLC back to open."""
    reflect_transaction(lock("H4"), logger, block_height=10)
    snap = dict(get_account(ALICE)); e_snap = bal(HTLC_ESCROW)
    reflect_transaction(refund("H4"), logger, block_height=200)
    reflect_transaction(refund("H4"), logger, block_height=200, revert=True)
    assert get_account(ALICE) == snap and bal(HTLC_ESCROW) == e_snap, "refund reverts byte-identical"
    assert kv_ops.htlc_get("H4")["status"] == "open", "status back to open after refund revert"

def _expect_reject(tx, substr):
    """Assert validate_transaction rejects tx with an AssertionError containing substr."""
    try:
        validate_transaction(tx, logger, block_height=tx["max_block"]); raise RuntimeError("accepted!")
    except AssertionError as e:
        assert substr in str(e), f"wrong reason: {e}"

def t6_guards():
    """Prove every validation guard rejects: wrong preimage, expired claim, non-claimant, early refund, non-sender, missing HTLC."""
    # seed an OPEN htlc "G" (expiry 100) directly for validation checks
    kv_ops.htlc_put("G", {"sender": ALICE, "claimant": BOB, "amount": AMT, "hashlock": HASH,
                          "expiry": 100, "status": "open"})
    # wrong preimage
    _expect_reject(signed(BK, "htlc_claim", {"htlc_id": "G", "preimage": "bb" * 32}, target=20), "preimage does not match")
    # claim after expiry (max_block >= expiry)
    _expect_reject(signed(BK, "htlc_claim", {"htlc_id": "G", "preimage": PRE}, target=100), "expired")
    # claim by a non-claimant (Alice tries)
    _expect_reject(signed(AK, "htlc_claim", {"htlc_id": "G", "preimage": PRE}, target=20), "only the claimant")
    # refund before expiry
    _expect_reject(signed(AK, "htlc_refund", {"htlc_id": "G"}, target=20), "not expired yet")
    # refund by a non-sender (Bob tries)
    _expect_reject(signed(BK, "htlc_refund", {"htlc_id": "G"}, target=200), "only the original sender")
    # claim/refund against a missing HTLC
    _expect_reject(signed(BK, "htlc_claim", {"htlc_id": "NOPE", "preimage": PRE}, target=20), "no OPEN HTLC")

def t7_valid_claim_and_refund_pass_validation():
    """Prove a correct claim (pre-expiry) and a correct refund (post-expiry) both pass validation."""
    kv_ops.htlc_put("OK", {"sender": ALICE, "claimant": BOB, "amount": AMT, "hashlock": HASH,
                           "expiry": 100, "status": "open"})
    validate_transaction(signed(BK, "htlc_claim", {"htlc_id": "OK", "preimage": PRE}, target=20), logger, block_height=20)
    validate_transaction(signed(AK, "htlc_refund", {"htlc_id": "OK"}, target=150), logger, block_height=150)

def t8_lock_validation_window():
    """Prove lock validation enforces the HTLC_MIN_TIMELOCK window and rejects self-claim (claimant == sender)."""
    # a valid lock passes; an out-of-window expiry is rejected
    good = signed(AK, "htlc_lock", {"claimant": BOB, "hashlock": HASH, "expiry": 10 + HTLC_MIN_TIMELOCK + 5},
                  amount=AMT, fee=MIN_TX_FEE, target=10)
    validate_transaction(good, logger, block_height=10)
    _expect_reject(signed(AK, "htlc_lock", {"claimant": BOB, "hashlock": HASH, "expiry": 10 + 1},
                          amount=AMT, fee=MIN_TX_FEE, target=10), "timelock window")
    # self-claim (claimant == sender) is rejected
    _expect_reject(signed(AK, "htlc_lock", {"claimant": ALICE, "hashlock": HASH, "expiry": 10 + HTLC_MIN_TIMELOCK + 5},
                          amount=AMT, fee=MIN_TX_FEE, target=10), "must differ")

def t9_inblock_double_settle_key():
    """Prove claim and refund of one HTLC share the ("htlc_settle", id) uniqueness key (one settle per block)."""
    assert reserved_uniqueness_key(claim("G")) == ("htlc_settle", "G"), "claim uniqueness by htlc_id"
    assert reserved_uniqueness_key(refund("G")) == ("htlc_settle", "G"), "refund shares the key (one settle/block)"

for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
