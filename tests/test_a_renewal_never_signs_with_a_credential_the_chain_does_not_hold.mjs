// A signature renewal never signs with a credential the chain does not hold — and a wallet that already does heals.
//
// 2026-10-22, reported by the operator: "lease signature rejected: ES256 signature does not verify". The wallet saved the
// credential id the moment navigator.credentials.create() returned, before the pre-flight or any relay saw the statement.
// A statement that never landed left the browser remembering a credential the chain never stored, and every renewal
// signed with it (the node verifies correctly: native/attest authdata.rs, no high-S rule for P-256), on every renewal,
// with no fallback. This test runs the REAL functions from static/interface.js with a stubbed localStorage:
//   1. create() alone saves nothing; the id is saved only when the very statement (by its attestationObject) is accepted;
//   2. an accepted register of ANOTHER statement, or of another sender, saves nothing;
//   3. a refused SIGNATURE renewal forgets the saved id and says so (in its own i18n key), so the next attempt attests;
//   4. any other refusal, or a refused statement, keeps the saved id;
//   5. both submit paths (the lease renewal and the register flow) call acceptedRegisterTx on success and
//      healSignatureRenewal on refusal, and the lease loop retries once after a heal.
// Run: node tests/test_a_renewal_never_signs_with_a_credential_the_chain_does_not_hold.mjs
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = readFileSync(join(ROOT, "static", "interface.js"), "utf8");
let fails = 0;
const check = (name, ok, detail = "") => {
  console.log((ok ? "PASS  " : "FAIL  ") + name + (ok ? "" : "  " + JSON.stringify(detail)));
  if (!ok) fails++;
};

function grab(name) {
  const at = src.indexOf("function " + name + "(");
  if (at < 0) throw new Error("no function " + name);
  let i = src.indexOf("{", at), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}" && --depth === 0) return src.slice(at, i + 1);
  }
  throw new Error("unbalanced " + name);
}

const store = new Map();
const logs = [];
const sandbox = new Function("localStorage", "log", "i18", "btoa",
  "let _pendingCred = null;\n" +
  ["storedCredentialId", "rememberCredentialId", "acceptedRegisterTx", "healSignatureRenewal"].map(grab).join("\n") +
  "\nreturn { storedCredentialId, rememberCredentialId, acceptedRegisterTx, healSignatureRenewal };");
const W = sandbox(
  { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) },
  (lvl, msg) => logs.push([lvl, msg]),
  (key, en) => key + "|" + en,
  (s) => Buffer.from(s, "binary").toString("base64"));

const A = "ndoA", B = "ndoB";
const raw = new Uint8Array([1, 2, 3, 4]).buffer;
W.rememberCredentialId(A, raw, "ATT1");
check("1. create() alone saves no credential id", W.storedCredentialId(A) === null);
W.acceptedRegisterTx({ sender: A, device: { att: "OTHER", cdj: "x" } });
check("2. an accepted register of ANOTHER statement saves nothing", W.storedCredentialId(A) === null);
W.acceptedRegisterTx({ sender: B, device: { att: "ATT1", cdj: "x" } });
check("2. an accepted register by another sender saves nothing", W.storedCredentialId(A) === null && W.storedCredentialId(B) === null);
W.acceptedRegisterTx({ sender: A, device: { att: "ATT1", cdj: "x" } });
check("1. the id is saved once THAT statement is accepted", W.storedCredentialId(A) === "AQIDBA==", W.storedCredentialId(A));

const sigTx = { sender: A, device: { ad: "a", cdj: "c", sig: "s", rp: "r" } };
check("4. another refusal keeps the saved id", !W.healSignatureRenewal(sigTx, "too low") && W.storedCredentialId(A) === "AQIDBA==");
check("4. a refused STATEMENT keeps the saved id",
  !W.healSignatureRenewal({ sender: A, device: { att: "ATT1", cdj: "x" } }, "signature renewal rejected: x") && W.storedCredentialId(A) === "AQIDBA==");
const healed = W.healSignatureRenewal(sigTx, "signature renewal rejected: ES256 signature does not verify");
check("3. a refused signature renewal forgets the saved id", healed && W.storedCredentialId(A) === null);
check("3. ... and says so in its own message key", logs.some(([l, m]) => l === "warn" && m.startsWith("bind.sigStale|")), logs);

const body = (name) => grab(name);
const lease = body("broadcastLeaseRenewal"), reg = body("submitRegisterTx");
check("5. the lease renewal commits the credential on acceptance", /acceptedRegisterTx\(tx\)/.test(lease));
check("5. the lease renewal heals a refused signature and retries once",
  /!healed && healSignatureRenewal\(tx, lastMsg\)\) \{ healed = true; attempt--; continue; \}/.test(lease));
check("5. the register flow commits on acceptance and heals on refusal",
  /acceptedRegisterTx\(tx\)/.test(reg) && /healSignatureRenewal\(tx, m\)/.test(reg));
check("5. nothing writes the credential id except acceptedRegisterTx",
  (src.match(/localStorage\.setItem\("nado_cred_"/g) || []).length === 1 && /function acceptedRegisterTx[\s\S]{0,200}localStorage\.setItem\("nado_cred_"/.test(src));

console.log(fails ? `${fails} FAILURES` : "ALL PASS — a renewal never signs with a credential the chain does not hold");
process.exit(fails ? 1 : 0);
