"""
PROPELLANT FROM WATER on the world server (#173, doc/land-navigation.md 1.5; operator 2026-11-10: "requires launching
orbital real physical gps satellites into orbit"). scripts/land_server.py factory_tick / run_cost, land-recipes.json:

  1. the recipes' energy is the derivation's (land research rockets/ENERGY.md): a bucket of water is 555.0 mol, split at
     a practical 1.5 V (237.24 kJ x 1.5 / 1.229 per mol) — 160.7 MJ; its 1.119 kg of hydrogen and the 6.748 kg of oxygen
     it burns with (6.03 : 1) liquefied at 11.5 and 1.22 kWh/kg — 75.9 MJ; a run of power is a twentieth of a coal's
     electricity (1 m3 x 1.35 t x 24 MJ/kg x 38 % = 12.3 GJ);
  2. an electrolyser beside a chest of water splits one bucketful a run into a hydrogen and an oxygen canister, and its
     generator's charge falls by 160.7 / 615 of a run — one coal splits 76 buckets, then it waits for power;
  3. a liquefier makes a hydrogen and an oxygen canister into liquid propellant, charged 75.9 / 615 of a run;
  4. the smelter still costs one run (no recipe without an energy figure is charged differently); a machine runs only
     work it stands in for, never hand work done at no station.

Run: python3 tests/test_water_is_split_and_liquefied_into_propellant_on_a_generators_real_energy.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-propellant-")
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
    data = tempfile.mkdtemp(prefix="nado_land_propellant_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "b" * 32)
    world.http = ClientSession()
    a = A["address"]
    R = {r["id"]: r for r in S.RULES["recipes"]}

    # 1. the energy, from the cited constants
    mol = 10 * 0.99984 * 1000 / 18.015                                  # a 10 L bucket of water
    e_split = mol * 237.24 * 1.5 / 1.229 / 1000                          # MJ
    h2 = mol * 2.016 / 1000; o2 = h2 * 6.03                             # kg
    e_liq = (h2 * 11.5 + o2 * 1.22) * 3.6                               # MJ
    coal = 1 * 1350 * 24 * 0.38                                         # MJ of electricity in a coal
    check(f"a bucket split at 1.5 V takes {e_split:.1f} MJ — the electrolysis recipe's", abs(R["electrolysis"]["mj"] - e_split) < 0.1, (R["electrolysis"]["mj"], e_split))
    check(f"liquefying its hydrogen and the oxygen it burns with takes {e_liq:.1f} MJ — the liquefier's", abs(R["liquefy_propellant"]["mj"] - e_liq) < 0.2, (R["liquefy_propellant"]["mj"], e_liq))
    check(f"a run of power is a twentieth of a coal's electricity ({coal:.0f} MJ)", abs(S.MACH["run_mj"] * S.MACH["fuel"]["coal"] - coal) / coal < 0.01, S.MACH["run_mj"])
    check(f"the propellant canister is that hydrogen and its oxygen at 6.03 : 1 ({h2 + o2:.2f} kg)", "7.87" in S.RULES["items"]["propellant"]["name"] and abs(h2 + o2 - 7.87) < 0.01)

    # 2. the electrolyser
    world.player(a)["items"].update({"electrolyser": 1, "liquefier": 1, "generator": 1, "chest": 3, "water": 100, "coal": 2, "hydrogen": 2, "oxygen": 2})
    Y = 20000
    el = [500, 500, Y, 100, 100, 120, S.MACHINES and 79]
    el_box = [600, 500, Y, 90, 50, 55, CHEST]
    lq = [500, 700, Y, 100, 100, 120, 80]
    lq_box = [600, 700, Y, 90, 50, 55, CHEST]
    gen = [500, 900, Y, 100, 100, 120, GEN]
    fuel = [600, 900, Y, 90, 50, 55, CHEST]
    added, _, refused = await world.boxes(a, PA, [el, el_box, lq, lq_box, gen, fuel], [])
    check("an electrolyser, a liquefier and a generator, each with a chest, are built", len(added) == 6 and not refused, refused)
    _, can, _ = await world.set_machine(a, PA, el, None)
    check("an electrolyser runs electrolysis and nothing else — not furnace, workshop or hand work", can == ["electrolysis"], can)
    await world.set_machine(a, PA, el, "electrolysis")
    await world.chest(a, PA, el_box, {"water": 100}, {})
    await world.chest(a, PA, fuel, {"coal": 1}, {})
    world.factory_tick()
    items = world.plots[PA]["chests"][S.chest_key(el_box)]
    charge = world.plots[PA]["gens"][S.chest_key(gen)]
    check("a run splits a bucket into a hydrogen and an oxygen canister", items.get("water") == 99 and items.get("hydrogen") == 1 and items.get("oxygen") == 1, items)
    check(f"…and the generator's charge falls by 160.7 / 615 of a run ({charge})", abs(charge - (20 - 160.7 / 615)) < 1e-6, charge)
    for _ in range(100):
        world.factory_tick()
    items = world.plots[PA]["chests"][S.chest_key(el_box)]
    st = world.plots[PA]["machines"][S.chest_key(el)]["status"]
    check(f"one coal splits 76 buckets ({100 - items.get('water', 0)} split), then it waits for power", 100 - items.get("water", 0) == 76 and st.startswith("no power"), (items, st))

    # 3. the liquefier
    await world.set_machine(a, PA, lq, "liquefy_propellant")
    await world.chest(a, PA, lq_box, {"hydrogen": 2, "oxygen": 2}, {})
    await world.chest(a, PA, fuel, {"coal": 1}, {})
    before = world.plots[PA]["gens"][S.chest_key(gen)]
    world.factory_tick()
    li = world.plots[PA]["chests"][S.chest_key(lq_box)]
    after = world.plots[PA]["gens"][S.chest_key(gen)]
    check("a liquefier makes a hydrogen and an oxygen canister into liquid propellant", li.get("propellant") == 1 and li.get("hydrogen") == 1 and li.get("oxygen") == 1, li)
    check("…charged for both machines' runs: 75.9 / 615 for it, 160.7 / 615 for the electrolyser beside it",
          abs((before + 20) - after - (75.9 + 160.7) / 615) < 1e-6, (before, after))

    # 4. the rest costs a run, as before
    check("a recipe without an energy figure still costs one run", S.run_cost(R["iron"]) == 1)
    await world.http.close(); await ex.close()


asyncio.run(main())
_report.done()
