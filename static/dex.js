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
import { htlcScript, p2wshAddress } from "./btcleg.js?v=3854b338";
import { claimTx, refundTx, addressToScript, genKeypair } from "./btcsign.js?v=15418184";
import { htlcAbi } from "./ethsign.js?v=1";
import { NadoDapp, rawToNado, nadoToRaw, _m, $, gate, wireWallet, stickyInputs, alertBar, loadQR,
         orderCards, disp, share, installModes, algHashn, base, esc, randId,
         blocksToTime } from "./nadodapp.js?v=68e91695";

const CID = "7e97163299583191d40d8676f43d5cfe";
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

let lastSto = null;
let assetReg = {};                                   // key: String(Number(id)) -> {sym, name, dec, id}
const akey = (id) => String(Number(id));
const tokMeta = (id) => assetReg[akey(id)] || null;
const tokSym = (id) => (tokMeta(id) || {}).sym || "token";
const tokName = (id) => { const m = tokMeta(id); return m ? (m.name || m.sym) : "unknown token"; };
async function refreshAssets() {
  try {
    // ?holder= returns YOUR balance per asset in the same request (doc/assets.md) — one poll, not one per token
    const q = "/exec/assets?ns=" + dapp.ns + (dapp.me ? "&holder=" + encodeURIComponent(dapp.me) : "");
    const r = await (await fetch(base() + q, { cache: "no-store" })).json();
    const map = {};
    for (const a of (r.assets || [])) map[akey(a.id)] = { sym: a.sym, name: a.name, dec: Number(a.dec) || 0,
      id: String(a.id), bal: a.balance != null ? String(a.balance) : null };
    if (Object.keys(map).length || !Object.keys(assetReg).length) assetReg = map;
  } catch (e) { /* keep the last good registry */ }
}
let sel = null;                       // selected pool id
let render = () => {};

// ---- reads (dex storage schema: ast/rn/rt/sup keyed by pool id) -------------------------------------
const poolIds = (sto) => Object.keys(_m(sto, "ast") || {});
const poolOf = (sto, id) => ({
  id: Number(id),
  asset: String((_m(sto, "ast") || {})[id] || ""),
  rn: BigInt((_m(sto, "rn") || {})[id] || 0),
  rt: BigInt((_m(sto, "rt") || {})[id] || 0),
  sup: BigInt((_m(sto, "sup") || {})[id] || 0),
});

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
const midPrice = (p) => (p.rn > 0n ? Number(p.rt) / Number(p.rn) : 0);   // display only, never minOut

// ---- rendering ---------------------------------------------------------------------------------------
function renderPools() {
  const box = $("pools");
  if (!box) return;
  const ids = lastSto ? poolIds(lastSto) : [];
  if (!ids.length) {
    box.innerHTML = `<p class="small dim">No pools yet — open one below and seed it.</p>`;
    return;
  }
  box.innerHTML = ids.map((id) => {
    const p = poolOf(lastSto, id);
    const on = String(p.id) === String(sel) ? " sel" : "";
    const sym = tokSym(p.asset), live = p.sup > 0n && p.rn > 0n;
    const price = live ? midPrice(p) : 0;
    const st = live ? stats24(p.id, price) : null;
    const chg = st ? (st.pct >= 0 ? "+" : "") + st.pct.toFixed(2) + "%" : "—";
    const cls = st ? (Math.abs(st.pct) < 0.005 ? "" : st.pct > 0 ? "up" : "dn") : "";
    return `<div class="poolrow${on}" data-pool="${p.id}" style="cursor:pointer">
      <div><b>${esc(sym)} / NADO</b><div class="small dim">${live ? fromUnits(p.rn) + " NADO liquidity" : "empty — needs liquidity"}</div></div>
      <div class="num">${live ? fmtPrice(price) + " " + esc(sym) : "—"}</div>
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
  const t = $("addT"); if (t) t.placeholder = `${sym} amount`;
  el.textContent = `You are adding to the ${sym} / NADO pool.`;
}
function renderSwap() {
  const card = $("swapCard");
  if (!card) return;
  gate({ swapCard: !!sel, liqCard: !!sel });
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
  const inU = toUnits((($("swapAmt") || {}).value || "").trim());
  const out = dir === "n2t" ? quoteOut(inU, p.rn, p.rt) : quoteOut(inU, p.rt, p.rn);
  const slipPct = Number((($("slip") || {}).value) || "1");
  // minOut = the quote reduced by the tolerance, rounded DOWN (the contract compares UNITs as integers).
  const minOut = out * BigInt(Math.max(0, Math.round((100 - slipPct) * 100))) / 10000n;
  $("quote").textContent = out > 0n
    ? `${fromUnits(out)} ${dir === "n2t" ? sym : "NADO"}   (at worst ${fromUnits(minOut)})`
    : "—";
  const amtIn = $("swapAmt"); if (amtIn) amtIn.placeholder = `amount in ${dir === "n2t" ? "NADO" : sym}`;
  card.dataset.minout = String(minOut);
  card.dataset.inunits = String(inU);
  // ticket chrome: which side is which, what you hold, the rate and what the trade itself moves the price by
  const paySym = dir === "n2t" ? "NADO" : sym, getSym = dir === "n2t" ? sym : "NADO";
  const setTxt = (id, v) => { const e = $(id); if (e) e.textContent = v; };
  setTxt("paySym", paySym); setTxt("getSym", getSym);
  const execRate = inU > 0n && out > 0n ? Number(out) / Number(inU) : (dir === "n2t" ? midPrice(p) : (midPrice(p) ? 1 / midPrice(p) : 0));
  setTxt("sumRate", execRate ? `1 ${paySym} ≈ ${fmtPrice(execRate)} ${getSym}` : "—");
  const spot = dir === "n2t" ? midPrice(p) : (midPrice(p) ? 1 / midPrice(p) : 0);
  const impact = spot > 0 && execRate > 0 ? (1 - execRate / spot) * 100 : 0;
  const imp = $("sumImpact");
  if (imp) { imp.textContent = inU > 0n && out > 0n ? impact.toFixed(2) + "%" : "—";
    imp.style.color = impact >= 5 ? "var(--danger)" : impact >= 1 ? "var(--warn)" : "var(--dim)"; }
  const qa = $("quoteAmt"); if (qa) qa.value = out > 0n ? fromUnits(out) : "";
  const payBalU = dir === "n2t" ? execUnits() : tokenUnits(p.asset);
  setTxt("payBal", payBalU === null ? "—" : "Balance " + fromUnits(payBalU) + " " + paySym);
  const getBalU = dir === "n2t" ? tokenUnits(p.asset) : execUnits();
  setTxt("getBal", getBalU === null ? "" : "Balance " + fromUnits(getBalU) + " " + getSym);
}

function fillAssetPicker(el, { withNado = true, keepValue = true } = {}) {
  if (!el) return;
  const prev = keepValue ? el.value : "";
  const toks = Object.values(assetReg);
  const opts = (withNado ? [`<option value="0">NADO</option>`] : [])
    .concat(toks.map((a) => `<option value="${a.id}">${esc(a.sym)} — ${esc(a.name || a.sym)}</option>`));
  const sig = opts.join("");
  if (el.dataset.sig === sig) { return; }
  el.dataset.sig = sig;
  el.innerHTML = opts.length ? opts.join("") : `<option value="">no tokens yet</option>`;
  if (prev && [...el.options].some((o) => o.value === prev)) el.value = prev;
}
function doRender() {
  fillAssetPicker($("newAsset"), { withNado: false });
  fillAssetPicker($("limGiveAsset"));
  fillAssetPicker($("limWantAsset"));
  renderMarket();
  renderPools();
  renderSwap();
  renderLiq();
  renderOtc();
  renderLimits();
}

// ---- actions -------------------------------------------------------------------------------------------
function openPool() {
  const asset = (($("newAsset") || {}).value || ($("newAssetCustom") || {}).value || "").trim();
  if (!asset) return alertBar("No tokens exist yet to pair with NADO.");
  let aidB; try { aidB = BigInt(asset); } catch (e) { return alertBar("That token id isn't valid."); }
  if (aidB <= 0n) return alertBar("That token id isn't valid.");
  if (lastSto) for (const id of poolIds(lastSto))                       // don't open a duplicate market
    if (akey(poolOf(lastSto, id).asset) === akey(asset)) { sel = String(id); render();
      return alertBar(`A ${tokSym(asset)} / NADO pool already exists — selected it for you.`); }
  const pid = randId();
  dapp.call("open", [pid, aidB], null, `Opening the ${tokSym(asset)} / NADO pool…`, { poolId: pid });
}

function fundNative() {
  if (!sel) return alertBar("Select a pool first.");
  const p = poolOf(lastSto, sel);
  const pos = posFor(p.id);
  const u = toUnits(($("addN").value || "").trim());
  if (u <= 0n) return alertBar("Enter a NADO amount (at least 0.01).");
  dapp.call("fundn", [pos, p.id, Number(u)], u * UNIT, "Staging NADO…", { posId: pos });
}

function fundToken() {
  if (!sel) return alertBar("Select a pool first.");
  const p = poolOf(lastSto, sel);
  const pos = posFor(p.id);
  const u = toUnits(($("addT").value || "").trim());
  if (u <= 0n) return alertBar(`Enter a ${tokSym(p.asset)} amount.`);
  // opts.asset makes this an ASSET-denominated call (value = amount, asset = which token).
  dapp.call("fundt", [pos, p.id, Number(u)], u * UNIT, "Staging token…",
            { posId: pos }, { asset: p.asset });
}

function joinPool() {
  if (!sel) return alertBar("Select a pool first.");
  const p = poolOf(lastSto, sel);
  dapp.call("join", [posFor(p.id), p.id], null, "Confirming your liquidity…", { posId: posFor(p.id) });
}

function refundPos() {
  if (!sel) return alertBar("Select a pool first.");
  const p = poolOf(lastSto, sel);
  dapp.call("refund", [posFor(p.id), p.id, BigInt(p.asset)], null, "Returning your deposits…", { posId: posFor(p.id) });
}

function exitPos() {
  if (!sel) return alertBar("Select a pool first.");
  const p = poolOf(lastSto, sel);
  const sh = Number(($("exitSh").value || "").trim());
  if (!(sh > 0)) return alertBar("Enter how much of your position to withdraw.");
  dapp.call("exit", [posFor(p.id), p.id, sh, BigInt(p.asset)], null, "Withdrawing your liquidity…", { posId: posFor(p.id) });
}

function doSwap() {
  if (!sel) return alertBar("Select a pool first.");
  const p = poolOf(lastSto, sel);
  const card = $("swapCard");
  const inU = BigInt(card.dataset.inunits || "0");
  const minOut = BigInt(card.dataset.minout || "0");
  if (inU <= 0n) return alertBar("Enter an amount to swap.");
  if (($("dir").value || "n2t") === "n2t") {
    dapp.call("swapn", [p.id, Number(inU), Number(minOut), BigInt(p.asset)], inU * UNIT,
              "Swapping…", { poolId: p.id });
  } else {
    dapp.call("swapt", [p.id, Number(inU), Number(minOut)], inU * UNIT,
              "Swapping…", { poolId: p.id }, { asset: p.asset });
  }
}


// ================= CROSS-CHAIN ORDER BOOK (otc contract — doc/dex-bridge.md §4) =========================
// Same page, DIFFERENT contract: the book is its own tiny escrow contract beside the AMM (no shared state,
// no shared upgrade surface), called through this dapp session via opts.cid. One venue, two contracts.
const OTC_CID = "6bb0bd0d5dad478bb33d254e73cde85d";
const OTC_ASK = 1, OTC_BID = 2, OTC_INTRA = 3;                       // kind: maker SELLS NADO / maker BUYS NADO
const OTC_ST = { 1: "open", 2: "filled", 3: "settled", 4: "refunded", 5: "cancelled" };
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
const otcVmParts = (sHex) => {                        // H_vm = alghash(limbs), as the two 32-bit halves post() takes
  const h = algHashn(otcLimbs(sHex).map(BigInt));
  return [Number(h >> 32n), Number(h & 0xFFFFFFFFn)];
};
async function sha256Hex(hex) {                       // H_sha — the FOREIGN chain's native hashlock of the same s
  const b = new Uint8Array(hex.match(/../g).map((x) => parseInt(x, 16)));
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", b)), (x) => x.toString(16).padStart(2, "0")).join("");
}
const otcSecrets = () => { try { return JSON.parse(localStorage.getItem(LS_OTC_SECRETS) || "{}"); } catch (e) { return {}; } };
const otcRec = (o) => { const v = otcSecrets()[o]; return typeof v === "string" ? { s: v } : (v || {}); };
const otcSaveRec = (o, patch) => { const m = otcSecrets(); const cur = typeof m[o] === "string" ? { s: m[o] } : (m[o] || {});
  m[o] = Object.assign(cur, patch); localStorage.setItem(LS_OTC_SECRETS, JSON.stringify(m)); };

// ---- the AUTOMATIC Bitcoin leg (no builder, no pubkey pasting — see btcsign.js) -----------------------
// NETWORKS: an order's `wch` names the exact NETWORK, not just the coin — so both sides build the same
// address and nobody sends mainnet coins to a testnet script. Adding a network is one row here.
const NETS = {
  btc:  { chain: "btc", coin: "BTC", label: "Bitcoin",          hrp: "bc",  explorer: "https://mempool.space" },
  btct: { chain: "btc", coin: "tBTC", label: "Bitcoin testnet", hrp: "tb",  explorer: "https://mempool.space/testnet" },
  eths: { chain: "eth", coin: "SepETH", label: "Ethereum Sepolia", evm: "0xaa36a7", htlc: "0xCd8F71E75Bb37F438c49a8011ae4037da5A8968F" },
  eth:  { chain: "eth", coin: "ETH", label: "Ethereum mainnet",  evm: "0x1",     htlc: "" },
};
const NET_BY_CHAIN = { btc: ["btc", "btct"], eth: ["eths", "eth"] };
const netOf = (od) => NETS[od.wch] || null;
const chainOf = (od) => (NETS[od.wch] || {}).chain || String(od.wch || "");
const coinOf = (od) => (NETS[od.wch] || {}).coin || String(od.wch || "").toUpperCase();
const explorerOf = (od) => (NETS[od.wch] || {}).explorer || "https://mempool.space";
// your address per NETWORK — typed once, reused forever (a swap always pays you on the same network)
const LS_FADDR = "nado_otc_faddr";
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
  el.textContent = "checking…";
  try {
    const a = await (await fetch(`${explorerOf(od)}/api/address/${b.addr}`, { cache: "no-store" })).json();
    const conf = Number(a.chain_stats.funded_txo_sum || 0), pend = Number(a.mempool_stats.funded_txo_sum || 0);
    el.innerHTML = conf > 0
      ? `<span style="color:var(--accent2)">CONFIRMED: ${conf / 1e8} BTC locked</span>${pend ? ` (+${pend / 1e8} unconfirmed)` : ""}`
      : pend > 0 ? `UNCONFIRMED: ${pend / 1e8} BTC in the mempool — wait for ≥2 confirmations`
      : "nothing sent to this address yet";
  } catch (e) { el.textContent = "explorer unreachable — try again"; }
}
async function btcSpendFlow(od, mode) {
  // ONE button: find the funded coin, ask where to send it, sign in-page, broadcast via the explorer.
  const b = btcInfo(od);
  if (!b) return alertBar("Still deriving the Bitcoin address — try again in a second.");
  let utxo;
  try { utxo = (await (await fetch(`${explorerOf(od)}/api/address/${b.addr}/utxo`, { cache: "no-store" })).json())[0]; }
  catch (e) { return alertBar("Explorer unreachable — try again."); }
  if (!utxo) return alertBar("Nothing to spend at the swap address (not funded, or already spent).");
  if (!utxo.status.confirmed && !confirm("The coin is still UNCONFIRMED. Continue anyway?")) return;
  const rec = otcRec(od.o);
  if (!rec.k) return alertBar("This browser doesn't hold the swap key for this order (use the device you posted/filled from, or scripts/otc_btc_leg.py).");
  const payout = (prompt("Your Bitcoin address — where the coins should go:") || "").trim();
  if (!payout) return;
  let outScriptHex;
  try { outScriptHex = await addressToScript(payout, (netOf(od) || {}).hrp || "bc"); } catch (e) { return alertBar(String(e.message || e)); }
  let feeRate = 10;
  try { feeRate = Math.max(1, (await (await fetch(`${explorerOf(od)}/api/v1/fees/recommended`)).json()).fastestFee); } catch (e) {}
  const feeSat = feeRate * 160;                        // ~160 vB for this 1-in/1-out P2WSH spend
  const sHex = mode === "claim" ? (od.kind === OTC_ASK ? rec.s : otcSecretFromLimbs(od.limbs)) : null;
  if (mode === "claim" && !/^[0-9a-f]{64}$/.test(sHex || "")) return alertBar("The swap secret isn't available yet.");
  try {
    const hex = mode === "claim"
      ? await claimTx({ scriptHex: b.script, secretHex: sHex, privHex: rec.k, fundTxid: utxo.txid,
                        vout: utxo.vout, amountSat: utxo.value, outScriptHex, feeSat })
      : await refundTx({ scriptHex: b.script, locktime: Math.floor(Number(od.expf)), privHex: rec.k,
                         fundTxid: utxo.txid, vout: utxo.vout, amountSat: utxo.value, outScriptHex, feeSat });
    const r = await fetch(`${explorerOf(od)}/api/tx`, { method: "POST", body: hex });
    const t = (await r.text()).trim();
    if (!r.ok) return alertBar(/non-final|non-BIP68/.test(t) ? "The Bitcoin deadline hasn't passed yet — try again after it." : "Bitcoin rejected it: " + t.slice(0, 120));
    alertBar((mode === "claim" ? "Claimed! " : "Reclaimed! ") + "Bitcoin txid: " + t.slice(0, 24) + "… — coins on the way to " + payout.slice(0, 16) + "…");
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
    if (r && r.storage) otcSto = r.storage;
  } catch (e) { /* keep the last good view */ }
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
    fref: String(g("fref", o) || ""), limbs: [0, 1, 2, 3, 4].map((i) => g("s" + i, o) || 0),
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
  if (!ethProv()) throw new Error("no Ethereum wallet in this browser (install MetaMask, or use scripts/otc_eth_leg.mjs)");
  const [addr] = await ethReq("eth_requestAccounts");
  const chain = await ethReq("eth_chainId");
  return { addr, chain };
}
function ethHtlcFor(od) { return (netOf(od) || {}).htlc || ""; }
function ethDeadline(od) { return Number(od.expf) || 0; }
// the maker's/taker's EVM address for an order rides in the same "|"-packed field the BTC pubkey uses
const ethAddrOf = (field) => { const p = (field || "").split("|").pop(); return /^0x[0-9a-fA-F]{40}$/.test(p) ? p : ""; };
async function ethLeg(od, mode) {
  // mode: fund (the ETH sender locks) · claim (reveal s, get paid) · refund (after the deadline)
  try {
    const { addr, chain } = await ethConnect();
    const net = netOf(od) || {};
    const htlc = ethHtlcFor(od);
    if (!htlc) { alertBar(`No swap contract is deployed on ${net.label || "that network"} yet — use the command shown on this row.`); return; }
    if (chain !== net.evm) { alertBar(`Switch your wallet to ${net.label} — this order is on that network.`); return; }
    const sells = od.kind === OTC_ASK;                  // ASK: taker sends ETH, maker claims
    const senderAddr = sells ? ethAddrOf(od.tadr) : ethAddrOf(od.wadr);   // who funded the lock (the refundee)
    const claimAddr = sells ? ethAddrOf(od.wadr) : ethAddrOf(od.tadr);    // who claims with the secret
    const dl = ethDeadline(od);
    const key = htlcAbi.lockKey(od.hsha, claimAddr, senderAddr, dl);
    let data, valueHex;
    if (mode === "fund") { data = htlcAbi.fund(claimAddr, od.hsha, dl); valueHex = "0x" + (BigInt(Math.round(Number(od.wamt) * 1e18))).toString(16); }
    else if (mode === "claim") {
      let sHex = sells ? otcRec(od.o).s : otcSecretFromLimbs(od.limbs);
      if (!/^[0-9a-f]{64}$/.test(sHex || "")) return alertBar("The swap secret isn't available yet.");
      data = htlcAbi.claim(key, sHex);
    } else data = htlcAbi.refund(key);
    const txid = await ethReq("eth_sendTransaction", [{ from: addr, to: htlc, data, value: valueHex }]);
    alertBar((mode === "fund" ? "ETH locked" : mode === "claim" ? "Claimed" : "Reclaimed") + " — tx " + String(txid).slice(0, 20) + "…");
  } catch (e) { alertBar(String((e && e.message) || e).slice(0, 140)); }
}
async function ethFoundSecret(od) {
  // the taker (ASK) reads s out of the maker's claim calldata on the EVM to settle the NADO side
  try {
    const htlc = ethHtlcFor(od);
    if (!htlc) return null;
    const logs = await ethReq("eth_getLogs", [{ address: htlc, fromBlock: "earliest", toBlock: "latest",
      topics: ["0x" + (await (async () => { const { keccak_256 } = await import("./vendor/noble-sha3.js?v=1");
        return Array.from(keccak_256(new TextEncoder().encode("Claimed(bytes32,bytes32)")), (x) => x.toString(16).padStart(2, "0")).join(""); })())] }]);
    for (const lg of logs) { const s = (lg.data || "").slice(-64); if (/^[0-9a-f]{64}$/.test(s) && (await sha256Hex(s)) === od.hsha) return s; }
  } catch (e) {}
  return null;
}
function ethCliHint(od) {
  const rec = otcRec(od.o);
  return `<div class="small dim mt">No browser wallet detected. Run the ETH leg from a terminal:<br>
    <span class="mono" style="word-break:break-all">node scripts/otc_eth_leg.mjs claim --rpc ${od.wch === "eths" ? "https://ethereum-sepolia-rpc.publicnode.com" : "&lt;rpc&gt;"} --htlc ${esc((netOf(od) || {}).htlc || "&lt;deploy first&gt;")} --key &lt;your-eth-key&gt; --hash ${esc(od.hsha)} --claimant &lt;addr&gt; --refundee &lt;addr&gt; --deadline ${ethDeadline(od)} --secret &lt;s&gt;</span></div>`;
}

// ---- rendering ----------------------------------------------------------------------------------------
function otcRow(od, mine) {
  const me = dapp.me, isMaker = od.maker === me, isTaker = od.taker === me;
  const sells = od.kind === OTC_ASK;
  const left = otcLeft(od), expired = left <= 0;
  const chain = esc(coinOf(od));
  const head = sells
    ? `sells <b>${rawToNado(od.namtRaw.toString())} NADO</b> for <b>${esc(od.wamt)} ${chain}</b>`
    : `buys <b>${rawToNado(od.namtRaw.toString())} NADO</b> for <b>${esc(od.wamt)} ${chain}</b>`;
  const pill = od.st === 1
    ? (expired ? '<span class="pill warn">expired</span>' : '<span class="pill">open</span>')
    : `<span class="pill${od.st === 2 ? " warn" : ""}">${OTC_ST[od.st] || od.st}</span>`;
  const party = isMaker || isTaker;
  const acts = [];
  if (od.st === 2 && !expired && party) acts.push(`<button class="primary" data-otc="settle" data-o="${od.o}">Settle…</button>`);
  if (od.st === 1 && !expired && !isMaker && me && !mine) acts.push(`<button class="primary" data-otc="fillask" data-o="${od.o}">Fill…</button>`);
  if (od.st === 1 && !expired && isMaker) acts.push(`<button class="ghost" data-otc="cancel" data-o="${od.o}">Cancel</button>`);
  if ((od.st === 1 || od.st === 2) && expired && party) acts.push(`<button class="ghost" data-otc="expire" data-o="${od.o}">Reclaim</button>`);
  if ((od.st === 1 || od.st === 2) && !expired && party) acts.push(`<button class="ghost" data-otc="boost" data-o="${od.o}">Tip</button>`);
  const isEth = chainOf(od) === "eth";
  const ethSender = isEth && (sells ? isTaker : isMaker), ethClaimer = isEth && (sells ? isMaker : isTaker);
  if (isEth && od.st === 2 && ethSender) acts.push(`<button class="primary" data-otc="ethfund" data-o="${od.o}">Lock the ETH…</button>`);
  if (isEth && ((sells && od.st === 2) || (!sells && od.st === 3)) && ethClaimer) acts.unshift(`<button class="primary" data-otc="ethclaim" data-o="${od.o}">Claim the ETH…</button>`);
  if (isEth && od.st >= 2 && ethSender && Date.now() / 1000 >= Number(od.expf)) acts.push(`<button class="ghost" data-otc="ethrefund" data-o="${od.o}">Reclaim ETH</button>`);
  const btc = chainOf(od) === "btc" ? btcInfo(od) : null;
  const btcFunder = chainOf(od) === "btc" && (sells ? isTaker : isMaker);
  const btcClaimer = chainOf(od) === "btc" && (sells ? isMaker : isTaker);
  if (btc && od.st === 2 && btcClaimer && sells && otcRec(od.o).s) acts.unshift(`<button class="primary" data-otc="btcclaim" data-o="${od.o}">Claim the BTC…</button>`);
  if (btc && od.st === 3 && btcClaimer && !sells) acts.unshift(`<button class="primary" data-otc="btcclaim" data-o="${od.o}">Claim your BTC…</button>`);
  if (btc && od.st >= 2 && btcFunder && Date.now() / 1000 >= Number(od.expf)) acts.push(`<button class="ghost" data-otc="btcrefund" data-o="${od.o}">Reclaim BTC</button>`);
  if (od.st === 1 && !expired && isMaker && od.kind !== OTC_INTRA) acts.push(`<button class="ghost" data-otc="prem" data-o="${od.o}">Deposit…</button>`);
  let detail = "";
  if (mine) {
    let hint = "";
    if (od.st === 1 && !expired && isMaker) hint = "Waiting for a taker — your funds stay reclaimable. Cancel any time.";
    else if (od.st === 2 && !expired) {
      const foreign = chain;
      if (chainOf(od) === "eth") {
        if (sells && isMaker) hint = `Next: once the taker has locked the ETH, press Claim the ETH — your wallet signs it and it completes the swap.`;
        else if (sells && isTaker) hint = `Next: press Lock the ETH (your wallet pays it into the swap). When the maker claims it, press Settle for your NADO.`;
        else if (!sells && isMaker) hint = `Next: press Lock the ETH, then Settle to collect your NADO.`;
        else hint = `Next: wait — when the maker settles, a Claim the ETH button appears here.`;
      }
      else if (sells && isMaker) hint = `Next: press Verify below — once the taker's ${foreign} lock shows CONFIRMED, press Claim the BTC. Claiming completes your side.`;
      else if (sells && isTaker) hint = `Next: send the ${foreign} to the address below. When the maker claims it, press Settle — your NADO arrives automatically.`;
      else if (!sells && isMaker) hint = `Next: send the ${foreign} to the address below, wait for confirmations, then press Settle to collect your NADO.`;
      else if (!sells && isTaker) hint = `Next: wait — when the maker collects their NADO here, a Claim your BTC button appears on this row.`;
    } else if ((od.st === 1 || od.st === 2) && expired) hint = "Expired — Reclaim returns everything to whoever put it in.";
    if (hint) detail += `<div class="small mt" style="color:var(--accent2)">${hint}</div>`;
    if (chainOf(od) === "btc" && od.st >= 2 && (isMaker || isTaker)) {
      const b = btcInfo(od);
      if (b) detail += `<div class="small mt">${btcFunder && od.st === 2 ? `<b>Send exactly ${esc(od.wamt)} BTC to:</b><br>` : `Swap address: `}<span class="mono" style="word-break:break-all">${b.addr}</span>
        <a href="#" data-otc="btccopy" data-o="${od.o}">copy</a> · <a href="#" data-otc="btcverify" data-o="${od.o}">verify</a>
        <span id="btcv${od.o}" class="dim"></span></div>`;
      else if (!btcParts(od)) detail += `<div class="small dim mt">The counterparty's client didn't publish a Bitcoin key — finish this leg with scripts/otc_btc_leg.py.</div>`;
    }
    if (chainOf(od) === "eth" && od.st >= 2 && (isMaker || isTaker) && !ethProv()) detail += ethCliHint(od);
    const secret = otcRec(od.o).s;
    if (secret && (od.st === 1 || od.st === 2))
      detail += `<div class="small dim mt">Your swap secret: <span class="mono">${secret.slice(0, 16)}…</span>
        <a href="#" data-otc="showsecret" data-o="${od.o}">back up</a> — keep a copy: it is all this swap
        needs on any device (never share it before the counterparty's lock is CONFIRMED).</div>`;
    if (od.st === 2) detail += `<div class="small dim mt">Foreign leg ref: <span class="mono">${esc(od.fref).slice(0, 40)}</span>
      · counterparty ${esc(disp(isMaker ? od.taker : od.maker))}</div>`;
    if (od.st === 3 && od.limbs.some((x) => Number(x) > 0)) {
      const rs = otcSecretFromLimbs(od.limbs);
      detail += `<div class="small mt">Revealed secret (claims the ${chain} HTLC): <span class="mono" style="word-break:break-all">${rs}</span></div>`;
    }
  }
  return `<div class="loan"><div class="loanmain">
      <div class="loantop">${pill} <b>#${od.o}</b> ${esc(disp(od.maker))} ${head}</div>
      <div class="loanterms">${od.prem > 0n ? `asks a ${rawToNado(od.prem.toString())} NADO good-faith deposit · ` : ""}${od.bnty > 0n ? `<span class="pill">+${rawToNado(od.bnty.toString())} NADO tip</span> · ` : ""}hashlock <span class="dim">${esc(od.hsha).slice(0, 18)}…</span> ·
        ${od.st <= 2 ? (expired ? "refundable now" : `expires in ${left} blocks (~${blocksToTime(left)})`) : ""}</div>
      <div class="loanwho dim small">on <b>${esc((netOf(od) || {}).label || od.wch)}</b> · ${sells ? "maker receives" : "taker receives"} ${chain} at ${esc((sells ? od.wadr : od.tadr || od.wadr).split("|")[0]) || "(swap key published)"}</div>
      ${detail}
    </div><div class="loanacts">${acts.join("")}</div></div>`;
}
function renderOtc() {
  const book = $("otcBook"), mine = $("otcMine");
  if (!book || !mine) return;
  const all = otcOrders(), me = dapp.me;
  const open = all.filter((x) => x.st === 1 && x.kind !== OTC_INTRA && otcLeft(x) > 0);
  book.innerHTML = open.length ? open.map((x) => otcRow(x, false)).join("")
    : `<p class="small dim">No open orders. Post one — the book is permissionless.</p>`;
  const my = all.filter((x) => me && x.kind !== OTC_INTRA && (x.maker === me || x.taker === me));
  mine.innerHTML = my.length ? my.map((x) => otcRow(x, true)).join("")
    : `<p class="small dim">Nothing yet — post or fill an order.</p>`;
  [book, mine].forEach((box) => box.querySelectorAll("[data-otc]").forEach((el) => {
    el.onclick = (ev) => { ev.preventDefault(); otcAction(el.getAttribute("data-otc"), Number(el.getAttribute("data-o"))); };
  }));
}

// ---- actions ------------------------------------------------------------------------------------------
async function otcPost() {
  const kind = Number($("otcKind").value);
  const raw = (() => { try { return BigInt(nadoToRaw(($("otcNado").value || "").trim())); } catch (e) { return 0n; } })();
  const net = $("otcNet").value, chain = (NETS[net] || {}).chain, famt = ($("otcFAmt").value || "").trim(), faddr = ($("otcFAddr").value || "").trim();
  const blocks = Math.floor(Number($("otcExpiry").value || 0));
  if (raw <= 0n) return alertBar("Enter the NADO amount.");
  if (!famt || !(Number(famt) > 0)) return alertBar("Enter the foreign amount.");
  if (!faddr) return alertBar("Enter your " + (NETS[net] || {}).label + " address.");
  faddrSet(net, faddr);                                // typed once — reused for every future swap on this network
  if (!(blocks >= 20 && blocks <= 900000)) return alertBar("Expiry must be 20 … 900000 blocks.");
  const o = randId();
  const sHex = Array.from(crypto.getRandomValues(new Uint8Array(32)), (x) => x.toString(16).padStart(2, "0")).join("");
  let kp = null, packed = faddr;
  if (chain === "btc") { kp = genKeypair(); packed = faddr + "|" + kp.pub; }
  else if (chain === "eth") { const ek = ethProv() ? null : (await import("./ethsign.js?v=1")).ethKeypair();
    // with a wallet the maker's own EVM address is used at claim time; without one, a page key is generated for the CLI
    if (ek) { kp = { k: ek.k }; packed = faddr + "|" + ek.addr; } }
  otcSaveRec(o, Object.assign({ s: sHex }, kp || {})); // BEFORE the wallet redirect can navigate away
  const hsha = await sha256Hex(sHex);
  const [hi, lo] = otcVmParts(sHex);
  // expf: the FOREIGN leg's deadline both parties sign. Advisory to the VM (it cannot read that chain);
  // the wallet suggests ~60% of the NADO window in unix seconds so the foreign refund opens first (§6.3).
  const expf = Math.floor(Date.now() / 1000 + blocks * 6 * 0.6);
  const expn = (dapp.cursor || 0) + blocks;
  const box = $("otcSecretBox"); if (box) { box.classList.remove("hidden"); $("otcSecretHex").textContent = sHex + (kp ? "  ·  BTC key: " + kp.k : ""); }
  dapp.call("post", [o, kind, raw, net, famt, packed, hsha, hi, lo, expn, expf],
            kind === OTC_ASK ? raw : null, "Posting order #" + o + "…", { otc: o }, { cid: OTC_CID });
}
async function otcAction(what, o) {
  const od = otcOrders().find((x) => x.o === o);
  if (!od) return;
  if (what === "showsecret") {
    const r = otcRec(o);
    const parts = [r.s ? "secret: " + r.s : "", r.k ? "btc-key: " + r.k : ""].filter(Boolean).join("   ");
    if (parts) prompt("Backup for swap #" + o + " — copy it somewhere safe (it is ALL this swap needs on any device):", parts);
    return;
  }
  if (what === "cancel") return dapp.call("cancel", [o], null, "Cancelling #" + o + "…", { otc: o }, { cid: OTC_CID });
  if (what === "prem") {
    const raw = (prompt("Good-faith deposit the taker must escrow (in NADO). Returned to them on completion; forfeited to you if they walk away. Enter 0 to remove it:") || "").trim();
    let amt;
    try { amt = raw === "0" ? 0n : BigInt(nadoToRaw(raw)); } catch (e) { return; }
    if (amt == null || amt < 0n) return;
    return dapp.call("set_premium", [o, amt], null, "Setting deposit on #" + o + "…", { otc: o }, { cid: OTC_CID });
  }
  if (what === "boost") {
    // §8: attach a NADO bounty ANYONE can win by finishing this order (settle / expire / atomic fill).
    // It makes watchtowers work for you; cancel returns it to the maker.
    const amt = (() => { try { return BigInt(nadoToRaw((prompt("Tip in NADO — it pays whoever finishes or reclaims this swap for you (you, or any watchtower). Attach:") || "").trim())); } catch (e) { return 0n; } })();
    if (amt <= 0n) return;
    return dapp.call("boost", [o], amt, "Boosting #" + o + "…", { otc: o }, { cid: OTC_CID });
  }
  if (what === "expire") return dapp.call("expire", [o], null, "Reclaiming #" + o + "…", { otc: o }, { cid: OTC_CID });
  if (what === "fillask") {
    const chain = od.wch.toUpperCase();
    let myf, fref = "auto";
    if (od.wch === "btc") {
      const kp = genKeypair();                          // the swap's own key; the address to fund appears on the row after the fill lands
      otcSaveRec(o, { k: kp.k, pub: kp.pub });
      myf = kp.pub;
    } else if (od.wch === "eth") {
      if (ethProv()) { const { addr } = await ethConnect(); myf = addr; }   // the taker's own EVM account
      else { const ek = (await import("./ethsign.js?v=1")).ethKeypair(); otcSaveRec(o, { k: ek.k }); myf = ek.addr; }
    } else {
      myf = faddrGet(od.wch);                          // typed once per network, then never again
      if (!myf) {
        myf = prompt(`Your ${(netOf(od) || {}).label || chain} address (saved for next time):`);
        if (!myf) return;
        faddrSet(od.wch, myf);
      }
    }
    if (od.prem > 0n && !confirm(`This order asks a good-faith deposit of ${rawToNado(od.prem.toString())} NADO on top of the trade. It is returned to you when the swap completes — forfeited to the maker only if you walk away. Continue?`)) return;
    const total = (od.kind === OTC_BID ? od.namtRaw : 0n) + od.prem;
    dapp.call("fill", [o, myf, fref], total > 0n ? total : null,
              "Filling #" + o + "…", { otc: o }, { cid: OTC_CID });
    return;
  }
  if (what === "fillintra") {
    dapp.call("fill_intra", [o], od.want, "Filling limit order #" + o + "…", { otc: o },
              od.wast !== "0" ? { cid: OTC_CID, asset: od.wast } : { cid: OTC_CID });
    return;
  }
  if (what === "btccopy") { const b = btcInfo(od); if (b) navigator.clipboard.writeText(b.addr).then(() => alertBar("Address copied.")); return; }
  if (what === "btcverify") { btcVerifyInto(od, "btcv" + o); return; }
  if (what === "btcclaim") { btcSpendFlow(od, "claim"); return; }
  if (what === "btcrefund") { btcSpendFlow(od, "refund"); return; }
  if (what === "ethfund") { ethLeg(od, "fund"); return; }
  if (what === "ethclaim") { ethLeg(od, "claim"); return; }
  if (what === "ethrefund") { ethLeg(od, "refund"); return; }
  if (what === "settle") {
    (async () => {
      let s = otcRec(o).s;                              // a maker settles with their own stored secret
      if (!s && chainOf(od) === "btc") { alertBar("Looking up the revealed secret on Bitcoin…"); s = await btcFoundSecret(od); }
      if (!s && chainOf(od) === "eth") { alertBar("Looking up the revealed secret on Ethereum…"); s = await ethFoundSecret(od); }
      if (!s) s = (prompt("Paste the revealed 64-hex swap secret (from the foreign-chain claim):") || "").trim().toLowerCase();
      if (!/^[0-9a-f]{64}$/.test(s || "")) return alertBar("That is not a 32-byte hex secret.");
      dapp.call("settle", [o, ...otcLimbs(s)], null, "Settling #" + o + "…", { otc: o }, { cid: OTC_CID });
    })();
  }
}

// ---- SWAP_INTRA limit orders (same otc contract, rendered beside the AMM) -----------------------------
const limSide = (asset, amtRaw) => asset !== "0"
  ? `<b>${amtRaw}</b> ${esc(tokSym(asset))}`
  : `<b>${rawToNado(amtRaw.toString())} NADO</b>`;
function limRow(od) {
  const me = dapp.me, mine = od.maker === me;
  const left = otcLeft(od), expired = left <= 0;
  const acts = [];
  if (od.st === 1 && !expired && mine) acts.push(`<button class="ghost" data-otc="cancel" data-o="${od.o}">Cancel</button>`);
  if (od.st === 1 && !expired && mine) acts.push(`<button class="ghost" data-otc="boost" data-o="${od.o}">Tip</button>`);
  if (od.st === 1 && !expired && !mine && me) acts.push(`<button class="primary" data-otc="fillintra" data-o="${od.o}">Fill</button>`);
  if (od.st === 1 && expired && mine) acts.push(`<button class="ghost" data-otc="expire" data-o="${od.o}">Reclaim</button>`);
  const pill = od.st === 1 ? (expired ? '<span class="pill warn">expired</span>' : '<span class="pill">open</span>')
                           : `<span class="pill">${OTC_ST[od.st] || od.st}</span>`;
  return `<div class="loan"><div class="loanmain">
      <div class="loantop">${pill} <b>#${od.o}</b> ${esc(disp(od.maker))} gives ${limSide(od.gast, od.escRaw)}
        for ${limSide(od.wast, od.want)}</div>
      <div class="loanterms small dim">${od.bnty > 0n ? `+${rawToNado(od.bnty.toString())} NADO bounty · ` : ""}${od.st === 1 && !expired ? `expires in ${left} blocks (~${blocksToTime(left)})` : ""}</div>
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
    : `<p class="small dim">No limit orders yet — post one below.</p>`;
  box.querySelectorAll("[data-otc]").forEach((el) => {
    el.onclick = (ev) => { ev.preventDefault(); otcAction(el.getAttribute("data-otc"), Number(el.getAttribute("data-o"))); };
  });
}
function limPost() {
  const ga = ($("limGiveAsset").value || "0").trim() || "0";
  const wa = ($("limWantAsset").value || "0").trim() || "0";
  const blocks = Math.floor(Number($("limExpiry").value || 0));
  const amt = (v, asset) => { try { return asset !== "0" ? BigInt((v || "").trim()) : BigInt(nadoToRaw((v || "").trim())); } catch (e) { return 0n; } };
  const gv = amt($("limGiveAmt").value, ga), wv = amt($("limWantAmt").value, wa);
  if (gv <= 0n || wv <= 0n) return alertBar("Enter both amounts.");
  if (ga === "0" && wa === "0") return alertBar("Pick a token on one side — NADO for NADO is not a swap.");
  if (!(blocks >= 20 && blocks <= 900000)) return alertBar("Expiry must be 20 … 900000 blocks.");
  const o = randId();
  let gaB, waB; try { gaB = BigInt(ga); waB = BigInt(wa); } catch (e) { return alertBar("Asset ids must be numbers."); }
  dapp.call("post_intra", [o, gaB, gv, waB, wv, (dapp.cursor || 0) + blocks],
            gv, "Posting limit order #" + o + "…", { otc: o },
            gaB !== 0n ? { cid: OTC_CID, asset: ga } : { cid: OTC_CID });
}

// ===== MARKET: live price sampling + the exchange chart (dataviz: single price series, up/down color) =====
const LS_PRICES = "nado_dex_prices";
// SHARED history: a node-side sampler publishes the pool's price series, so a first-time visitor sees the
// real chart immediately instead of an empty box that only fills while their own tab stays open. The local
// samples below still add fine-grained recent points on top.
let sharedPrices = {};
async function refreshSharedPrices() {
  try {
    const r = await (await fetch("/static/market/prices.json", { cache: "no-store" })).json();
    if (r && r.pools) sharedPrices = r.pools;
  } catch (e) { /* sampler not running — the local series still works */ }
}
let mktRange = 3600;                                 // seconds; 0 = all
let wantMarket = null;                               // a symbol from the URL, resolved once assets load
let curMode = "swap";
const symOfPool = (p) => tokSym(p.asset).toUpperCase();
function marketUrl(includeOrigin = true) {
  let q = "";
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
  const m = (q.get("market") || q.get("pool") || "").trim();
  if (!m) return;
  if (/^\d+$/.test(m)) sel = m; else wantMarket = m.toUpperCase();
}
const priceStore = () => { try { return JSON.parse(localStorage.getItem(LS_PRICES) || "{}"); } catch (e) { return {}; } };
function samplePrices(sto) {
  if (!sto) return;
  const store = priceStore(), now = Date.now();
  let changed = false;
  for (const id of poolIds(sto)) {
    const p = poolOf(sto, id);
    if (p.rn <= 0n || p.rt <= 0n || p.sup <= 0n) continue;
    const price = Number(p.rt) / Number(p.rn);
    const arr = store[id] || (store[id] = []);
    const last = arr[arr.length - 1];
    if (!last || last[1] !== price || now - last[0] > 30000) {       // on a move, or a 30s heartbeat
      arr.push([now, price]); changed = true;
      if (arr.length > 2000) arr.splice(0, arr.length - 2000);
    }
  }
  if (changed) { try { localStorage.setItem(LS_PRICES, JSON.stringify(store)); } catch (e) {} }
}
function priceSeriesAll(id) {                          // the merged series, ignoring the range buttons
  const shared = (sharedPrices[id] || []).map((x) => [x[0] * 1000, x[1]]);
  const local = priceStore()[id] || [];
  const seen = new Set(), all = [];
  for (const pt of shared.concat(local).sort((a, b) => a[0] - b[0])) {
    const k = Math.round(pt[0] / 1000);
    if (seen.has(k)) continue;
    seen.add(k); all.push(pt);
  }
  return all;
}
function priceSeries(id) {
  const all = priceSeriesAll(id);
  return mktRange > 0 ? all.filter((x) => x[0] >= Date.now() - mktRange * 1000) : all;
}
function stats24(id, priceNow) {
  const cut = Date.now() - 86400000;
  const pts = priceSeriesAll(id).filter((x) => x[0] >= cut).map((x) => x[1]);
  if (!pts.length) return null;
  const first = pts[0], hi = Math.max(...pts, priceNow || -Infinity), lo = Math.min(...pts, priceNow || Infinity);
  return { first, hi, lo, pct: first > 0 ? ((priceNow || pts[pts.length - 1]) - first) / first * 100 : 0 };
}
const fmtPrice = (v) => v >= 1000 ? v.toFixed(2) : v >= 1 ? v.toFixed(4) : v.toPrecision(4);
const fmtAgo = (ts) => { const s = Math.max(0, (Date.now() - ts) / 1000); return s < 90 ? Math.round(s) + "s ago" : s < 5400 ? Math.round(s / 60) + "m ago" : s < 172800 ? Math.round(s / 3600) + "h ago" : Math.round(s / 86400) + "d ago"; };

function renderMarket() {
  const card = $("marketCard");
  if (!card) return;
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
    const opts = ids.map((id) => { const q = poolOf(lastSto, id); return `<option value="${q.id}">${esc(tokSym(q.asset))} / NADO</option>`; }).join("");
    if (pick.dataset.sig !== opts) { pick.dataset.sig = opts; pick.innerHTML = opts || `<option>no markets yet</option>`; }
    if (sel) pick.value = String(sel);
  }
  gate({ marketCard: !!sel });
  if (!sel || !lastSto) return;
  const p = poolOf(lastSto, sel);
  const live = p.rn > 0n && p.rt > 0n && p.sup > 0n;
  const price = live ? Number(p.rt) / Number(p.rn) : 0;
  const sym = tokSym(p.asset);
  $("mktPair").textContent = `${sym} / NADO`;
  $("mktPrice").textContent = live ? fmtPrice(price) : "—";
  // 24h change (or first point in range) from the observed series
  const st24 = live ? stats24(p.id, price) : null;
  const chgEl = $("mktChg");
  if (st24) {
    const pct = st24.pct;
    chgEl.textContent = (pct >= 0 ? "+" : "") + pct.toFixed(2) + "%  24h";
    chgEl.className = "chg " + (Math.abs(pct) < 0.005 ? "flat" : pct > 0 ? "up" : "dn");
  } else { chgEl.textContent = "no trades yet"; chgEl.className = "chg flat"; }
  // stats
  const tvlNado = live ? fromUnits(p.rn * 2n) : "0";       // NADO-side ×2 ≈ total value in NADO
  $("mktStats").innerHTML = [
    ["1 NADO buys", live ? fmtPrice(price) + " " + sym : "—"],
    [`1 ${sym} buys`, live ? fmtPrice(1 / price) + " NADO" : "—"],
    ["24h high", st24 ? fmtPrice(st24.hi) : "—"],
    ["24h low", st24 ? fmtPrice(st24.lo) : "—"],
    ["NADO in pool", fromUnits(p.rn)],
    [sym + " in pool", fromUnits(p.rt)],
    ["Pool value", "≈ " + tvlNado + " NADO"],
    ["LP shares", p.sup.toString()],
    ["Swap fee", "0.30%"],
  ].map(([l, v]) => `<div class="stat"><div class="l">${l}</div><div class="v">${v}</div></div>`).join("");
  renderChart(p);
  renderDepth(p, price);
  syncUrl(false);
}

// --- the price line chart: SVG, crosshair + tooltip (dataviz interaction layer) ---
const CW = 600, CH = 220, CML = 6, CMR = 54, CMT = 12, CMB = 20;
let _mktBound = false, _mktPts = [], _ttSym = "token";
function renderChart(p) {
  _ttSym = tokSym(p.asset);
  const svg = $("mktChart"), empty = $("mktEmpty");
  const data = priceSeries(p.id);
  if (data.length < 2) {
    svg.innerHTML = "";
    empty.classList.remove("hidden");
    empty.textContent = data.length ? "One price point so far — the line draws once the pool ticks again." : "Collecting live prices — the chart fills in as this pool trades and time passes.";
    _mktPts = []; return;
  }
  empty.classList.add("hidden");
  const t0 = data[0][0], t1 = data[data.length - 1][0], span = Math.max(1, t1 - t0);
  let lo = Infinity, hi = -Infinity;
  for (const d of data) { lo = Math.min(lo, d[1]); hi = Math.max(hi, d[1]); }
  const pad = (hi - lo) * 0.08 || hi * 0.02 || 1; lo -= pad; hi += pad;
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
    grid += `<text x="${CW - CMR + 6}" y="${(gy + 3.5).toFixed(1)}" fill="var(--faint)" font-size="10" font-family="ui-monospace,monospace">${fmtPrice(gv)}</text>`;
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
      if (!_mktPts.length) return;
      const r = svg.getBoundingClientRect(), vx = (e.clientX - r.left) / r.width * CW;
      let best = _mktPts[0]; for (const q of _mktPts) if (Math.abs(q[0] - vx) < Math.abs(best[0] - vx)) best = q;
      const cr = svg.querySelector("#mktCross"), dt = svg.querySelector("#mktDot");
      if (cr) { cr.setAttribute("x1", best[0]); cr.setAttribute("x2", best[0]); cr.setAttribute("opacity", "1"); }
      if (dt) { dt.setAttribute("cx", best[0]); dt.setAttribute("cy", best[1]); dt.setAttribute("opacity", "1"); }
      tt.style.opacity = "1";
      tt.style.left = (best[0] / CW * r.width) + "px";
      tt.style.top = (best[1] / CH * r.height) + "px";
      tt.innerHTML = `1 NADO = <b>${fmtPrice(best[3])}</b> ${_ttSym}<br><span style="color:var(--faint)">${fmtAgo(best[2])}</span>`;
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
  const RN = Number(p.rn), RT = Number(p.rt), F = 0.997, N = 40, maxFrac = 0.35;
  const buy = [], sell = [];                          // [sizeFrac, execPrice(TKN/NADO)]
  for (let i = 1; i <= N; i++) {
    const f = i / N * maxFrac;
    const dxn = RN * f, outT = RT * (dxn * F) / (RN + dxn * F); buy.push([f, outT / dxn]);
    const dxt = RT * f, outN = RN * (dxt * F) / (RT + dxt * F); sell.push([f, dxt / outN]);
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
    `<text x="8" y="${DH - 2}" fill="var(--danger)" font-size="9.5" font-family="ui-monospace,monospace">← bigger sells get a worse rate</text>` +
    `<text x="${DW - 8}" y="${DH - 2}" fill="var(--accent2)" font-size="9.5" text-anchor="end" font-family="ui-monospace,monospace">bigger buys get a worse rate →</text>`;
}

// ---- wiring / boot ---------------------------------------------------------------------------------------
async function refresh() {
  try {
    const sto = await dapp.storage();
    if (sto) lastSto = sto;
  } catch (e) { /* transient relay blip — keep the last good view rather than blanking the page */ }
  await refreshAssets();
  await refreshSharedPrices();
  samplePrices(lastSto);
  await otcRefresh();
  render();
}

function wireUI() {
  wireWallet(dapp, render);
  stickyInputs(dapp, ["addN", "addT", "slip", "otcNado", "otcFAmt", "otcExpiry", "limGiveAsset", "limGiveAmt", "limWantAsset", "limWantAmt", "limExpiry"]);
  $("btnOpen").onclick = openPool;
  $("btnFundN").onclick = fundNative;
  $("btnFundT").onclick = fundToken;
  $("btnJoin").onclick = joinPool;
  $("btnRefund").onclick = refundPos;
  $("btnExit").onclick = exitPos;
  $("btnSwap").onclick = doSwap;
  const bp = $("btnOtcPost"); if (bp) bp.onclick = otcPost;
  const lp = $("btnLimPost"); if (lp) lp.onclick = limPost;
  const chainSel = $("otcChain"), netSel = $("otcNet"), addrIn = $("otcFAddr");
  if (chainSel && netSel) {
    const fillNets = () => {
      const keys = NET_BY_CHAIN[chainSel.value] || [];
      netSel.innerHTML = keys.map((k) => `<option value="${k}">${NETS[k].label}</option>`).join("");
      loadAddr();
    };
    const loadAddr = () => { if (addrIn) { addrIn.value = faddrGet(netSel.value); 
      addrIn.placeholder = `your ${(NETS[netSel.value] || {}).label || ""} address (saved for next time)`; } };
    chainSel.onchange = fillNets;
    netSel.onchange = loadAddr;
    if (addrIn) addrIn.onchange = () => { if (addrIn.value.trim()) faddrSet(netSel.value, addrIn.value.trim()); };
    fillNets();
  }
  const amt = $("swapAmt");
  document.querySelectorAll(".pcts button[data-pct]").forEach((b) => {
    b.onclick = () => {
      if (!sel || !lastSto || !amt) return;
      const p = poolOf(lastSto, sel), d = ($("dir") || {}).value || "n2t";
      const bal = d === "n2t" ? execUnits() : tokenUnits(p.asset);
      if (bal == null) return alertBar("Sign in to use your balance.");
      const pct = BigInt(b.getAttribute("data-pct"));
      amt.value = fromUnits(bal * pct / 100n);
      renderSwap();
    };
  });
  const fl = $("btnFlip");
  if (fl) fl.onclick = () => { const d = $("dir"); if (!d) return;
    d.value = d.value === "n2t" ? "t2n" : "n2t"; if (amt) amt.value = ""; renderSwap(); };
  const mp = $("mktPick");
  if (mp) mp.onchange = () => { sel = mp.value; syncUrl(true); render(); };
  const rb = $("mktRanges");
  if (rb) rb.querySelectorAll("button").forEach((b) => { b.onclick = () => {
    mktRange = Number(b.getAttribute("data-range"));
    rb.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
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
    share(pair + " on NADO DEX", `Trade ${pair} on a post-quantum chain — no listing, no admin, no rake. ${url}`);
  };
}

dapp.onReturn((pend, ok, err) => {
  if (pend && pend.poolId != null) sel = String(pend.poolId);
  dapp.showReturn(pend, ok, err, {
    open: "Pool opened — confirming…",
    fundn: "NADO staged — confirming…",
    fundt: "Token staged — confirming…",
    join: "Liquidity added — confirming…",
    swapn: "Swap sent — confirming…",
    swapt: "Swap sent — confirming…",
    exit: "Withdrawal sent — confirming…",
    refund: "Refund sent — confirming…",
    post: "Order posted — confirming…",
    post_intra: "Limit order posted — confirming…",
    fill_intra: "Limit order filled — confirming…",
    fill: "Fill sent — confirming…",
    settle: "Settle sent — confirming…",
    set_premium: "Deposit requirement set — confirming…",
    expire: "Refund claim sent — confirming…",
    boost: "Bounty attached — confirming…",
    cancel: "Cancel sent — confirming…",
  });
  refresh();
});

async function boot() {
  try { await dapp.init(); } catch (e) {
    alertBar("Crypto bundle failed to load — reload.");
    return;
  }
  wireUI(); loadQR(); orderCards(["marketCard", "swapCard", "liqCard", "poolsCard", "otcLimitCard", "openCard", "otcBookCard", "otcPostCard", "otcMyCard", "walletcard"]);
  window.addEventListener("popstate", () => { wantMarket = null; readUrl(); render(); });
  const modes = installModes(dapp, { modes: [
    { key: "swap", icon: "🔄", label: "Swap", hint: "Trade NADO and tokens on the on-chain AMM — live price, depth, and pools.",
      cards: ["marketCard", "swapCard", "liqCard", "poolsCard", "otcLimitCard", "openCard"] },
    { key: "cross", icon: "🌉", label: "Cross-chain", hint: "Atomic BTC/ETH ↔ NADO swaps — no custodian, no wrapped coins.",
      cards: ["otcBookCard", "otcPostCard", "otcMyCard"] },
  ], onChange: (k) => { curMode = k; syncUrl(true); } });
  curMode = new URLSearchParams(location.search).get("mode") === "cross" ? "cross" : "swap";
  render = modes.wrap(doRender);
  readUrl();
  refresh();
  setInterval(refresh, 3000);
}
boot();
