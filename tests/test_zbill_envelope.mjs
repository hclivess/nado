/* The shielded-banknote delivery payload, through the REAL messaging crypto — no mocks.
 *
 * tests/test_zbill_delivery.js pins the SHAPE of the feature by reading the wallet source; this pins the
 * BEHAVIOUR by actually sealing and opening an envelope with static/messaging.js, which is written to run
 * under Node for exactly this purpose.
 *
 * What matters here is not that delivery works — msgSend has shipped that envelope for ordinary chat all
 * along — but that routing a CLAIM CODE through it does not leak one. The code is not bearer (only the
 * recipient's shieldOwner can bank it), yet anyone who reads it learns the amount, so it must never appear
 * in cleartext and the envelope must not say who it is for.
 *
 * Run: node tests/test_zbill_envelope.mjs
 */
const M = await import('../static/messaging.js');

const alice = M.identity("11".repeat(32));   // sender
const bob   = M.identity("22".repeat(32));   // intended recipient
const mal   = M.identity("33".repeat(32));   // uninvolved third party
const CODE  = "zbill2s.9xk3q";
const SENDER = "a".repeat(46);
const ts = Math.floor(Date.now() / 1000);

let fails = 0;
const eq = (a, b, m) => {
  if (a !== b) { fails++; console.log(`FAIL  ${m}: ${JSON.stringify(a)} != ${JSON.stringify(b)}`); }
  else console.log(`PASS  ${m}`);
};

const env = M.makeEnvelope(alice, SENDER, bob.kemPub,
  { type: "zbill", from: SENDER, alias: null, code: CODE, ts,
    body: "A private NADO banknote — open to claim: http://x/#claim?code=" + CODE }, ts);

const pt = M.tryOpen(bob, env);
eq(!!pt, true, "the intended recipient opens the envelope");
if (pt) {
  eq(pt.type, "zbill", "payload type survives — msgPoll dispatches on it");
  eq(pt.code, CODE, "claim code survives byte-exact (a mangled rho banks nothing)");
  eq(typeof pt.body === "string" && pt.body.includes(CODE), true,
     "fallback body carries the claim link, so a wallet predating this shows something openable");
}
eq(M.tryOpen(mal, env), null, "an uninvolved third party cannot open it");
eq(M.tryOpen(alice, env), null, "not even the sender's own identity trial-opens it");

const raw = JSON.stringify(env);
eq(raw.includes(CODE), false, "the claim code is NOT in the envelope in cleartext");
eq(raw.includes(bob.kemPub), false, "the recipient's public key is NOT echoed in the envelope");
eq(/"to"\s*:/.test(raw), false, "there is no cleartext recipient field — recipient stays hidden");
eq(typeof M.messageId(env) === "string" && M.messageId(env).length > 0, true, "the envelope has a stable id");

console.log();
if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
