/*
 * Cross-check that static/shielded.js hashes BYTE-IDENTICALLY to execnode/shielded.py (doc/privacy.md).
 * If the browser port drifts by even one byte, a note committed in the browser would be rejected by the pool.
 *
 * The reference vectors are GENERATED from execnode/shielded.py at run time (tests/shielded_js_crosscheck_gen.py),
 * never pinned here: the hard-coded hashes this file used to carry went stale at the debrand cutover (6531186b,
 * DOMAIN_SHIELD "nado.shield" -> "shield-v1" in both sides) and the check stayed red for months while JS and Python
 * agreed — which would have hidden a real drift. Do not paste literal hashes back in.
 *
 * Run:  node tests/shielded_js_crosscheck.mjs                (spawns the generator; NADO_PYTHON picks the interpreter)
 *  or:  python3 tests/shielded_js_crosscheck_gen.py | node tests/shielded_js_crosscheck.mjs -
 * Suite: tests/test_shielded_js_matches_the_pool.py runs it.
 *
 * Uses the SAME vendored @noble blake2b the browser loads, composed with the SAME canonicalize as miner.js.
 */
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { blake2b, bytesToHex } from "../static/vendor/nado-crypto.js";
import * as shielded from "../static/shielded.js";

// --- canonicalize + blake2bHash: copied verbatim from interface.js (itself byte-verified against Python) ---
function jsonEscapeAscii(s) { return JSON.stringify(s); }        // inputs here are ASCII -> JSON string literal
function canonicalize(data) {
  if (data === null || data === undefined) return "null";
  const t = typeof data;
  if (t === "boolean") return data ? "true" : "false";
  if (t === "bigint") return data.toString();
  if (t === "number") { if (!Number.isInteger(data)) throw new Error("float"); return String(data); }
  if (t === "string") return jsonEscapeAscii(data);
  if (Array.isArray(data)) return "[" + data.map(canonicalize).join(",") + "]";
  if (t === "object") { const k = Object.keys(data).sort(); return "{" + k.map((x) => jsonEscapeAscii(x) + ":" + canonicalize(data[x])).join(",") + "}"; }
  throw new Error("bad type " + t);
}
const _enc = new TextEncoder();
const blake2bHash = (data, size = 32) => bytesToHex(blake2b(_enc.encode(canonicalize(data)), { dkLen: size }));
shielded.initShielded(blake2bHash);

// --- reference vectors, from execnode/shielded.py NOW ---
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
let body;
if (process.argv[2] === "-") {
  body = "";
  for await (const chunk of process.stdin) body += chunk;
} else {
  const venv = join(ROOT, "nado_venv", "bin", "python");
  const py = process.env.NADO_PYTHON || (existsSync(venv) ? venv : "python3");
  body = execFileSync(py, [join(ROOT, "tests", "shielded_js_crosscheck_gen.py")], { cwd: ROOT, maxBuffer: 64 << 20 }).toString();
}
const V = JSON.parse(body);

let fails = 0, n = 0;
function eq(name, got, want) {
  n++;
  const ok = got === want;
  if (!ok) { fails++; console.log(`FAIL  ${name}\n   got  ${got}\n   want ${want}`); }
}

eq("DOMAIN_SHIELD", shielded.DOMAIN_SHIELD, V.domain);
eq("SHIELD_DEPTH", String(shielded.SHIELD_DEPTH), String(V.depth));
eq("empty_root", shielded.emptyRoot(), V.empty);
for (const o of V.owners) eq(`owner_id(${o.pk.slice(0, 8)})`, shielded.ownerId(o.pk), o.owner);
for (const v of V.notes) {
  eq(`note_commitment(value=${v.value})`, shielded.noteCommitment(v.value, v.owner, v.rho), v.cm);
  eq(`note_nullifier(${v.rho.slice(0, 8)})`, shielded.noteNullifier(v.pk, v.rho), v.nf);
}
V.sighashes.forEach((s, i) => eq(`transfer_sighash[${i}]`, shielded.transferSighash(s.pub), s.sighash));
for (const t of V.trees) {
  const k = t.leaves.length;
  eq(`merkle_root(${k})`, shielded.merkleRoot(t.leaves), t.root);
  const path = shielded.merklePath(t.leaves, t.pos);
  eq(`merkle_path(${k}, pos ${t.pos})`, path.join(","), t.path.join(","));
  eq(`verify_path(${k}, pos ${t.pos})`, String(shielded.verifyPath(t.leaves[t.pos], t.pos, t.path, t.root)), "true");
  const wrong = t.pos ^ 1;
  eq(`verify_path(${k}, wrong pos ${wrong}) rejected`, String(shielded.verifyPath(t.leaves[t.pos], wrong, t.path, t.root)), "false");
}

console.log(`\n${n - fails}/${n} PASS`);
console.log(fails ? `${fails} FAILED — JS and Python DIVERGE` : "ALL PASSED — JS ≡ Python byte-for-byte");
process.exit(fails ? 1 : 0);
