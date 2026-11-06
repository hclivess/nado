"""
The Land world server (scripts/land_server.py) changes a plot only for its title's current holder and the builders that
holder invited — a person's click and an AI agent's API call through the same check — and it knows who is calling only
by a signature over its own one-time challenge. Driven over real HTTP and websockets against a fake exec node.

  * login: an agent signs in with its OWN key of any offered scheme (ML-DSA-44 and SLH-DSA here); a key that does not
    derive the address, a reused challenge, a browser's challenge presented as an agent's, and a browser callback from
    another browser (no login cookie) are all refused; a browser login ends in an HttpOnly session cookie;
  * writes: the holder builds; a stranger cannot; an invited builder can while the grant's grantor holds the title, and
    cannot once the title moves (the new holder's grant works again); water, bedrock, the bedrock layer and anything
    off the planet are refused; a call is capped at MAX_CELLS and a caller at RATE cells/s;
  * live: an edit reaches every socket watching its plot, the sender's included; players near each other see each other;
  * storage: the plot survives a restart (edits, version, salt), its salt and commitment go only to who may build, and
    the commitment is byte-for-byte the browser's (static/land-world.js plotCommitment, run in node).

Run: python3 tests/test_the_land_server_lets_only_holders_and_their_builders_change_a_plot.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-server-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient
from signatures import generate_keydict, sign, unhex
from hashing import blake2b_hash
from execnode.runtimes import zkvm_addr_digest
from execnode.games import land as L

spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)

import _harness
_report = _harness.Report()
check = _report.check

ISSUER = L.ISSUER
OWNER, BUILDER, STRANGER, BUYER = generate_keydict(), generate_keydict(), generate_keydict(), generate_keydict()
AGENT_SLH = generate_keydict("slhdsa128s")
SPAWN_FACE, ROW, COL = 0, 4924, 4662
PA = (SPAWN_FACE * L.FACE_N + ROW) * L.FACE_N + COL            # the owner's plot
PB = PA + 1                                                     # a plot nobody here holds
UA, VA = COL * L.PLOT, ROW * L.PLOT                             # its first column

holders = {PA: OWNER["address"], PB: "6c29de76c487be78f3af402f892fe80c0eb7d9a9d92093f1ac"}
grants = {}                                                     # (plot, addr) -> grantor address


def fake_exec():
    async def assets(req):
        return web.json_response({"assets": [{"id": str(9000 + p), "issuer": ISSUER, "seed": str(L.plot_seed(p))} for p in (PA, PB)]})

    async def asset(req):
        p = int(req.query["id"]) - 9000
        return web.json_response({"asset": {"id": req.query["id"]}, "holders": {holders[p]: "1"}})

    async def view(req):
        p, addr = json.loads(req.query["args"])
        g = grants.get((p, addr))
        return web.json_response({"result": str(zkvm_addr_digest(g)) if g else None})
    app = web.Application()
    app.add_routes([web.get("/exec/assets", assets), web.get("/exec/asset", asset), web.get("/exec/view", view)])
    return app


async def agent_login(c, kd, alg=None, nonce=None, tamper=None):
    ch = await (await c.get("/land/api/challenge?kind=agent")).json()
    n = nonce or ch["nonce"]
    msg = blake2b_hash([S.DOMAIN, S.AGENT_ORIGIN, kd["address"], n, ch["issued"]], 32)
    body = {"address": kd["address"], "public_key": (tamper or kd)["public_key"], "signature": sign(kd["private_key"], unhex(msg), alg=alg), "nonce": n}
    if alg:
        body["alg"] = alg
    r = await c.post("/land/api/agent_login", json=body)
    return r.status, (await r.json() if r.status == 200 else await r.text()), n


async def main():
    ex = TestServer(fake_exec()); await ex.start_server()
    data = tempfile.mkdtemp(prefix="nado_land_srv_")
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "f" * 32)
    app = S.make_app(world, S.Hub(), "https://land.example", "https://wallet.example", secure_cookies=False)
    c = TestClient(TestServer(app)); await c.start_server()
    auth = lambda tok: {"Authorization": "Bearer " + tok}

    # ---- login -----------------------------------------------------------------------------------------------------
    st, owner, n1 = await agent_login(c, OWNER)
    check("an agent signs in with its own ML-DSA-44 key", st == 200 and owner["address"] == OWNER["address"], owner)
    st, slh, _ = await agent_login(c, AGENT_SLH, alg="slhdsa128s")
    check("…and with a key of another offered scheme (SLH-DSA)", st == 200, slh)
    st, txt, _ = await agent_login(c, STRANGER, tamper=OWNER)
    check("a key that does not derive the address is refused", st == 400 and "derive" in txt, (st, txt))
    st, txt, _ = await agent_login(c, OWNER, nonce=n1)
    check("a challenge is good for one login only", st == 400, (st, txt))
    bnonce, bissued = world.challenge("https://land.example", "bind-x")
    msg = blake2b_hash([S.DOMAIN, S.AGENT_ORIGIN, OWNER["address"], bnonce, bissued], 32)
    r = await c.post("/land/api/agent_login", json={"address": OWNER["address"], "public_key": OWNER["public_key"],
                                                    "signature": sign(OWNER["private_key"], unhex(msg)), "nonce": bnonce})
    check("a browser's challenge cannot be signed in as an agent's", r.status == 400, r.status)
    r = await c.get("/land/api/login", allow_redirects=False)
    loc = r.headers.get("Location", "")
    check("a browser login goes to the wallet with a land challenge and a login cookie",
          r.status == 302 and loc.startswith("https://wallet.example/?land_login=1") and "land_login" in r.cookies, (r.status, loc))
    q = dict(x.split("=", 1) for x in loc.split("?", 1)[1].split("&"))
    from urllib.parse import unquote
    site, nonce, issued = unquote(q["site"]), q["nonce"], int(q["issued"])
    msg = blake2b_hash([S.DOMAIN, site, BUILDER["address"], nonce, issued], 32)
    form = {"address": BUILDER["address"], "public_key": BUILDER["public_key"], "alg": "", "nonce": nonce,
            "signature": sign(BUILDER["private_key"], unhex(msg))}
    import aiohttp
    async with aiohttp.ClientSession() as other:                              # another browser: no login cookie
        r = await other.post(str(c.make_url("/land/api/login_callback")), data=form, allow_redirects=False)
        check("the wallet's callback must arrive in the browser that started the login", r.status == 403, r.status)
    r = await c.post("/land/api/login_callback", data=form, allow_redirects=False)
    sess = r.cookies.get("land_session")
    check("a browser login ends in an HttpOnly session cookie", r.status == 302 and sess is not None and sess["httponly"], (r.status, r.cookies))
    me = await (await c.get("/land/api/me")).json()
    check("…and the page then knows who it is", me.get("address") == BUILDER["address"], me)
    c.session.cookie_jar.clear()

    # ---- writes ----------------------------------------------------------------------------------------------------
    st, stranger, _ = await agent_login(c, STRANGER)
    st, builder, _ = await agent_login(c, BUILDER)
    cell = [SPAWN_FACE, UA + 3, VA + 4, 120, 11]
    r = await (await c.post("/land/api/set", json={"cells": [cell]}, headers=auth(owner["token"]))).json()
    check("the holder builds on their plot", r["applied"] == 1 and not r["refused"], r)
    r = await (await c.post("/land/api/set", json={"cells": [[SPAWN_FACE, UA + 5, VA, 120, 11]]}, headers=auth(stranger["token"]))).json()
    check("a stranger cannot", r["applied"] == 0 and "not your plot" in r["refused"][0][1], r)
    r = await (await c.post("/land/api/set", json={"cells": [[SPAWN_FACE, UA + 16, VA, 120, 11]]}, headers=auth(owner["token"]))).json()
    check("the holder cannot build on the next plot (someone else's)", r["applied"] == 0, r)
    r = await (await c.post("/land/api/set", json={"cells": [[SPAWN_FACE, UA + 6, VA, 120, 11]]}, headers=auth(builder["token"]))).json()
    check("an uninvited builder cannot", r["applied"] == 0, r)
    grants[(PA, BUILDER["address"])] = OWNER["address"]
    world.grants.clear()
    r = await (await c.post("/land/api/set", json={"cells": [[SPAWN_FACE, UA + 6, VA, 120, 9]]}, headers=auth(builder["token"]))).json()
    check("a builder the holder invited can", r["applied"] == 1, r)
    holders[PA] = BUYER["address"]; world.holders.clear(); world.grants.clear()          # the title is sold
    r = await (await c.post("/land/api/set", json={"cells": [[SPAWN_FACE, UA + 7, VA, 120, 9]]}, headers=auth(builder["token"]))).json()
    check("once the title moves, the old owner's grant is void", r["applied"] == 0, r)
    r = await (await c.post("/land/api/set", json={"cells": [[SPAWN_FACE, UA + 7, VA, 120, 9]]}, headers=auth(owner["token"]))).json()
    check("…and the old owner cannot build either", r["applied"] == 0, r)
    grants[(PA, BUILDER["address"])] = BUYER["address"]; world.grants.clear()
    r = await (await c.post("/land/api/set", json={"cells": [[SPAWN_FACE, UA + 7, VA, 120, 9]]}, headers=auth(builder["token"]))).json()
    check("the new holder's own grant works", r["applied"] == 1, r)
    holders[PA] = OWNER["address"]; world.holders.clear(); world.grants.clear()
    bad = [[SPAWN_FACE, UA, VA, 120, 5], [SPAWN_FACE, UA, VA, 120, 30], [SPAWN_FACE, UA, VA, 0, 3], [6, 0, 0, 100, 3], [SPAWN_FACE, UA, VA, 256, 3]]
    r = await (await c.post("/land/api/set", json={"cells": bad}, headers=auth(owner["token"]))).json()
    check("water, bedrock, the bedrock layer and cells off the planet are refused", r["applied"] == 0 and len(r["refused"]) == 5, r)
    r = await (await c.post("/land/api/set", json={"cells": [cell] * (S.MAX_CELLS + 1)}, headers=auth(owner["token"]))).json()
    check(f"a call carries at most {S.MAX_CELLS} cells", r["applied"] == 0 and "at most" in r["refused"][0][1], r)
    many = [[SPAWN_FACE, UA + (i % 16), VA + (i // 16) % 16, 130 + i // 256, 3] for i in range(S.MAX_CELLS)]
    r1 = await (await c.post("/land/api/set", json={"cells": many}, headers=auth(stranger["token"]))).json()
    r2 = await (await c.post("/land/api/set", json={"cells": many[:800]}, headers=auth(stranger["token"]))).json()
    check(f"one full call goes through the limiter, then a caller is held to {S.RATE} cells/s",
          "rate limited" not in str(r1["refused"][:1]) and r2["refused"] and "rate limited" in r2["refused"][0][1], (r1["refused"][:1], r2["refused"][:1]))
    r = await c.post("/land/api/set", json={"cells": [cell]})
    check("no session, no writes", r.status == 401, r.status)

    # ---- live ------------------------------------------------------------------------------------------------------
    w1 = await c.ws_connect("/land/ws?token=" + owner["token"])
    w2 = await c.ws_connect("/land/ws?token=" + stranger["token"])
    rj = lambda ws: asyncio.wait_for(ws.receive_json(), 5)                  # never wait forever on a socket
    h1, h2 = await rj(w1), await rj(w2)
    check("a socket is greeted with who it is", h1["you"] == OWNER["address"] and h2["you"] == STRANGER["address"], (h1, h2))
    await w2.send_json({"t": "watch", "plots": [PA]})
    first = await rj(w2)
    check("watching a plot sends its edits", first["t"] == "plot" and first["plot"] == PA and len(first["edits"]) >= 2 and "salt" not in first, first)
    await w1.send_json({"t": "watch", "plots": [PA]}); await rj(w1)
    await w1.send_json({"t": "set", "cells": [[SPAWN_FACE, UA + 9, VA + 9, 121, 12]], "req": 7})
    got = {}
    for ws, name in ((w1, "w1"), (w1, "w1"), (w2, "w2")):
        m = await asyncio.wait_for(ws.receive_json(), 5)
        while m["t"] == "players":
            m = await asyncio.wait_for(ws.receive_json(), 5)
        got.setdefault(name, []).append(m)
    check("the sender is told what applied", any(m["t"] == "set_ok" and m["applied"] == 1 and m["req"] == 7 for m in got["w1"]), got["w1"])
    check("every watcher gets the edit, the sender's included",
          any(m["t"] == "edit" and m["cells"] == [[SPAWN_FACE, UA + 9, VA + 9, 121, 12]] for m in got["w1"])
          and got["w2"][0]["t"] == "edit" and got["w2"][0]["by"] == OWNER["address"], got)
    await w1.send_json({"t": "pos", "p": [SPAWN_FACE, UA + 1.5, VA + 1.5, 120, 0]})
    await w2.send_json({"t": "pos", "p": [SPAWN_FACE, UA + 30.5, VA + 2.5, 121, 1]})
    seen = None
    for _ in range(20):
        m = await asyncio.wait_for(w2.receive_json(), 5)
        if m["t"] == "players" and m["list"]:
            seen = m["list"]; break
    check("players near each other see each other", seen and seen[0]["who"] == OWNER["address"], seen)
    await w2.send_json({"t": "set", "cells": [[SPAWN_FACE, UA + 1, VA + 1, 121, 12]]})
    m = await asyncio.wait_for(w2.receive_json(), 5)
    while m["t"] == "players":
        m = await asyncio.wait_for(w2.receive_json(), 5)
    check("a stranger's socket edit is refused like an API call", m["t"] == "set_ok" and m["applied"] == 0, m)
    await w1.close(); await w2.close()

    # ---- storage and the commitment ----------------------------------------------------------------------------------
    pj = await (await c.get(f"/land/api/plot?plot={PA}", headers=auth(owner["token"]))).json()
    pj2 = await (await c.get(f"/land/api/plot?plot={PA}", headers=auth(stranger["token"]))).json()
    check("the salt and commitment go to who may build, not to anyone", "salt" in pj and "commitment" in pj and "salt" not in pj2, (list(pj), list(pj2)))
    world.flush()
    w3 = S.World(data, "http://127.0.0.1:1", "")
    rec = w3.plots.get(PA)
    check("the plot survives a restart: edits, version and salt", rec and rec["edits"] == world.plots[PA]["edits"]
          and rec["ver"] == world.plots[PA]["ver"] and rec["salt"] == world.plots[PA]["salt"], rec)
    js = ("const W = await import(%s); const salt = Uint8Array.from(Buffer.from(%s, 'hex'));"
          "console.log(await W.plotCommitment(%d, salt, %s));") % (json.dumps(os.path.join(ROOT, "static", "land-world.js")),
                                                                  json.dumps(pj["salt"]), PA, json.dumps(pj["edits"]))
    out = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60)
    check("the server's commitment is the browser's, byte for byte", out.stdout.strip() == pj["commitment"], (out.stdout, out.stderr[-300:], pj["commitment"]))
    await c.close(); await ex.close()


asyncio.run(main())
_report.done()
