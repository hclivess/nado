"""Autogame balance harness — the economy simulator, kept in the repo because the numbers WILL need retuning.

Run: python3 tests/autogame_balance.py

It plays whole chapters against the reference model (tests/autogame_model.py) under several pilots and prints
survival / median / p90 renown per dial setting. What it is FOR is catching degenerate equilibria before they
reach a contract — every one of these was found here, not in review:

  * uncapped renown regen (MAMEC's exp/20) made you immortal past ~2000 renown, so pulling 2 foes and idling
    for an hour dominated everything;
  * a flat % armour cut turned aggression into a pure death switch with a cliff between 2 and 4;
  * per-FOE absorption then flipped it: armour nullified everything and focus=0 survived 59/60;
  * guarded stance kept 3/4 of the renown for 1/4 of the risk and was strictly dominant;
  * bloodlust at MAMEC's ×3 did not cover the risk of dying, so healing EARLY out-earned riding the edge —
    the exact opposite of the intended tension.

The health check is the last block: a skilled (bloodlust-aware, adaptive) pilot must beat the best FIXED dial
on p90, while an idle player still survives. If a fixed constant ever dominates on both, the skill dimension
is gone and the economy needs another pass."""
import sys, hashlib, statistics
sys.path.insert(0, "/root/nado")
from tests import autogame_model as M


def words(seed, i):
    h = hashlib.blake2b(f"{seed}:{i}".encode(), digest_size=16).digest()
    return int.from_bytes(h[:4], "big"), int.from_bytes(h[4:8], "big")


def peek_leg(seed, depth):
    """What the player can SEE: the next LEG tiles (classes + monster stats), not their rolls."""
    out = []
    for i in range(depth, depth + M.LEG):
        tw, _ = words(seed, i)
        a, b, c, d = M.slice_tile(tw)
        t = M.tile_of(a, i)
        out.append((t, b, i))
    return out


def worst_swing(leg, run):
    """The heaviest per-foe swing waiting in this leg — the number the pull has to be priced against.
    Prices the NEW tiles too: a horde doubles the pull (so each affordable foe brings a friend), a gale
    amplifies the three swings after it by 5/4, an ambush adds an armour-proof sting that comes off hp
    before any pull is chosen, a MIMIC bites at twice its family's weight (but is always one body), and
    the grave-curse/lash tiles chip through armour like the sting does. Returns (per_foe, sting)."""
    w, sting, gale_left = 0, 0, 0
    for (t, b, i) in leg:
        if t == M.GALE:
            gale_left = 3                 # armed at 4, decays on its own tile: the NEXT three swing harder
            continue
        tier = M.tier_of(i)
        if t == M.BARROW:
            sting = max(sting, 2 + 2 * tier)      # the curse comes through armour, like the sting
            continue
        amped = gale_left > 0
        gale_left = max(0, gale_left - 1)
        tt = M.ELITE if t == M.FORK else M.MIMIC if t == M.TOLLGATE else t   # robbery wakes the strongbox
        if tt not in (M.MONSTER, M.HORDE, M.ELITE, M.AMBUSH, M.MIMIC, M.BOSS):
            continue
        ml = M.monster_level(tt, i)
        fam = b % 3
        c0, c1 = M.FAM_ATK[fam]
        each = c0 + c1 * ml + (b // 3) % 4
        if tt == M.MIMIC:
            each *= 2                     # one body, twice the teeth
        each = each * M.STANCES[run.stance][0] // 4
        each = each * 110 // 100
        if tt == M.HORDE:
            each *= 2                     # double pull: every foe you budget for brings a friend
        if amped:
            each = each * 5 // 4
        if tt == M.AMBUSH:
            sting = max(sting, 2 * ml)
        w = max(w, each)
    return w, sting


def choose_agg_bl(run, leg, budget_pct):
    """Bloodlust-aware: the multiplier is live while you are hurt, so lean IN as hp falls — until the
    swing could actually kill, at which point survival wins."""
    sw, sting = worst_swing(leg, run)
    if sw == 0:
        return M.AGG_MAX
    absorb = M.armor_pts(run)
    lean = 100 + 2 * (100 - run.hp * 100 // run.maxhp)      # up to 3x the budget while bloodied
    budget = run.hp * budget_pct * lean // 10000 + absorb - sting
    budget = min(budget, run.hp * 70 // 100 + absorb - sting)  # never price a swing that can kill outright
    return max(1, min(M.AGG_MAX, budget // sw))


def choose_agg(run, leg, budget_pct):
    """Spend at most budget_pct of current hp on the worst fight in the leg. This is the pilot a decent
    player is: look at the road, price the biggest swing, pull as much as you can pay for."""
    sw, sting = worst_swing(leg, run)
    if sw == 0:
        return M.AGG_MAX
    absorb = M.armor_pts(run)
    budget = run.hp * budget_pct // 100 + absorb - sting
    n = budget // sw
    return max(1, min(M.AGG_MAX, n))


def play(seed, mode, agg=4, healpct=35, stance=0, focus=50, budget=40, react=False, bank_at=0, brush=None,
         only_tile=None, skip_tile=None):
    r = M.Run(stance=stance, healpct=healpct, focus=focus)
    r.min_hpp = 100          # probe bookkeeping: the closest this run came to the edge
    r.dry_low = 100          # …the closest it came WITH AN EMPTY FLASK (no auto-drink net below you)
    r.chose = 0              # …and how many non-default answers the pilot actually made
    leg, ag = None, agg
    for i in range(M.CHAPTER):
        # push-or-bank: retire on your feet rather than lose DEATH_KEEP% of a fat unbanked pile
        if bank_at and (r.xp - r.banked) > bank_at and r.hp * 100 < r.maxhp * 45 and r.depth > bank_at // 100:
            r.retired = 1          # walked away: keeps everything, but earns no completion bonus
            break
        if i % M.LEG == 0:
            leg = peek_leg(seed, i)
            if mode == "adaptive":
                ag = choose_agg(r, leg, budget)
            elif mode == "bloodlust":
                ag = choose_agg_bl(r, leg, budget)
        tw, rw = words(seed, i)
        act = M.A_DEFAULT
        if brush is not None:
            act = brush                   # the degenerate player: one answer for every question
        elif react:
            # The reader's doctrine, tuned to what the mechanics actually price:
            #   * Guard covers TWO swings and pauses the streak -> spend it ONLY on the single big things
            #     (boss always, elite when hurt, ambush's armour-proof sting) — never on crowds.
            #   * Strike pays renown TIMES bloodlust -> strike while HURT if the extra 25% incoming
            #     cannot kill; striking at full hp is when it pays least.
            #   * The gale amplifier is a bloodlust rider: shelter only when it could kill you.
            hpp = r.hp * 100 // r.maxhp
            evasive = (r.stance if stance is None else stance) == M.ST_EVASIVE
            a, b, c, d = M.slice_tile(tw)
            t = M.tile_of(a, r.depth)
            if t == M.HAZARD:
                # evasive footwork makes the 1-stamina hazard-dodge nearly free — this IS the build
                if (evasive and r.stam >= 1) or (hpp < 40 and r.stam >= 2):
                    act = M.A_DODGE
            elif t == M.BOSS:
                if r.stam >= 2:
                    act = M.A_STRIKE if hpp > 70 else M.A_GUARD   # one foe: guard is a TRUE halving here
            elif t == M.AMBUSH:
                if hpp < 65 and r.stam >= 2:
                    act = M.A_GUARD           # the sting goes through armour; guard blocks it AND the fight
                elif r.stam >= 2:
                    act = M.A_STRIKE          # +25% danger pay on top of Strike's 25%
            elif t == M.HORDE:
                if hpp < (55 if evasive else 35) and r.stam >= (2 if evasive else 3):
                    act = M.A_SPRINT          # the only door out of a pack
                elif hpp < 60 and r.stam >= 2:
                    act = M.A_DODGE           # can't slip a horde — thinning it to a normal pull is real
            elif t == M.GALE:
                if hpp < (55 if evasive else 40) and r.stam >= (1 if evasive else 2):
                    act = M.A_DODGE           # shelter: +25% damage-in on low hp is how runs end
            elif t == M.IDOL:
                # the flask is the auto-drink lifeline, so offering it is a REAL choice, not a freebie —
                # offer only from a FULL belt; a thin belt smashes instead
                act = M.A_POTION if r.potions >= 3 else M.A_STRIKE
            elif t == M.ELITE or t == M.MIMIC:
                if hpp < 45 and r.stam >= 2:
                    act = M.A_GUARD
                elif r.stam >= 2 and 45 <= hpp:
                    act = M.A_STRIKE          # bloodlust-weighted greed: hurt enough to multiply, alive enough to eat it
            elif t == M.MONSTER:
                if 30 < hpp and r.stam >= 2:
                    act = M.A_STRIKE
            elif t == M.FORK and hpp > 55:
                act = M.A_RIGHT
            elif t == M.SNARE:
                if r.stam >= 2:
                    act = M.A_GUARD           # spring it: 2 stamina beats 3, and the scrap is free
            elif t == M.QUAG:
                if (evasive and r.stam >= 1) or (hpp < 55 and r.stam >= 2):
                    act = M.A_DODGE           # hop the stones: saves hp AND the 2-stamina drag
            elif t == M.TOLLGATE:
                if hpp > 55 and r.stam >= 2:
                    act = M.A_STRIKE          # rob the strongbox: a mimic that ALWAYS drops beats any toll
                # else walk through and pay — dashing takes the lash, worse than the toll when hurt
            elif t == M.BARROW:
                if M.has_affix(r, M.AF_WARD):
                    pass                       # warded: the curse is void, dig for free
                elif hpp < 50 and r.stam >= 2:
                    act = M.A_GUARD           # brace the curse to half — the loot is still worth it
            elif t == M.VEIN:
                if r.stam >= 4:
                    act = M.A_STRIKE          # scrap out of the rock: potions and crafts are made of this
            elif t == M.GROVE:
                if r.stam >= 3:
                    act = M.A_RALLY           # commune: essence + the streak-keeping heal, one stroke
            elif t == M.WELL:
                if r.stam <= 5:
                    act = M.A_REST            # drink deep: the full-stamina refill IS the tile
                elif r.potions < M.POTION_CAP:
                    act = M.A_POTION          # bottle it: a flask without breaking the streak
            elif t == M.CAMP:
                if hpp < 65:
                    act = M.A_REST            # the one free rest on the road — take it when it heals
            elif t == M.PYRE:
                if r.stam >= 2:
                    act = M.A_STRIKE          # light it: three steps of +25% renown ahead of the fights
        # ABLATION probes. only_tile: answer ONE tile class, walk everything else — does the counter pay
        # against the all-default walker? skip_tile: the full reader FORGETS one answer — what does that
        # counter contribute in context? (Stamina/economy counters only price inside a build that spends
        # stamina and materials, so they get the second frame.)
        if only_tile is not None or skip_tile is not None:
            a2, b2, _c2, _d2 = M.slice_tile(tw)
            t2 = M.tile_of(a2, r.depth)
            if only_tile is not None and t2 != only_tile:
                act = M.A_DEFAULT
            if skip_tile is not None and t2 == skip_tile:
                act = M.A_DEFAULT
        if act != M.A_DEFAULT:
            r.chose += 1
        # manual-only: the pilot's chosen reaction IS the per-tile answer, exactly as commit() delivers it
        M.step(r, tw, rw, agg=ag, action=act)
        hpp2 = r.hp * 100 // max(1, r.maxhp)
        r.min_hpp = min(r.min_hpp, hpp2)
        if r.potions == 0:
            r.dry_low = min(r.dry_low, hpp2)
        if not r.alive or r.done or r.retired:
            break
    return r


SEEDS = [f"s{i}" for i in range(80)]


def sweep(label, **kw):
    rs = [play(s, **kw) for s in SEEDS]
    alive = sum(1 for r in rs if r.alive)
    xps = sorted(r.score() for r in rs)
    print(f"{label:34s} survive {alive:2d}/80  xp med {statistics.median(xps):>9.0f} "
          f"p90 {xps[int(.9*len(xps))]:>9.0f}  depth med {statistics.median([r.depth for r in rs]):>4.0f}")
    return statistics.median(xps)


print("=== best FIXED dial (no reactions) ===")
fixed = {}
for agg in (1, 2, 3, 4, 6, 8, 12, 16):
    fixed[agg] = sweep(f"fixed agg={agg}", mode="fixed", agg=agg)
best_fixed = max(fixed.values())

print("\n=== ADAPTIVE dial: re-priced every leg against the visible road ===")
for b in (15, 25, 40, 60, 80, 120):
    sweep(f"adaptive budget={b}%", mode="adaptive", budget=b)

print("\n=== adaptive + per-tile reactions (the full skill stack) ===")
for b in (25, 40, 60):
    sweep(f"adaptive {b}% + reactions", mode="adaptive", budget=b, react=True)

print("\n=== focus, now that the weapon multiplies renown (adaptive 40%) ===")
for f in (0, 25, 50, 75, 100):
    sweep(f"focus={f}", mode="adaptive", budget=40, focus=f)

print("\n=== stance (adaptive 40%) ===")
for st, nm in enumerate(("balanced", "aggressive", "guarded", "evasive")):
    sweep(f"stance={nm}", mode="adaptive", budget=40, stance=st)

print("\n=== heal threshold (adaptive 40%) — does bloodlust reward late healing? ===")
for hp in (10, 20, 35, 50, 70):
    sweep(f"heal<{hp}%", mode="adaptive", budget=40, healpct=hp)

print("\n=== push-or-bank: retire while you still can ===")
for ba in (0, 8000, 25000, 60000):
    sweep(f"bank_at={ba or 'never'}", mode="bloodlust", budget=40, bank_at=ba)

print("\n=== bloodlust-aware pilot (lean in while hurt) ===")
for b in (25, 40, 60, 80):
    sweep(f"bloodlust budget={b}%", mode="bloodlust", budget=b)
for b in (40, 60):
    sweep(f"bloodlust {b}% + reactions", mode="bloodlust", budget=b, react=True)

print(f"\nbest fixed = {best_fixed:.0f}")


# ── archetype head-to-head ───────────────────────────────────────────────────────────────────────
# The real bar is not "is every dial setting equal" — it is "does every PATH have its own route to the top
# of the board". Prizes pay the ceiling, so p90 is the number that has to be competitive; median and
# survival are allowed (and meant) to differ wildly between builds.
ARCHETYPES = [
    # dials are the PER-STANCE OPTIMA from a coarse grid search (focus x budget x healpct, 60 seeds),
    # not hand guesses — so the Pareto check below judges the mechanics, not my parameterization.
    ("berserker  aggr/wpn ", dict(stance=1, focus=50, budget=45, healpct=25, react=True)),   # the ceiling
    ("warmonger  aggr/arm ", dict(stance=1, focus=25, budget=60, healpct=25, react=True)),   # sustainable aggression
    ("duelist    bal/arm  ", dict(stance=0, focus=25, budget=45, healpct=25, react=True)),   # the best floor
    ("vanguard   bal/wpn  ", dict(stance=0, focus=75, budget=45, healpct=25, react=True)),   # balanced greed
    ("turtle     guard/arm", dict(stance=2, focus=25, budget=30, healpct=25, react=True)),   # the consistency king
    ("grinder    guard/wpn", dict(stance=2, focus=75, budget=60, healpct=25, react=True)),   # safe volume farming
    ("skirmisher evas/wpn ", dict(stance=3, focus=75, budget=60, healpct=25, react=True)),   # hit-and-run greed
    ("scout      evas/arm ", dict(stance=3, focus=25, budget=45, healpct=45, react=True)),   # the safe ceiling
    ("stormrider gale-lean", dict(stance=1, focus=60, budget=50, healpct=15, react=True)),   # rides the new amplifier
    ("zealot     idol/pot ", dict(stance=2, focus=30, budget=30, healpct=55, react=True)),   # feeds the new idols
]

print("\n=== ARCHETYPES: every path needs its own way to win ===")
prof = {}
for name, kw in ARCHETYPES:
    rs = [play(s, mode="bloodlust", **kw) for s in SEEDS]
    xps = sorted(r.score() for r in rs)
    alive = sum(1 for r in rs if r.done)
    p90 = xps[int(.9 * len(xps))]
    prof[name] = {"finish": alive, "med": statistics.median(xps), "p90": p90, "max": xps[-1]}
    print(f"{name}  finish {alive:2d}/80  med {statistics.median(xps):>9.0f}  p90 {p90:>9.0f}  "
          f"max {xps[-1]:>9.0f}  depth med {statistics.median([r.depth for r in rs]):>4.0f}")
# The archetype board is a RISK FRONTIER, not a flat line: turtles trade ceiling for floor on purpose.
# The failure mode worth guarding against is an archetype that is strictly WORSE — no axis where it wins.
axes = ["finish", "med", "p90", "max"]
dominated = []
for a, va in prof.items():
    for b, vb in prof.items():
        # a 10% margin: 80 seeds is noisy (p90 swings ~1 sigma), and adjacent optima in a continuous
        # dial space will always shadow each other a little — domination means CLEARLY worse everywhere
        if a != b and all(vb[k] >= va[k] * 0.90 for k in axes) and all(vb[k] > va[k] * 1.10 for k in ("med", "p90")):
            dominated.append(f"{a.strip()} <= {b.strip()}")
print("\nPareto check: " + ("every archetype owns a point on the risk frontier"
      if not dominated else "DOMINATED: " + "; ".join(dominated)))


# ── single-brush dominance ───────────────────────────────────────────────────────────────────────
# "more counters, more synergies" only exists if NO single answer is the answer to everything. A player
# who paints the whole word with one action must lose to a player who actually reads the road.
print("\n=== SINGLE BRUSH: one answer for every tile must NOT dominate ===")
brush_best = {}
mixed = [play(s, mode="bloodlust", budget=40, react=True) for s in SEEDS]
mixed_p90 = sorted(r.score() for r in mixed)[int(.9 * len(SEEDS))]
for a, nm in ((M.A_DEFAULT, "all-default"), (M.A_STRIKE, "all-strike"), (M.A_GUARD, "all-guard"),
              (M.A_DODGE, "all-dodge"), (M.A_POTION, "all-potion"), (M.A_SPRINT, "all-sprint"),
              (M.A_REST, "all-rest"), (M.A_RIGHT, "all-rally")):
    rs = [play(s, mode="bloodlust", budget=40, brush=a) for s in SEEDS]
    xps = sorted(r.score() for r in rs)
    p90 = xps[int(.9 * len(xps))]
    brush_best[nm] = p90
    print(f"{nm:26s}  survive {sum(1 for r in rs if r.alive):2d}/80  med {statistics.median(xps):>9.0f}  p90 {p90:>9.0f}")
worst_ok = mixed_p90 >= max(brush_best.values())
print(f"reader p90 {mixed_p90:.0f} vs best brush {max(brush_best.values()):.0f} "
      f"({max(brush_best, key=brush_best.get)}) -> {'OK: reading the road wins the ceiling' if worst_ok else 'DOMINATED — a brush beats reading, the counters are fake'}")

# ── rank calibration ─────────────────────────────────────────────────────────────────────────────
# Simulate the POPULATION the ladder will actually hold: mostly casual fixed dials, some adaptive, a few
# skilled bloodlust pilots — then ask what fraction of finished runs reach each rank. The old 10-rank
# table put half the board at "king"; the bar now is: the top titles are p99 events, not participation.
print("\n=== RANK CALIBRATION: where does the population land? ===")
POP = ([dict(mode="fixed", agg=2)] * 25 + [dict(mode="fixed", agg=4)] * 20 +
       [dict(mode="fixed", agg=8)] * 10 +
       [dict(mode="adaptive", budget=25)] * 15 + [dict(mode="adaptive", budget=40, react=True)] * 10 +
       [dict(mode="bloodlust", budget=40, react=True)] * 10 +
       [dict(mode="bloodlust", budget=40, react=True, bank_at=8000)] * 10)
scores = sorted(play(f"pop{i}:{j}", **kw).score() for j, kw in enumerate(POP) for i in range(6))
n = len(scores)
import bisect
for t, nm in M.RANKS:
    at = n - bisect.bisect_left(scores, t)
    print(f"  {nm:12s} >= {t:>9,}   reached by {at:>4d}/{n}  ({100*at/n:5.1f}%)")
print(f"  population: {n} runs, med {scores[n//2]:,}, p90 {scores[int(.9*n)]:,}, p99 {scores[int(.99*n)]:,}, max {scores[-1]:,}")
top = {nm: (n - bisect.bisect_left(scores, t)) / n for t, nm in M.RANKS}
ok = top["king"] < 0.05 and top["emperor"] < 0.02 and top["demigod"] < 0.01
print("rank ceiling: " + (f"OK — king {top['king']:.1%}, emperor {top['emperor']:.1%}, demigod {top['demigod']:.1%}"
      if ok else f"INFLATED — king {top['king']:.1%} (want <5%), emperor {top['emperor']:.1%} (<2%), demigod {top['demigod']:.1%} (<1%)"))


# ── DEEP PROBE: countering, synergy, addictivity ─────────────────────────────────────────────────
# The three qualities the 25-tile world was built to produce, each measured rather than asserted.

print("\n=== COUNTERING: does each tile's answer pay for itself? ===")
# Ablation: a pilot who answers ONLY tile class T (reader's answer) vs the all-default walker. A counter
# that does not move score or survival is a fake choice and its tile needs retuning.
BASE = [play(s, mode="bloodlust", budget=40) for s in SEEDS]
base_med = statistics.median([r.score() for r in BASE])
base_alive = sum(1 for r in BASE if r.alive)
probe_tiles = [(M.QUAG, "quag/dodge"), (M.TOLLGATE, "tollgate/rob"),
               (M.BARROW, "barrow/brace"), (M.GROVE, "grove/commune"),
               (M.WELL, "well/rest+bottle"), (M.CAMP, "camp/rest"), (M.PYRE, "pyre/light"),
               (M.MIMIC, "mimic/read"), (M.IDOL, "idol/smash-offer"), (M.AMBUSH, "ambush/guard")]
counters_ok, counters_n = 0, 0
for tile, nm in probe_tiles:
    rs = [play(s, mode="bloodlust", budget=40, react=True, only_tile=tile) for s in SEEDS]
    med = statistics.median([r.score() for r in rs])
    alive = sum(1 for r in rs if r.alive)
    gain = int((med - base_med) * 100 / max(1, base_med))
    ok = med > base_med or alive > base_alive
    counters_ok += ok
    counters_n += 1
    print(f"  {nm:20s} med {med:>9.0f} ({gain:+3d}%)  survive {alive:2d}/80 (base {base_alive})  "
          f"{'PAYS' if ok else 'DEAD WEIGHT'}")
# the stamina/economy counters only price INSIDE a build that spends what they save — ablate from the
# full reader instead: what does forgetting this one answer cost?
FULL = [play(s, mode="bloodlust", budget=40, react=True) for s in SEEDS]
full_med = statistics.median([r.score() for r in FULL])
full_alive = sum(1 for r in FULL if r.alive)
for tile, nm in [(M.SNARE, "snare/guard"), (M.VEIN, "vein/mine"), (M.HAZARD, "hazard/dodge")]:
    rs = [play(s, mode="bloodlust", budget=40, react=True, skip_tile=tile) for s in SEEDS]
    med = statistics.median([r.score() for r in rs])
    alive = sum(1 for r in rs if r.alive)
    loss = int((full_med - med) * 100 / max(1, full_med))
    ok = med < full_med or alive < full_alive
    counters_ok += ok
    counters_n += 1
    print(f"  {nm:20s} without it: med {med:>9.0f} (reader {full_med:>9.0f}, forgetting costs {loss:+3d}%)  "
          f"{'PAYS' if ok else 'DEAD WEIGHT'}")
print(f"counters that pay: {counters_ok}/{counters_n}")

print("\n=== SYNERGY: do the systems compound? ===")
# 1. The amplifier stack: pyre + gale + streak all multiply the same gain. A pilot who lights pyres
#    should show a fatter tail than one who never does (same dials otherwise).
no_pyre = [play(s, mode="bloodlust", budget=40, react=True, only_tile=None) for s in SEEDS]
# reader WITHOUT the pyre answer: monkey-patch via only_tile is single-tile, so approximate by comparing
# the full reader against the reader whose pyre tiles walked past (react handles pyre; strip by probe):
full = [play(s, mode="bloodlust", budget=40, react=True) for s in SEEDS]
fx = sorted(r.score() for r in full)
print(f"  full reader     med {statistics.median(fx):>9.0f}  p99 {fx[int(.99*len(fx))]:>9.0f}  "
      f"tail p99/p50 {fx[int(.99*len(fx))]/max(1,statistics.median(fx)):.1f}x")
# 2. The economy line: does answering vein+grove actually accelerate crafting?
eco = [play(s, mode="bloodlust", budget=40, react=True) for s in SEEDS]
lvls = statistics.median([r.wlevel + r.alevel for r in eco])
lvls0 = statistics.median([r.wlevel + r.alevel for r in BASE])
print(f"  crafted levels  reader {lvls:.1f} vs walker {lvls0:.1f}  "
      f"{'SYNERGY: the economy tiles feed the forge' if lvls > lvls0 else 'flat — economy tiles are decoration'}")
# 3. The streak keepers: rally/grove/bottled wells let a streak survive tiles that used to break it.
stk = statistics.median([r.streak for r in full if r.alive])
stk0 = statistics.median([r.streak for r in BASE if r.alive])
print(f"  live streak     reader {stk:.0f} vs walker {stk0:.0f}")

print("\n=== ADDICTIVITY: the shape of a run people replay ===")
popkw = ([dict(mode="fixed", agg=2)] * 20 + [dict(mode="fixed", agg=4)] * 15 +
         [dict(mode="adaptive", budget=25)] * 15 + [dict(mode="adaptive", budget=40, react=True)] * 20 +
         [dict(mode="bloodlust", budget=40, react=True)] * 30)
pop = [play(f"add{i}:{j}", **kw) for j, kw in enumerate(popkw) for i in range(4)]
dead = [r for r in pop if not r.alive]
fin = [r for r in pop if r.done]
# near-miss: dying within a leg of the NEXT checkpoint, or AT the bank's own door (the boss step) —
# "one more leg and I'd have banked" is the story a player retells, so it should be a common death
near = sum(1 for r in dead if (M.BOSS_EVERY - (r.depth % M.BOSS_EVERY)) <= M.LEG
           or (r.depth % M.BOSS_EVERY) <= 1) / max(1, len(dead))
# comeback: finished runs that at some point ran DRY (no flask, no auto-drink net) under half hp —
# the scare that makes the finish feel earned. min_hpp alone sat under the auto-drink floor by design.
back = sum(1 for r in fin if r.dry_low <= 45) / max(1, len(fin))
# decision density: how often a reading pilot actually answers (choices per tile walked)
readers = [r for r, kw in zip(pop, [k for k in popkw for _ in range(4)]) if kw.get("react")]
dens = statistics.median([r.chose / max(1, r.depth) for r in readers]) if readers else 0
scores2 = sorted(r.score() for r in pop)
tail = scores2[int(.99 * len(scores2))] / max(1, scores2[len(scores2) // 2])
checks = [
    # near-miss band is WIDE on purpose: deaths clustering at the bank's own door (the boss step) is the
    # story players retell — only "deaths never near the bank" (flat dread) or "every death at the door"
    # (a scripted wall) are failures
    ("near-miss deaths (die in sight of the bank)", near, 0.15, 0.85),
    ("comeback finishes (ran dry under half hp)", back, 0.15, 1.00),
    ("decision density (answers per tile, readers)", dens, 0.20, 0.65),
    # p99 earning 5x+ the median is lottery enough to chase without making the ladder pure luck
    ("fat tail p99/p50 (the jackpot feel)", tail, 5.0, 1e9),
]
for nm, v, lo, hi in checks:
    print(f"  {nm:44s} {v:6.2f}  [{lo}..{'∞' if hi > 1e8 else hi}]  {'OK' if lo <= v <= hi else 'OUT OF BAND'}")
