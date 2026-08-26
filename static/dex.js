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
import { NadoDapp, rawToNado, nadoToRaw, _m, $, gate, wireWallet, stickyInputs, alertBar, loadQR,
         orderCards, disp, share, installModes, playModes, algHashn, base, esc, randId,
         blocksToTime } from "./nadodapp.js?v=68e91695";

const CID = "7e97163299583191d40d8676f43d5cfe";
const dapp = new NadoDapp({ cid: CID, app: "Dex" });

const UNIT = 100000000n;              // 1e8 raw = 0.01 NADO — must match dex.UNIT
const FEE_NUM = 9970n, FEE_DEN = 10000n;
const ID_MAX = 4294967296;            // 2^32 — ids are slot keys (see the contract's slot model)

const toUnits = (nado) => { try { return BigInt(nadoToRaw(nado)) / UNIT; } catch (e) { return 0n; } };
const fromUnits = (u) => rawToNado((BigInt(u) * UNIT).toString());

let lastSto = null;
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
    return `<div class="poolrow${on}" data-pool="${p.id}" style="cursor:pointer">
      <div><b>#${p.id}</b> <span class="mono small dim">${disp(p.asset).slice(0, 20)}</span></div>
      <div class="mono small">${fromUnits(p.rn)} NADO · ${fromUnits(p.rt)} TKN</div>
      <div class="small dim">${p.sup > 0n ? "≈ " + midPrice(p).toFixed(6) + " TKN/NADO" : "empty — needs liquidity"}</div>
    </div>`;
  }).join("");
  box.querySelectorAll(".poolrow").forEach((el) => {
    el.onclick = () => { sel = el.getAttribute("data-pool"); render(); };
  });
}

function renderSwap() {
  const card = $("swapCard");
  if (!card) return;
  gate({ swapCard: !!sel, liqCard: !!sel });
  if (!sel || !lastSto) return;
  const p = poolOf(lastSto, sel);
  const dir = ($("dir") || {}).value || "n2t";     // n2t = sell NADO, t2n = sell token
  const inU = toUnits((($("swapAmt") || {}).value || "").trim());
  const out = dir === "n2t" ? quoteOut(inU, p.rn, p.rt) : quoteOut(inU, p.rt, p.rn);
  const slipPct = Number((($("slip") || {}).value) || "1");
  // minOut = the quote reduced by the tolerance, rounded DOWN (the contract compares UNITs as integers).
  const minOut = out * BigInt(Math.max(0, Math.round((100 - slipPct) * 100))) / 10000n;
  $("quote").textContent = out > 0n
    ? `${fromUnits(out)} ${dir === "n2t" ? "TKN" : "NADO"}   (min ${fromUnits(minOut)})`
    : "—";
  card.dataset.minout = String(minOut);
  card.dataset.inunits = String(inU);
}

function doRender() {
  renderPools();
  renderSwap();
  renderOtc();
  renderLimits();
}

// ---- actions -------------------------------------------------------------------------------------------
function openPool() {
  const pid = Number(($("newPid").value || "").trim());
  const asset = ($("newAsset").value || "").trim();
  if (!asset) return alertBar("Enter the asset id to pair with NADO.");
  if (!(pid > 0 && pid < ID_MAX)) return alertBar("Pool id must be between 1 and 2^32-1.");
  let aidB; try { aidB = BigInt(asset); } catch (e) { return alertBar("Asset id must be a number."); }
  if (aidB <= 0n) return alertBar("Asset id must be a number.");
  dapp.call("open", [pid, aidB], null, "Opening pool…", { poolId: pid });
}

function fundNative() {
  if (!sel) return alertBar("Select a pool first.");
  const p = poolOf(lastSto, sel);
  const pos = Number(($("posId").value || "").trim());
  const u = toUnits(($("addN").value || "").trim());
  if (!(pos > 0 && pos < ID_MAX)) return alertBar("Enter a position id (1 … 2^32-1) — it is your LP slot.");
  if (u <= 0n) return alertBar("Enter a NADO amount (min 0.01).");
  dapp.call("fundn", [pos, p.id, Number(u)], u * UNIT, "Staging NADO…", { posId: pos });
}

function fundToken() {
  if (!sel) return alertBar("Select a pool first.");
  const p = poolOf(lastSto, sel);
  const pos = Number(($("posId").value || "").trim());
  const u = toUnits(($("addT").value || "").trim());
  if (!(pos > 0)) return alertBar("Enter your position id.");
  if (u <= 0n) return alertBar("Enter a token amount.");
  // opts.asset makes this an ASSET-denominated call (value = amount, asset = which token).
  dapp.call("fundt", [pos, p.id, Number(u)], u * UNIT, "Staging token…",
            { posId: pos }, { asset: p.asset });
}

function joinPool() {
  if (!sel) return alertBar("Select a pool first.");
  const p = poolOf(lastSto, sel);
  const pos = Number(($("posId").value || "").trim());
  if (!(pos > 0)) return alertBar("Enter your position id.");
  dapp.call("join", [pos, p.id], null, "Adding liquidity…", { posId: pos });
}

function refundPos() {
  if (!sel) return alertBar("Select a pool first.");
  const p = poolOf(lastSto, sel);
  const pos = Number(($("posId").value || "").trim());
  if (!(pos > 0)) return alertBar("Enter your position id.");
  dapp.call("refund", [pos, p.id, BigInt(p.asset)], null, "Refunding staged funds…", { posId: pos });
}

function exitPos() {
  if (!sel) return alertBar("Select a pool first.");
  const p = poolOf(lastSto, sel);
  const pos = Number(($("posId").value || "").trim());
  const sh = Number(($("exitSh").value || "").trim());
  if (!(pos > 0)) return alertBar("Enter your position id.");
  if (!(sh > 0)) return alertBar("Enter how many shares to withdraw.");
  dapp.call("exit", [pos, p.id, sh, BigInt(p.asset)], null, "Withdrawing liquidity…", { posId: pos });
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
const MEMPOOL = "https://mempool.space";
const btcCache = {};                                   // orderId -> { script, addr } once computed
function btcParts(od) {
  // both parties' swap pubkeys ride the order itself (packed behind "|" in their address fields)
  if (od.wch !== "btc") return null;
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
  p2wshAddress(script, "bc").then((addr) => { btcCache[od.o] = { script, addr }; render(); });
  return null;
}
async function btcVerifyInto(od, elId) {
  const el = document.getElementById(elId), b = btcInfo(od);
  if (!el || !b) return;
  el.textContent = "checking…";
  try {
    const a = await (await fetch(`${MEMPOOL}/api/address/${b.addr}`, { cache: "no-store" })).json();
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
  try { utxo = (await (await fetch(`${MEMPOOL}/api/address/${b.addr}/utxo`, { cache: "no-store" })).json())[0]; }
  catch (e) { return alertBar("Explorer unreachable — try again."); }
  if (!utxo) return alertBar("Nothing to spend at the swap address (not funded, or already spent).");
  if (!utxo.status.confirmed && !confirm("The coin is still UNCONFIRMED. Continue anyway?")) return;
  const rec = otcRec(od.o);
  if (!rec.k) return alertBar("This browser doesn't hold the swap key for this order (use the device you posted/filled from, or scripts/otc_btc_leg.py).");
  const payout = (prompt("Your Bitcoin address — where the coins should go:") || "").trim();
  if (!payout) return;
  let outScriptHex;
  try { outScriptHex = await addressToScript(payout, "bc"); } catch (e) { return alertBar(String(e.message || e)); }
  let feeRate = 10;
  try { feeRate = Math.max(1, (await (await fetch(`${MEMPOOL}/api/v1/fees/recommended`)).json()).fastestFee); } catch (e) {}
  const feeSat = feeRate * 160;                        // ~160 vB for this 1-in/1-out P2WSH spend
  const sHex = mode === "claim" ? (od.kind === OTC_ASK ? rec.s : otcSecretFromLimbs(od.limbs)) : null;
  if (mode === "claim" && !/^[0-9a-f]{64}$/.test(sHex || "")) return alertBar("The swap secret isn't available yet.");
  try {
    const hex = mode === "claim"
      ? await claimTx({ scriptHex: b.script, secretHex: sHex, privHex: rec.k, fundTxid: utxo.txid,
                        vout: utxo.vout, amountSat: utxo.value, outScriptHex, feeSat })
      : await refundTx({ scriptHex: b.script, locktime: Math.floor(Number(od.expf)), privHex: rec.k,
                         fundTxid: utxo.txid, vout: utxo.vout, amountSat: utxo.value, outScriptHex, feeSat });
    const r = await fetch(`${MEMPOOL}/api/tx`, { method: "POST", body: hex });
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
    for (const tx of await (await fetch(`${MEMPOOL}/api/address/${b.addr}/txs`, { cache: "no-store" })).json())
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

// ---- rendering ----------------------------------------------------------------------------------------
function otcRow(od, mine) {
  const me = dapp.me, isMaker = od.maker === me, isTaker = od.taker === me;
  const sells = od.kind === OTC_ASK;
  const left = otcLeft(od), expired = left <= 0;
  const chain = esc(od.wch.toUpperCase());
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
  const btc = od.wch === "btc" ? btcInfo(od) : null;
  const btcFunder = od.wch === "btc" && (sells ? isTaker : isMaker);
  const btcClaimer = od.wch === "btc" && (sells ? isMaker : isTaker);
  if (btc && od.st === 2 && btcClaimer && sells && otcRec(od.o).s) acts.unshift(`<button class="primary" data-otc="btcclaim" data-o="${od.o}">Claim the BTC…</button>`);
  if (btc && od.st === 3 && btcClaimer && !sells) acts.unshift(`<button class="primary" data-otc="btcclaim" data-o="${od.o}">Claim your BTC…</button>`);
  if (btc && od.st >= 2 && btcFunder && Date.now() / 1000 >= Number(od.expf)) acts.push(`<button class="ghost" data-otc="btcrefund" data-o="${od.o}">Reclaim BTC</button>`);
  if (od.st === 1 && !expired && isMaker && od.kind !== OTC_INTRA) acts.push(`<button class="ghost" data-otc="prem" data-o="${od.o}">Deposit…</button>`);
  let detail = "";
  if (mine) {
    let hint = "";
    if (od.st === 1 && !expired && isMaker) hint = "Waiting for a taker — your funds stay reclaimable. Cancel any time.";
    else if (od.st === 2 && !expired) {
      if (sells && isMaker) hint = `Next: press Verify below — once the taker's ${chain} lock shows CONFIRMED, press Claim the BTC. Claiming completes your side.`;
      else if (sells && isTaker) hint = `Next: send the ${chain} to the address below. When the maker claims it, press Settle — your NADO arrives automatically.`;
      else if (!sells && isMaker) hint = `Next: send the ${chain} to the address below, wait for confirmations, then press Settle to collect your NADO.`;
      else if (!sells && isTaker) hint = `Next: wait — when the maker collects their NADO here, a Claim your BTC button appears on this row.`;
    } else if ((od.st === 1 || od.st === 2) && expired) hint = "Expired — Reclaim returns everything to whoever put it in.";
    if (hint) detail += `<div class="small mt" style="color:var(--accent2)">${hint}</div>`;
    if (od.wch === "btc" && od.st >= 2 && (isMaker || isTaker)) {
      const b = btcInfo(od);
      if (b) detail += `<div class="small mt">${btcFunder && od.st === 2 ? `<b>Send exactly ${esc(od.wamt)} BTC to:</b><br>` : `Swap address: `}<span class="mono" style="word-break:break-all">${b.addr}</span>
        <a href="#" data-otc="btccopy" data-o="${od.o}">copy</a> · <a href="#" data-otc="btcverify" data-o="${od.o}">verify</a>
        <span id="btcv${od.o}" class="dim"></span></div>`;
      else if (!btcParts(od)) detail += `<div class="small dim mt">The counterparty's client didn't publish a Bitcoin key — finish this leg with scripts/otc_btc_leg.py.</div>`;
    }
    const secret = otcRec(od.o).s;
    if (secret && (od.st === 1 || od.st === 2))
      detail += `<div class="small dim mt">Your swap secret: <span class="mono">${secret.slice(0, 16)}…</span>
        <a href="#" data-otc="showsecret" data-o="${od.o}">show</a> — reveal it on the ${chain} side ONLY after
        verifying the counterparty's lock.</div>`;
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
      <div class="loanwho dim small">${sells ? "maker receives" : "taker receives"} ${chain} at ${esc((sells ? od.wadr : od.tadr || od.wadr).split("|")[0]) || "(swap key published)"}</div>
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
  const chain = $("otcChain").value, famt = ($("otcFAmt").value || "").trim(), faddr = ($("otcFAddr").value || "").trim();
  const blocks = Math.floor(Number($("otcExpiry").value || 0));
  if (raw <= 0n) return alertBar("Enter the NADO amount.");
  if (!famt || !(Number(famt) > 0)) return alertBar("Enter the foreign amount.");
  if (!faddr) return alertBar("Enter your " + chain.toUpperCase() + " address.");
  if (!(blocks >= 20 && blocks <= 900000)) return alertBar("Expiry must be 20 … 900000 blocks.");
  const o = randId();
  const sHex = Array.from(crypto.getRandomValues(new Uint8Array(32)), (x) => x.toString(16).padStart(2, "0")).join("");
  const kp = chain === "btc" ? genKeypair() : null;    // the swap's own Bitcoin key — never typed, never leaves this browser
  otcSaveRec(o, Object.assign({ s: sHex }, kp || {})); // BEFORE the wallet redirect can navigate away
  const hsha = await sha256Hex(sHex);
  const [hi, lo] = otcVmParts(sHex);
  // expf: the FOREIGN leg's deadline both parties sign. Advisory to the VM (it cannot read that chain);
  // the wallet suggests ~60% of the NADO window in unix seconds so the foreign refund opens first (§6.3).
  const expf = Math.floor(Date.now() / 1000 + blocks * 6 * 0.6);
  const expn = (dapp.cursor || 0) + blocks;
  const box = $("otcSecretBox"); if (box) { box.classList.remove("hidden"); $("otcSecretHex").textContent = sHex; }
  const wadr = kp ? faddr + "|" + kp.pub : faddr;
  dapp.call("post", [o, kind, raw, chain, famt, wadr, hsha, hi, lo, expn, expf],
            kind === OTC_ASK ? raw : null, "Posting order #" + o + "…", { otc: o }, { cid: OTC_CID });
}
function otcAction(what, o) {
  const od = otcOrders().find((x) => x.o === o);
  if (!od) return;
  if (what === "showsecret") { const s = otcSecrets()[o]; if (s) prompt("Swap secret for order #" + o + " — keep it safe:", s); return; }
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
    } else {
      myf = prompt(od.kind === OTC_ASK
        ? "Your " + chain + " refund address (your " + chain + " lock refunds there if the swap dies):"
        : "Your " + chain + " receiving address (the maker's " + chain + " lock pays you there):");
      if (!myf) return;
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
  if (what === "settle") {
    (async () => {
      let s = otcRec(o).s;                              // a maker settles with their own stored secret
      if (!s && od.wch === "btc") { alertBar("Looking up the revealed secret on Bitcoin…"); s = await btcFoundSecret(od); }
      if (!s) s = (prompt("Paste the revealed 64-hex swap secret (from the foreign-chain claim):") || "").trim().toLowerCase();
      if (!/^[0-9a-f]{64}$/.test(s || "")) return alertBar("That is not a 32-byte hex secret.");
      dapp.call("settle", [o, ...otcLimbs(s)], null, "Settling #" + o + "…", { otc: o }, { cid: OTC_CID });
    })();
  }
}

// ---- SWAP_INTRA limit orders (same otc contract, rendered beside the AMM) -----------------------------
const limSide = (asset, amtRaw) => asset !== "0"
  ? `<b>${amtRaw}</b> <span class="mono small dim">asset ${esc(asset).slice(0, 12)}…</span>`
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
  const ga = ($("limGiveAsset").value || "").trim() || "0";
  const wa = ($("limWantAsset").value || "").trim() || "0";
  const blocks = Math.floor(Number($("limExpiry").value || 0));
  const amt = (v, asset) => { try { return asset !== "0" ? BigInt((v || "").trim()) : BigInt(nadoToRaw((v || "").trim())); } catch (e) { return 0n; } };
  const gv = amt($("limGiveAmt").value, ga), wv = amt($("limWantAmt").value, wa);
  if (gv <= 0n || wv <= 0n) return alertBar("Enter both amounts (tokens in raw base units).");
  if (ga === "0" && wa === "0") return alertBar("NADO for NADO is not a swap — one side must be an asset.");
  if (!(blocks >= 20 && blocks <= 900000)) return alertBar("Expiry must be 20 … 900000 blocks.");
  const o = randId();
  let gaB, waB; try { gaB = BigInt(ga); waB = BigInt(wa); } catch (e) { return alertBar("Asset ids must be numbers."); }
  dapp.call("post_intra", [o, gaB, gv, waB, wv, (dapp.cursor || 0) + blocks],
            gv, "Posting limit order #" + o + "…", { otc: o },
            gaB !== 0n ? { cid: OTC_CID, asset: ga } : { cid: OTC_CID });
}
// ---- wiring / boot ---------------------------------------------------------------------------------------
async function refresh() {
  try {
    const sto = await dapp.storage();
    if (sto) lastSto = sto;
  } catch (e) { /* transient relay blip — keep the last good view rather than blanking the page */ }
  await otcRefresh();
  render();
}

function wireUI() {
  wireWallet(dapp, render);
  stickyInputs(dapp, ["newPid", "newAsset", "posId", "addN", "addT", "slip", "otcNado", "otcFAmt", "otcFAddr", "otcExpiry", "limGiveAsset", "limGiveAmt", "limWantAsset", "limWantAmt", "limExpiry"]);
  $("btnOpen").onclick = openPool;
  $("btnFundN").onclick = fundNative;
  $("btnFundT").onclick = fundToken;
  $("btnJoin").onclick = joinPool;
  $("btnRefund").onclick = refundPos;
  $("btnExit").onclick = exitPos;
  $("btnSwap").onclick = doSwap;
  const bp = $("btnOtcPost"); if (bp) bp.onclick = otcPost;
  const lp = $("btnLimPost"); if (lp) lp.onclick = limPost;
  ["swapAmt", "slip", "dir"].forEach((id) => {
    const el = $(id);
    if (el) { el.oninput = renderSwap; el.onchange = renderSwap; }
  });
  const sh = $("btnShare");
  if (sh) sh.onclick = () => share("NADO DEX", "Swap NADO and tokens on a post-quantum chain — no listing, no admin, no rake.");
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
  wireUI(); loadQR(); orderCards(["swapCard", "poolsCard", "liqCard", "otcLimitCard", "openCard", "otcBookCard", "otcPostCard", "otcMyCard", "walletcard"]);
  const modes = installModes(dapp, { modes: playModes({ icon: "🔄", play: ["swapCard", "poolsCard", "liqCard", "otcLimitCard", "openCard"],
    extra: [{ key: "cross", icon: "🌉", label: "Cross-chain", hint: "Swap NADO against BTC/ETH — atomic, no custodian, no wrapped coins.",
              cards: ["otcBookCard", "otcPostCard", "otcMyCard"] }] }) });
  render = modes.wrap(doRender);
  const q = new URLSearchParams(location.search).get("pool");
  if (q) sel = q;
  refresh();
  setInterval(refresh, 3000);
}
boot();
