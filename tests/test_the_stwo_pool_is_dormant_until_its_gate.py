"""The Stwo shielded pool is dormant until its gate, absent from the exec root until it holds a note, and once live it
alone takes deposits and spends (execnode/state.py rules_stwo_pool, _apply_stwo_shield, _apply_stwo_transfer).

STWO_POOL_HEIGHT was 269000 on gen 28 and 1 from gen 29; G9 inlined it (ExecState.rules_stwo_pool: applying height
>= 1). Pins, on the real exec state (throwaway HOME), with the native verifier stood in by a recording fake:
  1. genesis (a state at cursor -1) does not route to the Stwo pool, and every block from 1 does;
  2. with the pool empty, the exec root is the one the code before the pool computed (empty is absent);
  3. a deposit lands in the Stwo pool (commitment computed from the L1 amount) and a joinsplit3 bundle is refused
     (the pre-gate half — a wide deposit and a refused stwo_js bundle below the gate — retired in G9: gen 28's rules);
  4. a verified transfer spends the nullifier, appends both outputs and records the unshield exit; a second spend of
     the nullifier, an unknown root and a refused proof all change nothing.

Run: python3 tests/test_the_stwo_pool_is_dormant_until_its_gate.py
"""
import os, sys, tempfile, types, copy
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-stwo-gate-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
H = os.environ["HOME"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from execnode.state import ExecState
from execnode import shielded_stwo as SP, exec_root as ER

import _harness
_report = _harness.Report()
check = _report.check


def fresh(cursor):
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=H), "s.json"))
    st.cursor = cursor
    return st


check("1. the Stwo pool is in force from block 1, never at genesis",
      not fresh(-1).rules_stwo_pool() and fresh(0).rules_stwo_pool() and fresh(10 ** 9).rules_stwo_pool())

st = fresh(500)
with_pool = st.state_root()
del st.stwo_pool
st._touch()
check("2. an empty Stwo pool leaves the exec root exactly as before it existed", st.state_root() == with_pool)

calls = []
fake = types.ModuleType("execnode.stark.stwo_js_native")
VERDICT = [True]
HEIGHTS = []                                 # the height each verify was asked at (STWO_JS_128_HEIGHT picks the config)


def _verify(proof, root, nf, cm1, cm2, unshield, fee, dest, height):
    calls.append((root, nf, cm1, cm2, unshield, fee, dest))
    HEIGHTS.append(height)
    return (True, "") if VERDICT[0] else (False, "proof refused")
fake.verify = _verify
sys.modules["execnode.stark.stwo_js_native"] = fake
import execnode.stark as _stk
_stk.stwo_js_native = fake

GATE = 1000                                  # a test height (the pool holds from block 1)
nsk = "11" * 32
owner = SP.owner_of(nsk)

# 3's pre-gate half (a wide deposit and a refused stwo_js bundle below the gate) retired in G9: generation 28's rules
st = fresh(GATE - 1)
r = st.apply_field_shield(5000, owner, 7)
cm_in = SP.commit(5000, owner, 7)
check("3. a deposit lands in the Stwo pool, its commitment computed from the L1 amount",
      st.stwo_pool.commitments == [cm_in] and not hasattr(st, "wide_pool"), r)   # (the wide pool is deleted, G9 slice 5)
check("...and the exec root now carries the Stwo pool", st.state_root() != with_pool)
TF = st.apply_field_transfer if hasattr(st, "apply_field_transfer") else None
r = TF({"stark": {"joinsplit3": {}}})
check("...a joinsplit3 bundle is refused at the gate", "takes a stwo_js bundle" in r, r)

nf = SP.nullifier(nsk, 7)
c1, c2 = SP.commit(3000, owner, 8), SP.commit(1500, owner, 9)
from ops.address_ops import make_address
DEST = make_address("ab" * 1312)                     # a real format-2 address (any public key derives one)
bundle = {"stark": {"stwo_js": {"proof": "ab" * 8, "root": st.stwo_pool.root(), "nf": nf, "cm_out1": c1, "cm_out2": c2,
                                "unshield": 400, "fee": 100}}, "withdraw_addr": DEST}
before = copy.deepcopy(st._snapshot())
VERDICT[0] = False
r = TF(copy.deepcopy(bundle))
check("4. a refused proof changes nothing", "proof refused" in r and st._snapshot() == before, r)
r = TF(dict(copy.deepcopy(bundle), stark={"stwo_js": dict(bundle["stark"]["stwo_js"], root="ee" * 32)}))
check("...an unknown anchor root changes nothing (and is refused before the proof)", "unknown anchor" in r and st._snapshot() == before, r)
VERDICT[0] = True
calls.clear()
HEIGHTS.clear()
r = TF(copy.deepcopy(bundle))
check("...the proof is verified at the height of the block it applies in (which selects its node config)",
      HEIGHTS == [st.applying_height()], (HEIGHTS, st.applying_height()))
uw = list(st.unshield_withdrawals.values())
check("a verified transfer spends the nullifier and appends both outputs",
      st.stwo_pool.has_nullifier(nf) and st.stwo_pool.commitments == [cm_in, c1, c2], r)
check("...the verifier saw exactly the bundle's public inputs, destination included",
      calls and calls[-1] == (bundle["stark"]["stwo_js"]["root"], nf, c1, c2, 400, 100, DEST), calls)
check("...and the unshield is a provable exit record", uw and uw[-1] == {"addr": DEST, "amount": 400}, uw)
snap = copy.deepcopy(st._snapshot())
r = TF(copy.deepcopy(bundle))
check("a second spend of the nullifier changes nothing", "double-spend" in r and st._snapshot() == snap, r)
again = ExecState(os.path.join(tempfile.mkdtemp(dir=H), "s.json"))
again._restore(copy.deepcopy(st._snapshot()))
check("the pool survives a snapshot round trip", again.stwo_pool.root() == st.stwo_pool.root()
      and again.stwo_pool.nullifiers == st.stwo_pool.nullifiers)

print("ALL PASS — the Stwo pool is live from block 1" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
