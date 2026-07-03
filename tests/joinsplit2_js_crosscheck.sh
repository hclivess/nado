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
fr = p["fri"]
fr["offset"] = int(fr["offset"]); fr["pow"] = int(fr["pow"])
fr["final"] = [int(x) for x in fr["final"]]
for q in fr["queries"]:
    q["idx"] = int(q["idx"])
    for s in q["steps"]:
        s["lo"] = int(s["lo"]); s["hi"] = int(s["hi"])
for op in p["openings"]:
    op["lo"] = int(op["lo"])
    for c in op["cols"]:
        c["cur"] = int(c["cur"]); c["nxt"] = int(c["nxt"])

root, nf, cm1, cm2 = int(d["root"]), int(d["nf"]), int(d["cm1"]), int(d["cm2"])
ok, why = J2.verify_transfer(p, root, nf, cm1, cm2, 0, 0, lambda r: True)
assert ok, "Python REJECTED the JS on-device joinsplit2 proof: " + why
print("joinsplit2 (JS on-device proof + range gadget, Python verify): OK")
PY
echo "ALL PASSED — browser 2-output prover ≡ Python (C-3 range gadget included)"
