/* Every Stwo deposit note is restorable from the recovery phrase — on another device, from two devices, right after
 * the deposit, and on the chain after a reroll that carried the pool.
 *
 * Pre-push review 2026-10-12 (stwo-on). REPRODUCES FOUR WAYS a deposit note is not restored (each FAILS on 941a93f7):
 *
 *  1. TWO DEVICES RE-USE ONE DEPOSIT INDEX. stwoDepositIndexTake's floors are all per-device (localStorage, the page,
 *     the device's own notes). The once-per-device restore scan (stwoDepositKey()+".scan") runs when the wallet first
 *     opens, so a device that opened before another device deposited never learns that index and takes it again.
 *     Both deposits then publish the SAME owner — the link the fresh-owner rule exists to prevent.
 *  2. A RESTORE KEEPS ONE NOTE PER OWNER. stwoRecoverDeposits keys the account's deposits by owner
 *     (new Map(deps.map(t => [owner, t]))), so two deposits under one index collapse: the restored wallet banks one and
 *     the other is unrecoverable once its device's storage is gone (its rho exists only in the lost note and the old tx).
 *  3. A DEPOSIT NOT YET APPLIED BY THE EXEC NODE IS SKIPPED FOR GOOD. A deposit whose commitment is not in the tree
 *     yet (exec trails L1 by the finality depth) is `continue`d, the scan is then marked done, and it never runs again
 *     on that device: restoring a wallet minutes after depositing on another device never shows that deposit.
 *  4. A REROLL ERASES THE RESTORE SOURCE. The carry (exec_genesis stwo_pool) keeps the commitments, but the restore
 *     reads the account's OWN shield transactions — which live on the old chain. On the new chain the account has none,
 *     so a deposit note carried across the reroll cannot be restored from the recovery phrase at all.
 *
 * The wallet's own functions are RUN (extracted from static/interface.js) with static/stark/stwo_js.js, a generated
 * throwaway key (never a real one) and the chain stubbed.
 *
 * Run: node tests/test_every_stwo_deposit_is_restorable_from_the_recovery_phrase.mjs
 */
import fs from "fs";
import path from "path";
import crypto from "crypto";
import { fileURLToPath } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(HERE, "..", "static", "interface.js"), "utf8");
const stwo = await import(path.join(HERE, "..", "static", "stark", "stwo_js.js"));
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

// ---- one chain (L1 txs + the exec tree) shared by every device -------------------------------------------------------
const ADDR = "ndo_review_account", KEY = crypto.randomBytes(32).toString("hex");   // throwaway, generated here
const chain = { txs: [], leaves: new Set(), nfs: new Set(), carried: [] };
let seq = 0;

function device(submit) {
  const store = new Map();
  const localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) };
  const env = {
    state: { wallet: { address: ADDR, privateKey: KEY, publicKey: "pk" } }, localStorage, _stwo: stwo,
    blake2bHash: (parts) => crypto.createHash("blake2b512").update(JSON.stringify(parts)).digest("hex").slice(0, 64),
    shieldStwo: () => true, shieldWide: () => false, ensureShielded: () => {}, refreshShieldRules: async () => {},
    shieldPaused: () => false, wideDepositClosed: () => false, _shieldTip: 0,
    nadoToRaw: (s) => BigInt(s) * 10000000000n, rawToNado: (x) => String(x),
    $: () => ({ value: "5" }), log: () => {}, i18: (k, fb) => fb,
    _randField: () => BigInt("0x" + crypto.randomBytes(7).toString("hex")).toString(),
    noteCommit: (v, owner, rho) => stwo.commit(v, owner, rho),
    getLatestBlock: async () => ({ block_number: 100 }), MIN_TX_FEE: 1, nowSeconds: () => 0,
    buildTransferTx: (wallet, kind, amount, fee, target, data) =>
      ({ txid: "t" + (++seq), sender: wallet.address, recipient: kind, amount: String(amount), data }),
    submitTransaction: submit || (async (tx) => { chain.txs.push(tx); return { data: { result: true } }; }),
    stwoOwnTransactions: async (addr) => chain.txs.filter((t) => t.sender === addr),
    execJSON: async (p) => (p === "/exec/field_leaves" ? { leaves: [...chain.leaves] }
                            : p === "/exec/stwo_nullifiers" ? { nullifiers: [...chain.nfs] }
                            : p.startsWith("/exec/stwo_carried_deposits") ? { deposits: chain.carried.filter((r) => r.addr === ADDR) } : {}),
    setTimeout: () => {}, renderShield: async () => {},
  };
  const body = [constSrc("DOMAIN_SHIELD_NSK_STWO"), constSrc("ZADDR_STWO"), constSrc("STWO_RESTORE_MARGIN"),
    fnSrc("shieldNskStwo"), fnSrc("shieldOwner"), fnSrc("ownerStr"), fnSrc("cmStr"), fnSrc("shieldStoreKey"),
    fnSrc("_notePool"), fnSrc("_activePool"), fnSrc("loadNotes"), fnSrc("saveNotes"),
    fnSrc("stwoDepositNsk"), fnSrc("noteNskWire"), fnSrc("stwoRestoreKey"), fnSrc("_stwoRestoreLoad"), fnSrc("_stwoRestoreSave"),
    fnSrc("stwoCarriedDeposits", true),
    fnSrc("doShield", true), fnSrc("stwoRecoverDeposits", true),
    "return { doShield, stwoRecoverDeposits, loadNotes };"].join("\n");
  return new Function(...Object.keys(env), body)(...Object.values(env));
}
const lastDeposit = () => chain.txs[chain.txs.length - 1];
const apply = (t) => chain.leaves.add(t.data.cm);                // the exec node applies the deposit
const sum = (ns) => ns.filter((n) => !n.spent).reduce((s, n) => s + BigInt(n.value), 0n);

// 1. two devices, one wallet
const A = device(), B = device();
await A.stwoRecoverDeposits();                 // A opens the wallet first (renderShield): nothing yet, scan marked done
await B.doShield(); apply(lastDeposit());      // B deposits 5
await A.stwoRecoverDeposits();                 // A renders again later
await A.doShield(); apply(lastDeposit());      // A deposits 5
const [d1, d2] = chain.txs;
check("two devices of one wallet never publish the same deposit owner (no index re-use)", d1.data.owner !== d2.data.owner,
      `both deposits published owner ${d1.data.owner.slice(0, 16)}… (index 0 taken on each device)`);

// 2. a third device restores from the recovery phrase
const C = device();
await C.stwoRecoverDeposits();
check("a restored wallet banks every deposit the account made", C.loadNotes().length === 2 && sum(C.loadNotes()) === 2n * 50000000000n,
      `restored ${C.loadNotes().length} of 2 deposits (${sum(C.loadNotes())} raw of ${2n * 50000000000n})`);

// 3. a restore just after a deposit the exec node has not applied yet
chain.txs.length = 0; chain.leaves.clear();
const E = device();
await E.doShield();                            // deposited on E; the exec node has not applied it yet
const D = device();
await D.stwoRecoverDeposits();                 // the user opens the wallet on a new phone right away
apply(lastDeposit());                          // ...the exec node applies it a minute later
await D.stwoRecoverDeposits();                 // and the wallet renders again
check("a deposit the exec node applies after the first restore scan is still restored", D.loadNotes().length === 1,
      `restored ${D.loadNotes().length} of 1 (the scan was marked done while the leaf was still pending)`);

// 4. a reroll that carried the pool: the commitments cross, the account's old shield transactions do not
chain.txs.length = 0; chain.leaves.clear();
const F = device();
await F.doShield(); apply(lastDeposit());
const carried = new Set(chain.leaves);
// new chain: the exec genesis carries the commitments AND the deposits' public records (execnode/exec_genesis.py); L1 starts empty
chain.carried = chain.txs.map((t) => ({ addr: t.sender, amount: t.amount, owner: t.data.owner, rho: t.data.rho }));
chain.txs.length = 0; chain.leaves = carried;
const G = device();
await G.stwoRecoverDeposits();
check("a deposit note carried across a reroll is restorable from the recovery phrase", G.loadNotes().length === 1,
      `restored ${G.loadNotes().length} of 1: the restore reads the account's own shield txs, which stayed on the old chain`);

// 5. refused deposits burn indices (taken BEFORE the send), and the restore stops after STWO_DEPOSIT_GAP = 20 misses
chain.txs.length = 0; chain.leaves = new Set();
const R = device();
let refuse = 20;                                        // the node refuses 20 deposits (rate limit, balance, fee...)
const W = device(async (tx) => (refuse-- > 0 ? { data: { result: false, message: "refused" } }
                                             : (chain.txs.push(tx), { data: { result: true } })));
for (let i = 0; i < 21; i++) await W.doShield();       // 20 refused, then one lands
apply(lastDeposit());
await R.stwoRecoverDeposits();
check("a deposit made after 20 refused deposits is still restorable (refusals burn indices past the scan gap)",
      chain.txs.length === 1 && R.loadNotes().length === 1,
      `restored ${R.loadNotes().length} of ${chain.txs.length}: the landed deposit used index 20, the scan stopped at 19`);

console.log(fails ? `${fails} FAILURES` : "ALL PASS — every Stwo deposit is restorable from the recovery phrase");
process.exit(fails ? 1 : 0);
