"""Pets item finds and rerolls pin a LATER epoch beacon (execnode/games/pets.py _item_drop / REROLL, Release B game
fairness). Both used the previous block's hash, which the caller sees before sending the call.

  * collect(bid), phase 1: pins bdp = epoch(cursor) + 2 and records the operator's tier (bdr); nothing is found in
    that call. Further collects before cursor reaches bdp * EPOCH_LENGTH leave the pin where it is.
  * collect(bid), phase 2: roll = LO32(H(BEACON(bdp) + bdp + bid)); a find iff roll % DROP_ONE_IN == 0 and bdr > 0
    (slot roll % GEAR_SLOTS, rarity bdr, affixes salted by roll) — and the same call pins the next find. Re-staffing
    a rarer pet after the pin does not change the rarity; a pin older than STALE re-pins without reading a beacon.
  * reroll(item)[fee], phase 1: costs taken, irp = epoch(cursor) + 2, affixes untouched — even when BEACON(irp)
    were already known. A second reroll before the beacon epoch reverts (the pin does not move, nothing is
    charged twice); equip and fuse refuse an item with a pending reroll.
  * reroll(item), phase 2 (any caller, value 0, cursor >= irp * EPOCH_LENGTH): affixes = the reference roll over
    BEACON(irp) + irp + item; irp cleared.

Run: python3 tests/test_pets_item_rolls_pin_a_later_beacon.py
"""
import os
import sys
import tempfile
import shutil

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-pets-beacon-pin-")   # never the live database (assign, not setdefault)
import atexit; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from execnode.state import ExecState                                   # noqa: E402
from execnode.runtimes import zkvm_addr_digest                         # noqa: E402
from execnode.stark import alghash, field as F                         # noqa: E402
from execnode.games import pets as P                                   # noqa: E402
from execnode.games import _lib                                        # noqa: E402

FAILED = []
EL = _lib.EPOCH_LENGTH


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


A = "ndoA" + "a" * 44
B = "ndoB" + "b" * 44
_n = [0]


def fresh(cursor=1000):
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=os.environ["HOME"]), "s.json"))
    st.cursor = cursor
    st.block_hashes = {h: (h * 1_000_003 + 7) for h in range(0, 4000)}
    for w in (A, B):
        st.bridge[w] = 10 ** 14
    code = P.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": P.ABI, "nonce": "n"}, A, "d")
    return st, st.contract_id(A, code, "n")


def call(st, cid, who, m, args, value=None):
    _n[0] += 1
    blob = {"op": "call", "contract": cid, "method": m, "args": args}
    if value is not None:
        blob["value"] = value
    return st.apply_blob(blob, who, f"{m}-{_n[0]}")


def rd(st, cid, f, k):
    return int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))


def put(st, cid, f, k, v):
    st.contracts[cid]["storage"].setdefault("slots", {})[str(f * (1 << 32) + k)] = int(v)


def res(st, cid, who, kind):
    return st.view(cid, "res_of", [who, kind])


def grant(st, cid, who, kind, amount):
    slot = alghash.hashn([P.TG_RES, zkvm_addr_digest(who), kind])
    st.contracts[cid]["storage"].setdefault("slots", {})[str(slot)] = int(amount)


def farmer(st, cid, start):
    """mint + hatch until a pet born to trade 0 (fodder) turns up."""
    for pid in range(start, start + 400):
        assert "ok" in call(st, cid, A, "mint", [pid], P.MINT_FEE)
        st.cursor += 3
        assert "ok" in call(st, cid, A, "hatch", [pid])
        if rd(st, cid, P.SI, pid) % P.NJOBS == 0:
            return pid
    raise AssertionError("no farmer")


def beacon_for(bdp, bid, hit):
    """a beacon value whose find roll hits (or misses) — the test picks the chain's randomness, not the contract."""
    for v in range(1, 10 ** 6):
        r = P.ref_find_roll(v, bdp, bid)
        if (r % P.DROP_ONE_IN == 0) == hit:
            return v, r
    raise AssertionError("no beacon")


# ---- the find: phase 1 pins, phase 2 resolves from BEACON(pin) ------------------------------------------------------
st, cid = fresh()
pid = farmer(st, cid, 100)
BID = 7
assert "ok" in call(st, cid, A, "build", [BID, 0, pid], P.BUILD_FEE)
assert "ok" in call(st, cid, A, "staff", [BID, pid])
st.cursor = (st.cursor // EL + 1) * EL + 5                   # a known spot inside a later epoch
r = call(st, cid, A, "collect", [BID])
bdp = rd(st, cid, P.BDP, BID)
check("collect phase 1 pins bdp = epoch(cursor) + 2", "ok" in r and bdp == st.cursor // EL + 2, (r, bdp))
check("phase 1 records the operator's tier as the find's rarity", rd(st, cid, P.BDR, BID) == rd(st, cid, P.SP, pid))
check("phase 1 finds nothing in the same call", rd(st, cid, 0, P.ICNT_SLOT) == 0)
v_hit, roll = beacon_for(bdp, BID, True)
st.beacons[bdp] = v_hit                                      # even a beacon already known cannot pull it forward
st.cursor = bdp * EL - 1
r = call(st, cid, B, "collect", [BID])
check("a collect before the beacon epoch leaves the pin where it is and finds nothing",
      "ok" in r and rd(st, cid, P.BDP, BID) == bdp and rd(st, cid, 0, P.ICNT_SLOT) == 0, r)
sp_at_pin = rd(st, cid, P.BDR, BID)
put(st, cid, P.SP, pid, 6)                                   # the operator "becomes" top tier after the pin
st.cursor = bdp * EL + 3
r = call(st, cid, B, "collect", [BID])
check("phase 2 (any caller) resolves the pinned find", "ok" in r and rd(st, cid, 0, P.ICNT_SLOT) == 1, r)
iid = rd(st, cid, P.ILIST, 0)
check("the find goes to the base's owner, unworn", rd(st, cid, P.IO, iid) == zkvm_addr_digest(A)
      and rd(st, cid, P.IE, iid) == 0)
check("its gear slot is roll % GEAR_SLOTS of LO32(H(BEACON(bdp) + bdp + bid))",
      rd(st, cid, P.IT, iid) == roll % P.GEAR_SLOTS)
check("its rarity is the tier recorded at pin time, not the operator's tier at resolution",
      rd(st, cid, P.IR, iid) == sp_at_pin and sp_at_pin != 6)
check("its affixes equal the reference roll", [rd(st, cid, P.IA_BASE + k, iid) for k in range(3)]
      == P.ref_affixes(roll, sp_at_pin))
check("the resolving collect pins the next find from the current epoch",
      rd(st, cid, P.BDP, BID) == st.cursor // EL + 2 and rd(st, cid, P.BDR, BID) == 6)

bdp2 = rd(st, cid, P.BDP, BID)
v_miss, _ = beacon_for(bdp2, BID, False)
st.beacons[bdp2] = v_miss
st.cursor = bdp2 * EL
r = call(st, cid, A, "collect", [BID])
check("a beacon that misses resolves to no find and re-pins", "ok" in r and rd(st, cid, 0, P.ICNT_SLOT) == 1
      and rd(st, cid, P.BDP, BID) == bdp2 + 2, r)

bdp3 = rd(st, cid, P.BDP, BID)
st.cursor = bdp3 * EL + P.STALE + 1                          # no beacon recorded for bdp3 at all
r = call(st, cid, A, "collect", [BID])
check("a pin older than STALE re-pins without reading its beacon (a long-idle base never bricks)",
      "ok" in r and rd(st, cid, P.BDP, BID) == st.cursor // EL + 2, r)

# an unstaffed pin finds nothing even on a hitting beacon
st, cid = fresh()
pid = farmer(st, cid, 100)
assert "ok" in call(st, cid, A, "build", [9, 0, pid], P.BUILD_FEE)
assert "ok" in call(st, cid, A, "collect", [9])
bdp = rd(st, cid, P.BDP, 9)
check("an unstaffed base pins with rarity 0", bdp != 0 and rd(st, cid, P.BDR, 9) == 0)
st.beacons[bdp] = beacon_for(bdp, 9, True)[0]
st.cursor = bdp * EL
r = call(st, cid, A, "collect", [9])
check("and its hitting beacon mints nothing (a find needs a worker at pin time)",
      "ok" in r and rd(st, cid, 0, P.ICNT_SLOT) == 0, r)

# ---- reroll: phase 1 pays and pins, phase 2 resolves from BEACON(pin) ----------------------------------------------
st, cid = fresh()
pid = farmer(st, cid, 100)
IID, RAR = 12, 2
for f, v in ((P.IO, zkvm_addr_digest(A)), (P.IT, 1), (P.IR, RAR), (P.IE, 0)):
    put(st, cid, f, IID, v)
for k in range(3):
    put(st, cid, P.IA_BASE + k, IID, 1 * P.AFFIX_MUL + 3)
for f, v in ((P.IO, zkvm_addr_digest(A)), (P.IT, 1), (P.IR, RAR), (P.IE, 0)):
    put(st, cid, f, IID + 1, v)
for kind in (1, 2, 3, 4):
    grant(st, cid, A, kind, 10000)
before = [rd(st, cid, P.IA_BASE + k, IID) for k in range(3)]
st.cursor = (st.cursor // EL + 1) * EL + 10
pin_expected = st.cursor // EL + 2
st.beacons[pin_expected] = 0x5EED5EED5EED                   # known in advance: phase 1 must still not use it
ess0 = res(st, cid, A, 4)
burn0 = rd(st, cid, 0, P.BURN_SLOT)
r = call(st, cid, A, "reroll", [IID], P.REROLL_FEE)
irp = rd(st, cid, P.IRP, IID)
check("reroll phase 1 pins irp = epoch(cursor) + 2", "ok" in r and irp == pin_expected, (r, irp))
check("phase 1 cannot resolve in the same call: the affixes are untouched",
      [rd(st, cid, P.IA_BASE + k, IID) for k in range(3)] == before)
check("phase 1 takes the costs (essence + fee)", res(st, cid, A, 4) == ess0 - RAR * P.REROLL_ESSENCE
      and rd(st, cid, 0, P.BURN_SLOT) == burn0 + P.REROLL_FEE)
ess1 = res(st, cid, A, 4)
r = call(st, cid, A, "reroll", [IID], P.REROLL_FEE)
check("a second phase-1 call does not move the pin or charge again",
      "ok" not in r and rd(st, cid, P.IRP, IID) == irp and res(st, cid, A, 4) == ess1, r)
check("a resolve before the beacon epoch is refused and leaves the pin",
      "ok" not in call(st, cid, B, "reroll", [IID]) and rd(st, cid, P.IRP, IID) == irp)
check("equip refuses an item with a pending reroll", "ok" not in call(st, cid, A, "equip", [IID, pid])
      and rd(st, cid, P.IE, IID) == 0)
check("fuse refuses an item with a pending reroll", "ok" not in call(st, cid, A, "fuse", [IID, IID + 1], P.FUSE_FEE)
      and "ok" not in call(st, cid, A, "fuse", [IID + 1, IID], P.FUSE_FEE) and rd(st, cid, P.IR, IID) == RAR)
st.cursor = irp * EL
check("phase 2 carries no value", "ok" not in call(st, cid, B, "reroll", [IID], P.REROLL_FEE))
r = call(st, cid, B, "reroll", [IID])
salt = (st.beacons[irp] % F.P + irp + IID) % F.P
after = [rd(st, cid, P.IA_BASE + k, IID) for k in range(3)]
check("phase 2 (any caller) resolves the affixes from BEACON(irp) + irp + item",
      "ok" in r and after == P.ref_affixes(salt, RAR), (r, after, P.ref_affixes(salt, RAR)))
check("phase 2 clears the pin and keeps slot + rarity", rd(st, cid, P.IRP, IID) == 0
      and rd(st, cid, P.IT, IID) == 1 and rd(st, cid, P.IR, IID) == RAR)
check("after resolving, the item equips again", "ok" in call(st, cid, A, "equip", [IID, pid]))

print(f"\n{'ALL PASS' if not FAILED else str(len(FAILED)) + ' FAILED'}")
sys.exit(1 if FAILED else 0)
