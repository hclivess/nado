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


def _call(meth, args, storage, caller=1234, cursor=0, timestamp=0):
    cf, fa = runtimes.zkvm_statement(caller, args, {})
    return zkvm.run(CODE, meth, cf, fa, storage, cursor=cursor, timestamp=timestamp, block_hashes=BH)


def _words(height_hash, run_id, i):
    """Exactly what the contract computes: lo32(alghash(BHASH(h), runId, i))."""
    return alghash.hashn([height_hash % F.P, run_id, i]) & 0xFFFFFFFF


def _contract_state(st, rid):
    g = lambda f: st.get(f * (1 << 32) + rid, 0)
    return dict(hp=g(A.RHP), maxhp=g(A.RMX), stam=g(A.RST), potions=g(A.RPO), xp=g(A.RXP),
                banked=g(A.RBK), streak=g(A.RSK), depth=g(A.RDP), kills=g(A.RKI), alive=g(A.RAV),
                done=g(A.RDN), wlevel=g(A.RWL), alevel=g(A.RAL),
                mats=[g(A.RM0), g(A.RM1), g(A.RM2)],
                gear=[g(A.GEAR0 + i) for i in range(A.NSLOT)], pyre=g(A.RPY))


def _model_state(run):
    return dict(hp=run.hp, maxhp=run.maxhp, stam=run.stam, potions=run.potions, xp=run.xp,
                banked=run.banked, streak=run.streak, depth=run.depth, kills=run.kills,
                alive=run.alive, done=run.done, wlevel=run.wlevel, alevel=run.alevel,
                mats=list(run.mats), gear=list(run.gear), pyre=run.pyre)


def _leg_word(acts):
    """Sixteen per-tile answers, 3 bits each, step 0 in the low bits — the word commit() accepts."""
    w = 0
    for i, a in enumerate(acts):
        w |= (a & 7) << (3 * i)
    return w


def _answer_cells(st, rid, leg):
    """The three cells a commit writes: the hash-keyed word advance() consumes, plus the two readable
    mirrors the animator replays a settled leg from. A commit half that STANDS DOWN has to leave all three
    exactly as it found them — "no dice were scheduled" cannot see a stale word landing in the answer slot
    of a leg it was never written for, which is the whole thing the select-gating protects."""
    return (st.get(alghash.hashn([A.OVR_TAG, rid, leg]), 0),
            st.get(A.RCW * (1 << 32) + rid, 0),
            st.get(A.RCL * (1 << 32) + rid, 0))


def _peek_tiles(rid, st, lh):
    """The 16 tile CLASSES the next leg will walk, derived exactly as the client's road strip derives them
    from the already-final terrain hash. This is what a player looks at before answering — so tests that
    want "strike every monster" build their answer word from this, through the same channel a person uses,
    rather than reaching into the rules from the side."""
    d0 = st.get(A.RDP * (1 << 32) + rid, 0)
    out = []
    for i in range(A.LEG):
        a, _b, _c, _sc = M.slice_tile(_words(BH[lh], rid, i))
        out.append(M.tile_of(a, d0 + i))
    return out


def _answers(tiles, classmap):
    return [classmap.get(t, A.A_DEFAULT) for t in tiles]


def drive(rid, classmap, legs, agg=1, stance=None, focus=None, healpct=None, start_cursor=100):
    """Run `legs` legs through BOTH implementations and compare after each one.

    Manual-only: every leg is answered. `classmap` maps tile class -> the action to answer it with
    (anything absent answers A_DEFAULT); the word is built from the leg's ACTUAL tiles, read from the
    terrain hash the way the road strip reads them, and committed before the dice exist — the only flow
    the contract has.
    """
    st = {}
    _ok, _r, st, _ = _call("constructor", [], st)
    ok, _r, st, _ = _call("begin", [rid], st, cursor=start_cursor)
    assert ok, "begin reverted"
    assert st.get(A.RLH * (1 << 32) + rid), "begin must ARM the march (the two-step lost three real players)"
    assert st.get(A.RNH * (1 << 32) + rid, 0) == 0, "…but must NOT schedule dice"

    run = M.Run()
    if stance is not None:
        run.stance = stance
    if focus is not None:
        run.focus = focus
    if healpct is not None:
        run.healpct = healpct
    run.agg = agg
    if agg != 1 or stance is not None or focus is not None or healpct is not None:
        ok, _r, st, _ = _call("plan", [rid, agg, run.stance, run.focus, run.healpct],
                              st, cursor=start_cursor)
        assert ok, "plan (dials) reverted"

    for leg in range(legs):
        lh = st.get(A.RLH * (1 << 32) + rid, 0)
        acts = _answers(_peek_tiles(rid, st, lh), classmap)
        ok, _r, st, _ = _call("commit", [rid, _leg_word(acts)], st, cursor=lh + 1)
        assert ok, f"commit(leg={leg}) reverted"
        nh = st[A.RNH * (1 << 32) + rid]
        for i in range(A.LEG):
            if not run.alive or run.done:
                break
            tw = _words(BH[lh], rid, i)
            rw = _words(BH[nh], rid, i)
            M.step(run, tw, rw, action=acts[i])

        ok, _r, st, _ = _call("advance", [rid], st, cursor=nh + 1)
        assert ok, f"advance(leg={leg}) reverted"

        cs, ms = _contract_state(st, rid), _model_state(run)
        if cs != ms:
            diff = {k: (cs[k], ms[k]) for k in cs if cs[k] != ms[k]}
            raise AssertionError(f"leg {leg} diverged (contract, model): {diff}")
        if not run.alive or run.done:
            break
        assert st.get(A.RNH * (1 << 32) + rid, 0) == 0, "the march must PARK after every settled leg"
    return st, run


def t_blank_answers():
    """The all-blank word: sixteen zeros IS a valid answer (walk in, fight plainly). This is the floor the
    whole design rests on — an unanswered tile is an unspent choice, never a trap — so it matches first."""
    drive(11, {}, legs=8)


def t_every_reaction():
    """Every action exercised through real answers, including the unaffordable ones that must degrade to
    Default rather than revert, and action 7 doing double duty (fork lane / Rally)."""
    cm = {A.MONSTER: A.A_STRIKE, A.ELITE: A.A_GUARD, A.HAZARD: A.A_DODGE, A.CACHE: A.A_SPRINT,
          A.SHRINE: A.A_RALLY, A.FORGE: A.A_REST, A.RELIC: A.A_POTION, A.FORK: A.A_RIGHT,
          A.BOSS: A.A_STRIKE}
    drive(12, cm, legs=6, agg=3)


def t_all_stances_and_focus():
    """Each archetype drives different branches — guarded never builds a streak, weapon focus adds
    lifesteal, evasive halves hazards."""
    for i, (stance, focus, heal) in enumerate([(0, 50, 35), (1, 75, 20), (2, 0, 60), (3, 25, 45),
                                               (0, 100, 25)]):
        drive(20 + i, {A.MONSTER: A.A_STRIKE, A.ELITE: A.A_GUARD}, legs=6, agg=2 + i,
              stance=stance, focus=focus, healpct=heal)


def t_long_run_to_boss():
    """Far enough to cross a boss checkpoint (depth 128) — banking, +10 maxhp, the guaranteed drop."""
    st, run = drive(31, {}, legs=12, agg=2, stance=M.ST_GUARDED, focus=25)
    assert run.depth >= 128 or not run.alive, f"expected to reach the checkpoint, got depth {run.depth}"
    if run.depth >= 128 and run.alive:
        assert run.banked > 0, "crossing a boss must bank the renown"
        assert run.maxhp > A.HP0, "a boss must raise max hp"


def t_death_is_terminal():
    """A reckless pull kills, and a dead run stops advancing — no further legs, no further renown."""
    cm = {A.MONSTER: A.A_STRIKE, A.ELITE: A.A_STRIKE, A.BOSS: A.A_STRIKE}
    st, run = drive(41, cm, legs=10, agg=A.AGG_MAX, stance=M.ST_AGGRESSIVE, focus=100)
    assert not run.alive, "agg 16 from step 0 on an aggressive/all-weapon build should be fatal"
    before = _contract_state(st, 41)
    ok, _r, st2, _ = _call("advance", [41], dict(st), cursor=99999)
    assert not ok, "advance on a dead run must revert"
    assert _contract_state(st2, 41) == before, "a reverted advance must not mutate the run"


def t_dials_cannot_rewrite_a_rolled_leg():
    """THE fairness property, restated for what is left of standing state.

    Actions need no fence — commit() stores them and only then schedules the dice. But the DIALS
    (aggression/stance/focus/heal) shape a leg after it is committed, so the POLH fence must hold: a leg
    obeys a generation of dials only if that generation PREDATES its rolling height. Re-tuning after the
    roll is public cannot change the leg that roll belongs to.
    """
    rid = 51
    st = {}
    _ok, _r, st, _ = _call("constructor", [], st)
    _ok, _r, st, _ = _call("begin", [rid], st, cursor=100)
    lh = st[A.RLH * (1 << 32) + rid]
    word = _leg_word(_answers(_peek_tiles(rid, st, lh), {A.MONSTER: A.A_STRIKE, A.ELITE: A.A_STRIKE,
                                                        A.BOSS: A.A_STRIKE}))
    ok, _r, st, _ = _call("commit", [rid, word], st, cursor=lh + 1)
    assert ok
    nh = st[A.RNH * (1 << 32) + rid]

    # dials re-tuned LATE — after this leg's dice are already public
    late = dict(st)
    ok, _r, late, _ = _call("plan", [rid, 8, 1, 90, 20], late, cursor=nh + 5)
    assert ok, "re-tuning the dials must always be allowed — there is no window"
    ok, _r, late, _ = _call("advance", [rid], late, cursor=nh + 6)
    assert ok, "advance reverted"

    # the same run, never re-tuned
    none_ = dict(st)
    ok, _r, none_, _ = _call("advance", [rid], none_, cursor=nh + 6)
    assert ok, "advance reverted"

    a, b = _contract_state(late, rid), _contract_state(none_, rid)
    assert a == b, ("dials set AFTER the roll changed the leg that roll belongs to — the fence is "
                    f"broken: {[(k, a[k], b[k]) for k in a if a[k] != b[k]]}")

    # and dials set BEFORE the roll DO govern that leg (otherwise the fence would be vacuous)
    early = dict(st)
    ok, _r, early, _ = _call("plan", [rid, 8, 1, 90, 20], early, cursor=nh - 1)
    assert ok
    ok, _r, early, _ = _call("advance", [rid], early, cursor=nh + 6)
    assert ok
    c = _contract_state(early, rid)
    assert c != b, "dials set before the roll must actually change the outcome, or nothing is being applied"

    # TWO late plans must not beat the fence. The queue is one generation deep, so an unconditional
    # rotate pushes the GOVERNING generation out: the first post-roll plan lands in the queue slot,
    # both slots then postdate the roll, and the fence falls back to NEUTRAL dials — letting a player
    # who sees a lethal roll knock their own committed aggression down to agg-1 and dodge the leg.
    # Found LIVE when the lossy pool double-landed one late plan() resubmit (kills 22 vs the honest 36).
    # The baseline must be a NON-default governing generation ("early"), because begin's defaults equal
    # the neutral fallback and make the comparison vacuous — the first version of this test passed
    # against the broken contract for exactly that reason.
    twice = dict(st)
    ok, _r, twice, _ = _call("plan", [rid, 8, 1, 90, 20], twice, cursor=nh - 1)   # the honest orders
    assert ok
    ok, _r, twice, _ = _call("plan", [rid, 2, 3, 10, 60], twice, cursor=nh + 5)   # late...
    assert ok
    ok, _r, twice, _ = _call("plan", [rid, 2, 3, 10, 60], twice, cursor=nh + 6)   # ...and its double-land
    assert ok, "a repeated identical plan (a resubmit that double-lands) must be accepted"
    ok, _r, twice, _ = _call("advance", [rid], twice, cursor=nh + 7)
    assert ok
    d = _contract_state(twice, rid)
    assert d == c, ("a DOUBLE post-roll plan changed the leg the honest orders governed: "
                    f"{[(k, d[k], c[k]) for k in d if d[k] != c[k]]}")

    # ...and the newest plan is still the live generation for the NEXT leg — the in-place replacement
    # must not resurrect an older plan later.
    assert twice[A.POLA * (1 << 32) + rid] == 2, "the newest plan must be the live generation"


def t_plan_validates_its_arguments():
    st = {}
    _ok, _r, st, _ = _call("constructor", [], st)
    _ok, _r, st, _ = _call("begin", [52], st, cursor=100)
    ok, _r, _s, _ = _call("plan", [52, 4, 0, 50, 35], dict(st), cursor=200)
    assert ok, "a well-formed dial set must be accepted"
    for args, why in (([52, 99, 0, 50, 35], "aggression above AGG_MAX"),
                      ([52, 0, 0, 50, 35], "aggression below 1"),
                      ([52, 4, 9, 50, 35], "an out-of-range stance"),
                      ([52, 4, 0, 200, 35], "focus above 100"),
                      ([52, 4, 0, 50, 200], "a heal threshold above 100")):
        ok, _r, _s, _ = _call("plan", args, dict(st), cursor=200)
        assert not ok, f"{why} must revert"
    ok, _r, _s, _ = _call("plan", [52, 4, 0, 50, 35], dict(st), caller=999, cursor=200)
    assert not ok, "a non-owner must not set the dials"


def t_advance_is_permissionless_and_late_safe():
    """The lateness argument, manual-only edition.

    The OWNER commits every answer word (that is the design: answers are yours, settlement is anyone's),
    and each committed leg is a pure function of two already-final hashes. So for a given committed leg,
    WHO calls advance() and WHEN must be irrelevant: the owner settling promptly and a stranger settling
    hours later must produce bit-identical state — across several legs, with the commits themselves made
    at identical heights in both timelines so the dice are the same dice.
    """
    RID = 61
    st = {}
    _ok, _r, st, _ = _call("constructor", [], st)
    _ok, _r, st, _ = _call("begin", [RID], st, cursor=100)
    cm = {A.MONSTER: A.A_STRIKE, A.ELITE: A.A_GUARD}

    st_a, st_b = dict(st), dict(st)
    for leg in range(4):
        lh = st_a.get(A.RLH * (1 << 32) + RID, 0)
        if st_a.get(A.RAV * (1 << 32) + RID, 0) != 1 or st_a.get(A.RDN * (1 << 32) + RID, 0):
            break
        word = _leg_word(_answers(_peek_tiles(RID, st_a, lh), cm))
        # the SAME commit, at the SAME height, in both timelines — the owner's action is one event
        ok, _r, st_a, _ = _call("commit", [RID, word], st_a, caller=1234, cursor=lh + 1)
        assert ok
        ok, _r, st_b, _ = _call("commit", [RID, word], st_b, caller=1234, cursor=lh + 1)
        assert ok
        nh = st_a[A.RNH * (1 << 32) + RID]
        # ...then settled promptly by the owner in one timeline, hours later by a stranger in the other.
        # "Late" means as late as the horizon allows: lh + HORIZON - 1 is the last height at which this
        # leg's terrain hash is still readable, so it is the strongest late-safety claim we can make —
        # one block further and the mists rule concludes the run instead (see t_mists_concludes_a_stranded_run).
        ok, _r, st_a, _ = _call("advance", [RID], st_a, caller=1234, cursor=nh + 1)
        assert ok, "owner advance reverted"
        ok, _r, st_b, _ = _call("advance", [RID], st_b, caller=999999, cursor=lh + A.HORIZON - 1)
        assert ok, "advance must be permissionless"
        a, b = _contract_state(st_a, RID), _contract_state(st_b, RID)
        assert a == b, (f"leg {leg}: settling late, by a stranger, changed the outcome: "
                        f"{[(k, a[k], b[k]) for k in a if a[k] != b[k]]}")


def t_mists_concludes_a_stranded_run():
    """THE MISTS. A leg's terrain is BHASH(lh); record_block_hash keeps only ~20000 heights back, so a run
    left parked past HORIZON has a terrain hash no node can read — the leg can never resolve, on any node,
    forever. The rule turns that dead-end into a deterministic conclusion: advance() past the horizon marks
    the run `mists` (terminal, standing) and it scores exactly its last-resolved depth — no completion bonus,
    no retire bonus. Permissionless like every advance, and a public height condition so every node agrees.
    """
    RID = 62
    mi = lambda s: s.get(A.RMI * (1 << 32) + RID, 0)
    st = {}
    _ok, _r, st, _ = _call("constructor", [], st)
    _ok, _r, st, _ = _call("begin", [RID], st, cursor=100)
    cm = {A.MONSTER: A.A_STRIKE, A.ELITE: A.A_GUARD}

    # resolve one leg the honest way, so there is a real last-resolved depth to bank
    lh = st[A.RLH * (1 << 32) + RID]
    word = _leg_word(_answers(_peek_tiles(RID, st, lh), cm))
    ok, _r, st, _ = _call("commit", [RID, word], st, cursor=lh + 1)
    assert ok
    nh = st[A.RNH * (1 << 32) + RID]
    ok, _r, st, _ = _call("advance", [RID], st, cursor=nh + 1)
    assert ok
    resolved = _contract_state(st, RID)
    assert resolved["depth"] == A.LEG, "one resolved leg should stand at depth 16"
    assert mi(st) == 0, "a run mid-march is not in the mists"

    # commit the NEXT leg, then abandon it past the horizon
    lh2 = st[A.RLH * (1 << 32) + RID]
    word2 = _leg_word(_answers(_peek_tiles(RID, st, lh2), cm))
    ok, _r, st, _ = _call("commit", [RID, word2], st, cursor=lh2 + 1)
    assert ok

    # one block short of the horizon the leg still resolves; the boundary itself concludes it
    ok, _r, st_near, _ = _call("advance", [RID], dict(st), caller=555, cursor=lh2 + A.HORIZON - 1)
    assert ok and mi(st_near) == 0, "within the horizon the leg must still resolve, not vanish into the mists"

    ok, _r, st, _ = _call("advance", [RID], st, caller=555, cursor=lh2 + A.HORIZON)
    assert ok, "advance past the horizon must succeed (permissionless conclusion, not a revert)"
    assert mi(st) == 1, "past the horizon the run must be flagged mists"
    # terminal ⇒ nh == 0, like every other ending: a concluded run stranded mid-commit must not keep a
    # live-looking scheduled-dice height (the client's auto-settle gate read exactly that as a leg to settle)
    assert st.get(A.RNH * (1 << 32) + RID, 0) == 0, "the mists must park the dice (RNH = 0)"
    concluded = _contract_state(st, RID)
    banked = {k: concluded[k] for k in ("depth", "kills", "xp", "hp", "streak")}
    kept = {k: resolved[k] for k in banked}
    assert banked == kept, f"the mists must bank the last-resolved state, no bonus: {banked} vs {kept}"
    assert concluded["alive"] == 1 and not concluded["done"], "the mists is standing, not a death or a finish"

    # terminal everywhere: no second conclusion, and the owner can no longer act on it
    ok, _r, _s2, _ = _call("advance", [RID], dict(st), cursor=lh2 + A.HORIZON + 10)
    assert not ok, "a concluded run cannot advance again"
    # march too: it re-states these guards by hand rather than calling _live(), so a run already lost to
    # the mists would otherwise re-conclude itself on every call — ok, a fee, and nothing to show for it
    for meth, args in (("commit", [RID, 0]), ("plan", [RID, 4, 0, 50, 35]), ("retire", [RID]),
                       ("march", [RID, 0, 0])):
        ok, _r, _s2, _ = _call(meth, args, dict(st), cursor=lh2 + A.HORIZON + 10)
        assert not ok, f"{meth} on a run lost to the mists must revert"


def t_only_owner_controls():
    st = {}
    _ok, _r, st, _ = _call("constructor", [], st)
    _ok, _r, st, _ = _call("begin", [71], st, caller=1234, cursor=100)
    lh = st[A.RLH * (1 << 32) + 71]
    for meth, args in (("plan", [71, 7, 3, 50, 35]), ("commit", [71, 5]), ("retire", [71]),
                       ("march", [71, 5, 0])):
        ok, _r, _s, _ = _call(meth, args, dict(st), caller=555, cursor=lh + 1)
        assert not ok, f"{meth} must reject a non-owner"


def t_scratch_leaves_no_residue():
    """advance() uses fixed scratch slots as working registers; none may survive into the state root."""
    st, _run = drive(81, {A.MONSTER: A.A_STRIKE}, legs=3, agg=4)
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
    _ok, _r, st, _ = _call("plan", [rid, 4, M.ST_GUARDED, 0, 35], st, cursor=100)

    # expensive AND survivable, or the run dies in three steps and stresses nothing: top-tier armour in
    # every slot, all-armour focus, Guarded stance, plus `blazing` so every kill drops and _take_item runs
    # on every combat step. Aggression stays moderate — this is a budget test, not a lethality test.
    for sl in range(A.NSLOT):
        affix = A.AF_BLAZE if sl == 0 else A.AF_KEEN
        st[(A.GEAR0 + sl) * (1 << 32) + rid] = 1 + 7 * 64 + 7 * 8 + affix
    st[(A.AFFX + A.AF_BLAZE) * (1 << 32) + rid] = 1
    st[(A.AFFX + A.AF_KEEN) * (1 << 32) + rid] = 1
    st[A.RAL * (1 << 32) + rid] = A.LEVEL_CAP

    cm = {A.MONSTER: A.A_STRIKE, A.ELITE: A.A_STRIKE, A.BOSS: A.A_STRIKE, A.FORK: A.A_RIGHT}
    real_limit = zkvm.GAS_LIMIT
    zkvm.GAS_LIMIT = int(real_limit * HEADROOM)
    try:
        legs_done = 0
        lh = st[A.RLH * (1 << 32) + rid]
        word = _leg_word(_answers(_peek_tiles(rid, st, lh), cm))
        ok, _r, st, _ = _call("commit", [rid, word], st, cursor=lh + 1)
        assert ok, "first commit reverted under the lowered budget"
        for leg in range(24):
            nh = st.get(A.RNH * (1 << 32) + rid, 0)
            if not nh:
                break                               # the run ended; nothing left to stress
            # the standalone advance first — the keeper/mists path must never brick…
            ok, _r, probe, _ = _call("advance", [rid], dict(st), caller=999, cursor=nh + 1)
            assert ok, (f"advance reverted at leg {leg} inside {HEADROOM:.0%} of the trace budget — this is "
                        f"the brick case: a lucky kit made a step too expensive to ever settle")
            if probe.get(A.RAV * (1 << 32) + rid, 0) != 1 or probe.get(A.RDN * (1 << 32) + rid, 0) != 0:
                st = probe
                legs_done += 1
                break
            # …and then march(), the SAME resolve plus the commit tail — the actual worst-case call now.
            # The probe supplies what the pipelined client previews: the next tiles and the parked leg.
            word = _leg_word(_answers(_peek_tiles(rid, probe, probe[A.RLH * (1 << 32) + rid]), cm))
            ok, _r, st, _ = _call("march", [rid, word, probe[A.RLG * (1 << 32) + rid]], st, cursor=nh + 1)
            assert ok, (f"march reverted at leg {leg} inside {HEADROOM:.0%} of the trace budget — the fused "
                        f"op must fit wherever advance fits, or the latency path bricks the lucky runs")
            legs_done += 1
        assert legs_done >= 4, f"stress run only advanced {legs_done} legs — it is not stressing anything"
    finally:
        zkvm.GAS_LIMIT = real_limit


def t_march_equals_advance_plus_commit():
    """march(runId, word, leg) is the LATENCY op: settle-then-answer in one transaction. Its resolve half
    is the shared loop advance() runs and its commit half must be gate-for-gate the commit() method — so
    the whole claim is checkable as byte equality: drive one run with separate advance+commit calls and a
    twin with march, at IDENTICAL cursors, and require the two storage dicts to be IDENTICAL after every
    leg. Any drift — a register the fused op forgets, an extra write, a different pin — fails as a diff,
    not a hunch. The model runs alongside as the third witness.

    Driven TWICE: once on a run that survives every leg, and once on a build that dies inside a fused leg.
    The second is not decoration — the stand-down is the one path where the two halves are supposed to
    DISAGREE about what to write (advance writes nothing further, march must also write nothing), and a
    fused op that stored a zero-valued answer cell where the pair stores no cell at all only ever shows up
    as a dict-KEY diff, which the surviving twin never reaches."""
    def twin(rid, cm, dials=None):
        """Returns True if the comparison actually covered a leg whose commit half stood down."""
        # assignment, never dict.update: a zero write DELETES a slot, so merging each call's output over
        # the previous state resurrects it — plan(heal=0) leaves begin's default 35 standing and the model
        # is then driven with dials the contract never had
        _ok, _r, base, _ = _call("constructor", [], {})
        ok, _r, base, _ = _call("begin", [rid], base, cursor=100)
        assert ok, "begin reverted"
        run = M.Run()
        if dials:
            ok, _r, base, _ = _call("plan", [rid] + list(dials), base, cursor=100)
            assert ok, "plan (dials) reverted"
            run.agg, run.stance, run.focus, run.healpct = dials
        sa, sb = dict(base), dict(base)

        ended = False
        for leg in range(8):
            # twin A runs the two-transaction cadence; both twins use the SAME cursor for everything, so any
            # difference in the resulting storage is the fused op's fault, never the clock's.
            if leg == 0:
                cur = sa[A.RLH * (1 << 32) + rid] + 1   # the first moment the terrain is visible
            else:
                cur = sa[A.RNH * (1 << 32) + rid] + 1   # the first moment the previous dice are visible
                ok, _r, sa, _ = _call("advance", [rid], sa, caller=999, cursor=cur)
                assert ok, f"advance(leg={leg}) reverted"
            ended = (sa.get(A.RAV * (1 << 32) + rid, 0) != 1 or sa.get(A.RDN * (1 << 32) + rid, 0) != 0)
            word = 0
            if not ended:
                lh = sa[A.RLH * (1 << 32) + rid]
                acts = _answers(_peek_tiles(rid, sa, lh), cm)
                word = _leg_word(acts)
                ok, _r, sa, _ = _call("commit", [rid, word], sa, cursor=cur)
                assert ok, f"commit(leg={leg}) reverted"
            # twin B mirrors the WHOLE iteration with one march (on an ended run its commit half stands
            # down — the guards passed before the resolve killed it, so the call still succeeds)
            ok, ret, sb, _ = _call("march", [rid, word, leg], sb, cursor=cur)
            assert ok, f"march(leg={leg}) reverted"
            assert sa == sb, f"leg {leg}: storage diverged"
            if ended:
                break
            nh = sa[A.RNH * (1 << 32) + rid]
            assert ret == nh == cur + A.START_GAP, "march must pin and return dice past its own cursor"
            for i in range(A.LEG):
                if not run.alive or run.done:
                    break
                M.step(run, _words(BH[lh], rid, i), _words(BH[nh], rid, i), action=acts[i])

        # the loop left ONE committed leg unresolved in both twins: close the books identically.
        nh = sa.get(A.RNH * (1 << 32) + rid, 0)
        if nh:
            ok, _r, sa, _ = _call("advance", [rid], sa, caller=999, cursor=nh + 1)
            assert ok, "closing advance (twin A) reverted"
            ok, _r, sb, _ = _call("advance", [rid], sb, caller=999, cursor=nh + 1)
            assert ok, "closing advance (twin B) reverted"
            assert sa == sb, "storage diverged after the closing settle"
        cs, ms = _contract_state(sa, rid), _model_state(run)
        assert cs == ms, {k: (cs[k], ms[k]) for k in cs if cs[k] != ms[k]}
        return ended

    twin(71, {A.MONSTER: A.A_STRIKE, A.ELITE: A.A_GUARD, A.HAZARD: A.A_DODGE, A.BOSS: A.A_STRIKE})
    assert twin(75, {A.MONSTER: A.A_STRIKE, A.ELITE: A.A_STRIKE, A.HORDE: A.A_STRIKE,
                     A.AMBUSH: A.A_STRIKE, A.BOSS: A.A_STRIKE},
                dials=[A.AGG_MAX, M.ST_AGGRESSIVE, 100, 0]), \
        "the lethal twin never reached a stood-down leg — the half of the claim it exists for is untested"


def t_march_pipelined_cadence():
    """The cadence the CLIENT actually runs after this change: answer the NEXT leg while the previous one
    is merely rolled-but-unsettled, and send ONE march that settles leg L and commits leg L+1. The next
    leg's tiles are read from the previous ROLL hash (nh becomes the new lh) at the depth the run will
    have — exactly how the pipelined road strip derives them."""
    rid = 72
    # A REAL classmap, not blanks. A_DEFAULT is 0, so an all-default word IS the all-zero word: driven that
    # way this test could not tell march storing arg(1) from march storing a hard-coded zero, which is the
    # one thing the client's whole word-carrying pipeline depends on.
    cm = {A.MONSTER: A.A_STRIKE, A.ELITE: A.A_GUARD, A.HAZARD: A.A_DODGE, A.BOSS: A.A_STRIKE}
    st = {}
    _ok, _r, st, _ = _call("constructor", [], st)
    ok, _r, st, _ = _call("begin", [rid], st, cursor=100)
    assert ok
    run = M.Run()

    lh = st[A.RLH * (1 << 32) + rid]
    acts = _answers(_peek_tiles(rid, st, lh), cm)
    word = _leg_word(acts)
    assert word, "the answer word must be non-trivial, or storing it and dropping it look the same"
    ok, _r, st, _ = _call("march", [rid, word, 0], st, cursor=lh + 1)   # first answers: pure commit
    assert ok, "first march (pure commit) reverted"
    assert st[A.RCW * (1 << 32) + rid] == word, "march must store the word it was handed"

    for leg in range(6):
        nh = st[A.RNH * (1 << 32) + rid]
        # step the model NOW — the player previews this leg the moment the dice land, then answers the next
        for i in range(A.LEG):
            if not run.alive or run.done:
                break
            M.step(run, _words(BH[lh], rid, i), _words(BH[nh], rid, i), action=acts[i])
        if not run.alive or run.done:
            ok, _r, st, _ = _call("advance", [rid], st, caller=999, cursor=nh + 1)
            assert ok, "closing advance reverted"
            break
        # answer the NEXT sixteen off the roll hash that is about to become the terrain hash, at the depth
        # the run will stand at once this march resolves — the road strip the client draws while the
        # previous leg is still unsettled, which is the only place these answers can come from
        peek = dict(st)
        peek[A.RDP * (1 << 32) + rid] = run.depth
        acts = _answers(_peek_tiles(rid, peek, nh), cm)
        word = _leg_word(acts)
        ok, ret, st, _ = _call("march", [rid, word, leg + 1], st, cursor=nh + 1)
        assert ok, f"fused march(leg={leg + 1}) reverted"
        assert st[A.RLG * (1 << 32) + rid] == leg + 1, "march must have resolved the previous leg"
        assert ret == nh + 1 + A.START_GAP, "…and pinned the next dice past its own cursor"
        # .get: a zero cell is a deleted cell, and an all-default leg answers with the all-zero word
        assert st.get(A.RCW * (1 << 32) + rid, 0) == word, "…storing the word it was handed, not a placeholder"
        assert st.get(A.RCL * (1 << 32) + rid, 0) == leg + 1, "…against the leg it answers"
        cs, ms = _contract_state(st, rid), _model_state(run)
        assert cs == ms, f"leg {leg}: " + str({k: (cs[k], ms[k]) for k in cs if cs[k] != ms[k]})
        lh = nh

    cs, ms = _contract_state(st, rid), _model_state(run)
    assert cs == ms, {k: (cs[k], ms[k]) for k in cs if cs[k] != ms[k]}


def t_march_edges():
    """The conditional commit half: every way it must STAND DOWN without wrecking the settlement, and the
    ways the whole call must revert.

    "Reverted AND left the state untouched" is worth nothing as an assertion here: zkvm.run hands the
    caller's own storage dict straight back on any revert, so comparing it to a copy of that same dict is
    an identity that cannot fail, and it would still hold on a VM that did not roll back. What actually
    pins a guard down is the PAIR — the reverting call and the minimally different one that succeeds — so
    the revert is attributable to the gate under test rather than to some other require further up.
    """
    rid = 73
    st = {}
    _ok, _r, st, _ = _call("constructor", [], st)
    _ok, _r, st, _ = _call("begin", [rid], st, cursor=100)
    lh = st[A.RLH * (1 << 32) + rid]
    word = _leg_word([A.A_STRIKE] * A.LEG)
    stale = _leg_word([A.A_GUARD] * A.LEG)   # never committed by this run, so a stray write to the answer
                                             # cells reads as a diff instead of hiding behind an equal value

    # not the owner: the commit half answers for the run, so march is owner-only (advance stays open).
    # Its control is the eligible owner call below, at the identical cursor.
    ok, _r, _s2, _ = _call("march", [rid, word, 0], dict(st), caller=999, cursor=lh + 1)
    assert not ok, "march by a non-owner must revert"

    # not before the terrain is visible either. The leg's tiles come from BHASH(lh) and its dice from
    # BHASH(cursor + START_GAP), so at cursor lh - START_GAP the two are the SAME block hash: terrain and
    # rolls perfectly correlated, which is the one thing the whole design is built to keep apart. march
    # folds commit()'s cursor gate into its eligibility flag, so both entry points must refuse it.
    ok, _r, _s2, _ = _call("march", [rid, word, 0], dict(st), cursor=lh - A.START_GAP)
    assert not ok, "march before this leg's terrain exists must revert"
    ok, _r, _s2, _ = _call("commit", [rid, word], dict(st), cursor=lh - A.START_GAP)
    assert not ok, "…and standalone commit refuses that same cursor — march inherits its gate"

    # nothing to do: dice already scheduled but not yet mined -> no resolve, no park, must revert (the
    # no-op honesty rule). Its control is the happy fused call at the bottom: same args, one block later.
    ok, _r, st, _ = _call("march", [rid, word, 0], st, cursor=lh + 1)
    assert ok, "eligible march reverted"
    nh = st[A.RNH * (1 << 32) + rid]
    ok, _r, _s2, _ = _call("march", [rid, word, 1], dict(st), cursor=nh - 1)
    assert not ok, "march with dice pending and nothing resolvable must revert"

    # RETIRED: march re-states _live()'s requires by hand instead of calling it, so each one needs its own
    # case. A run that has already cashed out must not resolve one more leg or pin fresh dice.
    ok, _r, st_rt, _ = _call("retire", [rid], dict(st), cursor=nh - 1)
    assert ok, "retire reverted"
    ok, _r, _s2, _ = _call("march", [rid, word, 1], st_rt, cursor=nh + 1)
    assert not ok, "march on a retired run must revert"

    # WRONG LEG: the resolve half lands, the stale word must NOT answer tiles it wasn't written for —
    # the run parks (RNH == 0) instead of committing, and no answer cell moves
    cells = _answer_cells(st, rid, 1)
    ok, _r, st_wrong, _ = _call("march", [rid, stale, 5], dict(st), cursor=nh + 1)
    assert ok, "march with a stale leg must still settle"
    assert st_wrong[A.RLG * (1 << 32) + rid] == 1, "the leg must have resolved"
    assert st_wrong.get(A.RNH * (1 << 32) + rid, 0) == 0, "…but the stale word must not schedule dice"
    assert _answer_cells(st_wrong, rid, 1) == cells, "…nor answer the leg it was not written for"

    # OVERSIZED WORD: same stand-down — settle yes, commit no
    ok, _r, st_big, _ = _call("march", [rid, 1 << (3 * A.LEG), 1], dict(st), cursor=nh + 1)
    assert ok and st_big.get(A.RNH * (1 << 32) + rid, 0) == 0, \
        "an out-of-range word must settle the leg and drop the answers"
    assert _answer_cells(st_big, rid, 1) == cells, "…and never reach the answer cells"
    # …and with nothing to settle either, an oversized word is a full no-op -> revert
    ok, _r, _s2, _ = _call("march", [rid, 1 << (3 * A.LEG), 1], dict(st_big), cursor=nh + 2)
    assert not ok, "no resolve + no commit must revert"

    # THE MISTS, reached through the fused op. march is the client's primary call now, so the horizon
    # conclusion has to count as "something happened" here exactly as it does in advance() — otherwise the
    # one run that can never resolve is the one whose every retry reverts and burns a fee.
    ok, _r, st_mist, _ = _call("march", [rid, word, 1], dict(st), cursor=lh + A.HORIZON)
    assert ok, "march past the horizon must conclude the run, not revert"
    assert st_mist[A.RMI * (1 << 32) + rid] == 1, "…flagged mists"
    assert st_mist.get(A.RNH * (1 << 32) + rid, 0) == 0, "…with the dice parked, like every other ending"
    assert _contract_state(st_mist, rid) == _contract_state(st, rid), \
        "the mists must bank the last-resolved state exactly — no leg, no bonus"

    # the happy fused path from the same state, as the control
    ok, _r, st_ok, _ = _call("march", [rid, word, 1], dict(st), cursor=nh + 1)
    assert ok and st_ok[A.RNH * (1 << 32) + rid] == nh + 1 + A.START_GAP


def t_march_stands_down_on_death():
    """A march whose resolve half kills the run must keep the settlement (you died where you died) and
    drop the answers — never commit a word, never schedule dice, never revert the death away."""
    rid = 74
    st = {}
    _ok, _r, st, _ = _call("constructor", [], st)
    _ok, _r, st, _ = _call("begin", [rid], st, cursor=100)
    _ok, _r, st, _ = _call("plan", [rid, A.AGG_MAX, M.ST_AGGRESSIVE, 100, 0], st, cursor=100)
    word = _leg_word([A.A_STRIKE] * A.LEG)
    lh = st[A.RLH * (1 << 32) + rid]
    ok, _r, st, _ = _call("march", [rid, word, 0], st, cursor=lh + 1)
    assert ok, "first march (pure commit) reverted"
    doomed, doomed_cur, doomed_leg = None, 0, 0
    for leg in range(30):
        nh = st.get(A.RNH * (1 << 32) + rid, 0)
        if not nh:
            break                                   # the commit half stood down: the resolve ended the run
        # ONE fused call resolves the rolled leg and (if the run survives it) commits the next answers
        doomed, doomed_cur, doomed_leg = dict(st), nh + 1, leg + 1
        ok, _r, st, _ = _call("march", [rid, word, leg + 1], st, cursor=nh + 1)
        assert ok, f"fused march(leg={leg + 1}) reverted"
    assert st.get(A.RAV * (1 << 32) + rid, 0) != 1, \
        "agg 16 aggressive all-strike did not die in 30 legs — the test stressed nothing"
    assert st.get(A.RNH * (1 << 32) + rid, 0) == 0, "a dead run must never carry scheduled dice"

    # the fatal leg again, carrying a word this run has NEVER committed. Every leg above answered with the
    # same word, so a commit half that wrote the readable mirror regardless of the flag would have stored a
    # value identical to the one already sitting there and left no trace at all.
    other = _leg_word([A.A_GUARD] * A.LEG)
    cells = _answer_cells(doomed, rid, doomed_leg)
    ok, _r, st_f, _ = _call("march", [rid, other, doomed_leg], dict(doomed), cursor=doomed_cur)
    assert ok, "the fatal march must still settle the leg that killed the run"
    assert st_f.get(A.RAV * (1 << 32) + rid, 0) != 1, "…and keep the death"
    assert st_f.get(A.RNH * (1 << 32) + rid, 0) == 0, "…schedule no dice"
    assert _answer_cells(st_f, rid, doomed_leg) == cells, "…and write no answers onto a run that just died"

    # terminal: the very call that just succeeded against the live state must now revert
    ok, _r, _s2, _ = _call("march", [rid, other, doomed_leg], dict(st), cursor=99999)
    assert not ok, "march on a dead run must revert"


def t_js_engine_matches_the_model():
    """The browser engine is the THIRD implementation, and the client uses it to preview your answers
    before you commit them. A preview that disagrees with settlement is worse than no preview, so it gets
    the same treatment as everything else here: driven over identical inputs and diffed field by field.

    The model is already proven against the contract above, so this chains the browser engine transitively
    to the chain. Vectors carry raw hash windows plus the per-step ACTION — what is under test is the step
    function, not the sponge."""
    import json, shutil, subprocess, tempfile
    node = shutil.which("node")
    if not node:
        print("      (node not installed — skipping the browser-engine check)")
        return

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # regenerating the rules must be a no-op: if it is not, the browser is running different numbers.
    # The file has TWO generators — the constant table emitted from this module, and the ACTS_FOR matrix
    # DERIVED by tests/autogame_action_matrix.py, which appends its block after it. Demanding byte equality
    # with the constant table alone therefore failed the moment the matrix was regenerated, which read as
    # "the browser has different numbers" when the numbers were identical. The constant table must be an
    # exact PREFIX; the matrix checks its own block with `autogame_action_matrix.py --check`.
    from execnode.games.autogame import rules_js
    on_disk = open(os.path.join(root, "static", "autogame-rules.js")).read()
    assert on_disk.startswith(rules_js()), \
        "static/autogame-rules.js is stale — regenerate: python3 -m execnode.games.autogame --emit-js"
    assert "ACTS_FOR" in on_disk, \
        "static/autogame-rules.js lost its action matrix — regenerate: python3 tests/autogame_action_matrix.py"

    cases = []
    configs = [("balanced", 0, 35, 50, 3), ("berserker", 1, 20, 75, 6), ("turtle", 2, 60, 0, 2),
               ("skirmisher", 3, 45, 25, 4), ("vampire", 0, 25, 100, 5)]
    for ci, (name, stance, heal, focus, agg) in enumerate(configs):
        run = M.Run(stance=stance, healpct=heal, focus=focus)
        run.agg = agg
        steps = []
        for n in range(400):
            tw = _words(BH[3000 + n], 7, n % A.LEG)
            rw = _words(BH[9000 + n], 7, n % A.LEG)
            act = (n * 3 + ci) % 8              # every action, in a different phase per archetype
            M.step(run, tw, rw, action=act)
            steps.append({"tw": tw, "rw": rw, "act": act, "agg": agg,
                          "after": {"hp": run.hp, "maxhp": run.maxhp, "stam": run.stam,
                                    "potions": run.potions, "xp": run.xp, "banked": run.banked,
                                    "streak": run.streak, "depth": run.depth, "kills": run.kills,
                                    "alive": run.alive, "done": run.done, "wlevel": run.wlevel,
                                    "alevel": run.alevel, "gear": list(run.gear), "mats": list(run.mats)}})
            if not run.alive or run.done:
                break
        cases.append({"name": name, "stance": stance, "healpct": heal, "focus": focus,
                      "agg": agg, "steps": steps, "score": run.score()})

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
        ok, _r, st, _ = _call("plan", [rid, 2, 1, 50, 35], st, cursor=100)
        assert ok, f"plan({rid}) reverted"

    c = {"abi": A.ABI, "runtime": "zkvm",
         "storage": {"slots": {str(k): str(v) for k, v in st.items()}}}
    es = ExecState.__new__(ExecState)
    es.zk_addrs = {}
    view = ExecState.decode_view(es, c)

    assert view, "the view decoded to nothing at all"
    # `lv` is the run's alive flag. It used to be `av`, which is the name static/provable.js reads the DAY
    # ANCHOR from on every provable board — mounting the Daily Gauntlet on this contract made the two
    # collide. The names are one-per-purpose now, and this list is what pins that down.
    # `nh` is deliberately NOT here: a freshly begun run is armed-but-parked, and a parked run's nh is 0 —
    # a zero slot is a deleted slot, so the map is legitimately empty until a leg is committed.
    for name in ("hp", "mx", "lv", "fo", "hl", "lh", "pa"):
        got = sorted((view.get(name) or {}).keys())
        assert got == [str(i) for i in ids], f"map {name!r} enumerated {got}, want {ids}"
    assert all(v == A.HP0 for v in view["hp"].values()), f"hp map wrong: {view['hp']}"
    # a run the client can actually find: the owner map must resolve, not be a bare digest
    assert set((view.get("ra") or {}).keys()) == {str(i) for i in ids}, "owner map must list every run"
    assert "av" not in view, "the alive flag must not shadow the provable board's day-anchor map"
    # manual-only pruned the doctrine and auto maps from the schema; a resurrected name here means someone
    # re-grew the second mode
    for dead in ("p0", "p9", "q0", "q9", "au"):
        assert dead not in view, f"map {dead!r} belongs to the removed auto/doctrine mode"

    # The Daily Gauntlet rides its OWN index (entries) and day index, which the run index must not touch:
    # a claim posted today has to decode under a key set that has nothing to do with run ids.
    ok, _r, st, _ = _call("anchor", [20000], st, cursor=100, timestamp=20000 * 86400 + 5)
    assert ok, "anchor(day) reverted on a fresh day"
    words = [7] * A.DAILY_WORDS
    ok, _r, st, _ = _call("post", [20000, 1234, A.DAILY_HEAD + 10] + words, st, cursor=100,
                          timestamp=20000 * 86400 + 5)
    assert ok, "post(day, score, n, w...) reverted"
    c["storage"]["slots"] = {str(k): str(v) for k, v in st.items()}
    view = ExecState.decode_view(es, c)
    assert sorted((view.get("eday") or {}).keys()) == ["0"], f"claim index: {view.get('eday')}"
    assert view["eday"]["0"] == 20000 and view["escore"]["0"] == 1234
    assert view["en"]["0"] == A.DAILY_HEAD + 10
    for k in range(A.DAILY_WORDS):
        assert view.get(f"ew{k}", {}).get("0") == 7, f"claim word {k} did not decode"
    assert sorted((view.get("ah") or {}).keys()) == ["20000"], f"day index: {view.get('ah')}"
    assert set((view.get("lv") or {}).keys()) == {str(i) for i in ids}, \
        "the claim index must not leak into the run maps"


def t_per_tile_answers_and_the_unscheduled_roll():
    """The point of the whole design, now the ONLY design: you answer the SPECIFIC tiles in front of you,
    and the dice for them do not exist until you do.

    A leg parks with nh == 0; advance() refuses. The terrain is visible, you commit an answer to those
    sixteen tiles, and committing is what schedules the roll — so a per-tile answer can never be racing a
    window, at any lag.
    """
    rid = 71
    st = {}
    _ok, _r, st, _ = _call("constructor", [], st)
    _ok, _r, st, _ = _call("begin", [rid], st, cursor=100)
    lh = st[A.RLH * (1 << 32) + rid]
    assert lh, "begin must arm"
    assert st.get(A.RNH * (1 << 32) + rid, 0) == 0, "the roll must NOT be scheduled at begin"

    ok, _r, _s, _ = _call("advance", [rid], dict(st), cursor=lh + 500)
    assert not ok, "advance must refuse a leg whose dice were never scheduled"

    # answering the visible tiles schedules the roll
    answers = [A.A_STRIKE if i % 2 == 0 else A.A_GUARD for i in range(A.LEG)]
    word = _leg_word(answers)
    ok, _r, _s, _ = _call("commit", [rid, word], dict(st), cursor=lh - 1)
    assert not ok, "committing before the terrain is visible must revert"
    ok, _r, st, _ = _call("commit", [rid, word], st, cursor=lh + 3)
    assert ok, "commit reverted"
    nh = st[A.RNH * (1 << 32) + rid]
    assert nh > lh + 3, f"committing must schedule the roll in the FUTURE (nh={nh}, cursor={lh + 3})"
    ok, _r, _s, _ = _call("commit", [rid, word], dict(st), cursor=nh - 1)
    assert not ok, "a second commit for the same leg must revert — the dice are already scheduled"

    # and the answers actually change the outcome
    ok, _r, st2, _ = _call("advance", [rid], dict(st), cursor=nh + 1)
    assert ok, "advance reverted"
    bare = dict(st)
    import execnode.stark.alghash as _ah
    bare[_ah.hashn([A.OVR_TAG, rid, 0])] = 0          # same leg, all answers blanked to A_DEFAULT
    ok, _r, st3, _ = _call("advance", [rid], bare, cursor=nh + 1)
    assert ok
    a, b = _contract_state(st2, rid), _contract_state(st3, rid)
    assert a != b, "per-tile answers must actually change what happens"

    # after the leg settles the march parks again — the next roll waits for your next answers
    assert st2.get(A.RNH * (1 << 32) + rid, 0) == 0, "the march must park after settling"


def t_constants_are_not_duplicated():
    """The model must IMPORT the rules, never restate them — otherwise a retune desyncs the oracle from
    the thing it checks and this whole file silently stops meaning anything."""
    src = open(os.path.join(os.path.dirname(__file__), "autogame_model.py")).read()
    assert "from execnode.games.autogame import" in src, "model must import the contract's constants"
    for name in ("CHAPTER", "BOSS_EVERY", "STREAK_DIV", "DEATH_KEEP", "HORDE_DIV"):
        assert f"\n{name} = " not in src, f"{name} is redefined in the model — it must be imported"
        assert getattr(M, name) == getattr(A, name), f"{name} differs between model and contract"


if __name__ == "__main__":
    check("the all-blank answer word (walk in, fight plainly)", t_blank_answers)
    check("every reaction, including unaffordable degradation", t_every_reaction)
    check("all stances x focus splits", t_all_stances_and_focus)
    check("long run across a boss checkpoint", t_long_run_to_boss)
    check("death is terminal and a dead run cannot advance", t_death_is_terminal)
    check("dials cannot rewrite a leg whose dice already rolled", t_dials_cannot_rewrite_a_rolled_leg)
    check("plan validates its arguments", t_plan_validates_its_arguments)
    check("advance is permissionless and late-safe", t_advance_is_permissionless_and_late_safe)
    check("the mists conclude a run stranded past the block-hash horizon", t_mists_concludes_a_stranded_run)
    check("only the owner controls a run", t_only_owner_controls)
    check("scratch leaves no residue in the state root", t_scratch_leaves_no_residue)
    check("worst-case advance has trace headroom (a lucky run must not brick)", t_worst_case_advance_has_headroom)
    check("march == advance + commit, byte for byte", t_march_equals_advance_plus_commit)
    check("march runs the pipelined cadence the client sends", t_march_pipelined_cadence)
    check("march commit half stands down where it must", t_march_edges)
    check("march stands down on death and keeps the settlement", t_march_stands_down_on_death)
    check("storage view decodes into the maps the client reads", t_storage_view_actually_decodes)
    check("per-tile answers, and a roll that is not scheduled until you give them",
          t_per_tile_answers_and_the_unscheduled_roll)
    check("browser engine matches the model (transitively, the chain)", t_js_engine_matches_the_model)
    check("rules are imported, not duplicated", t_constants_are_not_duplicated)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
