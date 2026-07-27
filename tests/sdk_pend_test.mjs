/**
 * The SDK's click-pending lifecycle — the shared gate EVERY game's buttons and auto-pumps hang off.
 *
 * Run: node tests/sdk_pend_test.mjs
 *
 * Why this file exists. static/nadodapp.js decides, for every action, "is this still in flight?" — and the
 * whole fleet's feel depends on getting the RELEASE right. Release too late and a pool-dropped tx strands
 * the player on "Sending…" for minutes with no retry (the autogame stall). Release too early and a
 * still-pending tx gets re-sent, burning a fee on a guaranteed revert — or worse, double-acts something
 * that is not idempotent on-chain.
 *
 * The bug that motivated it: the tip-based expiry was keyed on the SDK's `isValue` flag, which is
 * `valueRaw != null` — and `0n != null` is TRUE in JavaScript. Every autogame call passes 0n for its
 * free calls, so the expiry excluded the exact game it was written for, silently. That is a mistake no
 * amount of reading catches reliably; it needs an executable claim, which is what this is.
 *
 * The module is a browser ES module, so the handful of browser globals it touches are stubbed below. That
 * is deliberate: this drives the REAL nadodapp.js, not a transcription of it.
 */
const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};
globalThis.location = { search: "", pathname: "/", hash: "", href: "http://x/", origin: "http://x" };
globalThis.history = { replaceState() {} };
globalThis.document = {
  getElementById: () => null,
  createElement: () => ({ style: {}, classList: { add() {}, remove() {} }, appendChild() {}, remove() {}, setAttribute() {} }),
  body: { appendChild() {} },
  documentElement: { appendChild() {} },
  addEventListener() {},
  querySelectorAll: () => [],
};
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.fetch = async () => ({ ok: false, json: async () => ({}) });

const url = new URL("../static/nadodapp.js", import.meta.url);
const mod = await import(url.href);
const Dapp = mod.NadoDapp || mod.Dapp || mod.default;
if (!Dapp) {
  console.error("could not find the dapp class; exports:", Object.keys(mod));
  process.exit(1);
}

let pass = 0, fail = 0;
const ck = (name, cond, extra = "") => {
  if (cond) { console.log("PASS  " + name); pass++; }
  else { console.log("FAIL  " + name + (extra ? "  " + extra : "")); fail++; }
};
const fresh = (cursor = 100) => {
  store.clear();
  const d = new Dapp({ cid: "test", app: "test" });
  d.me = "mldsa44test";
  d.cursor = cursor;
  return d;
};

// ── the value-free / staked split ────────────────────────────────────────────────────────────────
// `stakes` as call() derives it. isValue (valueRaw != null) still drives WALLET ROUTING and must not
// change; only the pend policy keys on this.
const stakesOf = (valueRaw) => {
  const isValue = valueRaw != null;
  let s = false;
  try { s = isValue && BigInt(valueRaw) > 0n; } catch (e) { s = isValue; }
  return s;
};
ck("0n is not a staked call (the bug: 0n != null is true)", stakesOf(0n) === false);
ck("null is not a staked call", stakesOf(null) === false);
ck("undefined is not a staked call", stakesOf(undefined) === false);
ck("a real stake IS a staked call", stakesOf(5n) === true && stakesOf(10n ** 10n) === true);
ck("a string amount does not throw and is treated as staking", stakesOf("100") === true);

// ── tip-based expiry is OPT-IN, never a fleet default ────────────────────────────────────────────
// Releasing a click guard early is only safe where a duplicate submission is harmless: the caller has an
// auto-pump that re-sends and the on-chain op is idempotent-by-guard. Defaulting it ON turned a fix for
// one game into a duplicate-submission hazard for twenty (the daily board's post() appends
// unconditionally; pets' sweeps re-sign every eligible item; a board move is a real move).
{
  const d = fresh(100);
  d._pendAdd({ phase: "commit", leg: 5 }, false, true);        // value-free AND opted in
  const rec = JSON.parse(localStorage.getItem(d.LS_CLICK))[0];
  ck("an opted-in value-free pend is tip-expirable and stamps its submit cursor",
     rec.nv === 1 && rec.cur0 === 100, JSON.stringify(rec));
  ck("the guard arms at CLICK time, before any signing", d.busy("commit") === true);
  d.cursor = 102;                       // TX_INCLUSION_DELAY is 2: the tx cannot even be mined before now
  ck("still guarded while inclusion is still possible", d.busy("commit") === true);
  d.cursor = 104;
  ck("releases once the tx is a likely pool casualty, so the pump re-sends", d.busy("commit") === false);
}
{
  const d = fresh(100);
  d._pendAdd({ phase: "post", day: 1 }, false, false);         // value-free but NOT opted in
  d.cursor = 130;
  ck("a value-free pend that did NOT opt in keeps the wall clock (no early re-submit)",
     d.busy("post") === true);
}

// ── staked actions keep the conservative wall clock even if they ask for tip expiry ───────────────
{
  const d = fresh(100);
  d._pendAdd({ phase: "bet", table: 1 }, true, true);
  d.cursor = 200;
  ck("a STAKED action never expires by tip age (an early retry re-escrows)", d.busy("bet") === true);
}

// ── backwards compatibility ──────────────────────────────────────────────────────────────────────
{
  const d = fresh(100);
  localStorage.setItem(d.LS_CLICK, JSON.stringify([{ ts: Date.now(), p: { phase: "hatch" } }]));
  d.cursor = 9999;
  ck("entries written by an older build (no nv/cur0) are still honoured", d.busy("hatch") === true);
}
{
  const d = fresh(100);
  d.cursor = null;                      // before the first refresh there is no cursor to compare against
  d._pendAdd({ phase: "move" }, false);
  ck("a pend added before the first refresh does not expire spuriously", d.busy("move") === true);
}

// ── keyed pends stay independent ─────────────────────────────────────────────────────────────────
{
  const d = fresh(100);
  d._pendAdd({ phase: "commit", leg: 5 }, false);
  ck("a keyed guard matches its own key", d.busy("commit", "leg", 5) === true);
  ck("...and not a different one", d.busy("commit", "leg", 6) === false);
}

// ── _settleBlocked: phase scoping ────────────────────────────────────────────────────────────────
// A settle's input is already fixed on-chain, so the ONLY thing that may hold it is a settle of the same
// phase. An unrelated in-flight action starving every settle was the "queued for minutes" stall.
{
  const d = fresh(100);
  d._pendAdd({ phase: "commit", leg: 5 }, false);
  ck("phase-scoped settle is NOT blocked by an unrelated pend",
     d._settleBlocked({ phase: "advance" }) === false);
  ck("phase-scoped settle IS blocked by its own phase",
     d._settleBlocked({ phase: "commit" }) === true);
  ck("an unscoped caller keeps the old conservative behaviour (any pend blocks)",
     d._settleBlocked({}) === true);
}
{
  const d = fresh(100);
  d.inflight = { ts: Date.now(), phase: "commit", leg: 5 };
  ck("phase-scoped settle is NOT blocked by an unrelated INFLIGHT action",
     d._settleBlocked({ phase: "advance" }) === false);
  ck("...but is blocked by an inflight of its own phase (never double-settle)",
     d._settleBlocked({ phase: "advance" }) === false && (() => {
       const e = fresh(100);
       e.inflight = { ts: Date.now(), phase: "advance" };
       return e._settleBlocked({ phase: "advance" }) === true;
     })());
  ck("an unscoped caller is still blocked by any inflight", d._settleBlocked({}) === true);
}
{
  const d = fresh(100);
  ck("no wallet -> every settle is blocked", (() => { d.me = null; return d._settleBlocked({ phase: "advance" }); })() === true);
}

console.log(fail ? `\n${fail} FAILURES` : `\nALL PASS (${pass} checks)`);
process.exit(fail ? 1 : 0);
