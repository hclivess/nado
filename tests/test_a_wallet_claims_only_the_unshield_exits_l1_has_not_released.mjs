/* A wallet claims only the unshield exits L1 has NOT released yet (interface.js claimUnshields + nado.py /unshield_claimed).
 *
 * Loopback walk of the Stwo pool, 2026-10-12: the exec node's /exec/unshields lists every exit it ever recorded — it never
 * learns that L1 released one — so the wallet re-sent a refused claim for every past exit on every Shield-tab render, and
 * a manual claim then said "Still settling on L1" about coins already in the balance. The wallet now asks L1 which nonces
 * it released and claims the rest; a relay without the endpoint leaves the old behaviour (claim the whole list).
 * The function is RUN from static/interface.js with the network stubbed.
 *
 * Run: node tests/test_a_wallet_claims_only_the_unshield_exits_l1_has_not_released.mjs
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(HERE, "..", "static", "interface.js"), "utf8");
const NADO = fs.readFileSync(path.join(HERE, "..", "nado.py"), "utf8");
function fnSrc(name, isAsync = false) {
  const i = SRC.indexOf((isAsync ? "async function " : "function ") + name + "(");
  if (i === -1) throw new Error(name + " not found in interface.js");
  let depth = 0, j = SRC.indexOf("{", SRC.indexOf(")", i));
  for (; j < SRC.length; j++) { if (SRC[j] === "{") depth++; else if (SRC[j] === "}" && --depth === 0) break; }
  return SRC.slice(i, j + 1);
}
let fails = 0;
const check = (name, ok, detail = "") => { console.log((ok ? "PASS  " : "FAIL  ") + name + (ok ? "" : "  " + detail)); if (!ok) fails++; };

function run(claimedAnswer) {
  const sent = [], status = { textContent: "" };
  const env = {
    state: { wallet: { address: "ndo_me" } },
    execJSON: async (p) => p.startsWith("/exec/unshields") ? { unshields: [{ nonce: 1 }, { nonce: 2 }, { nonce: 3 }] }
                                                           : { addr: "ndo_me", amount: 5, nonce: new URLSearchParams(p.split("?")[1]).get("nonce"), proof: "p" },
    relayBase: () => "http://relay",
    fetch: async (url) => ({ json: async () => {
      if (url.includes("/get_settled")) return { state_root: "r" };
      if (url.includes("/unshield_claimed")) { if (claimedAnswer === "old") throw new Error("404 not json"); return { claimed: claimedAnswer }; }
      return {};
    } }),
    getLatestBlock: async () => ({ block_number: 10 }), nowSeconds: () => 0,
    buildTransferTx: (w, kind, a, f, target, data) => ({ data }),
    submitTransaction: async (tx) => { sent.push(String(tx.data.nonce)); return { data: { result: true } }; },
    $: () => status, i18: (k, fb, v) => fb.replace("{n}", v && v.n), log: () => {},
    setTimeout: () => {}, refreshDashboard: async () => {}, renderShield: async () => {},
  };
  const f = new Function(...Object.keys(env), fnSrc("claimUnshields", true) + "\nreturn claimUnshields;")(...Object.values(env));
  return f(false).then(() => ({ sent, status: status.textContent }));
}

let r = await run(["1", "2"]);
check("exits L1 already released are not claimed again", JSON.stringify(r.sent) === '["3"]', JSON.stringify(r.sent));
r = await run(["1", "2", "3"]);
check("with every exit released, nothing is sent and the wallet does not claim it is still settling",
      r.sent.length === 0 && !/settling/i.test(r.status), JSON.stringify(r));
r = await run("old");
check("a relay without /unshield_claimed: the whole list is claimed, as before", JSON.stringify(r.sent) === '["1","2","3"]', JSON.stringify(r.sent));
check("the node serves /unshield_claimed from L1's own record",
      NADO.includes('web.get("/unshield_claimed", unshield_claimed)') && /def unshield_claimed[\s\S]{0,1400}shield_nullifier_exists/.test(NADO));
console.log(fails ? `${fails} FAILURES` : "ALL PASS — a wallet claims only what L1 has not released");
process.exit(fails ? 1 : 0);
