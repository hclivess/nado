"""
A signed-in player comes back where they left off — on any device, in any browser ("land server does not store player
position? why did i respawn somewhere off again", operator 2026-11-07). Driven through the world server's real app
(scripts/land_server.py make_app) over its live channel, as the page speaks it:

  1. a player who signs in and moves is told nothing of a place on the first visit; their place is kept as they move
     (at most every POS_SAVE_S) and when they leave, and survives a restart of the world server;
  2. the next connection — another browser, another device — is told that place in its hello; a stranger's (signed-out)
     hello carries none, and a place out of the world is never kept;
  3. the page goes there on its first connect when it is newer than the browser's own saved place (a reload in the same
     browser keeps where you just were; an underground place waits for its plot's edits), and re-asks the
     world server about builder invitations at every title refresh (one given or withdrawn shows without a reload).

Run: python3 tests/test_a_signed_in_player_comes_back_to_their_last_place_on_any_device.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-place-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from signatures import generate_keydict, sign, unhex
from hashing import blake2b_hash
spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
import _harness
_report = _harness.Report()
check = _report.check
KD = generate_keydict()
PLACE = [0, 55048.5, 80001.5, 137.0, 0.25]


async def main():
    data = os.path.join(os.environ["HOME"], "land")
    world = S.World(data, "http://127.0.0.1:1", "e" * 32)
    srv = TestServer(S.make_app(world, S.Hub(), "http://land.test", "http://wallet.test", secure_cookies=False))
    await srv.start_server()
    base = f"http://127.0.0.1:{srv.port}"
    try:
        async with ClientSession() as c:
            ch = await (await c.get(base + "/land/api/challenge?kind=agent")).json()
            msg = blake2b_hash([S.DOMAIN, S.AGENT_ORIGIN, KD["address"], ch["nonce"], ch["issued"]], 32)
            tok = (await (await c.post(base + "/land/api/agent_login", json={"address": KD["address"], "public_key": KD["public_key"],
                   "signature": sign(KD["private_key"], unhex(msg)), "nonce": ch["nonce"]})).json())["token"]
            auth = {"Authorization": "Bearer " + tok}

            async def visit(moves, headers=auth):
                ws = await c.ws_connect(base + "/land/ws", headers=headers)
                hello = await ws.receive_json()
                for p in moves:
                    await ws.send_json({"t": "pos", "p": p})
                await asyncio.sleep(0.3)
                await ws.close()
                await asyncio.sleep(0.2)
                return hello

            h1 = await visit([[9, 1, 1, 1, 0], PLACE])
            check("a first visit is told of no place", h1.get("t") == "hello" and h1.get("pos") is None, h1)
            h2 = await visit([])
            check("the next visit — another browser, another device — is told where they left off, and when",
                  h2.get("pos") == PLACE and isinstance(h2.get("pos_at"), int) and abs(h2["pos_at"] - __import__("time").time()) < 30, h2)
            h3 = await visit([], headers={})
            check("a stranger's (signed-out) hello carries no place", "pos" not in h3 and h3.get("you") is None, h3)
            check("a place out of the world is never kept", world.player(KD["address"])["pos"][0] == 0)
            # kept as they move, at most every POS_SAVE_S: a live session updates it without leaving
            ws = await c.ws_connect(base + "/land/ws", headers=auth)
            await ws.receive_json()
            await ws.send_json({"t": "pos", "p": [0, 55050.5, 80003.5, 137.0, 1.0]})
            await asyncio.sleep(0.3)
            check("…and kept while they play, before they leave", world.player(KD["address"])["pos"][1] == 55050.5)
            await ws.close()
            await asyncio.sleep(0.2)
    finally:
        await srv.close()
    world.flush()
    w2 = S.World(data, "http://127.0.0.1:1", "e" * 32)
    check("the place survives a restart of the world server", w2.player(KD["address"]).get("pos") == [0, 55050.5, 80003.5, 137.0, 1.0],
          w2.player(KD["address"]).get("pos"))


asyncio.run(main())

page = open(os.path.join(ROOT, "static", "land.js"), encoding="utf-8").read()
check("the page goes to the kept place on its first connect, when it is newer than the browser's own",
      "if (!net.placed) { net.placed = true; if (m.pos && (m.pos_at || 0) > localPlace) takePlace(m.pos); }" in page
      and "at: Math.floor(Date.now() / 1000), hot, piece" in page and "pendingPlace = [f, u, v, h, yaw, P.pitch]" in page)
check("…and re-asks about builder invitations at every title refresh, adding or removing",
      "t.asked = false; t.checked = false;" in page and "if (r.may_build) builds.add(plot); else builds.delete(plot);" in page)
_report.done()
