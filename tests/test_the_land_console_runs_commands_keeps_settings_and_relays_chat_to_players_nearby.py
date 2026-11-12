"""
The Land console ("there should be also a console like in minecraft to send commands", "also add configurable setting
along with the console (command line)", operator 2026-11-06):

  1. the world server relays a chat line to every socket watching a plot the sender watches (the sender included) and
     to nobody else; only a signed-in player chats; one line a second; at most 200 characters, control characters out;
  2. the page: "/" opens the console with a command, Enter with chat, Escape closes it; the commands (help, pos, tp,
     fly, settings, set, clear) exist; a line without a slash goes to the server as chat; the help card stays hidden
     while the console is open;
  3. every setting reaches what it names — fov the camera, sens and invert the mouse, grass the meshing, shadows the
     sun, effects the post-processing — is range-checked, and is remembered in this browser;
  4. every console string is in all 17 languages.

Run: python3 tests/test_the_land_console_runs_commands_keeps_settings_and_relays_chat_to_players_nearby.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-console-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, re, sys

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

A, B, C = generate_keydict(), generate_keydict(), generate_keydict()
PNEAR, PFAR = 4995 * 8192 + 3435, 4000 * 8192 + 3000


async def login(c, kd):
    ch = await (await c.get("/land/api/challenge?kind=agent")).json()
    msg = blake2b_hash([S.DOMAIN, S.AGENT_ORIGIN, kd["address"], ch["nonce"], ch["issued"]], 32)
    r = await c.post("/land/api/agent_login", json={"address": kd["address"], "public_key": kd["public_key"],
                                                     "signature": sign(kd["private_key"], unhex(msg)), "nonce": ch["nonce"]})
    return (await r.json())["token"]


async def main():
    data = tempfile.mkdtemp(prefix="nado_land_con_", dir=os.environ["HOME"])
    world = S.World(data, "http://127.0.0.1:1", "")
    app = S.make_app(world, S.Hub(), "https://land.example", "https://wallet.example", secure_cookies=False)
    c = TestClient(TestServer(app)); await c.start_server()
    ta, tb, tc = await login(c, A), await login(c, B), await login(c, C)
    wa, wb, wc = [await c.ws_connect("/land/ws?token=" + t) for t in (ta, tb, tc)]
    wv = await c.ws_connect("/land/ws")                                       # a visitor, not signed in

    async def drain(ws, t=0.4):
        got = []
        try:
            while True:
                got.append(await asyncio.wait_for(ws.receive_json(), t))
        except asyncio.TimeoutError:
            return got
    for ws, plots in ((wa, [PNEAR]), (wb, [PNEAR, PNEAR + 1]), (wc, [PFAR]), (wv, [PNEAR])):
        await ws.send_json({"t": "watch", "plots": plots})
    for ws in (wa, wb, wc, wv):
        await drain(ws)
    chats = lambda ms: [m for m in ms if m.get("t") == "chat"]

    await wa.send_json({"t": "chat", "text": "hello\x07 there " + "x" * 300})
    ga, gb, gc, gv = [chats(await drain(ws)) for ws in (wa, wb, wc, wv)]
    check("a chat line reaches every player watching a plot the sender watches, the sender included",
          len(ga) == 1 and len(gb) == 1 and ga[0]["who"] == A["address"], (ga, gb))
    check("…and nobody watching elsewhere", not gc, gc)
    check("…at most 200 characters, control characters out", gb and len(gb[0]["text"]) <= 200 and "\x07" not in gb[0]["text"]
          and gb[0]["text"].startswith("hello there"), gb)
    await asyncio.sleep(1.05)
    await wa.send_json({"t": "chat", "text": "one"})
    await wa.send_json({"t": "chat", "text": "two"})                       # in the same second
    got = [m["text"] for m in chats(await drain(wb))]
    await drain(wa); await drain(wv)
    check("one line a second", got == ["one"], got)
    await asyncio.sleep(1.05)
    await wa.send_json({"t": "chat", "text": "later"})
    check("…the next second it goes", [m["text"] for m in chats(await drain(wb))] == ["later"])
    await drain(wa); await drain(wv)
    await wv.send_json({"t": "chat", "text": "anon"})
    vr, ar = await drain(wv), await drain(wa)
    check("a visitor who has not signed in cannot chat (and is told so)",
          any(m.get("t") == "chat_ok" and m.get("error") for m in vr) and not chats(ar) and not chats(vr), (vr, ar))
    for ws in (wa, wb, wc, wv):
        await ws.close()
    await c.close()


asyncio.run(main())

# ---- the page ------------------------------------------------------------------------------------------------------
js = open(os.path.join(ROOT, "static", "land.js"), encoding="utf-8").read()
html = open(os.path.join(ROOT, "static", "land.html"), encoding="utf-8").read()
check("/ opens the console with a command, Enter with chat (not over the bag), Escape closes it",
      'e.code === "Slash") { e.preventDefault(); keys.clear(); return conShow(true, "/"); }' in js
      and 'e.code === "NumpadEnter") && $("palette").classList.contains("hidden")) { e.preventDefault(); keys.clear(); return conShow(true, ""); }' in js
      and 'else if (e.key === "Escape") { e.preventDefault(); conShow(false); }' in js and 'id="conIn"' in html)
cmds = js[js.index("const CMDS = {"):js.index("function conRun(")]
# THE PROFILER ("work on performance, take a hint from true wind", operator 2026-11-09): /prof, ` and ?prof=1 open it; it
# times the frame's parts, the 4-a-second tick and the workers' meshes; closed, pt() only calls through
prof = js[js.index("const PROF = {"):js.index("function frame(now)")]
check("the profiler opens with /prof, ` or ?prof=1, and times the frame, the tick and the meshes",
      re.search(r"\n  prof: ", cmds) and 'if (e.code === "Backquote") profToggle();' in js and 'get("prof") === "1") profToggle(true)' in js
      and "if (!PROF.on) return fn();" in prof and all(f'pt("{k}"' in js for k in ("step", "aim", "sky", "render", "chunks", "hud", "mesh"))
      and "profFrame(now, performance.now() - work0);" in js and 'id="prof"' in html)
check("the commands exist: help, pos, tp, fly, settings, set, clear",
      all(re.search(r"\n  %s: " % k, cmds) for k in ("help", "pos", "tp", "fly", "settings", "set", "clear")))
check("a line without a slash goes to the server as chat", 'net.send({ t: "chat", text: text.slice(0, 200) });' in js
      and 'm.t === "chat"' in js)
check("the help card stays hidden while the console is open", 'if (open) $("help").classList.add("hidden");' in js)
# …and it is shown once: closing the console never brings it back (it came back after every chat line, and a phone
# could not put it away at all, operator 2026-11-09); sending a line captures the mouse again, quietly retrying the
# browser's "cannot be acquired immediately" refusal instead of showing it
check("the welcome card is shown once per device: any tap, click or key, or Play, puts it away for good",
      'for (const ev of ["pointerdown", "touchstart", "keydown"]) document.addEventListener(ev, (e) => { if (!(e.target && e.target.closest && e.target.closest("#help"))) away(); }, { capture: true, passive: true });' in js
      and 'welcome.addEventListener("click", () => { away(); if (!touch) lockPointer(); });' in js
      and 'localStorage.setItem(WELCOME_SEEN, "1")' in js and 'if (localStorage.getItem(WELCOME_SEEN)) welcome.classList.add("hidden");' in js
      and '$("help").classList.toggle(' not in js)
check("…sending a line goes back to play, and a refused pointer capture is retried, never shown",
      "conShow(false); conRun(v); if (!touch) lockPointer();" in js and "r.catch(() => setTimeout(" in js and js.count("requestPointerLock()") == 2)
check("every setting reaches what it names",
      "new THREE.PerspectiveCamera(SET.fov," in js and "camera.fov = SET.fov; camera.updateProjectionMatrix()" in js
      and "e.movementX * 0.0024 * SET.sens" in js and "(SET.invert ? -1 : 1)" in js
      and "grass: !!SET.grass" in js and "sun.castShadow = elev > 0.12 && !!SET.shadows" in js
      and "if (!SET.effects ||" in js and "pipeline = buildPipeline();                             // the post-processing" in js
      # (res: the stars' point size follows the resolution too since 3d7b3ea8, #181 item 9 — the line became a block)
      and 'if (k === "res") { renderer.setPixelRatio(basePR() * SET.res / 100);' in js and "viewDist = SET.view;" in js
      and "const sound = new Sound(() => !!SET.sound);" in js)    # sound (#113): the cues read the switch
check("…range-checked and remembered in this browser",
      "v >= SET_RANGE[k][0] && v <= SET_RANGE[k][1]" in js and "localStorage.setItem(LS_SET, JSON.stringify({ ...SET, sv: SET_VER }))" in js
      and "s[k] >= SET_RANGE[k][0] && s[k] <= SET_RANGE[k][1]" in js)
tr = json.load(open(os.path.join(ROOT, "static", "i18n_games", "land.json"), encoding="utf-8"))
keys = set(re.findall(r'T\("(c[A-Z][A-Za-z]+)"', js)) | {"cPlaceholder"}
check(f"every console string ({len(keys)}) is in all 17 languages",
      len(keys) >= 17 and len(tr) == 17 and all(all(l.get("land." + k) for k in keys) for l in tr.values()),
      [(n, k) for n, l in tr.items() for k in keys if not l.get("land." + k)][:6])
_report.done()
