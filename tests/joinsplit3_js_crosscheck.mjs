/*
 * Cross-check the browser WIDE join-split prover (static/stark/joinsplit3.js over static/alghash2.js) against
 * the Python verifier: generate a full on-device proof in Node and write it to argv[2]; the companion
 * joinsplit3_js_crosscheck.sh verifies it with execnode.stark.joinsplit3.verify_transfer. One field element of
 * drift in the JS hash, trace, periodic columns or constraints and Python rejects it. Also prints the wide note
 * algebra's outputs so the shell step can pin them against Python's znote (owner / cm / nf / root equality).
 *
 * Run via: tests/joinsplit3_js_crosscheck.sh
 */
import { blake2b, bytesToHex } from "../static/vendor/nado-crypto.js";
import * as A2 from "../static/alghash2.js";
import { initHashing } from "../static/stark/hashing.js";
import * as J3 from "../static/stark/joinsplit3.js";
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
A2.initAlghash2(H);
initHashing(H);

// v_in = 1000 -> v1 = 700 (recipient) + v2 = 300 (change), public_value = 0, fee = 0; a one-note pool at depth 12
const nsk = 0xCAFEn, vIn = 1000n, rho = 0x1111n;
const o1 = A2.ownerOf(0xB0Bn), o2 = A2.ownerOf(nsk);
const cmIn = A2.commit(vIn, o2, rho);
const { sibs, dirs } = A2.treePath([cmIn], 0);
const t0 = Date.now();
const bt = J3.buildTrace(nsk, vIn, rho, sibs, dirs, 700n, o1, 0x2222n, 300n, o2, 0x3333n);
const bnd = J3.boundaries(bt.D, bt.root, bt.nf, bt.cm1, bt.cm2, 0n, 0n);
const rules = { round2: process.env.NADO_PROOF_ROUND2 === "1", traceLdt: process.env.NADO_PROOF_TRACE_LDT === "1" };
const proof = sstark.prove(bt.tr, J3.transitions(), bnd, J3.periodic(bt.T, bt.D), J3.MAX_DEGREE, sstark.NUM_QUERIES, null, { ...rules, zk: J3.ZK_RANDOMIZERS });
proof.D = bt.D;
const ms = Date.now() - t0;
const ser = (x) => typeof x === "bigint" ? x.toString() : Array.isArray(x) ? x.map(ser) : (x && typeof x === "object" ? Object.fromEntries(Object.entries(x).map(([k, v]) => [k, ser(v)])) : x);
fs.writeFileSync(process.argv[2], JSON.stringify({ proof: ser(proof), root: A2.toHex(bt.root), nf: A2.toHex(bt.nf),
  cm1: A2.toHex(bt.cm1), cm2: A2.toHex(bt.cm2), owner: A2.toHex(o2), cm_in: A2.toHex(cmIn),
  pool_root: A2.toHex(A2.treeRoot([cmIn])), ms }));
console.log(`joinsplit3 JS proof: T=${bt.T} W=${bt.tr[0].length} in ${ms} ms`);
