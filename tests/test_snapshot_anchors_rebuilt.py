"""A pool loaded from a snapshot holds exactly the anchors an honest replay holds, and never a donor's extra root
(execnode/shielded_wide.py, shielded_field.py, shielded.py from_dict; execnode/state.py exit-counter floors).

The exec state root commits the commitment tree and the nullifier set but not the anchor window, so a node adopting a
peer's snapshot used to take the donor's anchors on faith: the root of a fake tree let a real proof against it through
(zk audit 2026-09-26 F2, reproduced: forged note, pool_value negative, a forged exit). Pins: after any number of appends,
save+load reproduces the live anchor window exactly (an honest restart changes nothing); an injected fake root is
dropped; and an exit counter below a pending record's key is floored so the next exit cannot overwrite it.

Run: python3 tests/test_snapshot_anchors_rebuilt.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-anchors-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import sys, random, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.shielded_wide import WideShieldedPool, ANCHOR_WINDOW
from execnode.shielded_field import FieldShieldedPool
from execnode.shielded import ShieldedPool, _h as sh_h
from execnode.stark import znote as Z

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


rnd = random.Random(7)
wide_cm = lambda: tuple(rnd.randrange(1, 2**63) for _ in range(4))
for n in (0, 1, 5, ANCHOR_WINDOW - 1, ANCHOR_WINDOW, ANCHOR_WINDOW + 7):
    live = WideShieldedPool()
    for _ in range(n):
        live.append(wide_cm())
    back = WideShieldedPool.from_dict(json.loads(json.dumps(live.to_dict())))
    check(f"wide pool, {n} notes: a restart reproduces the anchor window exactly", back.anchors == live.anchors)
    fake = live.to_dict()
    fake["anchors"] = fake["anchors"] + [Z.to_hex(wide_cm())]
    check(f"wide pool, {n} notes: a donor's extra root is dropped", WideShieldedPool.from_dict(fake).anchors == live.anchors)

for n in (0, 3, 130):
    live = FieldShieldedPool()
    for _ in range(n):
        live.append(rnd.randrange(1, 2**63))
    back = FieldShieldedPool.from_dict(json.loads(json.dumps(live.to_dict())))
    check(f"field pool, {n} notes: a restart reproduces the anchor window exactly", back.anchors == live.anchors)
    fake = live.to_dict(); fake["anchors"] = fake["anchors"] + [str(rnd.randrange(1, 2**63))]
    check(f"field pool, {n} notes: a donor's extra root is dropped", FieldShieldedPool.from_dict(fake).anchors == live.anchors)

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

print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
