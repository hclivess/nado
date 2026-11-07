"""
Forests spread and bare earth greens over on their own (#110, "trees should have a process of reproduction as well as
the grass", operator 2026-11-06), driven through the world server's own methods against the REAL planet:

  1. the planet's trees on a plot are read from the generator (land_terrain.mjs trees) and a felled one stops counting;
  2. on an OWNED plot, over enough ticks, its trees drop saplings — each on open grass (grass under it, air over it),
     2-3 m from a trunk, on the plot itself, never within 2 m of another trunk or sapling, never past TREE_CAP — and each
     sapling has its growth timer, so it becomes a tree like a planted one;
  3. never on an unowned plot (the commons grows back whole instead), and the same tick gives the same answer after a
     restart (no RNG);
  4. bare earth with open air above greens over on an owned plot even with no grass beside it — slowly.

Run: python3 tests/test_forests_seed_themselves_and_bare_earth_greens_over_on_owned_plots.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-forests-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
import _harness
_report = _harness.Report()
check = _report.check

OWNED = 40930676                                        # a first-wave plot with three trees (and bushes, which are none)
WILD = 40930677
B = json.loads(subprocess.run(["node", "--input-type=module", "-e",
    "const W = await import(%s); console.log(JSON.stringify({log: W.B.log, birch: W.B.birchlog, sapling: W.B.sapling, grass: W.B.grass, dirt: W.B.dirt}))"
    % json.dumps(os.path.join(ROOT, "static", "land-world.js"))], capture_output=True, text=True, timeout=120).stdout)


async def main():
    data = os.path.join(os.environ["HOME"], "land")
    w = S.World(data, "http://127.0.0.1:1", "")
    await w.start_oracle()
    owned = {OWNED}

    async def holder(q):
        return "ndoOWNER" if q in owned else None
    w.holder = holder
    w.titles = {OWNED: "1", WILD: "2"}
    w.refresh_titles = lambda *a, **k: asyncio.sleep(0)

    roots = await w.tree_roots(OWNED)
    check(f"the plot's trees come from the planet ({len(roots)} standing)", len(roots) >= 3, roots)
    f, row, col = S.plot_coords(OWNED)
    u, v, t = roots[0]
    w.plot(OWNED)["edits"][(u - col * S.PLOT, v - row * S.PLOT, t + 1)] = 0       # fell one at its foot
    check("…and a felled tree stops counting", len(await w.tree_roots(OWNED)) == len(roots) - 1)
    w.plot(OWNED)["edits"].pop((u - col * S.PLOT, v - row * S.PLOT, t + 1))

    seeded = []
    for i in range(400):
        out = await w.seed(1_900_000_000 + i * S.SEED_S)
        seeded += out.get(OWNED, [])
        check_wild = out.get(WILD)
        if check_wild:
            break
    check(f"over enough ticks an owned plot's trees drop saplings ({len(seeded)})", len(seeded) >= 1, seeded)
    check("…never on an unowned plot", WILD not in w.plots or not any(b == S.SAPLING for b in w.plots[WILD]["edits"].values()))
    rec = w.plots[OWNED]
    standing = await w.tree_roots(OWNED)
    saps = [(col * S.PLOT + x, row * S.PLOT + z, y) for (x, z, y), b in rec["edits"].items() if b == S.SAPLING]
    check("…never past TREE_CAP trees on the plot", len(standing) + len(saps) <= S.TREE_CAP, (len(standing), len(saps)))
    ok_ground = True
    for fu, fv, fh, b in [c[1:] for c in seeded]:
        at = await w.blocks_at([[f, fu, fv, fh - 1], [f, fu, fv, fh + 1]])
        ok_ground &= at[(f, fu, fv, fh - 1)] == S.GRASS and at[(f, fu, fv, fh + 1)] == 0 and S.plot_of(f, fu, fv) == OWNED
    check("…each on open grass on the plot itself", ok_ground)
    trunks = [(a, b) for a, b, _ in standing]
    check("…2-3 m from a trunk, never within 2 m of another trunk or sapling",
          all(any(2 <= max(abs(a - su), abs(b - sv)) <= 3 for a, b in trunks) for su, sv, _ in saps)
          and all(max(abs(a - su), abs(b - sv)) >= 2 for a, b in trunks for su, sv, _ in saps)
          and all(max(abs(a[0] - b[0]), abs(a[1] - b[1])) >= 2 for i, a in enumerate(saps) for b in saps[i + 1:]), (trunks, saps))
    check("…and each has its growth timer, so it grows like a planted one",
          all((su - col * S.PLOT, sv - row * S.PLOT, sh) in rec["grow"] for su, sv, sh in saps))

    # the same tick, the same answer, on a fresh world: deterministic
    w2 = S.World(os.path.join(os.environ["HOME"], "land2"), "http://127.0.0.1:1", "")
    w2.oracle, w2.oracle_lock = w.oracle, w.oracle_lock
    w2.holder, w2.titles, w2.refresh_titles = holder, {OWNED: "1"}, w.refresh_titles
    a = []
    for i in range(400):
        a += (await w2.seed(1_900_000_000 + i * S.SEED_S)).get(OWNED, [])
    check("the same ticks seed the same cells on another run (no RNG)", a == seeded, (a[:3], seeded[:3]))

    # 4. lone greening: a dug cell far from any grass (a 5 x 5 pit's centre, one down) greens over in time
    async def grass_top(cu, cv):
        hs = list(range(60, 250))
        at = await w.blocks_at([[f, cu, cv, h] for h in hs])
        return max((h for h in hs if at[(f, cu, cv, h)] == S.GRASS), default=None)
    spot = None
    for ox, oz in ((8, 8), (4, 12), (12, 4), (4, 4), (12, 12), (8, 4), (4, 8)):
        gu, gv = col * S.PLOT + ox, row * S.PLOT + oz
        tops = [await grass_top(gu + dx, gv + dz) for dx in range(-3, 4) for dz in range(-3, 4)]
        if None not in tops and max(tops) - min(tops) <= 1 and not any(max(abs(a - gu), abs(b - gv)) <= 4 for a, b, _ in saps):
            spot, top = (gu, gv), await grass_top(gu, gv)
            break
    check("a flat open spot on the plot to dig", spot is not None)
    w.work = lambda who, s: True
    pl = w.player("ndoOWNER"); pl["tools"] += ["shovel"]

    async def may_build(q, a):
        return True
    w.may_build = may_build
    pit = [[f, gu + dx, gv + dz, top, 0] for dx in range(-2, 3) for dz in range(-2, 3)]
    pit += [[f, gu + dx, gv + dz, top - 1, 0] for dx in range(-2, 3) for dz in range(-2, 3) if (dx, dz) != (0, 0)]
    w.take = lambda who, n: True
    _, ref, _ = await w.apply("ndoOWNER", pit)
    check("the pit is dug", not ref, ref[:3])
    at = await w.blocks_at([[f, gu, gv, top - 1]] + [[f, gu + dx, gv + dz, top - 1 + dy] for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)) for dy in (-1, 0, 1)])
    check("a cell with no grass beside it is set up: earth, open air, nothing green around",
          at[(f, gu, gv, top - 1)] == S.DIRT and S.GRASS not in [b for k, b in at.items() if k != (f, gu, gv, top - 1)], at)
    green = None
    for i in range(400):
        await w.spread(1_900_000_000 + i * S.SPREAD_S)
        if (await w.blocks_at([[f, gu, gv, top - 1]]))[(f, gu, gv, top - 1)] == S.GRASS:
            green = i; break
    check(f"…and greens over on its own, slowly (after {green} ticks)", green is not None and green >= 1, green)
    w.oracle.kill(); await w.oracle.wait()


asyncio.run(main())
srv = open(os.path.join(ROOT, "scripts", "land_server.py"), encoding="utf-8").read()
check("the world server seeds forests every SEED_S", "seeded = await world.seed()" in srv and "n % (SEED_S // 10) == 0" in srv)
_report.done()
