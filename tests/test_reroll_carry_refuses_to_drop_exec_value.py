"""The reroll carry refuses to run while exec value it cannot move would be dropped (tools/alphanet6_carryforward.py).

Found 2026-10-10: the carry checked only the LEGACY shielded pool, while every shield deposit from block 1 lands in the
WIDE pool (and some in the field pool and app_state); and it ignored exec ASSETS (`abal`) entirely (they now carry in the exec genesis). A reroll with notes
in the wide pool or a token held in exec would have dropped them silently — the coins are real, so that is a theft by
the protocol. Pins: each place exec value can sit is refused while it holds value, and an empty snapshot (the live
shape on 2026-10-10) is accepted.

Run: python3 tests/test_reroll_carry_refuses_to_drop_exec_value.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-carry-drop-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools.alphanet6_carryforward import exec_value_the_carry_would_drop as drop

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


empty = {"shielded": {"commitments": [], "nullifiers": [], "root": "00" * 32}, "field_pool": {"commitments": []},
         "abal": {}, "assets": {}}
check("an exec snapshot holding nothing the carry cannot move is accepted", drop(empty) == [], drop(empty))
for pool in ("shielded", "field_pool", "wide_pool"):
    d = dict(empty, **{pool: {"commitments": ["ab" * 32], "nullifiers": []}})
    got = drop(d)
    check(f"notes in the {pool} are refused", len(got) == 1 and pool in got[0], got)
check("app_state notes are refused", any("app_state" in r for r in drop(dict(empty, app_state={"trees": {"x": 1}}))))
check("a held exec asset is no longer a refusal: assets carry in the exec genesis",
      drop(dict(empty, abal={"tok": {"a" * 46: 5}})) == [])

src = open(os.path.join(ROOT, "tools", "alphanet6_carryforward.py")).read()
b = src[src.index("def build():"):]
check("build() refuses on any of them before it writes anything",
      b.index("exec_value_the_carry_would_drop(d)") < b.index("--write") if "--write" in b else True)
print("ALL PASS — the carry refuses to drop exec value" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
