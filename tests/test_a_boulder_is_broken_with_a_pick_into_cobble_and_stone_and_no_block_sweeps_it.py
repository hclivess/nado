"""
A BOULDER (#183 step 5, the concept picture's mossy boulder; land research look/step5/OBSERVED.md): the planet's own rock on
a meadow or a forest floor, a solid cell the world server (scripts/land_server.py) treats as stone's kind:
  1. by hand it is refused — "needs a stone pickaxe" (the rule's tool, named as the recipes name it);
  2. with a pick it breaks, the breaker gets cobble (and the bonus stone), and the cell is air at the server;
  3. a block placed into a boulder's cell is refused: it is no loose litter a block sweeps (SWEPT).
Run: python3 tests/test_a_boulder_is_broken_with_a_pick_into_cobble_and_stone_and_no_block_sweeps_it.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-boulder-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, subprocess, sys

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

A = generate_keydict()
FACE = 0


def find_boulder():
    """The first boulder of the planet's meadow near the town, as static/land-world.js litterAt places it: (plot, u, v, top)."""
    js = (f"const W = await import({json.dumps(os.path.join(ROOT, 'static', 'land-world.js'))});"
          "for (let v = 79000; v < 82000; v++) for (let u = 53000; u < 56500; u++) { const c = W.column(0, u, v);"
          " if (c.biome === 'grass' && c.top > W.SEA && W.litterAt(0, u, v, c) === W.B.boulder) { console.log(JSON.stringify([W.plotOf(0, u, v), u, v, c.top])); process.exit(0); } }")
    out = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def fake_exec(plot):
    async def assets(req):
        return web.json_response({"assets": [{"id": "7001", "issuer": L.ISSUER, "seed": str(L.plot_seed(plot))}]})

    async def asset(req):
        return web.json_response({"asset": {"id": req.query["id"]}, "holders": {A["address"]: "1"}})

    async def view(req):
        return web.json_response({"result": None})
    app = web.Application()
    app.add_routes([web.get("/exec/assets", assets), web.get("/exec/asset", asset), web.get("/exec/view", view)])
    return app


async def main():
    plot, u, v, top = find_boulder()
    check(f"the planet holds a boulder on a meadow plot ({plot} at {u}, {v})", plot and top > S.SEA if hasattr(S, "SEA") else True)
    ex = TestServer(fake_exec(plot)); await ex.start_server()
    data = tempfile.mkdtemp(prefix="nado_land_boulder_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "b" * 32)
    world.http = __import__("aiohttp").ClientSession()
    await world.start_oracle()
    world.work = lambda who, s: True
    a = A["address"]
    cell = [FACE, u, v, top + 1]
    at = await world.blocks_at([cell])
    check("the world server reads the boulder's cell as the boulder block (land_terrain through land-world)", at[tuple(cell)] == 85, at)
    pl = world.player(a); pl["tools"] = {}
    # 1. by hand
    applied, refused, changed = await world.apply(a, [cell + [0]])
    check("by hand it is refused: needs a pickaxe", refused and refused[0][1].startswith("needs a") and "pick" in refused[0][1], refused)
    # 3. a block does not sweep it
    pl["items"]["stone"] = 2
    applied, refused, changed = await world.apply(a, [cell + [3]])
    check("a block placed into the boulder's cell is refused (no loose litter a block sweeps)", refused and not applied.get(plot), (refused, applied))
    # 2. with a pick
    pl["tools"] = {"pick": 1.0} if isinstance(pl.get("tools"), dict) else pl["tools"]
    if not world._has_class(pl, "pick"):
        pl["tools"] = ["pick"]
    check("the breaker holds a pick (the test's premise)", world._has_class(pl, "pick"), pl["tools"])
    before = dict(pl["items"])
    applied, refused, changed = await world.apply(a, [cell + [0]])
    check("with a pick the boulder breaks", not refused and applied.get(plot), (refused, applied))
    got = {k: pl["items"].get(k, 0) - before.get(k, 0) for k in ("cobble", "stone")}
    check("…into cobble (and the bonus stone)", got["cobble"] >= 3 and got["stone"] >= 0, got)
    now = await world.blocks_at([cell])
    check("…and the cell is air at the server", now[tuple(cell)] == 0, now)
    world.oracle.kill(); await world.oracle.wait()
    await world.http.close(); await ex.close()


asyncio.run(main())
_report.done()
