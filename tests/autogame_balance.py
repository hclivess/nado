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
    """The heaviest per-foe swing waiting in this leg — the number the pull has to be priced against."""
    w = 0
    for (t, b, i) in leg:
        tt = M.ELITE if t == M.FORK else t
        if tt not in (M.MONSTER, M.ELITE, M.BOSS):
            continue
        ml = M.monster_level(tt, i)
        fam = b % 3
        c0, c1 = M.FAM_ATK[fam]
        each = c0 + c1 * ml + (b // 3) % 4
        each = each * M.STANCES[run.stance][0] // 4
        each = each * 110 // 100
        w = max(w, each)
    return w


def choose_agg_bl(run, leg, budget_pct):
    """Bloodlust-aware: the multiplier is live while you are hurt, so lean IN as hp falls — until the
    swing could actually kill, at which point survival wins."""
    sw = worst_swing(leg, run)
    if sw == 0:
        return M.AGG_MAX
    absorb = M.armor_pts(run)
    lean = 100 + 2 * (100 - run.hp * 100 // run.maxhp)      # up to 3x the budget while bloodied
    budget = run.hp * budget_pct * lean // 10000 + absorb
    budget = min(budget, run.hp * 70 // 100 + absorb)        # never price a swing that can kill outright
    return max(1, min(M.AGG_MAX, budget // sw))


def choose_agg(run, leg, budget_pct):
    """Spend at most budget_pct of current hp on the worst fight in the leg. This is the pilot a decent
    player is: look at the road, price the biggest swing, pull as much as you can pay for."""
    sw = worst_swing(leg, run)
    if sw == 0:
        return M.AGG_MAX
    absorb = M.armor_pts(run)
    budget = run.hp * budget_pct // 100 + absorb
    n = budget // sw
    return max(1, min(M.AGG_MAX, n))


def play(seed, mode, agg=4, healpct=35, stance=0, focus=50, budget=40, react=False):
    r = M.Run(stance=stance, healpct=healpct, focus=focus)
    leg, ag = None, agg
    for i in range(M.CHAPTER):
        if i % M.LEG == 0:
            leg = peek_leg(seed, i)
            if mode == "adaptive":
                ag = choose_agg(r, leg, budget)
            elif mode == "bloodlust":
                ag = choose_agg_bl(r, leg, budget)
        tw, rw = words(seed, i)
        act = M.A_DEFAULT
        if react:
            a, b, c, d = M.slice_tile(tw)
            t = M.tile_of(a, r.depth)
            if t in (M.MONSTER, M.ELITE, M.BOSS):
                if r.hp * 100 < r.maxhp * 30 and r.stam >= 1:
                    act = M.A_GUARD
                elif r.hp * 100 > r.maxhp * 75 and r.stam >= 2:
                    act = M.A_STRIKE
            elif t == M.FORK and r.hp * 100 > r.maxhp * 55:
                act = M.A_RIGHT
        M.step(r, tw, rw, act, ag)
        if not r.alive or r.done:
            break
    return r


SEEDS = [f"s{i}" for i in range(80)]


def sweep(label, **kw):
    rs = [play(s, **kw) for s in SEEDS]
    alive = sum(1 for r in rs if r.alive)
    xps = sorted(r.xp for r in rs)
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

print("\n=== bloodlust-aware pilot (lean in while hurt) ===")
for b in (25, 40, 60, 80):
    sweep(f"bloodlust budget={b}%", mode="bloodlust", budget=b)
for b in (40, 60):
    sweep(f"bloodlust {b}% + reactions", mode="bloodlust", budget=b, react=True)

print(f"\nbest fixed = {best_fixed:.0f}")
