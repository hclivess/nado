"""
A CRAFT TEARS THROUGH TREES (operator 2026-11-13, the X fighter wedged in a broadleaf after a landing on grass: "x fighter
should tear trees down through sheer force (minor damage perhaps)"). scripts/land_server.py apply(craft=) / craft_reach:
  1. the pilot's craft, beside the planet's own tree, tears its lowest trunk cell: applied, and the tree above it comes
     down with it (the felling), and NOTHING is gathered — no wood, no sticks — where a hand with an axe would gather;
  2. a crown cell is torn the same way, nothing gathered;
  3. refused: the ground under the tree ("trees, nothing else"); a tree out of the craft's reach; placing a block through
     a craft; a log someone PLACED (an edit, not the planet's tree);
  4. refused: a craft the caller does not fly (a stranger's id; its own after the pilot left);
  5. a titled plot of another keeps its trees from a stranger's craft (the plot's rule, as for a hand); the commons
     (an untitled plot) give way to anyone's craft;
  6. by hand the trunk still needs the axe (unchanged).
Run: python3 tests/test_a_flown_craft_tears_the_planets_trees_within_its_reach_and_gathers_nothing.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-tear-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, math, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from aiohttp import web
from aiohttp.test_utils import TestServer
from signatures import generate_keydict
from execnode.games import land as L
spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
import _harness
_report = _harness.Report()
check = _report.check

A, Bk = generate_keydict(), generate_keydict()
PA = 4989 * L.FACE_N + 3433                                   # A's titled plot (the fake exec below holds it for A): a wooded one, 7 trees
PB = PA + 1                                                   # its eastern neighbour: untitled, the commons
PLATE, THR, SEAT = 64, 65, 66
FACE = 0


def fake_exec():
    async def assets(req):
        return web.json_response({"assets": [{"id": "7001", "issuer": L.ISSUER, "seed": str(L.plot_seed(PA))}]})

    async def asset(req):
        return web.json_response({"asset": {"id": req.query["id"]}, "holders": {A["address"]: "1"}})

    async def view(req):
        return web.json_response({"result": None})
    app = web.Application()
    app.add_routes([web.get("/exec/assets", assets), web.get("/exec/asset", asset), web.get("/exec/view", view)])
    return app


def tree_roots(plot):
    """The planet's trees rooted in `plot` (static/land-world.js treeRoots): [{wu, wv, top, kind, height}, ...]."""
    fr, fc = (plot // L.FACE_N) % L.FACE_N, plot % L.FACE_N
    js = (f"const W = await import({json.dumps(os.path.join(ROOT, 'static', 'land-world.js'))});"
          f"console.log(JSON.stringify(W.treeRoots({FACE}, {fc * L.PLOT}, {fr * L.PLOT}, {L.PLOT}).map((r) => [r.wu, r.wv, r.col.top, r.tree.kind, r.tree.height])));")
    out = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, check=True).stdout
    return [dict(wu=u, wv=v, top=t, kind=k, height=h) for u, v, t, k, h in json.loads(out)]


async def tree_cells(world, root):
    """One trunk cell and one crown cell of this tree as the world server holds them: ((face, u, v, h), (face, u, v, h))."""
    u, v, top, h0 = root["wu"], root["wv"], root["top"], root["height"]
    cands = [[FACE, u + du, v + dv, top + dh] for dh in range(1, h0 + 2) for du in (0, 1, -1) for dv in (0, 1, -1)]
    got = await world.blocks_at(cands)
    wood = next((tuple(c) for c in cands if got[tuple(c)] in S.TREE_WOOD), None)
    crown = next((tuple(c) for c in cands if got[tuple(c)] in S.TREE_LEAVES), None)
    return wood, crown


async def craft_for(world, who, plot, y_cm):
    """A small craft (a plate, a seat, a thruster) built on `plot` in the air and boarded: its id."""
    fr, fc = (plot // L.FACE_N) % L.FACE_N, plot % L.FACE_N
    hull = [600, 600, y_cm, 400, 150, 5, PLATE]
    seat = [760, 640, y_cm + 5, 80, 90, 110, SEAT]
    thr = [700, 500, y_cm, 100, 100, 140, THR]
    world.player(who)["items"].update({"steel_plate": 2, "thruster": 2, "pilot_seat": 1})
    added, _, refused = await world.boxes(who, plot, [hull, seat, thr], [])
    assert len(added) == 3 and not refused, refused
    c, parts, err = await world.board(who, plot, seat)
    assert err is None, err
    return c


async def main():
    ex = TestServer(fake_exec()); await ex.start_server()
    data = tempfile.mkdtemp(prefix="nado_land_tear_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "b" * 32)
    world.http = __import__("aiohttp").ClientSession()
    await world.start_oracle()                                    # the terrain oracle: the planet's trees as the server reads them
    world.work = lambda who, s: True
    a, b = A["address"], Bk["address"]
    rootsA, rootsB = tree_roots(PA), tree_roots(PB)
    check("the planet grew trees on A's plot and on the commons beside it", len(rootsA) >= 2 and len(rootsB) >= 1, (len(rootsA), len(rootsB)))
    ta, tb = rootsA[0], rootsB[0]
    far = max(rootsA[1:], key=lambda r: math.dist((r["wu"], r["wv"]), (ta["wu"], ta["wv"])))
    (wood, crown), (fwood, _) = await tree_cells(world, ta), await tree_cells(world, far)
    check("a trunk cell and a crown cell of the first tree are found as the server holds them", wood and crown, (ta, wood, crown))
    beside = lambda r: [FACE, r["wu"] + 2.5, r["wv"] + 0.5, r["top"] + 1.5, 0.0]     # the craft's pose 2 m east of the trunk

    # A's craft, beside the tree on A's plot
    ca = await craft_for(world, a, PA, 20000)
    cid = ca["id"]
    reach = S.craft_reach(ca["pieces"])
    check("the craft's body reaches a few metres from its seat (craft_reach)", 2 < reach < 8, reach)
    ca["pose"] = beside(ta)
    pl = world.player(a); before = dict(pl["items"])

    # 1. the trunk is torn, the tree comes down, nothing gathered
    applied, refused, changed = await world.apply(a, [[*wood, 0]], craft=cid)
    cells = applied.get(PA) or []
    check("the craft tears the trunk cell: applied, no refusal", not refused and any(c[:4] == list(wood) for c in cells), (refused, cells[:3]))
    check("…and the tree above it comes down with it (more cells than the one torn)", len(cells) > 1, len(cells))
    check("…and nothing is gathered: no wood, no sticks, the inventory unchanged", dict(pl["items"]) == before and not changed, (pl["items"], before))
    now = await world.blocks_at([list(wood)])
    check("the trunk cell is air at the server now", now[wood] == 0, now)

    # 2. a crown cell of the far tree (still standing) — torn from beside it
    ca["pose"] = beside(far)
    _, fcrown = await tree_cells(world, far)
    applied, refused, changed = await world.apply(a, [[*fcrown, 0]], craft=cid)
    check("a crown cell is torn the same way, nothing gathered", not refused and (applied.get(PA) or []) and dict(pl["items"]) == before, (refused, pl["items"]))

    # 3. refusals: the ground; out of reach; placing; a placed log
    ground = (FACE, ta["wu"], ta["wv"], ta["top"])
    applied, refused, changed = await world.apply(a, [[*ground, 0]], craft=cid)
    check("the ground under the tree is refused: a craft tears through trees, nothing else", refused and "trees, nothing else" in refused[0][1], refused)
    ca["pose"] = beside(ta)                                       # back beside the first tree: the far tree's trunk is out of reach
    check("the far tree stands farther than the craft reaches (the test's premise)", math.dist(ca["pose"][1:4], (fwood[1] + 0.5, fwood[2] + 0.5, fwood[3] + 0.5)) > reach + S.TEAR_SLACK)
    applied, refused, changed = await world.apply(a, [[*fwood, 0]], craft=cid)
    check("a tree out of the craft's reach is refused", refused and "out of the craft's reach" in refused[0][1], refused)
    applied, refused, changed = await world.apply(a, [[FACE, ta["wu"], ta["wv"], ta["top"] + 12, PLATE]], craft=cid)
    check("placing through a craft is refused", refused and "places nothing" in refused[0][1], refused)
    pl["items"]["wood"] = 1
    placed = (FACE, ta["wu"] + 1, ta["wv"], ta["top"] + 12)
    applied, refused, changed = await world.apply(a, [[*placed, 7]])
    check("A places a log of their own in the air over the tree (by hand, on their plot)", not refused and applied.get(PA), refused)
    ca["pose"] = [FACE, placed[1] + 1.5, placed[2] + 0.5, placed[3] + 0.5, 0.0]
    applied, refused, changed = await world.apply(a, [[*placed, 0]], craft=cid)
    check("a placed log is no tree to a craft: refused", refused and "not what someone built" in refused[0][1], refused)

    # 4. not the pilot
    applied, refused, changed = await world.apply(b, [[*crown, 0]], craft=cid)
    check("a stranger naming A's craft is refused: you are not flying that", refused and refused[0][1] == "you are not flying that", refused)
    world.leave(a, cid)
    applied, refused, changed = await world.apply(a, [[*crown, 0]], craft=cid)
    check("…and so is its owner once they left the controls", refused and refused[0][1] == "you are not flying that", refused)

    # 5. a titled plot of another keeps its trees; the commons give way
    cb = await craft_for(world, b, PB, 20000)
    cb["pose"] = beside(ta)
    applied, refused, changed = await world.apply(b, [[*crown, 0]], craft=cb["id"])
    check("B's craft at A's tree: not your plot", refused and refused[0][1].startswith("not your plot"), refused)
    bwood, _ = await tree_cells(world, tb)
    cb["pose"] = beside(tb)
    applied, refused, changed = await world.apply(b, [[*bwood, 0]], craft=cb["id"])
    check("B's craft tears a tree of the commons", not refused and applied.get(PB), (refused, list(applied)))

    # 6. by hand, unchanged: the trunk needs the axe
    world.player(a)["tools"] = {}
    applied, refused, changed = await world.apply(a, [[*fwood, 0]])
    check("by hand the trunk still needs an axe", refused and refused[0][1].startswith("needs a"), refused)

    world.oracle.kill(); await world.oracle.wait()
    await world.http.close(); await ex.close()


asyncio.run(main())
_report.done()
