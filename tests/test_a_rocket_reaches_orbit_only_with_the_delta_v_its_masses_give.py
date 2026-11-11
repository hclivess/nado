"""
ROCKETS on the world server (#173, doc/land-navigation.md 1.5; operator 2026-11-10: "requires launching orbital real
physical gps satellites into orbit"). scripts/land_server.py launch_numbers / launch, land-recipes.json "rocket":

  1. the parts are the sourced ones: a tenth-scale RS-25 keeps its specific impulse and its thrust-to-weight (RS-25:
     1,859 kN at sea level for 3,177 kg); a tank weighs 3.6 % of the propellant it holds (the Shuttle's external tank,
     26.5 t empty for 735.5 t); a canister of propellant fits the tank's volume (1.119 kg of LH2 at 70.85 kg/m3 and
     6.748 kg of LOX at 1,141 kg/m3); a satellite weighs a GPS Block IIF's 1,633 kg;
  2. the launch is the rocket equation at sea-level Isp from the rocket's own masses, less the gravity loss of its whole
     burn — computed here by hand and matched — against the 1,096 m/s the orbit asks;
  3. one full tank falls short: launched, it is spent (pieces and propellant gone) and nothing reaches orbit;
  4. two full tanks reach orbit: the satellite is the next of the constellation, kept across a restart;
  5. a rocket whose thrust does not beat its weight is refused at the pad and nothing is spent;
  6. only the plot's owner (and their builders) launch from it.

Run: python3 tests/test_a_rocket_reaches_orbit_only_with_the_delta_v_its_masses_give.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-rocket-")
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
    import math
    ex = TestServer(fake_exec()); await ex.start_server()
    data = tempfile.mkdtemp(prefix="nado_land_rocket_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "b" * 32)
    world.http = ClientSession()
    a, b = A["address"], Bk["address"]
    RK, I = S.RULES["rocket"], S.RULES["items"]

    # 1. the parts
    e = RK["engine"]
    check("the engine keeps the RS-25's thrust-to-weight (1,859 kN for 3,177 kg) at a tenth of its size",
          abs(e["thrust_kn"] / e["kg"] - 1859 / 3177) < 1e-3 and abs(e["kg"] - 317.7) < 0.05, e)
    tank_dry = S.FLIGHT["unit_mass"]["82"] * 1000
    check(f"a tank weighs 3.6 % of the {RK['tank']['holds']} canisters it holds ({tank_dry:.1f} kg), as the Shuttle's external tank (26.5 / 735.5 t)",
          abs(tank_dry / (RK["tank"]["holds"] * RK["canister_kg"]) - 26.5 / 735.5) < 0.001, tank_dry)
    vol = RK["tank"]["holds"] * (1.119 / 70.85 + 6.748 / 1141.2)
    u = I["propellant_tank"]["unit"]
    check(f"its {RK['tank']['holds']} canisters of liquid hydrogen and oxygen ({vol:.2f} m3) fit inside it ({u[0] * u[1] * u[2] / 1e6:.2f} m3)", vol <= u[0] * u[1] * u[2] / 1e6, vol)
    check("a satellite weighs a GPS Block IIF's 1,633 kg", abs(S.FLIGHT["unit_mass"]["83"] - 1.633) < 1e-9)

    world.player(a)["items"].update({"launch_pad": 3, "rocket_engine": 3, "propellant_tank": 4, "nav_satellite": 3, "chest": 3, "propellant": 400, "steel_plate": 30})
    Y = 20000
    def rocket(x0, tanks):
        pad = [x0, 200, Y, 300, 300, 20, 84]
        eng = [x0 + 120, 320, Y + 20, 60, 60, 120, 81]
        parts = [pad, eng]
        for k in range(tanks):
            parts.append([x0 + 100, 300, Y + 140 + 220 * k, 100, 100, 220, 82])
        parts.append([x0 + 75, 275, Y + 140 + 220 * tanks, 150, 150, 150, 83])
        chest = [x0 + 300, 200, Y, 90, 50, 55, 54]
        return pad, parts, chest
    def expect(tanks, load):
        dry = e["kg"] + tanks * tank_dry + 1633; wet = dry + load * 7.87
        dv = 366 * 9.80665 * math.log(wet / dry); loss = 9.8 * load * 7.87 * 366 * 9.80665 / (e["thrust_kn"] * 1000)
        return dry, wet, dv, loss, dv - loss

    # 3. one tank: short
    pad1, parts1, chest1 = rocket(100, 1)
    added, _, refused = await world.boxes(a, PA, parts1 + [chest1], [])
    check("a pad, an engine, one tank, a satellite and a chest are built", len(added) == len(parts1) + 1 and not refused, refused)
    await world.chest(a, PA, chest1, {"propellant": 100}, {})
    n = world.launch_numbers(PA, pad1)
    dry, wet, dv, loss, net = expect(1, 100)
    check(f"its numbers are the rocket equation's from its own masses: Δv {n['dv']} m/s less {n['loss']} lost to gravity = {n['net']}",
          abs(n["dry_kg"] - dry) < 0.2 and abs(n["dv"] - dv) < 0.2 and abs(n["loss"] - loss) < 0.2 and n["need"] == 1096, (n, dry, dv, loss))
    check("…one full tank is not enough for orbit, and it says so", not n["ok"] and "not enough" in n["why"], n)
    _, _, err = await world.launch(b, PA, pad1)
    check("a stranger cannot launch from another's plot", err and "not your plot" in err, err)
    num, gone, err = await world.launch(a, PA, pad1)
    left = [x for x in world.plots[PA]["boxes"] if x in parts1[1:]]
    check("launched anyway, it is spent: its pieces gone, its propellant burnt, nothing in orbit",
          err is None and len(gone) == len(parts1) - 1 and not left and world.plots[PA]["chests"][S.chest_key(chest1)].get("propellant", 0) == 0 and world.sats == [], (err, len(gone), world.sats))

    # 4. two tanks: orbit
    pad2, parts2, chest2 = rocket(700, 2)
    added, _, refused = await world.boxes(a, PA, parts2 + [chest2], [])
    await world.chest(a, PA, chest2, {"propellant": 200}, {})
    n = world.launch_numbers(PA, pad2)
    dry, wet, dv, loss, net = expect(2, 200)
    check(f"two full tanks: Δv {n['dv']} less {n['loss']} = {n['net']} m/s, enough for the orbit's 1,096", n["ok"] and abs(n["net"] - net) < 0.3 and net >= 1096, n)
    num, gone, err = await world.launch(a, PA, pad2)
    check("launched, its satellite is in orbit — the first of the constellation", err is None and len(world.sats) == 1 and world.sats[0]["owner"] == a and world.sats[0]["n"] == 0, world.sats)
    world.flush()
    w2 = S.World(data, str(ex.make_url("")).rstrip("/"), "b" * 32)
    check("…and stays there across a restart", w2.sats == world.sats)

    # 5. too heavy to leave the pad
    pad3, parts3, _ = rocket(1100, 1)
    chest3 = [1100, 500, Y, 90, 50, 55, 54]                              # on the pad's north side
    ballast = [1100, 200, Y + 20, 70, 300, 600, 64]                      # 12.6 m3 of steel plate on the pad beside it: 18.9 t
    added, _, refused = await world.boxes(a, PA, parts3 + [ballast, chest3], [])
    check("a rocket with 18.9 t of steel on it is built", len(added) == len(parts3) + 2 and not refused, refused)
    await world.chest(a, PA, chest3, {"propellant": 100}, {})
    n = world.launch_numbers(PA, pad3)
    num, gone, err = await world.launch(a, PA, pad3)
    check(f"a rocket whose thrust ({n['thrust_kn']} kN) does not beat its weight ({n['weight_kn']} kN) is refused at the pad, nothing spent",
          n["thrust_kn"] <= n["weight_kn"] and err and "too heavy" in err and not gone and world.plots[PA]["chests"][S.chest_key(chest3)].get("propellant") == 100, (n, err))
    await world.http.close(); await ex.close()


asyncio.run(main())
_report.done()
