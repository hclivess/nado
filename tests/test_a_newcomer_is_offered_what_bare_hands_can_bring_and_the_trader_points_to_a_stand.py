"""
#165 (playtest 2026-11-11: "Bring 6 × Grain" offered to a level-1 player with empty hands; "Tobin · Trader says one line
and nothing else — no trade, no pointer to the stands"). The world server's own rules (scripts/land_server.py):
  * hand_bring(): the bring templates in the quest book's own `hand` list (land-recipes.json quests.hand) — sticks,
    stone, fibre, berries, flax; grain, clay, cobble and planks not — and every listed item comes off a breaking rule
    that needs no tool and no tool class (the list stays honest against the rules);
  * a level-1 player's offers are all from that list and none is a hunt; from level 2 the whole book is open;
  * the trader's word: with a trading stand within the market's reach, talk() says how far and on what bearing
    (0° north, 90° east); with none, that none is built yet; the elder says neither;
  * the page shows the trader's word over his greeting (static/land.js renderNpc), in all 17 languages;
  * a bring quest's line says where the item is found by hand — the first no-tool breaking rule's block ("Bring 6 ×
    Berries — found as Berry bush"), and every hand item has such a block.
Run: python3 tests/test_a_newcomer_is_offered_what_bare_hands_can_bring_and_the_trader_points_to_a_stand.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-offers-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import importlib.util, json, math, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
import _harness
_report = _harness.Report()
check = _report.check

data = os.path.join(os.environ["HOME"], "land")
w = S.World(data, "http://127.0.0.1:1", "")                   # offline, no oracle needed: offers and talk are pure bookkeeping
WHO = "ndoOFFR" + "O" * 41
Q = S.RULES["quests"]

# 1. the bare-hand list
hb = w.hand_bring()
names = {t[0] for t in hb}
check("hand_bring is the quest book's hand list: sticks, stone, fibre, berries and flax", names == {"sticks", "stone", "fiber", "berries", "flax"}, sorted(names))
check("…and grain, clay, cobble and planks (a field, a shovel, a pick, an axe) are not", not ({"grain", "clay", "cobble", "planks"} & names), sorted(names))
check("…every one of them is a template of the quest book", all(t in Q["bring"] for t in hb))
B = S.RULES["breaking"]
by_hand = {y[0] for r in B.values() if isinstance(r, dict) and not r.get("needs") and not r.get("class") for y in r.get("yields", []) if isinstance(y, list)}
check("…and every one comes off a breaking rule that needs no tool and no tool class (the list is honest against the rules)", names <= by_hand, sorted(names - by_hand))

# 2. a level-1 player's offers, many times over (the draw is random)
pl = w.player(WHO)
elder = next(n["id"] for n in Q["npcs"] if n.get("gives"))
bad = []
for _ in range(40):
    pl["offered"] = {}
    for q in w.offered(WHO, elder):
        if q["kind"] == "hunt" or (q["kind"] == "bring" and q["item"] not in names):
            bad.append(q)
check("a level-1 player is offered only what bare hands bring, and never a hunt (120 offers drawn)", not bad, bad[:3])
pl["xp"] = Q["level_xp"] * 3                                     # level 3
seen = set()
for _ in range(60):
    pl["offered"] = {}
    for q in w.offered(WHO, elder):
        seen.add(q["kind"] if q["kind"] != "bring" else q["item"])
check("from level 2 the whole book is open again (a hunt or a tool's item turns up)", "hunt" in seen or any(i in seen for i in ("grain", "cobble", "planks", "wood")), sorted(seen))
pl["xp"] = 0

# 3. the trader's word
trader = next(n for n in Q["npcs"] if n["role"] == "trader")
at = trader["at"]
pos = [at[0], at[1] + 1.0, at[2], 137.0, 0.0]
r, err = w.talk(WHO, trader["id"], pos)
check("the trader, with no stand built, says so", not err and r.get("stand") is None and "stand" in r, (r, err))
p = S.plot_of(at[0], int(at[1]), int(at[2]))
rec = w.plot(p)
sx, sz = (int(at[1]) - (p % S.FACE_N) * S.PLOT) * 100 + 600, (int(at[2]) - ((p // S.FACE_N) % S.FACE_N) * S.PLOT) * 100
rec["boxes"].append([sx, sz, 13700, 100, 50, 120, S.STAND if hasattr(S, "STAND") else 55])
r2, err2 = w.talk(WHO, trader["id"], pos)
check("with a stand six metres east, he says how far and on what bearing (0° north, 90° east)",
      not err2 and r2.get("stand") and 4 <= r2["stand"]["m"] <= 8 and 60 <= r2["stand"]["bearing"] <= 120, (r2.get("stand"), err2))
e_at = next(n for n in Q["npcs"] if n["role"] == "elder")["at"]
r3, _ = w.talk(WHO, elder, [e_at[0], e_at[1] + 1.0, e_at[2], 137.0, 0.0])
check("the elder says nothing of stands", "stand" not in r3)

# 4. the page and the languages
page = open(os.path.join(ROOT, "static", "land.js"), encoding="utf-8").read()
check("the page puts the trader's word over his greeting", 'm.stand === undefined ? ""' in page and 'T("traderStand"' in page and 'T("traderNoStand"' in page)
I = json.load(open(os.path.join(ROOT, "static", "i18n_games", "land.json"), encoding="utf-8"))
check("both lines are in all 17 languages with their placeholders", len(I) == 17 and all("{m}" in I[l]["land.traderStand"] and "{b}" in I[l]["land.traderStand"] and len(I[l]["land.traderNoStand"]) > 10 for l in I))
check("a bring line names where the item is found by hand (gatheredFrom: the first no-tool, no-class rule's block)",
      "function gatheredFrom(item)" in page and 'T("qBringFrom", "Bring {n} × {i} — found as {b}"' in page and "r.needs || r.class" in page)
check("…and every hand item has such a block", all(any(isinstance(r, dict) and not r.get("needs") and not r.get("class") and any(isinstance(y, list) and y[0] == i for y in r.get("yields", [])) for r in B.values()) for i in names), sorted(names))
check("the bring-from line is in all 17 languages with its three placeholders", all(all(ph in I[l]["land.qBringFrom"] for ph in ("{n}", "{i}", "{b}")) for l in I))
_report.done()
