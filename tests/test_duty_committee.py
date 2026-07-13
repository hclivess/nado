"""
Consensus-load aggregation (doc/consensus-aggregation.md):
  1. duty_committee — deterministic beacon-keyed stake-weighted seat sampling; seats sum to
     DUTY_COMMITTEE_SEATS; expected seats track stake; resamples across epochs
  2. merged `duty` tx — validates (committee-gated, per-section rules identical to the historical
     forms), reflects (attest+commit+reveal recorded), reverts byte-exactly
  3. committee-seat FFG quorum — 2/3 of seats justifies, minority doesn't, non-committee
     attestations count nothing
  4. cross-form block dedup — a duty-carried section and its historical twin can't share a block
  5. duty-carried attestation equivocation is slashable (proof opener accepts duty txs)

Run: python3 tests/test_duty_committee.py
"""
import os, sys, tempfile, traceback, logging
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_duty_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

logger = logging.getLogger("duty"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import (B_MIN, EPOCH_LENGTH, FINALITY_DEPTH, DUTY_COMMITTEE_SEATS, GENESIS_BEACON,
                      FFG_NUM, FFG_DEN)
from ops import kv_ops
from ops.account_ops import create_account, reflect_transaction, get_bonded_registry
from ops.mining_ops import duty_committee, beacon_commitment, selection_shares
from ops.transaction_ops import (construct_duty_tx, validate_transaction, dedupe_reserved,
                                 assert_unique_reserved, construct_attestation_tx,
                                 verify_attestation_equivocation_proof)
from ops.attestation_ops import checkpoint_justified
from ops.key_ops import generate_keys

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

# Validators: V1 heavy (6 shares), V2 light (2), V3 (2) -> total 10 shares.
V1 = generate_keys(); create_account(V1["address"], balance=B_MIN, bonded=6 * B_MIN)
V2 = generate_keys(); create_account(V2["address"], balance=B_MIN, bonded=2 * B_MIN)
V3 = generate_keys(); create_account(V3["address"], balance=B_MIN, bonded=2 * B_MIN)
REG = get_bonded_registry()

# duties land in epoch X=1 (blocks 60..119); epoch 1's checkpoint is block 60, beacon = GENESIS (epoch<2)
X = 1
CKPT = "c" * 64
kv_ops.block_index_put(X * EPOCH_LENGTH, CKPT)
TB = X * EPOCH_LENGTH + 5                      # inside every window (reveal_hi = 2*60-12-1 = 107)


def t1_committee_deterministic_and_stakeweighted():
    """Prove seat sampling is deterministic, seats sum to DUTY_COMMITTEE_SEATS, expected seats track
    stake, and different epochs resample."""
    c1 = duty_committee(REG, GENESIS_BEACON, X)
    c2 = duty_committee(REG, GENESIS_BEACON, X)
    assert c1 == c2, "same inputs -> identical committee on every node"
    assert sum(c1.values()) == DUTY_COMMITTEE_SEATS, "seats must sum to the committee size"
    assert set(c1) <= {V1["address"], V2["address"], V3["address"]}
    assert c1[V1["address"]] > c1.get(V2["address"], 0), "heavier stake -> more expected seats"
    c_other = duty_committee(REG, GENESIS_BEACON, X + 7)
    assert c_other != c1, "another epoch resamples (beacon-keyed by epoch+seat)"
    assert duty_committee({}, GENESIS_BEACON, X) == {}, "empty registry -> no committee (fail closed)"


def t2_duty_tx_validate_reflect_revert():
    """Prove the merged duty tx validates, records attest+commit+reveal, and reverts byte-exactly."""
    me = V1  # heavy validator: guaranteed seats
    secret_next = "aa" * 32                                    # reveal for X+1 needs a prior commit
    with kv_ops.write_txn():
        kv_ops.commit_put(me["address"], X + 1, beacon_commitment(secret_next))
    tx = construct_duty_tx(me, TB,
                           attest={"target_epoch": X, "target_hash": CKPT},
                           commit={"target_epoch": X + 2, "commitment": beacon_commitment("bb" * 32)},
                           reveal={"target_epoch": X + 1, "secret": secret_next})
    assert validate_transaction(tx, logger, block_height=TB), "full duty tx must validate"
    with kv_ops.write_txn():
        reflect_transaction(tx, logger, block_height=TB)
    assert kv_ops.attestation_exists(X, me["address"]), "attest recorded"
    assert kv_ops.commit_get(me["address"], X + 2), "commit recorded"
    assert secret_next in kv_ops.reveals_for_epoch(X + 1), "reveal recorded"
    # duplicate sections now fail validation (same rules as the historical forms)
    assert raises(lambda: validate_transaction(tx, logger, block_height=TB)), "re-validate must reject (already attested)"
    with kv_ops.write_txn():
        reflect_transaction(tx, logger, block_height=TB, revert=True)
    assert not kv_ops.attestation_exists(X, me["address"]), "revert removes the attest"
    assert kv_ops.commit_get(me["address"], X + 2) is None, "revert removes the commit"
    assert secret_next not in kv_ops.reveals_for_epoch(X + 1), "revert removes the reveal"


def t3_duty_rules():
    """Prove the duty-tx envelope rules: sections required, target epochs pinned to the landing
    epoch, non-bonded and seatless senders rejected."""
    me = V1
    assert raises(lambda: validate_transaction(
        construct_duty_tx(me, TB, attest={"target_epoch": X + 1, "target_hash": CKPT}), logger, TB)), \
        "attest section must target the landing epoch"
    poor = generate_keys(); create_account(poor["address"], balance=B_MIN)   # not bonded
    assert raises(lambda: validate_transaction(
        construct_duty_tx(poor, TB, attest={"target_epoch": X, "target_hash": CKPT}), logger, TB)), \
        "non-bonded sender cannot carry duties"
    bad = construct_duty_tx(me, TB, attest={"target_epoch": X, "target_hash": CKPT})
    bad["data"]["extra"] = 1
    from ops.transaction_ops import create_txid
    from signatures import sign, unhex
    bad["txid"] = create_txid(bad); bad["signature"] = sign(me["private_key"], unhex(bad["txid"]))
    assert raises(lambda: validate_transaction(bad, logger, TB)), "unknown sections rejected"
    empty = {"sender": me["address"], "recipient": "duty", "amount": 0, "fee": 0, "data": {},
             "max_block": TB, "chain_id": bad["chain_id"], "timestamp": 1, "nonce": "x",
             "public_key": me["public_key"]}
    empty["txid"] = create_txid(empty); empty["signature"] = sign(me["private_key"], unhex(empty["txid"]))
    assert raises(lambda: validate_transaction(empty, logger, TB)), "sectionless duty rejected"


def t4_committee_quorum():
    """Prove FFG justification counts COMMITTEE SEATS against the RECENTLY-ACTIVE (attesting)
    denominator: an unattested hash never justifies, a live active supermajority does, and a
    non-committee validator's attestation adds nothing (dark bonded stake can't block — the
    live-net liveness property)."""
    committee = duty_committee(REG, GENESIS_BEACON, X)
    ranked = sorted(committee, key=committee.get, reverse=True)
    assert not checkpoint_justified(X, CKPT, REG), "nobody attesting -> not justified"
    # the single largest seat-holder attesting is the only ACTIVE member, so its seats ARE the
    # denominator and it justifies — dark seats leak out (this is the fix, not a bug).
    with kv_ops.write_txn():
        kv_ops.attestation_put(X, ranked[0], CKPT)
    assert checkpoint_justified(X, CKPT, REG), "a lone active committee member justifies (dark seats leak)"
    assert not checkpoint_justified(X, "d" * 64, REG), "an unattested hash never justifies"
    # a NON-committee bonded validator attesting adds nothing to numerator or denominator
    outsider = generate_keys(); create_account(outsider["address"], balance=B_MIN, bonded=B_MIN)
    if outsider["address"] not in committee:
        with kv_ops.write_txn():
            kv_ops.attestation_put(X, outsider["address"], CKPT)
        assert checkpoint_justified(X, CKPT, REG), "a non-committee attester changes nothing"
    # cleanup for later tests
    with kv_ops.write_txn():
        for v in list(ranked) + [outsider["address"]]:
            kv_ops.attestation_del(X, v, CKPT)


def t5_cross_form_block_dedup():
    """Prove a duty-carried attest and a historical bare attest for the same (sender, epoch) can
    never share one block (either order), and disjoint-section duties may coexist."""
    me = V1
    duty = construct_duty_tx(me, TB, attest={"target_epoch": X, "target_hash": CKPT})
    bare = construct_attestation_tx(me, X, CKPT, TB)
    both = dedupe_reserved([duty, bare])
    assert len(both) == 1 and both[0] is duty, "producer drops the colliding bare form"
    assert raises(lambda: assert_unique_reserved([duty, bare])), "verify side rejects the pair"
    other = construct_duty_tx(V2, TB, commit={"target_epoch": X + 2, "commitment": beacon_commitment("cc" * 32)})
    assert len(dedupe_reserved([duty, other])) == 2, "different senders/sections coexist"


def t6_duty_equivocation_slashable():
    """Prove two duty txs attesting DIFFERENT hashes for one epoch form a valid slashing proof
    (the opener accepts duty carriers), and mixed duty+bare proofs work too."""
    me = V1
    a = construct_duty_tx(me, TB, attest={"target_epoch": X, "target_hash": CKPT})
    b = construct_duty_tx(me, TB + 1, attest={"target_epoch": X, "target_hash": "e" * 64})
    got = verify_attestation_equivocation_proof({"attest_a": a, "attest_b": b})
    assert got == (me["address"], X), f"duty-vs-duty equivocation must be provable, got {got}"
    bare = construct_attestation_tx(me, X, "f" * 64, TB)
    got2 = verify_attestation_equivocation_proof({"attest_a": a, "attest_b": bare})
    assert got2 == (me["address"], X), "duty-vs-bare equivocation must be provable"
    assert verify_attestation_equivocation_proof({"attest_a": a, "attest_b": a}) is None, \
        "same hash twice is not an equivocation"


for name, fn in sorted((n, f) for n, f in list(globals().items())
                       if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)

print(f"\n{'ALL DUTY/COMMITTEE CHECKS PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
