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


def _pack(doctrine):
    """One reaction per TILE CLASS, 3 bits each, class 0 in the low bits — the word plan() accepts."""
    w = 0
    for i, a in enumerate(doctrine):
        w |= (a & 7) << (3 * i)
    return w


def _doctrine(**kw):
    """Readable doctrine builder: _doctrine(monster=A_STRIKE, hazard=A_GUARD)."""
    d = [A.A_DEFAULT] * A.NTILE
    for name, act in kw.items():
        d[getattr(A, name.upper())] = act
    return d


def drive(rid, plans, legs, stance=None, focus=None, healpct=None, start_cursor=100):
    """Run `legs` legs through BOTH implementations and compare after each one.

    `plans` is either a (doctrine, aggression) pair applied as standing orders before the run, or {} for a
    run with no orders at all (the absent player).
    """
    st = {}
    _ok, _r, st, _ = _call("constructor", [], st)
    ok, _r, st, _ = _call("begin", [rid], st, cursor=start_cursor)
    assert ok, "begin reverted"

    run = M.Run()
    if stance is not None:
        run.stance = stance
    if focus is not None:
        run.focus = focus
    if healpct is not None:
        run.healpct = healpct

    doctrine, agg = plans if plans else ([A.A_DEFAULT] * A.NTILE, 1)
    # ONE call now carries every standing order, and it is also what ARMS the march: a run does not start
    # walking until its orders exist, so the first legs cannot resolve before the player has configured
    # anything (which, on a chain whose exec layer trails ten minutes, they always did).
    ok, _r, st, _ = _call("plan", [rid, _pack(doctrine), agg, run.stance, run.focus, run.healpct],
                          st, cursor=start_cursor)
    assert ok, "plan reverted"
    run.doctrine, run.agg = list(doctrine), agg

    lh = st[A.RLH * (1 << 32) + rid]
    for leg in range(legs):
        nh = lh + A.LEG
        # model: same two hashes, same order
        for i in range(A.LEG):
            if not run.alive or run.done:
                break
            tw = _words(BH[lh], rid, i)
            rw = _words(BH[nh], rid, i)
            M.step(run, tw, rw)

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
    # every reaction represented, including ones that cannot always be afforded (they must degrade to
    # Default rather than revert) and the fork entry that picks a lane
    d = _doctrine(monster=A.A_STRIKE, elite=A.A_GUARD, hazard=A.A_DODGE, cache=A.A_SPRINT,
                  shrine=A.A_RALLY, forge=A.A_REST, relic=A.A_POTION, fork=A.A_RIGHT, boss=A.A_STRIKE)
    drive(12, (d, 3), legs=6)


def t_all_stances_and_focus():
    """Each archetype drives different branches — guarded never builds a streak, weapon focus adds
    lifesteal, evasive halves hazards."""
    for i, (stance, focus, heal) in enumerate([(0, 50, 35), (1, 75, 20), (2, 0, 60), (3, 25, 45),
                                               (0, 100, 25)]):
        d = _doctrine(monster=A.A_STRIKE, elite=A.A_GUARD)
        drive(20 + i, (d, 2 + i), legs=6, stance=stance, focus=focus, healpct=heal)


def t_long_run_to_boss():
    """Far enough to cross a boss checkpoint (depth 128) — banking, +10 maxhp, the guaranteed drop."""
    st, run = drive(31, ([A.A_DEFAULT] * A.NTILE, 2), legs=12, stance=M.ST_GUARDED, focus=25)
    assert run.depth >= 128 or not run.alive, f"expected to reach the checkpoint, got depth {run.depth}"
    if run.depth >= 128 and run.alive:
        assert run.banked > 0, "crossing a boss must bank the renown"
        assert run.maxhp > A.HP0, "a boss must raise max hp"


def t_death_is_terminal():
    """A reckless pull kills, and a dead run stops advancing — no further legs, no further renown."""
    d = _doctrine(monster=A.A_STRIKE, elite=A.A_STRIKE, boss=A.A_STRIKE)
    st, run = drive(41, (d, A.AGG_MAX), legs=10, stance=M.ST_AGGRESSIVE, focus=100)
    assert not run.alive, "agg 16 from step 0 on an aggressive/all-weapon build should be fatal"
    before = _contract_state(st, 41)
    ok, _r, st2, _ = _call("advance", [41], dict(st), cursor=99999)
    assert not ok, "advance on a dead run must revert"
    assert _contract_state(st2, 41) == before, "a reverted advance must not mutate the run"


def t_doctrine_cannot_rewrite_a_rolled_leg():
    """THE fairness property, restated for standing orders.

    A doctrine may be set at any time — there is no window to hit, which is the whole point, because a
    window narrower than the exec layer's lag is unreachable. What keeps it honest is the POLH fence: a leg
    obeys the doctrine only if the doctrine PREDATES that leg's rolling height. So seeing a roll and then
    issuing new orders cannot change the leg that roll belongs to; the orders take effect from the next
    unresolved leg onward.

    This test proves exactly that: the same run, same hashes, orders issued AFTER the first leg's rolling
    height, must resolve leg 0 as if it had no orders at all.
    """
    d = _doctrine(monster=A.A_STRIKE, elite=A.A_STRIKE, boss=A.A_STRIKE)
    rid = 51
    ARM = ([A.A_DEFAULT] * A.NTILE, 1)
    st = {}
    _ok, _r, st, _ = _call("constructor", [], st)
    _ok, _r, st, _ = _call("begin", [rid], st, cursor=100)
    # arm it with neutral orders so there IS a window to talk about
    _ok, _r, st, _ = _call("plan", [rid, _pack(ARM[0]), 1, 0, 50, 35], st, cursor=100)
    lh = st[A.RLH * (1 << 32) + rid]
    nh = st[A.RNH * (1 << 32) + rid]

    # orders issued LATE — after this leg's dice are already public
    late = dict(st)
    ok, _r, late, _ = _call("plan", [rid, _pack(d), 8, 1, 90, 20], late, cursor=nh + 5)
    assert ok, "setting a doctrine must always be allowed — there is no window"
    ok, _r, late, _ = _call("advance", [rid], late, cursor=nh + 6)
    assert ok, "advance reverted"

    # the same run with NO orders at all
    none_ = dict(st)
    ok, _r, none_, _ = _call("advance", [rid], none_, cursor=nh + 6)
    assert ok, "advance reverted"

    a, b = _contract_state(late, rid), _contract_state(none_, rid)
    assert a == b, ("a doctrine set AFTER the roll changed the leg that roll belongs to — the fence is "
                    f"broken: {[(k, a[k], b[k]) for k in a if a[k] != b[k]]}")

    # and orders issued BEFORE the roll DO govern that leg (otherwise the fence would be vacuous)
    early = dict(st)
    ok, _r, early, _ = _call("plan", [rid, _pack(d), 8, 1, 90, 20], early, cursor=lh)
    assert ok
    ok, _r, early, _ = _call("advance", [rid], early, cursor=nh + 6)
    assert ok
    c = _contract_state(early, rid)
    assert c != b, "orders set before the roll must actually change the outcome, or nothing is being applied"


def t_plan_validates_its_arguments():
    st = {}
    _ok, _r, st, _ = _call("constructor", [], st)
    _ok, _r, st, _ = _call("begin", [52], st, cursor=100)
    W = _pack([1] * A.NTILE)
    ok, _r, _s, _ = _call("plan", [52, W, 4, 0, 50, 35], dict(st), cursor=200)
    assert ok, "a well-formed order set must be accepted"
    for args, why in (([52, W, 99, 0, 50, 35], "aggression above AGG_MAX"),
                      ([52, W, 0, 0, 50, 35], "aggression below 1"),
                      ([52, 1 << (3 * A.NTILE), 4, 0, 50, 35], "an over-wide doctrine word"),
                      ([52, W, 4, 9, 50, 35], "an out-of-range stance"),
                      ([52, W, 4, 0, 200, 35], "focus above 100"),
                      ([52, W, 4, 0, 50, 200], "a heal threshold above 100")):
        ok, _r, _s, _ = _call("plan", args, dict(st), cursor=200)
        assert not ok, f"{why} must revert"
    ok, _r, _s, _ = _call("plan", [52, W, 4, 0, 50, 35], dict(st), caller=999, cursor=200)
    assert not ok, "a non-owner must not set orders"


def _seed_planned_run(rid, plans, legs, caller=1234):
    """Begin a run and set standing orders once, before anything resolves."""
    st = {}
    _ok, _r, st, _ = _call("constructor", [], st)
    ok, _r, st, _ = _call("begin", [rid], st, caller=caller, cursor=100)
    assert ok
    # the window does not exist until the orders do — committing them is what arms the march
    doctrine, agg = plans
    ok, _r, st, _ = _call("plan", [rid, _pack(doctrine), agg, 0, 50, 35], st, caller=caller, cursor=100)
    assert ok, "plan reverted"
    assert st.get(A.RLH * (1 << 32) + rid), "committing orders must arm the march"
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
    plans = (_doctrine(monster=A.A_STRIKE, elite=A.A_GUARD), 3)
    # ONE run, one starting state — the world is seeded by run id, so comparing two ids would only prove
    # that different runs get different worlds.
    st0 = _seed_planned_run(RID, plans, LEGS)

    # (a) the owner, promptly, one leg at a time as each rolling height becomes available
    st_a = dict(st0)
    for _ in range(LEGS):
        lh = st_a.get(A.RLH * (1 << 32) + RID, 0)
        ok, _r, st_a, _ = _call("advance", [RID], st_a, caller=1234, cursor=lh + A.LEG + 1)
        if not ok:
            break                                   # run ended (death / chapter); (b) will end there too

    # (b) a stranger, hours later, clearing the whole backlog MAX_LEGS_PER_CALL at a time
    st_b = dict(st0)
    assert st_b.get(A.RLH * (1 << 32) + RID, 0), "the seeded run must be armed before it can be advanced"
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
    st, _run = drive(81, (_doctrine(monster=A.A_STRIKE), 4), legs=3)
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
    _ok, _r, st, _ = _call("plan", [rid, 0, 4, M.ST_GUARDED, 0, 35], st, cursor=100)   # arm the march

    # expensive AND survivable, or the run dies in three steps and stresses nothing: top-tier armour in
    # every slot, all-armour focus, Guarded stance, plus `blazing` so every kill drops and _take_item runs
    # on every combat step. Aggression stays moderate — this is a budget test, not a lethality test.
    for sl in range(A.NSLOT):
        affix = A.AF_BLAZE if sl == 0 else A.AF_KEEN
        st[(A.GEAR0 + sl) * (1 << 32) + rid] = 1 + 7 * 64 + 7 * 8 + affix
    st[(A.AFFX + A.AF_BLAZE) * (1 << 32) + rid] = 1
    st[(A.AFFX + A.AF_KEEN) * (1 << 32) + rid] = 1
    st[A.RAL * (1 << 32) + rid] = A.LEVEL_CAP

    real_limit = zkvm.GAS_LIMIT
    zkvm.GAS_LIMIT = int(real_limit * HEADROOM)
    try:
        legs_done = 0
        lh = st.get(A.RLH * (1 << 32) + rid, 0)
        for leg in range(24):
            if st.get(A.RAV * (1 << 32) + rid, 0) != 1 or st.get(A.RDN * (1 << 32) + rid, 0) != 0:
                break
            ok, _r, st2, _ = _call("advance", [rid], dict(st), caller=999, cursor=lh + A.LEG + 1)
            assert ok, (f"advance reverted at leg {leg} inside {HEADROOM:.0%} of the trace budget — this is "
                        f"the brick case: a lucky kit made a step too expensive to ever settle")
            st = st2
            legs_done += 1
            lh = st[A.RLH * (1 << 32) + rid]
        assert legs_done >= 4, f"stress run only advanced {legs_done} legs — it is not stressing anything"
    finally:
        zkvm.GAS_LIMIT = real_limit


def t_js_engine_matches_the_model():
    """The browser engine is the THIRD implementation, and the client uses it to preview a plan before you
    commit it. A preview that disagrees with settlement is worse than no preview, so it gets the same
    treatment as everything else here: driven over identical inputs and diffed field by field.

    The model is already proven against the contract above, so this chains the browser engine transitively
    to the chain. Vectors carry raw hash windows rather than block hashes — what is under test is the step
    function, not the sponge."""
    import json, shutil, subprocess, tempfile
    node = shutil.which("node")
    if not node:
        print("      (node not installed — skipping the browser-engine check)")
        return

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # regenerating the rules must be a no-op: if it is not, the browser is running different numbers
    from execnode.games.autogame import rules_js
    on_disk = open(os.path.join(root, "static", "autogame-rules.js")).read()
    assert on_disk == rules_js(), \
        "static/autogame-rules.js is stale — regenerate: python3 -m execnode.games.autogame --emit-js"

    cases = []
    configs = [("balanced", 0, 35, 50, 3), ("berserker", 1, 20, 75, 6), ("turtle", 2, 60, 0, 2),
               ("skirmisher", 3, 45, 25, 4), ("vampire", 0, 25, 100, 5)]
    doctrines = [
        _doctrine(monster=A.A_STRIKE, elite=A.A_GUARD, hazard=A.A_DODGE, fork=A.A_RIGHT),
        _doctrine(monster=A.A_GUARD, elite=A.A_STRIKE, shrine=A.A_RALLY, forge=A.A_REST),
        _doctrine(monster=A.A_SPRINT, hazard=A.A_GUARD, relic=A.A_POTION, boss=A.A_STRIKE),
        _doctrine(),
        _doctrine(monster=A.A_STRIKE, elite=A.A_STRIKE, boss=A.A_STRIKE, fork=A.A_RIGHT),
    ]
    for (name, stance, heal, focus, agg), doc in zip(configs, doctrines):
        run = M.Run(stance=stance, healpct=heal, focus=focus)
        run.doctrine, run.agg = list(doc), agg
        steps = []
        for n in range(400):
            tw = _words(BH[3000 + n], 7, n % A.LEG)
            rw = _words(BH[9000 + n], 7, n % A.LEG)
            M.step(run, tw, rw)
            steps.append({"tw": tw, "rw": rw, "doctrine": list(doc), "agg": agg,
                          "after": {"hp": run.hp, "maxhp": run.maxhp, "stam": run.stam,
                                    "potions": run.potions, "xp": run.xp, "banked": run.banked,
                                    "streak": run.streak, "depth": run.depth, "kills": run.kills,
                                    "alive": run.alive, "done": run.done, "wlevel": run.wlevel,
                                    "alevel": run.alevel, "gear": list(run.gear), "mats": list(run.mats)}})
            if not run.alive or run.done:
                break
        cases.append({"name": name, "stance": stance, "healpct": heal, "focus": focus,
                      "doctrine": list(doc), "agg": agg, "steps": steps, "score": run.score()})

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(cases, f)
        vec = f.name
    try:
        r = subprocess.run([node, os.path.join(root, "tests", "autogame_engine_verify.mjs"), vec],
                           capture_output=True, text=True, timeout=180)
        assert r.returncode == 0, f"browser engine diverged:\n{r.stdout}{r.stderr}"
        print(f"      {r.stdout.strip()}")
    finally:
        os.unlink(vec)


def t_storage_view_actually_decodes():
    """The client reads named maps, not slots — so the ABI's `_view` schema is load-bearing UI, and getting
    it wrong is invisible from the contract's side.

    decode_view enumerates keys from an index whose count lives at a RAW SLOT NUMBER and whose list is
    0-INDEXED. This contract originally wrote the count to RLIST*2^32 and appended at cnt+1, so the view
    enumerated nothing, every map decoded empty, and the page rendered perfectly while showing a contract
    with no state. Only running it caught that."""
    from execnode.state import ExecState
    st = {}
    _ok, _r, st, _ = _call("constructor", [], st)
    ids = [101, 202, 303]
    for rid in ids:
        ok, _r, st, _ = _call("begin", [rid], st, cursor=100)
        assert ok, f"begin({rid}) reverted"
        # arm it: an unarmed run has no window, so lh/nh are legitimately absent until orders exist
        ok, _r, st, _ = _call("plan", [rid, 0, 1, 0, 50, 35], st, cursor=100)
        assert ok, f"plan({rid}) reverted"

    c = {"abi": A.ABI, "runtime": "zkvm",
         "storage": {"slots": {str(k): str(v) for k, v in st.items()}}}
    es = ExecState.__new__(ExecState)
    es.zk_addrs = {}
    view = ExecState.decode_view(es, c)

    assert view, "the view decoded to nothing at all"
    for name in ("hp", "mx", "av", "fo", "hl", "lh", "nh"):
        got = sorted((view.get(name) or {}).keys())
        assert got == [str(i) for i in ids], f"map {name!r} enumerated {got}, want {ids}"
    assert all(v == A.HP0 for v in view["hp"].values()), f"hp map wrong: {view['hp']}"
    # a run the client can actually find: the owner map must resolve, not be a bare digest
    assert set((view.get("ra") or {}).keys()) == {str(i) for i in ids}, "owner map must list every run"


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
    check("a doctrine cannot rewrite a leg whose dice already rolled", t_doctrine_cannot_rewrite_a_rolled_leg)
    check("plan validates its arguments", t_plan_validates_its_arguments)
    check("advance is permissionless and late-safe", t_advance_is_permissionless_and_late_safe)
    check("only the owner controls a run", t_only_owner_controls)
    check("scratch leaves no residue in the state root", t_scratch_leaves_no_residue)
    check("worst-case advance has trace headroom (a lucky run must not brick)", t_worst_case_advance_has_headroom)
    check("storage view decodes into the maps the client reads", t_storage_view_actually_decodes)
    check("browser engine matches the model (transitively, the chain)", t_js_engine_matches_the_model)
    check("rules are imported, not duplicated", t_constants_are_not_duplicated)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
