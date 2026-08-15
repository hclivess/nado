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
import { NadoDapp, rawToNado, nadoToRaw, _m, $, gate, wireWallet, stickyInputs, alertBar, loadQR,
         orderCards, disp, share, installModes, playModes } from "./nadodapp.js?v=d93887e4";

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
}

// ---- actions -------------------------------------------------------------------------------------------
function openPool() {
  const pid = Number(($("newPid").value || "").trim());
  const asset = ($("newAsset").value || "").trim();
  if (!asset) return alertBar("Enter the asset id to pair with NADO.");
  if (!(pid > 0 && pid < ID_MAX)) return alertBar("Pool id must be between 1 and 2^32-1.");
  dapp.call("open", [pid, asset], null, "Opening pool…", { poolId: pid });
}

function fundNative() {
  if (!sel) return alertBar("Select a pool first.");
  const p = poolOf(lastSto, sel);
  const pos = Number(($("posId").value || "").trim());
  const u = toUnits(($("addN").value || "").trim());
  if (!(pos > 0 && pos < ID_MAX)) return alertBar("Enter a position id (1 … 2^32-1) — it is your LP slot.");
  if (u <= 0n) return alertBar("Enter a NADO amount (min 0.01).");
  dapp.call("fundn", [pos, p.id, Number(u)], (u * UNIT).toString(), "Staging NADO…", { posId: pos });
}

function fundToken() {
  if (!sel) return alertBar("Select a pool first.");
  const p = poolOf(lastSto, sel);
  const pos = Number(($("posId").value || "").trim());
  const u = toUnits(($("addT").value || "").trim());
  if (!(pos > 0)) return alertBar("Enter your position id.");
  if (u <= 0n) return alertBar("Enter a token amount.");
  // opts.asset makes this an ASSET-denominated call (value = amount, asset = which token).
  dapp.call("fundt", [pos, p.id, Number(u)], (u * UNIT).toString(), "Staging token…",
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
  dapp.call("refund", [pos, p.id, p.asset], null, "Refunding staged funds…", { posId: pos });
}

function exitPos() {
  if (!sel) return alertBar("Select a pool first.");
  const p = poolOf(lastSto, sel);
  const pos = Number(($("posId").value || "").trim());
  const sh = Number(($("exitSh").value || "").trim());
  if (!(pos > 0)) return alertBar("Enter your position id.");
  if (!(sh > 0)) return alertBar("Enter how many shares to withdraw.");
  dapp.call("exit", [pos, p.id, sh, p.asset], null, "Withdrawing liquidity…", { posId: pos });
}

function doSwap() {
  if (!sel) return alertBar("Select a pool first.");
  const p = poolOf(lastSto, sel);
  const card = $("swapCard");
  const inU = BigInt(card.dataset.inunits || "0");
  const minOut = BigInt(card.dataset.minout || "0");
  if (inU <= 0n) return alertBar("Enter an amount to swap.");
  if (($("dir").value || "n2t") === "n2t") {
    dapp.call("swapn", [p.id, Number(inU), Number(minOut), p.asset], (inU * UNIT).toString(),
              "Swapping…", { poolId: p.id });
  } else {
    dapp.call("swapt", [p.id, Number(inU), Number(minOut)], (inU * UNIT).toString(),
              "Swapping…", { poolId: p.id }, { asset: p.asset });
  }
}

// ---- wiring / boot ---------------------------------------------------------------------------------------
async function refresh() {
  try {
    const sto = await dapp.storage();
    if (sto) lastSto = sto;
  } catch (e) { /* transient relay blip — keep the last good view rather than blanking the page */ }
  render();
}

function wireUI() {
  wireWallet(dapp, render);
  stickyInputs(["newPid", "newAsset", "posId", "addN", "addT", "slip"], "nado_dex_form");
  $("btnOpen").onclick = openPool;
  $("btnFundN").onclick = fundNative;
  $("btnFundT").onclick = fundToken;
  $("btnJoin").onclick = joinPool;
  $("btnRefund").onclick = refundPos;
  $("btnExit").onclick = exitPos;
  $("btnSwap").onclick = doSwap;
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
  });
  refresh();
});

async function boot() {
  try { await dapp.init(); } catch (e) {
    alertBar("Crypto bundle failed to load — reload.");
    return;
  }
  wireUI(); loadQR(); orderCards(["swapCard", "poolsCard", "liqCard", "openCard", "walletcard"]);
  const modes = installModes(dapp, { modes: playModes({ icon: "🔄", play: ["swapCard", "poolsCard", "liqCard"] }) });
  render = modes.wrap(doRender);
  const q = new URLSearchParams(location.search).get("pool");
  if (q) sel = q;
  refresh();
  setInterval(refresh, 3000);
}
boot();
