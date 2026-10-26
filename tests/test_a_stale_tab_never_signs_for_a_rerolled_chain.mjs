/* A tab kept open across a reroll never signs for the new chain (G6 "a stale tab refused cleanly",
 * doc/stwo-migration.md §9.5; static/interface.js PAGE_CHAIN).
 *
 * Every rule a page applies comes with the /protocol.js it loaded: the gates, the VM hash a game commits with
 * (nadodapp algHashn: alghash on gen 28, BLAKE2s on gen 29), the RANDAO secret's form. The wallet used to adopt whatever
 * chain id its relay reported ("self-resolving upgrades"), so a gen-28 tab left open across the reroll would sign for
 * gen 29 under gen-28 rules — a game commitment hashed with the old hash can never be revealed, and its stake is lost.
 *
 * Pins, by RUNNING the wallet's and the SDK's own code with the network stubbed (no key is involved):
 *   - a relay on another chain is never adopted, and the page says so once;
 *   - nothing is submitted while the current relay is on another chain, nor any tx naming another chain;
 *   - back on the page's chain, signing resumes;
 *   - the page reloads by itself only when its OWN origin serves the new chain (a reload then brings matching code);
 *   - a candidate relay on another chain is never failed over to;
 *   - a game's signing request names its page's chain (both transports), and the wallet refuses one for another chain,
 *     and on a chain past generation 28 one that names none (a page older than the field).
 *
 * Run: node tests/test_a_stale_tab_never_signs_for_a_rerolled_chain.mjs
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(HERE, "..", "static", "interface.js"), "utf8");
const SDK = fs.readFileSync(path.join(HERE, "..", "static", "nadodapp.js"), "utf8");
function fnSrc(name, isAsync = false, src = SRC) {
  const i = src.indexOf((isAsync ? "async function " : "function ") + name + "(");
  if (i === -1) throw new Error(name + " not found");
  let depth = 0, j = src.indexOf("{", src.indexOf(")", i));
  for (; j < src.length; j++) { if (src[j] === "{") depth++; else if (src[j] === "}" && --depth === 0) break; }
  return src.slice(i, j + 1);
}
let fails = 0;
const check = (name, ok, detail = "") => { console.log((ok ? "PASS  " : "FAIL  ") + name + (ok ? "" : "  " + detail)); if (!ok) fails++; };
const tick = () => new Promise((r) => setTimeout(r, 0));

check("the page's chain is its /protocol.js chain, and CHAIN_ID starts there",
  /const PAGE_CHAIN = P\.CHAIN_ID;/.test(SRC) && /let CHAIN_ID = PAGE_CHAIN;/.test(SRC));

// ---- the wallet: identity, submit, failover ------------------------------------------------------------------------
function wallet({ relayChain, originChain }) {
  const rec = { logs: [], posts: 0, reloads: 0 };
  const env = {
    PAGE_CHAIN: "betanet-9", P: { CHAIN_GENERATION: 28 },
    $: () => null, LS_CHAIN_ID: "k", localStorage: { setItem() {} },
    log: (lvl, m) => rec.logs.push(m), i18: (k, d, v) => String(d).replace(/\{(\w+)\}/g, (_, n) => (v && n in v ? v[n] : "")),
    location: { protocol: "https:", origin: "https://home" },
    rpcJSON: async () => ({ data: { chain_id: relayChain.v, finality_depth: 45 } }),
    fetch: async (url, opt) => {
      if (url.endsWith("/submit_transaction")) { rec.posts++; return { ok: true, status: 200, text: async () => '{"result":true}' }; }
      return { json: async () => ({ chain_id: originChain.v }) };
    },
    canonicalize: (tx) => JSON.stringify(tx), relayBase: () => "https://relay",
    walletIdle: () => true,
    FINALITY_DEPTH: 45, POSW_LEASE_EPOCHS: 1, LEASE_BY_CLASS: {}, FIDELITY_MIN_GAP_EPOCHS: 1,
    state: { latest: 1000 }, relayMedianHeight: () => 1000, RELAY_HEIGHT_TOLERANCE: 20,
  };
  const src = "let staleChain = ''; let CHAIN_ID = PAGE_CHAIN; let netAdopted = false; let _reloadArmed = false;\n" +
    "let reloads = 0;\n" +
    "const relayExecPort = new Map();\n" + fnSrc("noteRelayExecPort") +   // refreshNetIdentity notes the relay's exec port
    fnSrc("staleChainMsg") + fnSrc("relayOnPageChain") + fnSrc("refreshNetIdentity", true) +
    fnSrc("_submitTransactionRaw", true) + fnSrc("relayAcceptable") +
    "function reloadWhenIdle() { reloads++; }\n" +
    "return { refreshNetIdentity, _submitTransactionRaw, relayAcceptable, get: () => ({ CHAIN_ID, staleChain, netAdopted, reloads }) };";
  return { api: new Function(...Object.keys(env), src)(...Object.values(env)), rec };
}
const relayChain = { v: "betanet-9" }, originChain = { v: "betanet-9" };
const w = wallet({ relayChain, originChain });
const TX = { chain_id: "betanet-9", txid: "t" };

await w.api.refreshNetIdentity();
check("on its own chain the page adopts the relay and signs", w.api.get().netAdopted && w.api.get().CHAIN_ID === "betanet-9");
check("...and a tx is submitted", (await w.api._submitTransactionRaw(TX)).data.result === true && w.rec.posts === 1);

relayChain.v = "betanet-10";                               // the relay rerolled; this page's origin has not yet
await w.api.refreshNetIdentity(); await tick(); await tick();
check("a relay on another chain is never adopted", w.api.get().CHAIN_ID === "betanet-9" && w.api.get().staleChain === "betanet-10");
check("...and the page says so once, naming both chains", w.rec.logs.length === 1 && /betanet-9/.test(w.rec.logs[0]) && /betanet-10/.test(w.rec.logs[0]));
await w.api.refreshNetIdentity(); await tick();
check("...only once", w.rec.logs.length === 1);
const refused = await w.api._submitTransactionRaw(TX);
check("nothing is submitted while the relay is on another chain", refused.data.result === false && w.rec.posts === 1 && /Nothing was sent/.test(refused.data.message));
check("the page does not reload while its own origin still serves its chain", w.api.get().reloads === 0);

originChain.v = "betanet-10";                              // now the page's origin serves the new chain too
relayChain.v = "betanet-9"; await w.api.refreshNetIdentity();   // (clear, then go stale again, to re-probe the origin)
relayChain.v = "betanet-10"; await w.api.refreshNetIdentity(); await tick(); await tick();
check("once its origin serves the new chain, the page reloads by itself (when idle)", w.api.get().reloads === 1);

relayChain.v = "betanet-9"; await w.api.refreshNetIdentity();
check("back on the page's chain, signing resumes", w.api.get().staleChain === "" && (await w.api._submitTransactionRaw(TX)).data.result === true);
const other = await w.api._submitTransactionRaw({ chain_id: "betanet-10", txid: "u" });
check("a tx naming another chain is never submitted", other.data.result === false && w.rec.posts === 2);
check("a candidate relay on another chain is never failed over to",
  w.api.relayAcceptable({ chain_id: "betanet-10", latest_block_height: 1000 }) === false
  && w.api.relayAcceptable({ chain_id: "betanet-9", latest_block_height: 1000 }) === true);

// ---- the game SDK names its page's chain in every signing request --------------------------------------------------
const payloadOf = SDK.match(/  _payloadOf\(obj\) \{[^\n]*\}/);
check("the SDK encodes every request through _payloadOf (both transports)",
  !!payloadOf && (SDK.match(/this\._payloadOf\(/g) || []).length === 2 && !/btoa\(unescape\(encodeURIComponent\(JSON\.stringify\((obj|job\.obj)\)/.test(SDK));
check("...which imports CHAIN_ID from its page's /protocol.js", /import \{[^}]*\bCHAIN_ID\b[^}]*\} from "\/protocol\.js"/.test(SDK));
const enc = new Function("CHAIN_ID", "btoa", "unescape", "return { " + payloadOf[0].trim() + " };")(
  "betanet-9", (s) => Buffer.from(s, "binary").toString("base64"), unescape);
const decoded = JSON.parse(decodeURIComponent(escape(Buffer.from(enc._payloadOf({ call: { fn: "move" } }), "base64").toString("binary"))));
check("...and the request carries it", decoded.chain === "betanet-9" && decoded.call.fn === "move");

// ---- the wallet refuses a game request built for another chain ----------------------------------------------------
const guard = SRC.slice(SRC.indexOf("  // A STALE GAME PAGE IS REFUSED (G6"), SRC.indexOf("  // an htlc_claim is value-free"));
check("the wallet's exec_sign guard is found before any signing branch", guard.includes("call.chain") && SRC.indexOf("  // A STALE GAME PAGE IS REFUSED") < SRC.indexOf("if (call.connect) {"));
const run = (call, gen) => { const out = []; const f = new Function("call", "PAGE_CHAIN", "P", "back", "i18", "out", guard + "\nout.push('passed');");
  f(call, "betanet-9", { CHAIN_GENERATION: gen }, (p) => out.push(p), (k, d) => d, out); return out; };
check("a request for the wallet's chain passes", run({ chain: "betanet-9" }, 28).join() === "passed");
const r1 = run({ chain: "betanet-10" }, 29);
check("a request for another chain is answered 'reload', never signed", r1.length === 1 && r1[0].startsWith("ok=0&err=") && /Reload/.test(decodeURIComponent(r1[0])));
check("a request naming no chain passes on gen 28 (pages older than the field, same chain)", run({}, 28).join() === "passed");
check("...and is refused on a chain past gen 28 (a tab kept open across the reroll)", run({}, 29)[0].startsWith("ok=0&err="));

console.log(fails ? `\nFAILED: ${fails}` : "\nALL PASS — a stale tab never signs for a rerolled chain");
process.exit(fails ? 1 : 0);
