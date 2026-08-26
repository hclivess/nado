"""Every game's ABI `_view` must be a shape decode_view can actually enumerate.

dex shipped `"index": {"pools": {"count": 0, "list": LIST}}` — a NAMED sub-index under the SINGULAR key,
with "count" instead of "cnt". decode_view read it as the simple single-index schema, found no "cnt",
took cnt=0, and returned every map EMPTY: the AMM's pools were invisible to the frontend for the
contract's entire life while every call landed fine on chain. This pins the key names for every game.

Run: HOME=$(mktemp -d) python3 tests/view_schema_test.py
"""
import importlib, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.games.deploy import GAMES

passed = failed = 0
def ok(c, m):
    global passed, failed
    if c: passed += 1
    else: failed += 1; print("  FAIL:", m)

for g in GAMES:
    view = (getattr(importlib.import_module(f"execnode.games.{g}"), "ABI", {}) or {}).get("_view")
    if not view:
        continue
    maps, idx, idxs = view.get("maps") or {}, view.get("index"), view.get("indexes")
    named = {n for spec in maps.values() if isinstance(spec, dict) for n in [spec.get("index")] if n}
    if named:                                   # RICH schema: every named index must exist under "indexes"
        ok(isinstance(idxs, dict), f"{g}: maps reference named indexes {sorted(named)} but there is no 'indexes' block "
                                   f"(a named index under the singular 'index' key decodes to nothing)")
        for n in sorted(named):
            spec = (idxs or {}).get(n)
            ok(isinstance(spec, dict), f"{g}: index {n!r} referenced by a map but not defined in 'indexes'")
            if isinstance(spec, dict):
                ok("cnt" in spec or spec.get("range"), f"{g}: index {n!r} has no 'cnt' key (\"count\" is NOT read) — every map would decode empty")
                ok("list" in spec or spec.get("range"), f"{g}: index {n!r} has no 'list' field and is not a range index")
    elif isinstance(idx, dict):                 # SIMPLE schema: the index itself carries cnt/list
        ok("cnt" in idx or idx.get("range"), f"{g}: simple 'index' has no 'cnt' key — every map would decode empty")
        ok(not any(isinstance(v, dict) for v in idx.values()),
           f"{g}: simple 'index' contains a nested dict — that is the RICH shape and belongs under 'indexes'")
    for name, spec in maps.items():             # a map's field must be an int (or {'field': int})
        f = spec.get("field") if isinstance(spec, dict) else spec
        ok(isinstance(f, int), f"{g}: map {name!r} has a non-integer field id")

print(f"\n[view-schema] {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
