"""
Bonded producer RAMP (anti-sudden-takeover) — consensus tests.

A newly-bonded identity's PRODUCER-selection weight ramps 0 -> full over BOND_RAMP_EPOCHS, by a STAKE-WEIGHTED
bond age. Covers: the ramp curve; unset age (genesis/pre-existing) = fully aged; stake-weighted top-up closes
the "age a cheap address then dump" loophole while auto-bond's small top-ups barely move it; EXACT revert;
the live selector actually withholds slots from a sudden whale; and — critically — the ramp does NOT touch
total_bonded_shares, so fork-choice weight and the FFG/settlement quorum stay ramp-free.

Run: python3 tests/test_bond_ramp.py
"""
import os, sys, tempfile, logging, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_bramp_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logger = logging.getLogger("bramp"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import BOND_RAMP_EPOCHS, B_MIN, EPOCH_LENGTH, BOND_CAP
from ops import kv_ops
from ops.account_ops import create_account, reflect_transaction, get_bonded_registry, apply_bond_since
from ops.mining_ops import (bond_ramp_weight, selection_shares, total_bonded_shares,
                            select_producer_two_lane)

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def t1_ramp_curve():
    """Prove bond_ramp_weight ramps 0 -> full over BOND_RAMP_EPOCHS, monotonically, with unset age = fully aged."""
    # base 100 shares, bonded at epoch 10
    assert bond_ramp_weight(100, 10, 10) == 0, "tenure 0 -> no weight"
    assert bond_ramp_weight(100, 10, 25) == 50, "half-ramped at tenure 15/30"
    assert bond_ramp_weight(100, 10, 40) == 100, "full at tenure == BOND_RAMP_EPOCHS"
    assert bond_ramp_weight(100, 10, 999) == 100, "stays full after"
    assert bond_ramp_weight(100, None, 0) == 100, "unset age (genesis/pre-existing) => fully aged"
    assert bond_ramp_weight(0, 5, 999) == 0, "no base shares => no weight"
    # monotonic non-decreasing over tenure
    prev = -1
    for e in range(10, 10 + BOND_RAMP_EPOCHS + 2):
        w = bond_ramp_weight(100, 10, e); assert w >= prev, "ramp must be monotonic"; prev = w

def _bond(sender, raw_amount, height, txid, revert=False):
    """Reflect (or revert) a bond transaction of raw_amount from sender at the given block height."""
    tx = {"sender": sender, "recipient": "bond", "amount": raw_amount, "fee": 0, "txid": txid}
    reflect_transaction(tx, logger=logger, block_height=height, revert=revert)

def t2_first_bond_sets_age_to_epoch():
    """Prove a first bond records bond_since as the epoch of the bonding block."""
    create_account("a", balance=100 * B_MIN)
    _bond("a", 1 * B_MIN, height=5 * EPOCH_LENGTH, txid="a1")     # epoch 5
    assert kv_ops.bond_since_get_raw("a") == 5, "first bond starts the age at its epoch"

def t3_stake_weighted_topup_closes_loophole():
    """Prove a big top-up onto a tiny aged bond re-ramps stake-weighted, closing the age-cheap-then-dump loophole."""
    create_account("whale", balance=100 * B_MIN)
    _bond("whale", 1 * B_MIN, height=0, txid="w1")               # tiny stake aged from epoch 0
    _bond("whale", 9 * B_MIN, height=100 * EPOCH_LENGTH, txid="w2")  # then DUMP 9x at epoch 100
    since = kv_ops.bond_since_get_raw("whale")
    # weighted: (1*0 + 9*100)/10 = 90 -> the dumped stake is re-ramped, NOT instantly aged
    assert since == 90, f"stake-weighted age should be 90, got {since}"
    reg = get_bonded_registry()
    base = selection_shares(reg["whale"]["bonded"])              # 10 shares
    from ops.mining_ops import bond_ramp_weight as brw
    assert brw(base, since, 100) < base, "dumped whale must NOT have full selection weight at the dump epoch"

def t4_auto_bond_preserves_age():
    """Prove a tiny auto-bond top-up barely moves a large aged stake's stake-weighted age (no reset to now)."""
    create_account("hodler", balance=200 * B_MIN)
    _bond("hodler", 100 * B_MIN, height=0, txid="h1")            # large stake, aged from epoch 0 — but
    # apply_bond_since never stores 0 (the "fully aged / genesis" sentinel), so an epoch-0 bonder ages from 1.
    _bond("hodler", 1 * B_MIN, height=100 * EPOCH_LENGTH, txid="h2")  # small auto-bond top-up at epoch 100
    since = kv_ops.bond_since_get_raw("hodler")
    # stake-weighted blend: (100*B_MIN * 1 + 1*B_MIN * 100) // (101*B_MIN) = 200//101 = 1 — the tiny top-up
    # BARELY moves the large aged stake's age (it does not reset it toward epoch 100).
    assert since == 1, f"a tiny top-up barely moves a large aged stake's age (got {since})"

def t5_revert_is_exact():
    """Prove reverting bonds restores bond_since exactly, back to UNSET after the first bond's revert."""
    create_account("r", balance=100 * B_MIN)
    assert kv_ops.bond_since_get_raw("r") is None
    _bond("r", 2 * B_MIN, height=7 * EPOCH_LENGTH, txid="r1")    # first bond
    assert kv_ops.bond_since_get_raw("r") == 7
    _bond("r", 8 * B_MIN, height=50 * EPOCH_LENGTH, txid="r2")   # top-up
    mid = kv_ops.bond_since_get_raw("r")
    _bond("r", 8 * B_MIN, height=50 * EPOCH_LENGTH, txid="r2", revert=True)   # revert top-up
    assert kv_ops.bond_since_get_raw("r") == 7, "revert restores the prior age exactly"
    _bond("r", 2 * B_MIN, height=7 * EPOCH_LENGTH, txid="r1", revert=True)    # revert first bond
    assert kv_ops.bond_since_get_raw("r") is None, "reverting the first bond leaves the age UNSET again"

def t6_selector_withholds_slots_from_a_sudden_whale():
    """Prove the live selector gives a whale bonded THIS epoch zero bonded slots while an aged validator wins them."""
    beacon = "c0ffee" * 8
    # aged small validator (unset age => full weight) vs a sudden whale with 100x stake, bonded THIS epoch
    aged = {"ndoAGED": {"bonded": 1 * B_MIN, "fidelity": None, "bond_since": None}}
    fresh_whale = {"ndoWHALE": {"bonded": BOND_CAP, "fidelity": None, "bond_since": 200}}
    reg = {**aged, **fresh_whale}
    epoch = 200
    whale_wins = aged_wins = 0
    for s in range(epoch * EPOCH_LENGTH, epoch * EPOCH_LENGTH + EPOCH_LENGTH):
        w = select_producer_two_lane({}, reg, beacon, s)
        if w == "ndoWHALE": whale_wins += 1
        elif w == "ndoAGED": aged_wins += 1
    assert whale_wins == 0, f"a whale bonded THIS epoch must win 0 bonded slots, won {whale_wins}"
    assert aged_wins > 0, "the aged validator should take the bonded slots"

def t7_quorum_and_weight_stay_ramp_free():
    """Prove total_bonded_shares (fork-choice weight + FFG/settlement quorum) ignores the ramp entirely."""
    # total_bonded_shares (fork-choice weight + FFG/settlement quorum) must IGNORE the ramp: a whale bonded
    # this instant still counts its FULL shares for finality — only PRODUCER selection is throttled.
    fresh_whale = {"ndoWHALE": {"bonded": BOND_CAP, "fidelity": None, "bond_since": 200}}
    raw = selection_shares(BOND_CAP)                            # 100 shares
    assert total_bonded_shares(fresh_whale) == raw, "quorum/weight must use ramp-free shares"

def t8_genesis_topup_keeps_aged_status():
    """Prove a small top-up on a genesis/pre-existing (unset-age) stake keeps it fully aged with full weight."""
    # a genesis/pre-existing stake has bonded but NO bond_since (fully aged). Auto-bonding MORE must NOT
    # reset the whole stake's age to now — that reset zeroed a sole validator's weight and deadlocked the chain.
    create_account("gen", balance=100 * B_MIN, bonded=100 * B_MIN)   # aged, bond_since unset
    assert kv_ops.bond_since_get_raw("gen") is None
    _bond("gen", 1 * B_MIN, height=100 * EPOCH_LENGTH, txid="g1")    # small top-up at epoch 100
    since = kv_ops.bond_since_get_raw("gen")
    assert since == 0, f"a small top-up on a large aged stake stays ~fully aged (got {since})"
    reg = get_bonded_registry()
    from ops.mining_ops import bond_ramp_weight as brw
    base = selection_shares(reg["gen"]["bonded"])
    assert brw(base, since, 100) == base, "aged validator keeps FULL selection weight after auto-bond"

def t9_liveness_fallback_when_all_fresh():
    """Prove that when EVERY bonded identity is still ramping (weight 0) the fallback still elects a producer."""
    # if EVERY bonded identity is still ramping (all tenure 0 -> ramped weight 0), the chain must NOT stall:
    # the un-ramped fallback still elects a producer. (This is the deadlock guard.)
    beacon = "beef" * 16
    epoch = 5
    reg = {f"ndoF{i:02x}": {"bonded": 5 * B_MIN, "fidelity": None, "bond_since": epoch} for i in range(3)}
    got = [select_producer_two_lane({}, reg, beacon, s)
           for s in range(epoch * EPOCH_LENGTH, epoch * EPOCH_LENGTH + EPOCH_LENGTH)]
    assert all(w is not None for w in got), "all-fresh bonded must never stall — liveness fallback must fire"
    assert all(w in reg for w in got), "fallback must elect a real bonded producer"

for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
