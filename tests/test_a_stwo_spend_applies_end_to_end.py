"""A Stwo spend applies end to end: deposits build the pool, the real prover proves a spend, the exec layer verifies it
with the real native verifier and moves exactly the value the proof binds (execnode/state.py _apply_stwo_transfer,
execnode/shielded_stwo.py, native/stwo_js).

Every piece has its own tests; this one walks the whole path, because the parts can each pass while the path is
wrong — wiring it found that the prototype's public value was value ENTERING the pool while the exec layer paid it out
as an exit (a mint), fixed in native/stwo_js before anything shipped. Pins:
  1. eleven real deposits rebuild fixture b's note tree, and the pool's root is the root inside the real proof;
  2. the spend applies through the native verifier: the nullifier is spent, both outputs appended, the unshield
     recorded as an exit to the bound destination, and the pool's value falls by unshield + fee;
  3. the same spend again, and the proof re-pointed at another destination, change nothing.
SKIPs without a stable cargo (the verifier) or the nightly toolchain (the prover).

Run: python3 tests/test_a_stwo_spend_applies_end_to_end.py
"""
import os, sys, tempfile, struct, copy, json, subprocess
_REAL_HOME = os.path.expanduser("~")
_T = tempfile.mkdtemp(prefix="nado-test-stwo-e2e-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, _T, ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests._stwo_js_build import Env

import _harness
_report = _harness.Report()
check = _report.check


env = Env(_REAL_HOME)
if not env.have_stable():
    print("SKIP  no stable cargo: the verifier cannot be built here"); sys.exit(0)
nbin = env.nightly_bin()
if not nbin:
    print("SKIP  no nightly-2026-01-15 toolchain: the prover cannot be built here"); sys.exit(0)
so, _s, log = env.build_verifier()
exe, _p, plog = env.build_prover(nbin)
if not so or not exe:
    print("FAIL  build", (log or "")[-500:], (plog or "")[-500:]); sys.exit(1)
os.environ["NADO_STWO_JS_LIB"] = so

import protocol as P
from execnode.state import ExecState
from execnode import shielded_stwo as SP
from ops.address_ops import make_address

DEST = make_address("cd" * 1312)
out = tempfile.mkdtemp(dir=_T)
r = subprocess.run([exe, "b", DEST, out], capture_output=True, text=True, timeout=900)
assert r.returncode == 0, r.stderr[-1000:]
proof = open(os.path.join(out, "proof.bin"), "rb").read()
pub = json.load(open(os.path.join(out, "public.json")))

# fixture b (native/stwo_js/src/prover.rs fixture_b): 11 notes of owner o1 = H(21, [0xFEED, 9 x7]) with value 3i+1 and
# rho i, except position 10 = the spent note commit(v_in, owner(nsk), rho)
w = lambda *x: struct.pack("<8I", *x).hex()
o1 = SP.owner_of(w(0xFEED, 9, 9, 9, 9, 9, 9, 9))
nsk = w(0x12345678, 0x9ABCDEF0, 0x0F0F0F0F, 0xDEADBEEF, 0x0BADF00D, 0x77777777, 0x2468ACE0, 0x13579BDF)
v_in, rho = 0x0123456789ABCDEF & ((1 << 61) - 1), 0x5EED5EED5EED

GATE = 1000
P.STWO_POOL_HEIGHT = GATE
st = ExecState(os.path.join(_T, "s.json"))
st.cursor = GATE - 1
for i in range(10):
    st.apply_field_shield(i * 3 + 1, o1, i)
st.apply_field_shield(v_in, SP.owner_of(nsk), rho)
check("1. eleven deposits rebuild fixture b's tree: the pool's root is the root inside the real proof",
      st.stwo_pool.root() == pub["root"], (st.stwo_pool.root(), pub["root"]))

v0 = st.pool_value
bundle = {"stark": {"stwo_js": {"proof": proof.hex(), "root": pub["root"], "nf": pub["nf"], "cm_out1": pub["cm1"],
                                "cm_out2": pub["cm2"], "unshield": pub["unshield"], "fee": pub["fee"]}},
          "withdraw_addr": DEST}
r = st.apply_field_transfer(copy.deepcopy(bundle))
uw = list(st.unshield_withdrawals.values())
check("2. the spend applies through the native verifier", "field-transfer stwo" in r, r)
check("...the nullifier is spent and both outputs appended",
      st.stwo_pool.has_nullifier(pub["nf"]) and st.stwo_pool.commitments[-2:] == [pub["cm1"], pub["cm2"]])
check("...the unshield is an exit to the bound destination", uw and uw[-1] == {"addr": DEST, "amount": pub["unshield"]}, uw)
check("...and the pool's value falls by exactly unshield + fee", v0 - st.pool_value == pub["unshield"] + pub["fee"],
      (v0, st.pool_value))
snap = copy.deepcopy(st._snapshot())
r = st.apply_field_transfer(copy.deepcopy(bundle))
check("3. the same spend again changes nothing", "double-spend" in r and st._snapshot() == snap, r)

st2 = ExecState(os.path.join(_T, "s2.json"))
st2.cursor = GATE - 1
for i in range(10):
    st2.apply_field_shield(i * 3 + 1, o1, i)
st2.apply_field_shield(v_in, SP.owner_of(nsk), rho)
before = copy.deepcopy(st2._snapshot())
other = make_address("ef" * 1312)
r = st2.apply_field_transfer(dict(copy.deepcopy(bundle), withdraw_addr=other))
check("...and the proof re-pointed at another destination changes nothing", r.startswith("skip") and st2._snapshot() == before, r)

print("ALL PASS — a Stwo spend applies end to end" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
