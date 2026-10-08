"""The exec BEACON of an epoch with no RANDAO reveals is computed from the next revealed epoch's reveals
(protocol.BEACON_EXTEND_HEIGHT, execnode/state.ExecState.exec_beacon_at).

  * below the gate every epoch keeps exec_beacon_int(epoch, its own reveals) — replay unchanged;
  * from the gate a reveal-less epoch is None (not final) until a later epoch with reveals is final, then takes its
    reveals; past BEACON_EXTEND_MAX empty epochs the plain value stands;
  * an epoch WITH reveals is unchanged by the gate;
  * advance_beacons stops at an unresolved epoch and fills it (and everything after) once it resolves — the beacon
    map stays a gap-free range;
  * the L1 settle-proof check, the exec node and the client all read the same definitions.

Run: python3 tests/test_reveal_less_epoch_beacon_waits_for_reveals.py
"""
import os
import re
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-beacon-extend-")   # never the live database (assign, not setdefault)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import protocol as P                                                   # noqa: E402
from execnode.state import ExecState                                   # noqa: E402

FAILED = []
L = P.EPOCH_LENGTH
GATE_E = 1000
P.BEACON_EXTEND_HEIGHT = GATE_E * L


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


REV = {}


def rv(e):
    return REV.get(e, set())


at = ExecState.exec_beacon_at
plain = ExecState.exec_beacon_int

# below the gate
E0 = GATE_E - 10
check("below the gate a reveal-less epoch keeps its plain value", at(E0, rv, E0) == plain(E0, []))
check("below the gate a future epoch is not final", at(E0 + 1, rv, E0) is None)

# from the gate
E = GATE_E + 5
REV[E + 2] = {"s1", "s2"}
check("from the gate a reveal-less epoch is not final while later epochs are empty", at(E, rv, E + 1) is None)
check("it takes the first revealed later epoch's reveals once that epoch is final",
      at(E, rv, E + 2) == plain(E, ["s1", "s2"]) and at(E, rv, E + 2) != plain(E, []))
check("the epoch number stays in the value (two empty epochs extending to one reveal set differ)",
      at(E + 1, rv, E + 2) == plain(E + 1, ["s1", "s2"]) and at(E + 1, rv, E + 2) != at(E, rv, E + 2))
check("an epoch with reveals is unchanged by the gate", at(E + 2, rv, E + 2) == plain(E + 2, ["s1", "s2"]))
E2 = GATE_E + 100
check("past BEACON_EXTEND_MAX empty epochs the plain value stands",
      at(E2, rv, E2 + P.BEACON_EXTEND_MAX + 3) == plain(E2, []))
check("... and not before they are all final", at(E2, rv, E2 + P.BEACON_EXTEND_MAX - 1) is None)

# advance_beacons
st = ExecState(os.path.join(os.environ["HOME"], "s.json"))
st.beacon_floor = E - 1
st.beacons = {}
st.randao_reveals = {E - 1: {"a"}, E + 2: {"s1", "s2"}}
st.advance_beacons((E + 1) * L + 3)
check("advance_beacons stops at the unresolved epoch", sorted(st.beacons) == [E - 1], sorted(st.beacons))
st.advance_beacons((E + 2) * L)
check("and fills it and every later epoch once it resolves", sorted(st.beacons) == [E - 1, E, E + 1, E + 2]
      and st.beacons[E] == plain(E, ["s1", "s2"]), sorted(st.beacons))

# one definition everywhere
src = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
check("the L1 settle-proof check reads BEACON through exec_beacon_at",
      "_ExecState.exec_beacon_at(_key, kv_ops.reveals_for_epoch, _fin // _EL)" in src
      and "_ExecState.exec_beacon_int(_key" not in src)
ex = open(os.path.join(ROOT, "execnode", "execnode.py")).read()
check("/exec/beacon is routed", 'web.get("/exec/beacon", h_beacon)' in ex)
js = open(os.path.join(ROOT, "static", "nadodapp.js")).read()
m = re.search(r"export const EPOCH_LENGTH = (\d+);", js)
check("the client's EPOCH_LENGTH is protocol.EPOCH_LENGTH", m and int(m.group(1)) == L, m and m.group(1))

print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILURES")
sys.exit(1 if FAILED else 0)
