"""
Alias system (ops/alias_ops + transaction_ops + account_ops): on-chain register / transfer /
unregister, send-to-alias resolution (a transfer whose recipient is a registered alias credits the
alias's current owner), owner-only transfer/unregister, name validation, and revert-symmetry.

Run: python3 tests/test_alias.py
"""
import os, sys, tempfile, traceback, logging
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_alias_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

logger = logging.getLogger("alias"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import ALIAS_REGISTRATION_FEE, MIN_TX_FEE, CHAIN_ID
from ops import kv_ops, alias_ops
from ops.account_ops import create_account, get_account, reflect_transaction
from ops.transaction_ops import construct_alias_tx, validate_transaction, create_txid, create_nonce
from ops.key_ops import generate_keys
from config import get_timestamp_seconds
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

def _key(bal):
    """Fund a fresh keypair with balance bal and return its key dict."""
    kd = generate_keys(); create_account(kd["address"], balance=bal); return kd
def _bal(a):
    """Spendable balance of address a."""
    return get_account(a)["balance"]

def _transfer_tx(kd, recipient, amount, fee, max_block=1):
    """Build a signed plain transfer tx from keypair kd to recipient."""
    tx = {"sender": kd["address"], "recipient": recipient, "amount": int(amount),
          "timestamp": get_timestamp_seconds(), "data": "", "nonce": create_nonce(),
          "public_key": kd["public_key"], "max_block": int(max_block),
          "chain_id": CHAIN_ID, "fee": int(fee)}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=kd["private_key"], message=unhex(tx["txid"]))
    return tx

# shared actors
A = _key(ALIAS_REGISTRATION_FEE * 10)
B = _key(ALIAS_REGISTRATION_FEE * 10)
C = _key(1_000_000 + MIN_TX_FEE * 10)

def t1_register():
    """Prove alias registration sets the owner, charges the registration fee, and resolves."""
    tx = construct_alias_tx(A, "register", "alice", max_block=1, fee=ALIAS_REGISTRATION_FEE)
    validate_transaction(tx, logger, 1)
    before = _bal(A["address"])
    reflect_transaction(tx, logger, 1)
    assert kv_ops.alias_get("alice") == A["address"], "owner set"
    assert _bal(A["address"]) == before - ALIAS_REGISTRATION_FEE, "fee charged"
    assert alias_ops.resolve_alias("alice") == A["address"]

def t2_duplicate_register_rejected():
    """Prove registering an already-taken alias fails validation."""
    tx = construct_alias_tx(B, "register", "alice", max_block=1, fee=ALIAS_REGISTRATION_FEE)
    assert raises(lambda: validate_transaction(tx, logger, 1)), "already-registered must reject"

def t3_send_to_alias_credits_owner():
    """Prove a transfer addressed to a registered alias validates and credits the alias owner."""
    tx = _transfer_tx(C, "alice", amount=50_000, fee=MIN_TX_FEE, max_block=2)
    validate_transaction(tx, logger, 2)            # alias resolves -> valid recipient
    before = _bal(A["address"])
    reflect_transaction(tx, logger, 2)
    assert _bal(A["address"]) == before + 50_000, "owner credited via alias"

def t4_transfer_alias():
    """Prove alias ownership transfers to the new owner, who then receives sends to the alias."""
    tx = construct_alias_tx(A, "transfer", "alice", max_block=1, fee=MIN_TX_FEE, to=B["address"])
    validate_transaction(tx, logger, 1)
    reflect_transaction(tx, logger, 1)
    assert kv_ops.alias_get("alice") == B["address"], "ownership moved to B"
    # a send now credits B
    tx2 = _transfer_tx(C, "alice", amount=30_000, fee=MIN_TX_FEE, max_block=3)
    before = _bal(B["address"])
    reflect_transaction(tx2, logger, 3)
    assert _bal(B["address"]) == before + 30_000

def t5_non_owner_cannot_transfer_or_unregister():
    """Prove alias transfer and unregister are rejected when the sender is not the owner."""
    assert raises(lambda: validate_transaction(
        construct_alias_tx(C, "transfer", "alice", 1, MIN_TX_FEE, to=C["address"]), logger, 1)), "non-owner transfer"
    assert raises(lambda: validate_transaction(
        construct_alias_tx(C, "unregister", "alice", 1, MIN_TX_FEE), logger, 1)), "non-owner unregister"

def t6_unregister_frees_name():
    """Prove unregister frees the name and sends to the now-free alias are rejected."""
    tx = construct_alias_tx(B, "unregister", "alice", max_block=1, fee=MIN_TX_FEE)
    validate_transaction(tx, logger, 1)
    reflect_transaction(tx, logger, 1)
    assert kv_ops.alias_get("alice") is None, "freed"
    # send-to-(now-free) alias is rejected
    assert raises(lambda: validate_transaction(_transfer_tx(C, "alice", 1000, MIN_TX_FEE), logger, 4)), \
        "send to unregistered alias must reject"

def t7_name_validation():
    """Prove valid_alias_name rejects short/cased/reserved/malformed names and accepts good ones."""
    for bad in ("ab", "Alice", "bond", "alias", "ndofoo", "has space", "1abc", "a" * 33, "", 123):
        assert not alias_ops.valid_alias_name(bad), f"{bad!r} should be invalid"
    for good in ("alice", "shop_1", "my-name", "abc"):
        assert alias_ops.valid_alias_name(good), f"{good!r} should be valid"

def t8_revert_register():
    """Prove reverting a register clears the alias and refunds the registration fee."""
    before = _bal(A["address"])
    tx = construct_alias_tx(A, "register", "revtest", max_block=1, fee=ALIAS_REGISTRATION_FEE)
    reflect_transaction(tx, logger, 1)
    assert kv_ops.alias_get("revtest") == A["address"] and _bal(A["address"]) == before - ALIAS_REGISTRATION_FEE
    reflect_transaction(tx, logger, 1, revert=True)
    assert kv_ops.alias_get("revtest") is None, "revert clears the registration"
    assert _bal(A["address"]) == before, "revert refunds the fee"

def t9_revert_transfer_and_unregister():
    """Prove reverting a transfer or an unregister restores the prior alias owner."""
    # set up: A registers "movable"
    reflect_transaction(construct_alias_tx(A, "register", "movable", 1, ALIAS_REGISTRATION_FEE), logger, 1)
    # transfer to B, then revert -> back to A
    tt = construct_alias_tx(A, "transfer", "movable", 1, MIN_TX_FEE, to=B["address"])
    reflect_transaction(tt, logger, 1)
    assert kv_ops.alias_get("movable") == B["address"]
    reflect_transaction(tt, logger, 1, revert=True)
    assert kv_ops.alias_get("movable") == A["address"], "transfer revert restores prior owner"
    # unregister by A, then revert -> back to A
    tu = construct_alias_tx(A, "unregister", "movable", 1, MIN_TX_FEE)
    reflect_transaction(tu, logger, 1)
    assert kv_ops.alias_get("movable") is None
    reflect_transaction(tu, logger, 1, revert=True)
    assert kv_ops.alias_get("movable") == A["address"], "unregister revert restores owner"

def t10_send_to_alias_indexed_under_owner():
    """Prove a send-to-alias is indexed under the owner's address, not the alias string."""
    # a send-to-alias must be filed in the OWNER's tx index (where the coins landed), not under the
    # alias string — otherwise it never shows in the recipient's history.
    from ops.transaction_ops import index_transactions
    reflect_transaction(construct_alias_tx(A, "register", "histname", 1, ALIAS_REGISTRATION_FEE), logger, 6)
    tx = _transfer_tx(C, "histname", amount=12345, fee=MIN_TX_FEE, max_block=7)
    a_before = _bal(A["address"])
    index_transactions({"block_number": 7}, [tx], logger)
    assert _bal(A["address"]) == a_before + 12345, "owner credited"
    under_owner = [t for (_b, t) in kv_ops.tx_of_account(A["address"], 0, 100)]
    under_alias = [t for (_b, t) in kv_ops.tx_of_account("histname", 0, 100)]
    assert tx["txid"] in under_owner, "send-to-alias must be indexed under the owner's address"
    assert tx["txid"] not in under_alias, "must NOT be indexed under the alias string"

for name, fn in list(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)

print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
