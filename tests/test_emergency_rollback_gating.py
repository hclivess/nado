"""Emergency sync must never revert a real block on one peer's word — or on no word at all.

WHY THIS FILE EXISTS. The emergency loop's reorg decision was a single donor's `knows_block` answer, and
that function collapsed "could not answer" into "does not know" ("an unreachable peer just counts as not
knowing"). Rolling back a REAL block on False meant every donor timeout converted directly into a
reverted block, and a flaky donor could eat an entire 40-block burst probing blindly for an ancestor.
Measured 2026-08-17, on a chain that was healthy the whole time: 634 emergency episodes, 2,609 rollbacks,
20 exhausted bursts. Historically 88% of episodes end in under 10 seconds and are spurious — and
emergency rollback storms are the one thing that has actually corrupted state here (h4260).

The fix is the same rule the exec layer's finality-revert probe enforces (and 2026-08-03 taught):
ABSENCE OF INFORMATION IS NEVER EVIDENCE OF DIVERGENCE.

  * knows_block is TRI-STATE: True (serves our hash), False (ANSWERED with a different hash — positive
    evidence), None (couldn't answer). Only an answer counts.
  * A positive mismatch still doesn't revert on its own: the rollback leg is gated on the MEASURED fork
    verdict (hash probes over up to 8 peers, seeds first, min 2 answers) — REORG rolls back, BEHIND/
    SYNCED/UNKNOWN never do, DEAD_FORK goes to the re-anchor ladder.
  * A REORG burst is bounded by the verdict's common ANCESTOR — rolling past the proven ancestor is pure
    loss, so the leg stops there instead of burning the budget.

Run: python3 tests/test_emergency_rollback_gating.py
"""
import asyncio
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILS = []
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


def src(path):
    return open(os.path.join(ROOT, path), encoding="utf8").read()


# ---- knows_block: the tri-state contract, against a real local HTTP server ----------------------------
class _Srv:
    """A one-endpoint aiohttp stand-in peer whose behaviour is set per test."""
    def __init__(self):
        self.mode = "ours"
        self.port = None

    async def start(self):
        from aiohttp import web
        async def h(request):
            if self.mode == "ours":
                return web.json_response({"block_number": 100, "block_hash": "aaaa"})
            if self.mode == "theirs":
                return web.json_response({"block_number": 100, "block_hash": "bbbb"})
            if self.mode == "404":
                return web.Response(status=404, text="Not found")
            if self.mode == "garbage":
                return web.Response(status=200, text="not json")
            if self.mode == "nohash":
                return web.json_response({"block_number": 100})
        app = web.Application()
        app.add_routes([web.get("/get_block_number", h)])
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        self.port = runner.addresses[0][1]
        return runner


class _Log:
    def __getattr__(self, _n):
        return lambda *a, **k: None


def _ask(mode):
    from ops.block_ops import knows_block

    async def run():
        srv = _Srv()
        srv.mode = mode
        runner = await srv.start()
        try:
            return await knows_block("127.0.0.1", srv.port, "aaaa", 100, _Log())
        finally:
            await runner.cleanup()
    return asyncio.run(run())


def t_a_peer_serving_our_hash_knows_it():
    assert _ask("ours") is True


def t_a_peer_serving_a_different_hash_is_positive_evidence():
    assert _ask("theirs") is False


def t_a_404_is_no_evidence():
    """A donor momentarily BEHIND us 404s our height — that must never read as divergence."""
    assert _ask("404") is None


def t_garbage_and_hashless_replies_are_no_evidence():
    assert _ask("garbage") is None
    assert _ask("nohash") is None


def t_an_unreachable_peer_is_no_evidence():
    from ops.block_ops import knows_block
    r = asyncio.run(knows_block("127.0.0.1", 1, "aaaa", 100, _Log()))   # nothing listens on port 1
    assert r is None, "a connection failure must be None, not False — False now means ROLLBACK territory"


# ---- the emergency loop is gated on the measured verdict ----------------------------------------------
def t_no_rollback_without_a_reorg_verdict():
    s = src("loops/core_loop.py")
    loop = s[s.index("def emergency_mode"):]
    loop = loop[:loop.index("def _fast_forward_from")]
    assert "elif known_block is None:" in loop, "the couldn't-answer case is no longer separated"
    assert "verdict = self._fork_verdict()" in loop, "the rollback leg is no longer verdict-gated"
    # the ONLY rollback call must be inside the REORG branch and must carry the ancestor bound
    assert loop.count("_rollback_one_for_reorg(") == 1, "a rollback path outside the verdict gate"
    assert "_rollback_one_for_reorg(ancestor=verdict.get(\"ancestor\"))" in loop
    reorg_at = loop.index("if vstate == fork_resolution.REORG:")
    rb_at = loop.index("_rollback_one_for_reorg(")
    assert reorg_at < rb_at, "the rollback is not inside the REORG branch"
    # non-REORG mismatches strike the tip, never the chain
    assert "not rolling back; striking the tip instead" in loop


def t_none_answers_do_not_strike_immediately_but_do_eventually():
    """One blip must not reject a possibly-fine tip; a permanently mute donor pool must not pin us."""
    s = src("loops/core_loop.py")
    loop = s[s.index("def emergency_mode"):s.index("def _fast_forward_from")]
    assert "self._donor_unanswered" in loop, "consecutive non-answers are not counted"
    assert "if self._donor_unanswered >= 3:" in loop, "a mute donor pool would pin the node forever"


def t_the_reorg_leg_stops_at_the_measured_ancestor():
    s = src("loops/core_loop.py")
    leg = s[s.index("def _rollback_one_for_reorg"):]
    leg = leg[:leg.index("\n    def ")]
    assert "ancestor=None" in leg.splitlines()[0], "the leg no longer accepts the ancestor bound"
    guard = leg.index("<= int(ancestor)")
    budget = leg.index("self.memserver.rollbacks >= self.memserver.max_rollbacks")
    assert guard < budget, "the ancestor guard must run before the budget check"
    assert "refusing to roll deeper" in leg


for name, fn in [(n, f) for n, f in list(globals().items()) if n.startswith("t_")]:
    check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "ROLLBACKS REQUIRE MEASURED EVIDENCE")
sys.exit(1 if FAILS else 0)
