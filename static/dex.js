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


// ================= CROSS-CHAIN ORDER BOOK (otc contract — doc/dex-bridge.md §4) =========================
// Same page, DIFFERENT contract: the book is its own tiny escrow contract beside the AMM (no shared state,
// no shared upgrade surface), called through this dapp session via opts.cid. One venue, two contracts.
const OTC_CID = "6bb0bd0d5dad478bb33d254e73cde85d";
const OTC_ASK = 1, OTC_BID = 2;                       // kind: maker SELLS NADO / maker BUYS NADO
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
const otcSaveSecret = (o, s) => { const m = otcSecrets(); m[o] = s; localStorage.setItem(LS_OTC_SECRETS, JSON.stringify(m)); };

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
  const acts = [];
  if (od.st === 1 && !expired && isMaker) acts.push(`<button class="ghost" data-otc="cancel" data-o="${od.o}">Cancel</button>`);
  if (od.st === 1 && !expired && !isMaker && me) acts.push(`<button class="primary" data-otc="fillask" data-o="${od.o}">Fill…</button>`);
  if ((od.st === 1 || od.st === 2) && expired) acts.push(`<button class="ghost" data-otc="expire" data-o="${od.o}">Expire → refund</button>`);
  if (od.st === 2 && !expired) acts.push(`<button class="primary" data-otc="settle" data-o="${od.o}">Settle…</button>`);
  let detail = "";
  if (mine) {
    const secret = otcSecrets()[od.o];
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
      <div class="loanterms">hashlock <span class="dim">${esc(od.hsha).slice(0, 18)}…</span> ·
        ${od.st <= 2 ? (expired ? "refundable now" : `expires in ${left} blocks (~${blocksToTime(left)})`) : ""}</div>
      <div class="loanwho dim small">${sells ? "maker receives" : "taker receives"} ${chain} at ${esc(sells ? od.wadr : od.tadr || od.wadr)}</div>
      ${detail}
    </div><div class="loanacts">${acts.join("")}</div></div>`;
}
function renderOtc() {
  const book = $("otcBook"), mine = $("otcMine");
  if (!book || !mine) return;
  const all = otcOrders(), me = dapp.me;
  const open = all.filter((x) => x.st === 1 && otcLeft(x) > 0);
  book.innerHTML = open.length ? open.map((x) => otcRow(x, false)).join("")
    : `<p class="small dim">No open orders. Post one — the book is permissionless.</p>`;
  const my = all.filter((x) => me && (x.maker === me || x.taker === me));
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
  otcSaveSecret(o, sHex);                              // BEFORE the wallet redirect can navigate away
  const hsha = await sha256Hex(sHex);
  const [hi, lo] = otcVmParts(sHex);
  // expf: the FOREIGN leg's deadline both parties sign. Advisory to the VM (it cannot read that chain);
  // the wallet suggests ~60% of the NADO window in unix seconds so the foreign refund opens first (§6.3).
  const expf = Math.floor(Date.now() / 1000 + blocks * 6 * 0.6);
  const expn = (dapp.cursor || 0) + blocks;
  const box = $("otcSecretBox"); if (box) { box.classList.remove("hidden"); $("otcSecretHex").textContent = sHex; }
  dapp.call("post", [o, kind, raw.toString(), chain, famt, faddr, hsha, hi, lo, expn, expf],
            kind === OTC_ASK ? raw.toString() : null, "Posting order #" + o + "…", { otc: o }, { cid: OTC_CID });
}
function otcAction(what, o) {
  const od = otcOrders().find((x) => x.o === o);
  if (!od) return;
  if (what === "showsecret") { const s = otcSecrets()[o]; if (s) prompt("Swap secret for order #" + o + " — keep it safe:", s); return; }
  if (what === "cancel") return dapp.call("cancel", [o], null, "Cancelling #" + o + "…", { otc: o }, { cid: OTC_CID });
  if (what === "expire") return dapp.call("expire", [o], null, "Reclaiming #" + o + "…", { otc: o }, { cid: OTC_CID });
  if (what === "fillask") {
    const chain = od.wch.toUpperCase();
    const myf = prompt(od.kind === OTC_ASK
      ? "Your " + chain + " refund address (your " + chain + " HTLC refunds there if the swap dies):"
      : "Your " + chain + " receiving address (the maker's " + chain + " HTLC pays you there):");
    if (!myf) return;
    let fref = "awaiting-maker";
    if (od.kind === OTC_ASK) {
      fref = prompt("Paste the txid of the " + chain + " HTLC you created for the maker (hashlock above, "
        + "amount " + od.wamt + " " + chain + ", to " + od.wadr + ", with a deadline BEFORE " + od.expf + "):") || "";
      if (!fref) return alertBar("Fill needs your foreign lock reference — create the " + chain + " HTLC first.");
    }
    dapp.call("fill", [o, myf, fref], od.kind === OTC_BID ? od.namtRaw.toString() : null,
              "Filling #" + o + "…", { otc: o }, { cid: OTC_CID });
    return;
  }
  if (what === "settle") {
    let s = otcSecrets()[o];                            // a BID maker settles with their own stored secret
    if (!s) s = (prompt("Paste the revealed 64-hex swap secret (from the foreign-chain claim):") || "").trim().toLowerCase();
    if (!/^[0-9a-f]{64}$/.test(s || "")) return alertBar("That is not a 32-byte hex secret.");
    dapp.call("settle", [o, ...otcLimbs(s)], null, "Settling #" + o + "…", { otc: o }, { cid: OTC_CID });
  }
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
  stickyInputs(dapp, ["newPid", "newAsset", "posId", "addN", "addT", "slip", "otcNado", "otcFAmt", "otcFAddr", "otcExpiry"]);
  $("btnOpen").onclick = openPool;
  $("btnFundN").onclick = fundNative;
  $("btnFundT").onclick = fundToken;
  $("btnJoin").onclick = joinPool;
  $("btnRefund").onclick = refundPos;
  $("btnExit").onclick = exitPos;
  $("btnSwap").onclick = doSwap;
  const bp = $("btnOtcPost"); if (bp) bp.onclick = otcPost;
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
    fill: "Fill sent — confirming…",
    settle: "Settle sent — confirming…",
    expire: "Refund claim sent — confirming…",
    cancel: "Cancel sent — confirming…",
  });
  refresh();
});

async function boot() {
  try { await dapp.init(); } catch (e) {
    alertBar("Crypto bundle failed to load — reload.");
    return;
  }
  wireUI(); loadQR(); orderCards(["swapCard", "poolsCard", "liqCard", "openCard", "otcBookCard", "otcPostCard", "otcMyCard", "walletcard"]);
  const modes = installModes(dapp, { modes: playModes({ icon: "🔄", play: ["swapCard", "poolsCard", "liqCard"],
    extra: [{ key: "cross", icon: "🌉", label: "Cross-chain", hint: "Swap NADO against BTC/ETH — atomic, no custodian, no wrapped coins.",
              cards: ["otcBookCard", "otcPostCard", "otcMyCard"] }] }) });
  render = modes.wrap(doRender);
  const q = new URLSearchParams(location.search).get("pool");
  if (q) sel = q;
  refresh();
  setInterval(refresh, 3000);
}
boot();
