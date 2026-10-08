"""A pets reroll whose pinned beacon epoch has gone STALE can be re-pinned by its owner — at the full reroll cost
(execnode/games/pets.py REROLL, reliability: an item must never be stuck behind a beacon the exec state pruned).

  * reroll(item)[REROLL_FEE] while irp != 0 and cursor < (irp + REROLL_STALE_EPOCHS) * EPOCH_LENGTH reverts, exactly
    as before (the pin does not move, nothing is charged).
  * once cursor >= (irp + REROLL_STALE_EPOCHS) * EPOCH_LENGTH the same paid call runs phase 1 again: owner only,
    unworn, essence + timber + stone + ore x rarity taken and REROLL_FEE burned — the same charge as a fresh reroll —
    and irp = epoch(cursor) + 2. The affixes are untouched until that new pin resolves.
  * a value-0 call on a stale pin is still phase 2 (it reverts when the beacon is gone, resolves when present).
  * the re-pinned item resolves from BEACON(new irp) exactly like any other reroll.
  * REROLL_STALE_EPOCHS stays inside the exec state's beacon retention, so the re-pin is always reachable first.

Run: python3 tests/test_pets_stale_reroll_repins_at_full_cost.py
"""
import os
import sys
import tempfile
import shutil

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-pets-stale-reroll-")   # never the live database (assign, not setdefault)
import atexit; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from execnode import state as S                                       # noqa: E402
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


def costs(st, cid, who):
    return [res(st, cid, who, k) for k in (1, 2, 3, 4)], rd(st, cid, 0, P.BURN_SLOT)


IID, RAR = 12, 3
check("REROLL_STALE_EPOCHS sits inside the exec state's beacon retention (the re-pin is reachable before pruning)",
      0 < P.REROLL_STALE_EPOCHS < S._BEACON_RETENTION_EPOCHS, (P.REROLL_STALE_EPOCHS, S._BEACON_RETENTION_EPOCHS))

st, cid = fresh()
for f, v in ((P.IO, zkvm_addr_digest(A)), (P.IT, 1), (P.IR, RAR), (P.IE, 0)):
    put(st, cid, f, IID, v)
for k in range(3):
    put(st, cid, P.IA_BASE + k, IID, 1 * P.AFFIX_MUL + 3)
for who in (A, B):
    for kind in (1, 2, 3, 4):
        grant(st, cid, who, kind, 100000)
before = [rd(st, cid, P.IA_BASE + k, IID) for k in range(3)]
st.cursor = (st.cursor // EL + 1) * EL + 10

c0, b0 = costs(st, cid, A)
r = call(st, cid, A, "reroll", [IID], P.REROLL_FEE)
irp = rd(st, cid, P.IRP, IID)
c1, b1 = costs(st, cid, A)
fresh_charge = ([x - y for x, y in zip(c0, c1)], b1 - b0)
check("a fresh reroll pins and charges (baseline)", "ok" in r and irp == st.cursor // EL + 2
      and fresh_charge == ([RAR * P.REROLL_TIMBER, RAR * P.REROLL_STONE, RAR * P.REROLL_ORE, RAR * P.REROLL_ESSENCE],
                           P.REROLL_FEE), (r, irp, fresh_charge))

# the beacon is never recorded: the pin has aged past retention in this scenario
st.cursor = (irp + P.REROLL_STALE_EPOCHS) * EL - 1
r = call(st, cid, A, "reroll", [IID], P.REROLL_FEE)
check("one block before the stale age, a paid reroll still reverts (pin kept, nothing charged)",
      "ok" not in r and rd(st, cid, P.IRP, IID) == irp and costs(st, cid, A) == (c1, b1), r)
r = call(st, cid, A, "reroll", [IID])
check("a value-0 call on a pin whose beacon is gone reverts (phase 2 cannot read it)",
      "ok" not in r and rd(st, cid, P.IRP, IID) == irp, r)

st.cursor = (irp + P.REROLL_STALE_EPOCHS) * EL
r = call(st, cid, B, "reroll", [IID], P.REROLL_FEE)
check("at the stale age, a non-owner cannot re-pin", "ok" not in r and rd(st, cid, P.IRP, IID) == irp, r)
r = call(st, cid, A, "reroll", [IID], P.REROLL_FEE - 1)
check("a re-pin that underpays the fee reverts", "ok" not in r and rd(st, cid, P.IRP, IID) == irp, r)
r = call(st, cid, A, "reroll", [IID], P.REROLL_FEE)
irp2 = rd(st, cid, P.IRP, IID)
c2, b2 = costs(st, cid, A)
repin_charge = ([x - y for x, y in zip(c1, c2)], b2 - b1)
check("at the stale age, the owner's paid reroll re-pins irp = epoch(cursor) + 2",
      "ok" in r and irp2 == st.cursor // EL + 2 and irp2 > irp, (r, irp, irp2))
check("the re-pin charges exactly what a fresh reroll charges (never a free roll)",
      repin_charge == fresh_charge, (repin_charge, fresh_charge))
check("the re-pin leaves the affixes untouched", [rd(st, cid, P.IA_BASE + k, IID) for k in range(3)] == before)
r = call(st, cid, A, "reroll", [IID], P.REROLL_FEE)
check("the new pin is young again: a second paid call reverts and charges nothing",
      "ok" not in r and rd(st, cid, P.IRP, IID) == irp2 and costs(st, cid, A) == (c2, b2), r)

st.beacons[irp2] = 0xC0FFEE1234
st.cursor = irp2 * EL
r = call(st, cid, B, "reroll", [IID])
salt = (st.beacons[irp2] % F.P + irp2 + IID) % F.P
after = [rd(st, cid, P.IA_BASE + k, IID) for k in range(3)]
check("the re-pinned reroll resolves from BEACON(new irp) + irp + item and clears the pin",
      "ok" in r and after == P.ref_affixes(salt, RAR) and rd(st, cid, P.IRP, IID) == 0, (r, after))

# a worn item can never be re-pinned (equip refuses a pending item, but pin a worn one directly to be sure)
st, cid = fresh()
for f, v in ((P.IO, zkvm_addr_digest(A)), (P.IT, 1), (P.IR, RAR), (P.IE, 5), (P.IRP, 20)):
    put(st, cid, f, IID, v)
for kind in (1, 2, 3, 4):
    grant(st, cid, A, kind, 100000)
st.cursor = (20 + P.REROLL_STALE_EPOCHS) * EL + 7
r = call(st, cid, A, "reroll", [IID], P.REROLL_FEE)
check("a stale pin on a worn item is not re-pinned (phase 1's unworn rule applies)",
      "ok" not in r and rd(st, cid, P.IRP, IID) == 20, r)

# a stale pin whose beacon IS still present can still be resolved for free (value 0), as before
st, cid = fresh()
for f, v in ((P.IO, zkvm_addr_digest(A)), (P.IT, 1), (P.IR, RAR), (P.IE, 0), (P.IRP, 20)):
    put(st, cid, f, IID, v)
st.beacons[20] = 0xABCDEF
st.cursor = (20 + P.REROLL_STALE_EPOCHS) * EL + 7
r = call(st, cid, B, "reroll", [IID])
salt = (st.beacons[20] % F.P + 20 + IID) % F.P
check("a value-0 call on a stale pin whose beacon is still present resolves it as phase 2",
      "ok" in r and rd(st, cid, P.IRP, IID) == 0
      and [rd(st, cid, P.IA_BASE + k, IID) for k in range(3)] == P.ref_affixes(salt, RAR), r)

# client: the re-roll-again offer uses the contract's own constant and gate
JS = open(os.path.join(ROOT, "static", "pets.js"), encoding="utf-8").read()
check("pets.js REROLL_STALE_EPOCHS equals the contract's",
      f"const REROLL_STALE_EPOCHS = {P.REROLL_STALE_EPOCHS};" in JS)
check("pets.js gates the offer on the contract's stale rule",
      "dapp.cursor >= (pin + REROLL_STALE_EPOCHS) * EPOCH_LENGTH" in JS and "pets.rerollAgain" in JS)

print(f"\n{'ALL PASS' if not FAILED else str(len(FAILED)) + ' FAILED'}")
sys.exit(1 if FAILED else 0)
