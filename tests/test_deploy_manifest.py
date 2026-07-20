"""
The `--all` deploy manifest must list every game module — no more, no less.

Run: python3 tests/test_deploy_manifest.py

`execnode/games/deploy.py` keeps a hand-written GAMES list that `--all` iterates. A hand-maintained mirror
of a directory drifts, and when it does it drifts SILENTLY: hamster was missing from that list, so every
`--all` run skipped it without a word, and the only symptom was a game that quietly never got redeployed.
Nothing errors, nothing warns — the list is simply shorter than reality.

This makes that a build failure instead of a discovery. A new game is added by dropping a module in
execnode/games/, and this test fails until it is also deployable.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

GAMES_DIR = os.path.join(ROOT, "execnode", "games")
NOT_A_GAME = {"deploy"}          # tooling that lives alongside the contracts


def modules_on_disk():
    return sorted(f[:-3] for f in os.listdir(GAMES_DIR)
                  if f.endswith(".py") and not f.startswith("_") and f[:-3] not in NOT_A_GAME)


def manifest():
    src = open(os.path.join(GAMES_DIR, "deploy.py")).read()
    body = re.search(r"^GAMES = \[(.*?)\]", src, re.S | re.M)
    assert body, "could not find the GAMES list in deploy.py"
    return [x.strip().strip("\"'") for x in body.group(1).replace("\n", " ").split(",") if x.strip()]


def main():
    disk, listed = modules_on_disk(), manifest()
    missing = [m for m in disk if m not in listed]
    orphan = [g for g in listed if g not in disk]
    dupes = sorted({g for g in listed if listed.count(g) > 1})

    ok = True
    if missing:
        ok = False
        print(f"FAIL  {len(missing)} game(s) would be SILENTLY SKIPPED by --all: {', '.join(missing)}")
        print("      add them to GAMES in execnode/games/deploy.py")
    if orphan:
        ok = False
        print(f"FAIL  GAMES lists {len(orphan)} module(s) that do not exist: {', '.join(orphan)}")
    if dupes:
        ok = False
        print(f"FAIL  GAMES lists duplicates: {', '.join(dupes)}")
    if ok:
        print(f"PASS  --all covers every game module ({len(disk)}): {' '.join(disk)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
