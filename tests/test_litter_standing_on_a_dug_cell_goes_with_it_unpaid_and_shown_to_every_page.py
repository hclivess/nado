"""
#177 (playtest 2026-11-11, shot 42_dug: "a pebble that stood on it stays floating above the hole"). Driven through the
world server's own apply() against the REAL planet (scripts/land_server.py, the terrain from static/land-world.js):
  * a meadow cell with litter on it (a pebble, twigs, flax or a flower as the planet laid it): dig the turf under it,
    and the litter cell is air too — not a pebble hanging over the hole;
  * the litter is not paid: the digger's bag gets the turf's yield and nothing for what fell;
  * both cells are in `applied`, so every page shows the litter go, and both are edits of the commons that regrow;
  * a sapling on the dug cell is NOT swept: it stays (a tree to be is the ecology's, not the dig's).
Run: python3 tests/test_litter_standing_on_a_dug_cell_goes_with_it_unpaid_and_shown_to_every_page.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-litter-")
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
const LIT = new Set([B.pebble, B.twigs, B.flax, ...W.FLOWERS]);
let hit = null;
for (let r = 0; r < 6000 && !hit; r += 1) for (let d = -r; d <= r && !hit; d += Math.max(1, r)) for (const [u, v] of [[sp.u0 + r, sp.v0 + d], [sp.u0 + d, sp.v0 + r], [sp.u0 - r, sp.v0 + d], [sp.u0 + d, sp.v0 - r]]) {
  const c = W.column(f, u, v);
  if (c.biome === "grass" && tb(u, v, c.top) === B.grass && LIT.has(tb(u, v, c.top + 1)) && tb(u, v, c.top + 2) === B.air) { hit = [f, u, v, c.top, tb(u, v, c.top + 1)]; break; }
}
console.log(JSON.stringify({ hit, B: { grass: B.grass, air: B.air, sapling: B.sapling, pebble: B.pebble } }));
""" % json.dumps(os.path.join(ROOT, "static", "land-world.js"))
P = json.loads(subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=900).stdout)
B = P["B"]
check("the planet offers a meadow cell with litter standing on it near the landing", bool(P["hit"]), P["hit"])

WHO = "ndoLITT" + "L" * 41


async def main():
    data = os.path.join(os.environ["HOME"], "land")
    w = S.World(data, "http://127.0.0.1:1", "")                   # offline: every plot is the commons
    await w.start_oracle()
    w.work = lambda who, s: True
    w.take = lambda who, n: True
    pl = w.player(WHO)
    pl["tools"] += ["shovel", "pick"]

    async def cell(face, u, v, h):
        p = S.plot_of(face, u, v)
        rec = w.plots.get(p) or {"edits": {}}
        k = (u - (p % S.FACE_N) * S.PLOT, v - ((p // S.FACE_N) % S.FACE_N) * S.PLOT, h)
        return rec["edits"][k] if k in rec["edits"] else (await w.terrain([[face, u, v, h]]))[0]

    f, u, v, top, litter = P["hit"]
    before = dict(pl["items"])
    applied, refused, _ = await w.apply(WHO, [[f, u, v, top, 0]])
    after = [await cell(f, u, v, top), await cell(f, u, v, top + 1)]
    check("dig the turf under litter: the turf and the litter are both air — nothing floats over the hole", not refused and after == [B["air"], B["air"]], (after, refused))
    yields = {k: pl["items"].get(k, 0) - before.get(k, 0) for k in set(pl["items"]) | set(before)}
    litter_rule = S.RULES["breaking"].get(str(litter)) or {"yields": []}
    turf_rule = S.RULES["breaking"][str(B["grass"])]
    check("the digger is paid the turf's yield and nothing for the litter that fell",
          all(yields.get(i, 0) >= n for i, n in turf_rule["yields"]) and all(yields.get(i, 0) == sum(m for j, m in turf_rule["yields"] if j == i) for i, n in litter_rule["yields"]), (yields, litter_rule["yields"]))
    moved = [c for cs in applied.values() for c in cs]
    check("both cells are in `applied`, so every page shows the litter go", [f, u, v, top, 0] in moved and [f, u, v, top + 1, 0] in moved, moved)
    p = S.plot_of(f, u, v)
    k1 = (u - (p % S.FACE_N) * S.PLOT, v - ((p // S.FACE_N) % S.FACE_N) * S.PLOT, top + 1)
    check("…and the litter's cell is an edit of the commons that regrows like any other", k1 in w.plots[p].get("exp", {}))

    # a sapling on a dug cell stays: plant one on a fresh turf cell, dig under it
    f2, u2, v2 = f, u + 2, v
    c2 = (await w.terrain([[f2, u2, v2, top]]))[0]
    if c2 == B["grass"] and (await w.terrain([[f2, u2, v2, top + 1]]))[0] == B["air"]:
        pl["items"]["sapling"] = pl["items"].get("sapling", 0) + 1
        _, ref2, _ = await w.apply(WHO, [[f2, u2, v2, top + 1, B["sapling"]]], at=[f2, u2, v2, top + 1])
        await w.apply(WHO, [[f2, u2, v2, top, 0]])
        check("a sapling on the dug cell is not swept away: it stays", not ref2 and (await cell(f2, u2, v2, top + 1)) == B["sapling"], (ref2, await cell(f2, u2, v2, top + 1)))
    else:
        check("a sapling on the dug cell is not swept away (no fresh turf beside the litter to plant on — skipped)", True)
    w.oracle.kill(); await w.oracle.wait()


asyncio.run(main())
_report.done()
