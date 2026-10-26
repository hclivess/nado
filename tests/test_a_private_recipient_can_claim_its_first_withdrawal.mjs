/* A recipient whose money arrived PRIVATELY can claim its first withdrawal, and a refused claim says why
 * (memserver.py empty-account gate, static/interface.js claimUnshields; the gen-29 rehearsal's two-user walk, 2026-10-26).
 *
 * B received 1 NADO privately and had no L1 account. Its withdrawal settled, but the fee-exempt `unshield` claim was
 * refused "Empty account" by the mempool's anti-spam gate (which lets only onboarding kinds and legacy_claim through
 * from a never-funded sender) — and the wallet, ignoring the refusal, told B "Still settling on L1 — it'll arrive
 * automatically", for ever. The claim is bounded by consensus like legacy_claim (a valid exit proof against the SETTLED
 * root, its nullifier burned, the claimant the exit's own address), so it joins the bypass.
 *
 * Pins: the mempool gate lets `unshield` through beside the onboarding kinds and legacy_claim (source — the gate runs
 * inside the node's submit path; the loopback walk scripts/testnet/test_shield_wallet.py drives it end to end), and the
 * wallet's own claimUnshields, RUN with the network stubbed, shows a refusal's reason instead of "still settling" and
 * still reports a landed claim.
 *
 * Run: node tests/test_a_private_recipient_can_claim_its_first_withdrawal.mjs
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(HERE, "..", "static", "interface.js"), "utf8");
const MEM = fs.readFileSync(path.join(HERE, "..", "memserver.py"), "utf8");
function fnSrc(name, isAsync = false) {
  const i = SRC.indexOf((isAsync ? "async function " : "function ") + name + "(");
  if (i === -1) throw new Error(name + " not found");
  let depth = 0, j = SRC.indexOf("{", SRC.indexOf(")", i));
  for (; j < SRC.length; j++) { if (SRC[j] === "{") depth++; else if (SRC[j] === "}" && --depth === 0) break; }
  return SRC.slice(i, j + 1);
}
let fails = 0;
const check = (name, ok, detail = "") => { console.log((ok ? "PASS  " : "FAIL  ") + name + (ok ? "" : "  " + detail)); if (!ok) fails++; };

const gate = MEM.match(/elif transaction\.get\("recipient"\) not in \(([^)]*)\)/);
const kinds = gate ? gate[1].replace(/\s+/g, "").split(",").map((k) => k.replace(/"/g, "")) : [];
check("the mempool's empty-account gate lets an unshield claim through", kinds.includes("unshield"), kinds.join(","));
check("...beside the onboarding kinds and legacy_claim, and nothing that spends",
  ["register", "heartbeat", "tpm_enrol", "tpm_challenge", "tpm_commit", "tpm_reveal", "legacy_claim"].every((k) => kinds.includes(k))
  && !kinds.some((k) => ["", "bond", "alias", "blob", "htlc_lock", "invite_lock", "tpm_ready"].includes(k)), kinds.join(","));

async function claim(result) {
  const status = { textContent: "" };
  const env = {
    state: { wallet: { address: "bbbb" } }, $: () => status, i18: (k, d, v) => String(d).replace(/\{(\w+)\}/g, (_, n) => (v && n in v ? v[n] : "")),
    log: () => {}, encodeURIComponent,
    execJSON: async (p) => (p.startsWith("/exec/unshields") ? { unshields: [{ nonce: 7 }] } : { proof: "pr", addr: "bbbb", amount: 5, nonce: 7 }),
    relayBase: () => "http://relay",
    fetch: async (u) => ({ json: async () => (u.includes("unshield_claimed") ? { claimed: [] } : { state_root: "r" }) }),
    getLatestBlock: async () => ({ block_number: 10 }), buildTransferTx: () => ({ txid: "t" }), nowSeconds: () => 1,
    submitTransaction: async () => ({ data: result }), setTimeout: () => {}, refreshDashboard: async () => {}, renderShield: async () => {},
  };
  await new Function(...Object.keys(env), fnSrc("claimUnshields", true) + "\nreturn claimUnshields;")(...Object.values(env))();
  return status.textContent;
}
const refused = await claim({ result: false, message: "Empty account" });
check("a refused claim shows the network's reason, never 'still settling'", /refused/.test(refused) && /Empty account/.test(refused)
  && !/settling/i.test(refused), refused);
const ok = await claim({ result: true });
check("a landed claim still says the coins arrived", /Received 1 withdrawal/.test(ok), ok);

console.log(fails ? `\nFAILED: ${fails}` : "\nALL PASS — a private recipient can claim its first withdrawal");
process.exit(fails ? 1 : 0);
