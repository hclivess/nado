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

def status(weight, tip, protocol=99):
    """Build a minimal peer status dict advertising the given tip weight and hash."""
    return {"latest_block_weight": weight, "latest_block_hash": tip, "protocol": protocol}


def t_foreign_protocol_weight_ignored():
    """A foreign-protocol peer is a different network: its heavier tip must not stall our production."""
    assert peer_claims_heavier_tip([status(W + 100, "old", protocol=2)], W,
                                   have_peers=True, rejected_tips=set(), min_protocol=3) is False
    assert peer_claims_heavier_tip([status(W + 100, "new", protocol=3)], W,
                                   have_peers=True, rejected_tips=set(), min_protocol=3) is True

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

def t_moving_target_fork_is_benched_by_peer_not_hash():
    """THE 2026-07-20 wedge. A node that forked ~3000 blocks back kept MINING its own branch, so it
    advertised a new tip hash every block — and a lone miner's branch can out-accumulate weight, so it
    looked heaviest to the whole network while serving no snapshot and knowing none of our blocks. Benching
    by hash could never catch it: each pass saw a fresh "heaviest" tip, burned a sync window failing to
    obtain it, and re-wedged (39 times in three hours, dropping every transaction submitted meanwhile).
    The bench therefore has to be keyed on the PEER, so its next hash is excluded before we chase it."""
    # by hash alone: yesterday's rejected tip is useless once the forker mints a new one
    assert peer_claims_heavier_tip([status(W + 500, "fork_block_2")], W,
                                   have_peers=True, rejected_tips={"fork_block_1"}, min_protocol=1) is True
    # by peer: the forker's CURRENT hash is benched because the peer is
    assert peer_claims_heavier_tip([status(W + 500, "fork_block_2")], W,
                                   have_peers=True, rejected_tips={"fork_block_1"}, min_protocol=1,
                                   benched={"fork_block_2"}) is False
    # and an honest heavier peer alongside the benched one still counts — we must not go blind
    assert peer_claims_heavier_tip([status(W + 500, "fork_block_2"), status(W + 10, "real_tip")], W,
                                   have_peers=True, rejected_tips=set(), min_protocol=1,
                                   benched={"fork_block_2"}) is True


def t_shared_tip_never_benches_its_peers():
    """The dangerous direction. A tip several peers advertise is a chain the NETWORK holds — a failure to
    fetch it says more about us than about them, and benching those peers would make this node ignore the
    real chain for minutes. Only a lone advertiser can ever be benched."""
    import loops.consensus_loop as CL

    class FakeMem:
        latest_block = {"block_hash": "ours", "cumulative_weight": W, "block_timestamp": 0}
        terminate = False
    c = CL.ConsensusClient.__new__(CL.ConsensusClient)
    c.memserver = FakeMem()
    c.block_hash_pool = {"a": "shared", "b": "shared", "c": "shared"}
    c.rejected_tips = set(); c._tip_strikes = {}; c._tip_until = {}
    c._peer_strikes = {}; c._peer_until = {}
    for _ in range(CL.PEER_BENCH_AFTER + 5):
        c.reject_tip("shared")
    assert not any(c.tip_source_benched(p) for p in ("a", "b", "c")), \
        "a chain multiple peers hold must never take its peers out of fork choice"


def t_reject_tip_strikes_the_advertising_peer():
    """reject_tip must strike every peer advertising the failed tip, and the bench must be readable
    per-peer — that is the whole mechanism the moving-target fork above depends on."""
    import loops.consensus_loop as CL

    class FakeMem:
        latest_block = {"block_hash": "ours", "cumulative_weight": W, "block_timestamp": 0}
        terminate = False
    c = CL.ConsensusClient.__new__(CL.ConsensusClient)
    c.memserver = FakeMem()
    c.block_hash_pool = {"1.2.3.4": "forktip", "5.6.7.8": "realtip"}
    c.rejected_tips = set(); c._tip_strikes = {}; c._tip_until = {}
    c._peer_strikes = {}; c._peer_until = {}
    assert c.tip_source_benched("1.2.3.4") is False
    c.reject_tip("forktip")
    assert c.tip_source_benched("1.2.3.4") is False, "one failure is a blip, not a fork — never bench on it"
    for _ in range(CL.PEER_BENCH_AFTER - 1):
        c.reject_tip("forktip")
    assert c.tip_source_benched("1.2.3.4") is True, "the peer that fed us the bad tip must be benched"
    assert c.tip_source_benched("5.6.7.8") is False, "an unrelated peer must not be collateral damage"
    # repeated failures back off further, never shorter
    first = c._peer_until["1.2.3.4"]
    c.reject_tip("forktip")
    assert c._peer_until["1.2.3.4"] > first, "backoff must grow with consecutive failures"



def t_fork_rejoin_only_fires_when_provably_isolated():
    """The escalation that drops the local finality floor must be impossible to trigger casually: it needs a
    real mesh, a STRICT majority of it on ONE other heavier tip, and repeated re-anchor failures first.
    Anything less and a couple of noisy peers could talk a healthy node off the canonical chain."""
    import types
    from loops.core_loop import CoreClient, MIN_REJOIN_PEERS, REANCHOR_ESCALATE

    def node(pool, failures=REANCHOR_ESCALATE, tip="ours", weight=W):
        c = CoreClient.__new__(CoreClient)
        c._reanchor_failures = failures
        c.consensus = types.SimpleNamespace(status_pool=pool)
        c.memserver = types.SimpleNamespace(
            latest_block={"block_hash": tip, "cumulative_weight": weight, "block_number": 100},
            earliest_block={"block_number": 0}, port=9173, terminate=False, rollbacks=0)
        c.logger = types.SimpleNamespace(warning=lambda *a: None, error=lambda *a: None)
        c._common_ancestor = lambda peers: None      # never actually reorg in a unit test
        return c

    heavier = lambda tip: {"latest_block_hash": tip, "latest_block_weight": W + 50, "protocol": 99}
    majority = {"a": heavier("theirs"), "b": heavier("theirs"), "c": heavier("theirs"), "d": heavier("theirs")}

    assert node(majority, failures=REANCHOR_ESCALATE - 1)._rejoin_by_rollback() is False, \
        "must not fire before re-anchoring has repeatedly failed"
    assert node(dict(list(majority.items())[:MIN_REJOIN_PEERS - 1]))._rejoin_by_rollback() is False, \
        "must not fire without a real peer mesh"
    split = {"a": heavier("x"), "b": heavier("y"), "c": heavier("z"), "d": heavier("w")}
    assert node(split)._rejoin_by_rollback() is False, \
        "peers disagreeing with each other are noise, not one canonical chain"
    lighter = {k: {"latest_block_hash": "theirs", "latest_block_weight": W - 1, "protocol": 99}
               for k in ("a", "b", "c", "d")}
    assert node(lighter)._rejoin_by_rollback() is False, "a LIGHTER chain never justifies dropping finality"
    tie = {"a": heavier("theirs"), "b": heavier("theirs"),
           "c": {"latest_block_hash": "ours", "latest_block_weight": W, "protocol": 99},
           "d": {"latest_block_hash": "ours", "latest_block_weight": W, "protocol": 99}}
    assert node(tie)._rejoin_by_rollback() is False, "half is not a strict majority"
    # the real thing: mesh + strict majority + heavier + escalated -> it looks for the common ancestor
    seen = {}
    n = node(majority)
    n._common_ancestor = lambda peers: seen.setdefault("peers", sorted(peers)) and None
    n._rejoin_by_rollback()
    assert seen.get("peers") == ["a", "b", "c", "d"], "should ask exactly the majority-tip holders"


check("fork rejoin only fires when provably isolated", t_fork_rejoin_only_fires_when_provably_isolated)
check("moving-target fork is benched by PEER, not by hash", t_moving_target_fork_is_benched_by_peer_not_hash)
check("reject_tip strikes the advertising peer", t_reject_tip_strikes_the_advertising_peer)
check("a tip several peers hold never benches them", t_shared_tip_never_benches_its_peers)
check("foreign-protocol weight is invisible to the production gate", t_foreign_protocol_weight_ignored)
check("emergency failure paths all reject the tip + loop re-checks behind", t_emergency_paths_reject)

print()
print("ALL SYBIL-STALL CHECKS PASSED" if not fails else f"{fails} SYBIL-STALL CHECK(S) FAILED")
sys.exit(1 if fails else 0)
