/* A wallet's RANDAO secret never repeats across a reroll (static/interface.js randaoSecretFor), audit 2026-09-24 (lower):
 * epochs restart at every reroll, so H(domain, seed, epoch) handed the new chain's epoch E the secret this validator had
 * already REVEALED for epoch E on the old chain. From generation 29 the chain id is part of the secret; generation 28 keeps
 * its form (a mid-generation switch would break a commitment already made — a missed reveal).
 *
 * Run: node tests/test_a_randao_secret_never_repeats_across_a_reroll.mjs
 */
import fs from "fs";
import path from "path";
import crypto from "crypto";
import { fileURLToPath } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(HERE, "..", "static", "interface.js"), "utf8");
function fnSrc(name) {
  const i = SRC.indexOf("function " + name + "(");
  let depth = 0, j = SRC.indexOf("{", SRC.indexOf(")", i));
  for (; j < SRC.length; j++) { if (SRC[j] === "{") depth++; else if (SRC[j] === "}" && --depth === 0) break; }
  return SRC.slice(i, j + 1);
}
let fails = 0;
const check = (n, ok, d = "") => { console.log((ok ? "PASS  " : "FAIL  ") + n + (ok ? "" : "  " + d)); if (!ok) fails++; };
const SEED = crypto.randomBytes(32).toString("hex");
const make = (gen, chainId) => new Function("P", "CHAIN_ID", "masterSeedOf", "state", "blake2bHash", "DOMAIN_RANDAO_SECRET",
  fnSrc("randaoSecretFor") + "\nreturn randaoSecretFor;")({ CHAIN_GENERATION: gen }, chainId, () => SEED, { wallet: {} },
  (parts) => crypto.createHash("blake2b512").update(JSON.stringify(parts)).digest("hex").slice(0, 64), "randao-secret-v1");
const g28 = make(28, "betanet-9"), g29 = make(29, "betanet-10"), g30 = make(30, "betanet-11");
const legacy = crypto.createHash("blake2b512").update(JSON.stringify(["randao-secret-v1", SEED, 4000])).digest("hex").slice(0, 64);
check("generation 28 keeps the secret it has always derived (no commitment made with it breaks)", g28(4000) === legacy);
check("the next generation's epoch E secret differs from generation 28's epoch E secret", g29(4000) !== g28(4000));
check("...and from every later generation's", g30(4000) !== g29(4000));
check("within a generation it is still deterministic per epoch, and differs per epoch", g29(7) === g29(7) && g29(7) !== g29(8));
const exp = fs.readFileSync(path.join(HERE, "..", "protocol.py"), "utf8");
check("CHAIN_GENERATION is exported to clients", /CLIENT_EXPORTS = \([\s\S]*"CHAIN_GENERATION"/.test(exp));
console.log(fails ? `${fails} FAILURES` : "ALL PASS — a RANDAO secret never repeats across a reroll");
process.exit(fails ? 1 : 0);
