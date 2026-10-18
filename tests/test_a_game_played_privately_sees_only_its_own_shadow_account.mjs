/* A game played privately sees only its own shadow account: derived from the master seed and the game's origin, a
 * different one per game, the same whichever HD account is active, and the one that signs everything for that game
 * (static/interface.js shadowKeypair / signerFor / resumePendingExecSign / doFundShadow).
 *
 * Shadow accounts (2026-10-18; Starknet's design): a game in private mode gets a separate account funded from the
 * Stwo pool by a relayed spend that pays the relay by its fee (protocol STWO_FEE_TO_HEIGHT) and sends the payout to
 * the shadow address, so nothing on chain ties the game's player to the wallet. Pins, running the wallet's own
 * functions with the crypto stubbed by deterministic hashes and a throwaway seed:
 *   1. the shadow key is a pure function of (master seed, origin): stable, distinct per game, never the master or an
 *      HD account, unchanged when the active account changes;
 *   2. signerFor gives the shadow account exactly when the game is in private mode, else the active account;
 *   3. inside resumePendingExecSign every signature and every answered address goes through `signer` — no
 *      state.wallet after it is chosen (so a private game never gets the real account);
 *   4. doFundShadow proves one relayed spend per banknote that pays the shadow address the amount and the relay its
 *      fee (fee_to), keeping the change, and never builds a transaction under any account.
 *
 * Run: node tests/test_a_game_played_privately_sees_only_its_own_shadow_account.mjs
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
const constSrc = (name) => { const m = SRC.match(new RegExp("const " + name + " = [^;]+;")); if (!m) throw new Error(name); return m[0]; };
let fails = 0;
const check = (name, ok, detail = "") => { console.log((ok ? "PASS  " : "FAIL  ") + name + (ok ? "" : "  " + detail)); if (!ok) fails++; };

const MASTER = crypto.randomBytes(32).toString("hex");            // throwaway, generated here
const store = new Map();
const env = {
  state: { masterSeed: MASTER, wallet: { address: "main", privateKey: MASTER } },
  localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) },
  blake2bHash: (parts, n) => crypto.createHash("blake2b512").update(JSON.stringify(parts)).digest("hex").slice(0, 2 * (n || 32)),
  keypairFromPriv: (priv) => ({ privateKey: priv, publicKey: "pk" + priv.slice(0, 6), address: "a" + priv.slice(0, 20) }),
  EXEC_SIGN_ALLOW: ["https://chess.nadochain.com", "https://dice.nadochain.com"],
};
const body = [constSrc("DOMAIN_HD_SHADOW"), constSrc("LS_SHADOW"), constSrc("DOMAIN_HD_ACCOUNT"), fnSrc("masterSeedOf"),
  fnSrc("accountChildSeed"), fnSrc("accountKeypair"), fnSrc("shadowOrigins"), fnSrc("shadowOn"), fnSrc("setShadowOn"),
  fnSrc("shadowKeypair"), fnSrc("signerFor"), fnSrc("shadowCandidateOrigins"),
  "return { shadowKeypair, signerFor, setShadowOn, shadowOn, accountKeypair, shadowCandidateOrigins };"].join("\n");
const W = new Function(...Object.keys(env), body)(...Object.values(env));
const CHESS = "https://chess.nadochain.com", DICE = "https://dice.nadochain.com";

// 1.
const c1 = W.shadowKeypair(CHESS), c2 = W.shadowKeypair(CHESS), d1 = W.shadowKeypair(DICE);
check("1. a game's shadow account is stable", c1.address === c2.address);
check("...different per game", c1.address !== d1.address);
check("...never the master or an HD account", ![0, 1, 2, 3].some((i) => W.accountKeypair(MASTER, i).address === c1.address));
env.state.wallet = W.accountKeypair(MASTER, 2);                    // the user switched to Account 3
check("...and unchanged when another account is active (it comes from the master seed)", W.shadowKeypair(CHESS).address === c1.address);
// 2.
check("2. a game not in private mode is signed for by the active account", W.signerFor(CHESS) === env.state.wallet);
W.setShadowOn(CHESS, true);
check("...in private mode, by its shadow account", W.signerFor(CHESS).address === c1.address && W.shadowOn(CHESS));
check("...and only that game", W.signerFor(DICE) === env.state.wallet);
W.setShadowOn(CHESS, false);
check("...until private mode is turned off", W.signerFor(CHESS) === env.state.wallet);
check("a restore checks every official game's shadow account", W.shadowCandidateOrigins().includes(DICE));
// 3.
const exec = fnSrc("resumePendingExecSign", true), cut = exec.indexOf("const signer = signerFor(retUrl.origin);");
check("3. resumePendingExecSign chooses the signer from the asking site", cut > 0);
check("...and uses only `signer` from there on (no state.wallet signs or answers for a game)",
      cut > 0 && !exec.slice(cut).includes("state.wallet"), (exec.slice(cut).match(/.{40}state\.wallet.{40}/) || [""])[0]);
// 4. doFundShadow's witness
const wits = [], txs = [];
let notes = [{ cm: "n1", value: "1000000", rho: "5", spent: false }];
const fenv = {
  state: { masterSeed: MASTER, wallet: { address: "main", privateKey: MASTER } },
  ensureShielded: () => {}, refreshShieldRules: async () => {}, shieldPaused: () => false,
  shieldStwo: () => true, stwoFeeToLive: () => true,
  shadowKeypair: (o) => ({ address: "shadow-of-" + o }),
  stwoRelays: async () => [{ url: "https://r1", address: "relay1", fee: 100000 }, { url: "https://r2", address: "relay2", fee: 100000 }],
  selectNotesFor: (amt) => notes.filter((n) => !n.spent && BigInt(n.value) >= amt).slice(0, 1).map((n) => ({ cm: n.cm })),
  insufficientMsg: () => "insufficient", uiConfirm: async () => true, log: () => {}, i18: (k, fb) => fb, rawToNado: String,
  loadNotes: () => notes.map((n) => ({ ...n })), saveNotes: (ns) => { notes = ns; },
  shieldOwner: () => "me", ownerStr: (x) => String(x), noteNskWire: () => "nsk", _randField: () => "7",
  proveTransfer2: async (w) => { wits.push(w); return { ok: true, cm_out1: "change1", cm_out2: "out2" }; },
  _markSpendPending: () => {}, buildTransferTx: () => { txs.push(1); return {}; }, submitTransaction: async () => { txs.push(1); return {}; },
};
const fund = new Function(...Object.keys(fenv), fnSrc("doFundShadow", true) + "\nreturn doFundShadow;")(...Object.values(fenv));
const ok = await fund(CHESS, 300000n);
const w = wits[0] || {};
check("4. funding proves a withdrawal of the amount to the shadow address", ok && w.public_value === "-300000" && w.withdraw_addr === "shadow-of-" + CHESS, JSON.stringify(w));
check("...paying the relay by its fee (fee_to relays, fee = the relay's)", w.fee === "100000" && Array.isArray(w.fee_to_relays) && w.fee_to_relays.length === 2);
check("...keeping the change in the wallet", w.v1 === String(1000000 - 300000 - 100000) && notes.some((n) => n.cm === "change1" && n.value === "600000"));
check("...and builds no transaction under any account", txs.length === 0);
console.log(fails ? `${fails} FAILURES` : "ALL PASS — a game played privately sees only its own shadow account");
process.exit(fails ? 1 : 0);
