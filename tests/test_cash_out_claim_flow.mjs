/**
 * A cash-out is finished automatically — in the wallet and from every game page — and says "received" only when it is.
 *
 * Run: node tests/test_cash_out_claim_flow.mjs
 *
 * WHY THIS EXISTS. A cash-out only debits the playable balance and records a withdrawal on the exec layer; the coins reach
 * the main-chain wallet when an L1 claim proves that record against a SETTLED root. Nothing built the claim, so every
 * cash-out stopped halfway (four of them, 10.06 NADO, 2026-10-10), while the wallet's dialog said "it lands automatically"
 * and the game SDK raised "✓ Cashed out — back in your main-chain wallet" the moment the PLAYABLE balance dropped.
 * tests/test_bridge_claim_js_matches_node.py pins that the claim the wallet builds is the tx L1 accepts; this pins the
 * behaviour around it, on the shipped code (the wallet block is lifted from interface.js, the SDK is the real module):
 *
 * WALLET (static/interface.js "CASH-OUT CLAIM")
 *   - a record not yet covered by a settled root shows "Cash-out pending" with the settlement wait, and submits nothing;
 *   - a provable record is claimed once, automatically, and held while the claim lands (no duplicate per poll);
 *   - a proof against a root the relay does not hold as settled is re-fetched against the relay's root, never submitted;
 *   - a refused claim keeps the panel with a retry line and a "Claim now" button; nothing says success;
 *   - "received" is logged only when the record is GONE (the exec node drops it when the claim finalizes);
 *   - the background-signer path (claim only the nonce a game names) claims exactly that one.
 * SDK (static/nadodapp.js _cashOuts / the withdraw balance watch)
 *   - the playable balance dropping after a cash-out says "recorded", never "cashed out";
 *   - a provable record is handed to the WALLET's background signer, one per pass, never twice while in flight;
 *   - a wallet that cannot sign in the background gets a "Finish in wallet" button — the tab is never navigated
 *     away on its own;
 *   - "✓ Cashed out" is raised only when the record is gone.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
let fails = 0;
const check = (name, cond, detail = "") => { console.log((cond ? "PASS  " : "FAIL  ") + name + (cond ? "" : ": " + detail)); if (!cond) fails++; };
const fill = (fb, vars) => String(fb).replace(/\{(\w+)\}/g, (m, n) => (vars && vars[n] != null ? String(vars[n]) : m));

// ============================================ WALLET ============================================
const js = readFileSync(join(ROOT, "static", "interface.js"), "utf8");
const cut = (a, b) => { const i = js.indexOf(a), j = js.indexOf(b, i + 1); return i >= 0 && j > i ? js.slice(i, j) : null; };
const block = cut("/* ==== CASH-OUT CLAIM", "/* ==== end CASH-OUT CLAIM ==== */");
check("the CASH-OUT CLAIM block is found in interface.js", !!block);
check("the dashboard poll runs the cash-out refresh", /function refreshDashboard\([\s\S]{0,1600}refreshCashOuts\(\)/.test(js));
check("the background signer handles a bridge_claim request",
      /if \(call\.bridge_claim\) \{[\s\S]{0,900}claimCashOuts\(d, \{ only: nonce \}\)/.test(js));

const ME = "me" + "a".repeat(48);
const SETTLED = "ab".repeat(32), OLD = "cd".repeat(32);
function fakeEl(id) {
  const cls = new Set(["hidden"]);
  return { id, textContent: "", disabled: false, onclick: null,
    classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c), contains: (c) => cls.has(c),
                 toggle: (c, on) => { if (on === undefined ? !cls.has(c) : on) cls.add(c); else cls.delete(c); } },
    hidden: () => cls.has("hidden") };
}
function wallet(opts) {
  const ev = { submits: [], logs: [], fetches: [] };
  const els = new Map();
  const relay = { tip: 1000, settled: SETTLED, submit: opts.submit || (() => ({ result: true })) };
  const exec = { resp: opts.exec };          // function(url) -> response body, or null for "unreachable"
  const env = {
    state: { wallet: { address: ME, publicKey: "pk", privateKey: "sk" }, latest: relay.tip },
    CHAIN_ID: "test", TX_INCLUSION_DELAY: 8, TX_TARGET_MARGIN: 300,
    $: (id) => { if (!els.has(id)) els.set(id, fakeEl(id)); return els.get(id); },
    execBase: () => "http://exec", relayBase: () => "http://relay",
    fetch: async (url) => {
      ev.fetches.push(url);
      if (url === "http://relay/get_settled") return { ok: true, json: async () => ({ state_root: relay.settled }) };
      if (url.startsWith("http://exec/exec/withdrawals?")) {
        const body = exec.resp(url);
        if (body === null) throw new TypeError("Failed to fetch");
        return { ok: true, json: async () => body };
      }
      return { ok: false, json: async () => ({}) };
    },
    getLatestBlock: async () => ({ block_number: relay.tip }),
    guardFrom: (h) => h + 8, nowSeconds: () => 1,
    randNonce: () => "n", finalizeTransaction: (draft, priv, fee) => ({ ...draft, fee, txid: "tx" + ev.submits.length }),
    submitResilient: async (build) => { const tx = await build(); ev.submits.push(tx); return { res: { data: relay.submit(tx) }, tx }; },
    log: (kind, msg) => ev.logs.push([kind, msg]),
    i18: (k, fb, vars) => fill(fb, vars),
    rawToNado: (r) => String(r), blocksToEta: (b) => b + " blocks",
  };
  const api = new Function("env", `with (env) { ${block}\n return { refreshCashOuts, claimCashOuts, fetchCashOuts, buildBridgeClaimTx, cashOutWaitBlocks }; }`)(env);
  return { env, ev, els, relay, exec, ...api, el: env.$ };
}
const rec = (nonce, amount, proof) => Object.assign({ nonce, amount: String(amount) }, proof ? { proof: { kv: "k" + nonce, path: {} }, state_root: proof } : {});
const listing = (pending) => ({ address: ME, pending, settled_root: SETTLED, settled_cursor: 970, cursor: 980, settle_every: 30 });

{ // 1. waiting for a settlement
  const w = wallet({ exec: () => listing([rec("1", 300)]) });
  await w.refreshCashOuts();
  check("a pending cash-out shows the panel", !w.el("cashOutPanel").hidden());
  check("... with its amount", w.el("cashOutAmt").textContent === "300 NADO", w.el("cashOutAmt").textContent);
  check("... and the settlement wait (settle cadence minus how far in, plus landing)",
        w.el("cashOutWhen").textContent.includes("Waiting for the next settlement (~36 blocks)"), w.el("cashOutWhen").textContent);
  check("nothing is submitted before a settled root covers it", w.ev.submits.length === 0);
  check("no Claim-now button for something that cannot be claimed yet", w.el("btnClaimCashOut").hidden());
  check("an overdue settle reads as the minimum wait, never negative",
        w.cashOutWaitBlocks({ settle_every: 30, cursor: 1100, settled_cursor: 970 }) === 16);
}
{ // 2. provable -> claimed once, held while it lands, "received" only when gone
  let pending = [rec("1", 300, SETTLED)];
  const w = wallet({ exec: () => listing(pending) });
  await w.refreshCashOuts();
  const tx = w.ev.submits[0];
  check("a provable cash-out is claimed automatically", w.ev.submits.length === 1, w.ev.submits.length);
  check("... as a self-claimed, fee-exempt bridge_withdraw with the served proof", tx && tx.recipient === "bridge_withdraw" &&
        tx.sender === ME && tx.data.addr === ME && tx.fee === 0 && tx.amount === 0 && tx.data.amount === 300n &&
        tx.data.nonce === "1" && tx.data.proof.kv === "k1" && tx.min_block === 1008 && tx.max_block === 1300, JSON.stringify(tx, (k, v) => typeof v === "bigint" ? v + "n" : v));
  check("the panel says it is confirming, not done", /Claim sent — confirming/.test(w.el("cashOutWhen").textContent), w.el("cashOutWhen").textContent);
  check("no success is claimed on submit", !w.ev.logs.some(([, m]) => /received/i.test(m)), JSON.stringify(w.ev.logs));
  await w.refreshCashOuts();
  check("the next poll does not claim it again while the claim lands", w.ev.submits.length === 1, w.ev.submits.length);
  w.relay.tip = 1000 + 8 * 4; w.env.state.latest = w.relay.tip;
  await w.refreshCashOuts();
  check("a claim that has not landed after its window is re-sent", w.ev.submits.length === 2, w.ev.submits.length);
  pending = [];
  await w.refreshCashOuts();
  check("once the record is gone the wallet says received", w.ev.logs.some(([k, m]) => k === "ok" && m === "Cash-out received: +300 NADO is in your spendable balance."), JSON.stringify(w.ev.logs));
  check("... and the panel hides", w.el("cashOutPanel").hidden());
}
{ // 3. a proof against a root the relay does not hold as settled is re-fetched, never submitted as is
  const w = wallet({ exec: (url) => listing([rec("1", 300, url.includes("&root=" + SETTLED) ? SETTLED : OLD)]) });
  await w.refreshCashOuts();
  check("a stale-root proof is re-asked against the relay's settled root", w.ev.fetches.some((u) => u.endsWith("&root=" + SETTLED)), JSON.stringify(w.ev.fetches));
  check("... and the claim carries the settled-root proof", w.ev.submits.length === 1);
  const w2 = wallet({ exec: () => listing([rec("1", 300, OLD)]) });
  await w2.refreshCashOuts();
  check("a proof that never matches the settled root is never submitted", w2.ev.submits.length === 0);
}
{ // 4. a refused claim: retry line + Claim now, no success
  const w = wallet({ exec: () => listing([rec("1", 300, SETTLED)]), submit: () => ({ result: false, message: "bridge escrow underfunded" }) });
  await w.refreshCashOuts();
  check("a refused claim says so and that it retries", w.el("cashOutWhen").textContent === "Claim not accepted yet (bridge escrow underfunded) — retrying automatically.", w.el("cashOutWhen").textContent);
  check("... offers Claim now", !w.el("btnClaimCashOut").hidden());
  check("... and never says received", !w.ev.logs.some(([, m]) => /received/i.test(m)));
  const before = w.ev.submits.length;
  await w.el("btnClaimCashOut").onclick();
  check("Claim now submits a claim", w.ev.submits.length >= before + 1, w.ev.submits.length);
}
{ // 5. the background-signer path claims only the nonce the game named
  const w = wallet({ exec: () => listing([rec("1", 300, SETTLED), rec("2", 40, SETTLED)]) });
  const r = await w.claimCashOuts(await w.fetchCashOuts(), { only: "2" });
  check("only the named nonce is claimed", w.ev.submits.length === 1 && w.ev.submits[0].data.nonce === "2" && r.submitted === 1 && r.txid === "tx0", JSON.stringify(r));
  const r2 = await w.claimCashOuts(await w.fetchCashOuts(), { only: "2" });
  check("asking again while it lands answers with the claim already sent", w.ev.submits.length === 1 && r2.submitted === 1 && r2.txid === "tx0", JSON.stringify(r2));
  const w3 = wallet({ exec: () => listing([rec("7", 5)]) });
  const r3 = await w3.claimCashOuts(await w3.fetchCashOuts(), { only: "7" });
  check("an unsettled nonce is answered 'not settled yet', nothing submitted", r3.submitted === 0 && r3.err === "not settled yet" && w3.ev.submits.length === 0, JSON.stringify(r3));
}
{ // 6. the exec node unreachable leaves the panel as it was
  let up = true;
  const w = wallet({ exec: () => (up ? listing([rec("1", 300)]) : null) });
  await w.refreshCashOuts(); up = false; await w.refreshCashOuts();
  check("an exec blip does not hide a pending cash-out", !w.el("cashOutPanel").hidden());
}

// ============================================== SDK ==============================================
const store = new Map();
const bars = [];
globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) };
globalThis.location = { search: "", pathname: "/", hash: "", href: "http://x/", origin: "http://x" };
globalThis.history = { replaceState() {} };
const mkEl = () => { const e = { style: {}, children: [], textContent: "", classList: { add() {}, remove() {}, toggle() {} },
  appendChild(c) { e.children.push(c); }, remove() { e.removed = true; }, setAttribute() {} }; return e; };
globalThis.document = {
  getElementById: () => null, createElement: mkEl,
  body: { appendChild(el) { bars.push(el); } }, documentElement: { appendChild() {} },
  addEventListener() {}, querySelectorAll: () => [],
};
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
let execList = { pending: [] }, execBal = 0n;
const sdkFetches = [];
globalThis.fetch = async (url) => {
  sdkFetches.push(url);
  if (url.includes("/exec/withdrawals?")) return { ok: true, json: async () => execList };
  if (url.includes("/exec/bridge?")) return { ok: true, json: async () => ({ balances: { [ME]: execBal.toString() } }) };
  if (url.includes("/get_account?")) return { ok: true, json: async () => ({ balance: 0 }) };
  return { ok: false, json: async () => ({}) };
};
const { NadoDapp } = await import(new URL("../static/nadodapp.js", import.meta.url).href);
const lastBar = () => bars[bars.length - 1];
const barText = () => (lastBar() ? lastBar().textContent : "");
function sdk() {
  const d = new NadoDapp({ cid: "c", app: "test" });
  d.me = ME;
  d.bg = [];
  d.redirects = [];
  d._goBackground = (obj, pend, isValue, onNeedUI, onResult) => d.bg.push({ obj, pend, isValue, onNeedUI, onResult });
  d._goRedirect = (obj, pend) => d.redirects.push({ obj, pend });
  return d;
}
const again = async (d) => { d._cashAt = 0; await d._cashOuts(); };

{ // the playable balance dropping after a cash-out is NOT the coins arriving
  const d = sdk();
  execBal = 1000n; await d._balances();
  d._balWatch = { phase: "withdraw", exec: null };
  await d._balances();                       // baseline
  execBal = 400n; bars.length = 0;
  await d._balances();
  check("SDK: a cash-out moving the playable balance says 'recorded', not 'cashed out'",
        /Cash-out recorded/.test(barText()) && !/Cashed out/.test(barText()), barText());
}
{
  const d = sdk();
  execList = { pending: [] };
  await d._cashOuts();
  check("SDK: nothing pending, nothing asked of the wallet", d.bg.length === 0);
  execList = { pending: [rec("1", 300)] };
  await again(d);
  check("SDK: a record not yet settled is left alone", d.bg.length === 0);
  const n = sdkFetches.length; await d._cashOuts();
  check("SDK: the poll is rate-limited", sdkFetches.length === n);
  execList = { pending: [rec("1", 300, SETTLED), rec("2", 40, SETTLED)] };
  await again(d);
  check("SDK: a provable record is handed to the wallet's background signer — one per pass",
        d.bg.length === 1 && d.bg[0].obj.bridge_claim.nonce === "1" && d.bg[0].isValue === false && typeof d.bg[0].onNeedUI === "function", JSON.stringify(d.bg.map((b) => b.obj)));
  await again(d);
  check("SDK: the next pass takes the next record, never the in-flight one again", d.bg.length === 2 && d.bg[1].obj.bridge_claim.nonce === "2", JSON.stringify(d.bg.map((b) => b.obj)));
  await again(d);
  check("SDK: both in flight -> nothing more asked", d.bg.length === 2);
  bars.length = 0;
  d.bg[0].onNeedUI("locked");
  const btn = lastBar() && lastBar().children.find((c) => c.textContent === "Finish in wallet");
  check("SDK: a wallet that cannot sign in the background gets a 'Finish in wallet' button", /finish it in your wallet/.test(barText()) && !!btn, barText());
  check("SDK: ... and the tab is NOT navigated on its own", d.redirects.length === 0);
  btn.onclick();
  check("SDK: the button sends the player to the wallet to claim that cash-out",
        d.redirects.length === 1 && d.redirects[0].obj.bridge_claim.nonce === "1" && d.redirects[0].pend.phase === "bridge_claim", JSON.stringify(d.redirects));
  bars.length = 0;
  execList = { pending: [rec("2", 40, SETTLED)] };
  await again(d);
  check("SDK: '✓ Cashed out' only once the record is gone", /Cashed out/.test(barText()) && barText().includes("(+0.00000003 NADO)"), barText());
}
{
  const d = sdk();
  d._bgOff = true;
  execList = { pending: [rec("5", 9, SETTLED)] };
  bars.length = 0;
  await d._cashOuts();
  check("SDK: a wallet known not to background-sign is not tried; the bar is shown at once",
        d.bg.length === 0 && d.redirects.length === 0 && /finish it in your wallet/.test(barText()), barText());
}

console.log(fails ? `\n${fails} FAILED` : "\nall checks passed");
process.exit(fails ? 1 : 0);
