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
    # since possession-before-rollback, the emergency loop itself contains NO rollback call at all —
    # reverting lives only inside _adopt_branch, which is only reachable through the REORG branch.
    assert loop.count("_rollback_one_for_reorg(") == 0, "a rollback path outside _adopt_branch"
    reorg_at = loop.index("if (vstate == fork_resolution.REORG and _anc is not None")
    adopt_at = loop.index("self._adopt_branch(_anc)")
    assert reorg_at < adopt_at, "adoption is not inside the REORG branch"
    src_all = src("loops/core_loop.py")
    ab = src_all[src_all.index("def _adopt_branch"):]
    ab = ab[:ab.index("\n    def ")]
    assert "_rollback_one_for_reorg(ancestor=anc)" in ab, "the adoption burst lost the ancestor bound"
    # non-REORG mismatches strike the tip, never the chain
    assert "not rolling back; striking the tip instead" in loop


def t_verdict_is_checked_before_any_donor_is_consulted():
    """THE SEESAW (observed live 2026-08-17 23:06, a real split at 62655): donor selection keys off the
    heaviest ADVERTISED tip, which flip-flops between a split's sides — a same-fork donor 'knows' our tip
    and fast-forward re-inflates the fork just rolled back, while each pass burns a 5 s knows_block
    round-trip (~1 rollback/minute on a 12-block fork). Under a measured REORG the rollback must run
    before, and without, any donor interaction."""
    s = src("loops/core_loop.py")
    loop = s[s.index("def emergency_mode"):s.index("def _fast_forward_from")]
    verdict_at = loop.index("verdict = self._fork_verdict()")
    donor_at = loop.index("peer = self.get_peer_to_sync_from(")
    knows_at = loop.index("known_block = asyncio.run(knows_block(")
    assert verdict_at < donor_at < knows_at, "the verdict no longer precedes donor selection"
    assert loop.index("self._adopt_branch(_anc)") < donor_at, \
        "the REORG path consults the heaviest-tip donor flow first — the seesaw is back"


def t_stale_verdicts_cannot_revert_freshly_adopted_blocks():
    """After landing on the ancestor, and after ANY fast-forward, the cached REORG verdict describes a tip
    that no longer exists — it must be dropped before it can drive another rollback."""
    s = src("loops/core_loop.py")
    loop = s[s.index("def emergency_mode"):s.index("def _fast_forward_from")]
    assert loop.count("self._fork_state_cache = None") >= 1, \
        "the emergency loop no longer invalidates the verdict after a fast-forward"
    src_all = src("loops/core_loop.py")
    ab = src_all[src_all.index("def _adopt_branch"):]
    ab = ab[:ab.index("\n    def ")]
    assert "self._fork_state_cache = None" in ab, \
        "a successful adoption no longer drops the verdict that described the dead tip"
    ff_at = loop.index("ended = self._fast_forward_from(")
    inv_after_ff = loop.index("self._fork_state_cache = None", ff_at)
    brk = loop.index("if ended:", ff_at)
    assert inv_after_ff < brk, "fast-forward can exit the loop with a stale verdict still cached"


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


def t_production_is_suppressed_on_a_measured_minority_fork():
    """Deterministic production means BOTH sides of a mempool split advance every slot at near-equal
    weight — the heavier-tip gate never fires and both extend their forks for hours (splits at 62655 and
    62895). Production must consult the measured verdict; positive REORG/DEAD_FORK suppresses the slot."""
    s = src("loops/core_loop.py")
    nm = s[s.index("def normal_mode"):s.index("def emergency_mode")]
    assert "MINORITY-FORK PRODUCTION GATE" in nm, "the production gate is gone"
    assert "_vs in (fork_resolution.REORG, fork_resolution.DEAD_FORK)" in nm, \
        "the gate no longer requires POSITIVE evidence — UNKNOWN/BEHIND must never halt production"
    assert "and not _on_minority" in nm, "the suppression flag no longer reaches the produce condition"
    gate_at = nm.index("_on_minority = False")
    build_at = nm.index("block_candidate = get_block_candidate(")
    assert gate_at < build_at, "the gate runs after the candidate is already built"


def t_the_production_gate_is_cheap_on_the_healthy_path():
    """The verdict walk is ~40 hash probes; it must fire only on a PERSISTED majority-hash mismatch —
    every block boundary mismatches for the propagation second, and probing there would stall minting."""
    s = src("loops/core_loop.py")
    nm = s[s.index("def normal_mode"):s.index("def emergency_mode")]
    assert "_maj_hash != self.memserver.latest_block[\"block_hash\"]" in nm, \
        "the cheap gossip trigger is gone — the probe would run unconditionally"
    assert "MINORITY_GRACE_S" in nm, "the hysteresis is gone — block-boundary lag would fire probes"
    probe_at = nm.index("_vs = self._fork_state()")
    grace_at = nm.index("MINORITY_GRACE_S")
    assert grace_at < probe_at, "the probe runs before the hysteresis has passed"
    reset_at = nm.index("self._prod_minority_since = None")
    assert reset_at > probe_at, "the hysteresis timer is never reset when back on the majority hash"


# ---- STABLE TIE-BREAK: splits must resolve once, not see-saw for hours --------------------------------
def t_tie_winner_is_stable_and_symmetric():
    """Weight increments are content-independent, so a same-height split is a PERMANENT exact tie. The
    old lowest-TIP-hash rule re-rolled every block; the first-divergent-block comparison never changes."""
    from ops.fork_resolution import tie_winner
    assert tie_winner("aaaa", "bbbb") == "ours"
    assert tie_winner("bbbb", "aaaa") == "theirs"
    # SYMMETRY: the two sides of a split must reach OPPOSITE conclusions from mirrored inputs — that is
    # what makes exactly one side reorg.
    assert tie_winner("aaaa", "bbbb") == "ours" and tie_winner("bbbb", "aaaa") == "theirs"
    # STABILITY: the answer is a pure function of the first divergents — growing branches change nothing.
    for _ in range(3):
        assert tie_winner("aaaa", "bbbb") == "ours"


def t_tie_winner_no_evidence_never_switches():
    from ops.fork_resolution import tie_winner
    assert tie_winner(None, "bbbb") == "ours"
    assert tie_winner("aaaa", None) == "ours"
    assert tie_winner("", "") == "ours"
    assert tie_winner("aaaa", "aaaa") == "ours", "no divergence is not a reason to switch"


def t_minority_consensus_resolves_ties_at_the_divergence_point():
    s = src("loops/core_loop.py")
    mc = s[s.index("def minority_block_consensus"):]
    mc = mc[:mc.index("def snapshot_bootstrap")]
    assert "_tb = self._tie_break_ours(hh)" in mc, "the tie case no longer consults the stable tie-break"
    tie_at = mc.index("_tb = self._tie_break_ours(hh)")
    grace_at = mc.index("# GRACE WINDOW")
    assert tie_at < grace_at, "the tie-break must resolve BEFORE the grace/switch path"
    assert "if _tb is True:" in mc and "if _tb is None:" in mc, \
        "winning or unknown ties must never fall through to the switch path"


def t_the_production_gate_respects_a_won_tie():
    """The winning side of a split must keep producing — that is what starves the minority branch and
    makes the majority strictly heavier, repairing the weight signal itself."""
    s = src("loops/core_loop.py")
    nm = s[s.index("def normal_mode"):s.index("def emergency_mode")]
    assert "and not _tie_ours" in nm, "a won tie no longer exempts production from suppression"
    assert "self._tie_break_ours(" in nm


# ---- POSSESSION BEFORE ROLLBACK: disruption must cost the attacker a real branch ----------------------
def t_no_rollback_before_the_branch_is_held_and_checked():
    s = src("loops/core_loop.py")
    ab = s[s.index("def _adopt_branch"):]
    ab = ab[:ab.index("\n    def ")]
    fetch_at = ab.index("snapshot_ops.fetch_block(")
    content_at = ab.index("block_content_hash(b)")
    weight_at = ab.index('staged[-1].get("cumulative_weight", 0)')
    roll_at = ab.index("_rollback_one_for_reorg(")
    apply_at = ab.index("produce_block(block=blk")
    assert fetch_at < content_at < weight_at < roll_at < apply_at, \
        "adoption must fetch -> verify content -> verify weight claim -> roll -> apply, in that order"
    assert "self._reapply_local_branch(old_tip)" in ab, \
        "a branch failing full validation must restore OUR branch, not leave the node rolled back"
    assert ab.count("self._reject_heaviest_tip()") >= 4, \
        "unusable branches must be benched — repeat attempts have to cost the advertiser"


def t_the_emergency_reorg_leg_goes_through_adoption():
    s = src("loops/core_loop.py")
    loop = s[s.index("def emergency_mode"):s.index("def _fast_forward_from")]
    assert "adopted = self._adopt_branch(_anc)" in loop, "the REORG leg no longer requires possession"
    assert "if adopted is None:" in loop, "the budget/floor escalation path is gone"
    assert loop.count("_rollback_one_for_reorg(") == 0, \
        "a rollback path in the emergency loop outside _adopt_branch — the free-rollback vector is back"


for name, fn in [(n, f) for n, f in list(globals().items()) if n.startswith("t_")]:
    check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "ROLLBACKS REQUIRE MEASURED EVIDENCE")
sys.exit(1 if FAILS else 0)
