"""
ECOLOGY in Land ("trees should have a process of reproduction as well as the grass, etc.", operator 2026-11-06), driven
through the world server's own methods (scripts/land_server.py) against the REAL planet (scripts/land_terrain.mjs, i.e.
static/land-world.js):

  1. leaves sometimes give a sapling (the breaking table's bonus), so a player reaches one from bare hands;
  2. a sapling is planted only in earth or grass; pulled up before its time, it never grows;
  3. after GROW_S a planted sapling becomes a young tree of its climate — a trunk from its own cell up and a crown — written
     only into cells that are still air (a build in the way stays), only on its own plot, and it stays (no regrow
     timer, even in the commons); the growth timers survive a restart;
  4. on an OWNED plot, bare earth with open air above turns to grass when grass grows beside it — not on someone else's
     unowned commons (which grows back whole anyway), and never earth that is covered;
  5. the page draws a planted sapling as its model, and places it as a cell (like earth), and it is named in 17 languages.

Run: python3 tests/test_saplings_grow_into_trees_and_grass_spreads_onto_bare_earth.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-ecology-")
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

js = """
const W = await import(%s);
const B = W.B, sp = W.plotCoords(W.plotId(0, W.SPAWN_PLOT_ROW, W.SPAWN_PLOT_COL)), f = sp.face;
const tb = (u, v, h) => W.terrainBlock(f, u, v, h);
// two meadow spots in the middle of plots (a tree reaches 2 columns), no tree nearby, flat enough
const spots = [];
for (let pr = 0; pr < 40 && spots.length < 3; pr++) {
  const q = W.plotCoords(W.plotId(0, W.SPAWN_PLOT_ROW + pr, W.SPAWN_PLOT_COL)), u = q.u0 + 8, v = q.v0 + 8, c = W.column(f, u, v);
  let ok = tb(u, v, c.top) === B.grass && tb(u, v, c.top - 1) === B.dirt;
  for (let du = -3; du <= 3 && ok; du++) for (let dv = -3; dv <= 3 && ok; dv++) {
    const cc = W.column(f, u + du, v + dv);
    if (W.treeAt(f, u + du, v + dv, cc) || Math.abs(cc.top - c.top) > 1 || tb(u + du, v + dv, cc.top) !== B.grass) ok = false;
  }
  if (ok) spots.push([f, u, v, c.top]);
}
const t0 = spots[0] && W.saplingTree(f, spots[0][1], spots[0][2], W.column(f, spots[0][1], spots[0][2]));
console.log(JSON.stringify({ spots, tree: t0, B: { sapling: B.sapling, grass: B.grass, dirt: B.dirt, log: B.log, birchlog: B.birchlog, leaves: B.leaves, needles: B.needles, stone: B.stone, air: B.air, planks: B.planks } }));
""" % json.dumps(os.path.join(ROOT, "static", "land-world.js"))
P = json.loads(subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=900).stdout)
B = P["B"]
check("the planet offers clear meadow spots to plant in", len(P["spots"]) >= 3, P["spots"])
R = json.load(open(os.path.join(ROOT, "static", "land-recipes.json")))
check("leaves sometimes give a sapling (the breaking table's bonus): a player reaches one from bare hands",
      R["breaking"][str(B["leaves"])].get("bonus", [None])[0] == "sapling" and not R["breaking"][str(B["leaves"])].get("needs")
      and R["items"]["sapling"]["places"] == B["sapling"] and R["breaking"][str(B["sapling"])]["yields"][0][0] == "sapling")
WHO = "ndoECOL" + "E" * 41


async def main():
    data = os.path.join(os.environ["HOME"], "land")
    w = S.World(data, "http://127.0.0.1:1", "")
    await w.start_oracle()
    w.work = lambda who, s: True
    w.take = lambda who, n: True
    pl = w.player(WHO)
    pl["tools"] += ["shovel", "axe"]
    pl["items"]["sapling"] = 5
    pl["items"]["planks"] = 5

    (f, u, v, top), (f2, u2, v2, top2), (f3, u3, v3, top3) = P["spots"][:3]
    # 2. planted only in soil
    _, ref, _ = await w.apply(WHO, [[f, u, v, top + 2, B["sapling"]]])
    check("a sapling is refused where there is no earth or grass under it", ref and "earth or grass" in ref[0][1], ref)
    _, ref, _ = await w.apply(WHO, [[f, u, v, top + 1, B["sapling"]]])
    p = S.plot_of(f, u, v)
    k = (u - (p % S.FACE_N) * S.PLOT, v - ((p // S.FACE_N) % S.FACE_N) * S.PLOT, top + 1)
    check("…and planted on grass, with its growth timer started", not ref and w.plots[p]["edits"][k] == B["sapling"] and k in w.plots[p]["grow"], ref)
    # a build in the way of its crown: a plank block one column over, at the crown's height
    t = P["tree"]
    crown_h = top + t["height"]
    await w.apply(WHO, [[f, u + 1, v, crown_h, B["planks"]]])
    # pulled up before its time: never grows
    _, ref2, _ = await w.apply(WHO, [[f2, u2, v2, top2 + 1, B["sapling"]]])
    planted2 = not ref2
    await w.apply(WHO, [[f2, u2, v2, top2 + 1, 0]])
    # 3. growth
    early = await w.grow(w.plots[p]["grow"][k] - 1)
    check("before its time a sapling stays a sapling", not early, early)
    # the timers survive a restart
    w.flush()
    w2 = S.World(data, "http://127.0.0.1:1", "")
    check("the growth timers survive a restart", w2.plots[p].get("grow") == w.plots[p]["grow"])
    grown = await w.grow(w.plots[p]["grow"][k] + 1)
    cells = [c for cs in grown.values() for c in cs]
    trunk = sorted(c[3] for c in cells if c[1] == u and c[2] == v and c[4] in (B["log"], B["birchlog"]))
    crown = [c for c in cells if c[4] in (B["leaves"], B["needles"])]
    check(f"after its time it is a young {t['kind']}: a trunk from its own cell up and a crown",
          trunk and trunk[0] == top + 1 and len(trunk) == t["height"] and len(crown) > 4, (trunk, len(crown)))
    check("…written only on its own plot", all(S.plot_of(c[0], c[1], c[2]) == p for c in cells))
    pk = (u + 1 - (p % S.FACE_N) * S.PLOT, v - ((p // S.FACE_N) % S.FACE_N) * S.PLOT, crown_h)
    check("…never over a build: the plank block in its crown stays", w.plots[p]["edits"][pk] == B["planks"])
    check("…and it stays: no regrow timer on the grown cells, even in the commons",
          not any((c[1] - (p % S.FACE_N) * S.PLOT, c[2] - ((p // S.FACE_N) % S.FACE_N) * S.PLOT, c[3]) in w.plots[p].get("exp", {}) for c in cells))
    p2 = S.plot_of(f2, u2, v2)
    check("a sapling pulled up before its time never grows", planted2 and not any(c[1] == u2 and c[2] == v2 and c[3] > top2 for c in [x for cs in grown.values() for x in cs])
          and not (w.plots.get(p2) or {}).get("grow"), (ref2, p2 in w.plots))

    # 4. grass spreads on an owned plot
    p3 = S.plot_of(f3, u3, v3)
    owned = {p3}
    async def holder(q):
        return "owner" if q in owned else None
    async def may_build(q, a):
        return q in owned                                        # the test's player builds on the owned plot
    w.holder, w.may_build = holder, may_build
    await w.apply(WHO, [[f3, u3, v3, top3, 0]])                 # dig the turf: bare earth one down, air above it
    await w.apply(WHO, [[f, u + 3, v + 3, top, 0]])              # the same on the commons plot
    green = None
    for i in range(40):
        out = await w.spread(1_900_000_000 + i * S.SPREAD_S)
        b = (await w.blocks_at([[f3, u3, v3, top3 - 1]]))[(f3, u3, v3, top3 - 1)]
        if b == B["grass"]:
            green = i; break
    check(f"on an owned plot, bare earth beside grass turns to grass (after {green} ticks)", green is not None, green)
    bc = (await w.blocks_at([[f, u + 3, v + 3, top - 1]]))[(f, u + 3, v + 3, top - 1)]
    check("…not on the unowned commons (which grows back whole instead)", bc == B["dirt"], bc)
    # covered earth stays earth: a plank over a dug cell's earth
    await w.apply(WHO, [[f3, u3 + 2, v3, top3, 0], [f3, u3 + 2, v3, top3, B["planks"]]])
    for i in range(40, 80):
        await w.spread(1_900_000_000 + i * S.SPREAD_S)
    bcov = (await w.blocks_at([[f3, u3 + 2, v3, top3 - 1]]))[(f3, u3 + 2, v3, top3 - 1)]
    check("…and never earth that is covered", bcov == B["dirt"], bcov)
    w.oracle.kill(); await w.oracle.wait()


asyncio.run(main())

# 5. the page
js_page = open(os.path.join(ROOT, "static", "land.js"), encoding="utf-8").read()
check("the page places a sapling as a cell, like earth", '"sapling"]);   // these fill the ground' in js_page)
r = subprocess.run(["node", "--input-type=module", "-e", """
const W = await import(%s), M = await import(%s);
const sp = W.plotCoords(W.plotId(0, W.SPAWN_PLOT_ROW, W.SPAWN_PLOT_COL)), u = sp.u0 + 8, v = sp.v0 + 8, c = W.column(0, u, v), h = c.top + 1;
const n = (e) => { const r = M.meshChunk(0, Math.floor(u / 16), Math.floor(v / 16), Math.floor(h / 16), e, null, 0); return ((r.bark ? r.bark.pos.length : 0) + (r.foliage ? r.foliage.pos.length : 0)) / 3; };
console.log(JSON.stringify([n(null), n(new Map([[`0:${u}:${v}:${h}`, W.B.sapling]]))]));
""" % (json.dumps(os.path.join(ROOT, "static", "land-world.js")), json.dumps(os.path.join(ROOT, "static", "land-mesher.js")))],
    capture_output=True, text=True, timeout=300)
a, b = json.loads(r.stdout.strip().splitlines()[-1])
check(f"a planted sapling is drawn as its model (stem and leaves: {b - a} vertices)", b > a + 20, (a, b, r.stderr[-300:]))
tr = json.load(open(os.path.join(ROOT, "static", "i18n_games", "land.json"), encoding="utf-8"))
check("a sapling is named in 17 languages", len(tr) == 17 and all(l.get("land.i.sapling") for l in tr.values()))
srv = int([l for l in open(os.path.join(ROOT, "scripts", "land_server.py")) if l.startswith("N_BLOCKS = ")][0].split()[2])
nb = int(subprocess.run(["node", "--input-type=module", "-e", "const W = await import(%s); console.log(W.BLOCKS.length)" % json.dumps(os.path.join(ROOT, "static", "land-world.js"))],
                        capture_output=True, text=True, timeout=120).stdout.strip())
check("the world server knows every block", srv == nb, (srv, nb))
_report.done()
