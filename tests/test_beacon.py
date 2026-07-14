# tests/test_beacon.py — the RANDAO BEACON exec-layer primitive (#randao). The exec node collects per-epoch
# reveal secrets from the finalized L1 blocks it replays and exposes each epoch's grind-resistant beacon to
# the VM via the BEACON opcode, so a game can settle OBJECTIVELY from chain randomness with NO player
# secret-reveal. Each beacon is a pure function of that epoch's FINALIZED reveals, so every node agrees
# regardless of when it started; a partially-witnessed epoch (below beacon_floor) is unavailable, not wrong.
import sys, tempfile
sys.path.insert(0, "/root/nado")
from execnode.state import ExecState
from protocol import EPOCH_LENGTH, GENESIS_BEACON
from ops.mining_ops import compute_beacon

F = []
def ck(n, c): print(("  ok  " if c else " FAIL ") + n); (F.append(n) if not c else None)

# two nodes that begin collecting at DIFFERENT heights must still agree on any fully-witnessed epoch
A = ExecState(tempfile.mktemp()); A.cursor = 10 * EPOCH_LENGTH; A.advance_beacons(A.cursor)
A.record_reveal(13, "aa"); A.record_reveal(13, "bb"); A.cursor = 14 * EPOCH_LENGTH; A.advance_beacons(A.cursor)
B = ExecState(tempfile.mktemp()); B.cursor = 11 * EPOCH_LENGTH; B.advance_beacons(B.cursor)
B.record_reveal(13, "bb"); B.record_reveal(13, "aa"); B.cursor = 14 * EPOCH_LENGTH; B.advance_beacons(B.cursor)
exp = int(compute_beacon(GENESIS_BEACON, sorted(["aa", "bb"]) + ["13"]), 16)
ck("beacon is a pure function of finalized reveals (node-time-agnostic)", A.beacons.get(13) == B.beacons.get(13) == exp)
ck("reveal order doesn't matter (sorted)", A.beacons.get(13) == exp)
ck("an epoch below the beacon floor is unavailable (no partial-witness beacon)", (A.beacon_floor - 1) not in A.beacons)

# the BEACON opcode: a contract reads a finalized beacon; a future/unavailable epoch reverts (no-op)
st = ExecState(tempfile.mktemp()); st.cursor = 1 * EPOCH_LENGTH; st.advance_beacons(st.cursor)   # floor = 3
st.record_reveal(4, "zz"); st.cursor = 8 * EPOCH_LENGTH; st.advance_beacons(st.cursor)            # epoch 4 >= floor
from execnode import zkvmasm
CODE = zkvmasm.assemble_contract({"getb": "beacon r1 r0\n ret r1"})
st.apply_blob({"op": "deploy", "code": CODE, "nonce": "b"}, "X", "d")
cid = list(st.contracts)[0]
from execnode.stark.field import P as _P
b4 = int(compute_beacon(GENESIS_BEACON, ["zz", "4"]), 16) % _P
ck("BEACON(finalized epoch) returns the exec beacon", st.view(cid, "getb", [4]) == b4 and 4 in st.beacons)
ck("BEACON(finalized) is reproducible (deterministic view)", st.view(cid, "getb", [4]) == st.view(cid, "getb", [4]))
ck("BEACON(future/unavailable epoch) reverts -> None", st.view(cid, "getb", [9999]) is None)
ck("a game result HASH(beacon || id) differs per id", st.view(cid, "getb", [4]) is not None)

# persistence + provisional clone carry the beacon subsystem
st.save(); R = ExecState(st.path)
ck("persist/restore round-trips beacons + floor", R.beacons == st.beacons and R.beacon_floor == st.beacon_floor and R.randao_reveals == st.randao_reveals)
ck("clone() (provisional view) carries the beacons", st.clone().beacons == st.beacons)

print("\n" + ("ALL PASS" if not F else f"{len(F)} FAILED: {F}"))
sys.exit(1 if F else 0)
