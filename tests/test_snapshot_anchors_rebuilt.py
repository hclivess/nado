"""A pool loaded from a snapshot holds exactly the anchors an honest replay holds, and never a donor's extra root
(execnode/shielded.py from_dict; execnode/state.py exit-counter floors and retired-pool keys).

The exec state root commits the commitment tree and the nullifier set but not the anchor window, so a node adopting a
peer's snapshot used to take the donor's anchors on faith: the root of a fake tree let a real proof against it through
(zk audit 2026-09-26 F2, reproduced: forged note, pool_value negative, a forged exit). Pins: after any number of appends,
save+load reproduces the live anchor window exactly (an honest restart changes nothing); an injected fake root is
dropped; and an exit counter below a pending record's key is floored so the next exit cannot overwrite it.
An exec_state.json from before G9 slice 5 still carries the deleted pools' keys ("field_pool" on every gen-29 node, and
possibly "wide_pool" / "app_state"): it loads, the keys are ignored, and the state root is the one it always had.

Run: python3 tests/test_snapshot_anchors_rebuilt.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-anchors-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import sys, random, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.shielded import ShieldedPool, _h as sh_h

import _harness
_report = _harness.Report()
check = _report.check


rnd = random.Random(7)
# (the wide pool's two depths, the deepened-window and O(n)-rebuild pins, and the field pool's window: retired in G9 slice 5
# with those pools; the legacy pool below is the one still live besides the Stwo pool, which has its own tests)

# the phase-1 pool remembers once per TRANSFER (several outputs), like shielded.apply_transfer
for transfers in (0, 4, 70):
    live = ShieldedPool()
    for t in range(transfers):
        for o in range(rnd.choice((1, 2, 3))):
            live._append_commitment(sh_h("cm", t, o))
        live._remember_anchor(live.root())
    back = ShieldedPool.from_dict(json.loads(json.dumps(live.to_dict())))
    check(f"phase-1 pool, {transfers} transfers: a restart keeps every honest anchor", back.anchor_list == live.anchor_list)
    fake = live.to_dict(); fake["anchors"] = fake["anchors"] + [sh_h("fake-tree-root")]
    check(f"phase-1 pool, {transfers} transfers: a donor's fake root is dropped",
          ShieldedPool.from_dict(fake).anchor_list == live.anchor_list)

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

# THE FLEET'S STATE FILES CARRY THE DELETED POOLS' KEYS (G9 slice 5): every gen-29 exec_state.json has an empty
# "field_pool", and an older one may hold "wide_pool" (at either depth — the depth check that refused a mismatch went
# with the pool) and "app_state". _restore must load them and ignore the keys, and the root must not move.
st3 = ExecState(os.path.join(os.environ["HOME"], "s3.json"))
st3.cursor = 10576
root3, snap3 = st3.state_root(), json.loads(json.dumps(st3._snapshot(), default=str))
old = dict(snap3, field_pool={"commitments": [], "nullifiers": [], "anchors": ["12068980620996700996"]},
           wide_pool={"commitments": [], "nullifiers": [], "depth": 12}, app_state={"trees": {}, "nullifiers": []})
json.dump(old, open(os.path.join(os.environ["HOME"], "s4.json"), "w"))
st4 = ExecState(os.path.join(os.environ["HOME"], "s4.json"))
check("an old state file with field_pool / wide_pool / app_state keys loads, with the root it always had",
      st4.cursor == 10576 and st4.state_root() == root3, (st4.cursor, st4.state_root(), root3))
check("...and the pools are gone from the state and its snapshot",
      not any(hasattr(st4, k) for k in ("field_pool", "wide_pool", "app_state"))
      and not any(k in st4._snapshot() for k in ("field_pool", "wide_pool", "app_state")))

print("ALL PASS" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
