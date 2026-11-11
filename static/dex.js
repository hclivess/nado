// dex.js — NADO DEX: a constant-product AMM (x·y=k) for NADO ↔ asset pairs on the execution layer.
// Built on the shared dApp SDK (nadodapp.js): the wallet round-trip, the confirming→confirmed lifecycle,
// balances and i18n are the SDK's, not this page's.
//
// WHAT THE CONTRACT IMPOSES ON THIS UI (execnode/games/dex.py):
//  * A call carries exactly ONE asset, so adding liquidity is TWO transactions into a POSITION you own —
//    fundn (NADO side) then fundt (token side) — and join() mints the shares. The UI walks that instead of
//    pretending it is one click, and refund() takes a half-finished deposit back at any time.
//  * Reserves are held in UNITs of 1e8 raw (0.01 NADO). Everything user-facing is NADO; the conversion is
//    in ONE place here (toUnits/fromUnits) so no other line has to remember the scale.
//  * The quote recomputes out = RT·dxf/(RN+dxf), dxf = dx·9970/10000, EXACTLY as the contract does, in
//    BigInt. A float quote would drift from the chain and mis-set minOut, turning a good swap into a revert.
import { htlcScript, p2wshAddress } from "./btcleg.js";
import { blake2s, personOf, bytesWord, hashWords } from "./blake2s.js";
import { claimTx, refundTx, addressToScript, genKeypair } from "./btcsign.js";
import { htlcAbi, htlcErc20Abi, erc20Abi, erc20Meta, toUnitsDec, fromUnitsDec, ethKeypair } from "./ethsign.js";
import { NadoDapp, rawToNado, nadoToRaw, _m, $, gate, wireWallet, financeLabels, stickyInputs, alertBar, loadQR, isAddress,
         orderCards, disp, share, installModes, algHashn, base, esc, randId, enhanceSelect, refreshPickers,
         renderWallet,
         uiConfirm, uiPrompt,
         blocksToTime } from "./nadodapp.js";

const CID = "08b256c6278ef1f6eed766c08095b460";
const dapp = new NadoDapp({ cid: CID, app: "Dex" });

const UNIT = 100000000n;              // 1e8 raw = 0.01 NADO — must match dex.UNIT
const FEE_NUM = 9970n, FEE_DEN = 10000n;
const ID_MAX = 4294967296;            // 2^32 — ids are slot keys (see the contract's slot model)

const LS_POS = "nado_dex_pos";
function posFor(poolId) {                            // your LP slot for this pool — created once, invisibly
  let m = {}; try { m = JSON.parse(localStorage.getItem(LS_POS) || "{}"); } catch (e) {}
  if (!m[poolId]) { m[poolId] = randId(); try { localStorage.setItem(LS_POS, JSON.stringify(m)); } catch (e) {} }
  return m[poolId];
}
const toUnits = (nado) => { try { return BigInt(nadoToRaw(nado)) / UNIT; } catch (e) { return 0n; } };
const fromUnits = (u) => rawToNado((BigInt(u) * UNIT).toString());
// A pool counts a token in the same UNIT-sized steps as NADO, but the token's own decimals decide what a
// raw unit MEANS — a 0-decimal token's pool unit is 10^10 whole tokens. These two are the only place that
// scale lives; NADO keeps toUnits/fromUnits.
const tokDec = (assetId) => { const m = tokMeta(assetId); return m ? Number(m.dec) || 0 : 10; };
function tokToUnits(str, assetId) {                    // "12.5" of a d-decimal token -> pool units (floored)
  const [i, f = ""] = String(str || "").trim().replace(",", ".").split(".");
  if (!/^\d*$/.test(i) || !/^\d*$/.test(f)) return 0n;
  const d = tokDec(assetId);
  const raw = BigInt((i || "0") + (f + "0".repeat(d)).slice(0, d));
  return raw / UNIT;
}
function tokFromUnits(u, assetId) {                    // pool units -> a decimal string in the token's own decimals
  const d = tokDec(assetId), raw = (BigInt(u) * UNIT).toString().padStart(d + 1, "0");
  const ip = raw.slice(0, raw.length - d), fp = d ? raw.slice(raw.length - d).replace(/0+$/, "") : "";
  return fp ? ip + "." + fp : ip;
}

let lastSto = null;
let assetReg = {};
const _pickerApi = {};             // id -> the picker wrapping that <select>, so labels follow dynamic options                                   // key: String(Number(id)) -> {sym, name, dec, id}
const akey = (id) => String(Number(id));
const tokMeta = (id) => assetReg[akey(id)] || null;
const tokSym = (id) => (tokMeta(id) || {}).sym || "token";
const tokName = (id) => { const m = tokMeta(id); return m ? (m.name || m.sym) : LT("unknownTok", "unknown token"); };
async function refreshAssets() {
  try {
    // TWO requests on purpose: ?holder= filters the registry down to assets you already hold (the node
    // skips zero balances), so asking with it was hiding every token from the pickers. The unfiltered
    // registry is what a trader needs to SEE; the holder pass only adds what you own.
    const [reg, mine] = await Promise.all([
      (await fetch(base() + "/exec/assets?ns=" + dapp.ns, { cache: "no-store" })).json(),
      dapp.me ? (await fetch(base() + "/exec/assets?ns=" + dapp.ns + "&holder=" + encodeURIComponent(dapp.me),
                             { cache: "no-store" })).json() : Promise.resolve({ assets: [] }),
    ]);
    const map = {};
    for (const a of (reg.assets || [])) map[akey(a.id)] = { sym: a.sym, name: a.name, dec: Number(a.dec) || 0,
      id: String(a.id), bal: null, supply: String(a.supply || "0"), holders: Number(a.holders) || 0 };
    for (const a of ((mine && mine.assets) || []))
      if (map[akey(a.id)]) map[akey(a.id)].bal = a.balance != null ? String(a.balance) : null;
    if (Object.keys(map).length || !Object.keys(assetReg).length) assetReg = map;
  } catch (e) { /* keep the last good registry */ }
}
let sel = null;                       // selected pool id
let render = () => {};

// ---- reads (dex storage schema: ast/rn/rt/sup keyed by pool id) -------------------------------------
const poolIds = (sto) => Object.keys(_m(sto, "ast") || {}).filter((id) => !curveRunning(sto, id));   // curves: Launch tab
const poolOf = (sto, id) => ({
  id: Number(id),
  asset: String((_m(sto, "ast") || {})[id] || ""),
  rn: BigInt((_m(sto, "rn") || {})[id] || 0),
  rt: BigInt((_m(sto, "rt") || {})[id] || 0),
  sup: BigInt((_m(sto, "sup") || {})[id] || 0),
  kind: Number((_m(sto, "kind") || {})[id] || 0),       // 0 pool · 1 a launch's curve · 2 a graduated launch
});
// LIVE: reserves on both sides and either LP shares or a graduated launch's locked liquidity (no shares by design —
// doc/launchpad.md: nobody can ever withdraw it). A curve still on its bonding curve trades in the Launch tab.
const livePool = (p) => p.rn > 0n && p.rt > 0n && (p.sup > 0n || p.kind === 2);
const curveRunning = (sto, id) => Number((_m(sto, "kind") || {})[id] || 0) === 1;

// The EXACT contract formula, in BigInt. Drift here shows up as a swap that reverts on minOut.
function quoteOut(inUnits, resIn, resOut) {
  if (inUnits <= 0n || resIn <= 0n || resOut <= 0n) return 0n;
  const dxf = (inUnits * FEE_NUM) / FEE_DEN;
  if (dxf <= 0n) return 0n;
  return (resOut * dxf) / (resIn + dxf);
}

function execUnits() {                                 // your spendable NADO on the exchange, in pool units
  try { return dapp.me ? BigInt(dapp.exec || 0n) / UNIT : null; } catch (e) { return null; }
}
function tokenUnits(assetId) {                        // your balance of the pool's token, in pool units
  const m = tokMeta(assetId);
  if (!dapp.me || !m || m.bal == null) return null;
  try { return BigInt(m.bal) / UNIT; } catch (e) { return null; }
}
// Price = tokens per NADO in the token's OWN decimals. The pool counts both sides in UNIT-sized steps, so
// the unit ratio rt/rn must be scaled by 10^(10-dec) — a 0-decimal token's pool unit is 10^10 tokens.
const pScale = (assetId) => 10 ** (10 - tokDec(assetId));
const midPrice = (p) => (p.rn > 0n ? Number(p.rt) / Number(p.rn) * pScale(p.asset) : 0);   // display only, never minOut

// ---- rendering ---------------------------------------------------------------------------------------
function renderPools() {
  const box = $("pools");
  if (!box) return;
  const ids = lastSto ? poolIds(lastSto) : [];
  if (!lastSto) { box.innerHTML = `<p class="small dim"><span class="spin"></span> ${esc(LT("mtLoading", "Loading markets…"))}</p>`; return; }
  if (!ids.length) {
    box.innerHTML = `<p class="small dim">${esc(LT("plNone", "No pools yet — open one below and seed it."))}</p>`;
    return;
  }
  box.innerHTML = ids.map((id) => {
    const p = poolOf(lastSto, id);
    const on = String(p.id) === String(sel) ? " sel" : "";
    const sym = tokSym(p.asset), live = livePool(p);
    const price = live ? nadoPerTok(p) : 0;            // NADO per coin, as the header says (it showed tokens per NADO)
    const st = live ? stats24(p.id, midPrice(p)) : null;
    const pc = live ? (ixChange(p.id, "h24", price, p.asset) ?? (st ? (1 / (1 + st.pct / 100) - 1) * 100 : null)) : null;
    const chg = pc != null ? (pc >= 0 ? "+" : "") + pc.toFixed(2) + "%" : "—";
    const cls = pc != null ? (Math.abs(pc) < 0.005 ? "" : pc > 0 ? "up" : "dn") : "";
    return `<div class="poolrow${on}" data-pool="${p.id}" style="cursor:pointer">
      <div class="pmain"><span class="tok" aria-hidden="true">${esc(tokIni(sym))}</span><div><b>${esc(sym)} / NADO</b><div class="small dim">${esc(live ? LT("plLiq", "{n} NADO liquidity", { n: fromUnits(p.rn) }) : LT("plEmpty", "empty — needs liquidity"))}</div></div></div>
      <div class="num">${live ? fmtShort(price) + " NADO" : "—"}</div>
      <div class="chgc ${cls}">${chg}</div>
    </div>`;
  }).join("");
  box.querySelectorAll(".poolrow").forEach((el) => {
    el.onclick = () => { sel = el.getAttribute("data-pool"); syncUrl(true); render(); };
  });
}

function renderLiq() {
  const el = $("liqPos");
  if (!el || !sel || !lastSto) return;
  const p = poolOf(lastSto, sel), sym = tokSym(p.asset);
  const t = $("addT"); if (t) t.placeholder = LT("lqSymPh", "{s} amount", { s: sym });
  el.innerHTML = LT("lqPos", "You are adding to the {s} / NADO pool. Position id {id} — it lives in this browser; note it down if you clear site data (your wallet key plus this id recovers the position).",
    { s: esc(sym), id: `<span class="mono">${esc(String(posFor(p.id)))}</span>` });
}
function renderSwap() {
  const card = $("swapCard");
  if (!card) return;
  // a graduated launch's pool takes no liquidity (its seeding is refused on chain): no add/remove card for it
  gate({ swapCard: !!sel, liqCard: !!sel && !(lastSto && poolOf(lastSto, sel).kind === 2) });
  if (!sel || !lastSto) return;
  const p = poolOf(lastSto, sel);
  const sym = tokSym(p.asset);
  const dsel = $("dir");
  if (dsel && dsel.dataset.sym !== sym) {              // keep the picker named after the ACTUAL token
    const keep = dsel.value || "n2t";
    dsel.innerHTML = `<option value="n2t">NADO → ${esc(sym)}</option><option value="t2n">${esc(sym)} → NADO</option>`;
    dsel.value = keep; dsel.dataset.sym = sym;
  }
  const dir = (dsel || {}).value || "n2t";     // n2t = sell NADO, t2n = sell token
  const inU = dir === "n2t" ? toUnits((($("swapAmt") || {}).value || "").trim()) : tokToUnits(($("swapAmt") || {}).value, p.asset);
  const out = dir === "n2t" ? quoteOut(inU, p.rn, p.rt) : quoteOut(inU, p.rt, p.rn);
  const fmtOut = (u) => dir === "n2t" ? tokFromUnits(u, p.asset) : fromUnits(u);
  // A comma decimal ("0,5") or any junk used to throw here — BEFORE the dataset below was written — so
  // the button kept signing the PREVIOUS amount while the box showed something else (audit).
  const slipRaw = String((($("slip") || {}).value) || "1").replace(",", ".");
  const slipNum = Number(slipRaw);
  const slipPct = Number.isFinite(slipNum) ? Math.min(50, Math.max(0, slipNum)) : 1;
  // minOut = the quote reduced by the tolerance, rounded DOWN (the contract compares UNITs as integers).
  const minOut = out * BigInt(Math.max(0, Math.round((100 - slipPct) * 100))) / 10000n;
  $("quote").textContent = out > 0n
    ? `${fmtOut(out)} ${dir === "n2t" ? sym : "NADO"}   (${LT("swAtWorst", "at worst {v}", { v: fmtOut(minOut) })})`
    : "—";
  card.dataset.worst = out > 0n ? fmtOut(minOut) : "";      // doSwap's warning quotes it (the label above is translated)
  const amtIn = $("swapAmt"); if (amtIn) amtIn.placeholder = LT("swAmtPh", "amount in {s}", { s: dir === "n2t" ? "NADO" : sym });
  card.dataset.minout = String(minOut);
  card.dataset.inunits = String(inU);
  // ticket chrome: which side is which, what you hold, the rate and what the trade itself moves the price by
  const paySym = dir === "n2t" ? "NADO" : sym, getSym = dir === "n2t" ? sym : "NADO";
  const setTxt = (id, v) => { const e = $(id); if (e) e.textContent = v; };
  setTxt("paySym", paySym); setTxt("getSym", getSym);
  const unitRate = inU > 0n && out > 0n ? Number(out) / Number(inU) : 0;
  const execRate = unitRate ? (dir === "n2t" ? unitRate * pScale(p.asset) : unitRate / pScale(p.asset)) : (dir === "n2t" ? midPrice(p) : (midPrice(p) ? 1 / midPrice(p) : 0));
  setTxt("sumRate", execRate ? `1 ${paySym} ≈ ${fmtPrice(execRate)} ${getSym}` : "—");
  const spot = dir === "n2t" ? midPrice(p) : (midPrice(p) ? 1 / midPrice(p) : 0);
  const impact = spot > 0 && execRate > 0 ? (1 - execRate / spot) * 100 : 0;
  const imp = $("sumImpact");
  card.dataset.impact = String(inU > 0n && out > 0n ? impact : 0);
  if (imp) { imp.textContent = inU > 0n && out > 0n ? impact.toFixed(2) + "%" + (impact >= 5 ? " (" + LT("swImpVHigh", "very high") + ")" : impact >= 1 ? " (" + LT("swImpHigh", "high") + ")" : "") : "—";
    imp.style.color = impact >= 5 ? "var(--danger)" : impact >= 1 ? "var(--warn)" : "var(--dim)"; }
  const qa = $("quoteAmt"); if (qa) qa.value = out > 0n ? fmtOut(out) : "";
  const payBalU = dir === "n2t" ? execUnits() : tokenUnits(p.asset);
  setTxt("payBal", payBalU === null ? "—" : LT("swBal", "Balance {v}", { v: (dir === "n2t" ? fromUnits(payBalU) : tokFromUnits(payBalU, p.asset)) + " " + paySym }));
  const getBalU = dir === "n2t" ? tokenUnits(p.asset) : execUnits();
  setTxt("getBal", getBalU === null ? "" : LT("swBal", "Balance {v}", { v: (dir === "n2t" ? tokFromUnits(getBalU, p.asset) : fromUnits(getBalU)) + " " + getSym }));
}

function fillAssetPicker(el, { withNado = true, keepValue = true, search = "" } = {}) {
  if (!el) return;
  const prev = keepValue ? el.value : "";
  const q = String(search || "").trim().toLowerCase();
  const toks = Object.values(assetReg).filter((a) => !q
    || (a.sym || "").toLowerCase().includes(q) || (a.name || "").toLowerCase().includes(q) || String(a.id).includes(q));
  toks.sort((a, b) => (b.bal ? 1 : 0) - (a.bal ? 1 : 0) || String(a.sym).localeCompare(String(b.sym)));
  const opts = (withNado && (!q || "nado".includes(q)) ? [`<option value="0">NADO</option>`] : [])
    .concat(toks.map((a) => `<option value="${a.id}">${esc(a.sym)} — ${esc(a.name || a.sym)}${a.bal ? " ·" : ""}</option>`));
  const sig = opts.join("");
  if (el.dataset.sig === sig) { return; }
  el.dataset.sig = sig;
  el.innerHTML = opts.length ? opts.join("") : `<option value="">${esc(q ? LT("pickNoMatch", "no token matches that") : LT("pickNone", "no tokens yet"))}</option>`;
  if (prev && [...el.options].some((o) => o.value === prev)) el.value = prev;
}
function doRender() {
  const wc = $("walletcard"); if (wc) wc.classList.toggle("signed", !!dapp.me);
  renderWallet(dapp);                                 // who you are + both balances; without this a
                                                      // completed sign-in never showed up on the page
  if (!dapp.me) { const w = $("who"); if (w) w.textContent = LT("notSignedIn", "not signed in"); }   // the SDK writes it in English
  fillAssetPicker($("newAsset"), { withNado: false });
  fillAssetPicker($("limGiveAsset"));
  fillTokenPicker();
  fillAssetPicker($("limWantAsset"));
  renderMarket();
  renderMarkets();
  renderPools();
  renderSwap();
  renderLiq();
  renderOtc();
  renderLimits();
  renderLaunch();
  refreshPickers();                                   // option lists change every poll — keep the labels honest
}

// ---- actions -------------------------------------------------------------------------------------------
function openPool() {
  const asset = (($("newAsset") || {}).value || ($("newAssetCustom") || {}).value || "").trim();
  if (!asset) return alertBar(LT("opNoTok", "No tokens exist yet to pair with NADO."));
  let aidB; try { aidB = BigInt(asset); } catch (e) { return alertBar(LT("opBadId", "That token id isn't valid.")); }
  if (aidB <= 0n) return alertBar(LT("opBadId", "That token id isn't valid."));
  if (lastSto) for (const id of poolIds(lastSto))                       // don't open a duplicate market
    if (akey(poolOf(lastSto, id).asset) === akey(asset)) { sel = String(id); render();
      return alertBar(LT("opExists", "A {s} / NADO pool already exists — selected it for you.", { s: tokSym(asset) })); }
  const pid = randId();
  dapp.call("open", [pid, aidB], null, LT("opCall", "Opening the {s} / NADO pool…", { s: tokSym(asset) }), { poolId: pid });
}

function fundNative() {
  if (!sel) return alertBar(LT("selPool", "Select a pool first."));
  const p = poolOf(lastSto, sel);
  const pos = posFor(p.id);
  const u = toUnits(($("addN").value || "").trim());
  if (u <= 0n) return alertBar(LT("lqNeedN", "Enter a NADO amount (at least 0.01)."));
  dapp.call("fundn", [pos, p.id, Number(u)], u * UNIT, LT("lqCallN", "Staging NADO…"), { posId: pos });
}

function fundToken() {
  if (!sel) return alertBar(LT("selPool", "Select a pool first."));
  const p = poolOf(lastSto, sel);
  const pos = posFor(p.id);
  const u = tokToUnits($("addT").value, p.asset);
  if (u <= 0n) return alertBar(LT("lqNeedT", "Enter a {s} amount (at least {m} {s} — the pool counts in that step).", { s: tokSym(p.asset), m: tokFromUnits(1n, p.asset) }));
  // opts.asset makes this an ASSET-denominated call (value = amount, asset = which token).
  dapp.call("fundt", [pos, p.id, Number(u)], u * UNIT, LT("lqCallT", "Depositing token…"),
            { posId: pos }, { asset: p.asset });
}

async function joinPool() {
  if (!sel) return alertBar(LT("selPool", "Select a pool first."));
  const p = poolOf(lastSto, sel), sym = tokSym(p.asset);
  const live = p.sup > 0n && p.rn > 0n;
  // value-free calls sign without a wallet dialog, so the page itself states what this does before it goes
  if (!await uiConfirm({ title: LT("lqAdd", "Add liquidity"),
    body: live ? LT("lqAddLive", "Both deposits go into the {s} / NADO pool at its current price and become pool shares. Anything that does not fit the ratio stays deposited and refundable.", { s: sym })
               : LT("lqAddFirst", "You are the first to supply {s} / NADO, so your two deposits SET its opening price. Check both amounts — a wrong ratio is free money for the first trader.", { s: sym }),
    rows: live ? [{ k: LT("lqPoolPrice", "Pool price"), v: `1 NADO = ${fmtPrice(midPrice(p))} ${sym}` }] : [],
    confirmText: LT("lqAdd", "Add liquidity") })) return;
  dapp.call("join", [posFor(p.id), p.id], null, LT("lqCallJoin", "Adding your liquidity…"), { posId: posFor(p.id) });
}

function refundPos() {
  if (!sel) return alertBar(LT("selPool", "Select a pool first."));
  const p = poolOf(lastSto, sel);
  dapp.call("refund", [posFor(p.id), p.id, BigInt(p.asset)], null, LT("lqCallRefund", "Returning your deposits…"), { posId: posFor(p.id) });
}

async function exitPos() {
  if (!sel) return alertBar(LT("selPool", "Select a pool first."));
  const p = poolOf(lastSto, sel), sym = tokSym(p.asset);
  const sh = Number(($("exitSh").value || "").trim());
  if (!(Number.isInteger(sh) && sh > 0)) return alertBar(LT("lqNeedSh", "Enter how many pool shares to withdraw (a whole number — the pool has {n} in total).", { n: p.sup }));
  if (BigInt(sh) > p.sup) return alertBar(LT("lqTooManySh", "The whole pool has only {n} {n|one:share|other:shares}.", { n: p.sup }));
  const outN = p.sup > 0n ? p.rn * BigInt(sh) / p.sup : 0n, outT = p.sup > 0n ? p.rt * BigInt(sh) / p.sup : 0n;
  if (!await uiConfirm({ title: LT("lqExitTitle", "Withdraw liquidity"),
    body: LT("lqExitBody", "Your shares are burned and both sides come back to your wallet. If you own fewer shares than this, the withdrawal is refused and nothing moves."),
    rows: [{ k: LT("lqShares", "Shares"), v: LT("lqShOf", "{a} of {b}", { a: sh, b: p.sup }) },
           { k: LT("youGet", "You receive"), v: `≈ ${fromUnits(outN)} NADO + ${tokFromUnits(outT, p.asset)} ${sym}` }],
    confirmText: LT("lqExitOk", "Withdraw") })) return;
  dapp.call("exit", [posFor(p.id), p.id, sh, BigInt(p.asset)], null, LT("lqCallExit", "Withdrawing your liquidity…"), { posId: posFor(p.id) });
}

async function doSwap() {
  if (!sel) return alertBar(LT("selPool", "Select a pool first."));
  const p = poolOf(lastSto, sel);
  const card = $("swapCard");
  const inU = BigInt(card.dataset.inunits || "0");
  const minOut = BigInt(card.dataset.minout || "0");
  if (inU <= 0n) return alertBar(LT("swNeedAmt", "Enter an amount to swap."));
  if (inU >= 1n << 31n) return alertBar(LT("swCap", "Trades are capped at {n} NADO-units per swap — split it into smaller swaps.", { n: fromUnits((1n << 31n) - 1n) }));
  if (minOut <= 0n) return alertBar(LT("swNoOut", "This pool cannot fill that amount — nothing would come out."));   // the contract requires out > 0
  const impact = Number(card.dataset.impact || 0);
  if (impact >= 5 && !await uiConfirm({ title: LT("swHighImp", "High price impact"), danger: true,
    body: LT("swHighImpBody", "This trade moves the pool's price by {p}%. You get at worst {w}. A smaller amount, or several swaps, gets a better rate.",
      { p: impact.toFixed(1), w: card.dataset.worst || "" }),
    confirmText: LT("swAnyway", "Swap anyway") })) return;
  // SWAPS ARE BATCHED (execnode/games/dex.py SWAPS): an order in this block's batch, which clears at one price; minOut
  // protects it against the whole batch. The coins are collected by swapClaims once the block has passed.
  const oid = randId(), side = ($("dir").value || "n2t") === "n2t" ? 1 : 2;
  const os = lpRead(LS_SW, []); os.push({ oid, pid: p.id, side, units: String(inU), at: dapp.cursor, asset: p.asset, me: dapp.me }); lpWrite(LS_SW, os);
  if (side === 1) dapp.call("obuy", [p.id, oid, Number(inU), Number(minOut)], inU * UNIT, LT("swPlacing", "Placing your swap in this block's batch…"), { poolId: p.id, id: oid });
  else dapp.call("osell", [p.id, oid, Number(inU), Number(minOut)], inU * UNIT, LT("swPlacing", "Placing your swap in this block's batch…"), { poolId: p.id, id: oid }, { asset: p.asset });
}

// ---- your swaps: each an order in its block's batch, read back from the chain (the contract's order() read: the block
// of an unclaimed order's batch, 0 if none) and collected once that block has passed. A claim carries no value, so a
// wallet with auto-sign collects silently. An order the chain never shows (refused for its limit, or never landed) is
// dropped after a while and says so.
const LS_SW = "nado_dex_swaps", SW_GIVEUP = 60;           // blocks without a trace before an order is called refused
const swState = {};                                       // oid -> { k: block of its batch (0 = none), at: when read }
async function swOrder(oid) {
  const c = swState[oid];
  if (c && Date.now() - c.at < 6000) return c.k;
  try {
    const r = await (await fetch(base() + "/exec/view?ns=" + dapp.ns + "&cid=" + CID + "&method=order&args=" + encodeURIComponent(JSON.stringify([oid])), { cache: "no-store" })).json();
    swState[oid] = { k: Number(r && r.result || 0), at: Date.now() };
  } catch (e) { return c ? c.k : null; }
  return swState[oid].k;
}
async function swapClaims() {
  if (!dapp.me || dapp.cursor == null) return;
  const os = lpRead(LS_SW, []).filter((o) => o.me === dapp.me);
  let changed = false;
  for (const o of os) {
    if (o.done) continue;
    const k = await swOrder(o.oid);
    if (k == null) continue;
    if (k > 0) { o.seen = true; if (dapp.cursor > k && !o.claimed) {
      o.claimed = true; changed = true;
      dapp.call("claim", [o.oid, BigInt(o.asset)], null, LT("swCollect", "Collecting your swap…"), { phase: "swclaim", id: o.oid });
      break;                                                // one signature at a time
    } }
    else if (o.claimed || o.seen) { o.done = true; changed = true; }               // claimed (or claimed elsewhere)
    else if (dapp.cursor - Number(o.at || 0) > SW_GIVEUP) { o.done = o.refused = true; changed = true; }
  }
  if (changed) { const all = lpRead(LS_SW, []).map((x) => os.find((y) => y.oid === x.oid) || x); lpWrite(LS_SW, all.filter((x) => !x.done || dapp.cursor - Number(x.at || 0) < 2000)); }
  renderSwPending();
}
function renderSwPending() {
  const box = $("swPending"); if (!box || !lastSto) return;
  const os = lpRead(LS_SW, []).filter((o) => o.me === dapp.me && (!o.done || o.refused) && dapp.cursor - Number(o.at || 0) < 400);
  box.innerHTML = os.length ? `<h3 class="mt">${esc(LT("swYours", "Your swaps"))}</h3>` + os.map((o) => {
    const sym = tokSym(o.asset), amt = o.side === 1 ? fromUnits(BigInt(o.units)) + " NADO" : tokFromUnits(BigInt(o.units), o.asset) + " " + sym;
    const k = (swState[o.oid] || {}).k;
    const st = o.refused ? LT("swRefused", "not filled — refused for its slippage limit, or never landed; nothing was taken")
      : o.claimed ? LT("swCollecting", "collecting…") : k > 0 ? LT("swInBatch", "in the batch of block {b} — collected once it has passed", { b: k })
      : LT("swLanding", "landing…");
    return `<div class="row small"><span>${esc((o.side === 1 ? LT("buy", "Buy") : LT("sell", "Sell")) + " · " + amt)} — ${esc(st)}</span>${k > 0 && !o.claimed && dapp.cursor > k ? `<button class="ghost" data-swc="${o.oid}">${esc(LT("claim", "Claim"))}</button>` : ""}</div>`;
  }).join("") : "";
  box.querySelectorAll("[data-swc]").forEach((b) => { b.onclick = () => { const o = lpRead(LS_SW, []).find((x) => String(x.oid) === b.dataset.swc);
    if (o) dapp.call("claim", [o.oid, BigInt(o.asset)], null, LT("swCollect", "Collecting your swap…"), { phase: "swclaim", id: o.oid }); }; });
}


// ================= LAUNCHPAD (the same contract, upgraded in place — doc/launchpad.md) ===================
// "create it now, i think by upgrading the existing dex contract and updating it in place, then adding functionalities
// to the gui" (operator, 2026-11-07). What the contract imposes on this UI:
//  * a launch is THREE approvals, in the order that strands nothing: issue the coin (asset_create, fixed supply), pay
//    the launch fee (prelaunch — it reserves the id), send the whole supply into the curve (launch). The wallet's
//    one-approval follow-up (opts.then) carries no value by design, and two of these carry value. Progress is read
//    FROM THE CHAIN (coin issued? id reserved? curve live?), never from callbacks, so a reload resumes it.
//  * trades are ORDERS into a batch: everyone in the opening window, then everyone in a block, gets one price; the
//    coins (or NADO) are claimed once the batch has closed. A quote is what the order alone would get — the honest
//    estimate; the batch price is the same for every order in it.
//  * no admin, no curation: the feed is ordered by on-chain facts only.
const LT = (k, en, v) => (typeof window !== "undefined" && window.t ? window.t("dex." + k, en, v || {})
  : String(en).replace(/\{(\w+)\}/g, (_, x) => (v && v[x] != null ? v[x] : "")));
const LP_CREATE_FEE = 1000n, LP_WINDOW = 10, LP_FEE = 100n, LP_MIN_SUPPLY = 1000n, LP_VN0 = 50000n;   // dex.py
const LP_VN_MIN = 100n, LP_VN_MAX = 1n << 26n;                                                       // dex.py VN_MIN/MAX
const LS_LP = "nado_dex_launch", LS_LPO = "nado_dex_orders";
const IPFS_GW = "https://nft.nadochain.com/ipfs/";          // the NFT host's gateway (content-addressed: ipfs://<cid>)
let lpSel = null, lpAssets = {};
const lpRead = (k, d) => { try { return JSON.parse(localStorage.getItem(k) || "null") || d; } catch (e) { return d; } };
const lpWrite = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };
const curveOf = (sto, id) => {
  const f = (k) => BigInt((_m(sto, k) || {})[id] || 0);
  return Object.assign(poolOf(sto, id), { cn: f("cn"), ct: f("ct"), vn: f("vn"), grad: f("grad"), lblk: Number(f("lblk")),
    open: f("open"), creator: String((_m(sto, "creator") || {})[id] || "") });
};
const curveIds = (sto) => Object.keys(_m(sto, "kind") || {}).filter((id) => Number((_m(sto, "kind") || {})[id]) > 0);
// the curve's spot price, NADO per coin unit (both sides counted in 1e8-raw units, as the contract does)
const lpSpot = (c) => (c.kind === 2 ? (c.rt > 0n ? Number(c.rn) / Number(c.rt) : 0) : (c.ct > 0n ? Number(c.vn + c.cn) / Number(c.ct) : 0));
// NADO per WHOLE coin: the unit ratio over the token's scale (a pool unit is 1e8 raw of each side — pScale, as midPrice)
const lpPrice = (c) => lpSpot(c) / pScale(c.asset);
const lpSupply = (c) => c.grad * 5n;                         // launch supply (GRAD = supply // 5) — display only
const lpSold = (c) => (c.kind === 2 ? 100 : Math.max(0, Math.min(100, Number(lpSupply(c) - c.ct) * 100 / Number(lpSupply(c) || 1n) * 1.25)));
const lpInWindow = (c) => dapp.cursor != null && c.kind === 1 && dapp.cursor - c.lblk < LP_WINDOW && dapp.cursor >= c.lblk;
// what an order alone would get — the exact curve formula of dex.py _clear, net of the 1 % fee
function lpQuote(c, side, units) {
  const net = units - units / LP_FEE;
  if (net <= 0n || c.ct <= 0n) return 0n;
  const x = c.vn + c.cn;
  return side === 1 ? (c.ct * net) / (x + net) : (x * net) / (c.ct + net);
}
async function lpAsset(aid) {                                // the coin's ledger row (issuer, supply, mintable, uri)
  const k = akey(aid);
  if (lpAssets[k] && Date.now() - lpAssets[k].at < 30000) return lpAssets[k].a;
  try { const a = await (await fetch(base() + "/exec/asset?ns=" + dapp.ns + "&id=" + encodeURIComponent(aid), { cache: "no-store" })).json();
        lpAssets[k] = { a, at: Date.now() }; return a; } catch (e) { return null; }
}
const lpImg = (uri) => {
  const u = String(uri || "");
  if (u.startsWith("ipfs://")) { const cid = u.slice(7).replace(/^ipfs\//, ""); return /^[A-Za-z0-9]+$/.test(cid) ? IPFS_GW + cid : ""; }
  return /^https:\/\/[^\s"'<>]+$/.test(u) ? u : "";
};

function renderLaunch() {
  if (curMode !== "launch") return;
  gate({ lpFeedCard: true, lpCreateCard: true, lpCoinCard: !!lpSel });
  const feed = $("lpFeed");
  if (!feed) return;
  if (!lastSto) { feed.innerHTML = `<p class="small dim"><span class="spin"></span> ${esc(LT("loading", "Loading launches…"))}</p>`; return; }
  // on-chain facts only: live curves by how far they have sold, then the graduated
  const cs = curveIds(lastSto).map((id) => curveOf(lastSto, id))
    .sort((a, b) => (a.kind - b.kind) || (lpSold(b) - lpSold(a)) || (b.id - a.id));
  feed.innerHTML = cs.length ? cs.map((c) => {
    const sym = tokSym(c.asset), st = c.kind === 2 ? LT("graduated", "Graduated · locked pool") : lpInWindow(c) ? LT("opening", "Opening batch") : LT("live", "On its curve");
    return `<div class="poolrow${String(c.id) === String(lpSel) ? " sel" : ""}" data-lp="${c.id}" style="cursor:pointer">
      <div class="pmain"><span class="tok" aria-hidden="true">${esc(tokIni(sym))}</span><div><b>${esc(sym)}</b> <span class="small dim">${esc(tokName(c.asset))}</span>
        <div class="small dim">${esc(st)} · ${esc(LT("raised", "{n} NADO raised", { n: fromUnits(c.kind === 2 ? c.rn : c.cn) }))}</div></div></div>
      <div class="num">${lpSpot(c) ? esc(fmtPrice(lpPrice(c))) + " NADO" : "—"}</div>
      <div class="chgc">${Math.round(lpSold(c))}%</div></div>`;
  }).join("") : `<p class="small dim">${esc(LT("none", "No launches yet — be the first."))}</p>`;
  feed.querySelectorAll("[data-lp]").forEach((el) => { el.onclick = () => { lpSel = el.getAttribute("data-lp"); render(); }; });
  renderLpCoin();
  renderLpCreate();
}

function renderLpCoin() {
  const box = $("lpCoin");
  if (!box || !lpSel || !lastSto) return;
  const c = curveOf(lastSto, lpSel), sym = tokSym(c.asset);
  const mine = lpRead(LS_LPO, []).filter((o) => String(o.pid) === String(c.id) && !o.done);
  const side = Number(($("lpSide") || {}).value || 1);
  const inputs = box.dataset.for === String(c.id);
  if (!inputs) {
    box.dataset.for = String(c.id);
    box.innerHTML = `<div id="lpHead"></div>
      <div class="bar mt" style="height:8px;border-radius:6px;background:var(--line);overflow:hidden"><i id="lpBar" style="display:block;height:100%;background:var(--accent);width:0"></i></div>
      <div class="small dim mt" id="lpProg"></div>
      <div id="lpFair" class="small mt"></div>
      <div class="rangebtns mt" id="lpTf" role="group" aria-label="${esc(LT("tf", "Timeframe"))}"></div>
      <div class="chartwrap"><svg id="lpChart" preserveAspectRatio="none"></svg><div class="tt" id="lpTt"></div><div class="chart-empty hidden" id="lpEmpty"></div></div>
      <div id="lpTrade" class="mt">
        <div class="row"><select id="lpSide" aria-label="${esc(LT("side", "Buy or sell"))}"><option value="1">${esc(LT("buy", "Buy"))}</option><option value="2">${esc(LT("sell", "Sell"))}</option></select>
          <input id="lpAmt" inputmode="decimal" autocomplete="off" aria-label="${esc(LT("amount", "Amount"))}">
          <button id="lpGo" class="btn">${esc(LT("place", "Place order"))}</button></div>
        <div class="small dim mt" id="lpQuote"></div></div>
      <h3 class="mt">${esc(LT("yourOrders", "Your orders"))}</h3><div id="lpMine"></div>
      <h3 class="mt">${esc(LT("tTitle", "Recent trades"))}</h3><div id="lpTrades"></div>`;
    $("lpSide").onchange = () => renderLpCoin(); $("lpAmt").oninput = () => renderLpCoin();
    $("lpGo").onclick = () => lpOrder();
  }
  const set = (id, h) => { const e = $(id); if (e) e.innerHTML = h; };
  set("lpHead", `<b>${esc(sym)}</b> · ${esc(tokName(c.asset))} · ${esc(LT("price", "1 {s} = {p} NADO", { s: sym, p: lpSpot(c) ? fmtPrice(lpPrice(c)) : "—" }))}`);
  const bar = $("lpBar"); if (bar) bar.style.width = Math.round(lpSold(c)) + "%";
  set("lpProg", c.kind === 2 ? esc(LT("gradNote", "Graduated: trades on its own pool, whose liquidity nobody can withdraw. Swap it in the Swap tab."))
    : esc(LT("prog", "{p}% of the way to graduation · {n} NADO raised{w}", { p: Math.round(lpSold(c)), n: fromUnits(c.cn),
      w: lpInWindow(c) ? " · " + LT("window", "opening batch: every order until block {b} gets one price", { b: c.lblk + LP_WINDOW }) : "" })));
  gate({ lpTrade: c.kind === 1 });
  // fairness, as the settled root states it: never mintable, and the creator's own holding
  lpAsset(c.asset).then((a) => {
    if (!a || String(lpSel) !== String(c.id)) return;
    const img = lpImg(a.uri);
    set("lpFair", `${img ? `<img src="${esc(img)}" alt="" style="max-width:96px;max-height:96px;border-radius:10px;float:right;margin-left:8px">` : ""}
      ${a.mintable === false ? "✓ " + esc(LT("fixed", "Fixed supply — it can never be minted again")) : "⚠ " + esc(LT("mintable", "This coin is MINTABLE — its supply can grow"))}<br>
      ${esc(LT("issuer", "Issued by {a}", { a: String(a.issuer || "").slice(0, 16) + "…" }))}`);
  });
  const amtEl = $("lpAmt");
  if (amtEl) amtEl.placeholder = side === 1 ? LT("inNado", "NADO to spend") : LT("inCoin", "{s} to sell", { s: sym });
  const u = side === 1 ? toUnits((amtEl && amtEl.value || "").trim()) : tokToUnits(amtEl && amtEl.value, c.asset);
  const q = c.kind === 1 && u > 0n ? lpQuote(c, side, u) : 0n;
  set("lpQuote", u > 0n ? esc(LT("quote", "Alone in its batch this order gets ≈ {q}. Everyone in the same batch gets the same price; 1 % fee ({f}).",
    { q: side === 1 ? tokFromUnits(q, c.asset) + " " + sym : fromUnits(q) + " NADO", f: side === 1 ? LT("feeSealed", "sealed NADO") : LT("feeBurned", "burned coins") })) : "");
  set("lpMine", mine.length ? mine.map((o) => `<div class="row small"><span>${esc(o.side === 1 ? LT("buy", "Buy") : LT("sell", "Sell"))} ·
      ${esc(o.side === 1 ? fromUnits(BigInt(o.units)) + " NADO" : tokFromUnits(BigInt(o.units), c.asset) + " " + sym)} · ${esc(LT("block", "block {b}", { b: o.at }))}</span>
      <button class="ghost" data-claim="${o.oid}">${esc(LT("claim", "Claim"))}</button></div>`).join("")
    : `<p class="small dim">${esc(LT("noOrders", "No open orders on this coin."))}</p>`);
  box.querySelectorAll("[data-claim]").forEach((b) => { b.onclick = () => lpClaim(Number(b.getAttribute("data-claim")), c); });
  // its chart and trades: a curve's fills land at the block its batch cleared, at that batch's one price
  renderPairBoard(c.id, c.asset, lpSpot(c) ? lpPrice(c) : 0, c.kind, { tf: "lpTf", svg: "lpChart", tt: "lpTt", empty: "lpEmpty", trades: "lpTrades" });
}

async function lpOrder() {
  if (!dapp.me) return alertBar(LT("signIn", "Sign in with your NADO wallet first."));
  const c = curveOf(lastSto, lpSel), side = Number($("lpSide").value || 1), sym = tokSym(c.asset);
  const u = side === 1 ? toUnits(($("lpAmt").value || "").trim()) : tokToUnits($("lpAmt").value, c.asset);
  if (u < LP_FEE) return alertBar(LT("tooSmall", "An order is at least {n}.", { n: side === 1 ? fromUnits(LP_FEE) + " NADO" : tokFromUnits(LP_FEE, c.asset) + " " + sym }));
  if (u >= 1n << 31n) return alertBar(LT("tooBig", "That order is too large for one batch — split it."));
  const oid = randId();
  const os = lpRead(LS_LPO, []); os.push({ oid, pid: c.id, side, units: String(u), at: dapp.cursor, asset: c.asset }); lpWrite(LS_LPO, os);
  if (side === 1) dapp.call("buy", [c.id, oid, Number(u)], u * UNIT, LT("callBuy", "buy {s} with {n} NADO", { s: sym, n: fromUnits(u) }), { phase: "lpbuy", id: oid });
  else dapp.call("sell", [c.id, oid, Number(u)], u * UNIT, LT("callSell", "sell {n} {s}", { s: sym, n: tokFromUnits(u, c.asset) }), { phase: "lpsell", id: oid }, { asset: c.asset });
}

function lpClaim(oid, c) {
  const os = lpRead(LS_LPO, []), o = os.find((x) => Number(x.oid) === oid);
  if (o && dapp.cursor != null && Number(o.at) === dapp.cursor) return alertBar(LT("notYet", "Its batch is still open — claim from the next block on."));
  if (o && c.kind === 1 && lpInWindow(c) && Number(o.at) >= c.lblk && Number(o.at) < c.lblk + LP_WINDOW)
    return alertBar(LT("notYetWin", "The opening batch is still open — claim after block {b}.", { b: c.lblk + LP_WINDOW }));
  dapp.call("claim", [oid, BigInt(c.asset)], null, LT("callClaim", "claim order {o}", { o: oid }), { phase: "lpclaim", id: oid });
  if (o) { o.done = true; lpWrite(LS_LPO, os); }
}

// ---- create: three steps, each read back from the chain ----
// the coin's id before it exists: execnode/state.asset_id = the VM hash over (the issuer's address digest, seed) — the
// same function as static/nft.js assetId, pinned against the Python by tests/test_an_nft_mints_with_its_royalty_in_one_approval.py
const LP_PERSON = personOf("NADOvmA1");
function lpAssetId(addr, seed) {
  const digest = bytesWord(blake2s(new TextEncoder().encode(JSON.stringify(["zkvmaddr", String(addr)])), LP_PERSON));
  return hashWords([digest, BigInt(seed)]);
}
let lpStepAt = 0;
async function renderLpCreate() {
  const st = $("lpSteps");
  if (!st) return;
  const job = lpRead(LS_LP, null);
  if (!job || !dapp.me || job.me !== dapp.me) { st.innerHTML = ""; gate({ lpForm: true }); return; }
  gate({ lpForm: false });
  if (Date.now() - lpStepAt < 2500 && st.dataset.done) return;
  lpStepAt = Date.now();
  const aid = String(lpAssetId(dapp.me, job.seed)), a = await lpAsset(aid);
  const reserved = lastSto && String((_m(lastSto, "creator") || {})[job.pid] || "") !== "", live = lastSto && curveRunning(lastSto, job.pid);
  const step = live ? 4 : reserved ? 3 : a && a.id ? 2 : 1;
  const row = (n, txt) => `<div class="small">${step > n ? "✓" : step === n ? "▶" : "·"} ${esc(txt)}</div>`;
  st.dataset.done = "1";
  st.innerHTML = row(1, LT("step1", "1. Issue {s}: {n} coins, fixed supply", { s: job.sym, n: job.units }))
    + row(2, LT("step2", "2. Pay the launch fee ({f} NADO, sealed) — reserves the launch"))
    + row(3, LT("step3", "3. Send the whole supply into its curve"))
    + (step === 4 ? `<p class="small mt">${esc(LT("launched", "Launched! It is in the list above."))}</p><button class="ghost" id="lpDone">${esc(LT("another", "Launch another"))}</button>`
                  : `<button class="btn mt" id="lpNext">${esc(LT("continue", "Continue: step {n}", { n: step }))}</button> <button class="ghost mt" id="lpForget">${esc(LT("forget", "Start over"))}</button>`);
  if (step === 4 && job.pid) lpSel = String(job.pid);
  const nx = $("lpNext"); if (nx) nx.onclick = () => lpStep(step, job, aid);
  const dn = $("lpDone"); if (dn) dn.onclick = () => { lpWrite(LS_LP, null); render(); };
  const fg = $("lpForget"); if (fg) fg.onclick = () => { lpWrite(LS_LP, null); render(); };
}
function lpStep(step, job, aid) {
  if (step === 1)
    dapp.signBlob({ op: "asset_create", seed: job.seed, name: job.name, sym: job.sym, dec: 8, supply: BigInt(job.units) * UNIT, mintable: false, ...(job.uri ? { uri: job.uri } : {}) },
      LT("callIssue", "issue {s} · {n} coins · fixed supply", { s: job.sym, n: job.units }), { phase: "lpissue", id: job.seed }, { confirm: true });
  else if (step === 2)
    dapp.call("prelaunch", [job.pid], LP_CREATE_FEE * UNIT, LT("callFee", "launch fee for {s} ({f} NADO, sealed)", { s: job.sym, f: fromUnits(LP_CREATE_FEE) }), { phase: "lpfee", id: job.pid });
  else if (step === 3)
    dapp.call("launch", [job.pid, Number(job.units), Number(job.vn || LP_VN0)], BigInt(job.units) * UNIT, LT("callLaunch", "send all {n} {s} into its curve", { n: job.units, s: job.sym }),
              { phase: "lplaunch", id: job.pid }, { asset: aid });
}
function lpCreate() {
  if (!dapp.me) return alertBar(LT("signIn", "Sign in with your NADO wallet first."));
  const name = ($("lpName").value || "").trim(), sym = ($("lpSym").value || "").trim().toUpperCase(), uri = ($("lpUri").value || "").trim();
  const units = BigInt(String(($("lpSupply").value || "").replace(/[\s_,]/g, "")) || "0");
  if (!name || name.length > 32) return alertBar(LT("needName", "Name the coin (at most 32 characters)."));
  if (!/^[A-Z0-9]{2,10}$/.test(sym)) return alertBar(LT("needSym", "A symbol is 2 to 10 letters or digits."));
  if (units < LP_MIN_SUPPLY || units >= 1n << 31n) return alertBar(LT("needSupply", "Supply is between {a} and {b} coins.", { a: LP_MIN_SUPPLY, b: (1n << 31n) - 1n }));
  if (uri && (!lpImg(uri) || uri.length > 128)) return alertBar(LT("needUri", "The image is an ipfs:// or https:// link (at most 128 characters)."));
  // the curve's scale: VN (virtual NADO, in units) = the graduation target / 4 — dex.py VN_MIN..VN_MAX
  const target = toUnits(String(($("lpTarget").value || "").trim())), vn = target / 4n;
  if (vn < LP_VN_MIN || vn >= LP_VN_MAX) return alertBar(LT("needTarget", "The graduation target is between {a} and {b} NADO.", { a: fromUnits(LP_VN_MIN * 4n), b: fromUnits((LP_VN_MAX - 1n) * 4n) }));
  lpWrite(LS_LP, { me: dapp.me, seed: randId(), pid: randId(), name, sym, units: String(units), uri, vn: String(vn) });
  render();
}

// ================= CROSS-CHAIN ORDER BOOK (otc contract — doc/dex-bridge.md §4) =========================
// Same page, DIFFERENT contract: the book is its own tiny escrow contract beside the AMM (no shared state,
// no shared upgrade surface), called through this dapp session via opts.cid. One venue, two contracts.
const OTC_CID = "83562ce0cf5ee023d98b366bfcbc6e57";
let otcState = "loading";                    // loading | ok | missing | down — never a spinner forever
const otcEmpty = (msg) => otcState === "ok" || otcSto ? `<p class="small dim">${msg}</p>`
  : otcState === "missing" ? `<p class="small warn">${esc(LT("otcMissing", "Order-book contract {c}… is not deployed on this chain — the page needs rewiring (execnode.games.redeploy).", { c: OTC_CID.slice(0, 10) }))}</p>`
  : otcState === "down" ? `<p class="small dim">${esc(LT("otcDown", "Order book unreachable right now — retrying."))}</p>`
  : `<p class="small dim"><span class="spin"></span> ${esc(LT("otcLoading", "Loading orders…"))}</p>`;
const OTC_ASK = 1, OTC_BID = 2, OTC_INTRA = 3;                       // kind: maker SELLS NADO / maker BUYS NADO
const OTC_ST = () => ({ 1: LT("stOpen", "open"), 2: LT("stFilled", "filled"), 3: LT("stSettled", "settled"), 4: LT("stRefunded", "refunded"), 5: LT("stCancelled", "cancelled") });
const LIMB_BITS = 52n, LIMBS = 5;                     // must match otc.preimage_limbs
const LS_OTC_SECRETS = "nado_otc_secrets";            // {orderId: 64-hex swap secret} — maker-side only
let otcSto = null;

// ---- the dual hashlock, client side (see the contract docstring) --------------------------------------
const otcLimbs = (sHex) => {                          // 32-byte secret -> five 52-bit limbs (JS-exact ints)
  const v = BigInt("0x" + sHex), m = (1n << LIMB_BITS) - 1n;
  return Array.from({ length: LIMBS }, (_, i) => Number((v >> (LIMB_BITS * BigInt(i))) & m));
};
const otcSecretFromLimbs = (ls) =>                    // s0..s4 back to the 64-hex secret (after a settle)
  ls.reduce((v, l, i) => v | (BigInt(l) << (LIMB_BITS * BigInt(i))), 0n).toString(16).padStart(64, "0");
const otcVmParts = (sHex) => {                        // the hashlock as the eight 32-bit pieces post() takes
  const L = otcLimbs(sHex).map(BigInt);
  // ONE 256-bit BLAKE2s digest of the five limbs, as eight pieces most significant first — otc.py vm_hashlock_parts
  // v2, so the contract recombines it into the one hashlock its settle() checks. The gen-28 form (four 64-bit alghash
  // digests offset by otc.py HDOM) went with BLAKE_EXEC_HEIGHT in G9; never reintroduce it, the contract checks v2.
  const h = algHashn(L);
  return Array.from({ length: 8 }, (_, i) => Number((h >> (32n * BigInt(7 - i))) & 0xFFFFFFFFn));
};
async function sha256Hex(hex) {                       // H_sha — the FOREIGN chain's native hashlock of the same s
  const b = new Uint8Array(hex.match(/../g).map((x) => parseInt(x, 16)));
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", b)), (x) => x.toString(16).padStart(2, "0")).join("");
}
const otcSecrets = () => { try { return JSON.parse(localStorage.getItem(LS_OTC_SECRETS) || "{}"); } catch (e) { return {}; } };
const otcRec = (o) => { const v = otcSecrets()[o]; return typeof v === "string" ? { s: v } : (v || {}); };
const otcSaveRec = (o, patch) => { const m = otcSecrets(); const cur = typeof m[o] === "string" ? { s: m[o] } : (m[o] || {});
  m[o] = Object.assign(cur, patch); localStorage.setItem(LS_OTC_SECRETS, JSON.stringify(m)); };
const otcForget = (o) => { const m = otcSecrets(); delete m[o]; try { localStorage.setItem(LS_OTC_SECRETS, JSON.stringify(m)); } catch (e) {} };
// a wallet extension's error, in the user's terms — what happened and what to do, never its internals
function walletErr(e) {
  const m = String((e && e.message) || e || ""), code = e && e.code;
  if (code === 4001 || /user (rejected|denied)|rejected the request/i.test(m)) return LT("weCancel", "You cancelled it in your wallet — nothing was sent.");
  if (/insufficient funds/i.test(m)) return LT("weFunds", "Not enough coin in that account to pay the network fee.");
  if (/chain|network/i.test(m) && /switch|unsupported|mismatch/i.test(m)) return LT("weNet", "Your wallet is on a different network — switch it and try again.");
  return LT("weRefused", "Your wallet refused the transaction: {m}", { m: m.slice(0, 120) });
}

// ---- the AUTOMATIC Bitcoin leg (no builder, no pubkey pasting — see btcsign.js) -----------------------
// NETWORKS: an order's `wch` names the exact NETWORK, not just the coin — so both sides build the same
// address and nobody sends mainnet coins to a testnet script. Adding a network is one row here.
const NETS = {
  btc:  { chain: "btc", coin: "BTC", label: "Bitcoin",          hrp: "bc",  explorer: "https://mempool.space" },
  btct: { chain: "btc", coin: "tBTC", label: "Bitcoin testnet", test: true, hrp: "tb",  explorer: "https://mempool.space/testnet" },
  eths: { chain: "eth", coin: "SepETH", label: "Ethereum Sepolia", test: true, evm: "0xaa36a7", rpc: "https://ethereum-sepolia-rpc.publicnode.com", htlc: "0xea946ca7df38607ba8af01e30486524c97363ec3", erc20: "0x16a2714026cf9ace31cf4fd9b20fcedc3721e71b" },
  // 2026-08-29: contracts record the revealed preimage (revealed(key)) — every address below verified against the build by eth_getCode
  eth:  { chain: "eth", coin: "ETH", label: "Ethereum mainnet",  evm: "0x1", rpc: "https://ethereum-rpc.publicnode.com",     htlc: "0x16a2714026cf9ace31cf4fd9b20fcedc3721e71b", erc20: "0x3a6ed3d17cc00feeb5dd53b69341d42b09ed9e14" },
  // Solana needs a deployed PROGRAM (unlike Bitcoin, whose HTLC is just a script). `program: ""` means
  // nothing is deployed on that cluster yet and the row says so rather than letting anyone fund a lock
  // into thin air. Filling one in is the only change a new cluster needs.
  sold: { chain: "sol", coin: "devSOL", label: "Solana devnet", test: true, rpc: "https://api.devnet.solana.com", cluster: "devnet", program: "", explorer: "https://explorer.solana.com" },
  sol:  { chain: "sol", coin: "SOL", label: "Solana mainnet", rpc: "https://api.mainnet-beta.solana.com", cluster: "", program: "", explorer: "https://explorer.solana.com" },
};
// An ERC-20 swap names its token inside the network field: wch = "<network>|<token address>". Everything
// below reads the network through netKeyOf, so a token order behaves exactly like a native one.
const netKeyOf = (od) => String(od.wch || "").split("|")[0];
// a token rides in the order's network field: "eths|0x…" (ERC-20) or "sold|<mint>" (SPL). EVM addresses
// are case-insensitive and stored lowercase; Solana mints are base58 and case-SENSITIVE — never lowercase them.
const isB58Addr = (a) => /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(a || "");
const tokNorm = (t) => (/^0x/i.test(t) ? t.toLowerCase() : t);
const tokAddrOf = (od) => { const t = String(od.wch || "").split("|")[1] || ""; return /^0x[0-9a-fA-F]{40}$/.test(t) || isB58Addr(t) ? t : ""; };
const mktKeyOf = (od) => netKeyOf(od) + (tokAddrOf(od) ? "|" + tokNorm(tokAddrOf(od)) : "");   // the MARKET an order trades in
const netSupportsTokens = (k) => ["eth", "sol"].includes((NETS[k] || {}).chain);   // ERC-20 / SPL; a missing contract is said at lock time
// Mainnet and testnets are different worlds and never share a list: one switch, remembered, in the URL.
const LS_ENV = "nado_dex_env";
let xEnv = (() => { try { return localStorage.getItem(LS_ENV) === "test" ? "test" : "main"; } catch (e) { return "main"; } })();
const envOf = (k) => ((NETS[k] || {}).test ? "test" : "main");
function setEnv(e) { xEnv = e === "test" ? "test" : "main"; try { localStorage.setItem(LS_ENV, xEnv); } catch (x) {} }
const netOf = (od) => NETS[netKeyOf(od)] || null;
const chainOf = (od) => (NETS[netKeyOf(od)] || {}).chain || netKeyOf(od);
const erc20Names = {};                               // "0xtoken" -> {symbol, decimals}, read from the chain
const coinOf = (od) => { const t = tokAddrOf(od);
  if (t) return (erc20Names[tokNorm(t)] || {}).symbol || (tokensFor(netKeyOf(od))[tokNorm(t)] || {}).sym || "TOKEN";
  return (NETS[netKeyOf(od)] || {}).coin || netKeyOf(od).toUpperCase(); };
const explorerOf = (od) => (NETS[netKeyOf(od)] || {}).explorer || "https://mempool.space";
// your address per NETWORK — typed once, reused forever (a swap always pays you on the same network)
const LS_FADDR = "nado_otc_faddr";
// KNOWN ERC-20s. Deliberately NOT a hardcoded address list: a wrong address here would send someone's
// money to the wrong contract. Tokens become known by being VERIFIED against the chain (symbol/decimals
// read from the contract itself) or by appearing on a live order, and are remembered per network.
const LS_TOKENS = "nado_otc_tokens";
// A short seed list so the picker is not empty on a fresh browser. Every entry was verified against the
// chain before being written here — the contract itself answered with this symbol and this many decimals
// (Sepolia, 2026-08-27). Nothing is taken on trust: the address is always shown next to the symbol,
// because any contract can claim any name and only the address is identity.
// KNOWN TOKENS, every address VERIFIED against its chain before it went in here (symbol() and decimals()
// read over JSON-RPC on 2026-08-28). A wrong address would send someone's money to the wrong contract.
const SEED_TOKENS = {
  eth: {
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": { sym: "USDC", dec: 6 },
    "0xdac17f958d2ee523a2206206994597c13d831ec7": { sym: "USDT", dec: 6 },
    "0x6b175474e89094c44da98b954eedeac495271d0f": { sym: "DAI", dec: 18 },
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": { sym: "WBTC", dec: 8 },
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": { sym: "WETH", dec: 18 },
    "0x514910771af9ca656af840dff83e8264ecf986ca": { sym: "LINK", dec: 18 },
    "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984": { sym: "UNI", dec: 18 },
    "0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9": { sym: "AAVE", dec: 18 },
    "0xae7ab96520de3a18e5e111b5eaab095312d7fe84": { sym: "stETH", dec: 18 },
    "0x6982508145454ce325ddbe47a25d4ec3d2311933": { sym: "PEPE", dec: 18 },
    "0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce": { sym: "SHIB", dec: 18 },
    "0x9f8f72aa9304c8b593d555f12ef6589cc3a579a2": { sym: "MKR", dec: 18 },
    "0xb50721bcf8d664c30412cfbc6cf7a15145234ad1": { sym: "ARB", dec: 18 },
    "0xfaba6f8e4a5e8ab82f62fe7c39859fa577269be3": { sym: "ONDO", dec: 18 },
  },
  eths: {
    "0x1c7d4b196cb0c7b01d743fbc6116a902379c7238": { sym: "USDC", dec: 6 },
    "0xfff9976782d46cc05630d1f6ebab18b2324d6b14": { sym: "WETH", dec: 18 },
    "0x779877a7b0d9e8603169ddbd7836e478b4624789": { sym: "LINK", dec: 18 },
    "0xff34b3d4aee8ddcd6f9afffb6fe49bd371b8a357": { sym: "DAI", dec: 18 },
    "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984": { sym: "UNI", dec: 18 },
  },
  sold: { "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU": { sym: "USDC", dec: 6 } },   // Circle devnet USDC — spl-token mint, 6 dp
};
const tokensAll = () => { try { return JSON.parse(localStorage.getItem(LS_TOKENS) || "{}"); } catch (e) { return {}; } };
const tokensFor = (net) => Object.assign({}, SEED_TOKENS[net] || {}, tokensAll()[net] || {});
function tokenRemember(net, addr, meta) {
  const all = tokensAll(); const m = all[net] || (all[net] = {});
  m[addr.toLowerCase()] = { sym: meta.symbol, dec: meta.decimals };
  try { localStorage.setItem(LS_TOKENS, JSON.stringify(all)); } catch (e) {}
}
const faddrAll = () => { try { return JSON.parse(localStorage.getItem(LS_FADDR) || "{}"); } catch (e) { return {}; } };
const faddrGet = (net) => faddrAll()[net] || "";
const faddrSet = (net, a) => { const m = faddrAll(); m[net] = a; try { localStorage.setItem(LS_FADDR, JSON.stringify(m)); } catch (e) {} };
const btcCache = {};                                   // orderId -> { script, addr } once computed
function btcParts(od) {
  // both parties' swap pubkeys ride the order itself (packed behind "|" in their address fields)
  if (chainOf(od) !== "btc") return null;
  const okp = (p) => /^0[23][0-9a-f]{64}$/.test(p || "");
  const mp = (od.wadr.split("|")[1] || "").toLowerCase();
  const tp = ((od.tadr || "").split("|").pop() || "").toLowerCase();
  if (!okp(mp) || !okp(tp)) return null;
  const sells = od.kind === OTC_ASK;                   // ASK: the maker RECEIVES the BTC -> claimant
  return { claimPub: sells ? mp : tp, refundPub: sells ? tp : mp, lock: Math.floor(Number(od.expf) || 0) };
}
function btcInfo(od) {
  if (od.st < 2) return null;                          // the address exists once BOTH keys are known (filled)
  if (btcCache[od.o]) return btcCache[od.o] === "pending" ? null : btcCache[od.o];
  const p = btcParts(od);
  if (!p || !/^[0-9a-f]{64}$/.test(od.hsha) || !(p.lock > 0)) return null;
  btcCache[od.o] = "pending";
  const script = htlcScript(od.hsha, p.claimPub, p.refundPub, p.lock);
  p2wshAddress(script, (netOf(od) || {}).hrp || "bc").then((addr) => { btcCache[od.o] = { script, addr }; render(); });
  return null;
}
async function btcVerifyInto(od, elId) {
  const el = document.getElementById(elId), b = btcInfo(od);
  if (!el || !b) return;
  el.textContent = LT("checking", "checking…");
  try {
    const a = await (await fetch(`${explorerOf(od)}/api/address/${b.addr}`, { cache: "no-store" })).json();
    const conf = Number(a.chain_stats.funded_txo_sum || 0), pend = Number(a.mempool_stats.funded_txo_sum || 0);
    const need = Math.round(Number(od.wamt) * 1e8);     // the AGREED amount — a dust lock must never read green
    el.innerHTML = conf >= need && need > 0
      ? `<span style="color:var(--accent2)">${esc(LT("btcConf", "CONFIRMED: {n} BTC locked", { n: conf / 1e8 }))}</span>${pend ? ` (${esc(LT("btcPlusUnconf", "+{n} unconfirmed", { n: pend / 1e8 }))})` : ""}`
      : conf > 0 ? `<span style="color:var(--danger)">${esc(LT("btcUnderNoReveal", "UNDERFUNDED: only {n} of the agreed {a} BTC — do NOT reveal your secret", { n: conf / 1e8, a: od.wamt }))}</span>`
      : pend > 0 ? esc(LT("btcUnconf", "UNCONFIRMED: {n} BTC in the mempool — wait for confirmations", { n: pend / 1e8 }))
      : esc(LT("btcNothing", "nothing sent to this address yet"));
  } catch (e) { el.textContent = LT("explDown", "explorer unreachable — try again"); }
}
async function btcSpendFlow(od, mode) {
  // ONE button: find the funded coin, ask where to send it, sign in-page, broadcast via the explorer.
  const b = btcInfo(od);
  if (!b) return alertBar(LT("btcDeriving", "Still deriving the Bitcoin address — try again in a second."));
  let utxos;
  try { utxos = await (await fetch(`${explorerOf(od)}/api/address/${b.addr}/utxo`, { cache: "no-store" })).json(); }
  catch (e) { return alertBar(LT("explDown2", "Explorer unreachable — try again.")); }
  const need = Math.round(Number(od.wamt) * 1e8);
  // Spend the coin that pays the AGREED amount, not merely the first one listed: claiming a dust output
  // publishes the swap secret while the real coin sits untouched (audit).
  const utxo = (utxos || []).filter((u) => u.value >= need).sort((a, c) => a.value - c.value)[0];
  if (!utxo) {
    const most = Math.max(0, ...(utxos || []).map((u) => u.value));
    return alertBar(mode === "claim"
      ? LT("btcNoCoin", "No coin here pays the agreed {a} {c} (largest: {m}). Claiming a smaller one would publish your secret for nothing.", { a: od.wamt, c: coinOf(od), m: most / 1e8 })
      : LT("btcNoReclaim", "Nothing here to reclaim (largest: {m}).", { m: most / 1e8 }));
  }
  if (!utxo.status.confirmed && !await uiConfirm({ title: LT("btcUnconfTitle", "That coin is still unconfirmed"),
    body: LT("btcUnconfBody", "It has not been mined yet, so this spend may not be accepted. Continue anyway?"), danger: true })) return;
  const rec = otcRec(od.o);
  if (!rec.k) return alertBar(LT("btcNoKey", "This browser doesn't hold the swap key for this order (use the device you posted/filled from, or scripts/otc_btc_leg.py)."));
  const payout = ((await uiPrompt({ title: LT("btcWhere", "Where should the coins go?"),
    body: LT("btcWhereBody", "Your {c} address — this spend pays it directly.", { c: coinOf(od) }), placeholder: LT("addrPh", "address") })) || "").trim();
  if (!payout) return;
  let outScriptHex;
  try { outScriptHex = await addressToScript(payout, (netOf(od) || {}).hrp || "bc"); } catch (e) { return alertBar(String(e.message || e)); }
  let feeRate = 10;
  try { feeRate = Math.max(1, (await (await fetch(`${explorerOf(od)}/api/v1/fees/recommended`)).json()).fastestFee); } catch (e) {}
  // The fee estimate comes from an explorer we do not control, so cap it: unbounded, a bad (or hostile)
  // estimate could burn most of the coin, and the only prior guard was "output > 0" (audit).
  const feeSat = Math.min(feeRate * 160, Math.floor(utxo.value * 0.02), 200000);
  if (utxo.value - feeSat < 546) return alertBar(LT("btcDust", "This coin is too small to spend after fees."));
  if (!await uiConfirm({ title: mode === "claim" ? LT("btcClaimT", "Claim these coins") : LT("btcReclaimT", "Reclaim these coins"),
    rows: [{ k: LT("youGet", "You receive"), v: (utxo.value - feeSat) / 1e8 + " " + coinOf(od) },
           { k: LT("rowTo", "To"), v: payout.slice(0, 22) + (payout.length > 22 ? "…" : "") },
           { k: LT("rowNetFee", "Network fee"), v: `${feeSat} sat (${(feeSat / utxo.value * 100).toFixed(2)}%)` }],
    confirmText: LT("send", "Send") })) return;
  const sHex = mode === "claim" ? await otcKnownSecret(od) : null;
  if (mode === "claim" && !sHex) return alertBar(LT("noSecretYet", "The swap secret isn't available yet."));
  // A claim that lands after the deadline still publishes the secret; Bitcoin's CLTV clock is median-time-
  // past, which lags wall time by up to ~1h, so keep a wider margin than the other chains.
  if (mode === "claim" && Math.floor(Date.now() / 1000) > Math.floor(Number(od.expf)) - 3600 - 900)
    return alertBar(LT("tooLate", "Too close to this lock's deadline — a claim that lands late would publish your secret and pay nothing."));
  try {
    const hex = mode === "claim"
      ? await claimTx({ scriptHex: b.script, secretHex: sHex, privHex: rec.k, fundTxid: utxo.txid,
                        vout: utxo.vout, amountSat: utxo.value, outScriptHex, feeSat })
      : await refundTx({ scriptHex: b.script, locktime: Math.floor(Number(od.expf)), privHex: rec.k,
                         fundTxid: utxo.txid, vout: utxo.vout, amountSat: utxo.value, outScriptHex, feeSat });
    const r = await fetch(`${explorerOf(od)}/api/tx`, { method: "POST", body: hex });
    const t = (await r.text()).trim();
    if (!r.ok) return alertBar(/non-final|non-BIP68/.test(t) ? LT("btcNotYet", "The Bitcoin deadline hasn't passed yet — try again after it.") : LT("btcRejected", "Bitcoin rejected it: {m}", { m: t.slice(0, 120) }));
    const tv = { t: t.slice(0, 24), a: payout.slice(0, 16) };
    alertBar(mode === "claim" ? LT("btcClaimed", "Claimed! Bitcoin txid: {t}… — coins on the way to {a}…", tv) : LT("btcReclaimed", "Reclaimed! Bitcoin txid: {t}… — coins on the way to {a}…", tv));
  } catch (e) { alertBar(String(e.message || e)); }
}
async function btcFoundSecret(od) {
  // the taker's shortcut: the maker's claim already published the secret ON BITCOIN — read it back.
  const b = btcInfo(od);
  if (!b) return null;
  try {
    for (const tx of await (await fetch(`${explorerOf(od)}/api/address/${b.addr}/txs`, { cache: "no-store" })).json())
      for (const vin of tx.vin || [])
        if (vin.prevout && vin.prevout.scriptpubkey_address === b.addr)
          for (const w of vin.witness || [])
            if (typeof w === "string" && w.length === 64 && (await sha256Hex(w)) === od.hsha) return w;
  } catch (e) {}
  return null;
}

// ---- reads --------------------------------------------------------------------------------------------
async function otcRefresh() {
  try {
    const r = await (await fetch(base() + "/exec/contract?ns=" + dapp.ns + "&cid=" + OTC_CID + "&provisional=1", { cache: "no-store" })).json();
    if (r && r.storage) { otcSto = r.storage; otcState = "ok"; }
    else if (r && r.error) otcState = "missing";       // the contract id this page carries is not on this chain
  } catch (e) { if (otcState !== "ok") otcState = "down"; /* keep the last good view */ }
}
function otcOrders() {
  if (!otcSto) return [];
  const g = (m, o) => (_m(otcSto, m) || {})[o];
  return Object.keys(_m(otcSto, "mk") || {}).map((o) => ({
    o: Number(o), kind: Number(g("kind", o) || 0), maker: String(g("maker", o) || ""),
    escRaw: BigInt(g("esc", o) || 0), namtRaw: BigInt(g("namt", o) || 0),
    wch: String(g("wch", o) || ""), wamt: String(g("wamt", o) || ""), wadr: String(g("wadr", o) || ""),
    hsha: String(g("hsha", o) || ""), expn: Number(g("expn", o) || 0), expf: String(g("expf", o) || ""),
    st: Number(g("st", o) || 0), taker: String(g("taker", o) || ""), tadr: String(g("tadr", o) || ""),
    fref: String(g("fref", o) || ""), hid: String(g("hid", o) || ""), fillh: Number(g("fillh", o) || 0), tb: BigInt(g("tb", o) || 0), limbs: [0, 1, 2, 3, 4].map((i) => g("s" + i, o) || 0),
    gast: String(g("gast", o) || "0"), wast: String(g("wast", o) || "0"), want: BigInt(g("want", o) || 0),
    bnty: BigInt(g("bnty", o) || 0), prem: BigInt(g("prem", o) || 0), pheld: BigInt(g("pheld", o) || 0),
  })).filter((x) => x.kind);
}
const otcLeft = (od) => od.expn - (dapp.cursor || 0);          // blocks until the refund window opens

// ---- the ETHEREUM leg (injected wallet: the page builds calldata, MetaMask signs and pays the gas) ----
// One shared ownerless HtlcEth per EVM chain (doc/dex-bridge.md §6.5). Filled once deployed; until then an
// ETH order's row shows the exact scripts/otc_eth_leg.mjs command instead of a dead button.

const ethProv = () => (typeof window !== "undefined" ? window.ethereum : null);
async function ethReq(method, params) { return ethProv().request({ method, params: params || [] }); }
async function ethConnect() {
  if (!ethProv()) throw new Error(LT("ethNoWallet", "No Ethereum wallet in this browser — install MetaMask, or open this page in a wallet browser."));
  const [addr] = await ethReq("eth_requestAccounts");
  const chain = await ethReq("eth_chainId");
  return { addr, chain };
}
function ethHtlcFor(od) { return (netOf(od) || {}).htlc || ""; }
function ethDeadline(od) { return Number(od.expf) || 0; }
// the maker's/taker's EVM address for an order rides in the same "|"-packed field the BTC pubkey uses
const ethAddrOf = (field) => { const p = (field || "").split("|").pop(); return /^0x[0-9a-fA-F]{40}$/.test(p) ? p : ""; };
// One in-page summary before any foreign-chain wallet popup (the BTC leg has its own with the fee):
// what this does, how much, on which network, until when. A wallet popup shows calldata, not meaning.
async function legConfirm(od, mode, netLabel) {
  const coin = coinOf(od), dl = new Date(ethDeadline(od) * 1000);
  const when = dl.toISOString().slice(0, 16).replace("T", " ") + "Z";
  const amt = `${od.wamt} ${coin}`;
  const spec = mode === "fund"
    ? { title: LT("legLockT", "Lock {a}", { a: amt }), body: LT("legLockB", "Only the counterparty can take it, and only with the swap secret. If they never do, you reclaim it after {w}.", { w: when }), confirmText: LT("lock", "Lock") }
    : mode === "claim"
    ? { title: LT("legClaimT", "Claim {a}", { a: amt }), body: LT("legClaimB", "Claiming publishes the swap secret on that chain — after this the counterparty can take the NADO side. This is what completes the swap."), confirmText: LT("claim", "Claim") }
    : { title: LT("legReclaimT", "Reclaim {a}", { a: amt }), body: LT("legReclaimB", "Returns your locked coins to the account that funded them. Only possible after the deadline."), confirmText: LT("reclaim", "Reclaim") };
  return uiConfirm(Object.assign(spec, { rows: [{ k: LT("amount", "Amount"), v: amt }, { k: LT("rowNetwork", "Network"), v: netLabel || coin }, { k: LT("rowDeadline", "Deadline"), v: when }] }));
}
async function ethLeg(od, mode) {
  // mode: fund (the ETH/token sender locks) · claim (reveal s, get paid) · refund (after the deadline)
  try {
    const { addr, chain } = await ethConnect();
    const net = netOf(od) || {}, token = tokAddrOf(od);
    const htlc = token ? (net.erc20 || "") : ethHtlcFor(od);
    if (!htlc) { alertBar(token ? LT("ethNoTokCtr", "No token swap contract is deployed on {n} yet — use the command shown on this row.", { n: net.label || LT("thatNet", "that network") })
                                : LT("ethNoCtr", "No swap contract is deployed on {n} yet — use the command shown on this row.", { n: net.label || LT("thatNet", "that network") })); return; }
    if (chain !== net.evm) { alertBar(LT("ethSwitch", "Switch your wallet to {n} — this order is on that network.", { n: net.label })); return; }
    const sells = od.kind === OTC_ASK;                  // ASK: taker sends the coin, maker claims
    const senderAddr = sells ? ethAddrOf(od.tadr) : ethAddrOf(od.wadr);   // who funded the lock (the refundee)
    const claimAddr = sells ? ethAddrOf(od.wadr) : ethAddrOf(od.tadr);    // who claims with the secret
    const dl = ethDeadline(od);
    if ((mode === "fund" || mode === "refund") && senderAddr && addr.toLowerCase() !== senderAddr.toLowerCase())
      return alertBar(LT("ethWrongAcct", "This swap's Ethereum side belongs to {a}… — switch your wallet to that account.", { a: senderAddr.slice(0, 10) }));
    const meta0 = token ? await ethTokenMeta(token) : { decimals: 18 };
    const amtWei = toUnitsDec(od.wamt, meta0.decimals);   // the AGREED amount is part of the lock key
    const key = token ? htlcErc20Abi.lockKey(token, od.hsha, claimAddr, senderAddr, dl, amtWei)
                      : htlcAbi.lockKey(od.hsha, claimAddr, senderAddr, dl, amtWei);
    let data, valueHex;
    if (mode === "fund") {
      if (token) {
        const amt = amtWei;
        if (amt <= 0n) return alertBar(LT("ethBadAmt", "That order's token amount is not a number."));
        // ERC-20 needs an allowance first — top it up only when it is short, so a second swap costs one tx.
        const cur = BigInt(await ethReq("eth_call", [{ to: token, data: erc20Abi.allowance(addr, htlc) }, "latest"]) || "0x0");
        if (cur < amt) {
          alertBar(LT("ethApproving", "Approving {s}… confirm the first transaction, then the lock.", { s: meta0.symbol || LT("theToken", "the token") }));
          await ethReq("eth_sendTransaction", [{ from: addr, to: token, data: erc20Abi.approve(htlc, amt) }]);
        }
        data = htlcErc20Abi.fund(token, claimAddr, addr, od.hsha, dl, amt);
      } else {
        data = htlcAbi.fund(claimAddr, addr, od.hsha, dl);
        valueHex = "0x" + amtWei.toString(16);
      }
    } else if (mode === "claim") {
      const sHex = await otcKnownSecret(od);
      if (!sHex) return alertBar(LT("noSecretYet", "The swap secret isn't available yet."));
      const nowS2 = Math.floor(Date.now() / 1000);
      if (nowS2 > dl - 900)                              // a claim that misses the deadline still leaks s
        return alertBar(LT("tooLate", "Too close to this lock's deadline — a claim that lands late would publish your secret and pay nothing."));
      // Read the lock back before revealing: an underfunded or mis-parameterised lock must NOT buy the secret.
      const raw = await ethReq("eth_call", [{ to: htlc, data: (token ? htlcErc20Abi : htlcAbi).locks(key) }, "latest"]);
      const words = (raw || "0x").replace(/^0x/, "").match(/.{64}/g) || [];
      const held = words.length ? BigInt("0x" + words[token ? 3 : 2]) : 0n;
      if (held < amtWei)
        return alertBar(LT("ethShort", "That lock holds less than the agreed amount — claiming it would publish your secret for nothing."));
      data = token ? htlcErc20Abi.claim(key, sHex) : htlcAbi.claim(key, sHex);
    } else data = token ? htlcErc20Abi.refund(key) : htlcAbi.refund(key);
    if (!await legConfirm(od, mode, net.label)) return;
    const txid = await ethReq("eth_sendTransaction", [{ from: addr, to: htlc, data, value: valueHex }]);
    alertBar(LT("legDone", "{w} — tx {t}…", { w: mode === "fund" ? LT("wLocked", "Locked") : mode === "claim" ? LT("wClaimed", "Claimed") : LT("wReclaimed", "Reclaimed"), t: String(txid).slice(0, 20) }));
  } catch (e) { alertBar(walletErr(e)); }
}
// a token's symbol/decimals, read once from the chain and cached (the row shows the symbol, the lock needs the decimals)
async function ethTokenMeta(token) {
  const k = token.toLowerCase();
  if (erc20Names[k]) return erc20Names[k];
  const url = ethProv() ? null : null;
  try {
    const dec = await ethReq("eth_call", [{ to: token, data: erc20Abi.decimals() }, "latest"]);
    const raw = await ethReq("eth_call", [{ to: token, data: erc20Abi.symbol() }, "latest"]);
    const b = raw.replace(/^0x/, "");
    let sym = "TOKEN";
    if (b.length === 64) sym = (decodeURIComponent(b.replace(/(..)/g, "%$1")) || "").replace(/\u0000+$/, "").trim() || "TOKEN";
    else if (b.length > 128) { const len = Number(BigInt("0x" + b.slice(64, 128)));
      sym = decodeURIComponent(b.slice(128, 128 + len * 2).replace(/(..)/g, "%$1")) || "TOKEN"; }
    erc20Names[k] = { symbol: sym, decimals: Number(BigInt(dec || "0x12")) };
  } catch (e) { erc20Names[k] = { symbol: "TOKEN", decimals: 18 }; }
  render();
  return erc20Names[k];
}
async function ethFoundSecret(od) {
  // the taker (ASK) reads s out of the maker's claim calldata on the EVM to settle the NADO side
  try {
    const htlc = ethHtlcFor(od);
    if (!htlc) return null;
    const logs = await ethReq("eth_getLogs", [{ address: htlc, fromBlock: "earliest", toBlock: "latest",
      topics: ["0x" + (await (async () => { const { keccak_256 } = await import("./vendor/noble-sha3.js");
        return Array.from(keccak_256(new TextEncoder().encode("Claimed(bytes32,bytes32)")), (x) => x.toString(16).padStart(2, "0")).join(""); })())] }]);
    for (const lg of logs) { const s = (lg.data || "").slice(-64); if (/^[0-9a-f]{64}$/.test(s) && (await sha256Hex(s)) === od.hsha) return s; }
  } catch (e) {}
  return null;
}
function ethCliHint(od) {
  const rec = otcRec(od.o);
  return `<div class="small dim mt">${esc(LT("ethCli", "No Ethereum wallet in this browser. Install MetaMask (or open this page in a wallet browser) to finish this step here."))}
    <details class="more"><summary>${esc(LT("cliAdv", "Advanced: finish it from a terminal"))}</summary><span class="mono" style="word-break:break-all">node scripts/otc_eth_leg.mjs claim --rpc ${od.wch === "eths" ? "https://ethereum-sepolia-rpc.publicnode.com" : "&lt;rpc&gt;"} --htlc ${esc((netOf(od) || {}).htlc || "&lt;deploy first&gt;")} --key &lt;your-eth-key&gt; --hash ${esc(od.hsha)} --claimant &lt;addr&gt; --refundee &lt;addr&gt; --deadline ${ethDeadline(od)} --secret &lt;s&gt;</span></details></div>`;
}

// ---- the Solana leg (scripts/solana-htlc, via static/solsign.js) -------------------------------------
// The escrow is a program-derived address whose SEEDS ARE THE SWAP'S TERMS, so both sides compute the same
// address from public data and an underfunded lock simply lands somewhere else — a claimant can never be
// tricked into publishing the secret for dust. Solana is an account model, so whoever submits pays the
// fee: the browser path uses the visitor's own wallet (as the Ethereum leg uses MetaMask) and falls back
// to the headless CLI on the row when no wallet is installed.
let SOL = null;
const solMod = async () => (SOL || (SOL = await import("./solsign.js")));
const solProgramOf = (od) => (netOf(od) || {}).program || "";
const solRpcOf = (od) => (netOf(od) || {}).rpc || "";
const solAddrOf = (field) => { const a = String(field || "").split("|")[0]; return isB58Addr(a) ? a : ""; };
function solHas() { try { const w = window; return !!(w.phantom?.solana || w.solflare || w.backpack?.solana || w.solana); } catch (e) { return false; } }
const solLamports = (amt) => { const [i, f = ""] = String(amt).split("."); return BigInt(i || 0) * 1000000000n + BigInt(((f + "000000000").slice(0, 9)) || 0); };

const solMintMeta = {};                               // mint -> {decimals}, read from the chain once
async function solMintDecimals(rpc, mint) {
  if (solMintMeta[mint]) return solMintMeta[mint].decimals;
  const S = await solMod();
  const v = (await S.solRpc(rpc, "getAccountInfo", [mint, { encoding: "jsonParsed" }])).value;
  const info = v && v.data && v.data.parsed && v.data.parsed.type === "mint" ? v.data.parsed.info : null;
  if (!info) throw new Error(LT("solNotSpl", "That mint address is not an SPL token."));
  solMintMeta[mint] = { decimals: Number(info.decimals) };
  return solMintMeta[mint].decimals;
}
const solTokUnits = (amt, dec) => { const [i, f = ""] = String(amt).trim().replace(",", ".").split("."); return BigInt((i || "0") + (f + "0".repeat(dec)).slice(0, dec)); };
async function solTerms(od) {
  const S = await solMod();
  const sells = od.kind === OTC_ASK;                     // ASK: the taker sends the coin, the maker claims
  const funder = solAddrOf(sells ? od.tadr : od.wadr);
  const claimant = solAddrOf(sells ? od.wadr : od.tadr);
  const deadline = Number(od.expf) || 0, rpc = solRpcOf(od);
  const mint = chainOf(od) === "sol" && isB58Addr(tokAddrOf(od)) ? tokAddrOf(od) : "";   // an SPL order names its mint
  const lamports = mint ? solTokUnits(od.wamt, await solMintDecimals(rpc, mint)) : solLamports(od.wamt);   // "lamports" = the lock's amount units
  const program = solProgramOf(od);
  if (!program) throw new Error(LT("solNoProg", "No swap program is deployed on {n} yet.", { n: (netOf(od) || {}).label }));
  if (!funder || !claimant) throw new Error(LT("solNoAddrs", "This swap's Solana addresses aren't both published yet."));
  if (!/^[0-9a-f]{64}$/.test(od.hsha || "")) throw new Error(LT("solNoHash", "This order has no usable hashlock."));
  if (!(deadline > 0) || lamports <= 0n) throw new Error(LT("solNoAmt", "This order's Solana amount or deadline is missing."));
  const { address } = mint ? await S.htlcPdaTok(program, od.hsha, claimant, funder, deadline, Number(lamports), mint)
                           : await S.htlcPda(program, od.hsha, claimant, funder, deadline, Number(lamports));
  const lockAta = mint ? await S.ataOf(address, mint) : "";
  return { S, sells, funder, claimant, deadline, lamports, program, address, rpc, mint, lockAta };
}
async function solLeg(od, mode) {
  try {
    const t = await solTerms(od);
    const { provider, address: me } = await t.S.solWalletConnect();
    const want = mode === "claim" ? t.claimant : t.funder;
    if (me !== want)
      return alertBar(LT("solWrongAcct", "This swap's Solana side belongs to {a}… — switch your wallet to that account.", { a: want.slice(0, 8) }));
    let ix;
    const ata = async (owner) => t.mint ? await t.S.ataOf(owner, t.mint) : "";
    if (mode === "fund") {
      const already = await t.S.solLockInfo(t.rpc, t.program, t.address);
      if (already) return alertBar(LT("solFunded", "That lock is already funded — nothing more to send."));
      ix = t.mint ? t.S.ixFundToken(t.program, me, t.address, od.hsha, t.claimant, t.deadline, Number(t.lamports), t.mint, await ata(me), t.lockAta)
                  : t.S.ixFund(t.program, me, t.address, od.hsha, t.claimant, t.deadline, Number(t.lamports));
    } else if (mode === "claim") {
      const sHex = await otcKnownSecret(od);
      if (!sHex) return alertBar(LT("noSecretYet", "The swap secret isn't available yet."));
      if (Math.floor(Date.now() / 1000) > t.deadline - 900)
        return alertBar(LT("tooLate", "Too close to this lock's deadline — a claim that lands late would publish your secret and pay nothing."));
      // Read the escrow back before revealing anything: the secret buys nothing from an empty account.
      const info = await t.S.solLockInfo(t.rpc, t.program, t.address);
      if (!info) return alertBar(LT("solNoLock", "No lock exists at this swap's address yet — nothing to claim."));
      if (info.owner !== t.program) return alertBar(LT("solNotOwned", "That account is not owned by the swap program — do not reveal your secret."));
      if (info.hashlock !== od.hsha || info.claimant !== t.claimant || info.amount < t.lamports || (info.mint || "") !== t.mint)
        return alertBar(LT("solMismatch", "The lock on chain does not match this order's terms — claiming it would publish your secret for nothing."));
      ix = t.mint ? t.S.ixClaimToken(t.program, me, t.address, t.claimant, sHex, t.mint, t.lockAta, await ata(t.claimant))
                  : t.S.ixClaim(t.program, me, t.address, t.claimant, sHex);
    } else {
      ix = t.mint ? t.S.ixRefundToken(t.program, me, t.address, t.funder, t.mint, t.lockAta, await ata(t.funder))
                  : t.S.ixRefund(t.program, me, t.address, t.funder);
    }
    if (!await legConfirm(od, mode, (netOf(od) || {}).label)) return;
    const sig = await t.S.solWalletSend(t.rpc, provider, me, [ix]);
    alertBar(LT("legDone", "{w} — tx {t}…", { w: mode === "fund" ? LT("wLocked", "Locked") : mode === "claim" ? LT("wClaimed", "Claimed") : LT("wReclaimed", "Reclaimed"), t: sig.slice(0, 20) }));
  } catch (e) { alertBar(walletErr(e)); }
}
async function solFoundSecret(od) {
  try { const t = await solTerms(od); return await t.S.solFoundSecret(t.rpc, t.address, od.hsha); }
  catch (e) { return null; }
}
function solCliHint(od) {
  const net = netOf(od) || {};
  return `<div class="small dim mt">${esc(LT("solCli", "No Solana wallet in this browser. Install Phantom (or open this page in a wallet browser) to finish this step here."))}
    <details class="more"><summary>${esc(LT("cliAdv", "Advanced: finish it from a terminal"))}</summary><span class="mono" style="word-break:break-all">node scripts/otc_sol_leg.mjs claim --rpc ${esc(net.rpc || "&lt;rpc&gt;")} --program ${esc(net.program || "&lt;not deployed&gt;")} --key &lt;your-key&gt; --hash ${esc(od.hsha)} --claimant &lt;addr&gt; --funder &lt;addr&gt; --deadline ${Number(od.expf) || 0} --amount ${tokAddrOf(od) ? "&lt;units&gt;" : String(solLamports(od.wamt))}${tokAddrOf(od) ? " --mint " + esc(tokAddrOf(od)) : ""} --secret &lt;s&gt;</span></details></div>`;
}

// ---- cross-chain markets: a BTC/NADO book IS a market, so it gets the same header, chart and stats ----
let xsel = "btc";                                    // selected cross-chain MARKET: a network key, or "net|token"
const XKEY = (key) => "x:" + key;
/** Every cross-chain market: each network's coin, plus every token known on it (seeded, verified, or seen on a live order). */
function xMarkets(env = xEnv) {
  const out = [];
  for (const k of Object.keys(NETS)) {
    const n = NETS[k];
    if (envOf(k) !== env) continue;
    out.push({ key: k, net: k, token: "", coin: n.coin, label: n.label, chain: n.chain });
    if (!netSupportsTokens(k)) continue;
    const toks = tokensFor(k);
    for (const od of otcOrders()) {
      const t = tokAddrOf(od);
      if (t && netKeyOf(od) === k && !toks[tokNorm(t)]) toks[tokNorm(t)] = { sym: (erc20Names[tokNorm(t)] || {}).symbol || "TOKEN", dec: 18 };
    }
    for (const a of Object.keys(toks)) out.push({ key: k + "|" + a, net: k, token: a, coin: toks[a].sym, label: LT("xTokOn", "{s} on {n}", { s: toks[a].sym, n: n.label }), chain: n.chain });
  }
  return out;
}
const xMarket = (key) => xMarkets("main").concat(xMarkets("test")).find((m) => m.key === key) || null;
/** Why a market cannot be traded yet, or "" — Bitcoin needs nothing deployed; EVM and Solana need their swap contract. */
function xMarketBlocker(m) {
  if (!m) return "";
  const n = NETS[m.net] || {};
  if (n.chain === "eth" && !(m.token ? n.erc20 : n.htlc)) return m.token ? LT("xBlkTok", "The token swap contract is not deployed on {n} yet — trading here opens when it is.", { n: n.label })
                                                                       : LT("xBlkEth", "The ETH swap contract is not deployed on {n} yet — trading here opens when it is.", { n: n.label });
  if (n.chain === "sol" && !n.program) return LT("xBlkSol", "The swap program is not deployed on {n} yet — trading here opens when it is.", { n: n.label });
  return "";
}
const otcPrice = (od) => {                           // NADO per 1 foreign coin
  const f = Number(od.wamt); const nado = Number(od.namtRaw) / 1e10;
  return f > 0 && nado > 0 ? nado / f : 0;
};
function bookOf(net) {
  const bids = [], asks = [];                        // bid = someone paying NADO for the coin (ASK_NADO)
  for (const od of otcOrders()) {
    if (mktKeyOf(od) !== net || od.st !== 1 || od.kind === OTC_INTRA || otcLeft(od) <= 0) continue;   // a token is its own market
    const px = otcPrice(od);
    if (!px) continue;
    (od.kind === OTC_ASK ? bids : asks).push({ px, size: Number(od.wamt), o: od.o, od });
  }
  bids.sort((a, b) => b.px - a.px); asks.sort((a, b) => a.px - b.px);
  const bb = bids[0] ? bids[0].px : 0, ba = asks[0] ? asks[0].px : 0;
  return { bids, asks, bb, ba, mid: bb && ba ? (bb + ba) / 2 : (bb || ba) };
}
function renderXMarket() {
  if (wantMarket) { const hit = xMarkets("main").concat(xMarkets("test")).find((m) => m.coin.toUpperCase() === wantMarket);
    if (hit) { setEnv(envOf(hit.net)); xsel = hit.key; wantMarket = null; } }
  boardFor(false);
  const seg = $("envSeg");
  if (seg) { seg.classList.remove("hidden"); seg.querySelectorAll("button").forEach((b) => { b.classList.toggle("on", b.dataset.env === xEnv); b.setAttribute("aria-selected", String(b.dataset.env === xEnv)); }); }
  const mkts = xMarkets(), keys = mkts.map((m) => m.key);
  const pick = $("mktPick");
  if (pick) {
    const opts = mkts.map((m) => `<option value="${esc(m.key)}">${esc(m.coin)} / NADO${xMarketBlocker(m) ? " · " + esc(LT("vSoon", "soon")) : ""} — ${esc(m.label)}</option>`).join("");
    if (pick.dataset.sig !== opts) { pick.dataset.sig = opts; pick.innerHTML = opts; }
    if (!keys.includes(xsel)) xsel = keys[0];
    pick.value = xsel;
  }
  if (!keys.includes(xsel)) xsel = keys[0];
  const m = xMarket(xsel) || mkts[0];
  // a market that cannot trade yet SHOWS it: "soon" in the picker and the pill, no post form, and a book
  // that points at where trading is live — nothing to read, nothing to click that will not work
  const blk = xMarketBlocker(m);
  const pc = $("otcPostCard"); if (pc) pc.classList.toggle("offmarket", !!blk);   // its own class: the mode switcher re-shows gated cards after every render
  const pb = $("btnOtcPost"); if (pb) { pb.title = blk; pb.disabled = !!blk || !!(($("otcFAddrHint") || {}).style || {}).color && $("otcFAddrHint").style.color === "var(--danger)"; if (!blk) { const ai = $("otcFAddr"); if (ai && ai.oninput) ai.oninput(); } }
  const netSel0 = $("otcNet"), tp0 = $("otcTokenPick");
  if (netSel0 && !netSel0.dataset.touched && [...netSel0.options].some((o) => o.value === m.net)) {
    if (netSel0.value !== m.net) { netSel0.value = m.net; netSel0.dispatchEvent(new Event("change", { bubbles: true })); }
    fillTokenPicker();                                 // the picker must already list the token before it can be selected
    if (tp0 && tp0.value !== m.token && [...tp0.options].some((o) => o.value === m.token)) {   // the form follows the market you are looking at
      tp0.value = m.token; tp0.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }
  const net = Object.assign({}, NETS[m.net] || {}, { coin: m.coin, label: m.label }), b = bookOf(xsel);
  $("mktPair").textContent = `${net.coin} / NADO`;
  $("mktPrice").textContent = b.mid ? fmtPrice(b.mid) : "—";
  const st24 = stats24(XKEY(xsel), b.mid);
  const chgEl = $("mktChg");
  if (st24 && b.mid) {
    chgEl.textContent = (st24.pct >= 0 ? "+" : "") + st24.pct.toFixed(2) + "%  24h";
    chgEl.className = "chg " + (Math.abs(st24.pct) < 0.005 ? "flat" : st24.pct > 0 ? "up" : "dn");
  } else { chgEl.textContent = blk ? LT("xSoon", "coming soon") : b.bids.length || b.asks.length ? LT("xOneSide", "one side quoted") : LT("xNoOrders", "no open orders"); chgEl.className = "chg flat"; }
  chgEl.title = blk;
  const mine = otcOrders().filter((x) => mktKeyOf(x) === xsel && dapp.me && (x.maker === dapp.me || x.taker === dapp.me)).length;
  $("mktStats").innerHTML = [
    [LT("stBestBid", "Best bid"), b.bb ? fmtPrice(b.bb) + " NADO" : "—"],
    [LT("stBestAsk", "Best ask"), b.ba ? fmtPrice(b.ba) + " NADO" : "—"],
    [LT("stSpread", "Spread"), b.bb && b.ba ? ((b.ba - b.bb) / b.ba * 100).toFixed(2) + "%" : "—"],
    [LT("st24Hi", "24h high"), st24 && b.mid ? fmtShort(st24.hi) : "—"],
    [LT("st24Lo", "24h low"), st24 && b.mid ? fmtShort(st24.lo) : "—"],
    [LT("st24Vol", "24h volume"), vol24(XKEY(xsel)) ? fmtShort(vol24(XKEY(xsel))) + " NADO" : "—"],
    [LT("st24Swaps", "24h swaps"), String(trades24(XKEY(xsel)))],
    [LT("stBuyOrders", "Buy orders"), String(b.bids.length)],
    [LT("stSellOrders", "Sell orders"), String(b.asks.length)],
    [LT("yourOrders", "Your orders"), String(mine)],
  ].map(([l, v]) => `<div class="stat"><div class="l">${esc(l)}</div><div class="v">${v}</div></div>`).join("");
  const mcX = $("marketCard"); if (mcX) mcX.classList.remove("nomarket");   // a cross-chain market always has a book to show
  const cap = $("depthCap"); if (cap) cap.textContent = LT("depthBook", "Live order book — how much is offered at each price:");
  // …and how far back the record goes: a range button that reaches behind it draws what there is, and says so here
  const since = seriesStart(XKEY(xsel));
  const mc = $("mktCap"); if (mc) mc.textContent = LT("capBook", "Prices come from open orders on this book. Nothing is back-filled — a gap means nothing was offered.")
    + (since ? " " + LT("capFrom", "The price record starts {ago}.", { ago: fmtAgo(since) }) : "");
  // WHAT YOU NEED, said up front — the other chain's side is signed by that chain's wallet, and a page that
  // only reveals this at the lock step has already let someone post an order they cannot finish here
  const rq = $("xReq");
  if (rq) {
    rq.classList.remove("hidden");
    const ch = net.chain, has = ch === "eth" ? !!ethProv() : ch === "sol" ? solHas() : true;
    rq.className = "small mt " + (has ? "dim" : "warn");
    const c = { c: esc(net.coin) };
    rq.innerHTML = ch === "eth"
      ? (has ? LT("reqEthOk", "Ethereum wallet connected — the {c} side is signed by it.", c)
             : LT("reqEthNo", "<b>An Ethereum wallet extension (MetaMask or similar) is required to trade {c} here.</b> None is detected in this browser. You can still post and take orders, but locking, claiming or reclaiming the {c} side must then be done from a terminal (shown on the swap row).", c))
      : ch === "sol"
      ? (has ? LT("reqSolOk", "Solana wallet detected — the {c} side is signed by it.", c)
             : LT("reqSolNo", "<b>A Solana wallet extension (Phantom or similar) is required to trade {c} here.</b> None is detected in this browser.", c))
      : LT("reqBtc", "No extra wallet needed: this page builds and signs the Bitcoin side itself and shows you the address to fund.");
  }
  renderChart(XKEY(xsel), "NADO", `1 ${net.coin} =`);
  renderBookDepth(b, net.coin, blk ? (xEnv === "main" ? LT("depthSoonMain", "trading opens when the swap contract is live — try Testnet") : LT("depthSoonTest", "trading opens when the swap program is live")) : "");
  syncUrl(false);
}
// the order book as cumulative depth — the classic book view, drawn from live open orders
function renderBookDepth(b, coin, emptyText = "") {
  const svg = $("mktDepth");
  if (!svg) return;
  if (!b.bids.length && !b.asks.length) {
    svg.innerHTML = `<text x="${DW / 2}" y="${DH / 2}" fill="var(--faint)" font-size="11" text-anchor="middle">${esc(emptyText || LT("depthNone", "no open orders — post one below"))}</text>`;
    svg.setAttribute("viewBox", `0 0 ${DW} ${DH}`); return;
  }
  const cum = (arr) => { let t = 0; return arr.map((x) => ({ px: x.px, t: (t += x.size) })); };
  const B = cum(b.bids), A = cum(b.asks);
  const pxs = B.concat(A).map((x) => x.px), maxT = Math.max(...B.concat(A).map((x) => x.t), 1e-12);
  const lo = Math.min(...pxs), hi = Math.max(...pxs);
  const mid = b.mid || (lo + hi) / 2;
  // one order, or several at one price, means hi === lo — without a floor the whole scale collapses to a
  // point and the chart renders empty, which reads as "no orders" when there certainly are some.
  const span = Math.max(hi - lo, mid * 0.05, 1e-9);
  const X = (px) => 8 + (px - (mid - span)) / (2 * span) * (DW - 16);
  const Y = (t) => 6 + (1 - t / maxT) * (DH - 20);
  // A depth chart is a STEP: the cumulative total rises at each price and HOLDS until the next one,
  // running outward from mid to the edge of the panel. Plotting only the data points meant a book with a
  // single order — whose price IS the mid — collapsed to a zero-width sliver and rendered blank, which
  // reads as "no orders" on a market that has one.
  const side = (arr, col, dir) => {
    if (!arr.length) return "";
    const edge = dir > 0 ? DW - 8 : 8;                 // bids run left of mid, asks run right
    const base = DH - 14;
    const pts = arr.map((x) => [X(x.px), Y(x.t)]);
    const last = pts[pts.length - 1];
    let line = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
    for (let i = 1; i < pts.length; i++) line += ` L${pts[i][0].toFixed(1)} ${pts[i - 1][1].toFixed(1)} L${pts[i][0].toFixed(1)} ${pts[i][1].toFixed(1)}`;
    line += ` L${edge.toFixed(1)} ${last[1].toFixed(1)}`;
    const area = `M${pts[0][0].toFixed(1)} ${base} L` + line.slice(1).replace(/^M/, "") + ` L${edge.toFixed(1)} ${base} Z`;
    return `<path d="${area}" fill="${col}" opacity="0.16"/>` +
           `<path d="${line}" fill="none" stroke="${col}" stroke-width="1.5" stroke-linejoin="round"/>`;
  };
  svg.setAttribute("viewBox", `0 0 ${DW} ${DH}`);
  svg.innerHTML = `<line x1="${X(mid).toFixed(1)}" y1="4" x2="${X(mid).toFixed(1)}" y2="${DH - 14}" stroke="var(--border)"/>` +
    side(B, "var(--accent2)", -1) + side(A, "var(--danger)", 1) +   // bids run LEFT of mid, asks RIGHT
    `<text x="${X(mid).toFixed(1)}" y="${DH - 2}" fill="var(--faint)" font-size="9" text-anchor="middle" font-family="ui-monospace,monospace">${fmtPrice(mid)}</text>` +
    `<text x="8" y="${DH - 2}" fill="var(--accent2)" font-size="9.5" font-family="ui-monospace,monospace">${esc(LT("depthBuying", "buying {c}", { c: coin }))} ←</text>` +
    `<text x="${DW - 8}" y="${DH - 2}" fill="var(--danger)" font-size="9.5" text-anchor="end" font-family="ui-monospace,monospace">→ ${esc(LT("depthSelling", "selling {c}", { c: coin }))}</text>`;
}

// ---- the NADO leg on L1 -------------------------------------------------------------------------------
// The site proxies the L1 API at its root, so the page can read the bound HTLC back: its terms (before
// anyone funds the other side) and, once claimed, the PREIMAGE — which is how a BID taker learns the
// secret the maker revealed by taking their NADO, whether or not the maker ever calls settle.
async function nadoHtlc(od) {
  if (!od.hid) return null;
  try { return (await (await fetch(base() + "/get_htlc?id=" + encodeURIComponent(od.hid), { cache: "no-store" })).json()).htlc || null; }
  catch (e) { return null; }
}
/** The swap secret from wherever it is known — checked against the order's hashlock before it is used. */
async function otcKnownSecret(od) {
  const cands = [otcRec(od.o).s];
  if (od.limbs.some((x) => Number(x) > 0)) cands.push(otcSecretFromLimbs(od.limbs));
  for (const c of cands) if (/^[0-9a-f]{64}$/.test(c || "") && (await sha256Hex(c)) === od.hsha) return c;
  const h = await nadoHtlc(od);
  if (h && h.status === "claimed" && /^[0-9a-f]{64}$/.test(h.preimage || "") && (await sha256Hex(h.preimage)) === od.hsha) return h.preimage;
  return null;
}
/** The FOREIGN lock as data: {state: none|funded|short|claimed|error, html} — read from the chain, never from the order. */
async function foreignLockState(od) {
  const ch = chainOf(od), net = netOf(od) || {};
  try {
    if (ch === "btc") {
      const b = btcInfo(od); if (!b) return { state: "none", html: "— " + esc(LT("flDeriving", "deriving the address")) };
      const need = Math.round(Number(od.wamt) * 1e8);
      const a = await (await fetch(`${explorerOf(od)}/api/address/${b.addr}`, { cache: "no-store" })).json();
      const conf = Number(a.chain_stats.funded_txo_sum || 0), spent = Number(a.chain_stats.spent_txo_sum || 0), pend = Number(a.mempool_stats.funded_txo_sum || 0);
      if (spent >= need && need > 0) return { state: "claimed", html: `<span style="color:var(--accent2)">${esc(LT("flSpent", "spent — claimed or reclaimed"))}</span>` };
      if (conf >= need && need > 0) return { state: "funded", html: `<span style="color:var(--accent2)">${esc(LT("btcConf", "CONFIRMED: {n} BTC locked", { n: conf / 1e8 }))}</span>` };
      if (conf > 0) return { state: "short", html: `<span style="color:var(--danger)">${esc(LT("btcUnder", "UNDERFUNDED: only {n} of the agreed {a} BTC", { n: conf / 1e8, a: od.wamt }))}</span>` };
      return { state: "none", html: pend > 0 ? esc(LT("btcUnconf", "UNCONFIRMED: {n} BTC in the mempool — wait for confirmations", { n: pend / 1e8 })) : "— " + esc(LT("flNothingYet", "nothing sent yet")) };
    }
    if (ch === "sol") {
      const t = await solTerms(od);
      const info = await t.S.solLockInfo(t.rpc, t.program, t.address);
      if (!info) { const sec = await t.S.solFoundSecret(t.rpc, t.address, od.hsha); return sec ? { state: "claimed", html: `<span style="color:var(--accent2)">${esc(LT("flClaimed", "claimed"))}</span>` } : { state: "none", html: "— " + esc(LT("flNoLock", "nothing locked yet")) }; }
      const bad = [];
      if (info.owner !== t.program) bad.push(LT("badOwner", "not owned by the swap program"));
      if (info.hashlock !== od.hsha) bad.push(LT("badHash", "hashlock differs"));
      if (info.claimant !== t.claimant) bad.push(LT("badClaimant", "claimant is not the counterparty"));
      if (info.amount < t.lamports) bad.push(LT("badAmt", "amount short"));
      if ((info.mint || "") !== t.mint) bad.push(t.mint ? LT("badTok", "not this token") : LT("badNotSol", "a token lock, not SOL"));
      return bad.length ? { state: "short", html: `<span style="color:var(--danger)">${esc(LT("flMismatch", "DOES NOT MATCH: {m}", { m: bad.join("; ") }))}</span>` }
        : { state: "funded", html: `<span style="color:var(--accent2)">${esc(LT("flVerified", "verified: {a} locked until {d}", { a: od.wamt + " " + coinOf(od), d: new Date(t.deadline * 1000).toISOString().slice(0, 16).replace("T", " ") + "Z" }))}</span>` };
    }
    if (ch === "eth") {
      const token = tokAddrOf(od), htlc = token ? (net.erc20 || "") : ethHtlcFor(od);
      if (!htlc || !net.rpc) return { state: "none", html: "" };
      const sells = od.kind === OTC_ASK;
      const senderAddr = sells ? ethAddrOf(od.tadr) : ethAddrOf(od.wadr), claimAddr = sells ? ethAddrOf(od.wadr) : ethAddrOf(od.tadr);
      if (!senderAddr || !claimAddr) return { state: "none", html: "— " + esc(LT("flNoAddrs", "addresses not both published yet")) };
      const dec = token ? (await ethTokenMeta(token) || {}).decimals : 18;
      const amtWei = toUnitsDec(od.wamt, dec == null ? 18 : dec), dl = ethDeadline(od);
      const key = token ? htlcErc20Abi.lockKey(token, od.hsha, claimAddr, senderAddr, dl, amtWei) : htlcAbi.lockKey(od.hsha, claimAddr, senderAddr, dl, amtWei);
      const r = await (await fetch(net.rpc, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_call", params: [{ to: htlc, data: (token ? htlcErc20Abi : htlcAbi).locks(key) }, "latest"] }) })).json();
      const words = String(r.result || "0x").replace(/^0x/, "").match(/.{64}/g) || [];
      const held = words.length ? BigInt("0x" + words[token ? 3 : 2]) : 0n;
      if (held >= amtWei && amtWei > 0n) return { state: "funded", html: `<span style="color:var(--accent2)">${esc(LT("flVerifiedEth", "verified: {a} locked under this order's exact terms until {d}", { a: od.wamt + " " + coinOf(od), d: new Date(dl * 1000).toISOString().slice(0, 16).replace("T", " ") + "Z" }))}</span>` };
      if (held > 0n) return { state: "short", html: `<span style="color:var(--danger)">${esc(LT("flUnderEth", "UNDERFUNDED: holds less than the agreed amount — do not lock your side"))}</span>` };
      const sec = await ethRevealed(od, net.rpc, htlc, key, token);
      return sec ? { state: "claimed", html: `<span style="color:var(--accent2)">${esc(LT("flClaimed", "claimed"))}</span>`, secret: sec } : { state: "none", html: "— " + esc(LT("flNoLockTerms", "nothing locked under these terms yet")) };
    }
    return { state: "none", html: "" };
  } catch (e) { return { state: "error", html: "— " + esc(LT("flErr", "could not read the lock: {m}", { m: String(e.message || e).slice(0, 80) })) }; }
}
/** The preimage the contract recorded when the lock under this key was claimed — one eth_call, served by any RPC. */
async function ethRevealed(od, rpc, htlc, key, token) {
  try {
    const r = await (await fetch(rpc, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_call", params: [{ to: htlc, data: (token ? htlcErc20Abi : htlcAbi).revealed(key) }, "latest"] }) })).json();
    const s = String(r.result || "").replace(/^0x/, "").slice(-64);
    if (/^[0-9a-f]{64}$/.test(s) && /[1-9a-f]/.test(s) && (await sha256Hex(s)) === od.hsha) return s;
  } catch (e) {}
  return null;
}
/** Claimed(key, s) logs over a plain RPC (no wallet needed) — the secret, if the lock under this order was claimed. */
async function ethFoundSecretRpc(od, rpc, htlc) {
  // Public RPCs cap eth_getLogs at ~100 blocks, so walk back from the tip in chunks — a swap's whole
  // window is a few thousand blocks, and the scan stops at the first match.
  try {
    const { keccak_256 } = await import("./vendor/noble-sha3.js");
    const topic = "0x" + Array.from(keccak_256(new TextEncoder().encode("Claimed(bytes32,bytes32)")), (x) => x.toString(16).padStart(2, "0")).join("");
    const tip = Number(await ethBlockNumber(rpc)), CH = 100, MAX = 2500;
    for (let hi = tip; hi > tip - MAX; hi -= CH) {
      const lo = Math.max(0, hi - CH + 1);
      const r = await (await fetch(rpc, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_getLogs", params: [{ address: htlc, fromBlock: "0x" + lo.toString(16), toBlock: "0x" + hi.toString(16), topics: [topic] }] }) })).json();
      if (r.error) break;
      for (const lg of r.result || []) { const s = (lg.data || "").slice(-64); if (/^[0-9a-f]{64}$/.test(s) && (await sha256Hex(s)) === od.hsha) return s; }
    }
  } catch (e) {}
  return null;
}
async function ethBlockNumber(rpc) {
  const r = await (await fetch(rpc, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_blockNumber", params: [] }) })).json();
  return parseInt(r.result || "0x0", 16);
}
/** Fill #fchk<o> with the foreign lock's verdict. */
async function foreignLockCheck(od) {
  const el = $("fchk" + od.o); if (!el) return;
  const r = await foreignLockState(od); el.innerHTML = r.html;
}
// the node reports an L1 lock's status as an English word; say the ones we know in the page's language
const htlcStatus = (st) => ({ open: LT("stOpen", "open"), claimed: LT("flClaimed", "claimed"), refunded: LT("stRefunded", "refunded") })[st] || st;
/** Fill #hchk<o> with a verdict on the bound L1 lock: amount, hashlock, claimant, expiry, status. */
async function nadoHtlcCheck(od) {
  const el = $("hchk" + od.o); if (!el) return;
  const h = await nadoHtlc(od);
  if (!h) { el.textContent = "— " + LT("hNotFound", "not found on L1 yet"); return; }
  const sells = od.kind === OTC_ASK, wantClaimant = sells ? od.taker : od.maker;
  const bad = [];
  if (BigInt(h.amount || 0) < od.namtRaw) bad.push(LT("hBadAmt", "amount {a} < {b}", { a: rawToNado(String(h.amount || 0)), b: rawToNado(od.namtRaw.toString()) }));
  if (String(h.hashlock || "").toLowerCase() !== od.hsha) bad.push(LT("hBadHash", "locked under a different secret"));
  if (String(h.claimant || "") !== String(wantClaimant)) bad.push(LT("hBadClaimant", "not claimable by the counterparty"));
  if (Number(h.expiry || 0) < od.expn) bad.push(LT("hBadExp", "unlocks {t} before this order expires", { t: blocksToTime(Math.max(0, od.expn - Number(h.expiry || 0))) }));
  if (h.status !== "open") bad.push(LT("hAlready", "already {s}", { s: htlcStatus(h.status) }));
  el.innerHTML = bad.length
    ? `<span style="color:var(--danger)">${esc(LT("hMismatch", "DOES NOT MATCH: {m} — do not fund your side", { m: bad.join("; ") }))}</span>`
    : `<span style="color:var(--accent2)">${esc(LT("hVerified", "verified: {n} NADO, this hashlock, claimable by the counterparty for ≈ {t}", { n: rawToNado(String(h.amount)), t: blocksToTime(Math.max(0, Number(h.expiry) - (dapp.cursor || 0))) }))}</span>`;
}

// ---- the swap engine ---------------------------------------------------------------------------------
// A swap is two locks and two claims. The page reads BOTH chains for every swap you are part of, shows
// exactly one next step (or "waiting for the other side"), and performs the claims and the settle itself
// the moment they become possible — a claim can only pay you, so there is nothing to decide. The two
// LOCKS stay yours to confirm: they are the only moments money leaves you.
const SWAP = {};                                      // o -> { nado, foreign, secret, at }
const AUTO_LS = "nado_otc_auto";
const autoLog = () => { try { return JSON.parse(localStorage.getItem(AUTO_LS) || "{}"); } catch (e) { return {}; } };
const autoMark = (k) => { const m = autoLog(); m[k] = Date.now(); try { localStorage.setItem(AUTO_LS, JSON.stringify(m)); } catch (e) {} };
const autoRecently = (k, ms) => (Date.now() - (autoLog()[k] || 0)) < ms;
async function probeSwap(od) {
  const cur = SWAP[od.o];
  if (cur && Date.now() - cur.at < 8000) return cur;
  const st = { nado: "none", foreign: "none", secret: null, at: Date.now(), busy: true };
  SWAP[od.o] = Object.assign({}, cur || {}, st);
  try {
    if (od.hid) { const h = await nadoHtlc(od); st.nado = h ? h.status : "none"; st.nadoDoc = h; }
    st.secret = await otcKnownSecret(od);
    if (od.st >= 2) { const f = await foreignLockState(od); st.foreign = f.state; st.foreignHtml = f.html; st.fsecret = f.secret || null; if (!st.secret && f.secret) st.secret = f.secret; }
    if (!st.secret && (st.foreign === "claimed" || od.st === 3)) {   // the reveal happened on the foreign chain
      const ch = chainOf(od);
      st.secret = ch === "btc" ? await btcFoundSecret(od) : ch === "eth" ? st.fsecret || null : ch === "sol" ? await solFoundSecret(od) : null;
    }
  } catch (e) {}
  st.busy = false; st.at = Date.now();
  SWAP[od.o] = st;
  return st;
}
/** The one thing to do now for this swap, from the viewer's seat. */
function swapPlan(od, S) {
  const me = dapp.me, isMaker = od.maker === me, isTaker = od.taker === me, sells = od.kind === OTC_ASK;
  const coin = coinOf(od), nado = rawToNado(od.namtRaw.toString()) + " NADO", fam = `${od.wamt} ${coin}`;
  const expired = otcLeft(od) <= 0, fexp = Number(od.expf) && Date.now() / 1000 >= Number(od.expf);
  const ch = chainOf(od), fundAct = ch === "btc" ? "btcsend" : ch === "eth" ? "ethfund" : "solfund";
  const claimF = ch === "btc" ? "btcclaim" : ch === "eth" ? "ethclaim" : "solclaim";
  const refundF = ch === "btc" ? "btcrefund" : ch === "eth" ? "ethrefund" : "solrefund";
  const owesNado = sells ? isMaker : isTaker, owesF = !owesNado;
  const P = (o) => Object.assign({ step: 0 }, o);
  if (od.st === 5) return P({ done: LT("pCancelled", "Cancelled"), step: 6 });
  if (od.st === 4) return P({ done: LT("pRefunded", "Refunded"), step: 6 });
  if (od.st === 1) {
    if (expired) return isMaker ? P({ act: "cancel", label: LT("pCloseExpired", "Close this expired order"), step: 1 }) : P({ done: LT("pExpired", "Expired"), step: 1 });
    return isMaker ? P({ wait: LT("pWaitTaker", "Waiting for someone to take it"), step: 1 }) : P({ act: "fillask", label: LT("pTake", "Take this order"), step: 1 });
  }
  const nadoOpen = S.nado === "open", nadoClaimed = S.nado === "claimed", fFunded = S.foreign === "funded", fClaimed = S.foreign === "claimed";
  // finished?
  if ((owesNado && fClaimed) || (owesF && nadoClaimed) || (od.st === 3 && (owesNado ? fClaimed || !!S.secret : nadoClaimed))) return P({ done: LT("pComplete", "Swap complete"), step: 6 });
  // deadlines: reclaim what is yours
  if (owesNado && expired && od.hid && nadoOpen) return P({ act: "nadorefund", label: LT("pReclaimYour", "Reclaim your {a}", { a: nado }), step: 5 });
  if (owesF && fexp && fFunded) return P({ act: refundF, label: LT("pReclaimYour", "Reclaim your {a}", { a: fam }), step: 5 });
  if (expired || fexp) return P({ wait: LT("pExpiredEach", "Expired — each side reclaims its own lock"), step: 5 });
  // a fill costs nothing: if the taker never bound the NADO leg within the fill window, the maker may
  // release the order back to open (contract: release). Before that, say how long is left.
  if (isMaker && !od.hid) {
    const fillh = Number(od.fillh || 0), left = fillh ? fillh + 600 - (dapp.cursor || 0) : 600;
    const takerOwesNado = !sells;
    if (fillh && left <= 0 && (takerOwesNado || !fFunded)) return P({ act: "release", label: LT("pRelease", "Release this order — the taker never locked"), step: 2 });
    if (takerOwesNado && !nadoOpen) return P({ wait: LT("pWaitTakerLockLeft", "Waiting for the taker to lock {a} (they have ~{t} left, then you can release)", { a: nado, t: blocksToTime(Math.max(0, left)) }), step: 3 });
  }
  // the secret-holder (the maker) funds FIRST: ASK = maker's NADO, BID = maker's foreign coin
  if (sells) {
    if (isMaker) {
      if (!od.hid) return P({ act: "nadolock", label: LT("pLock", "Lock {a}", { a: nado }), step: 2 });
      if (!fFunded) return P({ wait: LT("pWaitTakerLock", "Waiting for the taker to lock {a}", { a: fam }), step: 3, hint: S.foreign === "short" ? LT("hShortNoClaim", "their lock is short — do not claim") : "" });
      if (S.secret) return P({ act: claimF, label: LT("pClaim", "Claim {a}", { a: fam }), auto: true, step: 4 });
      return P({ wait: LT("pNoSecret", "Your swap secret is not in this browser — restore it from your backup"), step: 4 });
    }
    if (isTaker) {
      if (!od.hid || !nadoOpen) return P({ wait: LT("pWaitMakerLock", "Waiting for the maker to lock {a}", { a: nado }), step: 2 });
      if (!fFunded && !fClaimed) return P({ act: fundAct, label: LT("pLock", "Lock {a}", { a: fam }), step: 3, hint: S.foreign === "short" ? LT("hShortYours", "your lock is short of the agreed amount") : "" });
      if (!S.secret) return P({ wait: LT("pWaitMakerClaim", "Waiting for the maker to claim the {c} — that reveals the secret", { c: coin }), step: 4 });
      return P({ act: "nadoclaim", label: LT("pClaim", "Claim {a}", { a: nado }), auto: true, step: 5 });
    }
  } else {
    if (isMaker) {
      if (!fFunded && !fClaimed) return P({ act: fundAct, label: LT("pLock", "Lock {a}", { a: fam }), step: 2 });
      if (!od.hid || !nadoOpen) return P({ wait: LT("pWaitTakerLock", "Waiting for the taker to lock {a}", { a: nado }), step: 3 });
      if (S.secret) return P({ act: "nadoclaim", label: LT("pClaim", "Claim {a}", { a: nado }), auto: true, step: 4 });
      return P({ wait: LT("pNoSecret", "Your swap secret is not in this browser — restore it from your backup"), step: 4 });
    }
    if (isTaker) {
      if (!fFunded) return P({ wait: LT("pWaitMakerLock", "Waiting for the maker to lock {a}", { a: fam }), step: 2, hint: S.foreign === "short" ? LT("hShortNoLock", "their lock is short — do not lock yours") : "" });
      if (!od.hid) return P({ act: "nadolock", label: LT("pLock", "Lock {a}", { a: nado }), step: 3 });
      if (!S.secret) return P({ wait: LT("pWaitMakerClaim", "Waiting for the maker to claim the {c} — that reveals the secret", { c: "NADO" }), step: 4 });
      return P({ act: claimF, label: LT("pClaim", "Claim {a}", { a: fam }), auto: true, step: 5 });
    }
  }
  return P({ wait: "…", step: 0 });
}
const STEPS = (od) => [LT("sPosted", "Posted"), LT("sTaken", "Taken"), LT("sLocked", "{c} locked", { c: od.kind === OTC_ASK ? "NADO" : coinOf(od) }),
  LT("sLocked", "{c} locked", { c: od.kind === OTC_ASK ? coinOf(od) : "NADO" }), LT("sClaimed", "Claimed"), LT("sDone", "Done")];
function stepperHtml(od, plan) {
  const names = STEPS(od), cur = Math.max(1, Math.min(6, plan.step || 1));
  return `<div class="steps">${names.map((n, i) => `<span class="stp${i + 1 < cur ? " done" : i + 1 === cur ? " cur" : ""}"${i + 1 === cur ? ' aria-current="step"' : ""}>${i + 1 < cur ? "✓ " : i + 1 === cur ? "▸ " : ""}${esc(n)}</span>`).join("")}</div>`;
}
let _autoBusy = false;
async function swapAutopilot() {
  // claims and settles fire themselves — once, retried after two minutes, only while the tab is visible
  if (_autoBusy || !dapp.me || document.visibilityState !== "visible") return;
  _autoBusy = true;
  try {
    for (const od of otcOrders()) {
      if (od.kind === OTC_INTRA || !(od.maker === dapp.me || od.taker === dapp.me) || od.st < 2 || od.st > 3) continue;
      const S = await probeSwap(od);
      const plan = swapPlan(od, S);
      if (plan.auto && plan.act && !autoRecently(plan.act + ":" + od.o, 120000)) {
        autoMark(plan.act + ":" + od.o);
        alertBar(LT("autoSigning", "{l} — signing…", { l: plan.label }));
        try { await otcAction(plan.act, od.o, null); } catch (e) {}
      }
      // settle is bookkeeping (publishes the secret on NADO, returns tips): value-free, so a wallet with
      // auto-sign on signs it silently; either party may send it
      if (od.st === 2 && S.secret && S.nado !== "open" && !autoRecently("settle:" + od.o, 180000)) {
        autoMark("settle:" + od.o);
        dapp.call("settle", [od.o, ...otcLimbs(S.secret)], null, LT("callSettle", "Settling #{o}…", { o: od.o }), { otc: od.o }, { cid: OTC_CID });
      }
    }
  } finally { _autoBusy = false; }
}

// ---- rendering ----------------------------------------------------------------------------------------
function otcRow(od, mine) {
  const me = dapp.me, isMaker = od.maker === me, isTaker = od.taker === me;
  const sells = od.kind === OTC_ASK;
  const left = otcLeft(od), expired = left <= 0;
  const chain = esc(coinOf(od));
  const hv = { n: `<b>${rawToNado(od.namtRaw.toString())} NADO</b>`, f: `<b>${esc(od.wamt)} ${chain}</b>` };
  const head = sells ? LT("rowSells", "sells {n} for {f}", hv) : LT("rowBuys", "buys {n} for {f}", hv);
  const pill = od.st === 1
    ? (expired ? `<span class="pill warn">${esc(LT("stExpired", "expired"))}</span>` : `<span class="pill">${esc(LT("stOpen", "open"))}</span>`)
    : `<span class="pill${od.st === 2 ? " warn" : ""}">${OTC_ST()[od.st] || od.st}</span>`;
  const party = isMaker || isTaker;
  const acts = [];
  const settler = sells ? isTaker : isMaker;            // settle pays ASK->taker, BID->maker (otc.py)
  if (od.st === 2 && !expired && settler) acts.push(`<button class="primary" data-otc="settle" data-o="${od.o}">${esc(LT("bSettle", "Settle…"))}</button>`);
  if (od.st === 1 && !expired && !isMaker && me && !mine) acts.push(`<button class="primary" data-otc="fillask" data-o="${od.o}">${esc(LT("bTake", "Take…"))}</button>`);
  if (od.st === 1 && !expired && isMaker) acts.push(`<button class="ghost" data-otc="cancel" data-o="${od.o}">${esc(LT("bCancel", "Cancel"))}</button>`);
  if ((od.st === 1 || od.st === 2) && expired && party) acts.push(`<button class="ghost" data-otc="expire" data-o="${od.o}">${esc(LT("reclaim", "Reclaim"))}${od.hid && (sells ? isMaker : isTaker) ? " " + rawToNado(od.namtRaw.toString()) + " NADO" : ""}</button>`);
  if ((od.st === 1 || od.st === 2) && !expired && party) acts.push(`<button class="ghost" data-otc="boost" data-o="${od.o}">${esc(LT("bTip", "Tip…"))}</button>`);
  const owesNado = od.st === 2 && (sells ? isMaker : isTaker);   // who provides the NADO side of this swap
  const getsNado = (sells ? isTaker : isMaker);                   // ... and who takes it with the secret
  if (od.st >= 2 && od.st !== 4 && od.hid && getsNado && !expired) acts.unshift(`<button class="primary" data-otc="nadoclaim" data-o="${od.o}">${esc(LT("bClaimThe", "Claim the {c}…", { c: "NADO" }))}</button>`);
  // the counterparty's foreign claim needs the secret: a BID taker can have it as soon as the NADO lock
  // is claimed on L1 (the row reads the preimage back), not only after the maker also calls settle
  const secretMayExist = od.st === 3 || (od.st === 2 && !!od.hid);
  if (owesNado && !expired && !od.hid) {
    acts.unshift(`<button class="primary" data-otc="nadolock" data-o="${od.o}">${esc(LT("bLockThe", "Lock the {c}…", { c: "NADO" }))}</button>`);
    acts.push(`<button class="ghost" data-otc="nadobind" data-o="${od.o}">${esc(LT("bBound", "I already locked it"))}</button>`);
  }
  const isEth = chainOf(od) === "eth";
  if (isEth && tokAddrOf(od) && !erc20Names[tokAddrOf(od).toLowerCase()] && ethProv()) ethTokenMeta(tokAddrOf(od));
  const ethSender = isEth && (sells ? isTaker : isMaker), ethClaimer = isEth && (sells ? isMaker : isTaker);
  if (isEth && od.st === 2 && ethSender) acts.push(`<button class="primary" data-otc="ethfund" data-o="${od.o}">${esc(LT("bLockThe", "Lock the {c}…", { c: "ETH" }))}</button>`);
  if (isEth && ((sells && od.st === 2) || (!sells && secretMayExist)) && ethClaimer) acts.unshift(`<button class="primary" data-otc="ethclaim" data-o="${od.o}">${esc(LT("bClaimThe", "Claim the {c}…", { c: "ETH" }))}</button>`);
  if (isEth && od.st >= 2 && ethSender && Date.now() / 1000 >= Number(od.expf)) acts.push(`<button class="ghost" data-otc="ethrefund" data-o="${od.o}">${esc(LT("reclaim", "Reclaim"))} ${esc(od.wamt)} ${chain}</button>`);
  const isSol = chainOf(od) === "sol";
  const solSender = isSol && (sells ? isTaker : isMaker), solClaimer = isSol && (sells ? isMaker : isTaker);
  if (isSol && od.st === 2 && solSender) acts.push(`<button class="primary" data-otc="solfund" data-o="${od.o}">${LT("bLockThe", "Lock the {c}…", { c: chain })}</button>`);
  if (isSol && ((sells && od.st === 2) || (!sells && secretMayExist)) && solClaimer) acts.unshift(`<button class="primary" data-otc="solclaim" data-o="${od.o}">${LT("bClaimThe", "Claim the {c}…", { c: chain })}</button>`);
  if (isSol && od.st >= 2 && solSender && Date.now() / 1000 >= Number(od.expf)) acts.push(`<button class="ghost" data-otc="solrefund" data-o="${od.o}">${esc(LT("reclaim", "Reclaim"))} ${esc(od.wamt)} ${chain}</button>`);
  const btc = chainOf(od) === "btc" ? btcInfo(od) : null;
  const btcFunder = chainOf(od) === "btc" && (sells ? isTaker : isMaker);
  const btcClaimer = chainOf(od) === "btc" && (sells ? isMaker : isTaker);
  if (btc && od.st === 2 && btcClaimer && sells && otcRec(od.o).s) acts.unshift(`<button class="primary" data-otc="btcclaim" data-o="${od.o}">${esc(LT("bClaimThe", "Claim the {c}…", { c: "BTC" }))}</button>`);
  if (btc && secretMayExist && btcClaimer && !sells) acts.unshift(`<button class="primary" data-otc="btcclaim" data-o="${od.o}">${esc(LT("bClaimYour", "Claim your {c}…", { c: "BTC" }))}</button>`);
  if (btc && od.st >= 2 && btcFunder && Date.now() / 1000 >= Number(od.expf)) acts.push(`<button class="ghost" data-otc="btcrefund" data-o="${od.o}">${esc(LT("reclaim", "Reclaim"))} BTC</button>`);
  let detail = "";
  if (mine) {
    let hint = "";
    if (od.st === 1 && !expired && isMaker) hint = esc(LT("hintWaitTaker", "Waiting for a taker — your funds stay reclaimable. Cancel any time."));
    else if (od.st === 2 && !expired) {
      const foreign = chain;
      const isBtc = chainOf(od) === "btc";
      const fv = { c: foreign };
      const lockF = isBtc ? LT("hLockFBtc", "send the {c} to the address below", fv) : LT("hLockF", "press Lock the {c} (your wallet pays it into the swap)", fv);
      const claimF = isBtc ? LT("hClaimFBtc", "press Claim the {c}", fv) : LT("hClaimF", "press Claim the {c} — your wallet signs it", fv);
      if (sells && isMaker && !od.hid) hint = LT("hAskMaker0", "Next: press Lock the NADO — it escrows your NADO on the main chain under this swap's hashlock, takeable only by the taker and only with the secret.");
      else if (sells && isMaker) hint = LT("hAskMaker1", "Next: once the taker's {c} lock is CONFIRMED and holds the agreed amount, {claim}. Claiming reveals the secret, and that completes your side.", { c: foreign, claim: claimF });
      else if (sells && isTaker && !od.hid) hint = LT("hAskTaker0", "Next: wait — the maker must lock their NADO on the main chain first. Do not send any {c} until that lock shows as verified below.", fv);
      else if (sells && isTaker) hint = LT("hAskTaker1", "Next: once the NADO lock below reads \"verified\", {lock}. When the maker claims it the secret becomes public — then press Claim the NADO.", { lock: lockF });
      else if (!sells && isMaker && !od.hid) hint = LT("hBidMaker0", "Next: {lock} FIRST — you hold the secret, so your lock goes in before the taker's. The taker locks the NADO once they have checked yours.", { lock: lockF });
      else if (!sells && isMaker) hint = LT("hBidMaker1", "Next: once the NADO lock below reads \"verified\", press Claim the NADO — that reveals the secret, and the taker claims your {c} with it.", fv);
      else if (!sells && isTaker && !od.hid) hint = LT("hBidTaker0", "Next: wait for the maker's {c} lock and CHECK it (the agreed amount, this hashlock, a deadline past this order's NADO expiry). Only then press Lock the NADO.", fv);
      else if (!sells && isTaker) hint = LT("hBidTaker1", "Next: wait. When the maker claims your NADO the secret becomes public, and Claim the {c} works here.", fv);
    } else if ((od.st === 1 || od.st === 2) && expired) hint = esc(LT("hExpired", "Expired — press Reclaim to take back whatever you locked; the other chain's lock is reclaimed with its own button."));
    if (hint) detail += `<div class="small mt" style="color:var(--accent2)">${hint}</div>`;
    if (chainOf(od) === "btc" && od.st >= 2 && (isMaker || isTaker)) {
      const b = btcInfo(od);
      if (b) detail += `<div class="small mt">${btcFunder && od.st === 2 ? `<b>${esc(LT("btcSendTo", "Send exactly {a} BTC to:", { a: od.wamt }))}</b><br>` : esc(LT("btcSwapAddr", "Swap address:")) + " "}<span class="mono" style="word-break:break-all">${b.addr}</span>
        <a href="#" data-otc="btccopy" data-o="${od.o}">${esc(LT("aCopy", "copy"))}</a> · <a href="#" data-otc="btcverify" data-o="${od.o}">${esc(LT("aVerify", "verify"))}</a>
        <span id="btcv${od.o}" class="dim"></span></div>`;
      else if (!btcParts(od)) detail += `<div class="small dim mt">${esc(LT("btcNoPub", "The counterparty's client did not publish a Bitcoin key, so this page cannot build the Bitcoin side."))} <details class="more"><summary>${esc(LT("advanced", "Advanced"))}</summary>${esc(LT("btcFinishCli", "Finish it with {s}.", { s: "scripts/otc_btc_leg.py" }))}</details></div>`;
    }
    if ((chainOf(od) === "eth" || chainOf(od) === "sol") && od.st === 2 && (isMaker || isTaker)) {
      detail += `<div class="small mt">${esc(LT("fLockLbl", "{c} lock:", { c: coinOf(od) }))} <span id="fchk${od.o}" class="dim">${esc(LT("checking", "checking…"))}</span></div>`;
      setTimeout(() => foreignLockCheck(od), 0);
    }
    if (chainOf(od) === "eth" && od.st >= 2 && (isMaker || isTaker) && !ethProv()) detail += ethCliHint(od);
    if (chainOf(od) === "sol" && od.st >= 2 && (isMaker || isTaker)) {
      if (!solProgramOf(od)) detail += `<div class="small dim mt">${esc(LT("solNoProgRow", "No swap program is deployed on {n} yet — this order cannot be completed here.", { n: (netOf(od) || {}).label }))}</div>`;
      else if (!solHas()) detail += solCliHint(od);
    }
    const rec0 = otcRec(od.o);
    if ((rec0.k || rec0.s) && (od.st === 1 || od.st === 2))
      detail += `<div class="small dim mt"><a href="#" data-otc="showsecret" data-o="${od.o}">${esc(LT("backupLink", "Back up this swap"))}</a> — ${esc(LT("backupWhy", "without it a lost browser means lost funds."))}</div>`;
    const secret = rec0.s;
    if (secret && (od.st === 1 || od.st === 2))
      detail += `<div class="small dim mt">${esc(LT("secretLbl", "Your swap secret:"))} <span class="mono">${secret.slice(0, 16)}…</span>
        <a href="#" data-otc="showsecret" data-o="${od.o}">${esc(LT("backupShort", "back up"))}</a> — ${esc(LT("secretKeep", "keep a copy: it is all this swap needs on any device (never share it before the counterparty's lock is CONFIRMED)."))}</div>`;
    if (od.st === 2 && od.hid) {
      detail += `<div class="small mt">${esc(LT("nadoLockedLbl", "NADO locked — lock"))} <span class="mono">${esc(String(od.hid)).slice(0, 16)}…</span> <span id="hchk${od.o}" class="dim">${esc(LT("checking", "checking…"))}</span></div>`;
      setTimeout(() => nadoHtlcCheck(od), 0);
    }
    if (od.st === 2 && od.fref && od.fref !== "pending") detail += `<div class="small dim mt">${LT("theirTx", "Their {c} transaction:", { c: chain })} <span class="mono">${esc(od.fref).slice(0, 40)}</span>
      · ${esc(LT("counterparty", "counterparty"))} ${esc(disp(isMaker ? od.taker : od.maker))}</div>`;
    if (od.st === 3 && od.limbs.some((x) => Number(x) > 0)) {
      const rs = otcSecretFromLimbs(od.limbs);
      detail += `<div class="small mt">${LT("secretRevealed", "Secret revealed — it unlocks the {c} side:", { c: chain })} <span class="mono" style="word-break:break-all">${rs}</span></div>`;
    }
  }
  let main = "", more = "";
  if (mine && party && od.kind !== OTC_INTRA) {
    const S = SWAP[od.o] || { nado: "none", foreign: "none", secret: null };
    if (!SWAP[od.o] || Date.now() - SWAP[od.o].at > 8000) probeSwap(od).then(() => render());
    const plan = swapPlan(od, S);
    const primary = plan.done ? `<span class="pill">${esc(plan.done)}</span>`
      : plan.act ? `<button class="primary" data-otc="${plan.act}" data-o="${od.o}">${esc(plan.label)}${plan.auto ? " (" + esc(LT("automatic", "automatic")) + ")" : ""}</button>`
      : `<span class="waiting"><span class="spin"></span>${esc(plan.wait || "")}</span>`;
    main = stepperHtml(od, plan) + `<div class="nextact">${primary}${plan.hint ? `<div class="small" style="color:var(--danger)">${esc(plan.hint)}</div>` : ""}</div>`;
    more = `<details class="more"><summary>${esc(LT("more", "More"))}</summary><div>${detail}<div class="loanacts" style="flex-direction:row;flex-wrap:wrap;margin-top:8px">${acts.join("")}</div></div></details>`;
    acts.length = 0; detail = "";
  }
  return `<div class="loan"><div class="loanmain">
      <div class="loantop">${pill} <b>#${od.o}</b> ${esc(disp(od.maker))} ${head}</div>
      ${main}
      <div class="loanterms">${od.prem > 0n ? esc(LT("rowStake", "maker has {n} NADO at stake", { n: rawToNado(od.prem.toString()) })) + " · " : ""}${od.bnty > 0n ? `<span class="pill">${esc(LT("rowTip", "+{n} NADO tip", { n: rawToNado(od.bnty.toString()) }))}</span> · ` : ""}${od.st <= 2 ? esc(expired ? LT("rowRefundable", "refundable now") : LT("rowExpires", "expires in {n} {n|one:block|other:blocks} (~{t})", { n: left, t: blocksToTime(left) })) : ""}
        ${od.expf ? `· ${esc(LT("rowDeadlineF", "{c} deadline {d}", { c: coinOf(od), d: new Date(Number(od.expf) * 1000).toISOString().slice(0, 16).replace("T", " ") + "Z" }))}` : ""}</div>
      <div class="loanwho dim small">${LT("rowOn", "on {n}", { n: `<b>${esc((netOf(od) || {}).label || od.wch)}</b>` })} · ${esc(sells ? LT("rowMakerGets", "maker receives {c} at", { c: coinOf(od) }) : LT("rowTakerGets", "taker receives {c} at", { c: coinOf(od) }))} ${esc((sells ? od.wadr : od.tadr || od.wadr).split("|")[0]) || esc("(" + LT("rowKeyPub", "swap key published") + ")")}</div>
      ${detail}${more}
    </div><div class="loanacts">${acts.join("")}</div></div>`;
}
function renderOtc() {
  const book = $("otcBook"), mine = $("otcMine");
  if (!book || !mine) return;
  const all = otcOrders(), me = dapp.me;
  const open = all.filter((x) => x.st === 1 && x.kind !== OTC_INTRA && mktKeyOf(x) === xsel && otcLeft(x) > 0);
  book.innerHTML = open.length ? open.map((x) => otcRow(x, false)).join("")
    : otcEmpty(esc(LT("bookNone", "No open orders. Post one — the book is permissionless.")));
  const my = all.filter((x) => me && x.kind !== OTC_INTRA && (x.maker === me || x.taker === me));
  mine.innerHTML = my.length ? my.map((x) => otcRow(x, true)).join("")
    : `<p class="small dim">${esc(LT("mineNone", "Nothing yet — post or take an order."))}</p>`;
  [book, mine].forEach((box) => box.querySelectorAll("[data-otc]").forEach((el) => {
    el.onclick = (ev) => { ev.preventDefault();
      runAction(el.tagName === "BUTTON" ? el : null, () => otcAction(el.getAttribute("data-otc"), Number(el.getAttribute("data-o")), el)); };
  }));
}

// ---- actions ------------------------------------------------------------------------------------------
// Fill the ERC-20 picker from what is actually known on this network, and say what a pasted address is.
function fillTokenPicker() {
  const netSel = $("otcNet"), tp = $("otcTokenPick");
  if (!tp || !netSel) return;
  const net = netSel.value, known = tokensFor(net);
  for (const od of otcOrders()) {                      // tokens seen on live orders count as discovered
    const t = tokAddrOf(od);
    if (t && netKeyOf(od) === net && !known[t.toLowerCase()]) {
      const m = erc20Names[t.toLowerCase()];
      known[t.toLowerCase()] = { sym: (m && m.symbol) || LT("tokWord", "token"), dec: (m && m.decimals) || 18 };
    }
  }
  const opts = [`<option value="">${esc(LT("tpNoTok", "{c} itself — no token", { c: (NETS[net] || {}).coin || LT("theCoin", "the coin") }))}</option>`]
    .concat(Object.keys(known).map((a) => `<option value="${a}">${esc(known[a].sym)} · ${a.slice(0, 10)}…</option>`))
    .concat([`<option value="?">${esc(LT("tpOther", "another token — paste its address"))}</option>`]);
  const sig = opts.join("");
  if (tp.dataset.sig !== sig) { tp.dataset.sig = sig; tp.innerHTML = sig; }
}
function showTokenInfo(text, bad) {
  const el = $("otcTokenInfo");
  if (el) { el.innerHTML = text ? `<span style="color:var(--${bad ? "danger" : "accent2"})">${esc(text)}</span>` : ""; }
}
async function verifyPastedToken() {
  const a = (($("otcToken") || {}).value || "").trim(), net = ($("otcNet") || {}).value;
  if (!/^0x[0-9a-fA-F]{40}$/.test(a)) return showTokenInfo(LT("tiBadAddr", "A token address is 0x followed by 40 hex characters."), true);
  if (!ethProv()) return showTokenInfo(LT("tiNoWallet", "Connect an Ethereum wallet to check this token against the chain."), true);
  showTokenInfo(LT("tiChecking", "checking the contract…"));
  try {
    const { chain } = await ethConnect();
    if (chain !== (NETS[net] || {}).evm) return showTokenInfo(LT("tiSwitch", "Switch your wallet to {n} to check a token there.", { n: (NETS[net] || {}).label }), true);
    const meta = await ethTokenMeta(a);
    if (!meta || meta.symbol === "TOKEN") return showTokenInfo(LT("tiNotErc20", "That address did not answer as an ERC-20 — check it on a block explorer."), true);
    tokenRemember(net, a, meta);
    fillTokenPicker();
    // A symbol is whatever the contract SAYS it is; the address is the only identity that matters.
    showTokenInfo(LT("tiOk", "{s} · {d} decimals · {a} — any contract can claim any symbol, so check the address.", { s: meta.symbol, d: meta.decimals, a }));
  } catch (e) { showTokenInfo(String((e && e.message) || e).slice(0, 120), true); }
}

// The segmented switch carries the short label; the sentence explaining it lives underneath and follows
// the choice, instead of being crammed into a button.
function kindHint() {
  const el = $("otcKindHint"), k = (($("otcKind") || {}).value) || "1";
  const netK = ($("otcNet") || {}).value, tp = $("otcTokenPick");
  const tokSel = tp && tp.value && tp.value !== "?" ? (tokensFor(netK)[tp.value] || {}).sym || LT("theToken", "the token") : "";
  const coin = tokSel || (NETS[netK] || {}).coin || LT("theCoin", "the coin");
  if (el) el.textContent = k === "1"
    ? LT("kindAsk", "You give NADO and receive {c}. You generate the swap secret, so you finish the swap.", { c: coin })
    : LT("kindBid", "You give {c} and receive NADO. You generate the swap secret; your {c} lock must outlast the taker's NADO lock.", { c: coin });
}

async function otcPost() {
  const kind = Number($("otcKind").value);
  const raw = (() => { try { return BigInt(nadoToRaw(($("otcNado").value || "").trim())); } catch (e) { return 0n; } })();
  const netSelV = $("otcNet").value, chain = (NETS[netSelV] || {}).chain;
  const tp2 = $("otcTokenPick");
  const tokenV = (tp2 && tp2.value && tp2.value !== "?") ? tp2.value : ((($("otcToken") || {}).value) || "").trim();
  if (tokenV && chain === "eth" && !/^0x[0-9a-fA-F]{40}$/.test(tokenV)) return alertBar(LT("postBadTok", "A token address looks like 0x followed by 40 hex characters."));
  if (tokenV && chain === "sol" && !isB58Addr(tokenV)) return alertBar(LT("postBadMint", "A Solana token is named by its mint address (32–44 base58 characters)."));
  if (tokenV && !netSupportsTokens(netSelV)) return alertBar(LT("postNoTokNet", "Token swaps are not available on {n} yet.", { n: (NETS[netSelV] || {}).label }));
  const net = tokenV ? netSelV + "|" + tokNorm(tokenV) : netSelV;   // the token rides in the network field
  const famt = ($("otcFAmt").value || "").trim(), faddr = ($("otcFAddr").value || "").trim();
  const blocks = Math.floor(Number($("otcExpiry").value || 0));
  if (raw <= 0n) return alertBar(LT("postNeedNado", "Enter the NADO amount."));
  if (!famt || !(Number(famt) > 0)) return alertBar(LT("postNeedF", "Enter the foreign amount."));
  if (!faddr) return alertBar(LT("postNeedAddr", "Enter your {n} address.", { n: (NETS[netSelV] || {}).label }));
  // Validate the receiving address by chain NOW: a bad one is otherwise discovered only when the other
  // side locks to it (an EVM lock to a malformed address pads to 0x000…0 — unclaimable by anyone).
  if (chain === "eth" && !/^0x[0-9a-fA-F]{40}$/.test(faddr)) return alertBar(LT("badEthAddr", "An Ethereum address is 0x followed by 40 hex characters."));
  if (chain === "sol" && !isB58Addr(faddr)) return alertBar(LT("badSolAddr", "That is not a Solana address (32–44 base58 characters)."));
  if (chain === "btc") { try { await addressToScript(faddr, (NETS[netSelV] || {}).hrp || "bc"); } catch (e) { return alertBar(LT("badBtcAddr", "That is not a valid {n} address: {m}", { n: (NETS[netSelV] || {}).label, m: String(e.message || e) })); } }
  faddrSet(netSelV, faddr);                                // typed once — reused for every future swap on this network
  if (!(blocks >= 20 && blocks <= 900000)) return alertBar(LT("expRange", "Expiry must be between 20 blocks (≈ {a}) and 900,000 blocks (≈ {b}).", { a: blocksToTime(20), b: blocksToTime(900000) }));
  const o = randId();
  const sHex = Array.from(crypto.getRandomValues(new Uint8Array(32)), (x) => x.toString(16).padStart(2, "0")).join("");
  let kp = null, packed = faddr;
  if (chain === "btc") { kp = genKeypair(); packed = faddr + "|" + kp.pub; }
  else if (chain === "eth") { const ek = ethProv() ? null : ethKeypair();
    // with a wallet the maker's own EVM address is used at claim time; without one, a page key is generated for the CLI
    if (ek) { kp = { k: ek.k }; packed = faddr + "|" + ek.addr; } }
  otcSaveRec(o, Object.assign({ s: sHex }, kp || {})); // BEFORE the wallet redirect can navigate away
  const hsha = await sha256Hex(sHex);
  const vmParts = otcVmParts(sHex);            // the four hashlocks, eight 32-bit halves
  // expf: the FOREIGN leg's deadline both parties sign. Advisory to the VM (it cannot read that chain);
  // the wallet suggests ~60% of the NADO window in unix seconds so the foreign refund opens first (§6.3).
  // Derive the foreign deadline from CHAIN time, not the poster's clock, and keep it comfortably inside
  // the NADO window (§6.3): the foreign side must be refundable BEFORE the NADO escrow unlocks.
  const nowSec = (dapp.chainNow && dapp.chainNow()) || Math.floor(Date.now() / 1000);
  // Land in the middle of the window the contract enforces (§6.3, otc.py FOREIGN_MIN_S/FOREIGN_MARGIN_S):
  // late enough for the foreign leg to be funded and confirmed, early enough to refund before the NADO side.
  const FOREIGN_MIN_S = 3600, FOREIGN_MARGIN_S = 7200, windowS = blocks * 6;
  // Every foreign HTLC template caps its deadline (HtlcEth / the Solana program: 30 days), so the deadline
  // this order carries must be reachable there — otherwise the lock reverts and the order can only expire.
  const FOREIGN_MAX_S = 29 * 24 * 3600;
  if (windowS < FOREIGN_MIN_S + FOREIGN_MARGIN_S + 1800)
    return alertBar(LT("expShort", "That expiry is too short for a {c} swap — use at least {n} blocks.", { c: (NETS[$("otcNet").value] || {}).coin || LT("crossWord", "cross-chain"), n: Math.ceil((FOREIGN_MIN_S + FOREIGN_MARGIN_S + 1800) / 6) }));
  // §6.3 is KIND-DEPENDENT (otc.py post): the maker generates the secret for both kinds, and the leg the
  // maker FUNDS must outlast the leg they CLAIM. ASK: maker funds NADO, so the foreign deadline sits
  // inside the NADO window. BID: maker funds the foreign leg, so its deadline sits PAST the NADO window.
  let expf;
  if (kind === OTC_ASK) expf = Math.floor(nowSec + (FOREIGN_MIN_S + windowS - FOREIGN_MARGIN_S) / 2);
  else {
    expf = Math.floor(nowSec + windowS + FOREIGN_MARGIN_S + 3600);
    if (expf > nowSec + FOREIGN_MAX_S)
      return alertBar(LT("expLong", "A buy order's {c} lock must outlast its NADO expiry, and that chain allows at most 30 days — use at most {n} blocks.", { c: (NETS[$("otcNet").value] || {}).coin || LT("foreignWord", "foreign"), n: Math.floor((FOREIGN_MAX_S - FOREIGN_MARGIN_S - 3600) / 6) }));
  }
  if (expf > nowSec + FOREIGN_MAX_S) expf = nowSec + FOREIGN_MAX_S;   // ASK: clamp long NADO windows; the margin still holds
  const expn = (dapp.cursor || 0) + blocks;
  {
    const coinName = tokenV ? (tokensFor(netSelV)[tokenV] || {}).sym || LT("tokensWord", "tokens") : (NETS[netSelV] || {}).coin || LT("coinsWord", "coins");
    const nadoF = Number(rawToNado(raw.toString())), price = nadoF > 0 ? Number(famt) / nadoF : 0;
    const give = kind === OTC_ASK ? `${rawToNado(raw.toString())} NADO` : `${famt} ${coinName}`;
    const get = kind === OTC_ASK ? `${famt} ${coinName}` : `${rawToNado(raw.toString())} NADO`;
    if (!await uiConfirm({ title: kind === OTC_ASK ? LT("otcSellNado", "Sell NADO") : LT("otcBuyNado", "Buy NADO"),
      body: LT("postBody", "Posting locks nothing. Once someone takes it, both sides are committed and your row walks you through the locks."),
      rows: [{ k: LT("youGive", "You give"), v: give }, { k: LT("youGet", "You receive"), v: get },
             { k: LT("rowPrice", "Price"), v: `1 NADO = ${fmtPrice(price)} ${coinName}` },
             { k: LT("rowPaidTo", "Paid to"), v: faddr.slice(0, 14) + "…" + faddr.slice(-6) },
             { k: LT("rowOpenFor", "Open for"), v: `≈ ${blocksToTime(blocks)}` }],
      confirmText: LT("otcPostBtn", "Post order") })) { otcForget(o); return; }
  }
  const box = $("otcSecretBox"); if (box) { box.classList.remove("hidden"); $("otcSecretHex").textContent = sHex + (kp ? "  ·  " + LT("btcKeyLbl", "BTC key:") + " " + kp.k : ""); }
  // No VALUE: the NADO leg of a cross-chain swap is escrowed in an L1 HTLC under the SAME SHA-256
  // hashlock as the foreign leg, never in this contract (see otc.py WHERE THE MONEY SITS).
  dapp.call("post", [o, kind, raw, net, famt, packed, hsha, ...vmParts, expn, expf],
            null, LT("callPost", "Posting order #{o}…", { o }), { otc: o }, { cid: OTC_CID });
}
async function runAction(btn, fn) {
  if (!btn) return fn();
  if (btn.dataset.busy) return;                        // ignore the double-click instead of firing twice
  const was = btn.textContent;
  btn.dataset.busy = "1"; btn.disabled = true; btn.textContent = LT("working", "working…");
  try { return await fn(); }
  catch (e) { alertBar((e && e.message) || String(e)); }   // a click must never end in silence
  finally { delete btn.dataset.busy; btn.disabled = false; btn.textContent = was; }
}
async function otcAction(what, o, btn) {
  const od = otcOrders().find((x) => x.o === o);
  if (!od) { render(); return alertBar(LT("aGone", "That order is no longer on the book — the list has been refreshed.")); }
  if (what === "showsecret") {
    const r = otcRec(o);
    // Everything needed to rebuild the swap on another device — the key alone is not enough, because the
    // witness script also needs the counterparty's pubkey, the hashlock and the deadline (audit).
    const b = chainOf(od) === "btc" ? btcInfo(od) : null;
    const blob = JSON.stringify(Object.assign({ order: o, network: netKeyOf(od), kind: od.kind,
      hashlock: od.hsha, deadline: od.expf, amount: od.wamt },
      r.s ? { secret: r.s } : {}, r.k ? { key: r.k } : {}, r.pub ? { pubkey: r.pub } : {},
      b ? { script: b.script, address: b.addr } : {}));
    if (r.s || r.k) await uiPrompt({ title: LT("bkTitle", "Back up swap #{o}", { o }),
      body: LT("bkBody", "Copy this somewhere safe — it is everything this swap needs to be finished or reclaimed from another device."),
      value: blob, confirmText: LT("sDone", "Done") });
    return;
  }
  // INVARIANT: a value-free call is signed in the background with NO wallet dialog, so this confirm is the only thing
  // between one click and an order gone for good (2026-11-05: two open ETH asks were cancelled a minute after posting
  // by a click their owner never meant). Every branch here that ends an order or a fill confirms first.
  const terms = od.kind === OTC_INTRA ? LT("termsFor", "{a} for {b}", { a: limText(od.gast, od.escRaw), b: limText(od.wast, od.want) })
                                      : LT("termsFor", "{a} for {b}", { a: `${rawToNado(od.namtRaw.toString())} NADO`, b: `${od.wamt} ${coinOf(od)}` });
  if (what === "cancel") {
    if (!await uiConfirm({ title: LT("cxTitle", "Cancel order #{o}?", { o }),
      body: LT("cxBody", "It leaves the book for good and whatever it escrowed comes back to you. To trade again you post a new order."),
      rows: [{ k: LT("rowOrder", "Order"), v: terms }], confirmText: LT("cxOk", "Cancel the order"), cancelText: LT("cxKeep", "Keep it"), danger: true })) return;
    return dapp.call("cancel", [o], null, LT("callCancel", "Cancelling #{o}…", { o }), { otc: o }, { cid: OTC_CID });
  }
  if (what === "boost") {
    if (od.st !== 1 && od.st !== 2) return alertBar(LT("tipDone", "This order is finished — nothing left to tip."));
    // §8: attach a NADO bounty ANYONE can win by finishing this order (settle / expire / atomic fill).
    // It makes watchtowers work for you; cancel returns it to the maker.
    const typed = ((await uiPrompt({ title: LT("tipTitle", "Tip whoever finishes this swap"),
      body: LT("tipBody", "Paid to whoever completes or reclaims this order — you, the counterparty, or any watchtower running unattended."),
      placeholder: LT("swAmtPh", "amount in {s}", { s: "NADO" }) })) || "").trim();
    if (typed === "") return;                          // dismissed
    const amt = (() => { try { return BigInt(nadoToRaw(typed.replace(",", "."))); } catch (e) { return 0n; } })();
    if (amt <= 0n) return alertBar(LT("tipNeed", "Enter a tip in NADO, e.g. 0.5."));
    return dapp.call("boost", [o], amt, LT("callBoost", "Boosting #{o}…", { o }), { otc: o }, { cid: OTC_CID });
  }
  if (what === "expire") return dapp.call("expire", [o], null, LT("callExpire", "Reclaiming #{o}…", { o }), { otc: o }, { cid: OTC_CID });
  if (what === "fillask") {
    // §6.3 from the TAKER's side (the contract enforces the same rule; this is the plain-language refusal).
    // ASK: the taker funds the foreign leg, so its deadline must sit safely INSIDE the NADO window.
    // BID: the taker funds the NADO leg, so the maker's foreign deadline must sit safely PAST it.
    // C3 (security review 2026-09-23): the chain clock (GENESIS + h*6) runs HOURS behind wall time and the gap
    // grows ~2.5 h/day, while the foreign deadline is a wall-clock timestamp. Judged in chain time, a BID whose
    // foreign deadline was already in the wall-clock PAST looked fine: the taker locked NADO, the maker refunded
    // the foreign leg at once and claimed the NADO with the secret. So the taker's own wall clock is the
    // authority here, and the NADO window is sized with a cadence BOUND in the direction that is unsafe for the
    // taker: the latest the NADO expiry can arrive (8 s/block) for a BID, the earliest (6 s/block) for an ASK.
    const nowS = Math.floor(Date.now() / 1000);
    const blocksLeft = Math.max(0, (od.expn - (dapp.cursor || 0)));
    const fdl = Number(od.expf) || 0;
    const okAsk = fdl > nowS + 1800 && fdl < nowS + blocksLeft * 6 * 0.75;
    const okBid = fdl > nowS + blocksLeft * 8 + 7200;
    if (od.kind === OTC_ASK ? !okAsk : !okBid) {
      return alertBar(LT("fillUnsafe",
        "This order's foreign deadline does not line up with its NADO expiry — filling it could let the maker reclaim their own lock and still take yours. Not safe to fill."));
    }
    const coin = coinOf(od);                             // the symbol the taker is paid in ("ETH", "USDC", "SOL", …)
    let myf, fref = "pending";
    const ch = chainOf(od);
    if (ch === "btc") {
      const kp = genKeypair();                          // the swap's own key; the address to fund appears on the row after the fill lands
      otcSaveRec(o, { k: kp.k, pub: kp.pub });
      myf = kp.pub;
    } else if (ch === "eth") {
      if (ethProv()) {                                  // the taker's own EVM account
        try { const { addr } = await ethConnect(); myf = addr; }
        catch (e) { return alertBar(LT("fillEthConn", "Your Ethereum wallet did not connect ({m}). Approve the connection in the wallet and click Take again.", { m: (e && e.message) || e })); }
      } else {
        // No wallet extension: ASK where the coin should go. Never silently invent a receive key —
        // a taker who did not know a key was generated for them cannot back it up, and the coin it
        // receives is only as safe as this browser's storage.
        const typed = ((await uiPrompt({ title: LT("fillWhereT", "Where should the {c} be paid?", { c: coin }),
          body: LT("fillWhereB", "Enter an {n} address you control — it receives the {a} {c} when the swap completes. Leave it empty to let this page keep a fresh key for you (you must then back it up from the row).", { n: (netOf(od) || {}).label, a: od.wamt, c: coin }),
          value: faddrGet(netKeyOf(od)) || "", placeholder: LT("fillAddrPh", "0x… address") })) || "").trim();
        if (typed && !/^0x[0-9a-fA-F]{40}$/.test(typed)) return alertBar(LT("badEthAddr", "An Ethereum address is 0x followed by 40 hex characters."));
        if (typed) { myf = typed; faddrSet(netKeyOf(od), typed); }
        else { const ek = ethKeypair(); otcSaveRec(o, { k: ek.k }); myf = ek.addr;
          // show the key NOW — the row it will later live on does not exist until the fill lands
          await uiPrompt({ title: LT("fillKeyT", "Your {c} receive key for swap #{o}", { c: coin, o }),
            body: LT("fillKeyB", "This page made a fresh Ethereum key to receive your {a} {c} at {addr}. It is stored only in this browser — copy it somewhere safe now. Later it is also under My swaps → #{o} → More → Back up this swap.", { a: od.wamt, c: coin, addr: ek.addr, o }),
            value: JSON.stringify({ order: o, address: ek.addr, key: ek.k }), confirmText: LT("fillKeySaved", "I saved it") }); }
      }
    } else if (ch === "sol" && solHas()) {
      try { myf = (await (await solMod()).solWalletConnect()).address; }   // the taker's own Solana account
      catch (e) { myf = ""; }
      if (!myf) return alertBar(LT("fillSolConn", "Connect your Solana wallet to fill this order — it is the account the swap pays."));
    } else {
      myf = faddrGet(netKeyOf(od));                    // typed once per network, then never again
      if (!myf) {
        myf = await uiPrompt({ title: LT("fillAddrT", "Your {n} address", { n: (netOf(od) || {}).label || coin }),
          body: LT("fillAddrB", "Where this swap pays you on that chain. Saved for next time."), placeholder: LT("addrPh", "address") });
        if (!myf) return;
        faddrSet(netKeyOf(od), myf);
      }
    }
    // a BID fill carries the taker bond (1% of the NADO, min 0.01) — back the moment you lock the NADO,
    // to the maker if you never do. This is what makes a fill cost something.
    const bondRaw = od.kind === OTC_BID ? (od.namtRaw * 100n / 10000n > 100000000n ? od.namtRaw * 100n / 10000n : 100000000n) : 0n;
    if (bondRaw > 0n && !await uiConfirm({ title: LT("pTake", "Take this order"),
      body: LT("bondBody", "A {b} NADO bond is held while you complete your side. It comes back in full when you lock the {n} NADO; if you never do, it goes to the maker.", { b: rawToNado(bondRaw.toString()), n: rawToNado(od.namtRaw.toString()) }),
      rows: [{ k: LT("rowBond", "Bond"), v: rawToNado(bondRaw.toString()) + " NADO" }], confirmText: LT("take", "Take") })) return;
    dapp.call("fill", [o, myf, fref], bondRaw > 0n ? bondRaw : null, LT("callFill", "Filling #{o}…", { o }), { otc: o }, { cid: OTC_CID });
    return;
  }
  if (what === "fillintra") {
    if (!await uiConfirm({ title: LT("limFillT", "Fill limit order #{o}", { o }),
      body: LT("limFillB", "Both sides swap in one transaction — no partial fills."),
      rows: [{ k: LT("youGive", "You give"), v: limText(od.wast, od.want) }, { k: LT("youGet", "You receive"), v: limText(od.gast, od.escRaw) }],
      confirmText: LT("fill", "Fill") })) return;
    dapp.call("fill_intra", [o], od.want, LT("callLimFill", "Filling limit order #{o}…", { o }), { otc: o },
              od.wast !== "0" ? { cid: OTC_CID, asset: od.wast } : { cid: OTC_CID });
    return;
  }
  if (what === "nadolock") {
    // The NADO leg of the swap: an L1 HTLC under the order's OWN SHA-256 hashlock, so the same secret
    // opens it and the foreign lock. The order-book contract never holds this money.
    const sells = od.kind === OTC_ASK;
    const owes = sells ? od.maker : od.taker;            // ASK: the maker sells NADO; BID: the taker provides it
    const to = sells ? od.taker : od.maker;
    if (dapp.me !== owes) return alertBar(LT("lkNotYours", "The NADO side of this swap is not yours to lock."));
    if (!isAddress(String(to))) return alertBar(LT("lkNoAddr", "The counterparty's NADO address isn't visible yet — wait for their fill to land."));
    const blocks = Math.max(1, od.expn - (dapp.cursor || 0));
    if (!sells && !(Number(od.expf) > Math.floor(Date.now() / 1000) + blocks * 8 + 7200)) {   // C3, at lock time
      return alertBar(LT("lkUnsafe",
        "The maker's foreign deadline no longer sits safely past this order's NADO expiry (judged by your clock, not the chain's). Locking now could let the maker reclaim their lock and still take yours."));
    }
    if (!await uiConfirm({ title: LT("lkTitle", "Lock the NADO side"),
      body: sells ? LT("lkBodyAsk", "They can only take it with the swap secret, and only before it expires — after that you reclaim it yourself.")
                  : LT("lkBodyBid", "Lock ONLY after you have checked the maker's {c} lock: the agreed amount, this order's hashlock, and a deadline past this order's NADO expiry. The maker holds the secret — if their lock is missing or short, they can take your NADO and give nothing.", { c: coinOf(od) }),
      rows: [{ k: LT("amount", "Amount"), v: rawToNado(od.namtRaw.toString()) + " NADO" },
             { k: LT("rowClaimable", "Claimable by"), v: String(to).slice(0, 16) + "…" },
             { k: LT("rowReclaimAfter", "You can reclaim after"), v: LT("nBlocks", "{n} {n|one:block|other:blocks}", { n: blocks }) }],
      confirmText: LT("lock", "Lock") })) return;
    dapp.htlcLock({ claimant: to, hashlock: od.hsha, amount: od.namtRaw, blocks }, { otc: o, phase: "htlc_lock" });
    return;
  }
  if (what === "btcsend") {                             // Bitcoin has no wallet extension to call: show where to send
    const b = btcInfo(od); if (!b) return alertBar(LT("btcDeriving", "Still deriving the Bitcoin address — try again in a second."));
    await uiPrompt({ title: LT("btcSendT", "Send exactly {a} to", { a: `${od.wamt} ${coinOf(od)}` }), body: LT("btcSendB", "From any Bitcoin wallet. The row updates itself once the coin confirms."), value: b.addr, confirmText: LT("sDone", "Done") });
    return;
  }
  if (what === "nadorefund") {                          // the L1 HTLC refund: an L1 tx signed by the wallet
    if (!od.hid) return alertBar(LT("rfNoLock", "No NADO lock is recorded on this order."));
    if (dapp.htlcRefund) return dapp.htlcRefund({ htlcId: od.hid }, { otc: o, phase: "htlc_refund" });
    return alertBar(LT("rfWallet", "Reclaim the NADO lock from your wallet's Swap tab (lock {h}…).", { h: od.hid.slice(0, 12) }));
  }
  if (what === "release") {
    if (!await uiConfirm({ title: LT("relTitle", "Release order #{o}?", { o }),
      body: LT("relBody", "The taker never locked, so their fill ends and the order goes back on the book for anyone to take."),
      rows: [{ k: LT("rowOrder", "Order"), v: terms }], confirmText: LT("relOk", "Release"), cancelText: LT("notNow", "Not now") })) return;
    return dapp.call("release", [o], null, LT("callRelease", "Releasing #{o}…", { o }), { otc: o }, { cid: OTC_CID });
  }
  if (what === "nadoclaim") {
    // The NADO leg pays out through an L1 htlc_claim, not through this contract. ASK: the taker claims once
    // the maker revealed the secret on the foreign chain. BID: the maker claims with their own secret — and
    // that reveal is what lets the taker claim the foreign leg.
    const sells = od.kind === OTC_ASK;
    if (dapp.me !== (sells ? od.taker : od.maker)) return alertBar(LT("ncNotYours", "The NADO side of this swap is not yours to claim."));
    let s = await otcKnownSecret(od);
    if (!s && sells) {
      alertBar(LT("lookup", "Looking up the revealed secret on {c}…", { c: coinOf(od) }));
      const ch = chainOf(od);
      s = ch === "btc" ? await btcFoundSecret(od) : ch === "eth" ? await ethFoundSecret(od) : ch === "sol" ? await solFoundSecret(od) : null;
    }
    if (!s) s = ((await uiPrompt({ title: LT("pasteSecret", "Paste the swap secret"),
      body: LT("pasteSecretB1", "The 64-character secret — this page could not find it on any chain yet."), placeholder: LT("hex64", "64 hex characters") })) || "").trim().toLowerCase();
    if (!/^[0-9a-f]{64}$/.test(s || "") || (await sha256Hex(s)) !== od.hsha) return alertBar(LT("secretMismatch", "That secret does not match this order's hashlock."));
    const h = await nadoHtlc(od);
    if (h && h.status !== "open") return alertBar(LT("ncAlready", "That NADO lock is already {s}.", { s: htlcStatus(h.status) }));
    if (!sells && Number(od.expf) && Math.floor(Date.now() / 1000) > Number(od.expf) - 7200)
      return alertBar(LT("ncTooLate", "Too close to your own foreign deadline — claiming now reveals the secret while the taker may no longer have time to claim your lock."));
    dapp.htlcClaim({ htlcId: od.hid, preimage: s }, { otc: o, phase: "htlc_claim" });
    return;
  }
  if (what === "nadobind") {
    const id = ((await uiPrompt({ title: LT("bindTitle", "Record your NADO lock"),
      body: LT("bindBody", "Paste the transaction id of the NADO lock you created, so the counterparty can find and check it."),
      placeholder: LT("txidPh", "transaction id") })) || "").trim();
    if (!/^[0-9a-f]{16,}$/.test(id)) return alertBar(LT("bindBad", "That doesn't look like a transaction id."));
    return dapp.call("bind", [o, id], null, LT("callBind", "Recording the NADO lock…"), { otc: o }, { cid: OTC_CID });
  }
  if (what === "btccopy") { const b = btcInfo(od); if (b) navigator.clipboard.writeText(b.addr).then(() => alertBar(LT("copied", "Address copied."))); return; }
  if (what === "btcverify") { btcVerifyInto(od, "btcv" + o); return; }
  if (what === "btcclaim") { btcSpendFlow(od, "claim"); return; }
  if (what === "btcrefund") { btcSpendFlow(od, "refund"); return; }
  if (what === "solfund") { solLeg(od, "fund"); return; }
  if (what === "solclaim") { solLeg(od, "claim"); return; }
  if (what === "solrefund") { solLeg(od, "refund"); return; }
  if (what === "ethfund") { ethLeg(od, "fund"); return; }
  if (what === "ethclaim") { ethLeg(od, "claim"); return; }
  if (what === "ethrefund") { ethLeg(od, "refund"); return; }
  if (what === "settle") {
    (async () => {
      let s = await otcKnownSecret(od);                 // own secret, published limbs, or the L1 claim
      if (!s && chainOf(od) === "btc") { alertBar(LT("lookup", "Looking up the revealed secret on {c}…", { c: "Bitcoin" })); s = await btcFoundSecret(od); }
      if (!s && chainOf(od) === "eth") { alertBar(LT("lookup", "Looking up the revealed secret on {c}…", { c: "Ethereum" })); s = await ethFoundSecret(od); }
      if (!s && chainOf(od) === "sol") { alertBar(LT("lookup", "Looking up the revealed secret on {c}…", { c: "Solana" })); s = await solFoundSecret(od); }
      if (!s) s = ((await uiPrompt({ title: LT("pasteSecret", "Paste the swap secret"),
        body: LT("pasteSecretB2", "The 64-character secret revealed when the other leg was claimed — this page could not find it automatically."),
        placeholder: LT("hex64", "64 hex characters") })) || "").trim().toLowerCase();
      if (!/^[0-9a-f]{64}$/.test(s || "")) return alertBar(LT("secretLen", "A swap secret is exactly 64 hex characters."));
      dapp.call("settle", [o, ...otcLimbs(s)], null, LT("callSettle", "Settling #{o}…", { o }), { otc: o }, { cid: OTC_CID });
    })();
  }
}

// ---- SWAP_INTRA limit orders (same otc contract, rendered beside the AMM) -----------------------------
// a token amount in its OWN decimals (raw = units of 10^-dec), NADO in NADO — never a raw integer on screen
const tokRawText = (asset, raw) => { const d = tokDec(asset), s = BigInt(raw).toString().padStart(d + 1, "0");
  const ip = s.slice(0, s.length - d), fp = d ? s.slice(s.length - d).replace(/0+$/, "") : ""; return fp ? ip + "." + fp : ip; };
const tokTextRaw = (asset, str) => { const [i, f = ""] = String(str || "").trim().replace(",", ".").split(".");
  if (!/^\d+$/.test(i || "0") || !/^\d*$/.test(f)) return 0n; const d = tokDec(asset);
  if (f.length > d) return -1n; return BigInt((i || "0") + f.padEnd(d, "0")); };
const limText = (asset, amtRaw) => asset !== "0" ? `${tokRawText(asset, amtRaw)} ${tokSym(asset)}` : `${rawToNado(amtRaw.toString())} NADO`;
const limSide = (asset, amtRaw) => asset !== "0"
  ? `<b>${tokRawText(asset, amtRaw)}</b> ${esc(tokSym(asset))}`
  : `<b>${rawToNado(amtRaw.toString())} NADO</b>`;
function limRow(od) {
  const me = dapp.me, mine = od.maker === me;
  const left = otcLeft(od), expired = left <= 0;
  const acts = [];
  if (od.st === 1 && !expired && mine) acts.push(`<button class="ghost" data-otc="cancel" data-o="${od.o}">${esc(LT("bCancel", "Cancel"))}</button>`);
  if (od.st === 1 && !expired && mine) acts.push(`<button class="ghost" data-otc="boost" data-o="${od.o}">${esc(LT("bTip", "Tip…"))}</button>`);
  if (od.st === 1 && !expired && !mine && me) acts.push(`<button class="primary" data-otc="fillintra" data-o="${od.o}">${esc(LT("fill", "Fill"))}</button>`);
  if (od.st === 1 && expired && mine) acts.push(`<button class="ghost" data-otc="expire" data-o="${od.o}">${esc(LT("reclaim", "Reclaim"))}</button>`);
  const pill = od.st === 1 ? (expired ? `<span class="pill warn">${esc(LT("stExpired", "expired"))}</span>` : `<span class="pill">${esc(LT("stOpen", "open"))}</span>`)
                           : `<span class="pill">${OTC_ST()[od.st] || od.st}</span>`;
  return `<div class="loan"><div class="loanmain">
      <div class="loantop">${pill} <b>#${od.o}</b> ${esc(disp(od.maker))} ${LT("limGives", "gives {a} for {b}", { a: limSide(od.gast, od.escRaw), b: limSide(od.wast, od.want) })}</div>
      <div class="loanterms small dim">${od.bnty > 0n ? esc(LT("rowTip", "+{n} NADO tip", { n: rawToNado(od.bnty.toString()) })) + " · " : ""}${od.st === 1 && !expired ? esc(LT("rowExpires", "expires in {n} {n|one:block|other:blocks} (~{t})", { n: left, t: blocksToTime(left) })) : ""}</div>
    </div><div class="loanacts">${acts.join("")}</div></div>`;
}
function renderLimits() {
  const box = $("otcLimits");
  if (!box) return;
  const me = dapp.me;
  const rows = otcOrders().filter((x) => x.kind === OTC_INTRA)
    .filter((x) => x.st === 1 || (me && x.maker === me && x.st !== 1))
    .sort((a, b) => (a.st - b.st) || (b.o - a.o)).slice(0, 40);
  box.innerHTML = rows.length ? rows.map(limRow).join("")
    : otcEmpty(esc(LT("limNone", "No limit orders yet — post one below.")));
  box.querySelectorAll("[data-otc]").forEach((el) => {
    el.onclick = (ev) => { ev.preventDefault();
      runAction(el.tagName === "BUTTON" ? el : null, () => otcAction(el.getAttribute("data-otc"), Number(el.getAttribute("data-o")), el)); };
  });
}
async function limPost() {
  const ga = ($("limGiveAsset").value || "0").trim() || "0";
  const wa = ($("limWantAsset").value || "0").trim() || "0";
  const blocks = Math.floor(Number($("limExpiry").value || 0));
  const amt = (v, asset) => { try { return asset !== "0" ? tokTextRaw(asset, v) : BigInt(nadoToRaw((v || "").trim())); } catch (e) { return 0n; } };
  const gv = amt($("limGiveAmt").value, ga), wv = amt($("limWantAmt").value, wa);
  if (gv < 0n || wv < 0n) return alertBar(LT("limDec", "That token counts at most {n} decimal places.", { n: tokDec(gv < 0n ? ga : wa) }));
  if (gv <= 0n || wv <= 0n) return alertBar(LT("limBoth", "Enter both amounts."));
  if (ga === "0" && wa === "0") return alertBar(LT("limNadoNado", "Pick a token on one side — NADO for NADO is not a swap."));
  if (ga === wa) return alertBar(LT("limSame", "Pick two different assets."));
  if (!(blocks >= 20 && blocks <= 900000)) return alertBar(LT("expRange", "Expiry must be between 20 blocks (≈ {a}) and 900,000 blocks (≈ {b}).", { a: blocksToTime(20), b: blocksToTime(900000) }));
  const o = randId();
  let gaB, waB; try { gaB = BigInt(ga); waB = BigInt(wa); } catch (e) { return alertBar(LT("limPick", "Pick a token from the list.")); }
  if (!await uiConfirm({ title: LT("limPostT", "Post limit order"),
    body: LT("limPostB", "Your side is escrowed now and comes back if you cancel or the order expires. The first taker swaps both sides in one go."),
    rows: [{ k: LT("youGive", "You give"), v: limText(ga, gv) }, { k: LT("youGet", "You receive"), v: limText(wa, wv) }, { k: LT("rowExpiresIn", "Expires in"), v: `≈ ${blocksToTime(blocks)}` }],
    confirmText: LT("post", "Post") })) return;
  dapp.call("post_intra", [o, gaB, gv, waB, wv, (dapp.cursor || 0) + blocks],
            gv, LT("callLimPost", "Posting limit order #{o}…", { o }), { otc: o },
            gaB !== 0n ? { cid: OTC_CID, asset: ga } : { cid: OTC_CID });
}

// ===== MARKET: live price sampling + the exchange chart (dataviz: single price series, up/down color) =====
const LS_PRICES = "nado_dex_prices";
// SHARED history: a node-side sampler publishes the pool's price series, so a first-time visitor sees the
// real chart immediately instead of an empty box that only fills while their own tab stays open. The local
// samples below still add fine-grained recent points on top.
let sharedPrices = {}, sharedTrades = {};
async function refreshSharedPrices() {
  try {
    const r = await (await fetch("/static/market/prices.json", { cache: "no-store" })).json();
    if (r && r.pools) sharedPrices = r.pools;
    if (r && r.trades) sharedTrades = r.trades;
  } catch (e) { /* sampler not running — the local series still works */ }
}
// THE LONG HISTORY (#185, operator 2026-11-11: "can you add at least some market history? last 24 hours is kinda
// weak"). The samples above are capped a market — a day, for a market that moves at every sample — so 1W and ALL drew one
// day. The node also keeps HOURLY CANDLES [hour, open, high, low, close, NADO] for the life of the chain
// (ops/dex_prices.py, static/market/history.json). INVARIANT: it is its own file, asked for every ten minutes — never
// folded into prices.json, which every open page fetches at every refresh and must not grow with the chain's age.
let sharedHistory = { tf: 3600, pools: {} }, histAt = 0;
async function refreshSharedHistory() {
  if (Date.now() - histAt < 600000) return;          // an hour closes once an hour
  histAt = Date.now();
  try {
    const r = await (await fetch("/static/market/history.json", { cache: "no-store" })).json();
    if (r && r.pools) sharedHistory = { tf: Number(r.tf) || 3600, pools: r.pools };
  } catch (e) { histAt = Date.now() - 540000; }       // none yet (a node that has not updated): asked again in a minute
}
let mktRange = 3600;                                 // seconds; 0 = all
let wantMarket = null;                               // a symbol from the URL, resolved once assets load
let curMode = "swap";
let modesRef = null;                                 // the mode switch, so a Markets row can open its venue
const symOfPool = (p) => tokSym(p.asset).toUpperCase();
function marketUrl(includeOrigin = true) {
  let q = "";
  if (curMode === "markets") return (includeOrigin ? location.origin + location.pathname : location.pathname) + "?mode=markets";
  if (curMode === "cross") return (includeOrigin ? location.origin + location.pathname : location.pathname)
    + "?market=" + encodeURIComponent((xMarket(xsel) || {}).coin || xsel) + "&mode=cross" + (xEnv === "test" ? "&net=test" : "");
  if (sel && lastSto) { const p = poolOf(lastSto, sel); const sym = symOfPool(p);
    q = "?market=" + encodeURIComponent(sym && sym !== "TOKEN" ? sym : String(p.id)); }
  if (curMode && curMode !== "swap") q += (q ? "&" : "?") + "mode=" + curMode;
  return (includeOrigin ? location.origin + location.pathname : location.pathname) + q;
}
function syncUrl(push) {
  const url = marketUrl(false);
  if (url === location.pathname + location.search) return;
  try { history[push ? "pushState" : "replaceState"]({ m: sel, mode: curMode }, "", url); } catch (e) {}
}
function readUrl() {                                 // "?market=DEMO" (symbol) or a raw pool id; legacy ?pool=
  const q = new URLSearchParams(location.search);
  if (q.get("net") === "test") setEnv("test"); else if (q.get("net") === "main") setEnv("main");
  const m = (q.get("market") || q.get("pool") || "").trim();
  if (!m) return;
  if (/^\d+$/.test(m)) sel = m; else wantMarket = m.toUpperCase();
  if (wantMarket) { const hit = xMarkets().find((m) => m.coin.toUpperCase() === wantMarket);   // a coin or token symbol names a cross-chain market
    if (hit) { xsel = hit.key; if (!hit.token) wantMarket = null; } }
}
const priceStore = () => { try { return JSON.parse(localStorage.getItem(LS_PRICES) || "{}"); } catch (e) { return {}; } };
function samplePrices(sto) {
  if (!sto) return;
  const store = priceStore(), now = Date.now();
  let changed = false;
  for (const id of poolIds(sto)) {
    const p = poolOf(sto, id);
    if (p.rn <= 0n || p.rt <= 0n || p.sup <= 0n) continue;
    const price = Number(p.rt) / Number(p.rn);         // stored in pool units (the server sampler does the same); scaled on read
    const arr = store[id] || (store[id] = []);
    const last = arr[arr.length - 1];
    if (!last || last[1] !== price || now - last[0] > 30000) {       // on a move, or a 30s heartbeat
      arr.push([now, price]); changed = true;
      if (arr.length > 2000) arr.splice(0, arr.length - 2000);
    }
  }
  if (changed) { try { localStorage.setItem(LS_PRICES, JSON.stringify(store)); } catch (e) {} }
}
const unitScale = (id) => lastSto && /^\d+$/.test(String(id)) ? pScale(poolOf(lastSto, id).asset) : 1;   // pool series: units -> the token's decimals
function priceSeriesAll(id) {                          // the merged FINE series (the samples), ignoring the range buttons
  const shared = (sharedPrices[id] || []).map((x) => [x[0] * 1000, x[1]]);
  const local = priceStore()[id] || [];
  const seen = new Set(), all = [];
  const sc = unitScale(id);
  for (const pt of shared.concat(local).sort((a, b) => a[0] - b[0])) {
    const k = Math.round(pt[0] / 1000);
    if (seen.has(k)) continue;
    seen.add(k); all.push([pt[0], pt[1] * sc]);
  }
  return all;
}
/** The hours of the long history that ended before `before` (ms): each one its closing price, at the hour's end. */
function priceHistory(id, before) {
  const tf = sharedHistory.tf * 1000, sc = unitScale(id), out = [];
  for (const c of sharedHistory.pools[id] || []) {
    const t = c[0] * 1000 + tf;
    if (t >= before) break;                            // the samples take over where they begin
    out.push([t, c[4] * sc]);
  }
  return out;
}
/** When this market's record begins (ms), 0 when there is none: the oldest hour of the history or the oldest sample. */
function seriesStart(id) {
  const h = (sharedHistory.pools[id] || [])[0], f = priceSeriesAll(id)[0];
  const t = Math.min(h ? h[0] * 1000 : Infinity, f ? f[0] : Infinity);
  return Number.isFinite(t) ? t : 0;
}
function priceSeries(id) {
  const fine = priceSeriesAll(id), cut = mktRange > 0 ? Date.now() - mktRange * 1000 : 0;
  // INVARIANT (#185): a range that reaches behind the oldest sample is drawn from the hourly history — without this
  // 1W, 1M and ALL end where the samples do, a day back on a market that moves at every sample.
  const all = !fine.length || fine[0][0] > cut ? priceHistory(id, fine.length ? fine[0][0] : Infinity).concat(fine) : fine;
  return mktRange > 0 ? all.filter((x) => x[0] >= cut) : all;
}
/** At most ~`max` points of a series for drawing: per slice of time its lowest and highest point (in time order) and
 *  both ends, so no spike is thinned away. The history grows by an hour every hour; the path the chart draws must not. */
function thinSeries(data, max = 800) {
  if (data.length <= max) return data;
  const t0 = data[0][0], span = Math.max(1, data[data.length - 1][0] - t0), nb = Math.floor(max / 2), out = [];
  let b = -1, lo = null, hi = null;
  const flush = () => { if (lo) out.push(...(lo === hi ? [lo] : lo[0] < hi[0] ? [lo, hi] : [hi, lo])); };
  for (const d of data) {
    const k = Math.min(nb - 1, Math.floor((d[0] - t0) / span * nb));
    if (k !== b) { flush(); b = k; lo = hi = d; }
    else { if (d[1] < lo[1]) lo = d; if (d[1] > hi[1]) hi = d; }
  }
  flush();
  if (out[0] !== data[0]) out.unshift(data[0]);
  if (out[out.length - 1] !== data[data.length - 1]) out.push(data[data.length - 1]);
  return out;
}
function stats24(id, priceNow) {
  const cut = Date.now() - 86400000;
  const pts = priceSeriesAll(id).filter((x) => x[0] >= cut).map((x) => x[1]);
  if (!pts.length) return null;
  const first = pts[0], hi = Math.max(...pts, priceNow || -Infinity), lo = Math.min(...pts, priceNow || Infinity);
  return { first, hi, lo, pct: first > 0 ? ((priceNow || pts[pts.length - 1]) - first) / first * 100 : 0 };
}
const group = (s) => String(s).replace(/^(-?)(\d+)/, (m, sg, d) => sg + d.replace(/\B(?=(\d{3})+(?!\d))/g, ","));
// Compact for tight cells (axis labels, stat tiles): 668.27B reads; 668,269,230,769.23 does not fit.
const fmtShort = (v) => { const a = Math.abs(v); if (!(a >= 1e5)) return fmtPrice(v);
  const u = [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]].find(([k]) => a >= k); return (v / u[0]).toFixed(2) + u[1]; };
const fmtPrice = (v) => v > 0 && v < 1e-6 ? "< 0.000001" : group(v >= 1e15 ? v.toExponential(3) : v >= 1000 ? v.toFixed(2) : v >= 1 ? v.toFixed(4) : v.toPrecision(4));
const fmtAgo = (ts) => { const s = Math.max(0, (Date.now() - ts) / 1000); return s < 90 ? LT("agoS", "{n}s ago", { n: Math.round(s) }) : s < 5400 ? LT("agoM", "{n}m ago", { n: Math.round(s / 60) }) : s < 172800 ? LT("agoH", "{n}h ago", { n: Math.round(s / 3600) }) : LT("agoD", "{n}d ago", { n: Math.round(s / 86400) }); };

// ---- the Markets tab: one table, both venues, sortable, click-through -------------------------------
const vol24 = (key) => (sharedTrades[key] || []).filter((t) => t[0] * 1000 >= Date.now() - 86400000).reduce((a, t) => a + Number(t[1] || 0), 0);
const trades24 = (key) => (sharedTrades[key] || []).filter((t) => t[0] * 1000 >= Date.now() - 86400000).length;
let mtSort = (() => { try { return JSON.parse(localStorage.getItem("nado_dex_mtsort") || "null") || { k: "liq", d: -1 }; } catch (e) { return { k: "liq", d: -1 }; } })();
const tokIni = (n) => String(n || "").split("/")[0].trim().replace(/[^A-Za-z0-9]/g, "").slice(0, 3).toUpperCase() || "?";
// the stats strip under the app bar: every market on both venues, summed
function renderTicker() {
  const el = $("dexTicker"); if (!el) return;
  let rows = [];
  try { rows = marketRows(); } catch (e) { return; }
  const live = rows.filter((r) => r.price > 0).length;
  const liq = rows.reduce((a, r) => a + (Number(r.liq) || 0), 0), vol = rows.reduce((a, r) => a + (Number(r.vol) || 0), 0);
  const f = (x) => x >= 1e6 ? (x / 1e6).toFixed(2) + "M" : x >= 1e3 ? (x / 1e3).toFixed(1) + "k" : x.toFixed(x >= 100 ? 0 : 2);
  el.innerHTML = [[LT("mtsTitle", "Markets"), `${rows.length}<small>· ${esc(LT("tkLive", "{n} live", { n: live }))}</small>`], [LT("tkLiq", "Total liquidity"), `${f(liq)}<small>NADO</small>`],
                  [LT("st24Vol", "24h volume"), `${f(vol)}<small>NADO</small>`], [LT("stFee", "Swap fee"), `0.30%<small>${esc(LT("tkToLps", "to LPs"))}</small>`]]
    .map(([l, v]) => `<div><div class="l">${esc(l)}</div><div class="v">${v}</div></div>`).join("");
  el.hidden = false;
}
// ================= THE BOARD: every market, its candles and its trades (Dexscreener-style) ====================
// "a DEX price/chart dashboard like Dexscreener" (operator, 2026-11-07). The numbers come from the exec node's trade
// index (execnode/dex_trades.py: /exec/dex_stats, /exec/dex_candles, /exec/dex_trades) — EXACT trades from the
// contract's own state, finalized blocks only, so a trade shows there ~5 minutes after it lands; the live spot (read
// from the pool every 3 s) closes the newest candle meanwhile. Before the index existed, the node's 30-s price samples
// (prices.json) are all there is: they draw price-only candles and the estimated volume, and the note says so.
// PRICES ARE NADO PER COIN everywhere on the board — the AMM used to read "tokens per NADO" while the cross-chain book
// read NADO per coin, under one "Price (NADO)" header.
const IX = { on: null, stats: {}, statsAt: 0, now: 0, candles: {}, trades: {} };
const TFS = [[60, "1m"], [300, "5m"], [900, "15m"], [3600, "1h"], [14400, "4h"], [86400, "1D"]];
let ixTf = (() => { const v = Number(lpRead("nado_dex_tf", 300)); return TFS.some(([t]) => t === v) ? v : 300; })();
async function ixGet(path) {
  const r = await fetch(base() + "/exec/" + path + (path.includes("?") ? "&" : "?") + "ns=" + dapp.ns + "&cid=" + CID, { cache: "no-store" });
  return r.ok ? r.json() : null;
}
async function ixStats() {
  if (Date.now() - IX.statsAt < 15000) return;
  IX.statsAt = Date.now();
  // an exec node without the index (older, or opted out) answers 404 or enabled:false — both read "no index here"
  try { const r = await ixGet("dex_stats"); IX.on = !!(r && r.enabled); IX.stats = (r && r.pools) || {}; IX.now = (r && r.now) || 0; } catch (e) {}
}
async function ixFetch(kind, pid, q) {               // candles / trades of one pool, cached 15 s per (pool, query)
  const key = kind + ":" + pid + ":" + q, c = IX[kind][key];
  if (c && Date.now() - c.at < 15000) return c.rows;
  IX[kind][key] = { at: Date.now(), rows: c ? c.rows : null };
  try {
    const r = await ixGet(kind === "candles" ? `dex_candles?pid=${pid}&tf=${q}&limit=300` : `dex_trades?pid=${pid}&limit=${q}`);
    IX[kind][key].rows = !r ? [] : kind === "candles" ? r.candles || [] : r.trades || [];   // never a spinner forever
  } catch (e) {}
  return IX[kind][key].rows;
}
// a coin's price from a (pn, pt) spot: NADO-units per coin-unit over the coin's scale = NADO per whole coin
const pxOf = (pn, pt, asset) => (pt ? Number(pn) / Number(pt) / pScale(asset) : 0);
const nadoPerTok = (p) => (p.rt > 0n ? Number(p.rn) / Number(p.rt) / pScale(p.asset) : 0);
const tokSupply = (asset) => { const m = tokMeta(asset); return m ? Number(m.supply || 0) / 10 ** (m.dec || 0) : 0; };
const unitsNado = (u) => Number(u) / 100;                            // contract UNITs -> NADO (display)
const unitsTok = (u, asset) => Number(u) * 1e8 / 10 ** tokDec(asset);
function ixChange(pid, w, now, asset) {                              // % over a window, from the index; null = unknown
  const s = IX.stats[String(pid)], then = s && s[w] && s[w].then;
  if (!then || !now) return null;
  const p0 = pxOf(then[0], then[1], asset);
  return p0 > 0 ? (now / p0 - 1) * 100 : null;
}
const fmtAge = (ts) => { const s = Math.max(0, Date.now() / 1000 - ts);
  return s < 3600 ? Math.max(1, Math.round(s / 60)) + LT("ageM", "m") : s < 172800 ? Math.round(s / 3600) + LT("ageH", "h") : Math.round(s / 86400) + LT("ageD", "d"); };
const shortAddr = (a) => (a ? String(a).slice(0, 6) + "…" + String(a).slice(-4) : "—");

// ---- the Markets tab: one table, both venues and the launches, sortable, click-through -------------------------
const MT_COLS = () => [
  ["name", LT("mtPair", "Pair")], ["price", LT("mtPrice", "Price (NADO)")], ["age", LT("mtAge", "Age")], ["txns", LT("mtTxns", "Txns")],
  ["vol", LT("mtVol", "Volume")], ["makers", LT("mtMakers", "Makers")], ["m5", "5M"], ["h1", "1H"], ["h6", "6H"], ["h24", "24H"],
  ["liq", LT("mtLiq", "Liquidity")], ["fdv", "FDV"],
];
function marketRows() {
  const rows = [];
  const ids = lastSto ? Object.keys(_m(lastSto, "ast") || {}) : [];
  for (const id of ids) {
    const kind = Number((_m(lastSto, "kind") || {})[id] || 0), c = curveOf(lastSto, id);
    const live = kind === 1 ? c.ct > 0n : livePool(c);
    if (!live) continue;
    const price = kind === 1 ? lpPrice(c) : nadoPerTok(c), s = IX.stats[String(id)];
    let vol = s ? unitsNado(s.h24.volume) : null, txns = s ? s.h24.buys + s.h24.sells : null, h24 = ixChange(id, "h24", price, c.asset);
    if (!s && kind !== 1) {                                         // no index yet: the samples' estimate (tokens/NADO, inverted)
      const st = stats24(c.id, midPrice(c)); h24 = st ? (1 / (1 + st.pct / 100) - 1) * 100 : null;
      vol = vol24(String(c.id)) || null; txns = trades24(String(c.id)) || null;
    }
    rows.push({ venue: kind === 1 ? "launch" : "swap", key: String(id), kind, name: `${tokSym(c.asset)} / NADO`, sub: tokName(c.asset), env: "main",
      price, age: s && s.created ? s.created : null, txns, buys: s ? s.h24.buys : null, sells: s ? s.h24.sells : null, vol,
      makers: s ? s.makers : null, m5: ixChange(id, "m5", price, c.asset), h1: ixChange(id, "h1", price, c.asset),
      h6: ixChange(id, "h6", price, c.asset), h24,
      liq: kind === 1 ? unitsNado(c.cn) : unitsNado(c.rn * 2n), fdv: price * tokSupply(c.asset) || null });
  }
  for (const m of xMarkets("main").concat(xMarkets("test"))) {
    const b = bookOf(m.key), st = stats24(XKEY(m.key), b.mid);
    const open = b.bids.concat(b.asks);
    const liq = open.reduce((a, x) => a + Number(x.od.namtRaw) / 1e10, 0);
    if (!open.length && !vol24(XKEY(m.key)) && m.token) continue;          // a token book nobody has used yet
    rows.push({ venue: "cross", key: m.key, name: `${m.coin} / NADO`, sub: m.label, env: envOf(m.net), blocked: !!xMarketBlocker(m),
      // txns are SETTLED swaps (the sampler counts each order once at SETTLED) — an open order is not a trade
      price: b.mid || 0, age: null, txns: trades24(XKEY(m.key)) || null, vol: vol24(XKEY(m.key)) || null, makers: null,
      m5: null, h1: null, h6: null, h24: st && b.mid ? st.pct : null, liq, fdv: null });
  }
  return rows;
}
const pctCell = (v) => (v == null || Number.isNaN(v) ? `<td class="dim">—</td>`
  : Math.abs(v) < 0.005 ? `<td>0.00%</td>`                                     // flat: never "-0.00%"
  : `<td class="${v > 0 ? "up" : "dn"}">${(v >= 0 ? "+" : "") + (Math.abs(v) >= 1000 ? fmtShort(v) : v.toFixed(2))}%</td>`);
function renderMarkets() {
  const head = $("mtHead"), body = $("mtBody");
  if (!head || !body || curMode !== "markets") return;
  const cols = MT_COLS();
  head.innerHTML = `<tr>${cols.map(([k, l]) => `<th data-k="${k}" class="${mtSort.k === k ? "on" : ""}" aria-sort="${mtSort.k === k ? (mtSort.d > 0 ? "ascending" : "descending") : "none"}">${esc(l)}${mtSort.k === k ? (mtSort.d > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr>`;
  head.querySelectorAll("th").forEach((th) => { th.onclick = () => {
    const k = th.dataset.k; mtSort = { k, d: mtSort.k === k ? -mtSort.d : (k === "name" ? 1 : -1) };
    try { localStorage.setItem("nado_dex_mtsort", JSON.stringify(mtSort)); } catch (e) {}
    renderMarkets(); }; });
  const q = (($("mtSearch") || {}).value || "").trim().toLowerCase();
  let rows = marketRows().filter((r) => !q || r.name.toLowerCase().includes(q) || (r.sub || "").toLowerCase().includes(q));
  const nul = (v) => v == null || Number.isNaN(v);
  rows.sort((a, b) => { const k = mtSort.k, av = k === "age" && a.age ? -a.age : a[k], bv = k === "age" && b.age ? -b.age : b[k];
    if (k === "name") return mtSort.d * String(av).localeCompare(String(bv));
    if (nul(av) && nul(bv)) return 0; if (nul(av)) return 1; if (nul(bv)) return -1;          // "—" always sinks
    return mtSort.d * (Number(av) - Number(bv)) || String(a.name).localeCompare(String(b.name)); });
  if (!lastSto && !otcSto) { body.innerHTML = `<tr><td colspan="${cols.length}" class="dim"><span class="spin"></span> ${esc(LT("mtLoading", "Loading markets…"))}</td></tr>`; return; }
  const venue = (r) => r.venue === "swap" ? (r.kind === 2 ? LT("vGrad", "graduated") : "AMM") : r.venue === "launch" ? LT("vLaunch", "launch") : r.env === "test" ? LT("vCrossTest", "cross · testnet") : LT("vCross", "cross-chain");
  const num = (v, f) => (v == null || !v ? `<td class="dim">—</td>` : `<td>${f(v)}</td>`);
  body.innerHTML = rows.length ? rows.map((r) => `<tr class="mrow" data-venue="${r.venue}" data-key="${esc(r.key)}" data-env="${r.env}" tabindex="0" role="link" aria-label="${esc(LT("mtOpen", "Open {m}", { m: r.name }))}">
      <td><span class="tok" aria-hidden="true">${esc(tokIni(r.name))}</span><span><span class="mname">${esc(r.name)}</span><span class="venue">${esc(venue(r))}</span>${r.blocked ? `<span class="venue">${esc(LT("vSoon", "soon"))}</span>` : ""}<div class="small dim" style="font-weight:400">${esc(r.sub || "")}</div></span></td>
      ${num(r.price, fmtShort)}${num(r.age, fmtAge)}
      ${r.txns ? `<td>${r.txns}${r.buys != null ? `<div class="small"><span class="up">${r.buys}</span>/<span class="dn">${r.sells}</span></div>` : ""}</td>` : `<td class="dim">—</td>`}
      ${num(r.vol, (v) => fmtShort(v))}${num(r.makers, String)}${pctCell(r.m5)}${pctCell(r.h1)}${pctCell(r.h6)}${pctCell(r.h24)}
      ${num(r.liq, (v) => fmtShort(v) + " NADO")}${num(r.fdv, (v) => fmtShort(v))}</tr>`).join("")
    : `<tr><td colspan="${cols.length}" class="dim">${esc(q ? LT("mtNoMatch", "No market matches that.") : LT("mtNone", "No markets yet."))}</td></tr>`;
  const go = (tr) => { const v = tr.dataset.venue, k = tr.dataset.key;
    if (v === "swap") sel = k; else if (v === "launch") lpSel = k; else { setEnv(tr.dataset.env); xsel = k; }
    modesRef && modesRef.set(v);                     // onChange → curMode, URL, render
    window.scrollTo({ top: 0, behavior: "smooth" }); };
  body.querySelectorAll("tr.mrow").forEach((tr) => { tr.onclick = () => go(tr); tr.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(tr); } }; });
  const note = $("mtNote");
  if (note) note.textContent = IX.on
    ? LT("mtNoteIx", "Prices are NADO per coin. Txns, volume, makers and the % changes are exact, from every trade this node indexed (finalized blocks: the newest trades appear about 5 minutes after they land). Liquidity = pool value, or NADO raised on a launch curve. FDV = price × supply.")
    : LT("mtNoteEst", "Prices are NADO per coin. This node keeps no trade index, so volume is estimated from reserve moves sampled every 30 s. Liquidity = pool value, or NADO raised on a launch curve. FDV = price × supply.");
}

// ---- candles: OHLC bodies, wicks and a volume band, crosshair + tooltip ------------------------------------------
// The index's candles (NADO-units per coin-unit) scaled to NADO per coin; the live spot closes the newest candle; with
// no index history, the 30-s samples (tokens per NADO, inverted) make price-only candles.
function candlesFor(pid, asset, spot, kind) {
  const tf = ixTf, now = Math.floor(Date.now() / 1000), sc = pScale(asset);
  const rows = IX.candles["candles:" + pid + ":" + tf];
  let cs = (rows && rows.rows || []).map((c) => [c[0], c[1] / sc, c[2] / sc, c[3] / sc, c[4] / sc, unitsNado(c[5]), c[6], c[7]]);
  if (cs.length < 2 && kind !== 1) {                                   // the samples, before the index existed
    const pts = priceSeriesAll(pid).filter((x) => x[1] > 0).map((x) => [Math.floor(x[0] / 1000), 1 / x[1]]);
    const byT = new Map();
    for (const [t, v] of pts) { const b = t - t % tf, c = byT.get(b);
      if (!c) byT.set(b, [b, v, v, v, v, 0, 0, 0]); else { c[2] = Math.max(c[2], v); c[3] = Math.min(c[3], v); c[4] = v; } }
    const sam = [...byT.values()].sort((a, b) => a[0] - b[0]);
    for (let i = 1; i < sam.length; i++) { sam[i][1] = sam[i - 1][4]; sam[i][2] = Math.max(sam[i][2], sam[i][1]); sam[i][3] = Math.min(sam[i][3], sam[i][1]); }
    if (sam.length > cs.length) cs = sam.slice(-300);
  }
  if (spot > 0) {
    const b = now - now % tf, last = cs[cs.length - 1];
    if (last && last[0] === b) { last[2] = Math.max(last[2], spot); last[3] = Math.min(last[3], spot); last[4] = spot; }
    else if (!last || Math.abs(last[4] - spot) / spot > 1e-9 || cs.length < 2) {
      const o = last ? last[4] : spot; cs.push([b, o, Math.max(o, spot), Math.min(o, spot), spot, 0, 0, 0]);
    }
  }
  return cs;
}
const _cBound = new Set();
function renderCandles(svgId, ttId, emptyId, cs) {
  const svg = $(svgId), empty = $(emptyId);
  if (!svg) return;
  svg.parentElement.classList.toggle("empty", cs.length < 2);
  if (cs.length < 2) { svg.innerHTML = ""; if (empty) { empty.classList.remove("hidden"); empty.textContent = LT("cEmpty", "No trades to chart yet — candles appear as this market trades."); } svg._cs = null; return; }
  if (empty) empty.classList.add("hidden");
  const W = CW, H = CH, VH = 34, PT = CMT, PB = H - CMB - VH - 4;           // price band, then the volume band
  let lo = Infinity, hi = -Infinity, vmax = 0;
  for (const c of cs) { lo = Math.min(lo, c[3]); hi = Math.max(hi, c[2]); vmax = Math.max(vmax, c[5]); }
  const pad = Math.max((hi - lo) * 0.08, hi * 0.005, 1e-18); lo -= pad; hi += pad;
  const n = cs.length, step = (W - CML - CMR) / n, bw = Math.max(1, Math.min(14, step * 0.7));
  const X = (i) => CML + (i + 0.5) * step, Y = (v) => PT + (1 - (v - lo) / (hi - lo || 1)) * (PB - PT);
  let g = "";
  for (let i = 0; i <= 4; i++) { const gy = PT + i / 4 * (PB - PT), gv = hi - i / 4 * (hi - lo);
    g += `<line x1="${CML}" y1="${gy.toFixed(1)}" x2="${W - CMR}" y2="${gy.toFixed(1)}" stroke="var(--border)" stroke-width="1" opacity="0.5"/>`
       + `<text x="${W - CMR + 6}" y="${(gy + 3.5).toFixed(1)}" fill="var(--faint)" font-size="10" font-family="ui-monospace,monospace">${fmtShort(gv)}</text>`; }
  let bars = "";
  cs.forEach((c, i) => {
    const up = c[4] >= c[1], col = up ? "var(--accent2)" : "var(--danger)", x = X(i);
    const y1 = Y(Math.max(c[1], c[4])), y2 = Y(Math.min(c[1], c[4]));
    bars += `<line x1="${x.toFixed(1)}" y1="${Y(c[2]).toFixed(1)}" x2="${x.toFixed(1)}" y2="${Y(c[3]).toFixed(1)}" stroke="${col}" stroke-width="1"/>`
         + `<rect x="${(x - bw / 2).toFixed(1)}" y="${y1.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1, y2 - y1).toFixed(1)}" fill="${col}"/>`;
    if (vmax > 0 && c[5] > 0) { const vh = c[5] / vmax * VH;
      bars += `<rect x="${(x - bw / 2).toFixed(1)}" y="${(H - CMB - vh).toFixed(1)}" width="${bw.toFixed(1)}" height="${vh.toFixed(1)}" fill="${col}" opacity="0.35"/>`; }
  });
  const tl = (t, a, x) => `<text x="${x}" y="${H - 6}" fill="var(--faint)" font-size="10" text-anchor="${a}" font-family="ui-monospace,monospace">${fmtAgo(t * 1000)}</text>`;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = g + bars + tl(cs[0][0], "start", CML) + tl(cs[n - 1][0], "end", W - CMR)
    + `<line class="cx" x1="0" y1="${PT}" x2="0" y2="${H - CMB}" stroke="var(--dim)" stroke-width="1" stroke-dasharray="3 3" opacity="0"/>`;
  svg._cs = { cs, X, step };
  if (_cBound.has(svgId)) return;
  _cBound.add(svgId);
  const tt = $(ttId);
  svg.addEventListener("mousemove", (e) => {
    const d = svg._cs; if (!d || !tt) return;
    const r = svg.getBoundingClientRect(), vx = (e.clientX - r.left) / r.width * CW;
    const i = Math.max(0, Math.min(d.cs.length - 1, Math.floor((vx - CML) / d.step))), c = d.cs[i], x = d.X(i);
    const cx = svg.querySelector(".cx"); if (cx) { cx.setAttribute("x1", x); cx.setAttribute("x2", x); cx.setAttribute("opacity", "1"); }
    tt.style.opacity = "1"; tt.style.left = (x / CW * r.width) + "px"; tt.style.top = "8px";
    tt.innerHTML = `O <b>${fmtPrice(c[1])}</b> H <b>${fmtPrice(c[2])}</b><br>L <b>${fmtPrice(c[3])}</b> C <b>${fmtPrice(c[4])}</b>`
      + (c[5] ? `<br>${esc(LT("cVol", "Vol {v} NADO · {b} buys / {s} sells", { v: fmtShort(c[5]), b: c[6], s: c[7] }))}` : "")
      + `<br><span style="color:var(--faint)">${fmtAgo(c[0] * 1000)}</span>`;
  });
  svg.addEventListener("mouseleave", () => { if (tt) tt.style.opacity = "0"; const cx = svg.querySelector(".cx"); if (cx) cx.setAttribute("opacity", "0"); });
}
function tfButtons(id, onPick) {
  const el = $(id); if (!el) return;
  const sig = TFS.map(([t]) => t).join() + ":" + ixTf;
  if (el.dataset.sig === sig) return;
  el.dataset.sig = sig;
  el.innerHTML = TFS.map(([t, l]) => `<button data-tf="${t}" class="${t === ixTf ? "on" : ""}" aria-pressed="${t === ixTf}">${l}</button>`).join("");
  el.querySelectorAll("button").forEach((b) => { b.onclick = () => { ixTf = Number(b.dataset.tf); lpWrite("nado_dex_tf", ixTf); onPick(); }; });
}
// ---- recent trades: the newest the index holds, with who and at what price -------------------------------------
function renderTrades(boxId, pid, asset, sym) {
  const box = $(boxId); if (!box) return;
  const rows = IX.trades["trades:" + pid + ":40"];
  const list = rows && rows.rows;
  if (IX.on === false) { box.innerHTML = `<p class="small dim">${esc(LT("tOff", "This node keeps no trade index, so it cannot list trades."))}</p>`; return; }
  if (!list) { box.innerHTML = `<p class="small dim"><span class="spin"></span></p>`; return; }
  if (!list.length) { box.innerHTML = `<p class="small dim">${esc(LT("tNone", "No trades indexed yet."))}</p>`; return; }
  const lbl = { buy: LT("tBuy", "Buy"), sell: LT("tSell", "Sell"), add: LT("tAdd", "Add"), remove: LT("tRemove", "Remove"), launch: LT("tLaunch", "Launch"), graduate: LT("tGrad", "Graduated") };
  box.innerHTML = `<div class="mtwrap"><table class="mt-table trades"><thead><tr><th>${esc(LT("tTime", "Time"))}</th><th>${esc(LT("tType", "Type"))}</th><th>${esc(LT("mtPrice", "Price (NADO)"))}</th><th>NADO</th><th>${esc(sym)}</th><th>${esc(LT("tMaker", "Maker"))}</th></tr></thead><tbody>`
    + list.map((t) => { const cl = t.side === "buy" || t.side === "add" ? "up" : t.side === "sell" || t.side === "remove" ? "dn" : "";
      return `<tr><td class="dim">${esc(fmtAgo(t.ts * 1000))}</td><td class="${cl}">${esc(lbl[t.side] || t.side)}</td><td>${t.pt ? fmtPrice(pxOf(t.pn, t.pt, asset)) : "—"}</td>
        <td>${t.nado ? fmtShort(unitsNado(t.nado)) : "—"}</td><td>${t.tokens ? fmtShort(unitsTok(t.tokens, asset)) : "—"}</td>
        <td class="dim" title="${esc(t.trader || "")}">${esc(shortAddr(t.trader))}</td></tr>`; }).join("") + `</tbody></table></div>`;
}
// the pair's chart + trades, fetched then drawn (used by the Swap tab's market card and the Launch tab's coin card)
function renderPairBoard(pid, asset, spot, kind, ids) {
  tfButtons(ids.tf, () => renderPairBoard(pid, asset, spot, kind, ids));
  const draw = () => { renderCandles(ids.svg, ids.tt, ids.empty, candlesFor(pid, asset, spot, kind)); renderTrades(ids.trades, pid, asset, tokSym(asset)); };
  draw();
  Promise.all([ixFetch("candles", pid, ixTf), ixFetch("trades", pid, 40)]).then(draw).catch(() => {});
}

function renderMarket() {
  const card = $("marketCard");
  if (!card) return;
  if (curMode === "cross") { gate({ marketCard: true }); return renderXMarket(); }
  // Land on a live market instead of an empty page: pick the deepest pool until the user chooses one.
  const ids = lastSto ? poolIds(lastSto) : [];
  if (wantMarket && lastSto) {                       // a permalink names the market by its token symbol
    const hit = ids.find((id) => symOfPool(poolOf(lastSto, id)) === wantMarket);
    if (hit) { sel = String(hit); wantMarket = null; }
    else if (Object.keys(assetReg).length) wantMarket = null;   // unknown symbol — fall through to the default
  }
  if (lastSto && (!sel || !ids.includes(String(sel)))) {
    let best = null;
    for (const id of ids) { const q = poolOf(lastSto, id); if (!best || q.rn > best.rn) best = q; }
    if (best) sel = String(best.id);
  }
  const pick = $("mktPick");
  if (pick && lastSto) {
    const opts = ids.map((id) => { const q = poolOf(lastSto, id);
      return `<option value="${q.id}">${esc(tokSym(q.asset))} / NADO — ${esc(tokName(q.asset))}</option>`; }).join("");
    if (pick.dataset.sig !== opts) { pick.dataset.sig = opts; pick.innerHTML = opts || `<option>${esc(LT("mtNone", "No markets yet."))}</option>`; }
    if (sel) pick.value = String(sel);
  }
  gate({ marketCard: !!sel });
  const mc0 = $("marketCard"); if (mc0) mc0.classList.toggle("nomarket", curMode !== "cross" && (!sel || !lastSto));   // empty state instead of a blank chart (AMM only)
  const seg = $("envSeg"); if (seg) seg.classList.add("hidden");   // the mainnet/testnet switch belongs to cross-chain markets only
  const rq0 = $("xReq"); if (rq0) rq0.classList.add("hidden");     // so does the wallet-requirement line
  if (!sel || !lastSto) return;
  const p = poolOf(lastSto, sel);
  const live = livePool(p);
  const price = live ? midPrice(p) : 0;               // tokens per NADO, in the token's own decimals ("1 NADO buys")
  const px = live ? nadoPerTok(p) : 0;                // the headline: NADO per coin, as on the board and the book
  const sym = tokSym(p.asset);
  boardFor(true);
  $("mktPair").textContent = `${sym} / NADO`;
  $("mktPrice").textContent = live ? fmtShort(px) + " NADO" : "—";
  $("mktPrice").title = live ? LT("pxTitle", "1 {s} = {p} NADO", { s: sym, p: fmtPrice(px) }) : "";
  // 24h change: exact from the trade index; before it, from the samples (tokens per NADO, so inverted)
  const st24 = live ? stats24(p.id, price) : null, ix = IX.stats[String(p.id)];
  const pct = live ? (ixChange(p.id, "h24", px, p.asset) ?? (st24 ? (1 / (1 + st24.pct / 100) - 1) * 100 : null)) : null;
  const chgEl = $("mktChg");
  if (pct != null) {
    chgEl.textContent = (pct >= 0 ? "+" : "") + pct.toFixed(2) + "%  24h";
    chgEl.className = "chg " + (Math.abs(pct) < 0.005 ? "flat" : pct > 0 ? "up" : "dn");
  } else { chgEl.textContent = LT("noTrades", "no trades yet"); chgEl.className = "chg flat"; }
  // stats
  const tvlNado = live ? fromUnits(p.rn * 2n) : "0";       // NADO-side ×2 ≈ total value in NADO
  $("mktStats").innerHTML = [
    [esc(LT("stBuys", "1 {s} buys", { s: "NADO" })), live ? fmtShort(price) + " " + esc(sym) : "—"],
    [esc(LT("stBuys", "1 {s} buys", { s: sym })), live ? fmtShort(1 / price) + " NADO" : "—"],
    [esc(LT("st24Hi", "24h high")), st24 ? fmtShort(st24.hi) : "—"],
    [esc(LT("st24Lo", "24h low")), st24 ? fmtShort(st24.lo) : "—"],
    [esc(LT("stInPool", "{s} in pool", { s: "NADO" })), group(fromUnits(p.rn))],
    [esc(LT("stInPool", "{s} in pool", { s: sym })), fmtShort(Number(tokFromUnits(p.rt, p.asset)))],
    [esc(LT("st24Vol", "24h volume")), ix ? fmtShort(unitsNado(ix.h24.volume)) + " NADO" : vol24(String(p.id)) ? "≈ " + fmtShort(vol24(String(p.id))) + " NADO" : "—"],
    [esc(LT("st24Trades", "24h trades")), ix ? `<span class="up">${ix.h24.buys}</span> / <span class="dn">${ix.h24.sells}</span>` : String(trades24(String(p.id)))],
    [esc(LT("mtMakers", "Makers")) + " 24h", ix ? String(ix.makers) : "—"],
    ["FDV", live && tokSupply(p.asset) ? fmtShort(px * tokSupply(p.asset)) + " NADO" : "—"],
    [esc(LT("pairAge", "Pair age")), ix && ix.created ? fmtAge(ix.created) : "—"],
    [esc(LT("stPoolVal", "Pool value")), "≈ " + tvlNado + " NADO"],
    [esc(LT("stLpShares", "LP shares")), p.sup.toString()],
    [esc(LT("stFee", "Swap fee")), "0.30%"],
  ].map(([l, v]) => `<div class="stat"><div class="l">${l}</div><div class="v">${v}</div></div>`).join("");
  const cap = $("depthCap"); if (cap) cap.textContent = LT("depthAmm", "How much the rate moves as your trade gets bigger:");
  const mc = $("mktCap"); if (mc) mc.textContent = IX.on
    ? LT("capIx", "Candles and trades from every trade this node indexed (finalized blocks, ~5 minutes behind); the live pool price closes the newest candle.")
    : LT("capSamples", "Price-only candles from the node's 30-s samples — this node keeps no trade index.");
  renderPairBoard(p.id, p.asset, px, p.kind, { tf: "mktTf", svg: "mktChart", tt: "mktTt", empty: "mktEmpty", trades: "mktTrades" });
  renderDepth(p, price);
  syncUrl(false);
}

// the market card serves both venues: candles, timeframes and trades for an AMM pool; the line chart and its ranges for
// the cross-chain book (whose prices are order-book mids, not trades)
function boardFor(amm) {
  const show = (id, on) => { const e = $(id); if (e) e.classList.toggle("hidden", !on); };
  show("mktTf", amm); show("mktTradesWrap", amm); show("mktRanges", !amm);
  const svg = $("mktChart"); if (svg && svg._amm !== amm) { svg._amm = amm; svg.innerHTML = ""; svg._cs = null; }
}
// --- the price line chart: SVG, crosshair + tooltip (dataviz interaction layer) ---
const CW = 600, CH = 220, CML = 6, CMR = 54, CMT = 12, CMB = 20;
let _mktBound = false, _mktPts = [], _ttSym = "token", _ttUnit = "";
function renderChart(key, sym, unit) {
  _ttSym = sym; _ttUnit = unit || "";
  const svg = $("mktChart"), empty = $("mktEmpty");
  const data = thinSeries(priceSeries(key));
  svg._cs = null;                                     // a line chart now: the candle tooltip stands down
  svg.parentElement.classList.toggle("empty", data.length < 2);
  if (data.length < 2) {
    svg.innerHTML = "";
    empty.classList.remove("hidden");
    empty.textContent = data.length ? LT("chOnePt", "One price point so far — the line draws once the pool ticks again.") : LT("chCollecting", "Collecting live prices — the chart fills in as this pool trades and time passes.");
    _mktPts = []; return;
  }
  empty.classList.add("hidden");
  const t0 = data[0][0], t1 = data[data.length - 1][0], span = Math.max(1, t1 - t0);
  let lo = Infinity, hi = -Infinity;
  for (const d of data) { lo = Math.min(lo, d[1]); hi = Math.max(hi, d[1]); }
  // Floor the range at 0.5% of the price: a series that only differs by float noise (the sampler rounds
  // to 10 digits, the browser does not) must draw flat, not as a cliff stretched to full height.
  const pad = Math.max((hi - lo) * 0.08, hi * 0.005, 1e-12); lo -= pad; hi += pad;
  const X = (t) => CML + (t - t0) / span * (CW - CML - CMR);
  const Y = (v) => CMT + (1 - (v - lo) / (hi - lo || 1)) * (CH - CMT - CMB);
  _mktPts = data.map((d) => [X(d[0]), Y(d[1]), d[0], d[1]]);
  const up = data[data.length - 1][1] >= data[0][1];
  const col = up ? "var(--accent2)" : "var(--danger)";
  const line = _mktPts.map((q, i) => (i ? "L" : "M") + q[0].toFixed(1) + " " + q[1].toFixed(1)).join(" ");
  const area = `M${_mktPts[0][0].toFixed(1)} ${(CH - CMB)} L` + _mktPts.map((q) => q[0].toFixed(1) + " " + q[1].toFixed(1)).join(" L") + ` L${_mktPts[_mktPts.length - 1][0].toFixed(1)} ${(CH - CMB)} Z`;
  // 4 horizontal grid lines + right-edge price labels
  let grid = "";
  for (let i = 0; i <= 4; i++) {
    const gy = CMT + i / 4 * (CH - CMT - CMB), gv = hi - i / 4 * (hi - lo);
    grid += `<line x1="${CML}" y1="${gy.toFixed(1)}" x2="${CW - CMR}" y2="${gy.toFixed(1)}" stroke="var(--border)" stroke-width="1" opacity="0.5"/>`;
    grid += `<text x="${CW - CMR + 6}" y="${(gy + 3.5).toFixed(1)}" fill="var(--faint)" font-size="10" font-family="ui-monospace,monospace">${fmtShort(gv)}</text>`;
  }
  const tlab = (t, anchor, x) => `<text x="${x}" y="${CH - 6}" fill="var(--faint)" font-size="10" text-anchor="${anchor}" font-family="ui-monospace,monospace">${fmtAgo(t)}</text>`;
  svg.setAttribute("viewBox", `0 0 ${CW} ${CH}`);
  svg.innerHTML =
    `<defs><linearGradient id="mgrad" x1="0" y1="0" x2="0" y2="1">
       <stop offset="0" stop-color="${up ? 'var(--accent)' : 'var(--danger)'}" stop-opacity="0.28"/>
       <stop offset="1" stop-color="${up ? 'var(--accent)' : 'var(--danger)'}" stop-opacity="0"/></linearGradient></defs>` +
    grid +
    `<path d="${area}" fill="url(#mgrad)"/><path d="${line}" fill="none" stroke="${col}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>` +
    tlab(t0, "start", CML) + tlab(t1, "end", CW - CMR) +
    `<line id="mktCross" x1="0" y1="${CMT}" x2="0" y2="${CH - CMB}" stroke="var(--dim)" stroke-width="1" stroke-dasharray="3 3" opacity="0"/>` +
    `<circle id="mktDot" r="3.5" fill="${col}" stroke="var(--elev)" stroke-width="1.5" opacity="0"/>`;
  if (!_mktBound) {
    _mktBound = true;
    const wrap = svg.parentElement, tt = $("mktTt");
    svg.addEventListener("mousemove", (e) => {
      if (!_mktPts.length || svg._cs) return;              // candles drawn here now (an AMM pool): theirs is the tooltip
      const r = svg.getBoundingClientRect(), vx = (e.clientX - r.left) / r.width * CW;
      let best = _mktPts[0]; for (const q of _mktPts) if (Math.abs(q[0] - vx) < Math.abs(best[0] - vx)) best = q;
      const cr = svg.querySelector("#mktCross"), dt = svg.querySelector("#mktDot");
      if (cr) { cr.setAttribute("x1", best[0]); cr.setAttribute("x2", best[0]); cr.setAttribute("opacity", "1"); }
      if (dt) { dt.setAttribute("cx", best[0]); dt.setAttribute("cy", best[1]); dt.setAttribute("opacity", "1"); }
      tt.style.opacity = "1";
      tt.style.left = (best[0] / CW * r.width) + "px";
      tt.style.top = (best[1] / CH * r.height) + "px";
      tt.innerHTML = `${esc(_ttUnit || "1 NADO =")} <b>${fmtPrice(best[3])}</b> ${esc(_ttSym)}<br><span style="color:var(--faint)">${fmtAgo(best[2])}</span>`;
    });
    svg.addEventListener("mouseleave", () => {
      tt.style.opacity = "0";
      const cr = svg.querySelector("#mktCross"), dt = svg.querySelector("#mktDot");
      if (cr) cr.setAttribute("opacity", "0"); if (dt) dt.setAttribute("opacity", "0");
    });
  }
}

// --- depth: execution price vs trade size, both directions (always meaningful, no history needed) ---
const DW = 600, DH = 110;
function renderDepth(p, price) {
  const svg = $("mktDepth");
  if (!(p.rn > 0n && p.rt > 0n) || !price) { svg.innerHTML = ""; return; }
  const RN = Number(p.rn), RT = Number(p.rt), F = 0.997, N = 40, maxFrac = 0.35, sc = pScale(p.asset);
  const buy = [], sell = [];                          // [sizeFrac, execPrice(TKN/NADO)] in the token's decimals
  for (let i = 1; i <= N; i++) {
    const f = i / N * maxFrac;
    const dxn = RN * f, outT = RT * (dxn * F) / (RN + dxn * F); buy.push([f, outT / dxn * sc]);
    const dxt = RT * f, outN = RN * (dxt * F) / (RT + dxt * F); sell.push([f, dxt / outN * sc]);
  }
  let lo = price, hi = price;
  for (const a of buy.concat(sell)) { lo = Math.min(lo, a[1]); hi = Math.max(hi, a[1]); }
  const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
  const midX = DW / 2, X = (f, side) => midX + side * (f / maxFrac) * (DW / 2 - 8);
  const Y = (v) => 6 + (1 - (v - lo) / (hi - lo || 1)) * (DH - 18);
  const path = (arr, side) => "M" + [[0, price]].concat(arr).map(([f, v]) => X(f, side).toFixed(1) + " " + Y(v).toFixed(1)).join(" L");
  const areaOf = (arr, side, col) => `<path d="${path(arr, side)} L${X(arr[arr.length - 1][0], side).toFixed(1)} ${DH - 12} L${midX} ${DH - 12} Z" fill="${col}" opacity="0.13"/>` +
    `<path d="${path(arr, side)}" fill="none" stroke="${col}" stroke-width="1.5"/>`;
  svg.setAttribute("viewBox", `0 0 ${DW} ${DH}`);
  svg.innerHTML =
    `<line x1="${midX}" y1="4" x2="${midX}" y2="${DH - 12}" stroke="var(--border)" stroke-width="1"/>` +
    areaOf(sell, -1, "var(--danger)") + areaOf(buy, 1, "var(--accent2)") +
    `<text x="8" y="${DH - 2}" fill="var(--danger)" font-size="9.5" font-family="ui-monospace,monospace">← ${esc(LT("dpSells", "bigger sells get a worse rate"))}</text>` +
    `<text x="${DW - 8}" y="${DH - 2}" fill="var(--accent2)" font-size="9.5" text-anchor="end" font-family="ui-monospace,monospace">${esc(LT("dpBuys", "bigger buys get a worse rate"))} →</text>`;
}


// ---- wiring / boot ---------------------------------------------------------------------------------------
let refreshing = false;
async function refresh() {
  if (refreshing) return;                                // a slow node must not stack overlapping refreshes
  refreshing = true;
  try {
    try {
      const sto = await dapp.storage();
      if (sto) lastSto = sto;
    } catch (e) { /* transient relay blip — keep the last good view rather than blanking the page */ }
    await refreshAssets();
    await refreshSharedPrices();
    await refreshSharedHistory();
    await ixStats();
    samplePrices(lastSto);
    await otcRefresh();
    render();
    renderTicker();
    swapAutopilot().catch(() => {});
    swapClaims().catch(() => {});
  } finally { refreshing = false; }
}

function wireUI() {
  dapp.walletLabels = financeLabels();   // an exchange, not a game
  wireWallet(dapp, render);
  stickyInputs(dapp, ["addN", "addT", "slip", "otcNado", "otcFAmt", "otcExpiry", "limGiveAsset", "limGiveAmt", "limWantAsset", "limWantAmt", "limExpiry"]);
  $("btnOpen").onclick = (e) => runAction(e.currentTarget, openPool);
  $("lpCreate").onclick = (e) => runAction(e.currentTarget, lpCreate);
  $("btnFundN").onclick = (e) => runAction(e.currentTarget, fundNative);
  $("btnFundT").onclick = (e) => runAction(e.currentTarget, fundToken);
  $("btnJoin").onclick = (e) => runAction(e.currentTarget, joinPool);
  $("btnRefund").onclick = (e) => runAction(e.currentTarget, refundPos);
  $("btnExit").onclick = (e) => runAction(e.currentTarget, exitPos);
  $("btnSwap").onclick = (e) => runAction(e.currentTarget, doSwap);
  const bp = $("btnOtcPost"); if (bp) bp.onclick = (e) => runAction(e.currentTarget, otcPost);
  const lp = $("btnLimPost"); if (lp) lp.onclick = (e) => runAction(e.currentTarget, limPost);
  const netSel = $("otcNet"), addrIn = $("otcFAddr");
  if (netSel) {
    // ONE control, not two: a separate "chain" dropdown said nothing the network did not already say.
    const fillNets = () => {
      const list = Object.keys(NETS).filter((k) => envOf(k) === xEnv);
      const sig = list.join(",");
      if (netSel.dataset.sig === sig) return;
      netSel.dataset.sig = sig; delete netSel.dataset.touched;
      netSel.innerHTML = list.map((k) => `<option value="${k}">${NETS[k].coin} · ${NETS[k].label}</option>`).join("");
      loadAddr();
    };
    const showTok = () => {
      const row = $("otcTokenRow"), on = netSupportsTokens(netSel.value);
      if (row) row.classList.toggle("hidden", !on);
      if (!on && $("otcToken")) $("otcToken").value = "";
    };
    const loadAddr = () => { showTok(); if (addrIn) { addrIn.value = faddrGet(netSel.value); 
      addrIn.placeholder = LT("addrSavedPh", "your {n} address (saved for next time)", { n: (NETS[netSel.value] || {}).label || "" }); } };
    netSel.onchange = () => { netSel.dataset.touched = "1"; loadAddr(); kindHint(); };
    // LIVE address feedback: the field says what it thinks as you type — empty, wrong shape for this
    // network, or valid — and Post stays disabled until it is valid. Nobody should learn their address
    // was wrong from a refused button.
    const addrHint = $("otcFAddrHint");
    async function checkAddr() {
      const v = (addrIn.value || "").trim(), n = NETS[netSel.value] || {}, ch = n.chain;
      let ok = false, msg = "";
      if (!v) msg = LT("adEnter", "Enter your {n} address — it is where this swap pays you.", { n: n.label || LT("netWord", "network") });
      else if (ch === "eth") { ok = /^0x[0-9a-fA-F]{40}$/.test(v); msg = ok ? LT("adValid", "Valid {n} address", { n: "Ethereum" }) : LT("adEthBad", "An Ethereum address is 0x followed by 40 hex characters"); }
      else if (ch === "sol") { ok = isB58Addr(v); msg = ok ? LT("adValid", "Valid {n} address", { n: "Solana" }) : LT("adSolBad", "A Solana address is 32–44 base58 characters"); }
      else if (ch === "btc") { try { await addressToScript(v, n.hrp || "bc"); ok = true; msg = LT("adValid", "Valid {n} address", { n: n.label }); } catch (e) { msg = LT("adNot", "Not a {n} address: {m}", { n: n.label, m: String(e.message || e).slice(0, 60) }); } }
      else { ok = v.length > 8; msg = ok ? "" : LT("adShort", "Address looks too short"); }
      if (addrHint) { addrHint.textContent = msg; addrHint.style.color = !v ? "var(--dim)" : ok ? "var(--accent2)" : "var(--danger)"; }
      addrIn.style.borderColor = !v ? "" : ok ? "var(--accent2)" : "var(--danger)";
      const pb = $("btnOtcPost"); if (pb && !pb.title) pb.disabled = !ok;    // a market-level block (title set) wins
      return ok;
    }
    if (addrIn) {
      addrIn.oninput = () => { checkAddr(); };
      addrIn.onchange = () => { if (addrIn.value.trim()) faddrSet(netSel.value, addrIn.value.trim()); checkAddr(); };
      netSel.addEventListener("change", () => setTimeout(checkAddr, 0));
      setTimeout(checkAddr, 0);
    }
    fillNets();
    window.addEventListener("nado-dex-env", fillNets);   // the switch above the market re-lists the networks
    const seg = $("envSeg");
    if (seg) seg.querySelectorAll("button").forEach((b) => { b.onclick = () => {
      setEnv(b.dataset.env); xsel = (xMarkets()[0] || {}).key || xsel;
      window.dispatchEvent(new Event("nado-dex-env")); syncUrl(true); render(); }; });
  }
  const amt = $("swapAmt");
  document.querySelectorAll(".pcts button[data-pct]").forEach((b) => {
    b.onclick = () => {
      if (!sel || !lastSto || !amt) return;
      const p = poolOf(lastSto, sel), d = ($("dir") || {}).value || "n2t";
      const bal = d === "n2t" ? execUnits() : tokenUnits(p.asset);
      if (bal == null) return alertBar(LT("signInBal", "Sign in to use your balance."));
      const pct = BigInt(b.getAttribute("data-pct"));
      amt.value = d === "n2t" ? fromUnits(bal * pct / 100n) : tokFromUnits(bal * pct / 100n, p.asset);
      renderSwap();
    };
  });
  const fl = $("btnFlip");
  if (fl) fl.onclick = () => { const d = $("dir"); if (!d) return;
    d.value = d.value === "n2t" ? "t2n" : "n2t"; if (amt) amt.value = ""; renderSwap(); };
  const ms = $("mtSearch"); if (ms) ms.oninput = () => renderMarkets();
  const mp = $("mktPick");
  if (mp) mp.onchange = () => { if (curMode === "cross") xsel = mp.value; else sel = mp.value; syncUrl(true); render(); };
  // the SDK sweeps every select on the page (including lists filled by a later poll); these two only
  // need their search wording set, so they are enhanced eagerly with a better placeholder
  enhanceSelect($("mktPick"), { searchPlaceholder: LT("mtSearch", "Search markets") });
  ["newAsset", "limGiveAsset", "limWantAsset", "otcTokenPick"].forEach((id) =>
    enhanceSelect($(id), { searchPlaceholder: LT("searchTok", "Search tokens by name, symbol or id") }));
  // ONE token control: pick a known token, or pick "another token" and paste it — the paste box checks
  // itself as you type, so no separate button repeats the job.
  const kindSel = $("otcKind");
  if (kindSel) kindSel.onchange = kindHint;
  kindHint();
  const tp = $("otcTokenPick"), ti = $("otcToken");
  if (tp) tp.onchange = () => {
    const other = tp.value === "?";
    if (ti) { ti.classList.toggle("hidden", !other); if (!other) ti.value = tp.value; else ti.focus(); }
    showTokenInfo();
  };
  if (ti) ti.oninput = () => {
    clearTimeout(ti._t);
    if (/^0x[0-9a-fA-F]{40}$/.test(ti.value.trim())) ti._t = setTimeout(verifyPastedToken, 350);
    else showTokenInfo();
  };
  const rb = $("mktRanges");
  if (rb) rb.querySelectorAll("button").forEach((b) => { b.onclick = () => {
    mktRange = Number(b.getAttribute("data-range"));
    rb.querySelectorAll("button").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-pressed", String(x === b)); });
    render();
  }; });
  ["swapAmt", "slip", "dir"].forEach((id) => {
    const el = $(id);
    if (el) { el.oninput = renderSwap; el.onchange = renderSwap; }
  });
  const sh = $("btnShare");
  if (sh) sh.onclick = () => {
    const url = marketUrl(true);
    const pair = sel && lastSto ? symOfPool(poolOf(lastSto, sel)) + "/NADO" : "NADO DEX";
    share(url, LT("shareText", "Trade {p} on a post-quantum chain — no listing, no admin, no rake.", { p: pair }), sh, LT("shareTitle", "{p} on NADO DEX", { p: pair }));
  };
}

dapp.onReturn((pend, ok, err) => {
  if (pend && pend.poolId != null) sel = String(pend.poolId);
  dapp.showReturn(pend, ok, err, {
    open: LT("rtOpen", "Pool opened — confirming…"),
    fundn: LT("rtFundN", "NADO deposited — confirming…"),
    fundt: LT("rtFundT", "Token deposited — confirming…"),
    join: LT("rtJoin", "Liquidity added — confirming…"),
    obuy: LT("swSent", "Swap placed in this block's batch — your coins are collected once it has passed"),
    osell: LT("swSent", "Swap placed in this block's batch — your coins are collected once it has passed"),
    exit: LT("rtExit", "Withdrawal sent — confirming…"),
    refund: LT("rtRefund", "Refund sent — confirming…"),
    post: LT("rtPost", "Order posted — confirming…"),
    post_intra: LT("rtPostIntra", "Limit order posted — confirming…"),
    fill_intra: LT("rtFillIntra", "Limit order filled — confirming…"),
    fill: LT("rtFill", "Order taken — confirming…"),
    settle: LT("rtSettle", "Settle sent — confirming…"),
    expire: LT("rtExpire", "Reclaim sent — confirming…"),
    boost: LT("rtBoost", "Tip attached — confirming…"),
    cancel: LT("rtCancel", "Cancel sent — confirming…"),
    release: LT("rtRelease", "Order released — confirming…"),
  });
  refresh();
});

async function boot() {
  try { await dapp.init(); } catch (e) {
    alertBar(LT("bootFail", "Crypto bundle failed to load — reload."));
    return;
  }
  wireUI(); loadQR();
  // blocks -> a duration a person can read, live under both expiry fields
  const human = (id, out) => { const el = $(id), o = $(out); if (!el || !o) return;
    const f = () => { const b = Math.floor(Number(el.value || 0)); o.textContent = b > 0 ? "≈ " + blocksToTime(b) : ""; };
    el.oninput = f; f(); };
  human("otcExpiry", "otcExpiryHuman"); human("limExpiry", "limExpiryHuman"); orderCards(["tradeRow", "liqCard", "poolsCard", "otcLimitCard", "openCard", "otcBookCard", "otcPostCard", "otcMyCard", "walletcard"]);
  window.addEventListener("popstate", () => { wantMarket = null; readUrl(); render(); });
  const modes = installModes(dapp, { modes: [
    { key: "markets", icon: "", label: LT("mtsTitle", "Markets"), hint: LT("modeMarketsHint", "Every pair on both venues — price, 24h change, volume, liquidity. Tap a row to trade it."),
      cards: ["marketsCard"] },
    { key: "swap", icon: "", label: LT("swTitle", "Swap"), hint: LT("modeSwapHint", "Trade NADO and tokens on the on-chain AMM — live price, depth, and pools."),
      // liqCard is the PAGE's to show (keep): a graduated launch's pool takes no liquidity, and a mode that owned the
      // card force-showed it after every render
      cards: ["marketCard", "swapCard", "poolsCard", "otcLimitCard", "openCard"], keep: ["liqCard"] },
    { key: "cross", icon: "", label: LT("modeCross", "Cross-chain"), hint: LT("modeCrossHint", "Atomic BTC / ETH / SOL ↔ NADO swaps — no custodian, no wrapped coins."),
      cards: ["marketCard", "otcBookCard", "otcPostCard", "otcMyCard"] },
    { key: "launch", icon: "", label: LT("modeLaunch", "Launch"), hint: LT("modeLaunchHint", "Launch a coin with a market from its first block — one price per batch for everyone, no platform or creator fee, liquidity nobody can pull."),
      cards: ["lpFeedCard", "lpCreateCard"], keep: ["lpCoinCard"] },   // the coin card only with a coin selected
  ], onChange: (k) => { curMode = k; syncUrl(true); render(); } });   // redraw NOW: the market card, its picker, chart and stats belong to the new mode
  modesRef = modes;
  curMode = modes.get();                                 // the SDK restores a remembered mode when the URL names none
  render = modes.wrap(doRender);
  // a language switch rewrites the data-i18n nodes at once; the strings this script writes follow on the same beat
  // instead of waiting for the next 3-s poll (the who line, the stats, the order rows, the network hint)
  window.addEventListener("nado-lang", () => { kindHint(); render(); });
  window.addEventListener("popstate", () => {
    const qm = new URLSearchParams(location.search).get("mode"), m = qm === "cross" || qm === "markets" || qm === "launch" ? qm : "swap";
    if (m !== modes.get()) modes.set(m);
  });
  readUrl();
  refresh();
  setInterval(refresh, 3000);
}
boot();
