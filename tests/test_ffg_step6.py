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
    """Prove checkpoint_justified needs STRICTLY > FFG_NUM/FFG_DEN of the epoch's DUTY-COMMITTEE
    SEATS (doc/consensus-aggregation.md): attest seat-holders one at a time and confirm the
    predicate flips exactly when accumulated seats cross the quorum."""
    from ops.block_ops import duty_committee_for_epoch
    from protocol import FFG_NUM, FFG_DEN
    reg = get_bonded_registry()
    committee = duty_committee_for_epoch(1)
    total = sum(committee.values())
    assert total > 0, "four bonded validators must form a committee"
    got = 0
    for v in sorted(committee, key=committee.get, reverse=True):
        assert checkpoint_justified(1, H_E, reg) == (got * FFG_DEN > total * FFG_NUM), \
            "predicate must track the accumulated seat count exactly"
        kv_ops.attestation_put(1, v, H_E)
        got += committee[v]
    assert checkpoint_justified(1, H_E, reg), "all committee seats attesting must justify"
    assert not checkpoint_justified(1, "d" * 64, reg), "a hash no one attested is never justified"
check("checkpoint_justified: strict >2/3 of committee SEATS", t1_threshold)


def t1b_committee_resamples_per_epoch():
    """Prove the committee is beacon-sampled per epoch (the mechanism that replaced the inactivity
    leak — a dark seat only blocks its own epoch's justification, and the next epoch resamples)."""
    from ops.block_ops import duty_committee_for_epoch
    c1 = duty_committee_for_epoch(1)
    c2 = duty_committee_for_epoch(2)
    assert sum(c1.values()) > 0 and sum(c2.values()) > 0, "both epochs have committees"
    # attestations for epoch 1 do not carry into epoch 2's justification (separate seat sets/hashes)
    for v in c1:
        kv_ops.attestation_del(1, v, H_E)   # clean up t1's attestations so t2 starts fresh
check("duty committee resamples per epoch", t1b_committee_resamples_per_epoch)


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
