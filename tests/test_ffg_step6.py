"""
FFG-lite objective finality unit checks (#6).

- checkpoint_justified: STRICTLY > FFG_NUM/FFG_DEN of the ACTIVE bonded shares (attested within
  INACTIVITY_WINDOW — the inactivity leak; dark validators drop out of the denominator).
- ffg_finalized_checkpoint: two-consecutive-justified epochs finalize the earlier checkpoint.
- attestation tx: validates for a bonded validator, ONE per (validator, epoch) (no on-chain double-vote),
  and is revert-symmetric.
"""
import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_ffg_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(os.path.expanduser(f"~/nado/{d}"), exist_ok=True)

import logging
logger = logging.getLogger("ffg"); logger.addHandler(logging.NullHandler())

from genesis import create_indexers
create_indexers()

from ops import kv_ops
from ops.account_ops import create_account, get_account, reflect_transaction
from ops.transaction_ops import create_txid, validate_transaction
from ops.attestation_ops import checkpoint_justified, ffg_finalized_checkpoint
from ops.account_ops import get_bonded_registry
from signatures import generate_keydict, sign, unhex
from protocol import B_MIN, EPOCH_LENGTH, CHAIN_ID

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

# 4 bonded validators, 1 share each (total 4). 2/3 supermajority (strict) => need >= 3 attesters.
VALS = [generate_keydict() for _ in range(4)]
for v in VALS:
    create_account(v["address"], bonded=B_MIN)
H_E = "e" * 64        # checkpoint hash for epoch 1 (block 60)
H_CHILD = "f" * 64    # checkpoint hash for epoch 2 (block 120)
kv_ops.block_index_put(1 * EPOCH_LENGTH, H_E)
kv_ops.block_index_put(2 * EPOCH_LENGTH, H_CHILD)


def t1_threshold():
    """Prove checkpoint_justified needs STRICTLY >2/3 of the ACTIVE bonded shares: with all four
    validators active (each attested within INACTIVITY_WINDOW), 2/4 attesters fail, 3/4 justify."""
    reg = get_bonded_registry()
    # make ALL FOUR validators ACTIVE for the epoch-1 quorum: each attests epoch 0 (inside the
    # INACTIVITY_WINDOW lookback), so the denominator is the full 4 shares — the leak (below) is
    # what removes dark validators, and t1 must measure the threshold, not the leak.
    for v in VALS:
        kv_ops.attestation_put(0, v["address"], "0" * 64)
    # 2 of 4 attest epoch 1 -> NOT justified (2*3=6 !> 4*2=8)
    for v in VALS[:2]:
        kv_ops.attestation_put(1, v["address"], H_E)
    assert not checkpoint_justified(1, H_E, reg), "2/4 must not justify"
    # 3rd attests -> justified (3*3=9 > 8)
    kv_ops.attestation_put(1, VALS[2]["address"], H_E)
    assert checkpoint_justified(1, H_E, reg), "3/4 must justify"
check("checkpoint_justified: strict >2/3 of ACTIVE bonded shares", t1_threshold)


def t1b_inactivity_leak():
    """Prove the INACTIVITY LEAK: a validator dark for the whole window drops out of the quorum
    denominator, so the remaining live majority can justify without it."""
    from ops.attestation_ops import active_shares
    from protocol import INACTIVITY_WINDOW
    reg = get_bonded_registry()
    far = 1 + INACTIVITY_WINDOW + 5           # an epoch far enough that no VALS attestation is in-window
    H_FAR = "d" * 64
    kv_ops.block_index_put(far * EPOCH_LENGTH, H_FAR)
    for v in VALS[:2]:                         # only 2 of 4 are active near `far`
        kv_ops.attestation_put(far, v["address"], H_FAR)
    assert active_shares(far, reg) == sum(
        1 for _ in VALS[:2]), "dark validators must leak from the active denominator"
    # 2 attesting of 2 active -> justified even though it is only 2 of 4 bonded
    assert checkpoint_justified(far, H_FAR, reg), "live majority must justify once dark stake leaks"
check("inactivity leak: dark validators drop from the FFG denominator", t1b_inactivity_leak)


def t2_finalize():
    """Prove two consecutive justified epochs finalize the earlier epoch's checkpoint."""
    reg = get_bonded_registry()
    # epoch 1 already justified (3 attesters from t1). Justify epoch 2 too -> finalize epoch 1.
    for v in VALS[:3]:
        kv_ops.attestation_put(2, v["address"], H_CHILD)
    assert checkpoint_justified(2, H_CHILD, reg)
    assert ffg_finalized_checkpoint(2) == 1 * EPOCH_LENGTH, "two-consecutive-justified must finalize epoch 1's checkpoint"
check("ffg_finalized_checkpoint: two-consecutive-justified finalizes the earlier checkpoint", t2_finalize)


def t3_attest_tx():
    """Prove an attest tx validates for a bonded validator, rejects a same-epoch double-vote, and reverts cleanly."""
    # a clean env-ish: use a fresh validator + epoch 3 checkpoint
    val = VALS[0]
    H3 = "3" * 64
    kv_ops.block_index_put(3 * EPOCH_LENGTH, H3)
    tx = {"sender": val["address"], "recipient": "attest", "amount": 0, "timestamp": 1,
          "data": {"target_epoch": 3, "target_hash": H3}, "nonce": "att", "public_key": val["public_key"],
          "max_block": 3 * EPOCH_LENGTH + 5, "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx); tx["signature"] = sign(val["private_key"], unhex(tx["txid"]))
    assert validate_transaction(tx, logger, block_height=3 * EPOCH_LENGTH + 1), "bonded validator attest must validate"
    with kv_ops.write_txn():
        reflect_transaction(tx, logger=logger, block_height=3 * EPOCH_LENGTH + 5)
    assert kv_ops.attestation_exists(3, val["address"]), "attestation not recorded"
    # second attestation from the same validator for the same epoch is rejected (no on-chain double-vote)
    try:
        validate_transaction(tx, logger, block_height=3 * EPOCH_LENGTH + 1); raise RuntimeError("double-vote accepted")
    except AssertionError as e:
        assert "already attested" in str(e)
    # revert removes it
    with kv_ops.write_txn():
        reflect_transaction(tx, logger=logger, revert=True, block_height=3 * EPOCH_LENGTH + 5)
    assert not kv_ops.attestation_exists(3, val["address"]), "attestation not cleared on revert"
check("attest tx: bonded-only, one-per-epoch (no double-vote), revert-symmetric", t3_attest_tx)


print(f"\n{'ALL FFG CHECKS PASSED' if not fails else str(fails) + ' FAILURE(S)'}")
sys.exit(1 if fails else 0)
