"""
"we may need npcs and quests and move this a little towards world of warcraft as well" (operator, 2026-11-09;
doc/land-civilisation.md, #165). The world server (scripts/land_server.py):

  * NPCs stand in the town where the rules put them; a player near one talks to them, a player across the land does not;
  * the quest giver offers each player quests made from the world (bring what the land holds, hunt its game, carry a
    parcel to another NPC); the NPCs near a player say whether they have work ("!") or a quest to hand in ("?");
  * a player holds a few at a time; a bring quest takes the items into the town treasury when handed in, a hunt quest
    counts the player's kills of its kind, a deliver quest hands a parcel over at the other NPC;
  * rewards: experience (a level from it) and a small share of the town treasury — and nothing from nothing: with an
    empty treasury a quest pays experience only; the treasury is filled by the market's share of every trade and by
    what quests bring in;
  * a dropped quest is gone, its parcel back with the town;
  * quests and experience are kept with the player.

Run: python3 tests/test_quests_are_given_by_npcs_and_paid_from_the_town_treasury.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-quests-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient
from signatures import generate_keydict, sign, unhex
from hashing import blake2b_hash

spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
import _harness
_report = _harness.Report()
check = _report.check
A, Bk, C = generate_keydict(), generate_keydict(), generate_keydict()
RULES = json.load(open(os.path.join(ROOT, "static", "land-recipes.json")))
MK = RULES["market"]
FACE, U0, V0, H = 0, 55040, 79712, 200                         # unowned land; the stands stand in the air (no terrain needed)


def fake_exec():
    async def assets(req):
        return web.json_response({"assets": []})

    async def asset(req):
        return web.json_response({"asset": {"id": "0"}, "holders": {}})

    async def view(req):
        return web.json_response({"result": None})
    app = web.Application()
    app.add_routes([web.get("/exec/assets", assets), web.get("/exec/asset", asset), web.get("/exec/view", view)])
    return app


async def login(c, kd):
    ch = await (await c.get("/land/api/challenge?kind=agent")).json()
    msg = blake2b_hash([S.DOMAIN, S.AGENT_ORIGIN, kd["address"], ch["nonce"], ch["issued"]], 32)
    r = await c.post("/land/api/agent_login", json={"address": kd["address"], "public_key": kd["public_key"],
                                                    "signature": sign(kd["private_key"], unhex(msg)), "nonce": ch["nonce"]})
    return {"Authorization": "Bearer " + (await r.json())["token"]}


async def main():
    ex = TestServer(fake_exec()); await ex.start_server()
    data = tempfile.mkdtemp(prefix="nado_land_quests_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "c" * 32)
    c = TestClient(TestServer(S.make_app(world, S.Hub(), "https://land.example", "https://wallet.example", secure_cookies=False)))
    await c.start_server()
    ha, hb = await login(c, A), await login(c, Bk)
    c.server.app["bg"][-1].cancel()                                # no herd: the test counts kills itself
    a, b = A["address"], Bk["address"]
    Q = RULES["quests"]
    NPC = {n["id"]: n for n in Q["npcs"]}
    def at_npc(who, nid, du=1.0):
        n = NPC[nid]; world.keep_place(who, [n["at"][0], n["at"][1] + du, n["at"][2], 137.0, 0.0])
    talk = lambda h, nid: c.get("/land/api/talk", params={"npc": nid}, headers=h)
    async def quest(h, op, nid, qid):
        return await (await c.post("/land/api/quest", json={"op": op, "npc": nid, "id": qid}, headers=h)).json()
    items = lambda who: world.inv_json(who)["items"]

    # ---- NPCs and what they offer ---------------------------------------------------------------------------------------
    world.keep_place(a, [0, 1000.0, 1000.0, 137.0, 0.0])
    r = await (await talk(ha, "elder")).json()
    check("a player across the land does not talk to the elder", not r["ok"] and "far" in r["error"], r)
    at_npc(a, "elder")
    r = await (await talk(ha, "elder")).json()
    check("near the elder, she offers quests made from the world", r["ok"] and len(r["offers"]) == Q["offered"]
          and all(q["kind"] in ("bring", "hunt", "deliver") for q in r["offers"]), r)
    marks = {n["id"]: n["mark"] for n in world.npcs_for(a, world.player(a)["pos"], 64)}
    check("the NPCs near a player say whether they have work for them", marks.get("elder") == "!" and set(marks) == set(NPC), marks)
    r2 = await (await talk(ha, "elder")).json()
    check("the offers stay the same until taken", [q["id"] for q in r2["offers"]] == [q["id"] for q in r["offers"]])

    # ---- one quest of each kind -------------------------------------------------------------------------------------------
    pl = world.player(a)
    pl["offered"]["elder"] = [{"id": "q1", "kind": "bring", "giver": "elder", "item": "sticks", "n": 10},
                              {"id": "q2", "kind": "hunt", "giver": "elder", "what": "rabbit", "n": 2, "got": 0},
                              {"id": "q3", "kind": "deliver", "giver": "elder", "to": "trader"}]
    for qid in ("q1", "q2", "q3"):
        r = await quest(ha, "accept", "elder", qid)
        check(f"quest {qid} is accepted", r["ok"], r)
    check("a deliver quest hands the player its parcel", items(a).get("parcel") == 1)
    r = await (await c.post("/land/api/offer", json={"give": {"parcel": 1}, "want": {"stone": 1}}, headers=ha)).json()
    check("…which is carried, not traded", not r["ok"] and "parcel" in r["error"], r)
    pl["offered"]["elder"].append({"id": "q4", "kind": "bring", "giver": "elder", "item": "stone", "n": 1})
    r = await quest(ha, "accept", "elder", "q4")
    check(f"at most {Q['max_open']} quests at a time", not r["ok"] and "at most" in r["error"], r)

    # bring: not done, then done; the items go to the town
    r = await quest(ha, "turnin", "elder", "q1")
    check("a bring quest is not handed in without the items", not r["ok"] and "not done" in r["error"], r)
    pl["items"]["sticks"] = 12
    marks = {n["id"]: n["mark"] for n in world.npcs_for(a, world.player(a)["pos"], 64)}
    check("…with them, the elder marks a quest to hand in", marks.get("elder") == "?", marks)
    r = await quest(ha, "turnin", "elder", "q1")
    check("handed in: experience, and with an empty treasury nothing else (nothing from nothing)", r["ok"] and r["xp"] == Q["xp"]["bring"] and r["paid"] == {}, r)
    check("…the sticks went to the town treasury", items(a).get("sticks") == 2 and world.treasury.get("sticks") == 10, world.treasury)

    # hunt: the kills count
    world.animal_seq += 1
    world.animals[world.animal_seq] = {"id": world.animal_seq, "kind": "rabbit", "face": 0, "u": pl["pos"][1] + 1, "v": pl["pos"][2], "h": 137.0,
                                       "yaw": 0.0, "hp": 1, "go": 1e18, "flee": 0, "angry": False}
    pl["tools"].append("spear"); world.workb.clear()
    res, err = world.hunt(a, world.animal_seq, pl["pos"])
    q2 = next(q for q in pl["quests"] if q["id"] == "q2")
    check("a rabbit hunted counts toward the hunt quest", res and res["killed"] == "rabbit" and q2["got"] == 1, (res, err, q2))
    r = await quest(ha, "turnin", "elder", "q2")
    check("…one of two is not enough", not r["ok"], r)
    q2["got"] = 2
    r = await quest(ha, "turnin", "elder", "q2")
    paid = r.get("paid")
    check("two hunted: handed in, paid from the treasury's largest stock (a small share)", r["ok"] and paid == {"sticks": max(1, int(10 * Q["reward_share"]))}
          and world.treasury["sticks"] == 10 - paid["sticks"], (r, world.treasury))

    # deliver: at the other NPC
    r = await quest(ha, "turnin", "elder", "q3")
    check("a parcel is not delivered to the one who sent it", not r["ok"] and "does not end here" in r["error"], r)
    r = await quest(ha, "turnin", "trader", "q3")
    check("…and not from across the square: go up to the trader", not r["ok"] and "far" in r["error"], r)
    at_npc(a, "trader")
    r = await quest(ha, "turnin", "trader", "q3")
    check("delivered to the trader: the parcel handed over, experience paid — and nothing from the treasury (a walk, free to repeat)",
          r["ok"] and not items(a).get("parcel") and r["xp"] == Q["xp"]["deliver"] and r["paid"] == {}, r)
    check("experience makes levels", world.inv_json(a)["xp"] == Q["xp"]["bring"] + Q["xp"]["hunt"] + Q["xp"]["deliver"] and world.inv_json(a)["level"] == 1 and S.World.level_of(100) == 2 and S.World.level_of(300) == 3)

    # ---- the treasury fills from the market --------------------------------------------------------------------------------
    t0 = world.treasury.get("copper_coin", 0)
    p = S.plot_of(0, 55041, 79990)
    fc, fr = p % S.FACE_N, (p // S.FACE_N) % S.FACE_N
    stand = [(55041 - fc * 16) * 100, (79990 - fr * 16) * 100, 20000] + RULES["items"]["stand"]["unit"] + [S.STAND]
    world.player(a)["items"].update({"stand": 1, "iron": 4}); world.player(b)["items"]["copper_coin"] = 100
    await (await c.post("/land/api/boxes", json={"plot": p, "add": [stand]}, headers=ha)).json()
    world.keep_place(a, [0, 55042.0, 79990.5, 200.0, 0.0]); world.keep_place(b, [0, 55042.5, 79990.5, 200.0, 0.0])
    r = await (await c.post("/land/api/offer", json={"give": {"iron": 4}, "want": {"copper_coin": 40}}, headers=ha)).json()
    await (await c.post("/land/api/accept", json={"id": r["id"]}, headers=hb)).json()
    check("the market's share of a trade goes into the town treasury", world.treasury.get("copper_coin", 0) == t0 + int(40 * RULES["market"]["fee"]), world.treasury)

    # ---- dropping, and keeping ---------------------------------------------------------------------------------------------
    pl["offered"]["elder"] = [{"id": "q5", "kind": "deliver", "giver": "elder", "to": "smith"}]
    at_npc(a, "elder")
    await quest(ha, "accept", "elder", "q5")
    r = await quest(ha, "drop", "", "q5")
    check("a dropped quest is gone, its parcel back with the town", r["ok"] and not any(q["id"] == "q5" for q in pl["quests"]) and not items(a).get("parcel"), r)
    world.odirty = True; world.flush()
    w2 = S.World(data, "http://127.0.0.1:1", "")
    check("quests, experience and the treasury are kept across a restart", w2.inv_json(a)["xp"] == world.inv_json(a)["xp"] and w2.treasury == world.treasury and w2.inv_json(a)["quests"] == world.inv_json(a)["quests"])

    await c.close(); await ex.close()


asyncio.run(main())
_report.done()
