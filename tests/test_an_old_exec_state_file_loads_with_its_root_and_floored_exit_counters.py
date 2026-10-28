"""An old exec_state.json loads with the root it always had, and its exit counters are floored at the pending keys
(execnode/state.py _restore: exit-counter floors and retired-pool keys).

An exit counter below a pending record's key is floored so the next exit cannot overwrite it (zk audit 2026-09-26 F2).
An exec_state.json from before G9 slice 5 / 5c still carries the deleted pools' keys ("shielded" and "field_pool" on every
gen-29 node, and possibly "wide_pool" / "app_state"): it loads, the keys are ignored, and the state root is the one it
always had. (The legacy pool's snapshot-anchor pins — a donor's fake root dropped on load — went with
execnode/shielded.py in G9 slice 5c; the Stwo pool's anchors have their own tests.)

Run: python3 tests/test_an_old_exec_state_file_loads_with_its_root_and_floored_exit_counters.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-anchors-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _harness
_report = _harness.Report()
check = _report.check

from execnode.state import ExecState
st = ExecState(os.path.join(os.environ["HOME"], "s.json"))
d = json.loads(json.dumps(st._snapshot(), default=str)) if hasattr(st, "_snapshot") else None
if d is not None:
    d["unshield_withdrawals"] = {"5": {"addr": "a", "amount": 1}}; d["uw_nonce"] = 2
    d["withdrawals"] = {"9": {}}; d["wd_nonce"] = 0
    d["dividend_withdrawals"] = {"3": {}}; d["dw_nonce"] = 7
    json.dump(d, open(os.path.join(os.environ["HOME"], "s2.json"), "w"))
    st2 = ExecState(os.path.join(os.environ["HOME"], "s2.json"))
    check("an exit counter below a pending key is floored to it", (st2.uw_nonce, st2.wd_nonce) == (5, 9), (st2.uw_nonce, st2.wd_nonce))
    check("an honest counter above every key is left alone", st2.dw_nonce == 7)
else:
    check("ExecState exposes _snapshot for the counter test", False)

# THE FLEET'S STATE FILES CARRY THE DELETED POOLS' KEYS (G9 slices 5, 5c): every gen-29 exec_state.json has an empty
# "shielded" (the legacy pool, exactly as its to_dict wrote it) and "field_pool", and an older one may hold "wide_pool" (at
# either depth — the depth check that refused a mismatch went with the pool) and "app_state". _restore must load them and
# ignore the keys, and the root must not move.
EMPTY_LEGACY = "3494ed478a1577a5dad291006765ffcbf43096c44f1cec9121c302cf6b767f92"
st3 = ExecState(os.path.join(os.environ["HOME"], "s3.json"))
st3.cursor = 10576
root3, snap3 = st3.state_root(), json.loads(json.dumps(st3._snapshot(), default=str))
old = dict(snap3, shielded={"commitments": [], "nullifiers": [], "anchors": [EMPTY_LEGACY], "root": EMPTY_LEGACY},
           field_pool={"commitments": [], "nullifiers": [], "anchors": ["12068980620996700996"]},
           wide_pool={"commitments": [], "nullifiers": [], "depth": 12}, app_state={"trees": {}, "nullifiers": []})
json.dump(old, open(os.path.join(os.environ["HOME"], "s4.json"), "w"))
st4 = ExecState(os.path.join(os.environ["HOME"], "s4.json"))
check("an old state file with shielded / field_pool / wide_pool / app_state keys loads, with the root it always had",
      st4.cursor == 10576 and st4.state_root() == root3, (st4.cursor, st4.state_root(), root3))
check("...and the pools are gone from the state and its snapshot",
      not any(hasattr(st4, k) for k in ("shielded", "field_pool", "wide_pool", "app_state"))
      and not any(k in st4._snapshot() for k in ("shielded", "field_pool", "wide_pool", "app_state")))

print("ALL PASS" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
