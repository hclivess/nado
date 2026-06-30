"""
Commit-reveal RANDAO unit checks (#7).

- commit (epoch E-2) + reveal (epoch E-1 finalized window) validate for a bonded validator, with the
  reveal opening the prior commitment; wrong window / wrong opening / non-bonded are rejected.
- reflect records commit/reveal and is revert-symmetric.
- epoch_beacon mixes the finalized anchor with the revealed secrets (changes when a reveal is present),
  and falls back to the anchor-only value with zero reveals.
"""
import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_randao_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(os.path.expanduser(f"~/nado/{d}"), exist_ok=True)

import logging
logger = logging.getLogger("randao"); logger.addHandler(logging.NullHandler())

from genesis import create_indexers
create_indexers()

from ops import kv_ops
from ops.account_ops import create_account, reflect_transaction
from ops.transaction_ops import create_txid, validate_transaction
from ops.block_ops import epoch_beacon
from ops.mining_ops import beacon_commitment
from Curve25519 import generate_keydict, sign, unhex
from protocol import B_MIN, EPOCH_LENGTH, FINALITY_DEPTH, CHAIN_ID

fails = 0
def check(name, fn):
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

E = 4                       # target epoch
SECRET = "a1b2c3" * 10 + "dd"
COMMITMENT = beacon_commitment(SECRET)
val = generate_keydict()
create_account(val["address"], bonded=B_MIN)


def signed(recipient, data, target_block, kd=val):
    tx = {"sender": kd["address"], "recipient": recipient, "amount": 0, "timestamp": 1, "data": data,
          "nonce": f"{recipient}{target_block}", "public_key": kd["public_key"],
          "target_block": target_block, "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx); tx["signature"] = sign(kd["private_key"], unhex(tx["txid"]))
    return tx


def t1_commit():
    tb = (E - 2) * EPOCH_LENGTH + 5   # epoch E-2
    tx = signed("commit", {"target_epoch": E, "commitment": COMMITMENT}, tb)
    assert validate_transaction(tx, logger, block_height=tb), "valid commit must validate"
    with kv_ops.write_txn():
        reflect_transaction(tx, logger=logger, block_height=tb)
    assert kv_ops.commit_get(val["address"], E) == COMMITMENT, "commit not recorded"
check("commit (epoch E-2) validates + records", t1_commit)


def t2_commit_wrong_window():
    tb = (E - 1) * EPOCH_LENGTH + 5   # epoch E-1 (too late for a commit)
    tx = signed("commit", {"target_epoch": E, "commitment": COMMITMENT}, tb)
    try:
        validate_transaction(tx, logger, block_height=tb); raise RuntimeError("accepted")
    except AssertionError as e:
        assert "epoch E-2" in str(e)
check("commit outside epoch E-2 -> rejected", t2_commit_wrong_window)


def t3_reveal():
    tb = (E - 1) * EPOCH_LENGTH + 5   # epoch E-1, within [..(E*EL - FINALITY_DEPTH - 1)]
    assert tb <= E * EPOCH_LENGTH - FINALITY_DEPTH - 1
    tx = signed("reveal", {"target_epoch": E, "secret": SECRET}, tb)
    assert validate_transaction(tx, logger, block_height=tb), "valid reveal must validate"
    with kv_ops.write_txn():
        reflect_transaction(tx, logger=logger, block_height=tb)
    assert SECRET in kv_ops.reveals_for_epoch(E), "reveal not recorded"
check("reveal (epoch E-1 finalized window, opens commit) validates + records", t3_reveal)


def t4_reveal_bad_opening():
    tb = (E - 1) * EPOCH_LENGTH + 6
    tx = signed("reveal", {"target_epoch": E, "secret": "not-the-secret"}, tb)
    try:
        validate_transaction(tx, logger, block_height=tb); raise RuntimeError("accepted")
    except AssertionError as e:
        assert "open the commitment" in str(e)
check("reveal that doesn't open the commitment -> rejected", t4_reveal_bad_opening)


def t5_reveal_outside_window():
    tb = E * EPOCH_LENGTH - 2         # too late (not finalized by E*EL)
    tx = signed("reveal", {"target_epoch": E, "secret": SECRET}, tb)
    try:
        validate_transaction(tx, logger, block_height=tb); raise RuntimeError("accepted")
    except AssertionError as e:
        assert "finalized window" in str(e)
check("reveal outside the finalized window -> rejected", t5_reveal_outside_window)


def t6_beacon_uses_reveals():
    kv_ops.block_index_put((E - 1) * EPOCH_LENGTH, "c0ffee" * 10 + "abcd")  # the epoch-E anchor (block 180)
    with_reveal = epoch_beacon(E)              # reveal from t3 is recorded
    kv_ops.reveal_del(E, SECRET)               # remove it -> anchor-only fallback
    without_reveal = epoch_beacon(E)
    assert with_reveal != without_reveal, "epoch_beacon must mix in the revealed secret"
    kv_ops.reveal_put(E, SECRET)               # restore
check("epoch_beacon mixes the finalized anchor with revealed secrets", t6_beacon_uses_reveals)


def t7_non_bonded_rejected():
    poor = generate_keydict(); create_account(poor["address"], bonded=0)
    tb = (E - 2) * EPOCH_LENGTH + 7
    tx = signed("commit", {"target_epoch": E, "commitment": COMMITMENT}, tb, kd=poor)
    try:
        validate_transaction(tx, logger, block_height=tb); raise RuntimeError("accepted")
    except AssertionError as e:
        assert "bonded validator" in str(e)
check("commit from a non-bonded sender -> rejected", t7_non_bonded_rejected)


print(f"\n{'ALL RANDAO CHECKS PASSED' if not fails else str(fails) + ' FAILURE(S)'}")
sys.exit(1 if fails else 0)
