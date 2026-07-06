"""
RANDAO participation-gate checks (randao_eligible_bonded), both policies:

  * RANDAO_ENFORCED = False (CURRENT, default): revealing is optional — the gate is a pure
    pass-through and the bonded draw always runs over the FULL registry.
  * RANDAO_ENFORCED = True: the bonded-lane draw for epoch E only admits identities that revealed
    their committed secret for E; withholding forfeits the epoch's production rights; an
    ALL-withheld epoch filters to an empty bonded lane and select_producer_two_lane's open
    fallback keeps the chain alive. Epochs 0-1 exempt.

Fork weight must keep using the FULL registry in either mode (withholding must not move
fork-choice).
"""
import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_randman_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(os.path.expanduser(f"~/nado/{d}"), exist_ok=True)

import logging
logger = logging.getLogger("randman"); logger.addHandler(logging.NullHandler())

from genesis import create_indexers
create_indexers()

import protocol
from ops import kv_ops
from ops.block_ops import randao_eligible_bonded
from ops.mining_ops import beacon_commitment, select_producer_two_lane, EPOCH_LENGTH

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

E = 5
GOOD, LAZY, WITHHOLDER = "ndoGOOD", "ndoLAZY", "ndoWITHHOLD"
S_GOOD = "aa" * 32
REGISTRY = {GOOD: {"bonded": 10**13}, LAZY: {"bonded": 10**13}, WITHHOLDER: {"bonded": 10**13}}

# GOOD committed + revealed; WITHHOLDER committed only; LAZY did nothing.
kv_ops.commit_put(GOOD, E, beacon_commitment(S_GOOD))
kv_ops.commit_put(WITHHOLDER, E, beacon_commitment("bb" * 32))
kv_ops.reveal_put(E, S_GOOD)


def t0_default_policy_is_optional():
    """CURRENT policy: enforcement off by default, and the gate is a pure pass-through even when
    some validators withheld/skipped — nobody loses production rights over the beacon duty."""
    assert protocol.RANDAO_ENFORCED is False, "default policy must be optional RANDAO"
    assert randao_eligible_bonded(REGISTRY, E) == REGISTRY, "optional mode must not filter anyone"
check("RANDAO_ENFORCED off by default; gate is a pass-through (optional RANDAO)", t0_default_policy_is_optional)

protocol.RANDAO_ENFORCED = True     # the remaining checks exercise the ENFORCED mode


def t1_filter():
    """Prove enforced mode admits only the revealer, passing registry entries through untouched."""
    elig = randao_eligible_bonded(REGISTRY, E)
    assert set(elig) == {GOOD}, f"only the revealer is eligible, got {set(elig)}"
    assert elig[GOOD] is REGISTRY[GOOD], "registry entries must pass through untouched"
check("enforced: revealed validator eligible; withholder + non-participant filtered out", t1_filter)


def t2_early_epochs_exempt():
    """Prove epochs 0-1 are exempt from the gate and an empty registry passes through."""
    assert randao_eligible_bonded(REGISTRY, 0) == REGISTRY
    assert randao_eligible_bonded(REGISTRY, 1) == REGISTRY
    assert randao_eligible_bonded({}, E) == {}
check("epochs 0-1 exempt; empty registry passes through", t2_early_epochs_exempt)


def t3_all_withheld_falls_back_to_open():
    """every bonded validator withheld -> eligible set {} -> a BONDED slot must fall back to the
    open lane (liveness), exactly like a chain with no stake at all"""
    E2 = E + 1
    kv_ops.commit_put(GOOD, E2, beacon_commitment("cc" * 32))     # committed, never revealed
    elig = randao_eligible_bonded(REGISTRY, E2)
    assert elig == {}, "no reveals -> nobody eligible"
    open_reg = {"ndoOPEN1": {"registered": 1, "fidelity": 0}}
    beacon = "d0" * 32
    bonded_slot = next(s for s in range(E2 * EPOCH_LENGTH, (E2 + 1) * EPOCH_LENGTH)
                       if __import__("ops.mining_ops", fromlist=["lane_of"]).lane_of(s, beacon) == "bonded")
    winner = select_producer_two_lane(open_reg, elig, beacon, slot=bonded_slot)
    assert winner == "ndoOPEN1", f"all-withheld bonded slot must fall back to open, got {winner}"
check("ALL-withheld epoch -> bonded slots fall back to the open lane (no halt)", t3_all_withheld_falls_back_to_open)


def t4_memo_tracks_reveal_set():
    """the memo is keyed by the reveal set: a new reveal for the epoch is honoured immediately"""
    E3 = E + 2
    s_l = "ee" * 32
    kv_ops.commit_put(LAZY, E3, beacon_commitment(s_l))
    assert randao_eligible_bonded(REGISTRY, E3) == {}, "not yet revealed"
    kv_ops.reveal_put(E3, s_l)
    assert set(randao_eligible_bonded(REGISTRY, E3)) == {LAZY}, "fresh reveal must be honoured"
    kv_ops.reveal_del(E3, s_l)                                    # reorg removes it
    assert randao_eligible_bonded(REGISTRY, E3) == {}, "reorged-out reveal must be forgotten"
check("eligibility follows the reveal set (add + reorg-remove)", t4_memo_tracks_reveal_set)


def t5_weight_sites_use_full_registry():
    """source-level: block_fork_weight call sites must NOT be fed the filtered registry —
    withholding must never move fork-choice weight"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in ("ops/block_ops.py", "loops/core_loop.py"):
        with open(os.path.join(root, path)) as f:
            src = f.read()
        for line in src.splitlines():
            if "block_fork_weight(" in line and "def block_fork_weight" not in line:
                assert "eligible" not in line, f"{path}: fork weight fed a filtered registry: {line.strip()}"
    # and both producer-selection sites in core_loop draw over the filtered set
    with open(os.path.join(root, "loops/core_loop.py")) as f:
        core = f.read()
    assert core.count("randao_eligible_bonded(") >= 2, "core_loop selection sites lost the filter"
check("fork weight stays on the FULL registry; selection sites keep the filter", t5_weight_sites_use_full_registry)


print(f"\n{'ALL RANDAO-GATE CHECKS PASSED' if not fails else str(fails) + ' FAILURE(S)'}")
sys.exit(1 if fails else 0)
