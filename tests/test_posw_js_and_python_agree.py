"""The browser's sequential-work prover (static/posw.js) and the node's (ops/posw.py) are ONE function: a proof made
by either verifies under the other, the two are byte-identical for the same challenge, and a tampered proof fails
in both.

Registration verifies a PoSW in consensus (ops/transaction_ops.py, register), so a browser proof the node rejects
is a user who cannot register, and one the node accepts that the browser's own verifier rejects is a wallet that
refuses its own work. tests/posw_xlang.mjs (the node-side driver: `prove` prints a proof, `verify <file>` prints
OK/FAIL) existed for this cross-check since 1b2c5c3a but nothing ever ran it — it did not match the runner's glob.

Run: python3 tests/test_posw_js_and_python_agree.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): a throwaway HOME, never the live node's
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-posw-xlang-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import copy, json, subprocess, sys

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS))
from ops import posw

# the driver's fixed statement (tests/posw_xlang.mjs): T, S, K, address, anchor
T, S, K, ADDR, ANCHOR = 1000, 10, 8, "ndoalice", "0" * 64
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def node(*args):
    r = subprocess.run(["node", os.path.join(TESTS, "posw_xlang.mjs"), *args], capture_output=True, text=True,
                       cwd=os.path.dirname(TESTS), timeout=300)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-400:])
    return r.stdout


def js_verifies(proof):
    p = os.path.join(os.environ["HOME"], "proof.json")
    with open(p, "w") as f:
        json.dump(proof, f)
    return node("verify", p) == "OK"


ch = posw.challenge_bytes(ADDR, ANCHOR)
py_proof = posw.prove(ch, T, S, K)
js_proof = json.loads(node("prove"))

check("the browser and the node make the byte-identical proof for one challenge", js_proof == py_proof,
      (js_proof.get("root"), py_proof.get("root")))
check("the node verifies the browser's proof", posw.verify(ch, js_proof, T, S, K))
check("the browser verifies the node's proof", js_verifies(py_proof))

bad = copy.deepcopy(py_proof)
o = bad["openings"][-1]
o["cj1"] = ("0" if o["cj1"][0] != "0" else "1") + o["cj1"][1:]
check("a tampered proof fails in the node", not posw.verify(ch, bad, T, S, K))
check("a tampered proof fails in the browser", not js_verifies(bad))
check("a proof for another address fails in the node", not posw.verify(posw.challenge_bytes("ndobob", ANCHOR), py_proof, T, S, K))

print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
