"""A Stwo spend can never move out of the Stwo pool more than Stwo deposits put in (ExecState.stwo_value), even with a
proof the verifier wrongly accepts — defence in depth behind the circuit's conservation (review 2026-10-11).

pool_value counts the frozen wide pool's notes too, so a cap on pool_value would let a forged Stwo proof drain value
the wide pool holds. stwo_value is the Stwo pool's own total: +amount per Stwo deposit, -(unshield + fee) per Stwo
spend, checked in ExecState.stwo_spend_refusal BEFORE any mutation. Pins:
  1. DRAINING (verifier forced to accept, i.e. a soundness failure): a spend exiting stwo_value + 1 is refused and the
     state is byte for byte unchanged, although pool_value (wide + Stwo) would cover it; exiting exactly stwo_value
     applies and leaves stwo_value 0 — the cap is the bound, not some other check;
  2. HONEST (a real proof from the shipped wallet WASM, verified by the real native verifier): the spend applies and
     stwo_value falls by exactly unshield + fee;
  3. stwo_value is in the snapshot (absent when zero, so pre-pool snapshots keep their bytes) and survives a clone;
     a revert through the snapshot restores it exactly;
  4. it is in the exec root when non-zero (two states differing only in it differ in root) and absent when zero.
Part 2 SKIPs without node or a stable cargo (the verifier).

Run: python3 tests/test_a_stwo_spend_cannot_exit_more_than_the_stwo_pool_holds.py
"""
import os, sys, tempfile, copy, json, secrets, shutil
_REAL_HOME = os.path.expanduser("~")
_T = tempfile.mkdtemp(prefix="nado-test-stwo-value-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
import atexit; atexit.register(shutil.rmtree, _T, ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {str(detail)[:600]}"))
    fails += 0 if ok else 1


from execnode.state import ExecState
from execnode import shielded_stwo as SP, exec_root as ER
from execnode.stark import stwo_js_native
from ops.address_ops import make_address

GATE = 1000
DEST = make_address("cd" * 1312)
rh = lambda: secrets.token_hex(32)


def fresh(name, stwo_deposits):
    """A state with value in another (frozen) pool and `stwo_deposits` Stwo notes. The other pool's note is deposited at
    height 0, the only height below the Stwo pool since G9 inlined STWO_POOL_HEIGHT as block 1 (it lands in the legacy
    field pool there); generation 28 put a wide note below its gate instead — the cap must hold against either."""
    s = ExecState(os.path.join(_T, name))
    s.cursor = -1
    r = s.apply_field_shield(10 ** 12, 7, 1)                        # a non-Stwo note: value pool_value counts, Stwo must not reach
    assert "skip" not in r, r
    s.cursor = GATE - 1
    for (v, owner, rho) in stwo_deposits:
        r = s.apply_field_shield(v, owner, rho)
        assert "stwo note" in r, r
    return s


def forged(st, unshield, fee=0):
    return {"stark": {"stwo_js": {"proof": "ab" * 16, "root": st.stwo_pool.root(), "nf": rh(), "cm_out1": rh(),
                                  "cm_out2": rh(), "unshield": str(unshield), "fee": str(fee)}}, "withdraw_addr": DEST}


# ---- 1. draining, with a verifier that accepts anything --------------------------------------------------------------
_real_verify = stwo_js_native.verify
stwo_js_native.verify = lambda *a, **k: (True, "")
try:
    st = fresh("drain.json", [(500, rh(), 1), (700, rh(), 2)])
    check("setup: stwo_value counts the Stwo deposits only, pool_value both pools",
          st.stwo_value == 1200 and st.pool_value == 10 ** 12 + 1200, (st.stwo_value, st.pool_value))
    before = copy.deepcopy(st._snapshot())
    r = st.apply_field_transfer(forged(st, 1200, 1))
    check("1. a spend exiting stwo_value + 1 (unshield + fee) is refused, though pool_value would cover it",
          r.startswith("skip") and "more than the Stwo pool holds" in r, r)
    check("...and the refused spend changed nothing", st._snapshot() == before)
    r = st.apply_field_transfer(forged(st, 1199, 1))
    check("...exiting exactly stwo_value applies (the cap is the bound)", "field-transfer stwo" in r and st.stwo_value == 0, r)
    check("...and pool_value fell by the same amount: the wide pool's value is untouched", st.pool_value == 10 ** 12)
    r = st.apply_field_transfer(forged(st, 1))
    check("...after which not one more raw leaves the Stwo pool", r.startswith("skip") and "more than" in r, r)
finally:
    stwo_js_native.verify = _real_verify

# ---- 3. snapshot, clone, revert ------------------------------------------------------------------------------------
st = fresh("snap.json", [(900, rh(), 3)])
snap = st._snapshot()
check("3. stwo_value is in the snapshot when non-zero", snap.get("stwo_value") == 900, snap.get("stwo_value"))
check("...and survives a clone", st.clone().stwo_value == 900)
empty = ExecState(os.path.join(_T, "empty.json"))
check("...and is ABSENT from the snapshot at zero (a pre-pool snapshot keeps its bytes)", "stwo_value" not in empty._snapshot())
saved = copy.deepcopy(st._snapshot())
stwo_js_native.verify = lambda *a, **k: (True, "")
try:
    st.apply_field_transfer(forged(st, 400))
finally:
    stwo_js_native.verify = _real_verify
check("...a spend lowers it", st.stwo_value == 500, st.stwo_value)
st._restore(copy.deepcopy(saved))
check("...and a revert through the snapshot restores it exactly", st.stwo_value == 900 and st._snapshot() == saved)

# ---- 4. the exec root ------------------------------------------------------------------------------------------
a = fresh("ra.json", [(900, "11" * 32, 3)])
b = fresh("rb.json", [(900, "11" * 32, 3)])
b.wide_pool, b.field_pool = a.wide_pool, a.field_pool            # identical but for what we set next
check("4. two identical states project identically (sanity)", ER.records_projection(a) == ER.records_projection(b))
b.stwo_value = 901
check("...and differ when only stwo_value differs", ER.records_projection(a) != ER.records_projection(b))
z = fresh("rz.json", [])
proj = ER.records_projection(z)
z.stwo_value = 0
check("...and zero is absent from the projection", ER.records_projection(z) == proj
      and ER.record_key(ER.T_DIGEST, "stwo_value", "0") not in proj)

# ---- 2. an honest spend, really proved and really verified -----------------------------------------------------
if not shutil.which("node"):
    print("SKIP  2: no node")
else:
    from tests._stwo_js_build import Env, wallet_prove
    env = Env(_REAL_HOME)
    so = env.build_verifier()[0] if env.have_stable() else None
    if not so:
        print("SKIP  2: no stable cargo (the verifier)")
    else:
        os.environ["NADO_STWO_JS_LIB"] = so
        nsk = secrets.token_hex(32)
        me, v_in, rho = SP.owner_of(nsk), 10 ** 11, secrets.randbits(64)
        st = fresh("honest.json", [(1000, rh(), 7), (v_in, me, rho), (2000, rh(), 8)])
        leaves = list(st.stwo_pool.commitments)
        take, fee = 3 * 10 ** 10, 55
        spend = {"nsk": nsk, "vIn": str(v_in), "rho": str(rho), "v1": str(v_in - take - fee), "o1": me,
                 "r1": str(secrets.randbits(64)), "v2": "0", "o2": me, "r2": str(secrets.randbits(64)),
                 "unshield": str(take), "fee": str(fee), "dest": DEST}
        out = wallet_prove(spend, leaves, leaves.index(SP.commit(v_in, me, rho)), st.applying_height())
        sv0 = st.stwo_value
        r = st.apply_field_transfer(json.loads(json.dumps(out["bundle"])))
        check("2. an honest spend (real proof, real verifier) applies under the cap", "field-transfer stwo" in r, r)
        check("...and stwo_value falls by exactly unshield + fee", sv0 - st.stwo_value == take + fee
              and st.stwo_value == 1000 + 2000 + v_in - take - fee, (sv0, st.stwo_value))

print("ALL PASS — a Stwo spend cannot exit more than the Stwo pool holds" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
