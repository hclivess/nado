"""Every game the faucet PAYS must advertise airdrop play, and nothing else may claim it.

The apps page badge ("🪂 airdrop play") is the only place a player learns a game has free play with real
prizes. It is set by hand on each tile (`faucet:true`) while the payouts are driven by a separate list in
_faucet_rewards.py, so the two drift silently: a game can be paid prizes nobody is told about, or promise
prizes it will never receive. Autogame was the first case — enrolled as idx 13 with a working daily and a
replay oracle, and no badge on its tile.

Run: python3 tests/test_faucet_badges.py
"""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_fails = []
def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  — " + detail) if detail and not cond else ""))
    if not cond: _fails.append(name)

src = open(os.path.join(ROOT, "_faucet_rewards.py"), encoding="utf8").read()
block = src[src.index("GAMES = ["):src.index("]", src.index("GAMES = ["))]
# (idx, cid, kind) plus the trailing comment naming the game
enrolled = {}
for m in re.finditer(r'\(\s*(\d+),\s*"([0-9a-f]+)",\s*"([^"]+)"\s*\),?\s*#\s*([^\s(]+)', block):
    enrolled[int(m.group(1))] = (m.group(4).lower().replace("-", ""), m.group(3))

html = open(os.path.join(ROOT, "website", "apps.html"), encoding="utf8").read()
badged, tiles = set(), {}
for body, url in re.findall(r'\{([^{}]*?url:\s*"([^"]+)"[^{}]*)\}', html):
    host = url.split("//")[1].split(".")[0].lower()
    tiles[host] = body
    if "faucet:true" in body:
        badged.add(host)

check(f"the distributor enrolls games ({len(enrolled)})", len(enrolled) > 0)
check(f"the apps page badges games ({len(badged)})", len(badged) > 0)

# host names differ from the code names in a couple of places; map only where they genuinely differ
ALIAS = {"connect": "connect4", "tictactoe": "tictactoe", "ticta ctoe": "tictactoe"}
unadvertised = []
for idx, (name, kind) in sorted(enrolled.items()):
    host = ALIAS.get(name, name)
    hit = host in badged or any(h.startswith(host) or host.startswith(h) for h in badged)
    if not hit:
        unadvertised.append(f"idx {idx} {name} ({kind})")
check("every PAID game advertises airdrop play on the apps page",
      not unadvertised, "paid but not advertised: " + ", ".join(unadvertised))

names = {ALIAS.get(n, n) for n, _ in enrolled.values()}
overclaimed = [h for h in sorted(badged)
               if not any(h.startswith(n) or n.startswith(h) for n in names)]
check("nothing claims airdrop play without being enrolled for payouts",
      not overclaimed, "badged but unpaid: " + ", ".join(overclaimed))

check("the badge counts match exactly", len(badged) == len(enrolled),
      f"{len(badged)} badged vs {len(enrolled)} enrolled")

print()
print("ALL FAUCET-BADGE CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
sys.exit(1 if _fails else 0)
