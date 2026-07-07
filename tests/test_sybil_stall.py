"""
Sybil-stall guard checks (2026-07-05): forked-away / lying peers must not be able to stall an
honest node's block production or wedge it in emergency mode.

Covers peer_claims_heavier_tip — the caught-up production gate's predicate: a tip we already
FAILED to sync a valid heavier chain for (rejected_tips) must not keep the gate closed, or two
Sybil clients advertising a bogus weight suppress minting network-wide forever. Also asserts the
emergency-loop failure paths (lying peer / fetch error / invalid block) all reject the heaviest
tip, and that the loop re-evaluates being-behind each pass — source-level, so a refactor that
silently drops one of the rejections fails here.
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_sybil_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loops.core_loop import peer_claims_heavier_tip

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")

W = 1000  # our tip weight

def status(weight, tip):
    """Build a minimal peer status dict advertising the given tip weight and hash."""
    return {"latest_block_weight": weight, "latest_block_hash": tip}

def t_solo():
    """a solo node (no peers, no statuses) mints normally"""
    assert peer_claims_heavier_tip([], W, have_peers=False, rejected_tips=set()) is False

def t_peers_no_status():
    """peers linked but tips unknown yet -> hold production (fork-while-syncing fix preserved)"""
    assert peer_claims_heavier_tip([], W, have_peers=True, rejected_tips=set()) is True

def t_real_heavier():
    """a genuine heavier tip (not rejected) -> hold production and sync"""
    assert peer_claims_heavier_tip([status(W + 1, "aa")], W, have_peers=True, rejected_tips=set()) is True

def t_lighter_and_equal():
    """lighter or equal advertisements never hold production"""
    assert peer_claims_heavier_tip([status(W, "aa"), status(W - 1, "bb")], W,
                                   have_peers=True, rejected_tips=set()) is False

def t_rejected_sybil():
    """THE STALL: a heavier-advertised tip we failed to obtain must NOT keep the gate closed"""
    assert peer_claims_heavier_tip([status(10**18, "bad")], W,
                                   have_peers=True, rejected_tips={"bad"}) is False

def t_two_sybils():
    """2 forked-away clients, both rejected -> mint; one fresh heavier tip among them -> hold"""
    sybils = [status(10**18, "bad1"), status(10**18, "bad2")]
    assert peer_claims_heavier_tip(sybils, W, have_peers=True,
                                   rejected_tips={"bad1", "bad2"}) is False
    assert peer_claims_heavier_tip(sybils + [status(W + 5, "real")], W,
                                   have_peers=True, rejected_tips={"bad1", "bad2"}) is True

def t_malformed_status():
    """defensive: statuses missing fields count as weight 0 / unknown tip and never crash"""
    assert peer_claims_heavier_tip([{}, {"latest_block_weight": None or 0}], W,
                                   have_peers=True, rejected_tips=set()) is False

def t_emergency_paths_reject():
    """source-level: every emergency-loop failure path excludes the tip + the loop re-checks
    being-behind each pass (a dropped rejection re-arms the infinite emergency wedge).
    The failure paths live in emergency_mode PLUS its extracted legs (_fast_forward_from:
    served-nothing / invalid-block / fetch-error; _rollback_one_for_reorg: budget-exhausted /
    missing-parent / finality-refused), so the rejection count is taken across all three."""
    src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "loops", "core_loop.py")
    with open(src_path) as f:
        src = f.read()
    def method_body(name):
        assert f"def {name}(" in src, f"{name} missing from core_loop"
        return src.split(f"def {name}(", 1)[1].split("\n    def ", 1)[0]
    emergency_legs = (method_body("emergency_mode") + method_body("_fast_forward_from")
                      + method_body("_rollback_one_for_reorg"))
    n_rejects = emergency_legs.count("_reject_heaviest_tip()")
    assert n_rejects >= 6, f"expected >=6 tip rejections across the emergency legs, found {n_rejects}"
    assert "minority_block_consensus()" in method_body("emergency_mode"), \
        "emergency loop no longer re-evaluates being-behind each pass"
    # and the production gate must consult rejected_tips
    normal = src.split("def normal_mode(", 1)[1].split("\n    def ", 1)[0]
    assert "rejected_tips" in normal, "caught-up gate no longer consults rejected_tips"

check("solo node mints", t_solo)
check("peers without statuses hold production", t_peers_no_status)
check("real heavier tip holds production", t_real_heavier)
check("lighter/equal tips never hold production", t_lighter_and_equal)
check("rejected bogus-heavy tip does NOT stall production", t_rejected_sybil)
check("2 Sybil clients cannot stall; a real heavier tip still counts", t_two_sybils)
check("malformed statuses are harmless", t_malformed_status)
check("emergency failure paths all reject the tip + loop re-checks behind", t_emergency_paths_reject)

print()
print("ALL SYBIL-STALL CHECKS PASSED" if not fails else f"{fails} SYBIL-STALL CHECK(S) FAILED")
sys.exit(1 if fails else 0)
