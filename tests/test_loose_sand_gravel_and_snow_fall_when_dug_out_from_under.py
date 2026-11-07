"""
GRAVITY in Land ("can we add some basic gravity", operator 2026-11-06; "i kept digging in snow but the snow stays put
and i dig under it"): sand, gravel and snow are loose. Driven through the world server's own apply() (scripts/
land_server.py) against the REAL planet — the server asks scripts/land_terrain.mjs, i.e. static/land-world.js, what each
cell holds:

  * a dune: dig out the sand under the top sand, and the top sand falls into the hole (the hole is filled, the top is
    empty); a column of three loose cells over a dug cell comes down as a column;
  * a snowy peak: dig under the snow and the snow comes down — it never hangs in the air over the hole;
  * earth does not fall: digging under a meadow's turf leaves the turf where it is;
  * placing sand over a dug pit drops it to the pit's floor;
  * a sandy seabed: the sand that falls leaves WATER behind it, never an air pocket under the sea;
  * every moved cell is broadcast in `applied` (so every page shows the fall) and is an edit of the commons, which
    regrows like any other.

Run: python3 tests/test_loose_sand_gravel_and_snow_fall_when_dug_out_from_under.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-gravity-")
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

# real columns from the generator
js = """
const W = await import(%s);
const B = W.B, sp = W.plotCoords(W.plotId(0, W.SPAWN_PLOT_ROW, W.SPAWN_PLOT_COL)), f = sp.face;
const find = (pred, step = 1) => { for (let r = 0; r < 6000; r += step) for (let d = -r; d <= r; d += Math.max(1, r)) for (const [u, v] of [[sp.u0 + r, sp.v0 + d], [sp.u0 + d, sp.v0 + r], [sp.u0 - r, sp.v0 + d], [sp.u0 + d, sp.v0 - r]]) {
  const c = W.column(f, u, v), x = pred(u, v, c); if (x) return x; } return null; };
const tb = (u, v, h) => W.terrainBlock(f, u, v, h);
const dune = find((u, v, c) => c.top > W.SEA + 1 && [0, 1, 2, 3].every((k) => tb(u, v, c.top - k) === B.sand) && tb(u, v, c.top + 1) === B.air ? [f, u, v, c.top] : null, 3);
// snow lies on the high ground and in the cold — far from the landing: a coarse sweep of the whole face
const snowy = (() => { for (let u = 0; u < W.W; u += 389) for (let v = 0; v < W.W; v += 389) { const c = W.column(f, u, v);
  if (tb(u, v, c.top) === B.snow && tb(u, v, c.top - 1) !== B.snow && tb(u, v, c.top - 1) !== B.air && tb(u, v, c.top + 1) === B.air) return [f, u, v, c.top]; } return null; })();
const meadow = find((u, v, c) => c.biome === "grass" && tb(u, v, c.top) === B.grass && tb(u, v, c.top - 1) === B.dirt && tb(u, v, c.top + 1) === B.air ? [f, u, v, c.top] : null);
const sea = find((u, v, c) => c.top < W.SEA - 1 && tb(u, v, c.top) === B.sand && tb(u, v, c.top - 1) === B.sand && tb(u, v, c.top + 1) === B.water ? [f, u, v, c.top] : null, 5);
console.log(JSON.stringify({ dune, snowy, meadow, sea, B: { sand: B.sand, snow: B.snow, dirt: B.dirt, grass: B.grass, water: B.water, air: B.air } }));
""" % json.dumps(os.path.join(ROOT, "static", "land-world.js"))
P = json.loads(subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=900).stdout)
B = P["B"]
check("the planet offers a dune, a snowy peak, a meadow and a sandy seabed to test on", all(P[k] for k in ("dune", "snowy", "meadow", "sea")),
      {k: P[k] for k in ("dune", "snowy", "meadow", "sea")})

WHO = "ndoGRAV" + "G" * 41


async def main():
    data = os.path.join(os.environ["HOME"], "land")
    w = S.World(data, "http://127.0.0.1:1", "")                   # offline: every plot is the commons
    await w.start_oracle()
    w.work = lambda who, s: True                                    # time is not what this test is about
    w.take = lambda who, n: True
    w.player(WHO)["tools"] += ["shovel", "pick"]

    async def cell(face, u, v, h):
        p = S.plot_of(face, u, v)
        rec = w.plots.get(p) or {"edits": {}}
        k = (u - (p % S.FACE_N) * S.PLOT, v - ((p // S.FACE_N) % S.FACE_N) * S.PLOT, h)
        return rec["edits"][k] if k in rec["edits"] else (await w.terrain([[face, u, v, h]]))[0]

    async def col(c, lo, hi):
        return [await cell(c[0], c[1], c[2], h) for h in range(lo, hi + 1)]

    # a dune: dig the sand under the top sand
    f, u, v, top = P["dune"]
    applied, refused, _ = await w.apply(WHO, [[f, u, v, top - 1, 0]])
    after = await col(P["dune"], top - 3, top + 1)
    check("dig under the top of a dune: the top sand falls into the hole and the top is empty",
          not refused and after == [B["sand"], B["sand"], B["sand"], B["air"], B["air"]], (after, refused))
    moved = [c for cs in applied.values() for c in cs]
    check("…and every moved cell is in `applied`, so every page shows the fall",
          [f, u, v, top - 1, B["sand"]] in moved and [f, u, v, top, B["air"]] in moved, moved)
    p = S.plot_of(f, u, v)
    k = (u - (p % S.FACE_N) * S.PLOT, v - ((p // S.FACE_N) % S.FACE_N) * S.PLOT, top - 1)
    check("…as an edit of the commons that regrows like any other", k in w.plots[p].get("exp", {}))
    # a column of three over a dug cell (the dune, now 3 sand from top-3 to top-1): dig the bottom one
    await w.apply(WHO, [[f, u, v, top - 3, 0]])
    after = await col(P["dune"], top - 4, top)
    check("a column of loose cells over a dug one comes down as a column",
          after[0] == B["sand"] and after[1:3] == [B["sand"], B["sand"]] and after[3] == B["air"] and after[4] == B["air"], after)

    # a snowy peak: dig under the snow
    f, u, v, top = P["snowy"]
    await w.apply(WHO, [[f, u, v, top - 1, 0]])
    after = await col(P["snowy"], top - 1, top + 1)
    check("dig under the snow and the snow comes down, never hanging over the hole", after == [B["snow"], B["air"], B["air"]], after)

    # earth does not fall
    f, u, v, top = P["meadow"]
    await w.apply(WHO, [[f, u, v, top - 1, 0]])
    after = await col(P["meadow"], top - 1, top)
    check("earth is not loose: dig under a meadow's turf and the turf stays", after == [B["air"], B["grass"]], after)

    # place sand over a dug pit: dig three cells down in the meadow next to it, then place sand at the top of the pit
    pit = [P["meadow"][0], P["meadow"][1] + 1, P["meadow"][2]]
    ptop = (await w.terrain([[pit[0], pit[1], pit[2], P["meadow"][3]]]))[0]
    t2 = P["meadow"][3]
    await w.apply(WHO, [[pit[0], pit[1], pit[2], t2 - k2, 0] for k2 in range(0, 3)])
    w.player(WHO)["items"]["sand"] = 5
    applied, refused, _ = await w.apply(WHO, [[pit[0], pit[1], pit[2], t2, B["sand"]]])
    after = await col(pit + [t2], t2 - 3, t2)
    check("sand placed over a pit drops to the pit's floor",
          not refused and after[1] == B["sand"] and after[2:] == [B["air"], B["air"]], (after, refused, ptop))

    # a sandy seabed: the fallen sand leaves water behind
    f, u, v, top = P["sea"]
    await w.apply(WHO, [[f, u, v, top - 1, 0]])
    after = await col(P["sea"], top - 1, top + 1)
    check("on the seabed, the sand that falls leaves water behind it — never an air pocket under the sea",
          after == [B["sand"], B["water"], B["water"]], after)
    w.oracle.kill(); await w.oracle.wait()


asyncio.run(main())
_report.done()
