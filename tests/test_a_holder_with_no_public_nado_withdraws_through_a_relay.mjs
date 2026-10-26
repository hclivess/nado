/* A holder with no public NADO withdraws through a relay, and a refused withdrawal says why
 * (static/interface.js doUnshield, _daSubmitFieldTransfer; found by the gen-29 rehearsal's two-user walk, 2026-10-26).
 *
 * B received 1 NADO privately and held nothing public. A withdrawal used to be published by the account itself, so its
 * blob was refused for the L1 fee — and _daSubmitFieldTransfer returned the refusal as `message` while every caller read
 * `error`, so the page said only "Proof failed:". A recipient could never take private money out.
 *
 * Pins, by RUNNING the wallet's own doUnshield with the network and the prover stubbed (no key is involved):
 *   - an account below MIN_TX_FEE withdraws through a relay: the proof binds fee = the relay's fee and fee_to_relays, the
 *     relay is paid out of the banknote (take + fee + change = the note), the user confirms the relay fee, and the
 *     "published by your own account" warning — false for a relayed withdrawal — is not shown;
 *   - an account that can pay withdraws exactly as before: fee 0, no relay, no extra dialog;
 *   - a refused withdrawal's reason reaches `error`, which is what the callers show.
 *
 * Run: node tests/test_a_holder_with_no_public_nado_withdraws_through_a_relay.mjs
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(HERE, "..", "static", "interface.js"), "utf8");
function fnSrc(name, isAsync = false) {
  const i = SRC.indexOf((isAsync ? "async function " : "function ") + name + "(");
  if (i === -1) throw new Error(name + " not found");
  let depth = 0, j = SRC.indexOf("{", SRC.indexOf(")", i));
  for (; j < SRC.length; j++) { if (SRC[j] === "{") depth++; else if (SRC[j] === "}" && --depth === 0) break; }
  return SRC.slice(i, j + 1);
}
let fails = 0;
const check = (name, ok, detail = "") => { console.log((ok ? "PASS  " : "FAIL  ") + name + (ok ? "" : "  " + detail)); if (!ok) fails++; };

const MIN_TX_FEE = 1000, RELAY_FEE = 1000000, NOTE = 10_000_000_000n;   // a relay answers its fee as a JSON number
async function withdraw({ balance, to }) {
  const rec = { wits: [], confirms: [], logs: [] };
  const fields = { unshieldAmount: { value: "0.5" }, unshieldTo: { value: to || "" }, shieldStatus: { textContent: "", innerHTML: "" },
                   btnUnshield: { disabled: false, textContent: "" } };
  const notes = [{ value: String(NOTE), rho: "1", cm: "c1", spent: false }];
  const env = {
    state: { wallet: { address: "bbbb" } }, ensureShielded: () => {}, refreshShieldRules: async () => {}, shieldPaused: () => false,
    nadoToRaw: (s) => BigInt(Math.round(Number(s) * 1e10)), $: (id) => fields[id], ADDR_RE_I: /^[0-9a-z]+$/,
    log: (lvl, m) => rec.logs.push(lvl + ": " + m), i18: (k, d, v) => String(d).replace(/\{(\w+)\}/g, (_, n) => (v && n in v ? v[n] : "")),
    getAccount: async () => ({ balance }), stwoRelays: async () => [{ url: "http://relay", address: "rrrr", fee: RELAY_FEE }],
    MIN_TX_FEE, selectNotesFor: (amt) => (BigInt(amt) <= NOTE ? [notes[0]] : null), insufficientMsg: (a) => "insufficient " + a,
    uiConfirm: async (spec) => { rec.confirms.push(spec); return true; }, rawToNado: (x) => String(x),
    localStorage: { getItem: () => null, setItem: () => {} }, shieldOwner: () => "owner", loadNotes: () => notes,
    _randField: () => "7", noteNskWire: () => "nsk", ownerStr: (o) => o,
    proveTransfer2: async (wit) => { rec.wits.push(wit); return { ok: true, cm_out1: "c2" }; },
    _markSpendPending: () => {}, saveNotes: () => {}, renderShield: async () => {}, claimUnshields: async () => {},
    setTimeout: () => {},
  };
  const f = new Function(...Object.keys(env), fnSrc("doUnshield", true) + "\nreturn doUnshield;")(...Object.values(env));
  await f();
  return rec;
}

// 1. no public NADO: a relay publishes it and is paid out of the note
let r = await withdraw({ balance: 0, to: "eeee" });
const w = r.wits[0] || {};
check("an account with no public NADO proves a relayed withdrawal (fee = the relay's, fee_to_relays bound)",
  w.fee === String(RELAY_FEE) && Array.isArray(w.fee_to_relays) && w.fee_to_relays[0].address === "rrrr", JSON.stringify(w));
check("...the relay is paid out of the banknote: take + fee + change = the note",
  -BigInt(w.public_value) + BigInt(w.fee) + BigInt(w.v1) === NOTE && -BigInt(w.public_value) === 5_000_000_000n, JSON.stringify(w));
check("...the user confirms the relay fee", r.confirms.length === 1 && JSON.stringify(r.confirms[0].rows).includes(String(RELAY_FEE)),
  JSON.stringify(r.confirms));
check("...and is not told the withdrawal is published by their own account", !r.confirms.some((c) => /own account/.test(c.body || "")));
check("...and it is reported proved", r.logs.some((l) => l.startsWith("ok:")), r.logs.join(" | "));

// 2. an account that can pay: exactly as before
r = await withdraw({ balance: 50_000, to: "" });
const w2 = r.wits[0] || {};
check("an account that can pay the fee publishes its own withdrawal as before (fee 0, no relay, no dialog)",
  w2.fee === "0" && !("fee_to_relays" in w2) && r.confirms.length === 0 && -BigInt(w2.public_value) === 5_000_000_000n
  && BigInt(w2.v1) === NOTE - 5_000_000_000n, JSON.stringify(w2));

// 3. a refused withdrawal says why (the field callers read)
const da = new Function("execJSON", "getLatestBlock", "buildBlobTx", "MIN_TX_FEE", "nowSeconds", "guardFrom", "submitTransaction", "state", "i18",
  fnSrc("_daSubmitFieldTransfer", true) + "\nreturn _daSubmitFieldTransfer;")(
  async () => ({ commitment: "dc" }), async () => ({ block_number: 5 }), () => ({ txid: "t" }), 1000, () => 1, () => 9,
  async () => ({ data: { result: false, message: "Insufficient balance for fee" } }), { wallet: {} }, (k, d) => d);
const res = await da({}, "x");
check("a refused withdrawal's reason reaches `error` (what callers show)", res.ok === false && /Insufficient balance/.test(res.error || ""), JSON.stringify(res));

console.log(fails ? `\nFAILED: ${fails}` : "\nALL PASS — a holder with no public NADO withdraws through a relay");
process.exit(fails ? 1 : 0);
