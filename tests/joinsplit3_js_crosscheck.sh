#!/bin/bash
# JS WIDE join-split proof (static/alghash2.js + static/stark/joinsplit3.js) verified by the Python verifier
# byte-for-byte, and the JS note algebra pinned against execnode/stark/znote.py.
set -e
cd "$(dirname "$0")/.."
VENV="${VENV:-python3}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

node tests/joinsplit3_js_crosscheck.mjs "$TMP/js_proof.json"

$VENV - "$TMP/js_proof.json" <<'PY'
import sys, json, os
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
assert Z.to_hex(SW.tree_root([cm_in])) == d["pool_root"] == d["root"], "JS tree != shielded_wide tree"
_r2 = os.environ.get("NADO_PROOF_ROUND2") == "1"
_ldt = os.environ.get("NADO_PROOF_TRACE_LDT") == "1"
_fq = os.environ.get("NADO_PROOF_FULL_QUERY") == "1"
with _stk.with_rules(_stk.Rules(True, True, True, _r2, _ldt, _fq)):
    ok, why = J3.verify_transfer(p, d["root"], d["nf"], d["cm1"], d["cm2"], 0, 0, lambda r: True)
assert ok, "Python REJECTED the JS on-device joinsplit3 proof: " + why
print("joinsplit3 (JS on-device wide proof, Python verify, round2=%s, trace_ldt=%s, JS prove %s ms): OK" % (_r2, _ldt, d["ms"]))
PY
echo "ALL PASSED — browser wide join-split prover ≡ Python (znote algebra + joinsplit3 circuit)"
