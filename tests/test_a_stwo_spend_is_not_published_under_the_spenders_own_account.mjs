/* A Stwo spend must not be published by an L1 transaction signed by the account that owns the spent note.
 *
 * ZK review 2026-10-11 (rev-zk). REPRODUCES A LEAK: this test FAILS on 37d076c6 and is the reproduction.
 *
 * The proof hides which note is spent and whose it is. The wallet then publishes it as a `field_transfer` blob that
 * the spender's OWN account signs and pays for (_daSubmitFieldTransfer -> buildBlobTx(state.wallet, ...): sender =
 * the account address, public_key = its key). The spend key is derived from that same account key
 * (shieldNskStwo), so the blob names the input note's owner: every nullifier is tied to an account, and with the
 * deposits (which publish the owner next to the same account, see
 * test_a_stwo_deposit_does_not_publish_the_owner_behind_the_wallets_zaddr.mjs) the input leaf's anonymity set is the
 * notes of that one account, not the pool.
 *
 * The check RUNS the wallet's own _onDeviceProveStwo and _daSubmitFieldTransfer (extracted from static/interface.js)
 * with the prover, DA and relay stubbed and a generated throwaway account (never a real key), and reads who signs
 * the transaction that carries the spend.
 *
 * FIXED (operator decision "nodes relay spends", ops/stwo_relay.py): a private spend is proved to pay a relay node its
 * fee and handed to that node, which publishes it under its own key; a failed relay falls back to the next one; with
 * no relay the spend is refused — never signed by the account. Only a withdrawal (public payout) is self-published.
 *
 * Run: node tests/test_a_stwo_spend_is_not_published_under_the_spenders_own_account.mjs
 */
import fs from "fs";
import path from "path";
import crypto from "crypto";
import { fileURLToPath } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(HERE, "..", "static", "interface.js"), "utf8");

function fnSrc(name, isAsync = false) {
  const i = SRC.indexOf((isAsync ? "async function " : "function ") + name + "(");
  if (i === -1) throw new Error(name + " not found in interface.js");
  let depth = 0, j = SRC.indexOf("{", SRC.indexOf(")", i));
  for (; j < SRC.length; j++) { if (SRC[j] === "{") depth++; else if (SRC[j] === "}" && --depth === 0) break; }
  return SRC.slice(i, j + 1);
}

let fails = 0;
const check = (name, ok, detail = "") => { console.log((ok ? "PASS  " : "FAIL  ") + name + (ok ? "" : "  " + detail)); if (!ok) fails++; };

const spender = { address: "ndo_spender_" + crypto.randomBytes(4).toString("hex"), privateKey: crypto.randomBytes(32).toString("hex"),
                  publicKey: "pk_" + crypto.randomBytes(4).toString("hex") };
const signed = [], relayed = [], proved = [];
const cm = "ab".repeat(32);
let relayAnswers = [];                              // what each successive relay POST answers
const env = {
  state: { wallet: spender },
  i18: (k, fb, v) => String(fb).replace(/\{(\w+)\}/g, (m, n) => (v && v[n] != null ? String(v[n]) : m)),
  _stwo: { proveSpend: async (sp) => { proved.push(sp); return { bundle: { stark: { stwo_js: { proof: "00", root: "11".repeat(32), nf: "22".repeat(32),
    cm_out1: "33".repeat(32), cm_out2: "44".repeat(32), unshield: String(sp.unshield), fee: "0" } }, ...(sp.dest ? { withdraw_addr: sp.dest } : {}) },
    cm1: "33".repeat(32), cm2: "44".repeat(32) }; } },
  execJSON: async () => ({ commitment: "da_commitment" }),
  getLatestBlock: async () => ({ block_number: 100 }),
  buildBlobTx: (wallet, payload) => { signed.push({ sender: wallet.address, public_key: wallet.publicKey, payload }); return { txid: "t" }; },
  MIN_TX_FEE: 1, nowSeconds: () => 0, guardFrom: (h) => h,
  submitTransaction: async () => ({ data: { result: true } }),
  // the relay node's /stwo/relay (ops/stwo_relay.py), stubbed: records what reaches it
  _stwoRelayPost: async (url, bundle) => { relayed.push({ url, bundle }); return relayAnswers.shift() || { ok: true, status: 200, txid: "relay_tx" }; },
};
const body = [fnSrc("_daSubmitFieldTransfer", true), fnSrc("_onDeviceProveStwo", true), "return { _onDeviceProveStwo };"].join("\n");
const W = new Function(...Object.keys(env), body)(...Object.values(env));

const FEE = 100000n;
const relays = [{ url: "http://relay-a.invalid", address: "ndo_relay_a", fee: FEE }, { url: "http://relay-b.invalid", address: "ndo_relay_b", fee: FEE }];
const wit = { cm, nsk: "cd".repeat(32), value_in: "100010", rho_in: "7", v1: "6", o1: "ef".repeat(32), r1: "1", v2: "4",
              o2: "ef".repeat(32), r2: "2", public_value: "0", fee: "0", relays, relayFee: FEE };
const leaves = ["00".repeat(32), cm];

let r = await W._onDeviceProveStwo(wit, "http://exec.invalid", leaves);
check("the wallet published the private spend (sanity)", r.ok && relayed.length === 1, JSON.stringify(r));
check("the field_transfer carrying a private spend is not signed by the spending account",
      signed.every((t) => t.sender !== spender.address && t.public_key !== spender.publicKey) && signed.length === 0,
      `signed by ${signed.map((t) => t.sender)} = the account whose key derives the note's spend key: the input note's owner is public`);
check("...it went to the relay, proved to pay that relay its fee (withdraw_addr = relay, unshield = fee)",
      relayed[0] && relayed[0].url === relays[0].url && proved[0].dest === relays[0].address && proved[0].unshield === String(FEE)
      && relayed[0].bundle.withdraw_addr === relays[0].address, JSON.stringify(proved[0]));

relayed.length = 0; proved.length = 0;
relayAnswers = [{ ok: false, status: 503, reason: "relay down" }];
r = await W._onDeviceProveStwo(wit, "http://exec.invalid", leaves);
check("a failed relay falls back to the next relay, with a fresh proof bound to ITS address",
      r.ok && relayed.length === 2 && relayed[1].url === relays[1].url && proved[1].dest === relays[1].address && signed.length === 0,
      JSON.stringify({ r, proved: proved.map((p) => p.dest) }));

relayed.length = 0; proved.length = 0;
relayAnswers = [{ ok: false, status: 503, reason: "down" }, { ok: false, status: 0, reason: "unreachable" }];
r = await W._onDeviceProveStwo(wit, "http://exec.invalid", leaves);
check("when every relay fails the spend is NOT published from the account: an error, nothing signed",
      !r.ok && r.error && signed.length === 0, JSON.stringify(r));
r = await W._onDeviceProveStwo({ ...wit, relays: [] }, "http://exec.invalid", leaves);
check("...and with no relay at all, the same: an error, nothing signed", !r.ok && r.error && signed.length === 0, JSON.stringify(r));

const own = { ...wit, relays: undefined, v1: "6", v2: "4", value_in: "15", public_value: "-5", withdraw_addr: spender.address };
r = await W._onDeviceProveStwo(own, "http://exec.invalid", leaves);
check("a WITHDRAWAL (public payout) is still published by the account itself (sanity: that path is unchanged)",
      r.ok && signed.length === 1 && signed[0].payload.op === "field_transfer", JSON.stringify(signed));
process.exit(fails ? 1 : 0);
