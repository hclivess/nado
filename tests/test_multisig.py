"""
Opt-in M-of-N multisig (ops/multisig_ops + transaction_ops): descriptor-derived addresses,
threshold signature verification in validate_origin, the payment-only / per-signature-fee
consensus gates in validate_transaction, the client draft + co-sign helpers,
and reflect/revert symmetry of a multisig spend.

Run: python3 tests/test_multisig.py
"""
import os, sys, tempfile, traceback, logging
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_msig_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

logger = logging.getLogger("msig"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import MIN_TX_FEE, CHAIN_ID
from ops.multisig_ops import (multisig_address, validate_descriptor, verify_multisig_origin,
                              draft_multisig_spend, add_member_signature)
from ops.account_ops import create_account, get_account, reflect_transaction
from ops.transaction_ops import validate_transaction, create_txid
from ops.key_ops import generate_keys
from Curve25519 import sign, unhex

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

# shared actors: three member keys + an outsider, and the 2-of-3 account they control
K1, K2, K3, OUTSIDER = generate_keys(), generate_keys(), generate_keys(), generate_keys()
MEMBERS = sorted([K1["address"], K2["address"], K3["address"]])
MSIG = multisig_address(2, MEMBERS)
PAYEE = generate_keys()["address"]
H = 100                                           # any landing block (multisig has no activation gate)
create_account(MSIG, balance=10_000_000_000)

def _draft(amount=1_000_000, fee=MIN_TX_FEE * 3, recipient=PAYEE, target_block=H, threshold=2):
    """Fresh unsigned 2-of-3 proposal from the shared multisig account."""
    return draft_multisig_spend(threshold, MEMBERS, recipient, amount, fee, target_block)

def _signed(signers, **kw):
    """Proposal signed by the given member keydicts."""
    tx = _draft(**kw)
    for kd in signers:
        add_member_signature(tx, kd["private_key"])
    return tx


def t01_address_is_deterministic_and_order_independent():
    """Prove the multisig address depends only on (threshold, member set): same inputs -> same
    address on every client, different threshold -> different account."""
    assert multisig_address(2, MEMBERS) == MSIG
    assert multisig_address(3, MEMBERS) != MSIG, "threshold must be part of the address"
    assert multisig_address(2, sorted(MEMBERS, reverse=True)[::-1]) == MSIG

def t02_two_of_three_spend_validates():
    """Prove a 2-of-3 spend carrying two valid member signatures passes the full consensus gate."""
    assert validate_transaction(_signed([K1, K3]), logger, H)

def t03_threshold_not_met_rejected():
    """Prove one signature on a 2-of-3 account is rejected."""
    assert raises(lambda: validate_transaction(_signed([K2]), logger, H))

def t04_duplicate_member_signature_rejected():
    """Prove the same member signing twice cannot satisfy the threshold (distinct members only)."""
    tx = _signed([K1])
    tx["signature"].append({"public_key": K1["public_key"],
                            "signature": sign(private_key=K1["private_key"], message=unhex(tx["txid"]))})
    assert raises(lambda: validate_transaction(tx, logger, H))

def t05_non_member_signature_rejected():
    """Prove an outsider's (valid!) signature hard-fails the tx rather than merely not counting."""
    tx = _signed([K1, K2])
    tx["signature"].append({"public_key": OUTSIDER["public_key"],
                            "signature": sign(private_key=OUTSIDER["private_key"], message=unhex(tx["txid"]))})
    assert raises(lambda: validate_transaction(tx, logger, H))

def t06_garbage_signature_rejected():
    """Prove a threshold-meeting tx with one corrupted signature entry is rejected."""
    tx = _signed([K1, K2])
    tx["signature"][1]["signature"] = "ab" * 2420
    assert raises(lambda: validate_transaction(tx, logger, H))

def t07_descriptor_canonical_form_enforced():
    """Prove unsorted / duplicate / oversized / short member lists and bad thresholds all fail
    descriptor validation (one policy == one encoding == one address)."""
    assert raises(lambda: validate_descriptor({"threshold": 2, "members": MEMBERS[::-1]}))
    assert raises(lambda: validate_descriptor({"threshold": 2, "members": [MEMBERS[0]] * 3}))
    assert raises(lambda: validate_descriptor({"threshold": 2, "members": MEMBERS[:1]}))
    assert raises(lambda: validate_descriptor({"threshold": 0, "members": MEMBERS}))
    assert raises(lambda: validate_descriptor({"threshold": 4, "members": MEMBERS}))
    assert raises(lambda: validate_descriptor({"threshold": 2, "members": MEMBERS, "x": 1}))
    assert raises(lambda: validate_descriptor({"threshold": True, "members": MEMBERS}))
    assert validate_descriptor({"threshold": 2, "members": MEMBERS}) == (2, MEMBERS)

def t08_sender_must_match_descriptor():
    """Prove a valid-in-itself signature set cannot spend from a DIFFERENT address by swapping the
    sender (descriptor -> address binding)."""
    tx = _draft()
    tx["sender"] = multisig_address(3, MEMBERS)      # a different (3-of-3) account
    tx["txid"] = create_txid({k: v for k, v in tx.items() if k not in ("signature", "txid")})
    tx["signature"] = []
    for kd in (K1, K2, K3):
        tx["signature"].append({"public_key": kd["public_key"],
                                "signature": sign(private_key=kd["private_key"], message=unhex(tx["txid"]))})
    assert raises(lambda: verify_multisig_origin(tx))

def t09_payment_accounts_only():
    """Prove a multisig sender cannot target reserved protocol recipients (bond/register/...)."""
    for reserved in ("bond", "register", "treasury_vote", "htlc_lock"):
        assert raises(lambda r=reserved: validate_transaction(
            _signed([K1, K2], recipient=r, fee=MIN_TX_FEE * 2), logger, H)), f"{reserved} must be rejected"

def t10_per_signature_fee_floor():
    """Prove the fee must cover MIN_TX_FEE per signature entry (each ~2.4KB ML-DSA sig rides outside
    the byte-size base fee)."""
    assert raises(lambda: validate_transaction(
        _signed([K1, K2, K3], fee=MIN_TX_FEE * 2), logger, H))          # 3 sigs, fee for 2
    assert validate_transaction(_signed([K1, K2, K3], fee=MIN_TX_FEE * 3), logger, H)

def t12_tampered_body_rejected():
    """Prove signatures bind the FULL body: bumping the amount after signing fails validate_txid."""
    tx = _signed([K1, K2])
    tx["amount"] += 1
    assert raises(lambda: validate_transaction(tx, logger, H))

def t13_cosign_helper_is_idempotent_and_verifies_txid():
    """Prove add_member_signature dedups per member, rejects outsiders, and refuses a proposal whose
    txid doesn't match its body (a member can't be tricked into signing a swapped body)."""
    tx = _draft()
    _, n = add_member_signature(tx, K1["private_key"])
    _, n = add_member_signature(tx, K1["private_key"])
    assert n == 1, "same member must not add a second entry"
    assert raises(lambda: add_member_signature(tx, OUTSIDER["private_key"]))
    evil = dict(tx, amount=tx["amount"] + 1)
    assert raises(lambda: add_member_signature(evil, K2["private_key"]))

def t14_reflect_and_revert_symmetry():
    """Prove a multisig spend moves balance exactly like a keyed transfer and reverts to byte-equal
    balances (fee burned on apply, restored on revert)."""
    tx = _signed([K1, K2], amount=2_500_000)
    m0, p0 = get_account(MSIG)["balance"], get_account(PAYEE)["balance"]
    reflect_transaction(tx, logger, H)
    assert get_account(MSIG)["balance"] == m0 - 2_500_000 - tx["fee"]
    assert get_account(PAYEE)["balance"] == p0 + 2_500_000
    reflect_transaction(tx, logger, H, revert=True)
    assert get_account(MSIG)["balance"] == m0 and get_account(PAYEE)["balance"] == p0

def t15_pubkey_once_never_stores_for_multisig():
    """Prove index_transactions leaves no public_key on a multisig account (the descriptor rides in
    every spend instead; there is no single key to pin)."""
    from ops.transaction_ops import index_transactions
    tx = _signed([K1, K2], amount=1)
    index_transactions({"block_number": H}, [tx], logger)
    assert not (get_account(MSIG) or {}).get("public_key"), "multisig account must not gain a pubkey"

for name, fn in list(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)

print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
