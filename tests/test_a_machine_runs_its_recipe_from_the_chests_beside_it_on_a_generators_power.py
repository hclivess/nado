"""
FACTORIES on the world server (#148, "we also may need factorization like factorio or Satisfactory … for advanced tech",
operator 2026-11-09). scripts/land_server.py set_machine / factory_tick, land-recipes.json "machines":

  1. a smelter set to make iron takes iron ore and charcoal from the chest touching it and makes iron into it, one run
     a tick, by itself — once a generator within reach has fuel from the chest beside it;
  2. it says why it waits: no power, what it needs, no chest beside it, its chest full;
  3. the generator burns one coal for 20 runs (charcoal 10), and keeps its charge;
  4. a machine runs only what it stands in for: an assembler cannot smelt, a smelter cannot assemble; it never makes a
     station or a tool;
  5. only the plot's owner (and their builders) choose a machine's recipe; the choice and the charge survive a restart;
     a machine taken down forgets its recipe.

Run: python3 tests/test_a_machine_runs_its_recipe_from_the_chests_beside_it_on_a_generators_power.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-factory-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from aiohttp import web, ClientSession
from aiohttp.test_utils import TestServer
from signatures import generate_keydict
from execnode.games import land as L

spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
import _harness
_report = _harness.Report()
check = _report.check

A, Bk = generate_keydict(), generate_keydict()
PA = 4995 * L.FACE_N + 3435
SMELT, ASSEM, GEN, CHEST = 67, 68, 69, 54


def fake_exec():
    async def assets(req):
        return web.json_response({"assets": [{"id": "7001", "issuer": L.ISSUER, "seed": str(L.plot_seed(PA))}]})

    async def asset(req):
        return web.json_response({"asset": {"id": "7001"}, "holders": {A["address"]: "1"}})

    async def view(req):
        return web.json_response({"result": None})
    app = web.Application()
    app.add_routes([web.get("/exec/assets", assets), web.get("/exec/asset", asset), web.get("/exec/view", view)])
    return app


async def main():
    ex = TestServer(fake_exec()); await ex.start_server()
    data = tempfile.mkdtemp(prefix="nado_land_factory_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "b" * 32)
    world.http = ClientSession()
    a, b = A["address"], Bk["address"]
    world.player(a)["items"].update({"smelter": 1, "assembler": 1, "generator": 1, "chest": 4, "ironore": 6, "charcoal": 6, "coal": 2})
    Y = 20000
    smelter = [500, 500, Y, 100, 100, 120, SMELT]
    box_in = [600, 500, Y, 90, 50, 55, CHEST]                          # touching the smelter's east face
    gen = [500, 900, Y, 100, 100, 120, GEN]                             # 4 m away
    box_fuel = [600, 900, Y, 90, 50, 55, CHEST]
    assem = [1200, 1200, Y, 100, 100, 120, ASSEM]
    added, _, refused = await world.boxes(a, PA, [smelter, box_in, assem], [])
    check("a smelter, a chest beside it and an assembler are built", len(added) == 3 and not refused, refused)

    # 4. what each can run
    cfg, can, err = await world.set_machine(a, PA, smelter, None)
    check("a smelter can make iron, steel, glass, charcoal (furnace work)", all(r in can for r in ("iron", "steel", "glass", "charcoal")), can)
    check("…but not wire or a circuit (workshop work), nor a station or a tool", not any(r in can for r in ("wire", "circuit", "bloomery", "pick", "anvil")), can)
    _, acan, _ = await world.set_machine(a, PA, assem, None)
    check("an assembler can make wire, circuits, motors, planks — and not iron", all(r in acan for r in ("wire", "circuit", "motor", "planks")) and "iron" not in acan, acan)
    _, _, err = await world.set_machine(a, PA, smelter, "wire")
    check("a smelter is refused a recipe it cannot run", err and "cannot" in err, err)
    _, _, err = await world.set_machine(b, PA, smelter, "iron")
    check("a stranger cannot set a machine on another's plot", err and "not your plot" in err, err)

    cfg, _, err = await world.set_machine(a, PA, smelter, "iron")
    check("its owner sets the smelter to make iron", err is None and cfg["recipe"] == "iron", err)

    # 2. why it waits
    world.factory_tick()
    st = lambda: world.plots[PA]["machines"][S.chest_key(smelter)]["status"]
    check("with an empty chest it says what it needs", st().startswith("needs"), st())
    await world.chest(a, PA, box_in, {"ironore": 6, "charcoal": 6}, {})
    world.factory_tick()
    check("with its inputs but no generator it says it has no power", st().startswith("no power"), st())
    added, _, refused = await world.boxes(a, PA, [gen, box_fuel], [])
    world.factory_tick()
    check("a generator with no fuel beside it gives no power", st().startswith("no power") and len(added) == 2, (st(), refused))
    await world.chest(a, PA, box_fuel, {"coal": 1}, {})

    # 1. it runs
    world.factory_tick()
    items = world.plots[PA]["chests"][S.chest_key(box_in)]
    check("powered, one tick makes one iron from two ore and two charcoal, into its chest", items.get("iron") == 1 and items.get("ironore") == 4 and items.get("charcoal") == 4 and st() == "running", (items, st()))
    world.factory_tick(); world.factory_tick(); world.factory_tick()
    items = world.plots[PA]["chests"][S.chest_key(box_in)]
    check("…and goes on by itself until the ore runs out (3 iron from 6 ore)", items.get("iron") == 3 and not items.get("ironore") and st().startswith("needs"), (items, st()))
    gens = world.plots[PA]["gens"]
    check("the generator burnt one coal for 20 runs (3 used: 17 left), the coal gone from its chest",
          gens[S.chest_key(gen)] == 17 and not world.plots[PA]["chests"].get(S.chest_key(box_fuel), {}).get("coal"), (gens, world.plots[PA]["chests"].get(S.chest_key(box_fuel))))

    # 5. kept, and forgotten when taken down
    world.flush()
    w2 = S.World(data, "http://127.0.0.1:1", "")
    check("a restart keeps the smelter's recipe and the generator's charge",
          w2.plots[PA]["machines"][S.chest_key(smelter)]["recipe"] == "iron" and w2.plots[PA]["gens"][S.chest_key(gen)] == 17)
    world.workb.clear()
    _, removed, refused = await world.boxes(a, PA, [], [smelter])
    world.factory_tick()
    check("a smelter taken down forgets its recipe", removed and S.chest_key(smelter) not in world.plots[PA].get("machines", {}), (removed, refused))
    await world.http.close(); await ex.close()


asyncio.run(main())
_report.done()
