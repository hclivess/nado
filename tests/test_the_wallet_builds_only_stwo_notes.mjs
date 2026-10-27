/* The wallet builds Stwo notes and proofs only (G6, doc/stwo-migration.md §9.5).
 *
 * The legacy, field and wide pools are closed (L1 refuses their deposits, the exec layer their spends from
 * STWO_POOL_HEIGHT) and were measured EMPTY on the live chain on 2026-10-25 (0 commitments, pool_value 0); a reroll
 * refuses to carry a note in any of them. So the wallet dropped them: no retired module is imported, no proof_rules are
 * read, and a page that cannot load the Stwo prover stops instead of falling back — a deposit escrowed under another
 * pool's owner lands in the Stwo pool where no key can ever spend it.
 *
 * The wallet's own functions are RUN (extracted from static/interface.js) with the network stubbed; no key is involved.
 *
 * Run: node tests/test_the_wallet_builds_only_stwo_notes.mjs
 */
import fs from "fs";
import path from "path";
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

// ---- 1. nothing of the retired pools is imported ------------------------------------------------------------------
const imports = (SRC.match(/^import [^;]*;$/gm) || []).join("\n") + "\n" + (SRC.match(/import\(\s*"[^"]+"\s*\)/g) || []).join("\n");
const RETIRED = ["alghash.js", "alghash2.js", "stark/joinsplit2.js", "stark/joinsplit3.js", "stark/stark.js",
                 "stark/field.js", "stark/hashing.js", "stark/tree.js", "goldilocks-wasm.js", "shielded.js"];
const found = RETIRED.filter((m) => imports.includes("/" + m + '"'));
check("the wallet imports no retired pool's module", found.length === 0, found.join(", "));
check("...and imports the Stwo prover on demand", /import\("\.\/stark\/stwo_js\.js"\)/.test(SRC));
check("...and reads no retired prover's rules", !SRC.includes("st.proof_rules") && !SRC.includes("pr.shield_wide"));

// ---- 2. only Stwo notes are the balance, and the others stay on disk untouched -----------------------------------
const store = new Map();
const localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) };
const notesApi = new Function("localStorage", "state",
  fnSrc("shieldStoreKey") + fnSrc("_notePool") + fnSrc("loadNotes") + fnSrc("saveNotes") + "return { loadNotes, saveNotes };")(
  localStorage, { wallet: { address: "ndoX" } });
const WIDE = { value: "5", rho: "1", cm: "ab".repeat(32), spent: false };          // a wide note: 64-hex cm, no tag
const LEGACY = { value: "6", rho: "2", cm: "12345", spent: false };                // a legacy note: decimal cm
const STWO = { value: "7", rho: "3", cm: "cd".repeat(32), spent: false, pool: "stwo" };
store.set("nado.shieldf.ndoX", JSON.stringify([WIDE, LEGACY, STWO]));
const got = notesApi.loadNotes();
check("the balance holds the Stwo note only", got.length === 1 && got[0].cm === STWO.cm, JSON.stringify(got));
notesApi.saveNotes([...got, { value: "8", rho: "4", cm: "ef".repeat(32), spent: false }]);
const disk = JSON.parse(store.get("nado.shieldf.ndoX"));
check("saving keeps the other pools' entries on disk untouched", disk.some((n) => n.cm === WIDE.cm && !n.pool) && disk.some((n) => n.cm === LEGACY.cm));
check("...and stamps every saved note as a Stwo note", disk.filter((n) => n.pool === "stwo").length === 2);

// ---- 3. a note's rho is a u64, the range L1 admission and the circuit take ---------------------------------------
const randRho = new Function("crypto", fnSrc("_randField") + "return _randField;")(globalThis.crypto);
let rhoOk = true;
for (let i = 0; i < 2000; i++) { const r = randRho(); if (!/^[0-9]+$/.test(r) || BigInt(r) >= (1n << 64n)) { rhoOk = false; break; } }
check("rho is a decimal u64", rhoOk);

// ---- 4. no pool, no deposit: without the prover the wallet stops and says why ------------------------------------
function poolApi({ module }) {
  const logs = [], sent = [];
  const env = {
    staleChain: "",
    log: (lvl, m) => logs.push(m), i18: (k, d) => d,
    relayBase: () => "https://relay",
    fetch: async () => ({ json: async () => ({ latest_block_height: 1000 }) }),
    _loadStwo: module,
    submitTransaction: async (tx) => { sent.push(tx); return { data: { result: true } }; },
  };
  const src = SRC.slice(SRC.indexOf("let _stwoGate = false, _stwo = null;"), SRC.indexOf("// owner ids and commitments as the wire carries them"))
    .replace('await import("./stark/stwo_js.js")', "await _loadStwo()") + "\nlet _shieldTip = 0;\n" + fnSrc("shieldDeposit", true);
  const api = new Function(...Object.keys(env), src + "\nreturn { refreshShieldRules, shieldPaused, shieldDeposit, shieldStwo };")(...Object.values(env));
  return { api, logs, sent };
}
let p = poolApi({ module: async () => ({}) });
await p.api.refreshShieldRules();
check("the pool is live (from block 1)", p.api.shieldStwo() === true && p.api.shieldPaused() === false);
// "below the gate every shielded action stops" retired in G9: generation 28's STWO_POOL_HEIGHT is inlined as block 1
p = poolApi({ module: async () => { throw new Error("offline"); } });
await p.api.refreshShieldRules();
check("a prover that does not load stops every action, never falls back", p.api.shieldPaused() === true && /could not load/.test(p.logs[0] || ""));
check("...and a deposit is never built or sent", (await p.api.shieldDeposit(10n, {})) === false && p.sent.length === 0);

// ---- 5. an address of a retired pool is refused, so nobody is paid into a note they can never spend --------------
const za = new Function("i18", "shieldOwner",
  "const ZADDR_STWO = \"zaddr_\";" + fnSrc("shieldAddr") + fnSrc("_b36") + fnSrc("parseShieldAddr") + "return { shieldAddr, parseShieldAddr };")(
  (k, d) => d, () => "0f".repeat(32));
let refused = 0;
for (const old of ["zaddr" + 12345n.toString(36), "zaddr" + ((1n << 255n) + 7n).toString(36)]) { try { za.parseShieldAddr(old); } catch (e) { refused++; } }
check("a legacy or wide zaddr is refused", refused === 2);
check("a Stwo zaddr parses back to its owner", za.parseShieldAddr(za.shieldAddr()) === "0f".repeat(32));

// ---- 6. the prover refuses an exec node that is not serving the Stwo pool -----------------------------------------
const prove = new Function("refreshShieldRules", "shieldStwo", "stwoMissing", "i18", "execJSON", "_onDeviceProveStwo",
  fnSrc("_onDeviceProve2", true) + "return _onDeviceProve2;")(
  async () => true, () => true, () => false, (k, d) => d, async () => ({ pool: "wide", leaves: [] }), async () => ({ ok: true }));
let poolErr = "";
try { await prove({}, "x"); } catch (e) { poolErr = e.message; }
check("a proof is never built against another pool's leaves", /disagree on which pool/.test(poolErr), poolErr);

console.log(fails ? `\nFAILED: ${fails}` : "\nALL PASS — the wallet builds Stwo notes and proofs only");
process.exit(fails ? 1 : 0);
