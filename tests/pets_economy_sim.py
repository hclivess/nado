"""Pets economy simulation — does Homestead inflate, and where?

The question this answers is not "are the numbers pretty" but "which quantities RUN AWAY". A pet economy
has three separate ledgers and they fail differently:

  NADO      — the real currency. Only mining mints it; pets only ever BURN it (mint/feed/train/build/
              upgrade/reroll/fuse). The danger is not minting, it is a SINK BEING DESTROYED: farmed fodder
              replaces the food burn, so a mature player stops paying upkeep forever.
  RESOURCES — produced forever by staffed bases. Danger: sinks that are FINITE (upgrades stop at level 5),
              after which the resource piles up with nothing to spend it on and the loop dead-ends.
  ITEMS     — dropped forever, but demand is bounded (4 slots x pets). Danger: everything is worthless and
              the chase ends — the Diablo 3 failure.

So the sim tracks stocks and flows day by day for a population that GROWS its base over time (players build,
upgrade, buy better pets), and reports whether each ledger converges or diverges. Run:

    python3 tests/pets_economy_sim.py            # current live parameters
    python3 tests/pets_economy_sim.py --sweep    # compare parameter sets
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.games import pets as P

NADO = 10 ** 10
DAY_BLOCKS = 14400            # 6s blocks
FOOD_NADO_PER_PET_DAY = 0.1   # what a pet costs to feed with BOUGHT food (average appetite)


class Params:
    """Everything the sim can vary. Defaults read the LIVE contract, so the sim can never drift from it."""
    def __init__(self, **kw):
        self.rate_div = P.RATE_DIV
        self.rarity_rate = P.RARITY_RATE
        self.fodder_blocks = P.FODDER_BLOCKS
        self.accrue_cap = P.ACCRUE_CAP
        self.build_fee = P.BUILD_FEE / NADO
        self.max_level = P.MAX_LEVEL
        self.drop_one_in = P.DROP_ONE_IN
        self.upg_timber, self.upg_stone, self.upg_ore = P.UPG_TIMBER, P.UPG_STONE, P.UPG_ORE
        self.reroll_timber, self.reroll_stone, self.reroll_ore = P.REROLL_TIMBER, P.REROLL_STONE, P.REROLL_ORE
        self.reroll_essence = P.REROLL_ESSENCE
        self.scrap_essence = P.SCRAP_ESSENCE
        self.reroll_cost = None      # optional override: (timber, stone, ore, essence) per rarity
        self.fuse_ore = P.FUSE_ORE
        self.fuse_timber, self.fuse_stone, self.fuse_essence = P.FUSE_TIMBER, P.FUSE_STONE, P.FUSE_ESSENCE
        self.fuse_max_tier = P.FUSE_MAX_TIER
        self.reroll_fee = P.REROLL_FEE / NADO    # NADO burned per reroll
        self.fuse_fee = P.FUSE_FEE / NADO        # NADO burned per fuse
        self.__dict__.update(kw)


def base_rate(p, level, stat, rarity):
    """Units per block — mirrors _accrue exactly (rarity ADDITIVE, then x level)."""
    return level * (10 + stat + p.rarity_rate * (rarity - 1))


class Player:
    """One player's whole state. Behaviour is deliberately GREEDY — everyone upgrades as soon as they can
    afford it and collects every base daily — because the failure modes only show up at the ceiling."""
    def __init__(self, p, pets, bases, stat, rarity):
        self.p = p
        self.pets = pets                      # pets owned (each eats every day)
        # kind is fixed AT CONSTRUCTION — deriving it from list position inside the loop made every base
        # look like base 0 (identical lists compare equal), so all output landed in fodder and nothing could
        # ever be upgraded. Bases are spread round-robin across the five trades.
        self.bases = [{"lvl": 1, "stat": stat, "rar": rarity, "kind": i % 5} for i in range(bases)]
        self.res = [0.0] * 5                  # fodder, timber, stone, ore, essence
        self.items = 0                        # items held (bag + worn)
        self.burned = 0.0                     # NADO this player has destroyed
        self.food_paid = 0.0                  # NADO spent on BOUGHT food
        self.collects = 0

    def day(self):
        p = self.p
        # ---- production: one collect per base per day, capped by ACCRUE_CAP
        blocks = min(DAY_BLOCKS, p.accrue_cap)
        for b in self.bases:
            units = blocks * base_rate(p, b["lvl"], b["stat"], b["rar"]) // p.rate_div
            self.res[b["kind"]] += units
            self.collects += 1
            if p.drop_one_in and (self.collects % p.drop_one_in == 0):
                self.items += 1

        # ---- feeding: fodder first (free), NADO for whatever it cannot cover
        need_blocks = self.pets * DAY_BLOCKS
        from_fodder = min(self.res[0] * p.fodder_blocks, need_blocks)
        self.res[0] -= from_fodder / p.fodder_blocks
        shortfall_pets = (need_blocks - from_fodder) / DAY_BLOCKS
        cost = shortfall_pets * FOOD_NADO_PER_PET_DAY
        self.food_paid += cost
        self.burned += cost

        # ---- upgrades: greedily push every base to the cap as materials allow
        for b in self.bases:
            lvl = b["lvl"]
            if lvl >= p.max_level:
                continue
            nl = lvl + 1
            t, s, o = p.upg_timber * nl, p.upg_stone * nl, (p.upg_ore * nl if nl >= 4 else 0)
            if self.res[1] >= t and self.res[2] >= s and self.res[3] >= o:
                self.res[1] -= t; self.res[2] -= s; self.res[3] -= o
                self.burned += p.build_fee * nl
                b["lvl"] = nl

        # ---- endgame loop: scrap what cannot be worn, fuse toward the cap, reroll for better rolls
        slots = self.pets * 4
        junk = max(0, self.items - slots)
        if junk:
            self.items -= junk
            self.res[4] += junk * p.scrap_essence          # scrapping yields essence
            # fusing consumes junk AND ore — the permanent ore sink
            per = p.fuse_max_tier
            fusible = min(junk // 2, int(self.res[1] // (p.fuse_timber * per)),
                          int(self.res[2] // (p.fuse_stone * per)), int(self.res[3] // (p.fuse_ore * per)),
                          int(self.res[4] // (p.fuse_essence * per)))
            self.res[1] -= fusible * p.fuse_timber * per
            self.res[2] -= fusible * p.fuse_stone * per
            self.res[3] -= fusible * p.fuse_ore * per
            self.res[4] -= fusible * p.fuse_essence * per
            self.burned += fusible * p.fuse_fee
        # reroll every worn item once a day if the materials are there (what an endgame player does)
        tier = 3
        rr = min(self.pets * 4,
                 int(self.res[4] // (p.reroll_essence * tier)),
                 int(self.res[1] // (p.reroll_timber * tier)),
                 int(self.res[2] // (p.reroll_stone * tier)),
                 int(self.res[3] // (p.reroll_ore * tier)))
        if rr > 0:
            self.res[4] -= rr * p.reroll_essence * tier
            self.res[1] -= rr * p.reroll_timber * tier
            self.res[2] -= rr * p.reroll_stone * tier
            self.res[3] -= rr * p.reroll_ore * tier
            self.burned += rr * p.reroll_fee


def simulate(p, days=365, pets=12, bases=5, stat=45, rarity=3, verbose=False):
    pl = Player(p, pets, bases, stat, rarity)
    pl.burned += bases * p.build_fee + pets * 1.0        # up-front: build the bases, buy the eggs
    marks = {}
    for d in range(1, days + 1):
        pl.day()
        if d in (1, 7, 30, 90, 180, 365):
            marks[d] = dict(res=[round(x) for x in pl.res], items=pl.items,
                            burned=round(pl.burned, 2), food=round(pl.food_paid, 2),
                            lvl=[b['lvl'] for b in pl.bases])
    return pl, marks


def report(name, p, **kw):
    pl, marks = simulate(p, **kw)
    days = kw.get("days", 365)
    print(f"\n=== {name} ===")
    print(f"  {'day':>4} {'fodder':>9} {'timber':>8} {'stone':>8} {'ore':>8} {'essence':>9} {'items':>6} {'levels':>12}")
    for d, m in marks.items():
        print(f"  {d:>4} {m['res'][0]:>9} {m['res'][1]:>8} {m['res'][2]:>8} {m['res'][3]:>8} "
              f"{m['res'][4]:>9} {m['items']:>6}   {''.join(str(x) for x in m['lvl'])}")
    burn_day = pl.burned / days
    print(f"  NADO burned over {days}d: {pl.burned:.1f}  ({burn_day:.3f}/day)   of which bought food: {pl.food_paid:.1f}")
    # what the SAME player would have burned on food with no Homestead at all
    baseline = kw.get("pets", 12) * FOOD_NADO_PER_PET_DAY * days + kw.get("pets", 12) * 1.0
    print(f"  same player WITHOUT Homestead would burn: {baseline:.1f}   -> Homestead is "
          f"{'a BIGGER' if pl.burned > baseline else 'a SMALLER'} sink ({pl.burned / baseline:.2f}x)")
    runaway = [n for n, v in zip(("fodder", "timber", "stone", "ore", "essence"), pl.res) if v > 50000]
    print(f"  runaway stocks (>50k held): {runaway or 'none'}   items held: {pl.items}")
    return pl


if __name__ == "__main__":
    base = Params()
    print(f"live parameters: RATE_DIV={base.rate_div} RARITY_RATE={base.rarity_rate} "
          f"FODDER_BLOCKS={base.fodder_blocks} DROP_ONE_IN={base.drop_one_in} "
          f"MAX_LEVEL={base.max_level}")
    report("AS SHIPPED — mid-size player (12 pets, 5 bases, rare workers)", base)
    report("AS SHIPPED — whale (60 pets, 20 bases, omega workers)", base,
           pets=60, bases=20, stat=66, rarity=6)
    report("AS SHIPPED — casual (3 pets, 1 base, common worker)", base,
           pets=3, bases=1, stat=30, rarity=1)

    if "--balance" in sys.argv:
        # Search for endgame costs that leave NO resource piling up. Every trade produces at the same rate,
        # so the four non-fodder sinks have to drain at the same rate too — except essence, which has a
        # SECOND faucet (scrapping), so it must be consumed proportionally harder. Guessing this by hand
        # over-corrected twice (first ore ran away, then essence, then the other three), which is exactly
        # the kind of question a simulation should answer instead.
        print("\n=== balancing the endgame sinks (day-365 stock held, whale) ===")
        print(f"  {'scrap':>5} {'rrE':>4} {'fzE':>4} | {'timber':>8} {'stone':>8} {'ore':>8} {'essence':>9} | {'worst':>9} {'ratio':>6}")
        best = None
        for scrap in (1, 2, 3):
            for rr_e in (10, 12, 14, 16):
                for fz_e in (20, 25, 30):
                    pr = Params(scrap_essence=scrap, reroll_essence=rr_e, fuse_essence=fz_e)
                    pl, _ = simulate(pr, pets=60, bases=20, stat=66, rarity=6)
                    worst = max(pl.res[1:])
                    ratio = pl.burned / (60 * FOOD_NADO_PER_PET_DAY * 365 + 60)
                    print(f"  {scrap:>5} {rr_e:>4} {fz_e:>4} | {pl.res[1]:>8.0f} {pl.res[2]:>8.0f} "
                          f"{pl.res[3]:>8.0f} {pl.res[4]:>9.0f} | {worst:>9.0f} {ratio:>6.2f}")
                    if ratio >= 1.0 and (best is None or worst < best[0]):
                        best = (worst, scrap, rr_e, fz_e, ratio)
        print(f"\n  BEST (no runaway, burn still >= 1.0x): scrap={best[1]} reroll_essence={best[2]} "
              f"fuse_essence={best[3]}  worst stock {best[0]:.0f}  ratio {best[4]:.2f}")

    if "--solve" in sys.argv:
        # Find the endgame NADO fee that makes Homestead at least as big a sink as the food burn it
        # displaces. The point is not the ratio itself but WHERE the burn lives: feeding stops costing NADO,
        # so the gear chase has to start costing it, or the expansion is a net removal of scarcity.
        print("\n=== solving for the reroll/fuse fee that keeps the burn whole ===")
        print(f"  {'fee':>6} {'casual':>9} {'mid':>9} {'whale':>9}   (Homestead burn / no-Homestead burn)")
        for fee in (0.0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3):
            row = []
            for pets, bases, stat, rar in ((3, 1, 30, 1), (12, 5, 45, 3), (60, 20, 66, 6)):
                pl, _ = simulate(Params(reroll_fee=fee, fuse_fee=fee * 2),
                                 pets=pets, bases=bases, stat=stat, rarity=rar)
                base_burn = pets * FOOD_NADO_PER_PET_DAY * 365 + pets * 1.0
                row.append(pl.burned / base_burn)
            print(f"  {fee:>6} " + " ".join(f"{r:>9.2f}" for r in row))

    if "--sweep" in sys.argv:
        for fee in (0.02, 0.05):
            report(f"WITH a {fee} NADO burn on reroll/fuse — whale",
                   Params(reroll_fee=fee, fuse_fee=fee * 2), pets=60, bases=20, stat=66, rarity=6)
        for drop in (12, 24):
            report(f"WITH DROP_ONE_IN={drop} — whale", Params(drop_one_in=drop),
                   pets=60, bases=20, stat=66, rarity=6)
