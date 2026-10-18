"""The reroll carry refuses to run while exec value it cannot move would be dropped (tools/alphanet6_carryforward.py).

Found 2026-10-10: the carry checked only the LEGACY shielded pool, while every shield deposit from block 1 lands in the
WIDE pool (and some in the field pool and app_state); and it ignored exec ASSETS (`abal`) entirely (they now carry in the exec genesis). A reroll with notes
in the wide pool or a token held in exec would have dropped them silently — the coins are real, so that is a theft by
the protocol. Pins: each place exec value can sit is refused while it holds value, and an empty snapshot (the live
shape on 2026-10-10) is accepted.

Review 2026-10-11 added: the Stwo pool (added after the list and missing from it) and the exec layer's own pool_value
total are refused; and an exec asset held BY A CONTRACT that would reset (fresh-deploy storage: the ledger of whose the
tokens are is gone) is refused, while the same holding in a contract that carries is accepted.

2026-10-12: the Stwo pool CARRIES (exec_shield_doc; tests/test_the_stwo_pool_crosses_a_reroll_with_its_root_and_spent_set.py),
so its notes are no longer a refusal — but pool_value it does not explain still is.

Run: python3 tests/test_reroll_carry_refuses_to_drop_exec_value.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-carry-drop-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools.alphanet6_carryforward import exec_value_the_carry_would_drop as drop

import _harness
_report = _harness.Report()
check = _report.check


empty = {"shielded": {"commitments": [], "nullifiers": [], "root": "00" * 32}, "field_pool": {"commitments": []},
         "abal": {}, "assets": {}}
check("an exec snapshot holding nothing the carry cannot move is accepted", drop(empty) == [], drop(empty))
for pool in ("shielded", "field_pool", "wide_pool"):
    d = dict(empty, **{pool: {"commitments": ["ab" * 32], "nullifiers": []}})
    got = drop(d)
    check(f"notes in the {pool} are refused", len(got) == 1 and pool in got[0], got)
got = drop(dict(empty, stwo_pool={"commitments": ["ab" * 32], "nullifiers": []}, stwo_value=4, pool_value=4))
check("notes in the stwo_pool are carried, not refused, when stwo_value explains pool_value", got == [], got)
got = drop(dict(empty, stwo_pool={"commitments": ["ab" * 32], "nullifiers": []}, stwo_value=4, pool_value=5))
check("...but value beyond stwo_value is refused", len(got) == 1 and "pool_value" in got[0], got)
check("app_state notes are refused", any("app_state" in r for r in drop(dict(empty, app_state={"trees": {"x": 1}}))))
check("a held exec asset is no longer a refusal: assets carry in the exec genesis",
      drop(dict(empty, abal={"tok": {"a" * 46: 5}})) == [])
got = drop(dict(empty, pool_value=7))
check("value counted in pool_value is refused even when no pool this list names holds a note",
      len(got) == 1 and "pool_value" in got[0], got)
check("a zero pool_value is accepted", drop(dict(empty, pool_value=0)) == [])
CID = "c" * 32
withc = dict(empty, contracts={CID: {"code": {}, "storage": {}}}, abal={"tok": {CID: 9, "a" * 46: 5}})
got = drop(withc, policy=lambda cid, c: "reset")
check("an exec asset held by a contract that would RESET is refused (its ledger would be lost)",
      len(got) == 1 and CID[:16] in got[0] and "tok:9" in got[0], got)
check("...the same holding in a contract that CARRIES is accepted", drop(withc, policy=lambda cid, c: "keep") == [])
check("...a zero holding is no refusal", drop(dict(withc, abal={"tok": {CID: 0}}), policy=lambda cid, c: "reset") == [])
check("...and by default the decision is the carry's own policy (an unknown contract resets)",
      len(drop(withc)) == 1)

src = open(os.path.join(ROOT, "tools", "alphanet6_carryforward.py")).read()
b = src[src.index("def build():"):]
check("build() refuses on any of them before it writes anything",
      b.index("exec_value_the_carry_would_drop(d,") < b.index("--write") if "--write" in b else True)
print("ALL PASS — the carry refuses to drop exec value" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
