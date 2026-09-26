"""The English game strings call a block producer a COLLECTOR, and a produced block a COLLECTED one
(static/i18n_games/*.json — the source merge_games.py bakes into i18n.js).

The rename was once made only in i18n.js; the next redeploy regenerated the games' block from these sources and
brought "no single miner can grind it" and "a block that hasn't been mined yet" back (2026-09-25). Pins: no English game
source says miner/mined/mining, except where the game itself digs (the pets' "Miner" trade and a pet that mines).

Run: python3 tests/test_block_producer_is_a_collector.py
"""
import os, re, sys, json, glob
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_CONTENT = {"pets.tradeMiner", "pets.bagNote"}          # a pet's trade and a pet that digs — not block production
bad = []
for f in sorted(glob.glob(os.path.join(ROOT, "static", "i18n_games", "*.json"))):
    for k, v in (json.load(open(f)).get("en") or {}).items():
        if k not in GAME_CONTENT and re.search(r"\bminers?\b|\bmined\b|\bmining\b", v, re.I):
            bad.append(f"{os.path.basename(f)}:{k}")
print(("PASS  " if not bad else "FAIL  ") + "no English game source calls a block producer a miner" + ("" if not bad else f"  {bad}"))
sys.exit(1 if bad else 0)
