#!/bin/bash
# JS 2-output join-split proof (with the C-3 range gadget) verified by the Python verifier byte-for-byte.
set -e
cd "$(dirname "$0")/.."
VENV="${VENV:-python3}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

node tests/joinsplit2_js_crosscheck.mjs "$TMP/js_proof.json"

$VENV - "$TMP/js_proof.json" <<'PY'
import sys, json
sys.path.insert(0, ".")
from execnode.stark import joinsplit2 as J2

d = json.load(open(sys.argv[1]))
p = d["proof"]
# normalise the JS-serialised proof (big field ints came over as strings)
for k in ("T", "W", "N", "blowup", "deg_bound", "D"):
    p[k] = int(p[k])
def _c(v):                    # base scalar or GF(p^D) limb tuple (arrays after JSON) — coerce element-wise
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

root, nf, cm1, cm2 = int(d["root"]), int(d["nf"]), int(d["cm1"]), int(d["cm2"])
import os
from execnode.stark import stark as _stk
_r2 = os.environ.get("NADO_PROOF_ROUND2") == "1"
_ldt = os.environ.get("NADO_PROOF_TRACE_LDT") == "1"
_fq = os.environ.get("NADO_PROOF_FULL_QUERY") == "1"
with _stk.with_rules(_stk.Rules(True, True, True, _r2, _ldt, _fq)):        # the rules the JS prover was told to use
    ok, why = J2.verify_transfer(p, root, nf, cm1, cm2, 0, 0, lambda r: True)
assert ok, "Python REJECTED the JS on-device joinsplit2 proof: " + why
print("joinsplit2 (JS on-device proof + range gadget, Python verify, round2=%s, trace_ldt=%s): OK" % (_r2, _ldt))
PY
echo "ALL PASSED — browser 2-output prover ≡ Python (C-3 range gadget included)"
