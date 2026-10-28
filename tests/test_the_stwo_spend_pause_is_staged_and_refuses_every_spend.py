"""The Stwo spend pause is staged and refuses every spend (protocol.STWO_PAUSE_HEIGHT, ExecState.stwo_spend_refusal).

An emergency pause must not be written, reviewed and tested under pressure (2026-10-27 incident survey: Zcash disabled
Orchard by an emergency soft fork after a counterfeiting bug in its circuit; RISC Zero turned affected verifiers off
through a pre-built "estop"). STWO_PAUSE_HEIGHT is never on every generation until an emergency release sets it to a
height; this pins that setting it is ALL that release needs.

Pins: it is never today (1 << 62); from the pause height every Stwo spend is refused by stwo_spend_refusal, the one
method the exec apply AND the node relay (/exec/stwo_spendable) decide through, and refused before the proof is read;
the refusal changes nothing; below the pause height the same spend applies; deposits still land while paused (an L1
deposit has already escrowed its coins and must never be stranded); and the endpoint the relay asks really goes
through stwo_spend_refusal.

Run: python3 tests/test_the_stwo_spend_pause_is_staged_and_refuses_every_spend.py
"""
import os, sys, tempfile, types, copy, inspect
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-stwo-pause-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
H = os.environ["HOME"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import protocol as P
from execnode.state import ExecState
from execnode import shielded_stwo as SP
from ops.address_ops import make_address

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


check("the pause is never today, on every generation (1 << 62)", P.STWO_PAUSE_HEIGHT == 1 << 62, P.STWO_PAUSE_HEIGHT)

VERIFIED = []
fake = types.ModuleType("execnode.stwo_js_native")
fake.verify = lambda proof, root, nf, cm1, cm2, unshield, fee, dest, height: (VERIFIED.append(height) or (True, ""))
sys.modules["execnode.stwo_js_native"] = fake
import execnode as _stk
_stk.stwo_js_native = fake

GATE, PAUSE = 1000, 1100
nsk = "11" * 32
owner = SP.owner_of(nsk)
DEST = make_address("ab" * 1312)


def pool_at(cursor):
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=H), "s.json"))
    st.cursor = GATE - 1
    st.apply_field_shield(5000, owner, 7)
    st.cursor = cursor
    return st


def bundle_for(st):
    return {"stark": {"stwo_js": {"proof": "ab" * 8, "root": st.stwo_pool.root(), "nf": SP.nullifier(nsk, 7),
                                  "cm_out1": SP.commit(3000, owner, 8), "cm_out2": SP.commit(1500, owner, 9),
                                  "unshield": 400, "fee": 100}}, "withdraw_addr": DEST}


P.STWO_PAUSE_HEIGHT = PAUSE                                  # what an emergency release would ship
st = pool_at(PAUSE - 1)                                      # applying block = PAUSE
b = bundle_for(st)
js = b["stark"]["stwo_js"]
why = st.stwo_spend_refusal(js["root"], js["nf"], js["cm_out1"], js["cm_out2"], 400, 100, PAUSE)
check("from the pause height the shared refusal names the pause", why is not None and "paused" in why, why)
before = copy.deepcopy(st._snapshot())
VERIFIED.clear()
r = st.apply_field_transfer(copy.deepcopy(b))
check("...the exec layer refuses the spend and changes nothing", "paused" in r and st._snapshot() == before, r)
check("...before the proof is even read (no verify call)", VERIFIED == [], VERIFIED)
r = st.apply_field_shield(2500, owner, 11)
check("...while a deposit still lands (an L1 deposit has already escrowed its coins)", "stwo note" in r
      and SP.commit(2500, owner, 11) in st.stwo_pool.commitments, r)

st2 = pool_at(PAUSE - 2)                                     # applying block = PAUSE - 1: not yet paused
r = st2.apply_field_transfer(copy.deepcopy(bundle_for(st2)))
check("below the pause height the same spend applies", r.startswith("field-transfer stwo"), r)

P.STWO_PAUSE_HEIGHT = 1 << 62
st3 = pool_at(PAUSE + 50)
r = st3.apply_field_transfer(copy.deepcopy(bundle_for(st3)))
check("with the pause never (as shipped) a spend at any height applies", r.startswith("field-transfer stwo"), r)

from execnode import execnode as EN
src = inspect.getsource(EN)
i = src.find("stwo_spend_refusal(")
check("the relay's /exec/stwo_spendable decides through the same stwo_spend_refusal", i > 0
      and "stwo_spendable" in src[max(0, i - 2500):i], "")

print("\nALL PASS — the Stwo spend pause is staged and refuses every spend" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
