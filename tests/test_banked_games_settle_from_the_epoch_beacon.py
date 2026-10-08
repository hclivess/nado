"""The shared epoch-beacon helpers every banked game binds and settles with (execnode/games/_lib.beacon_bind / seed_q).

  * beacon_bind stores gb = epoch(cursor) + 2 and gh = gb * EPOCH_LENGTH - 1, so "settle at gh + 1" is exactly
    "the beacon epoch has begun";
  * seed_q returns BEACON(gb) for a bound seat and BHASH(gh) + BHASH(gh + 1) for a seat with gb == 0 (placed under
    the block-hash rule) — the client formula chainResultAlg(beacon, "0", salt, mod) is the same seed;
  * _lib.EPOCH_LENGTH is protocol.EPOCH_LENGTH.

A two-method contract assembled from the helpers, run in a throwaway ExecState.
Run: python3 tests/test_banked_games_settle_from_the_epoch_beacon.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-beacon-lib-")      # never the live database (assign, not setdefault)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import protocol as P                                                   # noqa: E402
from execnode.state import ExecState                                   # noqa: E402
from execnode.stark import field as F                                  # noqa: E402
from execnode import zkvmasm                                           # noqa: E402
from execnode.games import _lib                                        # noqa: E402

FAILED = []
GH, GB, OUT = 11, 17, 18


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


check("_lib.EPOCH_LENGTH is protocol.EPOCH_LENGTH", _lib.EPOCH_LENGTH == P.EPOCH_LENGTH)

SRC = {
    "bind": _lib.beacon_bind(GH, GB) + "ret r0",
    "seed": _lib.seed_q(GH, GB) + f"slot r4 {OUT} r0\nsstore r4 r3\nret r0",
    # a seat written the way the code before the upgrade wrote it: gh = cursor + 2, no gb
    "legacy": f"ctx r5 cursor\nmovi r6 2\nadd r5 r6\nslot r4 {GH} r0\nsstore r4 r5\nret r0",
}
code = zkvmasm.assemble_contract(SRC)
st = ExecState(os.path.join(os.environ["HOME"], "s.json"))
st.cursor = 6000 + 17                       # epoch 100
st.bridge["ndoA"] = 10 ** 12
st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": {}, "nonce": "n"}, "ndoA", "d")
cid = st.contract_id("ndoA", code, "n")
_n = [0]


def call(m, g):
    _n[0] += 1
    st.apply_blob({"op": "call", "contract": cid, "method": m, "args": [g]}, "ndoA", f"{m}-{_n[0]}")


def rd(f, k):
    return int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))


call("bind", 1)
check("gb = epoch(cursor) + 2", rd(GB, 1) == 102, rd(GB, 1))
check("gh = gb * EPOCH_LENGTH - 1 (settle at gh + 1 = the beacon epoch's first block)", rd(GH, 1) == 102 * 60 - 1, rd(GH, 1))

BEACON = (1 << 255) + 12345
st.beacons[102] = BEACON
st.cursor = 102 * 60
call("seed", 1)
check("a bound seat's seed is BEACON(gb)", rd(OUT, 1) == BEACON % F.P, (rd(OUT, 1), BEACON % F.P))

st.cursor = 7000
call("legacy", 2)
st.block_hashes[7002] = (1 << 200) + 5
st.block_hashes[7003] = (1 << 190) + 9
st.cursor = 7004
call("seed", 2)
check("a seat with gb == 0 keeps BHASH(gh) + BHASH(gh + 1)",
      rd(OUT, 2) == ((st.block_hashes[7002] % F.P) + (st.block_hashes[7003] % F.P)) % F.P, rd(OUT, 2))

st.cursor = 8000
call("bind", 3)
before = rd(OUT, 3)
try:
    call("seed", 3)
except Exception:
    pass
check("a seat whose beacon is not available yet does not resolve", rd(OUT, 3) == before == 0)

print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILURES")
sys.exit(1 if FAILED else 0)
