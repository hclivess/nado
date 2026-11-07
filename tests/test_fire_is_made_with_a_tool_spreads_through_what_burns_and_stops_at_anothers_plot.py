"""
FIRE in Land (#124 — "invent fire and tools to generate it, spreading dynamics, destruction mechanics etc", operator
2026-11-07), driven through the world server's own methods (scripts/land_server.py ignite / fire_tick) on the REAL planet:

  1. fire is made with a tool (a bow drill — sticks and cordage — or flint and steel), in an air cell beside something
     that burns, where the maker may build; never without a tool, never in a cell with nothing to burn beside it;
  2. it burns what it reaches — grass to bare earth, a tree's wood and leaves to air — and spreads through it;
  3. a built piece of a burning material (planks) burns down whole; one of stone brick does not;
  4. it NEVER crosses into a plot whose owner did not let its starter build there: nobody can burn another's plot;
  5. it dies when nothing is left to burn (no fire cell remains); earth put on it smothers it, a hand beats it out;
     a restart puts every fire out; what burnt on the commons grows back like any commons edit;
  6. the server's lists of what burns are the planet's (land-world BURNS / PIECE_BURNS), and the page draws a burning
     cell as flames that cast no shadow, binds X to make fire, and names the tools in 17 languages.

Run: python3 tests/test_fire_is_made_with_a_tool_spreads_through_what_burns_and_stops_at_anothers_plot.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-fire-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, random, subprocess, sys

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
const B = W.B, f = 0;
const tb = (u, v, h) => W.terrainBlock(f, u, v, h);
// a meadow plot (grass top, flat, no tree) and, beside it to the east, the plot that will be someone else's
let meadow = null, forest = null;
// (litter may lie on it: stones do not burn, sticks and flax burn with the grass)
for (let pr = 0; pr < 80 && !meadow; pr++) for (let pc = 0; pc < 12 && !meadow; pc++) {
  const q = W.plotCoords(W.plotId(0, W.SPAWN_PLOT_ROW + pr, W.SPAWN_PLOT_COL + 7 + pc)); let ok = true;
  for (let du = 0; du < 18 && ok; du++) for (let dv = 0; dv < 16 && ok; dv++) { const c = W.column(f, q.u0 + du, q.v0 + dv);
    if (tb(q.u0 + du, q.v0 + dv, c.top) !== B.grass || W.treeAt(f, q.u0 + du, q.v0 + dv, c)) ok = false; }
  if (ok) meadow = { u0: q.u0, v0: q.v0 };
}
// a broadleaf tree's trunk foot
for (let r = 0; r < 3000 && !forest; r++) { const u = 55040 + (r %% 60), v = 79900 + Math.floor(r / 60); const c = W.column(f, u, v), t = W.treeAt(f, u, v, c);
  if (t && t.kind === "broadleaf") forest = { u, v, top: c.top, height: t.height }; }
const col = (u, v) => W.column(f, u, v).top;
console.log(JSON.stringify({ meadow, forest, tops: meadow ? Array.from({ length: 20 }, (_, i) => Array.from({ length: 16 }, (_, j) => col(meadow.u0 + i, meadow.v0 + j))) : null,
  burns: [...W.BURNS.entries()], pieces: [...W.PIECE_BURNS], B: { grass: B.grass, dirt: B.dirt, log: B.log, leaves: B.leaves, fire: B.fire, planks: B.planks, stonebrick: B.stonebrick } }));
""" % json.dumps(os.path.join(ROOT, "static", "land-world.js"))
P = json.loads(subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=900).stdout)
B = P["B"]
check("the planet offers a clear meadow plot and a broadleaf tree to burn", P["meadow"] and P["forest"], (P["meadow"], P["forest"]))
check("the server's lists of what burns are the planet's",
      {int(k): int(v) for k, v in P["burns"]} == S.BURNS and set(P["pieces"]) == S.PIECE_BURNS and S.FIRE == B["fire"])

WHO, OTHER = "ndoFIRE" + "F" * 41, "ndoOTHR" + "O" * 41


async def main():
    random.seed(7)
    data = os.path.join(os.environ["HOME"], "land")
    w = S.World(data, "http://127.0.0.1:1", "")
    await w.start_oracle()
    w.work = lambda who, s: True
    w.take = lambda who, n: True
    u0, v0 = P["meadow"]["u0"], P["meadow"]["v0"]
    p_meadow = S.plot_of(0, u0, v0)
    p_east = S.plot_of(0, u0 + 16, v0)                      # someone else's plot, right beside
    owned = {p_east: OTHER}
    async def holder(q):
        return owned.get(q)
    async def may_build(q, a):
        return owned.get(q) in (None, a)
    w.holder, w.may_build = holder, may_build
    w.titles = {p_east: "x"}                                # the east plot is titled; the meadow is commons
    pl = w.player(WHO)
    top = lambda i, j: P["tops"][i][j]

    # 1
    _, err = await w.ignite(WHO, [0, u0 + 8, v0 + 8, top(8, 8) + 1])
    check("no fire without a tool to make it", err and "something to make fire" in err, err)
    pl["tools"].append("bow_drill")
    _, err = await w.ignite(WHO, [0, u0 + 8, v0 + 8, top(8, 8) + 6])
    check("no fire where nothing beside it burns (in open air)", err and "nothing here burns" in err, err)
    _, err = await w.ignite(WHO, [0, u0 + 17, v0 + 8, P["tops"][17][8] + 1])
    check("no fire on another's plot", err and "not your plot" in err, err)
    # a free spot on the grass near the neighbour's edge (litter may lie in some cells)
    for j in range(16):
        spot = [0, u0 + 14, v0 + j, top(14, j) + 1]
        out, err = await w.ignite(WHO, spot)
        if not err:
            break
    check("a bow drill lights a fire on the grass, beside the neighbour's plot", not err and tuple(spot) in w.fires, err)

    # 2 + 4: let it burn
    # 3: a plank wall and a stone-brick wall on the meadow near the fire
    pl["items"].update({"planks": 10, "stonebrick": 10})
    plank = [1200, 300, (top(12, 3) + 1) * 100, 100, 20, 150, B["planks"]]
    stone = [1300, 1000, (top(13, 10) + 1) * 100, 100, 20, 150, B["stonebrick"]]
    added, _, ref = await w.boxes(WHO, p_meadow, [plank, stone], [])
    check("a plank wall and a stone-brick wall stand on the meadow", len(added) == 2, ref)
    seen_max, east_touched = 0, False
    for i in range(400):
        out, burnt = await w.fire_tick()
        seen_max = max(seen_max, len(w.fires))
        if any(p == p_east for p in out):
            east_touched = True
        if not w.fires:
            break
    rec = w.plots[p_meadow]
    dirt = sum(1 for (x_, z_, y_), b in rec["edits"].items() if b == B["dirt"])
    check(f"it spread across the meadow (up to {seen_max} fires at once) and burnt its grass to earth ({dirt} cells)", seen_max > 5 and dirt > 20, (seen_max, dirt))
    check("it never crossed into the neighbour's plot", not east_touched and not (w.plots.get(p_east) or {}).get("edits"))
    check("the plank wall burnt down; the stone-brick wall stands", plank not in rec["boxes"] and stone in rec["boxes"], rec["boxes"])
    check("it died when nothing was left to burn: no fire cell remains", not w.fires and not any(b == S.FIRE for p_ in w.plots.values() for b in p_["edits"].values()))
    check("what burnt on the commons grows back like any commons edit",
          all(k in rec.get("exp", {}) for k, b in rec["edits"].items() if b == B["dirt"]))

    # 2: a tree burns
    fo = P["forest"]
    pt = S.plot_of(0, fo["u"], fo["v"])
    out, err = await w.ignite(WHO, [0, fo["u"] + 1, fo["v"], fo["top"] + 2])
    for i in range(300):
        await w.fire_tick()
        if not w.fires:
            break
    logs_left = [h for h in range(fo["top"] + 1, fo["top"] + fo["height"] + 1)
                 if (await w.blocks_at([[0, fo["u"], fo["v"], h]]))[(0, fo["u"], fo["v"], h)] == B["log"]]
    check(f"a tree beside a fire burns: its trunk is gone ({len(logs_left)} of {fo['height']} logs left)", not err and len(logs_left) < fo["height"] // 2, (err, logs_left))

    # 5: smother and beat out
    pl["items"]["dirt"] = 5
    _, err = await w.ignite(WHO, [0, u0 + 2, v0 + 12, top(2, 12) + 1])
    c = (0, u0 + 2, v0 + 12, top(2, 12) + 1)
    if err:   # this spot may have burnt already: light the next one along
        c = (0, u0 + 3, v0 + 13, top(3, 13) + 1); _, err = await w.ignite(WHO, list(c))
    _, ref, _ = await w.apply(WHO, [list(c) + [B["dirt"]]])
    check("earth put on a fire smothers it", not ref and c not in w.fires, (err, ref))
    c2 = (0, u0 + 5, v0 + 14, top(5, 14) + 1)
    _, err2 = await w.ignite(WHO, list(c2))
    if not err2:
        _, ref, _ = await w.apply(WHO, [list(c2) + [0]])
        check("a hand beats a fire out", not ref and c2 not in w.fires, ref)
    else:
        check("a hand beats a fire out", False, err2)
    # restart
    c3 = (0, u0 + 1, v0 + 1, top(1, 1) + 1)
    await w.ignite(WHO, list(c3))
    w.flush()
    w2 = S.World(data, "http://127.0.0.1:1", "")
    check("a restart puts every fire out", not any(b == S.FIRE for r in w2.plots.values() for b in r["edits"].values()))
    w.oracle.kill(); await w.oracle.wait()


asyncio.run(main())

# 6: the page
page = open(os.path.join(ROOT, "static", "land.js"), encoding="utf-8").read()
mesher = open(os.path.join(ROOT, "static", "land-mesher.js"), encoding="utf-8").read()
check("the page binds X to make fire and draws burning cells as flames that cast no shadow",
      'if (e.code === "KeyX") ignite();' in page and "if (m.flames)" in page and "me.material !== matFlame && !me.isInstancedMesh" in page
      and "blk[((k + 1) * N + (j + 1)) * N + (i + 1)] !== B.fire" in mesher)
r = subprocess.run(["node", "--input-type=module", "-e", """
const W = await import(%s), M = await import(%s);
const sp = W.plotCoords(W.plotId(0, W.SPAWN_PLOT_ROW, W.SPAWN_PLOT_COL)), u = sp.u0 + 8, v = sp.v0 + 8, h = W.column(0, u, v).top + 1;
const r = M.meshChunk(0, Math.floor(u / 16), Math.floor(v / 16), Math.floor(h / 16), new Map([[`0:${u}:${v}:${h}`, W.B.fire]]), null, 0);
const e = M.meshChunk(0, Math.floor(u / 16), Math.floor(v / 16), Math.floor(h / 16), new Map(), null, 0);
const cubes = (r.solid ? r.solid.pos.length : 0) + (r.clear ? r.clear.pos.length : 0) - (e.solid ? e.solid.pos.length : 0) - (e.clear ? e.clear.pos.length : 0);
console.log((r.flames ? r.flames.pos.length / 3 : 0) + ":" + cubes);
""" % (json.dumps(os.path.join(ROOT, "static", "land-world.js")), json.dumps(os.path.join(ROOT, "static", "land-mesher.js")))],
    capture_output=True, text=True, timeout=300)
check("a burning cell is meshed as three crossed flame quads — and no cube", r.stdout.strip().endswith("12:0"), (r.stdout[-60:], r.stderr[-200:]))
R = json.load(open(os.path.join(ROOT, "static", "land-recipes.json")))
check("a bow drill is sticks and cordage made by hand; flint and steel is iron and stone at the anvil; both make fire",
      R["tools"]["bow_drill"]["class"] == R["tools"]["flint_steel"]["class"] == "fire"
      and any(x["id"] == "bow_drill" and not x.get("with") for x in R["recipes"]) and any(x["id"] == "flint_steel" and "anvil" in x["with"] for x in R["recipes"]))
tr = json.load(open(os.path.join(ROOT, "static", "i18n_games", "land.json"), encoding="utf-8"))
keys = ["land.t.bow_drill", "land.t.flint_steel", "land.noFireTool", "land.igniteAim", "land.kFire"]
check("the tools and the fire strings are in 17 languages", len(tr) == 17 and all(all(l.get(k) for k in keys) for l in tr.values()))
_report.done()
