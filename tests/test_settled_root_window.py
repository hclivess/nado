"""Settlement-proven claims are valid against a WINDOW of recent roots, not a single moving target.

The bug class: dividend/bridge/unshield/xmsg claims proved against ONLY latest_settled(), so every
claim died the moment the next settle landed — permanently unminable, rebuilt each epoch, a growing
pool graveyard some peers held and others refused (measured 2026-08-18: 16 dead claims in one pool,
the dominant residual fork/slow-block driver). Now any of the last K=3 justified roots proves a
claim; the per-claim NULLIFIER keeps payout at-most-once.

Run: python3 tests/test_settled_root_window.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FAILS = []


def check(name, fn):
    try:
        fn()
        print("PASS  " + name)
    except AssertionError as e:
        print("FAIL  " + name + " — " + str(e))
        FAILS.append(name)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"FAIL  {name} — {type(e).__name__}: {e}")
        FAILS.append(name)


def _patched(monkey):
    """Run recent_settled_roots with the storage layer stubbed (no LMDB)."""
    from ops import settlement_ops as SO
    saved = {}
    for name, fn in monkey.items():
        saved[name] = getattr(SO, name, None) if not name.startswith("kv:") else getattr(SO.kv_ops, name[3:])
        if name.startswith("kv:"):
            setattr(SO.kv_ops, name[3:], fn)
        else:
            setattr(SO, name, fn)
    return SO, saved


def _restore(SO, saved):
    for name, fn in saved.items():
        if name.startswith("kv:"):
            setattr(SO.kv_ops, name[3:], fn)
        else:
            setattr(SO, name, fn)


def t_window_returns_last_k_justified_descending():
    monkey = {
        "get_bonded_registry": lambda: {"v": {"bonded": 10}},
        "total_bonded_shares": lambda reg: 10,
        "settlement_justified": lambda ns, c, r, reg: True,
        "kv:settlement_cursors": lambda ns: [10, 20, 30, 40, 50],
        "kv:settlements_for_cursor": lambda ns, c: [("v", f"root{c}")],
        "kv:in_write_txn": lambda: True,     # force the uncached path
    }
    SO, saved = _patched(monkey)
    try:
        got = SO.recent_settled_roots("ns1", k=3)
        assert got == [(50, "root50"), (40, "root40"), (30, "root30")], got
        assert SO.recent_settled_roots("ns1", k=1) == [(50, "root50")]
    finally:
        _restore(SO, saved)


def t_unjustified_cursors_are_skipped_not_counted():
    monkey = {
        "get_bonded_registry": lambda: {"v": {"bonded": 10}},
        "total_bonded_shares": lambda reg: 10,
        "settlement_justified": lambda ns, c, r, reg: c != 40,     # cursor 40 never justified
        "kv:settlement_cursors": lambda ns: [10, 20, 30, 40, 50],
        "kv:settlements_for_cursor": lambda ns, c: [("v", f"root{c}")],
        "kv:in_write_txn": lambda: True,
    }
    SO, saved = _patched(monkey)
    try:
        got = SO.recent_settled_roots("ns1", k=3)
        assert got == [(50, "root50"), (30, "root30"), (20, "root20")], \
            f"an unjustified cursor polluted the window: {got}"
    finally:
        _restore(SO, saved)


def t_window_head_equals_latest_settled():
    """The window's first entry must be exactly latest_settled — the header commitment stays put."""
    monkey = {
        "get_bonded_registry": lambda: {"v": {"bonded": 10}},
        "total_bonded_shares": lambda reg: 10,
        "settlement_justified": lambda ns, c, r, reg: True,
        "kv:settlement_cursors": lambda ns: [7, 8, 9],
        "kv:settlements_for_cursor": lambda ns, c: [("v", f"r{c}")],
        "kv:in_write_txn": lambda: True,
    }
    SO, saved = _patched(monkey)
    try:
        assert SO.recent_settled_roots("x", k=3)[0] == SO.latest_settled("x")
    finally:
        _restore(SO, saved)


def t_empty_registry_gives_empty_window():
    monkey = {
        "get_bonded_registry": lambda: {},
        "total_bonded_shares": lambda reg: 0,
        "kv:in_write_txn": lambda: True,
    }
    SO, saved = _patched(monkey)
    try:
        assert SO.recent_settled_roots("x", k=3) == []
    finally:
        _restore(SO, saved)


def t_all_four_claim_branches_use_the_window():
    s = open(os.path.join(ROOT, "ops", "transaction_ops.py"), encoding="utf8").read()
    assert s.count("recent_settled_roots") >= 4, "a claim branch fell back to the single-root check"
    for marker, verifier in [("dividend_withdraw", "verify_dividend"), ("bridge_withdraw", "verify_withdrawal"),
                             ('recipient == "xmsg"', "verify_outbox_msg"), ('r == "unshield"' , "verify_unshield")]:
        assert verifier in s, f"{verifier} disappeared"
        seg = s[s.index(verifier) - 1200:s.index(verifier) + 300]
        assert "_window" in seg and "any(" in seg, f"{verifier} does not iterate the window"
    # the settle-proof pre-state binding must stay EXACT (a proof chains from the committed tip)
    seg = s[s.index("_tip_cursor, tip_root = latest_settled"):][:200]
    assert "recent_settled_roots" not in seg, "the settle-proof tip binding was loosened — it must stay exact"


def t_zero_cooldown_matcher_still_matches_the_new_messages():
    """The reject-cooldown zero rule matches on 'not proven against the settled' — every windowed
    message must keep that substring or skew refusals silently cool 12s again."""
    s = open(os.path.join(ROOT, "ops", "transaction_ops.py"), encoding="utf8").read()
    assert s.count("not proven against the settled") + s.count("proven against from_ns's settled") >= 4
    from memserver import MemServer
    assert MemServer.reject_cooldown_s(
        "Could not merge remote transaction: dividend collection is not proven against the settled "
        "execution-layer root window", False) == 0


def t_expired_txs_evict_every_pass_not_only_after_own_production():
    s = open(os.path.join(ROOT, "loops", "core_loop.py"), encoding="utf8").read()
    seg = s[s.index("def normal_mode"):]
    seg = seg[:seg.index("_peer_ahead = peer_claims_heavier_tip")]
    assert 'max_block", 0) > _tip_now' in seg, \
        "the per-pass pool sweep no longer drops expired txs — the .26 hoard returns"


def t_production_waits_for_pool_warm_up():
    s = open(os.path.join(ROOT, "loops", "core_loop.py"), encoding="utf8").read()
    seg = s[s.index("POOL WARM-UP GATE"):][:2000]
    assert "self.memserver.pool_warmed" in seg and "get_uptime() > 60" in seg, \
        "the warm-up gate lost its timeout fallback — a mute mesh would stall production forever"
    gate = s[s.index("len(peers) >= self.memserver.min_peers"):][:400]
    assert "self.memserver.pool_warmed" in gate, "production no longer checks pool_warmed"
    p = open(os.path.join(ROOT, "loops", "peer_loop.py"), encoding="utf8").read()
    assert "self.memserver.pool_warmed = True" in p, "nothing ever warms the pool — production stalls 60s always"


for name, fn in [(n, f) for n, f in list(globals().items()) if n.startswith("t_")]:
    check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "CLAIMS OUTLIVE THE NEXT SETTLE; POOLS SHED THE DEAD")
sys.exit(1 if FAILS else 0)
