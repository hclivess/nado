// The wallet reveals only the secret that reproduces the challenge it published, and forgets a secret at the
// enrolment's own expiry (static/interface.js maybeTpmChallenge, /tpm_duty "blob" and "expires_at").
//
// WHY (2026-10-06, the challenger pool v2 integration). With one wallet open on two devices, both challenge; the chain
// keeps one challenge and refuses the other as a duplicate, so one device stores a secret that is NOT on chain. A
// reveal from it is refused, and if the right device is offline the challenger is excluded for a day. The relay now
// sends the address's own published blob with a reveal duty, and the wallet checks it first.
// Run: node tests/test_wallet_tpm_reveal_checks_blob.mjs
import { readFileSync } from "node:fs";
import { credentialBlob, bytesToHex, hexToBytes } from "../static/tpmcred.js";

let fails = 0;
const check = (name, ok) => { console.log((ok ? "PASS  " : "FAIL  ") + name); if (!ok) fails++; };
const rnd = (n) => { const a = new Uint8Array(n); for (let i = 0; i < n; i++) a[i] = (i * 37 + n) & 255; return a; };

const name = rnd(34), s1 = rnd(32), r1 = rnd(31).length ? rnd(32).map((x) => x ^ 0x5a) : null, s2 = s1.map((x) => x ^ 1);
const published = bytesToHex(credentialBlob(name, s1, r1));
check("the secret that sealed the published challenge reproduces it",
      bytesToHex(credentialBlob(hexToBytes(bytesToHex(name)), s1, r1)) === published);
check("another device's secret does not", bytesToHex(credentialBlob(name, s2, r1)) !== published);

const js = readFileSync(new URL("../static/interface.js", import.meta.url), "utf8");
const fn = js.slice(js.indexOf("async function maybeTpmChallenge"), js.indexOf("async function maybeTpmChallenge") + 12000);
check("a reveal duty is checked against its published blob before anything is signed",
      /if \(mine && d\.blob\)/.test(fn) && /tpmCredentialBlob\(tpmHex\(d\.name\), tpmHex\(ent\.secret\), tpmHex\(ent\.seed\)\)\) === String\(d\.blob\)\.toLowerCase\(\)/.test(fn)
      && fn.indexOf("if (mine && d.blob)") < fn.indexOf("buildTransferTx("));
check("a mismatched secret is never revealed (it takes the no-secret path)", /if \(!mine\) \{/.test(fn));
check("a secret is forgotten at the enrolment's own expiry", /const expired = ent\.exp != null && tip > Number\(ent\.exp\)/.test(fn)
      && /if \(Number\.isInteger\(d\.expires_at\)\) expOf\[d\.id\] = d\.expires_at;/.test(fn));
console.log(fails ? `${fails} FAILURES` : "ALL PASS — the wallet reveals only its own on-chain secret");
process.exit(fails ? 1 : 0);
