#!/bin/bash
# JS WIDE join-split proof (static/alghash2.js + static/stark/joinsplit3.js) verified by the Python verifier
# byte-for-byte, and the JS note algebra pinned against execnode/stark/znote.py. At BOTH depths the wide pool has: 12
# below ZK_HARDEN_HEIGHT and 48 from it (the wallet builds at the depth the exec node reports), each through the node's
# real seam (joinsplit_transfer pins D to the depth in force, passed as the pool's).
set -e
cd "$(dirname "$0")/.."
VENV="${VENV:-python3}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

for DEPTH in 12 48; do
node tests/joinsplit3_js_crosscheck.mjs "$TMP/js_proof.json" "$DEPTH"

$VENV - "$TMP/js_proof.json" <<'PY'
import sys, json, os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-js3-")          # ASSIGN before any repo import (CLAUDE.md rule 4)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
sys.path.insert(0, ".")
from execnode.stark import joinsplit3 as J3, znote as Z, stark as _stk
from execnode import shielded_wide as SW

d = json.load(open(sys.argv[1]))
p = d["proof"]
for k in ("T", "W", "N", "blowup", "deg_bound", "D"):
    p[k] = int(p[k])
def _c(v):
    return [int(x) for x in v] if isinstance(v, (list, tuple)) else int(v)
fr = p["fri"]
fr["offset"] = int(fr["offset"]); fr["pow"] = int(fr["pow"])
fr["final"] = [_c(x) for x in fr["final"]]
for q in fr["queries"]:
    q["idx"] = int(q["idx"])
    for s in q["steps"]:
        s["lo"] = _c(s["lo"]); s["hi"] = _c(s["hi"])
for op in p["openings"]:
    op["lo"] = int(op["lo"])
    for c in op["cols"]:
        c["cur"] = _c(c["cur"]); c["nxt"] = _c(c["nxt"])
# the JS note algebra must equal znote's
nsk, rho = 0xCAFE, 0x1111
o2 = Z.owner_of(nsk)
assert Z.to_hex(o2) == d["owner"], "JS owner_of != znote.owner_of"
cm_in = Z.commit(1000, o2, rho)
assert Z.to_hex(cm_in) == d["cm_in"], "JS commit != znote.commit"
assert Z.to_hex(Z.nullifier(nsk, rho)) == d["nf"], "JS nullifier != znote.nullifier"
depth = int(d["depth"])
assert int(p["D"]) == depth, "the JS proof is not at the depth it was asked for"
leaves = [Z.from_hex(x) for x in d["leaves"]]
assert Z.to_hex(leaves[3]) == d["cm_in"]
pool = SW.WideShieldedPool(leaves, depth=depth)
assert Z.to_hex(SW.tree_root(leaves, depth)) == Z.to_hex(pool.root()) == d["pool_root"] == d["root"], "JS tree != shielded_wide tree"
_r2 = os.environ.get("NADO_PROOF_ROUND2") == "1"
_ldt = os.environ.get("NADO_PROOF_TRACE_LDT") == "1"
_fq = os.environ.get("NADO_PROOF_FULL_QUERY") == "1"
from execnode import shielded
bundle = {"stark": {"joinsplit3": {"proof": p, "root": d["root"], "nf": d["nf"], "cm_out1": d["cm1"], "cm_out2": d["cm2"],
                                   "public_value": 0, "fee": 0}}}
public = {"root": d["root"], "nullifiers": [d["nf"]], "out_commitments": [d["cm1"], d["cm2"]], "public_value": 0, "fee": 0}
with _stk.with_rules(_stk.Rules(True, True, True, _r2, _ldt, _fq)):
    ok, why = shielded.verify_transfer(public, bundle, pool.knows_root, wide_depth=depth)
    assert ok, "Python REJECTED the JS on-device joinsplit3 proof: " + why
    other = 48 if depth == 12 else 12
    bad, why2 = shielded.verify_transfer(public, bundle, pool.knows_root, wide_depth=other)
    assert not bad and "depth" in why2, "a proof at the wrong depth for the pool must be refused: " + why2
print("joinsplit3 (JS on-device wide proof at depth %d, Python verify, round2=%s, trace_ldt=%s, JS prove %s ms): OK" % (depth, _r2, _ldt, d["ms"]))
PY
done
echo "ALL PASSED — browser wide join-split prover ≡ Python (znote algebra + joinsplit3 circuit)"
