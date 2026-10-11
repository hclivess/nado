"""A Stwo spend PROVED BY THE WALLET'S SHIPPED WASM (static/vendor/stwo_js.wasm, driven by static/stark/stwo_js.js in
Node) verifies through the node's Python wrapper and applies through the exec layer — the whole wallet path short of
the browser Worker, against a local ExecState with STWO_POOL_HEIGHT moved to a test height.

The pieces each have their own tests (the JS algebra against the Python, the Rust prover against the verifier); this
walks the path a user's coins take, because the parts can each pass while the path is wrong. Pins:
  1. deposits land in the Stwo pool at the gate, and the wallet's JS (treePath over the pool's leaves) proves against
     a root the pool holds;
  2. an UNSHIELD proved in WASM verifies with execnode/stark/stwo_js_native.verify and applies: the nullifier is
     spent, both outputs appended, the exit recorded to the bound address, the pool's value down by unshield + fee;
  3. the wallet then spends its CHANGE note privately (unshield 0, empty destination) — a note the exec layer appended
     from the first proof — and that applies too;
  4. the first proof re-pointed at another withdraw_addr, and replayed, change nothing;
  5. the WASM's aux_of == the JS auxOf for the destination (the binding the node checks).
SKIPs without node or a stable cargo (the node's verifier); the WASM is the SHIPPED file, not a fresh build (its
provenance is tests/test_the_shipped_stwo_wasm_is_a_build_of_the_committed_sources.py).

Run: python3 tests/test_a_wallet_stwo_proof_made_in_wasm_applies_end_to_end.py
"""
import os, sys, tempfile, json, subprocess, copy, secrets
_REAL_HOME = os.path.expanduser("~")
_T = tempfile.mkdtemp(prefix="nado-test-stwo-wallet-e2e-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, _T, ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tests._stwo_js_build import Env, SHIPPED_WASM

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {str(detail)[:600]}"))
    fails += 0 if ok else 1


if not shutil.which("node"):
    print("SKIP  no node"); sys.exit(0)
env = Env(_REAL_HOME)
if not env.have_stable():
    print("SKIP  no stable cargo: the node's verifier cannot be built here"); sys.exit(0)
so, _s, log = env.build_verifier()
if not so:
    print("FAIL  verifier build", (log or "")[-800:]); sys.exit(1)
os.environ["NADO_STWO_JS_LIB"] = so

import protocol as P
from execnode.state import ExecState
from execnode import shielded_stwo as SP
from execnode.stark import stwo_js_native
from ops.address_ops import make_address

MODULE = "file://" + os.path.join(ROOT, "static", "stark", "stwo_js.js")
PROBE = r"""
import * as S from %s;
import fs from "fs";
import { randomFillSync } from "crypto";
const c = JSON.parse(process.argv[1]);
const core = await S.StwoCore.instantiate(fs.readFileSync(c.wasm));
const rand = (n) => randomFillSync(new Uint8Array(n));
const t0 = performance.now();
const r = await S.proveSpend(c.spend, c.leaves, c.pos, (w, d) => S.proveWith(core, w, d, rand));
const ms = performance.now() - t0;
console.log(JSON.stringify({ bundle: r.bundle, ms, aux_wasm: core.aux(c.spend.dest || ""), aux_js: S.auxOf(c.spend.dest || "") }));
""" % json.dumps(MODULE)


def wallet_prove(spend, leaves, pos):
    case = {"wasm": SHIPPED_WASM, "spend": spend, "leaves": leaves, "pos": pos}
    r = subprocess.run(["node", "--input-type=module", "-e", PROBE, json.dumps(case)], capture_output=True, text=True,
                       timeout=900)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


GATE = 1000
P.STWO_POOL_HEIGHT = GATE
nsk = secrets.token_hex(32)                       # the wallet's 256-bit spend key (never leaves this process)
me = SP.owner_of(nsk)
other = SP.owner_of(secrets.token_hex(32))
v_in, rho = 10 ** 12, secrets.randbits(64)


def fresh_state(name):
    """Eight deposits at the gate, the wallet's note fifth (an ExecState holds a lock: it is rebuilt, never copied)."""
    s = ExecState(os.path.join(_T, name))
    s.cursor = GATE - 1
    for i in range(4):
        s.apply_field_shield(1000 + i, other, i + 1)
    r = s.apply_field_shield(v_in, me, rho)
    for i in range(3):
        s.apply_field_shield(77 + i, other, 100 + i)
    return s, r


st, r0 = fresh_state("s.json")
leaves = list(st.stwo_pool.commitments)
pos = leaves.index(SP.commit(v_in, me, rho))
check("1. deposits land in the Stwo pool at the gate", "stwo note" in r0 and len(leaves) == 8, r0)

DEST = make_address("cd" * 1312)
take, fee = 4 * 10 ** 11, 1234
change = v_in - take - fee
r1, r2 = secrets.randbits(64), secrets.randbits(64)
spend1 = {"nsk": nsk, "vIn": str(v_in), "rho": str(rho), "v1": str(change), "o1": me, "r1": str(r1),
          "v2": "0", "o2": me, "r2": str(r2), "unshield": str(take), "fee": str(fee), "dest": DEST}
out1 = wallet_prove(spend1, leaves, pos)
b1 = out1["bundle"]
js1 = b1["stark"]["stwo_js"]
print(f"      WASM prove (Node, single thread, incl. self-verify): {out1['ms'] / 1000:.2f} s, "
      f"proof {len(js1['proof']) // 2} bytes")
check("...the wallet proves against a root the pool holds", st.stwo_pool.knows_root(js1["root"]), js1["root"])
check("5. the WASM's aux_of == the JS auxOf for the destination", out1["aux_wasm"] == out1["aux_js"], out1)
check("2. the bundle has exactly the fields _apply_stwo_transfer reads",
      set(b1) == {"stark", "withdraw_addr"} and set(js1) == {"proof", "root", "nf", "cm_out1", "cm_out2", "unshield", "fee"}
      and b1["withdraw_addr"] == DEST, b1.keys())
ok, why = stwo_js_native.verify(bytes.fromhex(js1["proof"]), js1["root"], js1["nf"], js1["cm_out1"], js1["cm_out2"],
                                int(js1["unshield"]), int(js1["fee"]), DEST)
check("...the WASM proof verifies through execnode/stark/stwo_js_native.verify", ok, why)

st_redirect, _ = fresh_state("s2.json")
v0 = st.pool_value
res = st.apply_field_transfer(json.loads(json.dumps(b1)))          # the DA path carries it as JSON
uw = list(st.unshield_withdrawals.values())
check("...and applies through the exec layer", "field-transfer stwo" in res, res)
check("...the nullifier is spent and both outputs appended",
      st.stwo_pool.has_nullifier(SP.nullifier(nsk, rho)) and st.stwo_pool.commitments[-2:] == [js1["cm_out1"], js1["cm_out2"]])
check("...the unshield is an exit to the bound address", uw and uw[-1] == {"addr": DEST, "amount": take}, uw)
check("...the pool's value falls by exactly unshield + fee", v0 - st.pool_value == take + fee, (v0, st.pool_value))

snap = copy.deepcopy(st._snapshot())
res = st.apply_field_transfer(json.loads(json.dumps(b1)))
check("4. the same proof again changes nothing", "double-spend" in res and st._snapshot() == snap, res)
before = copy.deepcopy(st_redirect._snapshot())
res = st_redirect.apply_field_transfer(dict(json.loads(json.dumps(b1)), withdraw_addr=make_address("ef" * 1312)))
check("...and re-pointed at another withdraw_addr changes nothing", res.startswith("skip") and st_redirect._snapshot() == before, res)

# 3. the change note (out1 of the first proof, appended by the exec layer) spent privately to another owner
leaves2 = list(st.stwo_pool.commitments)
pos2 = leaves2.index(js1["cm_out1"])
pay = 10 ** 11
spend2 = {"nsk": nsk, "vIn": str(change), "rho": str(r1), "v1": str(pay), "o1": other, "r1": str(secrets.randbits(64)),
          "v2": str(change - pay), "o2": me, "r2": str(secrets.randbits(64)), "unshield": "0", "fee": "0", "dest": DEST}
out2 = wallet_prove(spend2, leaves2, pos2)
b2 = out2["bundle"]
check("3. a private transfer carries no withdraw_addr (bound to the empty destination)", "withdraw_addr" not in b2, b2.keys())
v1 = st.pool_value
res = st.apply_field_transfer(json.loads(json.dumps(b2)))
check("...the change note, spent privately, applies", "field-transfer stwo" in res and st.pool_value == v1, res)
check("...and its nullifier is the wallet's for that note", st.stwo_pool.has_nullifier(SP.nullifier(nsk, r1)))

print("ALL PASS — a wallet Stwo proof made in WASM applies end to end" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
