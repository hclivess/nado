"""The wallet's Stwo prover (static/vendor/stwo_js.wasm) proves only from a FRESH, non-zero seed, once.

The proof's zero-knowledge IS its seed: every random row, FRI mask and Merkle salt is ChaCha20 of those 32 bytes, so
two proofs from one seed share their randomness and their difference is a function of the two witnesses alone; a
constant seed (an uninitialised buffer, a getRandomValues that failed quietly) would publish exactly that. Pins, on
the SHIPPED wasm through static/stark/stwo_js.js:
  1. an all-zero seed is refused (RC_NO_SEED), and a prove with no seed offered is refused before any work;
  2. a seed is accepted once: offering it again while pending, or after the proof that consumed it, is refused
     (RC_SEED_REUSED), and a second prove without a new seed is refused (RC_NO_SEED);
  3. proveWith() — the Worker's path — turns a repeating random source into an error, never a proof;
  4. two honest proofs of ONE witness with two seeds differ (the randomness is used), and both carry the same
     public inputs;
  5. a witness that does not conserve value (v_in != v1 + v2 + fee + unshield) is refused by the WASM itself, even
     when the JS-side check is bypassed.

Run: python3 tests/test_the_stwo_wasm_refuses_a_zero_or_reused_seed.py
"""
import os, sys, tempfile, json, subprocess
_T = tempfile.mkdtemp(prefix="nado-test-stwo-seed-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, _T, ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WASM = os.path.join(ROOT, "static", "vendor", "stwo_js.wasm")

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


if not shutil.which("node"):
    print("SKIP  no node"); sys.exit(0)

PROBE = r"""
import * as S from %s;
import fs from "fs";
import { randomFillSync } from "crypto";
const core = await S.StwoCore.instantiate(fs.readFileSync(%s));
const nsk = S.toHex(randomFillSync(new Uint8Array(32))), me = S.ownerOf(nsk);
const leaves = [S.commit(5n, me, 1n), S.commit(1000n, me, 77n), S.commit(9n, me, 3n)];
const p = S.treePath(leaves, 1);
const wit = { nsk, vIn: 1000n, rho: 77n, sibs: p.sibs, dirs: p.dirs, v1: 600n, o1: me, r1: 11n, v2: 390n, o2: me, r2: 12n, unshield: 0n, fee: 10n };
const W = S.packWitness(wit);
const seed = randomFillSync(new Uint8Array(32));
const o = {};
o.zero = core.seed(new Uint8Array(32));
o.noSeed = core.prove(W, "").rc;
o.first = core.seed(seed);
o.pending = core.seed(seed);
const a = core.prove(W, "");
o.proved = a.rc;
o.after = core.seed(seed);
o.consumed = core.prove(W, "").rc;
const fixed = randomFillSync(new Uint8Array(32));
o.repeating = [];
let second = null;
for (let i = 0; i < 2; i++) {
  try { const out = await S.proveWith(core, W, "", () => fixed.slice()); second = second || out; o.repeating.push("proof"); }
  catch (e) { o.repeating.push(e.message); }
}
const b = S.parseOutput(second);
const A = S.parseOutput(a.out);
o.differ = S.toHex(A.proof) !== S.toHex(b.proof);
o.samePublic = A.root === b.root && A.nf === b.nf && A.cm1 === b.cm1 && A.cm2 === b.cm2 && A.root === p.root;
const bad = W.slice(); bad[32] ^= 1;                       // v_in + 1: no longer conserves
core.seed(randomFillSync(new Uint8Array(32)));
o.nonConserving = core.prove(bad, "").rc;
let jsRefuses = false; try { S.packWitness({ ...wit, v1: 601n }); } catch (e) { jsRefuses = true; }
o.jsRefuses = jsRefuses;
o.RC = S.RC;
console.log(JSON.stringify(o));
""" % (json.dumps("file://" + os.path.join(ROOT, "static", "stark", "stwo_js.js")), json.dumps(WASM))
r = subprocess.run(["node", "--input-type=module", "-e", PROBE], capture_output=True, text=True, timeout=900)
if r.returncode != 0:
    print("FAIL  the probe runs", r.stderr[-1500:]); sys.exit(1)
o = json.loads(r.stdout)
RC = o["RC"]
check("1. an all-zero seed is refused", o["zero"] == RC["NO_SEED"], o["zero"])
check("...and a prove with no seed offered is refused", o["noSeed"] == RC["NO_SEED"], o["noSeed"])
check("2. a fresh seed is accepted once", o["first"] == RC["OK"] and o["proved"] == RC["OK"], (o["first"], o["proved"]))
check("...offering it again while pending is refused", o["pending"] == RC["SEED_REUSED"], o["pending"])
check("...offering it after the proof that used it is refused", o["after"] == RC["SEED_REUSED"], o["after"])
check("...and a second prove without a new seed is refused", o["consumed"] == RC["NO_SEED"], o["consumed"])
check("3. proveWith turns a repeating random source into an error, never a second proof",
      o["repeating"][0] == "proof" and "reused" in o["repeating"][1], o["repeating"])
check("4. two proofs of one witness with two seeds differ", o["differ"])
check("...and carry the same public inputs (the root of the wallet's own path)", o["samePublic"])
check("5. the WASM refuses a witness that does not conserve value", o["nonConserving"] == RC["NOT_A_JOINSPLIT"], o["nonConserving"])
check("...and so does the JS before it gets there", o["jsRefuses"])

print("ALL PASS — the Stwo WASM proves only from a fresh seed" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
