"""
Game storage-field layout guard — two field constants in one contract must never share a field number
when they are keyed by DIFFERENT things.

A zkVM game addresses storage as `field * 2**32 + key`. So a field number is only half the address: two
constants may safely share one ONLY if they also share a key space. The daily-board family (E_DAY, E_ADDR,
E_SCORE, E_N, E_TS, ELIST) is keyed by APPEND-LOG ENTRY ID — 0, 1, 2, … from the entry counter. The daily
anchor family (A_H, A_V, DLIST) is keyed by UTC DAY INDEX — floor(unix_seconds / 86400), which is ~20,662
today and rises by one a day. Put one of each on the same field and they collide the moment an entry id
reaches a live day index: silent cross-corruption of a posted score's timestamp and that day's randomness
anchor, with nothing to see until it happens.

hexholm shipped exactly that (E_TS = A_H = 54), while every sibling happened to keep them apart — hamster
54/70, autogame 204/240, scrapline 65/66, battleship 1014/1050. "Every other game got it right" is not a
guarantee; this makes it one.

Run: python3 tests/test_game_field_layout.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import importlib

GAMES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "execnode", "games")
NOT_A_GAME = {"deploy", "redeploy"}

ENTRY_KEYED = re.compile(r"^(E_[A-Z0-9_]+|ELIST)$")     # keyed by append-log entry id
DAY_KEYED = re.compile(r"^(A_[A-Z0-9_]+|DLIST)$")       # keyed by UTC day index


def main():
    games = sorted(f[:-3] for f in os.listdir(GAMES_DIR)
                   if f.endswith(".py") and not f.startswith("_") and f[:-3] not in NOT_A_GAME)
    fails = 0
    checked = 0
    for g in games:
        mod = importlib.import_module(f"execnode.games.{g}")
        by_field = {}
        for name in dir(mod):
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
                continue
            value = getattr(mod, name)
            if not isinstance(value, int) or not 0 < value < 100000:
                continue
            if ENTRY_KEYED.match(name) or DAY_KEYED.match(name):
                by_field.setdefault(value, []).append(name)
        for field, names in sorted(by_field.items()):
            entry = sorted(n for n in names if ENTRY_KEYED.match(n))
            day = sorted(n for n in names if DAY_KEYED.match(n))
            checked += 1
            if entry and day:
                fails += 1
                print(f"FAIL  {g}: field {field} is shared by entry-keyed {entry} and day-keyed {day} — "
                      f"they collide once an entry id reaches a live UTC day index")
    if fails:
        print(f"\n{fails} FAILED")
        return 1
    print(f"PASS  no entry/day field collisions across {len(games)} games ({checked} named fields checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
