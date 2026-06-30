"""
Equivocation slashing unit checks (#15, security step 5C).

- verify_equivocation_proof accepts two valid signatures by ONE identity over two DIFFERENT blocks at
  the SAME height+parent, and rejects non-conflicting / forged proofs.
- A slash tx burns SLASH_BOND_PENALTY of the offender's bonded stake, is replay-guarded
  (one-per-(offender,height)), and is REVERT-SYMMETRIC (rollback restores the bond + clears the guard).
"""
import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_slash_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(os.path.expanduser(f"~/nado/{d}"), exist_ok=True)

import logging
logger = logging.getLogger("slash"); logger.addHandler(logging.NullHandler())

from genesis import create_indexers
create_indexers()

from ops import kv_ops
from ops.account_ops import create_account, get_account, reflect_transaction
from ops.transaction_ops import create_txid, validate_transaction
from ops.block_ops import _block_sig_message_fields, verify_equivocation_proof
from Curve25519 import generate_keydict, sign, unhex
from protocol import B_MIN, SLASH_BOND_PENALTY, CHAIN_ID

fails = 0
def check(name, fn):
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

offender = generate_keydict()
NUM, PARENT, HA, HB = 100, "p" * 64, "a" * 64, "b" * 64

def mkproof(ha=HA, hb=HB, num=NUM, parent=PARENT, kd=offender):
    return {"block_number": num, "parent_hash": parent, "public_key": kd["public_key"],
            "block_hash_a": ha, "signature_a": sign(kd["private_key"], _block_sig_message_fields(num, parent, ha)),
            "block_hash_b": hb, "signature_b": sign(kd["private_key"], _block_sig_message_fields(num, parent, hb))}


def t1():
    assert verify_equivocation_proof(mkproof()) == (offender["address"], NUM), "valid proof must resolve offender+height"
check("valid equivocation proof -> (offender, height)", t1)

def t2():
    assert verify_equivocation_proof(mkproof(hb=HA)) is None, "same block hash is not equivocation"
check("non-conflicting (same block hash) -> rejected", t2)

def t3():
    p = mkproof(); p["signature_b"] = p["signature_b"][:-4] + ("1111" if p["signature_b"][-4:] != "1111" else "2222")
    assert verify_equivocation_proof(p) is None, "a forged/tampered signature must be rejected"
check("tampered signature -> rejected", t3)


def t4_end_to_end():
    create_account(offender["address"], bonded=5 * B_MIN)        # offender holds stake
    reporter = generate_keydict()
    proof = mkproof()
    tx = {"sender": reporter["address"], "recipient": "slash", "amount": 0, "timestamp": 1, "data": proof,
          "nonce": "s1", "public_key": reporter["public_key"], "target_block": 105, "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx); tx["signature"] = sign(reporter["private_key"], unhex(tx["txid"]))

    assert validate_transaction(tx, logger, block_height=100), "valid slash tx must validate"

    before = get_account(offender["address"])["bonded"]
    with kv_ops.write_txn():
        reflect_transaction(tx, logger=logger, block_height=100)
    assert get_account(offender["address"])["bonded"] == before - SLASH_BOND_PENALTY, "bond not burned"
    assert kv_ops.slash_exists(offender["address"], NUM), "slash not recorded"

    # replay: the same offence can't be slashed twice
    try:
        validate_transaction(tx, logger, block_height=100); raise RuntimeError("replay accepted")
    except AssertionError as e:
        assert "already slashed" in str(e)

    # revert: rollback restores the bond + clears the guard (revert-symmetric)
    with kv_ops.write_txn():
        reflect_transaction(tx, logger=logger, revert=True, block_height=100)
    assert get_account(offender["address"])["bonded"] == before, "bond not restored on revert"
    assert not kv_ops.slash_exists(offender["address"], NUM), "slash guard not cleared on revert"
check("slash tx burns bond, replay-guarded, revert-symmetric", t4_end_to_end)


def t5_insufficient_bond():
    poor = generate_keydict(); create_account(poor["address"], bonded=0)
    proof = mkproof(kd=poor)
    reporter = generate_keydict()
    tx = {"sender": reporter["address"], "recipient": "slash", "amount": 0, "timestamp": 1, "data": proof,
          "nonce": "s2", "public_key": reporter["public_key"], "target_block": 105, "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx); tx["signature"] = sign(reporter["private_key"], unhex(tx["txid"]))
    try:
        validate_transaction(tx, logger, block_height=100); raise RuntimeError("slash of unbonded accepted")
    except AssertionError as e:
        assert "insufficient bonded" in str(e)
check("slash of an offender with no bond -> rejected (keeps apply floor-free)", t5_insufficient_bond)


print(f"\n{'ALL SLASHING CHECKS PASSED' if not fails else str(fails) + ' FAILURE(S)'}")
sys.exit(1 if fails else 0)
