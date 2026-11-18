"""
Wool in Land (#128, "Wool: needs an animal source (sheep)"):

  1. a wild sheep lives in the grassland — a primitive, self-shedding sheep as the Soay of St Kilda — and its rules carry
     their sources (body mass and fleece from breed registers, speed scaled from Garland 1983 as the deer's is): it runs
     slower than a deer, never charges and fights back with nothing;
  2. through the world server's own strike: a sheep hunted down gives its meat and its wool to any hunter — the wool is
     plucked by hand, no knife — and its hide only to one with a knife, as every hide is;
  3. the wool is spun (a spindle) into yarn, woven (a loom) into woollen cloth, and sewn (a needle) into a woollen cloak
     and a woollen cap, each worn in its one place, all reachable from what a player can gather and hunt;
  4. the page draws a sheep (brown fleece, pale belly, curled horns), names it, colours the woollen clothes, and its
     wardrobe hint names wool — all in 17 languages.

Run: python3 tests/test_a_wild_sheep_gives_wool_that_is_spun_woven_and_sewn_into_clothes.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-sheep-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import importlib.util, json, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
import _harness
_report = _harness.Report()
check = _report.check
R = json.load(open(os.path.join(ROOT, "static", "land-recipes.json")))
HN = R["hunting"]
SH = HN["species"].get("sheep", {})

# 1. the animal and its sources
check("a wild sheep lives in the grassland", "grass" in SH.get("biomes", []))
about = HN.get("about_sheep", "")
check("its rules carry their sources: the Soay, its body mass and fleece, and the speed's scaling from Garland 1983",
      all(x in about for x in ("Soay", "23-36 kg", "1.5-2.25 kg", "Garland 1983", "48 km/h", "64 km/h")), about[:200])
check("…its speed is the deer's scaled by a wild sheep's 48 km/h against a deer's 64 (4.0 x 48/64 = 3.0)",
      abs(SH.get("speed", 0) - HN["species"]["deer"]["speed"] * 48 / 64) < 1e-9, SH.get("speed"))
check("it never charges and fights back with nothing", SH.get("angry") == 0 and SH.get("damage") == 0)
check("…and it gives meat, a hide and 2 wool (a 1.5-2.25 kg fleece)", dict(SH.get("drops", [])) == {"meat": 2, "hide": 1, "wool": 2})

# 2. hunted down, through the world server's own strike
w = S.World(os.path.join(os.environ["HOME"], "land"), "http://127.0.0.1:1", "")
A = "ndoSHEEP" + "A" * 40
pl = w.player(A)
def sheep():
    w.animal_seq += 1
    a = {"id": w.animal_seq, "kind": "sheep", "face": 0, "u": 10.0, "v": 10.0, "h": 100.0, "yaw": 0.0, "hp": 1, "go": 1e18, "flee": 0, "angry": False}
    w.animals[a["id"]] = a
    return a
r = w._strike(A, pl, sheep(), 5)
check("a sheep hunted down without a knife gives its meat and its wool (plucked by hand)", r["killed"] == "sheep"
      and pl["items"].get("wool") == 2 and pl["items"].get("meat") == 2 and not pl["items"].get("hide"), (r, pl["items"]))
pl["tools"].append("knife")
r = w._strike(A, pl, sheep(), 5)
check("…and its hide too to a hunter with a knife", pl["items"].get("hide") == 1 and pl["items"].get("wool") == 4, pl["items"])

# 3. spun, woven, sewn — reachable from what can be gathered and hunted
have, tools, st = set(), set(), set()
cls = lambda c: any(t == c or R["tools"][t].get("class") == c for t in tools)
for sp in HN["species"].values():
    for i, _ in sp["drops"]:
        have.add(i)
grew = True
while grew:
    grew = False
    for b in R["breaking"].values():
        if not isinstance(b, dict) or not b.get("yields") or (b.get("needs") and not cls(b["needs"])):
            continue
        for i, _ in b["yields"] + ([b["bonus"]] if b.get("bonus") else []):
            if i not in have:
                have.add(i); grew = True
    for rc in R["recipes"]:
        if not isinstance(rc, dict) or not all(i in have for i, _ in rc["uses"]) or not all(x in st or cls(x) for x in rc.get("with", [])):
            continue
        for i, _ in rc["makes"]:
            box = tools if i in R["tools"] else st if i in R["stations"] else have
            if i not in box:
                box.add(i); grew = True
rec = {rc["id"]: rc for rc in R["recipes"] if isinstance(rc, dict)}
check("wool is spun into yarn with a spindle", rec["yarn"]["uses"] == [["wool", 1]] and rec["yarn"]["with"] == ["spindle"])
check("yarn is woven into woollen cloth on a loom", rec["wool_cloth"]["uses"] == [["yarn", 6]] and rec["wool_cloth"]["with"] == ["loom"])
check("woollen cloth is sewn with a needle into a cloak and a cap",
      all(rec[g]["with"] == ["needle"] and dict(rec[g]["uses"]).get("wool_cloth") for g in ("woollen_cloak", "woollen_cap")))
check("…all of it reachable from what a player gathers and hunts", {"yarn", "wool_cloth", "woollen_cloak", "woollen_cap"} <= have, sorted({"yarn", "wool_cloth", "woollen_cloak", "woollen_cap"} - have))
check("each garment is worn in its one place", R["items"]["woollen_cloak"].get("wear") == "back" and R["items"]["woollen_cap"].get("wear") == "head")
pl["items"]["woollen_cap"] = 1
check("…and goes on there through the world server", w.wear(A, "head", "woollen_cap") is None and pl["worn"]["head"] == "woollen_cap")

# 4. the page
page = open(os.path.join(ROOT, "static", "land.js"), encoding="utf-8").read()
check("the page draws a sheep: brown fleece, a pale belly, curled horns",
      "sheep: { body: 0x5e4630, belly: 0xd9c9ad," in page and 'if (kind === "sheep") for (const s of [-1, 1]) {' in page and "TorusGeometry" in page)
check("…names it", 'rabbit: "rabbit", sheep: "sheep" }[k]' in page)
fn = page.split("const SKIN = ", 1)[1].split("function avatar(", 1)[0]
js = """
class Color { setHSL(h, s, l) { this.v = 1; return this; } getHex() { return this.v; } }
const THREE = { Color };
const SKIN = %s
console.log(JSON.stringify({ WEAR, on: lookColours("x", { worn: { back: "woollen_cloak", head: "woollen_cap" } }) }));
""" % fn
out = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60)
J = json.loads(out.stdout.strip().splitlines()[-1]) if out.stdout.strip() else {}
check("the woollen clothes have their colour and are drawn in it",
      J.get("on", {}).get("cloak") == J.get("WEAR", {}).get("woollen_cloak") and J.get("on", {}).get("cap") == J.get("WEAR", {}).get("woollen_cap") and J.get("on", {}).get("cap"), (J, out.stderr[-200:]))
check("the wardrobe hint names wool", "Sew clothes from linen, wool or leather with a needle" in page)
L = json.load(open(os.path.join(ROOT, "static", "i18n_games", "land.json"), encoding="utf-8"))
keys = ["land.a.sheep", "land.i.wool", "land.i.yarn", "land.i.wool_cloth", "land.i.woollen_cloak", "land.i.woollen_cap"]
check("the sheep, wool, yarn, cloth and both garments are named in all 17 languages", len(L) == 17 and all(L[x].get(k) for x in L for k in keys),
      [(x, k) for x in L for k in keys if not L[x].get(k)])
check("…and the wardrobe hint names wool in English", "wool" in L["en"]["land.wHint"])

print("\n" + ("ALL PASS" if not _report.fails else f"{_report.fails} FAILED"))
sys.exit(1 if _report.fails else 0)
