"""
Autogame — differential test: the zkasm contract vs the Python reference model, step for step.

Run: python3 tests/autogame_contract_test.py

The contract (execnode/games/autogame.py) is authoritative and the model (tests/autogame_model.py) is the
readable statement of what it is supposed to compute. Neither is evidence on its own — this file is. It
drives both over the SAME block hashes and the same plans and asserts every field of the run record matches
after every leg, which is the only way to know the assembly says what the prose says.

The two hash windows are reproduced here exactly as the VM derives them: BHASH reduces the L1 block hash mod
the Goldilocks prime, the contract feeds (T, runId, stepIndex) through the alghash sponge, and LO32 takes the
canonical low 32 bits.
"""
import hashlib
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode import runtimes, zkvm
from execnode.games import autogame as A
from execnode.stark import alghash
from execnode.stark import field as F
from tests import autogame_model as M

fails = 0


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


CODE = A.build()
BH = {h: int.from_bytes(hashlib.blake2b(b"autogame:%d" % h, digest_size=8).digest(), "big")
      for h in range(20000)}


def _call(meth, args, storage, caller=1234, cursor=0):
    cf, fa = runtimes.zkvm_statement(caller, args, {})
    return zkvm.run(CODE, meth, cf, fa, storage, cursor=cursor, block_hashes=BH)


def _words(height_hash, run_id, i):
    """Exactly what the contract computes: lo32(alghash(BHASH(h), runId, i))."""
    return alghash.hashn([height_hash % F.P, run_id, i]) & 0xFFFFFFFF


def _contract_state(st, rid):
    g = lambda f: st.get(f * (1 << 32) + rid, 0)
    return dict(hp=g(A.RHP), maxhp=g(A.RMX), stam=g(A.RST), potions=g(A.RPO), xp=g(A.RXP),
                banked=g(A.RBK), streak=g(A.RSK), depth=g(A.RDP), kills=g(A.RKI), alive=g(A.RAV),
                done=g(A.RDN), wlevel=g(A.RWL), alevel=g(A.RAL),
                mats=[g(A.RM0), g(A.RM1), g(A.RM2)],
                gear=[g(A.GEAR0 + i) for i in range(A.NSLOT)])


def _model_state(run):
    return dict(hp=run.hp, maxhp=run.maxhp, stam=run.stam, potions=run.potions, xp=run.xp,
                banked=run.banked, streak=run.streak, depth=run.depth, kills=run.kills,
                alive=run.alive, done=run.done, wlevel=run.wlevel, alevel=run.alevel,
                mats=list(run.mats), gear=list(run.gear))


def _pack(actions):
    """16 reactions x 3 bits, little-endian — the same word plan() accepts."""
    w = 0
    for i, a in enumerate(actions):
        w |= (a & 7) << (3 * i)
    return w


def drive(rid, plans, legs, stance=None, focus=None, healpct=None, start_cursor=100):
    """Run `legs` legs through BOTH implementations and compare after each one.

    `plans` maps leg index -> (list of 16 actions, aggression).
    """
    st = {}
    _ok, _r, st, _ = _call("constructor", [], st)
    ok, _r, st, _ = _call("begin", [rid], st, cursor=start_cursor)
    assert ok, "begin reverted"

    run = M.Run()
    if stance is not None:
        ok, _r, st, _ = _call("stance", [rid, stance], st, cursor=start_cursor)
        assert ok, "stance reverted"
        run.stance = stance
    if focus is not None:
        ok, _r, st, _ = _call("focus", [rid, focus], st, cursor=start_cursor)
        assert ok, "focus reverted"
        run.focus = focus
    if healpct is not None:
        ok, _r, st, _ = _call("orders", [rid, healpct], st, cursor=start_cursor)
        assert ok, "orders reverted"
        run.healpct = healpct

    lh = st[A.RLH * (1 << 32) + rid]
    for leg in range(legs):
        acts, agg = plans.get(leg, ([0] * A.LEG, 1))
        nh = lh + A.LEG
        if any(acts) or agg != 1:
            ok, _r, st, _ = _call("plan", [rid, leg, _pack(acts), agg], st, cursor=lh)
            assert ok, f"plan(leg={leg}) reverted"

        # model: same two hashes, same order
        for i in range(A.LEG):
            if not run.alive or run.done:
                break
            tw = _words(BH[lh], rid, i)
            rw = _words(BH[nh], rid, i)
            M.step(run, tw, rw, acts[i], agg)

        ok, _r, st, _ = _call("advance", [rid], st, cursor=nh + 1)
        assert ok, f"advance(leg={leg}) reverted"

        cs, ms = _contract_state(st, rid), _model_state(run)
        if cs != ms:
            diff = {k: (cs[k], ms[k]) for k in cs if cs[k] != ms[k]}
            raise AssertionError(f"leg {leg} diverged (contract, model): {diff}")
        if not run.alive or run.done:
            break
        lh = nh
    return st, run


def t_idle_run():
    """The absent player: no plan at all. This is the path most runs actually take, so it is the one that
    has to match first."""
    drive(11, {}, legs=8)


def t_planned_reactions():
    """Every reaction exercised, including the unaffordable ones that must degrade to Default rather than
    revert, and action 7 doing double duty (fork lane / Rally)."""
    plans = {
        0: ([A.A_STRIKE, A.A_GUARD, A.A_DODGE, A.A_SPRINT, A.A_RALLY, A.A_REST, A.A_POTION, A.A_RIGHT] * 2, 3),
        1: ([A.A_STRIKE] * 16, 6),            # cannot afford 16 strikes: most must degrade
        2: ([A.A_RALLY] * 16, 2),
        3: ([A.A_RIGHT] * 16, 8),
        4: ([A.A_POTION, A.A_REST] * 8, 5),
    }
    drive(12, plans, legs=6)


def t_all_stances_and_focus():
    """Each archetype drives different branches — guarded never builds a streak, weapon focus adds
    lifesteal, evasive halves hazards."""
    for i, (stance, focus, heal) in enumerate([(0, 50, 35), (1, 75, 20), (2, 0, 60), (3, 25, 45),
                                               (0, 100, 25)]):
        plans = {leg: ([A.A_STRIKE, 0, A.A_GUARD, 0] * 4, 2 + leg) for leg in range(6)}
        drive(20 + i, plans, legs=6, stance=stance, focus=focus, healpct=heal)


def t_long_run_to_boss():
    """Far enough to cross a boss checkpoint (depth 128) — banking, +10 maxhp, the guaranteed drop."""
    plans = {leg: ([0] * 16, 2) for leg in range(12)}
    st, run = drive(31, plans, legs=12, stance=M.ST_GUARDED, focus=25)
    assert run.depth >= 128 or not run.alive, f"expected to reach the checkpoint, got depth {run.depth}"
    if run.depth >= 128 and run.alive:
        assert run.banked > 0, "crossing a boss must bank the renown"
        assert run.maxhp > A.HP0, "a boss must raise max hp"


def t_death_is_terminal():
    """A reckless pull kills, and a dead run stops advancing — no further legs, no further renown."""
    plans = {leg: ([A.A_STRIKE] * 16, A.AGG_MAX) for leg in range(10)}
    st, run = drive(41, plans, legs=10, stance=M.ST_AGGRESSIVE, focus=100)
    assert not run.alive, "agg 16 from step 0 on an aggressive/all-weapon build should be fatal"
    before = _contract_state(st, 41)
    ok, _r, st2, _ = _call("advance", [41], dict(st), cursor=99999)
    assert not ok, "advance on a dead run must revert"
    assert _contract_state(st2, 41) == before, "a reverted advance must not mutate the run"


def t_plan_window_is_enforced():
    """The fairness argument in one test: you may not plan a leg once its rolling hash exists, and you may
    not plan a leg that is not the pending one."""
    st = {}
    _ok, _r, st, _ = _call("constructor", [], st)
    _ok, _r, st, _ = _call("begin", [51], st, cursor=100)
    nh = st[A.RNH * (1 << 32) + 51]

    ok, _r, _s, _ = _call("plan", [51, 0, _pack([1] * 16), 4], dict(st), cursor=nh - 1)
    assert ok, "planning before the rolling height must be allowed"
    ok, _r, _s, _ = _call("plan", [51, 0, _pack([1] * 16), 4], dict(st), cursor=nh)
    assert not ok, "planning AT the rolling height must revert — the dice are knowable"
    ok, _r, _s, _ = _call("plan", [51, 1, _pack([1] * 16), 4], dict(st), cursor=nh - 1)
    assert not ok, "planning a leg that is not pending must revert"
    ok, _r, _s, _ = _call("plan", [51, 0, _pack([1] * 16), 99], dict(st), cursor=nh - 1)
    assert not ok, "aggression above AGG_MAX must revert"
    ok, _r, _s, _ = _call("plan", [51, 0, 1 << 48, 4], dict(st), cursor=nh - 1)
    assert not ok, "an over-wide action word must revert"


def _seed_planned_run(rid, plans, legs, caller=1234):
    """Begin a run and plan LEG 0 only.

    Only the PENDING leg can be planned — the next leg's tiles come from a hash that does not exist yet, so
    there is nothing to plan against. A player who walks away therefore leaves a backlog that is unplanned
    by construction, which is precisely the absent-player path.
    """
    st = {}
    _ok, _r, st, _ = _call("constructor", [], st)
    ok, _r, st, _ = _call("begin", [rid], st, caller=caller, cursor=100)
    assert ok
    lh = st[A.RLH * (1 << 32) + rid]
    acts, agg = plans[0]
    ok, _r, st, _ = _call("plan", [rid, 0, _pack(acts), agg], st, caller=caller, cursor=lh)
    assert ok, "plan(leg=0) reverted"
    return st


def t_advance_is_permissionless_and_late_safe():
    """The whole lateness argument in one test.

    A leg's outcome is a pure function of two already-final block hashes, so WHO settles it and WHEN must
    be irrelevant. Two runs with identical plans are advanced completely differently — one leg at a time by
    the owner as each rolling height lands, versus a stranger settling the whole backlog hours later, two
    legs per call — and must end in bit-identical state.
    """
    LEGS = 8                                        # even, so both schedules land on the same leg boundary
    RID = 61
    plans = {0: ([A.A_STRIKE, 0, 0, A.A_GUARD] * 4, 3)}
    # ONE run, one starting state — the world is seeded by run id, so comparing two ids would only prove
    # that different runs get different worlds.
    st0 = _seed_planned_run(RID, plans, LEGS)

    # (a) the owner, promptly, one leg at a time as each rolling height becomes available
    st_a = dict(st0)
    for _ in range(LEGS):
        lh = st_a[A.RLH * (1 << 32) + RID]
        ok, _r, st_a, _ = _call("advance", [RID], st_a, caller=1234, cursor=lh + A.LEG + 1)
        if not ok:
            break                                   # run ended (death / chapter); (b) will end there too

    # (b) a stranger, hours later, clearing the whole backlog MAX_LEGS_PER_CALL at a time
    st_b = dict(st0)
    while st_b.get(A.RLG * (1 << 32) + RID, 0) < LEGS:
        ok, _r, st_b, _ = _call("advance", [RID], st_b, caller=999999, cursor=19000)
        assert ok or st_b.get(A.RAV * (1 << 32) + RID, 0) == 0, "advance must be permissionless"
        if not ok:
            break

    a, b = _contract_state(st_a, RID), _contract_state(st_b, RID)
    assert a == b, \
        f"settling late, by a stranger, changed the outcome: {[(k, a[k], b[k]) for k in a if a[k] != b[k]]}"


def t_only_owner_controls():
    st = {}
    _ok, _r, st, _ = _call("constructor", [], st)
    _ok, _r, st, _ = _call("begin", [71], st, caller=1234, cursor=100)
    for meth, args in (("stance", [71, 1]), ("focus", [71, 90]), ("orders", [71, 50]),
                       ("plan", [71, 0, 7, 3]), ("retire", [71])):
        ok, _r, _s, _ = _call(meth, args, dict(st), caller=555, cursor=101)
        assert not ok, f"{meth} must reject a non-owner"


def t_scratch_leaves_no_residue():
    """advance() uses fixed scratch slots as working registers; none may survive into the state root."""
    st, _run = drive(81, {0: ([A.A_STRIKE] * 16, 4)}, legs=3)
    left = [k for k in st if k >> 32 == A.SC and st[k] != 0]
    assert not left, f"scratch residue in the state root: {left}"


HEADROOM = 0.85          # the worst-case advance must fit in 85% of the trace budget


def t_worst_case_advance_has_headroom():
    """A run must NEVER become unadvanceable.

    Per-step cost is state-dependent: a step that drops walks six gear cells, one that equips also rescans
    the affix cache, and a `blazing` relic makes EVERY kill drop. So the expensive runs are the ones going
    WELL — if the budget were sized for a typical run, getting lucky would brick your own game permanently,
    with no way to move it forward ever again.

    Headroom is proven by lowering the VM's actual ceiling to HEADROOM of its real value and requiring the
    adversarial run to still settle. That is a stronger claim than reading a gas counter: it is the same
    check the VM performs, just stricter.
    """
    rid = 91
    st = {}
    _ok, _r, st, _ = _call("constructor", [], st)
    _ok, _r, st, _ = _call("begin", [rid], st, cursor=100)

    # expensive AND survivable, or the run dies in three steps and stresses nothing: top-tier armour in
    # every slot, all-armour focus, Guarded stance, plus `blazing` so every kill drops and _take_item runs
    # on every combat step. Aggression stays moderate — this is a budget test, not a lethality test.
    for sl in range(A.NSLOT):
        affix = A.AF_BLAZE if sl == 0 else A.AF_KEEN
        st[(A.GEAR0 + sl) * (1 << 32) + rid] = 1 + 7 * 64 + 7 * 8 + affix
    st[(A.AFFX + A.AF_BLAZE) * (1 << 32) + rid] = 1
    st[(A.AFFX + A.AF_KEEN) * (1 << 32) + rid] = 1
    st[A.RAL * (1 << 32) + rid] = A.LEVEL_CAP
    st[A.RSN * (1 << 32) + rid] = M.ST_GUARDED
    st[A.RFO * (1 << 32) + rid] = 0

    real_limit = zkvm.GAS_LIMIT
    zkvm.GAS_LIMIT = int(real_limit * HEADROOM)
    try:
        legs_done = 0
        lh = st[A.RLH * (1 << 32) + rid]
        for leg in range(24):
            if st.get(A.RAV * (1 << 32) + rid, 0) != 1 or st.get(A.RDN * (1 << 32) + rid, 0) != 0:
                break
            ok, _r, st2, _ = _call("plan", [rid, leg, _pack([A.A_STRIKE] * A.LEG), 4], dict(st), cursor=lh)
            if ok:
                st = st2
            ok, _r, st2, _ = _call("advance", [rid], dict(st), caller=999, cursor=lh + A.LEG + 1)
            assert ok, (f"advance reverted at leg {leg} inside {HEADROOM:.0%} of the trace budget — this is "
                        f"the brick case: a lucky kit made a step too expensive to ever settle")
            st = st2
            legs_done += 1
            lh = st[A.RLH * (1 << 32) + rid]
        assert legs_done >= 4, f"stress run only advanced {legs_done} legs — it is not stressing anything"
    finally:
        zkvm.GAS_LIMIT = real_limit


def t_constants_are_not_duplicated():
    """The model must IMPORT the rules, never restate them — otherwise a retune desyncs the oracle from
    the thing it checks and this whole file silently stops meaning anything."""
    src = open(os.path.join(os.path.dirname(__file__), "autogame_model.py")).read()
    assert "from execnode.games.autogame import" in src, "model must import the contract's constants"
    for name in ("CHAPTER", "BOSS_EVERY", "STREAK_DIV", "DEATH_KEEP", "HORDE_DIV"):
        assert f"\n{name} = " not in src, f"{name} is redefined in the model — it must be imported"
        assert getattr(M, name) == getattr(A, name), f"{name} differs between model and contract"


if __name__ == "__main__":
    check("idle run: no plan at all (the absent player)", t_idle_run)
    check("every reaction, including unaffordable degradation", t_planned_reactions)
    check("all stances x focus splits", t_all_stances_and_focus)
    check("long run across a boss checkpoint", t_long_run_to_boss)
    check("death is terminal and a dead run cannot advance", t_death_is_terminal)
    check("plan window enforces the fairness argument", t_plan_window_is_enforced)
    check("advance is permissionless and late-safe", t_advance_is_permissionless_and_late_safe)
    check("only the owner controls a run", t_only_owner_controls)
    check("scratch leaves no residue in the state root", t_scratch_leaves_no_residue)
    check("worst-case advance has trace headroom (a lucky run must not brick)", t_worst_case_advance_has_headroom)
    check("rules are imported, not duplicated", t_constants_are_not_duplicated)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
