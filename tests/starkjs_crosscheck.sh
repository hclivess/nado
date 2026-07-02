#!/bin/bash
# Cross-check the browser STARK prover (static/stark/*.js) against the Python verifier byte-for-byte
# (doc/wasm-prover.md). Phase 1: field/NTT. Phase 2: a JS-generated FRI proof accepted by Python fri.verify.
set -e
cd "$(dirname "$0")/.."
VENV="${VENV:-python3}"
TMP="$(mktemp -d)"

# Phase 1 — field/NTT ≡ Python
node --input-type=module -e '
import * as F from "./static/stark/field.js";
let f=0;const eq=(n,g,w)=>{if(g!==w){f++;console.log("FAIL "+n);}};
eq("rou8",F.primitiveRootOfUnity(8),18446744069397807105n);
eq("inv7",F.inv(7n),2635249152773512046n);
const c=[1n,2n,3n,4n,5n,6n,7n,8n];
eq("interp(eval)",JSON.stringify(F.interpolate(F.evaluate(c)).map(String)),JSON.stringify(c.map(String)));
console.log(f?f+" FIELD FAILED":"Phase 1 field/NTT: OK");if(f)process.exit(1);
'
# Phase 2 — JS FRI proof, verified by Python
node --input-type=module -e '
import { blake2b, bytesToHex } from "./static/vendor/nado-crypto.js";
import * as F from "./static/stark/field.js";
import { initHashing } from "./static/stark/hashing.js";
import * as fri from "./static/stark/fri.js";
import fs from "fs";
function canon(d){const t=typeof d;if(t==="bigint")return d.toString();if(t==="number")return String(d);if(t==="string")return JSON.stringify(d);if(Array.isArray(d))return "["+d.map(canon).join(",")+"]";throw 0;}
const enc=new TextEncoder();
initHashing((data,size=32)=>bytesToHex(blake2b(enc.encode(canon(data)),{dkLen:size})));
const coeffs=[];for(let i=0;i<16;i++)coeffs.push(BigInt(i*7+1));
const proof=fri.prove(F.cosetEvaluate(coeffs,64,F.GEN),F.GEN,4,24);
const ser=x=>typeof x==="bigint"?x.toString():Array.isArray(x)?x.map(ser):(x&&typeof x==="object"?Object.fromEntries(Object.entries(x).map(([k,v])=>[k,ser(v)])):x);
fs.writeFileSync("'$TMP'/fri.json",JSON.stringify(ser(proof)));
'
$VENV - "$TMP/fri.json" <<'PY'
import sys,json; sys.path.insert(0,".")
from execnode.stark import fri
p=json.load(open(sys.argv[1]))
p["offset"]=int(p["offset"]); p["final"]=[int(x) for x in p["final"]]
for q in p["queries"]:
    for s in q["steps"]: s["lo"]=int(s["lo"]); s["hi"]=int(s["hi"])
ok,why=fri.verify(p); assert ok, "Python rejected the JS FRI proof: "+why
p["queries"][0]["steps"][0]["lo"]+=1; assert not fri.verify(p)[0], "tamper not caught"
print("Phase 2 FRI (JS proof, Python verify): OK")
PY
rm -rf "$TMP"
echo "ALL PASSED — browser prover ≡ Python"
