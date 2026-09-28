// PYTHON <-> JS PARITY over the self-test vectors, headless. Run: node tests/selftest_vectors_crosscheck.mjs
//
// WHY THIS FILE EXISTS. The in-page self-test (interface.js runSelfTest) is the authoritative check, but it
// only runs when a human loads the page, so "the browser and the node agree" kept being ASSERTED in release
// notes instead of demonstrated -- once falsely, and it had to be retracted (7ec8793). This mirrors that
// self-test exactly and runs in CI, so the claim is either backed by output or it is not made.
//
// Vectors are read out of the SHIPPED static/interface.js (not a copy), so a stale VEC block fails here.
// Primitives come from nadotx.js, whose crypto bundle is pure JS with no DOM or wasm dependency.
//
// REGENERATE the vectors after ANY field/format/tag/chain_id change:
//   PYTHONPATH=<tree> python3 tools/gen_selftest_vectors.py   -> paste over the `const VEC = {...}` block.
//
// Two traps this file already fell into, both of which look like parity failures and are not:
//   * DOMAIN_REGISTER is "register-v1", not "register" (interface.js:58).
//   * JSON.parse cannot carry the >2^53 torture values -- build those objects with BigInt LITERALS, exactly
//     as runSelfTest does, or canonicalize throws "integer > 2^53".
import { blake2bHash, makeAddress, canonicalize, ADDR_PREFIX, ADDR_LEN, ADDR_FORMAT, isAddress }
  from "../static/nadotx.js";
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../static/interface.js", import.meta.url), "utf8");
const body0 = src.slice(src.indexOf("const VEC = {"));
const VEC = eval("(" + body0.slice(body0.indexOf("{"), body0.indexOf("\n};") + 2) + ")");

const DOMAIN_REGISTER = "register-v1";                     // interface.js:58
const bodyOf = (tx) => { const b = {}; for (const k of Object.keys(tx)) if (k !== "txid" && k !== "signature") b[k] = tx[k]; return b; };
const createTxid = (b) => { const p = {}; for (const k of Object.keys(b)) if (k !== "public_key") p[k] = b[k]; return blake2bHash(p); };

let pass = 0, fail = 0;
const add = (name, got, want) => {
  const ok = got === want; ok ? pass++ : fail++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) console.log(`        got  ${got}\n        want ${want}`);
};

add("blake2b_hash([DOMAIN_REGISTER, prefix+'TEST', 5])", blake2bHash([DOMAIN_REGISTER, ADDR_PREFIX + "TEST", 5]), VEC.hash_register_list);
add("blake2b_hash(addr_body, size=2)", blake2bHash(ADDR_PREFIX + VEC.checksum_body, 2), VEC.checksum_string_size2);
add("make_address(pubkey)", makeAddress(VEC.make_address_pub), VEC.make_address_out);
add("blake2b_hash_link('a','b')", blake2bHash(["a", "b"]), VEC.hash_link_a_b);

const torture = { z: 1, a: 'héllo "x"\n\t/end', m: [3, 2, { k: true, big: 12345678901234567890n }], n: null, "unicode_key_ü": "☃ snowman" };
add("canonical(torture obj)", canonicalize(torture), VEC.torture_canonical);
add("blake2b_hash(torture obj)", blake2bHash(torture), VEC.torture_hash);
const bigobj = { amount: 99999999999999999999n, x: 9007199254740993n };
add("canonical(BigInt > 2^53)", canonicalize(bigobj), VEC.bigobj_canonical);
add("blake2b_hash(BigInt obj)", blake2bHash(bigobj), VEC.bigobj_hash);

for (const k of ["register", "heartbeat", "transfer"]) {
  add(`${k} canonical body`, canonicalize(bodyOf(VEC[`${k}_tx`])), VEC[`${k}_canonical`]);
  add(`${k} txid (public_key-excluded)`, createTxid(bodyOf(VEC[`${k}_tx`])), VEC[`${k}_tx`].txid);
}

// the address format itself: 46 characters on format 1, 50 on format 2 (a 4-byte checksum; protocol.ADDRESS_LENGTH),
// and the vectors were generated for the format the files ship with — a stale VEC block from the other format fails here
add("ADDR_PREFIX removed", ADDR_PREFIX, "");
add("ADDR_LEN matches the format", String(ADDR_LEN), ADDR_FORMAT >= 2 ? "50" : "46");
add("generated address has that length", String(VEC.make_address_out.length), String(ADDR_LEN));
add("isAddress accepts it", String(isAddress(VEC.make_address_out)), "true");
add("isAddress rejects a prefixed address", String(isAddress("mldsa44" + VEC.make_address_out)), "false");
add("isAddress rejects the other format's length", String(isAddress(VEC.make_address_out.slice(0, 46))), ADDR_FORMAT >= 2 ? "false" : "true");
add("vectors name a chain", String(/^betanet-\d+$/.test(VEC.register_tx.chain_id)), "true");

console.log(`\n${fail === 0 ? "ALL PASS" : fail + " FAILURES"} — ${pass}/${pass + fail} checks`);
process.exit(fail ? 1 : 0);
