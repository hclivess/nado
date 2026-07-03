/*
 * Cross-check the browser 2-output join-split prover (static/stark/joinsplit2.js, WITH the C-3 range gadget)
 * against the Python verifier: generate a full on-device proof in Node and write it to the path in argv[2];
 * a companion Python step (joinsplit2_js_crosscheck.sh) verifies it with joinsplit2.verify_transfer. If the JS
 * trace/periodic/constraints drift from Python by one field element, Python rejects it.
 *
 * Run via: tests/joinsplit2_js_crosscheck.sh
 */
import { blake2b, bytesToHex } from "../static/vendor/nado-crypto.js";
import * as A from "../static/alghash.js";
import { initHashing } from "../static/stark/hashing.js";
import * as J2 from "../static/stark/joinsplit2.js";
import * as sstark from "../static/stark/stark.js";
import fs from "fs";

function canon(d) {
  const t = typeof d;
  if (t === "bigint") return d.toString();
  if (t === "number") return String(d);
  if (t === "string") return JSON.stringify(d);
  if (Array.isArray(d)) return "[" + d.map(canon).join(",") + "]";
  throw new Error("canon: " + t);
}
const enc = new TextEncoder();
const H = (data, size = 32) => bytesToHex(blake2b(enc.encode(canon(data)), { dkLen: size }));
A.initAlghash(H);
initHashing(H);

// v_in = 1000  ->  v1 = 700 (recipient) + v2 = 300 (change), public_value = 0, fee = 0
const nsk = 0xCAFEn, vIn = 1000n, rho = 0x1111n;
const o1 = A.ownerOf(0xB0Bn), o2 = A.ownerOf(nsk);
const sibs = [111n, 222n, 333n, 444n], dirs = [0, 1, 0, 1];
const bt = J2.buildTrace(nsk, vIn, rho, sibs, dirs, 700n, o1, 0x2222n, 300n, o2, 0x3333n);
const total = J2.bounds(bt.D)[2];
const bnd = [[0, J2.S0, A.DOM_OWNER], [0, J2.S1, A.ivVal()], [0, J2.AB, A.DOM_OWNER], [0, J2.CONS, 0n],
  [total, J2.ROOTREG, bt.root], [total, J2.NFREG, bt.nf], [total, J2.CMOUT1, bt.cm1], [total, J2.S0, bt.cm2]];
const proof = sstark.prove(bt.tr, J2.transitions(), bnd, J2.periodic(bt.T, bt.D), J2.MAX_DEGREE, sstark.NUM_QUERIES, null);
proof.D = bt.D;
const ser = (x) => typeof x === "bigint" ? x.toString()
  : Array.isArray(x) ? x.map(ser)
  : (x && typeof x === "object" ? Object.fromEntries(Object.entries(x).map(([k, v]) => [k, ser(v)])) : x);
fs.writeFileSync(process.argv[2], JSON.stringify({
  proof: ser(proof), root: bt.root.toString(), nf: bt.nf.toString(),
  cm1: bt.cm1.toString(), cm2: bt.cm2.toString(),
}));
console.log("JS proof written (W=" + proof.W + ", T=" + proof.T + ")");
