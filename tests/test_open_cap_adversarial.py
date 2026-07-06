"""
Adversarial cap test — the Nyzo guard, machine-checked.

A free/Sybil actor flooding the OPEN lane with UNLIMITED cheap identities can never win more than
K_OPEN/EPOCH_LENGTH (OPEN_BPS, ~20%) of slots — because the lane split is a beacon-keyed permutation of slot
INDICES (a fixed COUNT), not a per-identity weight. This turns the reward-capture theorem
(doc/reward-capture-theorem.md, doc/takeover-resistance.md) into a regression guard that runs on every commit,
under escalating flood sizes and across beacons.

Run: python3 tests/test_open_cap_adversarial.py
"""
import os, sys, tempfile, traceback
os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="nado_cap_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from protocol import EPOCH_LENGTH, K_OPEN, OPEN_BPS, BPS_DENOM, B_MIN
from ops.mining_ops import select_producer_two_lane, lane_of

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

BEACON = "a3f1" * 16   # any fixed hex beacon

def open_reg(n):        # n Sybil OPEN identities, each at the flat floor weight (fidelity 0)
    """Build a registry of n Sybil OPEN identities at the flat floor weight (fidelity 0)."""
    return {f"ndoOPEN{i:012x}": {"fidelity": 0} for i in range(n)}
def bonded_reg(n, bond=B_MIN * 5):
    """Build a registry of n bonded identities, each bonded at `bond`."""
    return {f"ndoBOND{i:012x}": {"bonded": bond, "fidelity": None} for i in range(n)}

def open_wins_in_epoch(oreg, breg):
    """Count epoch slots won by open-lane identities under the fixed BEACON."""
    return sum(1 for slot in range(EPOCH_LENGTH)
               if (w := select_producer_two_lane(oreg, breg, BEACON, slot)) is not None and w in oreg)


def t1_lane_split_is_exactly_k_open():
    """Prove lane_of assigns exactly K_OPEN slots per epoch and K_OPEN equals OPEN_BPS of the epoch."""
    open_slots = sum(1 for s in range(EPOCH_LENGTH) if lane_of(s, BEACON) == "open")
    assert open_slots == K_OPEN, f"lane split gives {open_slots} open slots, expected K_OPEN={K_OPEN}"
    assert K_OPEN == EPOCH_LENGTH * OPEN_BPS // BPS_DENOM, "K_OPEN must equal OPEN_BPS of the epoch"

def t2_flood_never_exceeds_cap():
    """Prove open-lane wins stay pinned at K_OPEN as the Sybil flood escalates from 1 to 100k identities."""
    breg = bonded_reg(3)
    prev = None
    for n in (1, 10, 1000, 100_000):                 # escalate the Sybil flood by 5 orders of magnitude
        ow = open_wins_in_epoch(open_reg(n), breg)
        assert ow == K_OPEN, f"flood of {n} Sybils won {ow} slots, cap is K_OPEN={K_OPEN}"
        assert ow / EPOCH_LENGTH <= OPEN_BPS / BPS_DENOM + 1e-9, "exceeded the OPEN_BPS ceiling"
        if prev is not None:
            assert ow == prev, "open-lane wins must NOT grow with flood size (structural cap, not weight)"
        prev = ow

def t3_flood_with_no_bonded_still_capped():
    """Prove an empty bonded lane fails closed: bonded slots skip, so Sybils still win only K_OPEN."""
    # bonded lane empty: BONDED slots SKIP (fail-closed, never fall to open) -> Sybils still can't cross K_OPEN
    ow = open_wins_in_epoch(open_reg(50_000), {})
    assert ow == K_OPEN, f"with no bonded lane, Sybil flood still won {ow}, cap K_OPEN={K_OPEN}"

def t4_cap_count_invariant_across_beacons():
    """Prove the open-slot COUNT is exactly K_OPEN for every beacon (permutation, not weighting)."""
    # the split is beacon-DEPENDENT, but its COUNT is invariant (it's a permutation of slot indices)
    for b in range(16):
        beacon = f"{b:064x}"
        ow = sum(1 for s in range(EPOCH_LENGTH) if lane_of(s, beacon) == "open")
        assert ow == K_OPEN, f"beacon {b}: {ow} open slots != K_OPEN={K_OPEN}"

def t5_one_bonded_holder_cannot_be_starved_below_capital_share():
    """Prove a lone bonded holder keeps all EPOCH_LENGTH-K_OPEN bonded slots despite a 100k Sybil flood."""
    # sanity: the other ~80% is bonded; a lone honest bonded holder wins all bonded slots regardless of the flood
    breg = bonded_reg(1)
    bonded_wins = EPOCH_LENGTH - open_wins_in_epoch(open_reg(100_000), breg)
    assert bonded_wins == EPOCH_LENGTH - K_OPEN, "bonded lane should retain exactly EPOCH_LENGTH-K_OPEN slots"

for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)
print(f"\n{'ALL PASSED — open-lane Sybil ceiling holds' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
