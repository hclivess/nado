"""
Clothes in Land (#111, "the crafted items should be what changes how you look"):

  1. a needle and every garment (shirt, trousers, cap, cloak) are reachable from bare hands — flax, thread, linen, a
     needle — and each garment names the one place it is worn;
  2. through the world server's own methods: a garment goes ON from the bag (it leaves the bag) and comes OFF back into
     it; nobody wears what they lack or wears a garment in the wrong place; a second garment in a slot sends the first
     back to the bag; skin and hair are chosen from the palettes and nothing else; all of it survives a restart;
  3. players nearby are sent each other's look with their position, and the page dresses them in it (and re-dresses
     them when it changes); the 3D body and the wardrobe's figure take their colours from one function;
  4. the wardrobe opens with V and from the bag, and its strings are in 17 languages.

Run: python3 tests/test_clothes_are_sewn_from_linen_worn_from_the_bag_and_seen_by_players_nearby.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-clothes-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
import _harness
_report = _harness.Report()
check = _report.check
R = json.load(open(os.path.join(ROOT, "static", "land-recipes.json")))
GARMENTS = {"linen_shirt": "body", "linen_trousers": "legs", "linen_cap": "head", "linen_cloak": "back"}

# 1. reachable from bare hands (the breaking table's yields, then every recipe the player can make, to a fixpoint)
have, tools, st = set(), set(), set()
cls = lambda c: any(t == c or R["tools"][t].get("class") == c for t in tools)
grew = True
while grew:
    grew = False
    for r in R["breaking"].values():
        if not isinstance(r, dict) or not r.get("yields") or (r.get("needs") and not cls(r["needs"])):
            continue
        for i, _ in r["yields"] + ([r["bonus"]] if r.get("bonus") else []):
            if i not in have:
                have.add(i); grew = True
    for r in R["recipes"]:
        if not isinstance(r, dict) or not all(i in have for i, _ in r["uses"]) or not all(w in st or cls(w) for w in r.get("with", [])):
            continue
        for i, _ in r["makes"]:
            box = tools if i in R["tools"] else st if i in R["stations"] else have
            if i not in box:
                box.add(i); grew = True
check("a needle is made from bare hands", "needle" in tools and R["tools"]["needle"]["class"] == "needle")
check("every garment is sewn from linen with a needle, reachable from bare hands",
      all(g in have for g in GARMENTS) and all(any(r["makes"][0][0] == g and "needle" in r.get("with", []) and any(i == "linen" for i, _ in r["uses"])
                                                  for r in R["recipes"]) for g in GARMENTS), sorted(set(GARMENTS) - have))
check("…each naming the one place it is worn", all(R["items"][g].get("wear") == s and s in S.WEAR_SLOTS for g, s in GARMENTS.items()))

# 2. wearing, through the world server
A, Bp = "ndoWEAR" + "A" * 41, "ndoWEAR" + "B" * 41
data = os.path.join(os.environ["HOME"], "land")
w = S.World(data, "http://127.0.0.1:1", "")
pa = w.player(A)
pa["items"].update({"linen_shirt": 2, "linen_cap": 1, "linen_trousers": 1})
check("a shirt goes on from the bag", w.wear(A, "body", "linen_shirt") is None and pa["worn"] == {"body": "linen_shirt"} and pa["items"]["linen_shirt"] == 1)
check("nobody wears what they lack", w.wear(A, "back", "linen_cloak") and "linen_cloak" not in pa["worn"].values())
check("a garment is worn only in its place", w.wear(A, "legs", "linen_cap") and pa["items"]["linen_cap"] == 1)
check("…and only in a place there is", w.wear(A, "feet", "linen_cap") is not None)
pa["items"]["linen_shirt"] = 1
w.player(A)["worn"]["body"] = "linen_shirt"
before = pa["items"]["linen_shirt"]
check("a second garment in a slot sends the first back to the bag",
      w.wear(A, "body", "linen_shirt") is None and pa["items"]["linen_shirt"] == before and pa["worn"]["body"] == "linen_shirt")
w.wear(A, "head", "linen_cap"); w.wear(A, "legs", "linen_trousers")
check("taking off puts it back in the bag", w.wear(A, "legs", None) is None and "legs" not in pa["worn"] and pa["items"]["linen_trousers"] == 1)
check("skin and hair come from the palettes", w.set_look(A, 3, 5) is None and pa["look"] == {"skin": 3, "hair": 5, "body": 0, "face": 0})
check("…and nothing else", w.set_look(A, S.LOOK_SKIN, 0) and w.set_look(A, -1, 0) and w.set_look(A, 1.5, 0) and w.set_look(A, True, 0) and pa["look"]["skin"] == 3)
# body type and a kawaii face ("let users customize the basics like gender and face and hair color", operator 2026-11-09)
check("a body type and a face are chosen too, and a bright hair colour", w.set_look(A, 3, 9, 1, 4) is None and pa["look"] == {"skin": 3, "hair": 9, "body": 1, "face": 4})
check("…from their ranges only", w.set_look(A, 3, 9, S.LOOK_BODY, 0) and w.set_look(A, 3, 9, 0, S.LOOK_FACE) and w.set_look(A, 3, 9, -1, 0) and pa["look"]["body"] == 1)
check("…and an older page sending skin and hair only keeps the body and face", w.set_look(A, 3, 5) is None and pa["look"] == {"skin": 3, "hair": 5, "body": 1, "face": 4})
check("the bag the page is sent carries what is worn and the look",
      w.inv_json(A)["worn"] == {"body": "linen_shirt", "head": "linen_cap"} and w.inv_json(A)["look"] == {"skin": 3, "hair": 5, "body": 1, "face": 4})
w.flush()
w2 = S.World(data, "http://127.0.0.1:1", "")
check("what is worn and the look survive a restart", w2.look_of(A) == {"worn": {"body": "linen_shirt", "head": "linen_cap"}, "skin": 3, "hair": 5, "body": 1, "face": 4}, w2.look_of(A))


# 3. players nearby are sent each other's look
class Sock:
    def __init__(self): self.sent = []
    async def send_json(self, m): self.sent.append(m)


hub = S.Hub()
sa, sb = Sock(), Sock()
hub.socks = {sa: {"id": 1, "who": A, "pos": [0, 10.0, 10.0, 100.0, 0.0]}, sb: {"id": 2, "who": Bp, "pos": [0, 12.0, 11.0, 100.0, 0.0]}}
asyncio.run(hub.positions(w))
got = sb.sent[-1]["list"][0] if sb.sent else {}
check("a player near you comes with their look", got.get("id") == 1 and got.get("look") == w.look_of(A), got)

page = open(os.path.join(ROOT, "static", "land.js"), encoding="utf-8").read()
html = open(os.path.join(ROOT, "static", "land.html"), encoding="utf-8").read()
check("the page dresses players in their look, and again when it changes",
      'r = { mesh: avatar(o.who || o.id, o.look, "p:" + o.id), who: o.who, sig }' in page and "if (r && r.sig !== sig) { scene.remove(r.mesh); dropFig(r); r = null; }" in page)
fn = page.split("const SKIN = ", 1)[1].split("function avatar(", 1)[0]
js = """
class Color { setHSL(h, s, l) { this.v = Math.round(h * 1000) * 7 + 1; return this; } getHex() { return this.v; } }
const THREE = { Color };
const SKIN = %s
console.log(JSON.stringify({ skin: SKIN.length, hair: HAIR.length, bodies: BODIES, faces: FACES, bare: lookColours("x", {}), dressed: lookColours("x", { skin: 2, hair: 4, worn: { body: "linen_shirt", legs: "linen_trousers", head: "linen_cap", back: "linen_cloak" } }), WEAR, SKIN, HAIR }));
""" % fn
r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60)
J = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
check("the page's palettes are the server's", J.get("skin") == S.LOOK_SKIN and J.get("hair") == S.LOOK_HAIR
      and J.get("bodies") == S.LOOK_BODY and J.get("faces") == S.LOOK_FACE, (J, r.stderr[-300:]))
# not blocks ("rework characters to not be fucking blocks", operator 2026-11-09): the body is round — capsules and spheres
# (the avatar's OWN body: up to the next function. The slice once ran on to faceCanvas and, when the animals and the
# arrow were written between the two, judged an arrow's box fletching as a player's body — #189.)
_a0 = page.index("function avatar(")
av = page[_a0:page.index("\nfunction ", _a0 + 1)]
check("the avatar's own body is what is judged", 400 < len(av) < 12000 and "function animal" not in av, len(av))
# the body is a person (#172, 2026-11-12): the MakeHuman figure of land-human.js, registered with the HumanView at its
# first placement with the look's colours; no capsule, sphere or box body is built here any more
check("a player is a MakeHuman body drawn by the HumanView, not capsules, spheres or boxes",
      'import { HumanView } from "./land-human.js";' in page and "Object.assign(g.userData, { fig: id, look, col: lookColours(seed, look) });" in av
      and "CapsuleGeometry" not in av and "SphereGeometry" not in av and "BoxGeometry" not in av
      and "if (human && !human.figs.has(u.fig)) human.add(u.fig, u.look, u.col);" in page)
hd = open(os.path.join(ROOT, "static", "land-human-data.js"), encoding="utf-8").read()
check("the page draws the body type (body 1 the female build) and the wardrobe chooses body and face",
      "export const variantOf = (look) => (look && look.body === 1 ? 1 : look && look.body === 2 ? 2 : 0);" in hd
      and "data-body=" in page and "data-face=" in page and 'body: look.body, face: look.face' in page)
d, b, W = J.get("dressed", {}), J.get("bare", {}), J.get("WEAR", {})
check("what you wear is what is drawn: each garment's colour on its part, the chosen skin and hair",
      d.get("top") == W.get("linen_shirt") and d.get("legs") == W.get("linen_trousers") and d.get("cap") == W.get("linen_cap")
      and d.get("cloak") == W.get("linen_cloak") and d.get("skin") == J["SKIN"][2] and d.get("hair") == J["HAIR"][4], J)
check("…and unclothed is plain: no cap, no cloak, an undershirt", b.get("cap") is None and b.get("cloak") is None and b.get("top") not in W.values(), b)
check("…every wearable has a colour", all(g in W for g in GARMENTS))
check("the 3D body and the wardrobe figure share one colouring", "col: lookColours(seed, look)" in av
      and "c = lookColours(net.me || \"\", look)" in page
      and "put(out, 0, c.skin, 0.6); put(out, 1, top, 0.55); put(out, 2, c.legs, 0.6);" in hd)   # (the look's colours onto the body's regions)
# 4
check("the wardrobe opens with V and from the bag", 'if (e.code === "KeyV") wardrobe(' in page and 'id="wardOpen"' in html and 'id="wardPanel"' in html
      and '<kbd>V</kbd>' in html)
check("…and sends the world server's own wear and look", 'send({ t: "wear", slot: b.dataset.slot, item: b.dataset.wear })' in page and 'send(Object.assign({ t: "look",' in page)
srv = open(os.path.join(ROOT, "scripts", "land_server.py"), encoding="utf-8").read()
check("the world server takes wear and look only from a signed-in player", 'elif t in ("wear", "look"):' in srv and "await hub.positions(world)" in srv)
tr = json.load(open(os.path.join(ROOT, "static", "i18n_games", "land.json"), encoding="utf-8"))
keys = ["land.i." + g for g in GARMENTS] + ["land.t.needle", "land.wardTitle", "land.kWard", "land.wSkin", "land.wHair", "land.wClothes",
        "land.wTakeOff", "land.wNothing", "land.wWear", "land.wHint"] + ["land.slot." + s for s in S.WEAR_SLOTS]
check("its strings are in 17 languages, the garment's name kept in Wear {i}",
      len(tr) == 17 and all(all(l.get(k) for k in keys) for l in tr.values()) and all("{i}" in l["land.wWear"] for l in tr.values()))
_report.done()
