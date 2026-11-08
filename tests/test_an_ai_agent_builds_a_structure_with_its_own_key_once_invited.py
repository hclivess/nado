"""
An AI agent shapes a plot through scripts/land_agent.py exactly as its docstring tells an operator to: `newkey` makes the
agent's OWN key (0600, never overwriting one), the plot's owner invites the printed address, `build` places a structure
from a JSON file of in-plot cells, and `plot` reads it back — against the real world server (scripts/land_server.py) over
HTTP, with a fake exec node standing in for the chain's answers (who holds the title, who was invited).

  * before the invitation the agent's build is refused, cell by cell, with the reason;
  * after it, every cell lands, at the planet coordinates the in-plot cells name;
  * a cell outside the plot is refused by the client before anything is sent;
  * `newkey` refuses to overwrite an existing key file.

Run: python3 tests/test_an_ai_agent_builds_a_structure_with_its_own_key_once_invited.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-agent-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, stat, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from aiohttp import web
from aiohttp.test_utils import TestServer
from signatures import generate_keydict
from execnode.runtimes import zkvm_addr_digest
from execnode.games import land as L

spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
import _harness
_report = _harness.Report()
check = _report.check

OWNER = generate_keydict()
PA = (0 * L.FACE_N + 4925) * L.FACE_N + 4663
invited = set()
AGENT = os.path.join(os.environ["HOME"], "agent.json")
HOUSE = os.path.join(os.environ["HOME"], "house.json")
CELLS = [[x, z, y, 11] for x in (4, 5, 6) for z in (4, 5, 6) for y in (130, 131)] + [[5, 5, 132, 13]]


def fake_exec():
    async def assets(req):
        return web.json_response({"assets": [{"id": "5001", "issuer": L.ISSUER, "seed": str(L.plot_seed(PA))}]})

    async def asset(req):
        return web.json_response({"asset": {"id": "5001"}, "holders": {OWNER["address"]: "1"}})

    async def view(req):
        p, addr = json.loads(req.query["args"])
        return web.json_response({"result": str(zkvm_addr_digest(OWNER["address"])) if (p, addr) in invited else None})
    app = web.Application()
    app.add_routes([web.get("/exec/assets", assets), web.get("/exec/asset", asset), web.get("/exec/view", view)])
    return app


def agent(*args):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "land_agent.py"), *args], capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout, r.stderr


async def main():
    ex = TestServer(fake_exec()); await ex.start_server()
    world = S.World(tempfile.mkdtemp(prefix="nado_land_agent_", dir=os.environ["HOME"]), str(ex.make_url("")).rstrip("/"), "d" * 32)
    srv = TestServer(S.make_app(world, S.Hub(), "https://land.example", "https://wallet.example", secure_cookies=False))
    await srv.start_server()
    url = str(srv.make_url("")).rstrip("/")
    loop = asyncio.get_running_loop()
    run = lambda *a: loop.run_in_executor(None, lambda: agent("--server", url, *a))

    rc, out, err = await run("newkey", "--out", AGENT)
    addr = out.strip()
    kd = json.load(open(AGENT))
    check("newkey makes the agent's own key and prints its address", rc == 0 and kd["address"] == addr and len(kd["private_key"]) == 64, (rc, out, err))
    check("…readable by its owner only", stat.S_IMODE(os.stat(AGENT).st_mode) == 0o600, oct(os.stat(AGENT).st_mode))
    rc, out, err = await run("newkey", "--out", AGENT)
    check("newkey never overwrites a key file", rc != 0 and "refusing to overwrite" in err, (rc, err))

    world.player(addr)["items"]["tiles"] = 4                         # what it builds with is its own inventory
    world.player(addr)["items"]["brick"] = 18
    json.dump(CELLS, open(HOUSE, "w"))
    rc, out, err = await run("--keys", AGENT, "build", "--plot", str(PA), "--file", HOUSE)
    r = json.loads(out or "{}")
    check("before the owner invites it, the agent's build is refused with the reason",
          rc == 0 and r.get("applied") == 0 and r.get("refused_total") == len(CELLS) and "not your plot" in r["refused"][0][1], (rc, out, err))

    invited.add((PA, addr)); world.grants.clear()                     # the owner presses "Invite a builder"
    rc, out, err = await run("--keys", AGENT, "build", "--plot", str(PA), "--file", HOUSE)
    r = json.loads(out or "{}")
    check("once invited, every cell of the structure lands", rc == 0 and r.get("applied") == len(CELLS) and r.get("refused_total") == 0, (rc, out, err))
    rc, out, err = await run("--keys", AGENT, "inventory")
    check("…spending exactly the bricks and tile it placed", rc == 0 and json.loads(out)["items"] == {"tiles": 3}, (rc, out, err))
    rc, out, err = await run("--keys", AGENT, "plot", "--plot", str(PA))
    pj = json.loads(out or "{}")
    got = sorted(map(tuple, pj.get("edits", [])))
    check("reading the plot back gives exactly the structure, in plot coordinates", got == sorted(map(tuple, CELLS)) and pj.get("may_build") is True, (got[:4], pj.get("may_build")))
    fr, fc = (PA // L.FACE_N) % L.FACE_N, PA % L.FACE_N
    check("…at the planet columns the in-plot cells name", world.plots[PA]["edits"].get((4, 4, 130)) == 11 and S.plot_of(0, fc * 16 + 4, fr * 16 + 4) == PA)

    world.player(addr)["items"]["planks"] = 1
    rc, out, err = await run("--keys", AGENT, "pieces", "--plot", str(PA), "--add", json.dumps([[400, 400, 13300, 150, 4, 90, 9], [0, 0, 13300, 1, 1, 1, 9]]))
    r = json.loads(out or "{}")
    check("an agent places pieces at 1 cm — a 150 x 4 x 90 cm board and a 1 cm peg — paid by their volume",
          rc == 0 and r.get("added") == 2 and r["inventory"]["vol"].get("planks") == 1_000_000 - 150 * 4 * 90 - 1, (rc, out, err))
    json.dump([[16, 0, 130, 11]], open(HOUSE, "w"))
    rc, out, err = await run("--keys", AGENT, "build", "--plot", str(PA), "--file", HOUSE)
    check("a cell outside the plot is refused by the client before anything is sent", rc != 0 and "outside the plot" in err, (rc, err))
    await srv.close(); await ex.close()


asyncio.run(main())
_report.done()
