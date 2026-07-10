"""
Unbond-delay unit checks (BOND_UNLOCK_DELAY enforcement).

- `unbond` is a REQUEST: it records a pending withdrawal (release_block = h + BOND_UNLOCK_DELAY) and the
  coins STAY in `bonded` (so they remain slashable + weighted) — it does NOT touch balance.
- `withdraw` releases bonded -> spendable balance only at/after the matured release_block.
- one pending unbond per address; revert-symmetric.
"""
import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_unbond_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(os.path.expanduser(f"~/nado/{d}"), exist_ok=True)

import logging
logger = logging.getLogger("unbond"); logger.addHandler(logging.NullHandler())

from genesis import create_indexers
create_indexers()

from ops import kv_ops
from ops.account_ops import create_account, get_account, reflect_transaction
from ops.transaction_ops import create_txid, validate_transaction
from Curve25519 import generate_keydict, sign, unhex
from protocol import B_MIN, BOND_UNLOCK_DELAY, CHAIN_ID

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

val = generate_keydict()
create_account(val["address"], bonded=5 * B_MIN)
H = 100  # the block the unbond lands in


def signed(recipient, amount, data, max_block):
    """Build a signed transaction from val to recipient (txid computed, signature attached)."""
    tx = {"sender": val["address"], "recipient": recipient, "amount": amount, "timestamp": 1, "data": data,
          "nonce": f"{recipient}{max_block}", "public_key": val["public_key"],
          "max_block": max_block, "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx); tx["signature"] = sign(val["private_key"], unhex(tx["txid"]))
    return tx


def t1_unbond_is_a_request():
    """Prove unbond only records a pending release (release_block = h + BOND_UNLOCK_DELAY): coins stay bonded, balance untouched."""
    tx = signed("unbond", 2 * B_MIN, "", H)
    assert validate_transaction(tx, logger, block_height=H), "valid unbond must validate"
    with kv_ops.write_txn():
        reflect_transaction(tx, logger=logger, block_height=H)
    acc = get_account(val["address"])
    # coins STAY bonded (still slashable + weighted); balance untouched
    assert acc["bonded"] == 5 * B_MIN, "unbond must NOT remove coins from bonded (they stay slashable)"
    assert acc["balance"] == 0, "unbond must NOT credit spendable balance"
    pending = kv_ops.unbond_get(val["address"])
    assert pending == {"amount": 2 * B_MIN, "release_block": H + BOND_UNLOCK_DELAY}, "pending unbond not recorded"
check("unbond records a pending release; coins stay bonded (slashable)", t1_unbond_is_a_request)


def t2_one_pending_only():
    """Prove a second unbond while one is pending is rejected ('already pending')."""
    tx = signed("unbond", B_MIN, "", H + 1)
    try:
        validate_transaction(tx, logger, block_height=H + 1); raise RuntimeError("second unbond accepted")
    except AssertionError as e:
        assert "already pending" in str(e)
check("a second unbond while one is pending -> rejected", t2_one_pending_only)


def t3_withdraw_before_maturity():
    """Prove a withdraw before the release_block matures is rejected ('not matured')."""
    pending = kv_ops.unbond_get(val["address"])
    tx = signed("withdraw", 0, {"amount": pending["amount"], "release_block": pending["release_block"]},
                pending["release_block"] - 1)  # max_block BEFORE maturity
    try:
        validate_transaction(tx, logger, block_height=H + 5); raise RuntimeError("premature withdraw accepted")
    except AssertionError as e:
        assert "not matured" in str(e)
check("withdraw before BOND_UNLOCK_DELAY matures -> rejected", t3_withdraw_before_maturity)


def t4_withdraw_at_maturity():
    """Prove a matured withdraw moves the amount bonded -> spendable balance and clears the pending unbond."""
    pending = kv_ops.unbond_get(val["address"])
    rel = pending["release_block"]
    tx = signed("withdraw", 0, {"amount": pending["amount"], "release_block": rel}, rel)  # matured
    assert validate_transaction(tx, logger, block_height=rel), "matured withdraw must validate"
    with kv_ops.write_txn():
        reflect_transaction(tx, logger=logger, block_height=rel)
    acc = get_account(val["address"])
    assert acc["bonded"] == 3 * B_MIN, "withdraw must move the amount out of bonded"
    assert acc["balance"] == 2 * B_MIN, "withdraw must credit spendable balance"
    assert kv_ops.unbond_get(val["address"]) is None, "pending unbond not cleared after withdraw"
check("withdraw at maturity releases bonded -> balance", t4_withdraw_at_maturity)


def t5_revert_symmetric():
    """Prove reverting an unbond clears the pending record and leaves bonded unchanged (revert symmetry)."""
    create_account("rev" + val["address"][3:], bonded=4 * B_MIN)  # fresh-ish sender via reuse not needed
    v2 = generate_keydict(); create_account(v2["address"], bonded=4 * B_MIN)
    before = get_account(v2["address"])["bonded"]
    tx = {"sender": v2["address"], "recipient": "unbond", "amount": B_MIN, "timestamp": 1, "data": "",
          "nonce": "u", "public_key": v2["public_key"], "max_block": 200, "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx); tx["signature"] = sign(v2["private_key"], unhex(tx["txid"]))
    with kv_ops.write_txn():
        reflect_transaction(tx, logger=logger, block_height=200)
    assert kv_ops.unbond_get(v2["address"]) is not None
    with kv_ops.write_txn():
        reflect_transaction(tx, logger=logger, revert=True, block_height=200)
    assert kv_ops.unbond_get(v2["address"]) is None, "revert must clear the pending unbond"
    assert get_account(v2["address"])["bonded"] == before, "revert must leave bonded unchanged"
check("unbond is revert-symmetric (pending cleared, bonded unchanged)", t5_revert_symmetric)


print(f"\n{'ALL UNBOND-DELAY CHECKS PASSED' if not fails else str(fails) + ' FAILURE(S)'}")
sys.exit(1 if fails else 0)
