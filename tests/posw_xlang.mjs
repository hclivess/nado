import { blake2b, bytesToHex, hexToBytes } from '../static/vendor/nado-crypto.js';
import { poswProve, poswVerify, challengeBytes } from '../static/posw.js';
import { readFileSync } from 'node:fs';
const deps = { blake2b, bytesToHex, hexToBytes };
const T = 1000, S = 10, K = 8, ADDR = "ndoalice", ANCHOR = "0".repeat(64);
const ch = challengeBytes(ADDR, ANCHOR);
const mode = process.argv[2];
if (mode === "prove") process.stdout.write(JSON.stringify(poswProve(ch, T, S, K, deps)));
else if (mode === "verify") {
  const proof = JSON.parse(readFileSync(process.argv[3], "utf8"));
  process.stdout.write(poswVerify(ch, proof, T, S, K, deps) ? "OK" : "FAIL");
}
