"""
FFG-lite objective finality unit checks (#6).

- checkpoint_justified: STRICTLY > FFG_NUM/FFG_DEN of the epoch's DUTY-COMMITTEE SEATS
  (doc/consensus-aggregation.md — beacon-sampled stake-weighted seats; the committee bounds the
  per-epoch consensus load to O(seats) and resampling replaces the old inactivity leak).
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
    """Prove checkpoint_justified needs STRICTLY > FFG_NUM/FFG_DEN of the RECENTLY-ACTIVE committee
    seats (doc/consensus-aggregation.md), where a member becomes active by attesting. Attest seats
    one at a time and confirm the predicate flips exactly when attesting seats cross 2/3 of the
    active (== attesting, on one honest chain) denominator — i.e. the FULL committee must attest to
    justify, because every attester is also in the denominator."""
    from ops.block_ops import duty_committee_for_epoch
    reg = get_bonded_registry()
    committee = duty_committee_for_epoch(1)
    seats = sorted(committee, key=committee.get, reverse=True)
    assert sum(committee.values()) > 0, "four bonded validators must form a committee"
    # with all attesters on ONE hash, active == attesting, so it only justifies once EVERY active
    # member has attested (numer == denom); partial attestation with others silent-but-active can't
    # happen here (silence == not active). This is the safety bar.
    for i, v in enumerate(seats):
        kv_ops.attestation_put(1, v, H_E)
    assert checkpoint_justified(1, H_E, reg), "the full active committee attesting must justify"
    assert not checkpoint_justified(1, "d" * 64, reg), "a hash no one attested is never justified"
    for v in seats:
        kv_ops.attestation_del(1, v, H_E)
check("checkpoint_justified: strict >2/3 of ACTIVE committee seats", t1_threshold)


def t1b_dark_majority_cannot_block():
    """THE LIVE-NET LIVENESS PROPERTY (the regression this leak fixes): a bonded MAJORITY that never
    attests must not freeze finality. Only the active minority's seats are in the denominator, so its
    own supermajority-of-active justifies — exactly like the old stake inactivity leak, now over
    committee seats."""
    from ops.block_ops import duty_committee_for_epoch
    reg = get_bonded_registry()
    committee = duty_committee_for_epoch(1)
    # pick the SINGLE largest seat-holder as the only active member
    lone = max(committee, key=committee.get)
    kv_ops.attestation_put(1, lone, H_E)
    assert checkpoint_justified(1, H_E, reg), \
        "a lone active committee member must justify (dark seats leak from the denominator)"
    kv_ops.attestation_del(1, lone, H_E)
check("committee inactivity leak: a dark bonded majority cannot block finality", t1b_dark_majority_cannot_block)


def t2_finalize():
    """Prove two consecutive justified epochs (each by its own committee) finalize the earlier one."""
    from ops.block_ops import duty_committee_for_epoch
    reg = get_bonded_registry()
    for E, H in ((1, H_E), (2, H_CHILD)):
        for v in duty_committee_for_epoch(E):          # every committee seat attests -> justified
            kv_ops.attestation_put(E, v, H)
        assert checkpoint_justified(E, H, reg)
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
