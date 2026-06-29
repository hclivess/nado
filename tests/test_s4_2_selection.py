import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_s42_")
os.makedirs(os.path.expanduser("~/nado/logs"), exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from protocol import B_MIN, BOND_CAP, MAX_SHARES, FIDELITY_CAP
from ops.mining_ops import (selection_shares, total_shares, select_producer,
                            beacon_commitment, verify_reveal, compute_beacon, epoch_of)
from hashing import blake2b_hash

def blake2b_seed(i):
    """deterministic per-index 'random' beacon (no Math.random / time)"""
    return blake2b_hash(["seed", i])

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e: fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def t1():
    assert selection_shares(0) == 0 and selection_shares(B_MIN - 1) == 0          # below min => ineligible
    assert selection_shares(B_MIN) == 1
    assert selection_shares(4 * B_MIN) == 4
    assert selection_shares(1000 * B_MIN) == MAX_SHARES                            # capped, anti-whale
    assert selection_shares(BOND_CAP * 10) == MAX_SHARES
check("selection_shares: min gate, linear, capped at MAX_SHARES", t1)

def t2():
    # fidelity ramp: newcomer at half the cap gets half weight; at/above cap gets full
    assert selection_shares(10 * B_MIN, fidelity=FIDELITY_CAP) == 10
    assert selection_shares(10 * B_MIN, fidelity=FIDELITY_CAP // 2) == 5
    assert selection_shares(10 * B_MIN, fidelity=0) == 0
check("fidelity ramps weight linearly to full", t2)

def t3():
    # determinism: same inputs => same winner
    reg = {"a": {"bonded": 3 * B_MIN}, "b": {"bonded": B_MIN}}
    assert select_producer(reg, "deadbeef", 7) == select_producer(reg, "deadbeef", 7)
    assert select_producer({}, "x", 1) is None
    assert select_producer({"z": {"bonded": B_MIN - 1}}, "x", 1) is None           # nobody eligible
check("select_producer deterministic; empty/ineligible -> None", t3)

def t4():
    # SPLIT-NEUTRALITY: an entity controlling 4*B_MIN wins with identical probability whether it
    # holds one address (4 shares) or four addresses (1 share each), against the same rivals.
    rivals = {"r1": {"bonded": 3 * B_MIN}, "r2": {"bonded": 2 * B_MIN}}
    combined = dict(rivals, entity={"bonded": 4 * B_MIN})
    split = dict(rivals, e1={"bonded": B_MIN}, e2={"bonded": B_MIN},
                 e3={"bonded": B_MIN}, e4={"bonded": B_MIN})
    assert total_shares(combined) == total_shares(split)
    entity_addrs = {"e1", "e2", "e3", "e4"}
    N = 5000
    win_combined = win_split = 0
    for i in range(N):
        beacon = blake2b_seed(i)
        if select_producer(combined, beacon, 0) == "entity": win_combined += 1
        if select_producer(split, beacon, 0) in entity_addrs: win_split += 1
    # identical by construction (same 4/9 share of the draw space) -> counts must match exactly
    assert win_combined == win_split, (win_combined, win_split)
    # and the entity's 4/9 share should be ~4/9 of draws
    assert abs(win_combined / N - 4 / 9) < 0.05, win_combined / N
check("selection is split-neutral (sharding gives zero edge)", t4)

def t5():
    # higher bond wins proportionally more
    reg = {"big": {"bonded": 9 * B_MIN}, "small": {"bonded": B_MIN}}
    big = sum(select_producer(reg, blake2b_seed(i), 0) == "big" for i in range(5000))
    assert abs(big / 5000 - 9 / 10) < 0.05, big / 5000
check("win probability proportional to bonded shares", t5)

def t6():
    secret = "s3cr3t-reveal-value"
    c = beacon_commitment(secret)
    assert verify_reveal(c, secret) and not verify_reveal(c, "wrong")
    # beacon deterministic; order-independent in reveals; changes if any reveal changes;
    # chained with prev so withholding (omitting a reveal) yields a different beacon
    b1 = compute_beacon("00", ["x", "y", "z"])
    b2 = compute_beacon("00", ["z", "y", "x"])
    assert b1 == b2, "beacon must be reveal-order-independent"
    assert compute_beacon("00", ["x", "y"]) != b1, "withholding a reveal must change the beacon"
    assert compute_beacon("11", ["x", "y", "z"]) != b1, "must chain with previous beacon"
    assert compute_beacon("00", []) and compute_beacon("00", []) == compute_beacon("00", [])
check("RANDAO commit/reveal + chained, order-independent, withholding-sensitive beacon", t6)

def t7():
    assert epoch_of(0) == 0 and epoch_of(59) == 0 and epoch_of(60) == 1
check("epoch_of partitions by EPOCH_LENGTH", t7)

print(f"\n{'ALL S4.2 CHECKS PASSED' if fails==0 else str(fails)+' S4.2 CHECK(S) FAILED'}")
sys.exit(1 if fails else 0)
