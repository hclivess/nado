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
const signed = [];
const cm = "ab".repeat(32);
const env = {
  state: { wallet: spender },
  i18: (k, fb) => fb,
  _stwo: { proveSpend: async () => ({ bundle: { stark: { stwo_js: { proof: "00", root: "11".repeat(32), nf: "22".repeat(32),
    cm_out1: "33".repeat(32), cm_out2: "44".repeat(32), unshield: "0", fee: "0" } } }, cm1: "33".repeat(32), cm2: "44".repeat(32) }) },
  execJSON: async () => ({ commitment: "da_commitment" }),
  getLatestBlock: async () => ({ block_number: 100 }),
  buildBlobTx: (wallet, payload) => { signed.push({ sender: wallet.address, public_key: wallet.publicKey, payload }); return { txid: "t" }; },
  MIN_TX_FEE: 1, nowSeconds: () => 0, guardFrom: (h) => h,
  submitTransaction: async () => ({ data: { result: true } }),
};
const body = [fnSrc("_daSubmitFieldTransfer", true), fnSrc("_onDeviceProveStwo", true), "return { _onDeviceProveStwo };"].join("\n");
const W = new Function(...Object.keys(env), body)(...Object.values(env));

const wit = { cm, nsk: "cd".repeat(32), value_in: "10", rho_in: "7", v1: "6", o1: "ef".repeat(32), r1: "1", v2: "4",
              o2: "ef".repeat(32), r2: "2", public_value: "0", fee: "0" };
const r = await W._onDeviceProveStwo(wit, "http://exec.invalid", ["00".repeat(32), cm]);
check("the wallet published the spend (sanity)", r.ok && signed.length === 1 && signed[0].payload.op === "field_transfer", JSON.stringify(signed));
if (signed.length) {
  check("the field_transfer carrying a private spend is not signed by the spending account",
        signed[0].sender !== spender.address && signed[0].public_key !== spender.publicKey,
        `sender ${signed[0].sender} = the account whose key derives the note's spend key: the input note's owner is public`);
}
process.exit(fails ? 1 : 0);
