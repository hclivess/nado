"""
Which actions actually DO something on which tile — derived from the rules, never typed by hand.

Run: python3 tests/autogame_action_matrix.py            # print the matrix
     python3 tests/autogame_action_matrix.py --check    # fail if the emitted table is stale

I hand-wrote this table once and got it wrong in both directions: "Strike forge" was offered and does
nothing but burn 2 stamina, "take the right lane" was offered on shrines where it means something else
entirely, and Sprint was offered everywhere despite being byte-identical to Dodge at a higher price. A menu
that invites choices the rules discard is worse than a short menu.

So the table is COMPUTED. For every (tile class, action) pair this brute-forces many worlds, runs the
reference model twice — once with the action, once with plain Default — and asks whether any observable
field of the run ever differs. If nothing ever differs, the action is a no-op on that tile and must not be
offered.

The result is emitted into static/autogame-rules.js (ACTS_FOR) alongside the other generated constants, so
the client renders exactly what the rules can honour.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.games import autogame as A          # noqa: E402
from tests import autogame_model as M             # noqa: E402

# a tile class is decided by the `a` field; pick a representative value inside each class's band
CLASS_A = {}
_lo = 0
for _i, _cut in enumerate(A.TILE_CUTS):
    CLASS_A[_i] = _lo
    _lo = _cut
CLASS_A[len(A.TILE_CUTS)] = A.TILE_CUTS[-1]        # the last class runs to 99

# STAMINA IS DELIBERATELY EXCLUDED. Every action spends some, so including it makes literally every action
# "have an effect" on every tile — which is how "Strike forge" looked defensible. The question that matters
# is whether an action changes anything BESIDES its own cost; if it does not, choosing it is pure waste.
FIELDS = ("hp", "maxhp", "potions", "xp", "banked", "streak", "depth", "kills", "alive",
          "wlevel", "alevel", "pyre")
# Stamina is observed too — but ADJUSTED, not raw. The snare eats it, the well refills it and Rally
# grants it, so two actions on those tiles can differ in nothing else; yet raw stamina would make every
# action "effective" everywhere through its own price. observe() re-adds the cost of the action the model
# actually charged (ev["act"], post-degradation), so only EXTERNAL stamina effects remain visible.


def tile_word(a, b, c, scen=0):
    """Build a tile word that decodes to exactly (a, b, c) — the inverse of slice_tile."""
    return a + 100 * (b + 64 * (c + 64 * scen))


def roll_word(x, y, z):
    return x + 100 * (y + 64 * z)


def observe(tile, action, seedset):
    """Run the model once per world with `action` on `tile`; return the tuple of end states."""
    out = []
    for (b, c, x, y, z, hp, mx, stam, pot, stk, xp, mats, gear) in seedset:
        run = M.Run()
        run.hp, run.maxhp, run.stam, run.potions = hp, mx, stam, pot
        run.streak, run.xp = stk, xp
        run.mats = list(mats)
        run.gear = list(gear)
        # BOSS only occurs on the chapter marks, so place the run there when probing it
        if tile == A.BOSS:
            run.depth = A.BOSS_EVERY
        a = CLASS_A[tile] if tile != A.BOSS else CLASS_A[A.ROAD]
        # manual-only: the action IS the per-tile answer, exactly as commit() delivers it
        ev = M.step(run, tile_word(a, b, c), roll_word(x, y, z), agg=4, action=action)
        adj_stam = run.stam + A.COST[ev.get("act", 0)]     # cancel the action's own price (see FIELDS)
        out.append(tuple(getattr(run, f) for f in FIELDS)
                   + (adj_stam, tuple(run.gear), tuple(run.mats)))
    return tuple(out)


def worlds():
    """A spread of monster stats, rolls and player states.

    SURVIVABLE states are essential, not decoration. Probing only a naked runner made every boss lethal in
    every sample, so nothing could differentiate one action from another and the boss row came back missing
    reactions that plainly matter. If the probe always dies, it measures nothing."""
    naked = [0] * A.NSLOT
    kitted = [M.pack_item(6, 5, 0)] * A.NSLOT          # enough armour to live through a boss exchange
    ws = []
    for b in (0, 5, 17, 31, 47, 63):
        for c in (0, 9, 23, 40, 61):
            for (x, y, z) in ((0, 0, 0), (13, 7, 3), (55, 33, 21), (91, 60, 62)):
                # (hp, maxhp, …) — a WOUNDED but survivable state is what exposes healing reactions. At
                # full hp a heal caps to nothing; dead, everything looks the same. Without one of these the
                # boss row came back with no Rally, which is simply false.
                # (hp, maxhp, stam, potions, STREAK, XP, gear). Streak and renown must be non-zero in some
                # probes or two actions can look identical purely because the thing that separates them is
                # zero: Rally preserves a greed streak and Rest breaks it, which is unobservable when there
                # is no streak, and Rest's renown cost is unobservable at zero renown.
                for (hp, mx, stam, pot, stk, xp, gear) in (
                        (100, 100, 12, 3, 0, 0, naked), (30, 100, 2, 1, 0, 0, naked),
                        (12, 100, 12, 0, 5, 400, naked), (400, 400, 12, 3, 0, 0, kitted),
                        (150, 400, 12, 3, 9, 5000, kitted), (60, 400, 4, 2, 3, 800, kitted)):
                    ws.append((b, c, x, y, z, hp, mx, stam, pot, stk, xp, (12, 6, 4), list(gear)))
    return ws


def matrix():
    """Per tile: the actions that change something other than their own stamina cost, minus any that are
    STRICTLY DOMINATED — identical in effect to a cheaper action. Sprint is the standing example: it does
    exactly what Dodge does and charges an extra stamina, so no state of the game makes it correct."""
    ws = worlds()
    out, notes = {}, []
    for tile in range(A.NTILE):
        base = observe(tile, A.A_DEFAULT, ws)
        effects = {}
        for action in range(1, 8):
            eff = observe(tile, action, ws)
            if eff != base:
                effects[action] = eff
        usable = []
        for action, eff in sorted(effects.items()):
            cheaper = [o for o, e in effects.items()
                       if e == eff and A.COST[o] < A.COST[action]]
            if cheaper:
                notes.append(f"{TILE_NAMES[tile]}: {ACT_NAMES[action]} is dominated by "
                             f"{ACT_NAMES[cheaper[0]]} (same effect, {A.COST[action]} vs "
                             f"{A.COST[cheaper[0]]} stamina)")
                continue
            usable.append(action)
        out[tile] = [0] + usable
    matrix.notes = notes
    return out


TILE_NAMES = ["road", "monster", "horde", "elite", "ambush", "mimic", "hazard", "snare", "quag", "gale",
              "tollgate", "cache", "barrow", "armory", "vein", "grove", "shrine", "well", "camp", "idol",
              "pyre", "forge", "fork", "relic", "boss"]
ACT_NAMES = ["default", "strike", "guard", "dodge", "potion", "sprint", "rest", "right/rally"]


def emit(mtx):
    rows = ", ".join("[%d]: [%s]" % (t, ", ".join(str(a) for a in acts)) for t, acts in sorted(mtx.items()))
    return ("// which actions actually change the outcome on each tile class — DERIVED by\n"
            "// tests/autogame_action_matrix.py from the rules themselves, never hand-written\n"
            "export const ACTS_FOR = {%s};\n" % rows)


def main():
    mtx = matrix()
    print(f"{'tile':9s} usable actions")
    for t, acts in sorted(mtx.items()):
        print(f"  {TILE_NAMES[t]:9s} {', '.join(ACT_NAMES[a] for a in acts)}")

    for n in getattr(matrix, "notes", [])[:8]:
        print("  note:", n)
    dead = [ACT_NAMES[a] for a in range(1, 8) if not any(a in acts for acts in mtx.values())]
    if dead:
        print(f"\nactions usable on NO tile at all (dead weight in the rules): {', '.join(dead)}")

    rules = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "static", "autogame-rules.js")
    block = emit(mtx)
    cur = open(rules).read()
    if "--check" in sys.argv:
        ok = block.strip() in cur
        print("\n" + ("PASS  the emitted ACTS_FOR matches the rules"
                      if ok else "FAIL  static/autogame-rules.js is stale — re-run without --check"))
        return 0 if ok else 1
    if block.strip() not in cur:
        marker = "// which actions actually change the outcome"
        if marker in cur:
            cur = cur[:cur.index(marker)] + block
        else:
            cur = cur.rstrip() + "\n\n" + block
        open(rules, "w").write(cur)
        print("\nwrote ACTS_FOR into static/autogame-rules.js")
    else:
        print("\nstatic/autogame-rules.js already matches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
