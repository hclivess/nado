"""Fixture for tests/test_two_players_and_an_agent_build_together_in_the_live_world.mjs (not a test itself): ONE origin
serving the real Land page (static/), the real world server (scripts/land_server.py make_app, mounted as in production
under /land/) and a fake exec node (/exec/*) that says OWNER holds plot PA and has invited AGENT to build on it.

  python3 tests/_land_live_fixture.py <protocol.js path>     -> prints "PORT <n>" then serves until killed
  GET /fixture/owner_token   -> {token}: OWNER signed in through the agent login, with OWNER's own key (the browser
                                session cookie the test sets is exactly what /land/api/login_callback would have set)
  GET /fixture/agent_build   -> AGENT signs in with ITS OWN key and builds a 3 x 3 wall through POST /land/api/set
  GET /fixture/plot          -> {plot, owner, agent}
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-live-")       # CLAUDE.md rule 4
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from aiohttp import web, ClientSession
from signatures import generate_keydict, sign, unhex
from hashing import blake2b_hash
from execnode.runtimes import zkvm_addr_digest
from execnode.games import land as L

spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)

STATIC = os.path.join(ROOT, "static")
PROTOCOL_JS = open(sys.argv[1]).read()
OWNER, AGENT = generate_keydict(), generate_keydict()
PA = (0 * L.FACE_N + 4924 + 4) * L.FACE_N + 4662 + 4          # a first-wave plot
TITLE = {"id": "777001", "issuer": L.ISSUER, "seed": str(L.plot_seed(PA)), "dec": 0, "supply": "1", "name": "Plot", "sym": "LAND"}


async def main():
    world = S.World(tempfile.mkdtemp(prefix="nado_land_live_"), "http://127.0.0.1:1", "e" * 32)
    app = S.make_app(world, S.Hub(), "http://land.test", "http://wallet.test", secure_cookies=False)
    port_box = {}

    async def assets(req):
        if req.query.get("issuer") == L.ISSUER:
            return web.json_response({"assets": [TITLE], "cursor": 1})
        if req.query.get("holder") == OWNER["address"]:
            return web.json_response({"assets": [TITLE], "cursor": 1})
        return web.json_response({"assets": [], "cursor": 1})

    async def asset(req):
        return web.json_response({"asset": TITLE, "holders": {OWNER["address"]: "1"}, "cursor": 1})

    async def view(req):
        p, addr = json.loads(req.query["args"])
        ok = p == PA and addr == AGENT["address"]
        return web.json_response({"result": str(zkvm_addr_digest(OWNER["address"])) if ok else None})

    async def login_as(kd):
        base = f"http://127.0.0.1:{port_box['p']}"
        async with ClientSession() as c:
            ch = await (await c.get(base + "/land/api/challenge?kind=agent")).json()
            msg = blake2b_hash([S.DOMAIN, S.AGENT_ORIGIN, kd["address"], ch["nonce"], ch["issued"]], 32)
            r = await c.post(base + "/land/api/agent_login", json={"address": kd["address"], "public_key": kd["public_key"],
                                                                   "signature": sign(kd["private_key"], unhex(msg)), "nonce": ch["nonce"]})
            return (await r.json())["token"]

    async def owner_token(req):
        return web.json_response({"token": await login_as(OWNER)})

    async def agent_build(req):
        tok = await login_as(AGENT)
        f, row, col = 0, (PA // L.FACE_N) % L.FACE_N, PA % L.FACE_N
        u0, v0 = col * L.PLOT + 2, row * L.PLOT + 12
        top = int(req.query.get("top", "100"))
        cells = [[f, u0 + i, v0, top + 1 + j, 14] for i in range(3) for j in range(3)]       # a 3 x 3 brick wall
        async with ClientSession() as c:
            r = await c.post(f"http://127.0.0.1:{port_box['p']}/land/api/set", json={"cells": cells},
                             headers={"Authorization": "Bearer " + tok})
            return web.json_response(await r.json())

    async def plot(req):
        return web.json_response({"plot": PA, "owner": OWNER["address"], "agent": AGENT["address"]})

    async def page(req):
        return web.FileResponse(os.path.join(STATIC, "land.html"))

    async def proto(req):
        return web.Response(text=PROTOCOL_JS, content_type="text/javascript")

    async def empty(req):
        return web.json_response({})

    app.add_routes([web.get("/", page), web.get("/protocol.js", proto), web.get("/exec/assets", assets),
                    web.get("/exec/asset", asset), web.get("/exec/view", view), web.get("/fixture/owner_token", owner_token),
                    web.get("/fixture/agent_build", agent_build), web.get("/fixture/plot", plot)])
    app.router.add_static("/static", STATIC)
    app.router.add_route("*", "/{tail:.*}", empty)
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0); await site.start()
    port_box["p"] = site._server.sockets[0].getsockname()[1]
    world.exec_url = f"http://127.0.0.1:{port_box['p']}"        # the fake exec routes live on this same origin
    print("PORT", port_box["p"], flush=True)
    while True:
        await asyncio.sleep(3600)

asyncio.run(main())
