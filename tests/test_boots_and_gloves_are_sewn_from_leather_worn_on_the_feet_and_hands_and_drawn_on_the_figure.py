"""
Boots and gloves in Land (#128, "more garments: boots, gloves"):

  1. leather boots and leather gloves are sewn from leather with linen thread and a needle; leather is the hunt's hide
     (every animal hunted drops one) tanned with lime on a tanning rack; each names the one place it is worn — the new
     feet and hands places, which the world server and the page both know;
  2. through the world server's own methods: boots go on the feet and gloves on the hands, from the bag and back into
     it; neither goes anywhere else; what is worn survives a restart;
  3. the page draws them: lookColours gives boots and gloves their colour (none when nothing is worn there), the 3D
     figure lays a boot over each foot and a glove over each hand, and the wardrobe's flat figure shows them too;
  4. their names and the two places are in all 17 languages, and the wardrobe's hint names leather beside linen.

Run: python3 tests/test_boots_and_gloves_are_sewn_from_leather_worn_on_the_feet_and_hands_and_drawn_on_the_figure.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-boots-")
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
NEW = {"leather_boots": "feet", "leather_gloves": "hands"}

# 1. what they are made of, and where they go
rec = {r["id"]: r for r in R["recipes"] if isinstance(r, dict)}
for g in NEW:
    r = rec.get(g)
    check(f"{g} is sewn from leather and linen thread with a needle",
          r is not None and r["makes"] == [[g, 1]] and dict(r["uses"]).get("leather", 0) >= 1 and dict(r["uses"]).get("thread", 0) >= 1
          and r.get("with") == ["needle"], r)
check("leather is the hunt's hide tanned with lime on a tanning rack",
      any(dict(r["uses"]) == {"hide": 1, "lime": 1} and r["makes"] == [["leather", 1]] and r.get("with") == ["tanning_rack"] for r in R["recipes"]))
check("…and every animal that can be hunted drops a hide",
      all(dict(sp["drops"]).get("hide", 0) >= 1 for sp in R["hunting"]["species"].values()) and len(R["hunting"]["species"]) >= 1)
check("each names the one place it is worn, a place the world server knows",
      all(R["items"][g].get("wear") == s and s in S.WEAR_SLOTS for g, s in NEW.items()))
page = open(os.path.join(ROOT, "static", "land.js"), encoding="utf-8").read()
check("the page knows the same places as the world server",
      'const WEAR_SLOTS = ["head", "body", "legs", "back", "feet", "hands"];' in page and S.WEAR_SLOTS == ("head", "body", "legs", "back", "feet", "hands"))

# 2. wearing, through the world server
A = "ndoBOOT" + "A" * 41
data = os.path.join(os.environ["HOME"], "land")
w = S.World(data, "http://127.0.0.1:1", "")
pa = w.player(A)
pa["items"].update({"leather_boots": 1, "leather_gloves": 1})
check("boots go on the feet from the bag", w.wear(A, "feet", "leather_boots") is None and pa["worn"].get("feet") == "leather_boots"
      and pa["items"]["leather_boots"] == 0)
check("gloves go on the hands from the bag", w.wear(A, "hands", "leather_gloves") is None and pa["worn"].get("hands") == "leather_gloves"
      and pa["items"]["leather_gloves"] == 0)
pa["items"]["leather_boots"] = 1
check("boots are worn nowhere else", w.wear(A, "hands", "leather_boots") is not None and w.wear(A, "head", "leather_boots") is not None
      and pa["items"]["leather_boots"] == 1 and pa["worn"]["hands"] == "leather_gloves")
check("…nor gloves on the feet", w.wear(A, "feet", "leather_gloves") is not None)
w.flush()
w2 = S.World(data, "http://127.0.0.1:1", "")
check("what is worn survives a restart", w2.look_of(A).get("worn") == {"feet": "leather_boots", "hands": "leather_gloves"}, w2.look_of(A))
check("taking them off puts them back in the bag", w.wear(A, "hands", None) is None and "hands" not in pa["worn"] and pa["items"]["leather_gloves"] == 1)

# 3. drawn on the figure
fn = page.split("const SKIN = ", 1)[1].split("function avatar(", 1)[0]
js = """
class Color { setHSL(h, s, l) { this.v = Math.round(h * 1000) * 7 + 1; return this; } getHex() { return this.v; } }
const THREE = { Color };
const SKIN = %s
console.log(JSON.stringify({ WEAR, bare: lookColours("x", {}), shod: lookColours("x", { worn: { feet: "leather_boots", hands: "leather_gloves" } }) }));
""" % fn
r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60)
J = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
Wc, shod, bare = J.get("WEAR", {}), J.get("shod", {}), J.get("bare", {})
check("each has its own colour", all(isinstance(Wc.get(g), int) for g in NEW) and Wc.get("leather_boots") != Wc.get("leather_gloves"), (J, r.stderr[-300:]))
check("worn, they are drawn in their colour", shod.get("boots") == Wc.get("leather_boots") and shod.get("gloves") == Wc.get("leather_gloves"), shod)
check("…and nothing is drawn where nothing is worn", bare.get("boots") is None and bare.get("gloves") is None, bare)
_a0 = page.index("function avatar(")
av = page[_a0:page.index("\nfunction ", _a0 + 1)]
check("the 3D figure lays a boot over each foot and a glove over each hand",
      "if (c.boots != null) for (const x of [-0.13, 0.13]) box(" in av and "c.boots);" in av
      and "if (c.gloves != null) for (const x of [-0.37, 0.37]) box(" in av and "c.gloves);" in av)
check("the wardrobe's flat figure shows them too", "c.gloves ?? c.skin" in page and "c.boots ?? 0x3a2e2a" in page)

# 4. in every language
L = json.load(open(os.path.join(ROOT, "static", "i18n_games", "land.json"), encoding="utf-8"))
keys = ["land.i.leather_boots", "land.i.leather_gloves", "land.slot.feet", "land.slot.hands"]
check("their names and the two places are in all 17 languages", len(L) == 17 and all(L[lang].get(k) for lang in L for k in keys),
      [(lang, k) for lang in L for k in keys if not L[lang].get(k)])
check("…the feet are not called what the legs are, in any language",
      all(L[lang]["land.slot.feet"] != L[lang]["land.slot.legs"] for lang in L))
check("the wardrobe's hint names leather beside linen", "Sew clothes from linen or leather with a needle" in page
      and "linen or leather" in L["en"]["land.wHint"])

print("\n" + ("ALL PASS" if not _report.fails else f"{_report.fails} FAILED"))
sys.exit(1 if _report.fails else 0)
