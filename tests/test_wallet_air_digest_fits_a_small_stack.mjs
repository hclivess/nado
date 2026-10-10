// The wallet's AIR digest fits a small call stack at production size (static/stark/stark.js airDigest, bhash.js).
//
// Found 2026-10-10 measuring the join-split prover: airDigest hashed its ~102,500 parts with b2b32(...parts), and
// spreading that many arguments overflows the stack — "RangeError: Maximum call stack size exceeded" in a Chrome
// Worker and in Node with --stack-size=300, the class of stack a phone browser may have. Pins: at the depth-48 size
// (25 periodic columns x 4096) the digest is computed in a child Node with --stack-size=300; and the array form
// b2b32Parts hashes exactly what b2b32 does, so no proof's transcript changes.
//
// Run: node tests/test_wallet_air_digest_fits_a_small_stack.mjs
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
let fails = 0;
const check = (name, ok, detail = "") => { console.log((ok ? "PASS  " : "FAIL  ") + name + (ok ? "" : "  " + detail)); if (!ok) fails++; };

const { b2b32, b2b32Parts, i8le } = await import(path.join(ROOT, "static/stark/bhash.js"));
const small = [Uint8Array.of(1, 2, 3), i8le(7n), i8le(123456789n)];
check("b2b32Parts(parts) is exactly b2b32(...parts)", b2b32Parts(small) === b2b32(...small));

const prog = `
  const { airDigest } = await import(${JSON.stringify(path.join(ROOT, "static/stark/stark.js"))});
  const periodic = Array.from({ length: 25 }, (_, c) => Array.from({ length: 4096 }, (_, i) => BigInt(c * 4096 + i)));
  const d = airDigest(8192, 40, 8, 30, [[0, 1, 5n], [8191, 2, 9n]], periodic);
  console.log("DIGEST " + d);`;
const r = spawnSync(process.execPath, ["--stack-size=300", "--input-type=module", "-e", prog], { encoding: "utf8", timeout: 300000 });
check("the depth-48-sized AIR digest is computed under a 300 KB stack", r.status === 0 && /DIGEST [0-9a-f]{64}/.test(r.stdout),
      (r.stderr || "").slice(-300));

console.log(fails ? `${fails} FAILURES` : "ALL PASS — the AIR digest fits a small stack");
process.exit(fails ? 1 : 0);
