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
import { htlcScript, p2wshAddress } from "./btcleg.js?v=93bc368e";
import { claimTx, refundTx, addressToScript, genKeypair } from "./btcsign.js?v=dc3d1162";
import { htlcAbi, htlcErc20Abi, erc20Abi, erc20Meta, toUnitsDec, fromUnitsDec, ethKeypair } from "./ethsign.js?v=b35591fc";
import { NadoDapp, rawToNado, nadoToRaw, _m, $, gate, wireWallet, stickyInputs, alertBar, loadQR,
         orderCards, disp, share, installModes, algHashn, base, esc, randId, enhanceSelect, refreshPickers,
         renderWallet,
         uiConfirm, uiPrompt,
         blocksToTime } from "./nadodapp.js?v=ef8ff764";

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
const tokName = (id) => { const m = tokMeta(id); return m ? (m.name || m.sym) : "unknown token"; };
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
      id: String(a.id), bal: null };
    for (const a of ((mine && mine.assets) || []))
      if (map[akey(a.id)]) map[akey(a.id)].bal = a.balance != null ? String(a.balance) : null;
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
// Price = tokens per NADO in the token's OWN decimals. The pool counts both sides in UNIT-sized steps, so
// the unit ratio rt/rn must be scaled by 10^(10-dec) — a 0-decimal token's pool unit is 10^10 tokens.
const pScale = (assetId) => 10 ** (10 - tokDec(assetId));
const midPrice = (p) => (p.rn > 0n ? Number(p.rt) / Number(p.rn) * pScale(p.asset) : 0);   // display only, never minOut

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
      <div class="num">${live ? fmtShort(price) + " " + esc(sym) : "—"}</div>
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
    ? `${fmtOut(out)} ${dir === "n2t" ? sym : "NADO"}   (at worst ${fmtOut(minOut)})`
    : "—";
  const amtIn = $("swapAmt"); if (amtIn) amtIn.placeholder = `amount in ${dir === "n2t" ? "NADO" : sym}`;
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
  if (imp) { imp.textContent = inU > 0n && out > 0n ? impact.toFixed(2) + "%" : "—";
    imp.style.color = impact >= 5 ? "var(--danger)" : impact >= 1 ? "var(--warn)" : "var(--dim)"; }
  const qa = $("quoteAmt"); if (qa) qa.value = out > 0n ? fmtOut(out) : "";
  const payBalU = dir === "n2t" ? execUnits() : tokenUnits(p.asset);
  setTxt("payBal", payBalU === null ? "—" : "Balance " + (dir === "n2t" ? fromUnits(payBalU) : tokFromUnits(payBalU, p.asset)) + " " + paySym);
  const getBalU = dir === "n2t" ? tokenUnits(p.asset) : execUnits();
  setTxt("getBal", getBalU === null ? "" : "Balance " + (dir === "n2t" ? tokFromUnits(getBalU, p.asset) : fromUnits(getBalU)) + " " + getSym);
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
  el.innerHTML = opts.length ? opts.join("") : `<option value="">${q ? "no token matches that" : "no tokens yet"}</option>`;
  if (prev && [...el.options].some((o) => o.value === prev)) el.value = prev;
}
function doRender() {
  const wc = $("walletcard"); if (wc) wc.classList.toggle("signed", !!dapp.me);
  renderWallet(dapp);                                 // who you are + both balances; without this a
                                                      // completed sign-in never showed up on the page
  fillAssetPicker($("newAsset"), { withNado: false });
  fillAssetPicker($("limGiveAsset"));
  fillTokenPicker();
  fillAssetPicker($("limWantAsset"));
  renderMarket();
  renderPools();
  renderSwap();
  renderLiq();
  renderOtc();
  renderLimits();
  refreshPickers();                                   // option lists change every poll — keep the labels honest
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
  const u = tokToUnits($("addT").value, p.asset);
  if (u <= 0n) return alertBar(`Enter a ${tokSym(p.asset)} amount (at least ${tokFromUnits(1n, p.asset)} ${tokSym(p.asset)} — the pool counts in that step).`);
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
  if (!(Number.isInteger(sh) && sh > 0)) return alertBar("Enter a whole number of shares to withdraw.");
  dapp.call("exit", [posFor(p.id), p.id, sh, BigInt(p.asset)], null, "Withdrawing your liquidity…", { posId: posFor(p.id) });
}

function doSwap() {
  if (!sel) return alertBar("Select a pool first.");
  const p = poolOf(lastSto, sel);
  const card = $("swapCard");
  const inU = BigInt(card.dataset.inunits || "0");
  const minOut = BigInt(card.dataset.minout || "0");
  if (inU <= 0n) return alertBar("Enter an amount to swap.");
  if (inU >= 1n << 31n) return alertBar("That amount is above the pool's per-trade bound.");
  if (minOut <= 0n) return alertBar("This pool cannot fill that amount — nothing would come out.");   // the contract requires out > 0
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
// The WIDE hashlock: four alghash digests of the same limbs, each with a different offset on the first
// limb. One 64-bit digest was forgeable at roughly 2^44 (audit); four independent constraints on one
// secret put that back out of reach, and the VM needs no new opcode. Must match otc.py HDOM exactly.
const HDOM = [0n, 0x10000000001n, 0x20000000003n, 0x30000000007n];
const otcVmParts = (sHex) => {                        // the four hashlocks, as the eight halves post() takes
  const L = otcLimbs(sHex).map(BigInt);
  const out = [];
  for (const d of HDOM) {
    const h = algHashn([L[0] + d, L[1], L[2], L[3], L[4]]);
    out.push(Number(h >> 32n), Number(h & 0xFFFFFFFFn));
  }
  return out;
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
  el.textContent = "checking…";
  try {
    const a = await (await fetch(`${explorerOf(od)}/api/address/${b.addr}`, { cache: "no-store" })).json();
    const conf = Number(a.chain_stats.funded_txo_sum || 0), pend = Number(a.mempool_stats.funded_txo_sum || 0);
    const need = Math.round(Number(od.wamt) * 1e8);     // the AGREED amount — a dust lock must never read green
    el.innerHTML = conf >= need && need > 0
      ? `<span style="color:var(--accent2)">CONFIRMED: ${conf / 1e8} BTC locked</span>${pend ? ` (+${pend / 1e8} unconfirmed)` : ""}`
      : conf > 0 ? `<span style="color:var(--danger)">UNDERFUNDED: only ${conf / 1e8} of the agreed ${esc(od.wamt)} BTC — do NOT reveal your secret</span>`
      : pend > 0 ? `UNCONFIRMED: ${pend / 1e8} BTC in the mempool — wait for confirmations`
      : "nothing sent to this address yet";
  } catch (e) { el.textContent = "explorer unreachable — try again"; }
}
async function btcSpendFlow(od, mode) {
  // ONE button: find the funded coin, ask where to send it, sign in-page, broadcast via the explorer.
  const b = btcInfo(od);
  if (!b) return alertBar("Still deriving the Bitcoin address — try again in a second.");
  let utxos;
  try { utxos = await (await fetch(`${explorerOf(od)}/api/address/${b.addr}/utxo`, { cache: "no-store" })).json(); }
  catch (e) { return alertBar("Explorer unreachable — try again."); }
  const need = Math.round(Number(od.wamt) * 1e8);
  // Spend the coin that pays the AGREED amount, not merely the first one listed: claiming a dust output
  // publishes the swap secret while the real coin sits untouched (audit).
  const utxo = (utxos || []).filter((u) => u.value >= need).sort((a, c) => a.value - c.value)[0];
  if (!utxo) {
    const most = Math.max(0, ...(utxos || []).map((u) => u.value));
    return alertBar(mode === "claim"
      ? `No coin here pays the agreed ${od.wamt} ${coinOf(od)} (largest: ${most / 1e8}). Claiming a smaller one would publish your secret for nothing.`
      : `Nothing here to reclaim (largest: ${most / 1e8}).`);
  }
  if (!utxo.status.confirmed && !await uiConfirm({ title: "That coin is still unconfirmed",
    body: "It has not been mined yet, so this spend may not be accepted. Continue anyway?", danger: true })) return;
  const rec = otcRec(od.o);
  if (!rec.k) return alertBar("This browser doesn't hold the swap key for this order (use the device you posted/filled from, or scripts/otc_btc_leg.py).");
  const payout = ((await uiPrompt({ title: "Where should the coins go?",
    body: `Your ${coinOf(od)} address — this spend pays it directly.`, placeholder: "address" })) || "").trim();
  if (!payout) return;
  let outScriptHex;
  try { outScriptHex = await addressToScript(payout, (netOf(od) || {}).hrp || "bc"); } catch (e) { return alertBar(String(e.message || e)); }
  let feeRate = 10;
  try { feeRate = Math.max(1, (await (await fetch(`${explorerOf(od)}/api/v1/fees/recommended`)).json()).fastestFee); } catch (e) {}
  // The fee estimate comes from an explorer we do not control, so cap it: unbounded, a bad (or hostile)
  // estimate could burn most of the coin, and the only prior guard was "output > 0" (audit).
  const feeSat = Math.min(feeRate * 160, Math.floor(utxo.value * 0.02), 200000);
  if (utxo.value - feeSat < 546) return alertBar("This coin is too small to spend after fees.");
  if (!await uiConfirm({ title: mode === "claim" ? "Claim these coins" : "Reclaim these coins",
    rows: [{ k: "You receive", v: (utxo.value - feeSat) / 1e8 + " " + coinOf(od) },
           { k: "To", v: payout.slice(0, 22) + (payout.length > 22 ? "…" : "") },
           { k: "Network fee", v: `${feeSat} sat (${(feeSat / utxo.value * 100).toFixed(2)}%)` }],
    confirmText: "Send" })) return;
  const sHex = mode === "claim" ? await otcKnownSecret(od) : null;
  if (mode === "claim" && !sHex) return alertBar("The swap secret isn't available yet.");
  // A claim that lands after the deadline still publishes the secret; Bitcoin's CLTV clock is median-time-
  // past, which lags wall time by up to ~1h, so keep a wider margin than the other chains.
  if (mode === "claim" && Math.floor(Date.now() / 1000) > Math.floor(Number(od.expf)) - 3600 - 900)
    return alertBar("Too close to this lock's deadline — a claim that lands late would publish your secret and pay nothing.");
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
  // mode: fund (the ETH/token sender locks) · claim (reveal s, get paid) · refund (after the deadline)
  try {
    const { addr, chain } = await ethConnect();
    const net = netOf(od) || {}, token = tokAddrOf(od);
    const htlc = token ? (net.erc20 || "") : ethHtlcFor(od);
    if (!htlc) { alertBar(`No ${token ? "token" : ""} swap contract is deployed on ${net.label || "that network"} yet — use the command shown on this row.`); return; }
    if (chain !== net.evm) { alertBar(`Switch your wallet to ${net.label} — this order is on that network.`); return; }
    const sells = od.kind === OTC_ASK;                  // ASK: taker sends the coin, maker claims
    const senderAddr = sells ? ethAddrOf(od.tadr) : ethAddrOf(od.wadr);   // who funded the lock (the refundee)
    const claimAddr = sells ? ethAddrOf(od.wadr) : ethAddrOf(od.tadr);    // who claims with the secret
    const dl = ethDeadline(od);
    if ((mode === "fund" || mode === "refund") && senderAddr && addr.toLowerCase() !== senderAddr.toLowerCase())
      return alertBar(`This swap's Ethereum side belongs to ${senderAddr.slice(0, 10)}… — switch your wallet to that account.`);
    const meta0 = token ? await ethTokenMeta(token) : { decimals: 18 };
    const amtWei = toUnitsDec(od.wamt, meta0.decimals);   // the AGREED amount is part of the lock key
    const key = token ? htlcErc20Abi.lockKey(token, od.hsha, claimAddr, senderAddr, dl, amtWei)
                      : htlcAbi.lockKey(od.hsha, claimAddr, senderAddr, dl, amtWei);
    let data, valueHex;
    if (mode === "fund") {
      if (token) {
        const amt = amtWei;
        if (amt <= 0n) return alertBar("That order's token amount is not a number.");
        // ERC-20 needs an allowance first — top it up only when it is short, so a second swap costs one tx.
        const cur = BigInt(await ethReq("eth_call", [{ to: token, data: erc20Abi.allowance(addr, htlc) }, "latest"]) || "0x0");
        if (cur < amt) {
          alertBar(`Approving ${meta0.symbol || "the token"}… confirm the first transaction, then the lock.`);
          await ethReq("eth_sendTransaction", [{ from: addr, to: token, data: erc20Abi.approve(htlc, amt) }]);
        }
        data = htlcErc20Abi.fund(token, claimAddr, addr, od.hsha, dl, amt);
      } else {
        data = htlcAbi.fund(claimAddr, addr, od.hsha, dl);
        valueHex = "0x" + amtWei.toString(16);
      }
    } else if (mode === "claim") {
      const sHex = await otcKnownSecret(od);
      if (!sHex) return alertBar("The swap secret isn't available yet.");
      const nowS2 = Math.floor(Date.now() / 1000);
      if (nowS2 > dl - 900)                              // a claim that misses the deadline still leaks s
        return alertBar("Too close to this lock's deadline — a claim that lands late would publish your secret and pay nothing.");
      // Read the lock back before revealing: an underfunded or mis-parameterised lock must NOT buy the secret.
      const raw = await ethReq("eth_call", [{ to: htlc, data: (token ? htlcErc20Abi : htlcAbi).locks(key) }, "latest"]);
      const words = (raw || "0x").replace(/^0x/, "").match(/.{64}/g) || [];
      const held = words.length ? BigInt("0x" + words[token ? 3 : 2]) : 0n;
      if (held < amtWei)
        return alertBar(`That lock holds less than the agreed amount — claiming it would publish your secret for nothing.`);
      data = token ? htlcErc20Abi.claim(key, sHex) : htlcAbi.claim(key, sHex);
    } else data = token ? htlcErc20Abi.refund(key) : htlcAbi.refund(key);
    const txid = await ethReq("eth_sendTransaction", [{ from: addr, to: htlc, data, value: valueHex }]);
    alertBar((mode === "fund" ? "Locked" : mode === "claim" ? "Claimed" : "Reclaimed") + " — tx " + String(txid).slice(0, 20) + "…");
  } catch (e) { alertBar(String((e && e.message) || e).slice(0, 140)); }
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

// ---- the Solana leg (scripts/solana-htlc, via static/solsign.js) -------------------------------------
// The escrow is a program-derived address whose SEEDS ARE THE SWAP'S TERMS, so both sides compute the same
// address from public data and an underfunded lock simply lands somewhere else — a claimant can never be
// tricked into publishing the secret for dust. Solana is an account model, so whoever submits pays the
// fee: the browser path uses the visitor's own wallet (as the Ethereum leg uses MetaMask) and falls back
// to the headless CLI on the row when no wallet is installed.
let SOL = null;
const solMod = async () => (SOL || (SOL = await import("./solsign.js?v=6f9e1078")));
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
  if (!info) throw new Error("That mint address is not an SPL token.");
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
  if (!program) throw new Error(`No swap program is deployed on ${(netOf(od) || {}).label} yet.`);
  if (!funder || !claimant) throw new Error("This swap's Solana addresses aren't both published yet.");
  if (!/^[0-9a-f]{64}$/.test(od.hsha || "")) throw new Error("This order has no usable hashlock.");
  if (!(deadline > 0) || lamports <= 0n) throw new Error("This order's Solana amount or deadline is missing.");
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
      return alertBar(`This swap's Solana side belongs to ${want.slice(0, 8)}… — switch your wallet to that account.`);
    let ix;
    const ata = async (owner) => t.mint ? await t.S.ataOf(owner, t.mint) : "";
    if (mode === "fund") {
      const already = await t.S.solLockInfo(t.rpc, t.program, t.address);
      if (already) return alertBar("That lock is already funded — nothing more to send.");
      ix = t.mint ? t.S.ixFundToken(t.program, me, t.address, od.hsha, t.claimant, t.deadline, Number(t.lamports), t.mint, await ata(me), t.lockAta)
                  : t.S.ixFund(t.program, me, t.address, od.hsha, t.claimant, t.deadline, Number(t.lamports));
    } else if (mode === "claim") {
      const sHex = await otcKnownSecret(od);
      if (!sHex) return alertBar("The swap secret isn't available yet.");
      if (Math.floor(Date.now() / 1000) > t.deadline - 900)
        return alertBar("Too close to this lock's deadline — a claim that lands late would publish your secret and pay nothing.");
      // Read the escrow back before revealing anything: the secret buys nothing from an empty account.
      const info = await t.S.solLockInfo(t.rpc, t.program, t.address);
      if (!info) return alertBar("No lock exists at this swap's address yet — nothing to claim.");
      if (info.owner !== t.program) return alertBar("That account is not owned by the swap program — do not reveal your secret.");
      if (info.hashlock !== od.hsha || info.claimant !== t.claimant || info.amount < t.lamports || (info.mint || "") !== t.mint)
        return alertBar("The lock on chain does not match this order's terms — claiming it would publish your secret for nothing.");
      ix = t.mint ? t.S.ixClaimToken(t.program, me, t.address, t.claimant, sHex, t.mint, t.lockAta, await ata(t.claimant))
                  : t.S.ixClaim(t.program, me, t.address, t.claimant, sHex);
    } else {
      ix = t.mint ? t.S.ixRefundToken(t.program, me, t.address, t.funder, t.mint, t.lockAta, await ata(t.funder))
                  : t.S.ixRefund(t.program, me, t.address, t.funder);
    }
    const sig = await t.S.solWalletSend(t.rpc, provider, me, [ix]);
    alertBar((mode === "fund" ? "Locked" : mode === "claim" ? "Claimed" : "Reclaimed") + " — tx " + sig.slice(0, 20) + "…");
  } catch (e) { alertBar(String((e && e.message) || e).slice(0, 160)); }
}
async function solFoundSecret(od) {
  try { const t = await solTerms(od); return await t.S.solFoundSecret(t.rpc, t.address, od.hsha); }
  catch (e) { return null; }
}
function solCliHint(od) {
  const net = netOf(od) || {};
  return `<div class="small dim mt">No Solana wallet detected. Run this leg from a terminal:<br>
    <span class="mono" style="word-break:break-all">node scripts/otc_sol_leg.mjs claim --rpc ${esc(net.rpc || "&lt;rpc&gt;")} --program ${esc(net.program || "&lt;not deployed&gt;")} --key &lt;your-key&gt; --hash ${esc(od.hsha)} --claimant &lt;addr&gt; --funder &lt;addr&gt; --deadline ${Number(od.expf) || 0} --amount ${tokAddrOf(od) ? "&lt;units&gt;" : String(solLamports(od.wamt))}${tokAddrOf(od) ? " --mint " + esc(tokAddrOf(od)) : ""} --secret &lt;s&gt;</span></div>`;
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
    for (const a of Object.keys(toks)) out.push({ key: k + "|" + a, net: k, token: a, coin: toks[a].sym, label: `${toks[a].sym} on ${n.label}`, chain: n.chain });
  }
  return out;
}
const xMarket = (key) => xMarkets("main").concat(xMarkets("test")).find((m) => m.key === key) || null;
/** Why a market cannot be traded yet, or "" — Bitcoin needs nothing deployed; EVM and Solana need their swap contract. */
function xMarketBlocker(m) {
  if (!m) return "";
  const n = NETS[m.net] || {};
  if (n.chain === "eth" && !(m.token ? n.erc20 : n.htlc)) return `The ${m.token ? "token" : "ETH"} swap contract is not deployed on ${n.label} yet — trading here opens when it is.`;
  if (n.chain === "sol" && !n.program) return `The swap program is not deployed on ${n.label} yet — trading here opens when it is.`;
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
  const seg = $("envSeg");
  if (seg) { seg.classList.remove("hidden"); seg.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.env === xEnv)); }
  const mkts = xMarkets(), keys = mkts.map((m) => m.key);
  const pick = $("mktPick");
  if (pick) {
    const opts = mkts.map((m) => `<option value="${esc(m.key)}">${esc(m.coin)} / NADO${xMarketBlocker(m) ? " · soon" : ""} — ${esc(m.label)}</option>`).join("");
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
  } else { chgEl.textContent = blk ? "coming soon" : b.bids.length || b.asks.length ? "one side quoted" : "no open orders"; chgEl.className = "chg flat"; }
  chgEl.title = blk;
  const mine = otcOrders().filter((x) => mktKeyOf(x) === xsel && dapp.me && (x.maker === dapp.me || x.taker === dapp.me)).length;
  $("mktStats").innerHTML = [
    ["Best bid", b.bb ? fmtPrice(b.bb) + " NADO" : "—"],
    ["Best ask", b.ba ? fmtPrice(b.ba) + " NADO" : "—"],
    ["Spread", b.bb && b.ba ? ((b.ba - b.bb) / b.ba * 100).toFixed(2) + "%" : "—"],
    ["Buy orders", String(b.bids.length)],
    ["Sell orders", String(b.asks.length)],
    ["Your orders", String(mine)],
  ].map(([l, v]) => `<div class="stat"><div class="l">${l}</div><div class="v">${v}</div></div>`).join("");
  const cap = $("depthCap"); if (cap) cap.textContent = "Live order book — how much is offered at each price:";
  const mc = $("mktCap"); if (mc) mc.textContent = "Prices come from open orders on this book. Nothing is back-filled — a gap means nothing was offered.";
  renderChart(XKEY(xsel), "NADO", `1 ${net.coin} =`);
  renderBookDepth(b, net.coin, blk ? (xEnv === "main" ? "trading opens when the swap contract is live — try Testnet" : "trading opens when the swap program is live") : "");
  syncUrl(false);
}
// the order book as cumulative depth — the classic book view, drawn from live open orders
function renderBookDepth(b, coin, emptyText = "") {
  const svg = $("mktDepth");
  if (!svg) return;
  if (!b.bids.length && !b.asks.length) {
    svg.innerHTML = `<text x="${DW / 2}" y="${DH / 2}" fill="var(--faint)" font-size="11" text-anchor="middle">${esc(emptyText || "no open orders — post one below")}</text>`;
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
    `<text x="8" y="${DH - 2}" fill="var(--accent2)" font-size="9.5" font-family="ui-monospace,monospace">buying ${esc(coin)} ←</text>` +
    `<text x="${DW - 8}" y="${DH - 2}" fill="var(--danger)" font-size="9.5" text-anchor="end" font-family="ui-monospace,monospace">→ selling ${esc(coin)}</text>`;
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
      const b = btcInfo(od); if (!b) return { state: "none", html: "— deriving the address" };
      const need = Math.round(Number(od.wamt) * 1e8);
      const a = await (await fetch(`${explorerOf(od)}/api/address/${b.addr}`, { cache: "no-store" })).json();
      const conf = Number(a.chain_stats.funded_txo_sum || 0), spent = Number(a.chain_stats.spent_txo_sum || 0), pend = Number(a.mempool_stats.funded_txo_sum || 0);
      if (spent >= need && need > 0) return { state: "claimed", html: `<span style="color:var(--accent2)">spent — claimed or reclaimed</span>` };
      if (conf >= need && need > 0) return { state: "funded", html: `<span style="color:var(--accent2)">CONFIRMED: ${conf / 1e8} BTC locked</span>` };
      if (conf > 0) return { state: "short", html: `<span style="color:var(--danger)">UNDERFUNDED: only ${conf / 1e8} of the agreed ${esc(od.wamt)} BTC</span>` };
      return { state: "none", html: pend > 0 ? `UNCONFIRMED: ${pend / 1e8} BTC in the mempool — wait for confirmations` : "— nothing sent yet" };
    }
    if (ch === "sol") {
      const t = await solTerms(od);
      const info = await t.S.solLockInfo(t.rpc, t.program, t.address);
      if (!info) { const sec = await t.S.solFoundSecret(t.rpc, t.address, od.hsha); return sec ? { state: "claimed", html: `<span style="color:var(--accent2)">claimed</span>` } : { state: "none", html: "— nothing locked yet" }; }
      const bad = [];
      if (info.owner !== t.program) bad.push("not owned by the swap program");
      if (info.hashlock !== od.hsha) bad.push("hashlock differs");
      if (info.claimant !== t.claimant) bad.push("claimant is not the counterparty");
      if (info.amount < t.lamports) bad.push("amount short");
      if ((info.mint || "") !== t.mint) bad.push(t.mint ? "not this token" : "a token lock, not SOL");
      return bad.length ? { state: "short", html: `<span style="color:var(--danger)">DOES NOT MATCH: ${esc(bad.join("; "))}</span>` }
        : { state: "funded", html: `<span style="color:var(--accent2)">verified: ${esc(od.wamt)} ${esc(coinOf(od))} locked until ${new Date(t.deadline * 1000).toISOString().slice(0, 16).replace("T", " ")}Z</span>` };
    }
    if (ch === "eth") {
      const token = tokAddrOf(od), htlc = token ? (net.erc20 || "") : ethHtlcFor(od);
      if (!htlc || !net.rpc) return { state: "none", html: "" };
      const sells = od.kind === OTC_ASK;
      const senderAddr = sells ? ethAddrOf(od.tadr) : ethAddrOf(od.wadr), claimAddr = sells ? ethAddrOf(od.wadr) : ethAddrOf(od.tadr);
      if (!senderAddr || !claimAddr) return { state: "none", html: "— addresses not both published yet" };
      const dec = token ? (await ethTokenMeta(token) || {}).decimals : 18;
      const amtWei = toUnitsDec(od.wamt, dec == null ? 18 : dec), dl = ethDeadline(od);
      const key = token ? htlcErc20Abi.lockKey(token, od.hsha, claimAddr, senderAddr, dl, amtWei) : htlcAbi.lockKey(od.hsha, claimAddr, senderAddr, dl, amtWei);
      const r = await (await fetch(net.rpc, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_call", params: [{ to: htlc, data: (token ? htlcErc20Abi : htlcAbi).locks(key) }, "latest"] }) })).json();
      const words = String(r.result || "0x").replace(/^0x/, "").match(/.{64}/g) || [];
      const held = words.length ? BigInt("0x" + words[token ? 3 : 2]) : 0n;
      if (held >= amtWei && amtWei > 0n) return { state: "funded", html: `<span style="color:var(--accent2)">verified: ${esc(od.wamt)} ${esc(coinOf(od))} locked under this order's exact terms until ${new Date(dl * 1000).toISOString().slice(0, 16).replace("T", " ")}Z</span>` };
      if (held > 0n) return { state: "short", html: `<span style="color:var(--danger)">UNDERFUNDED: holds less than the agreed amount</span>` };
      const sec = await ethRevealed(od, net.rpc, htlc, key, token);
      return sec ? { state: "claimed", html: `<span style="color:var(--accent2)">claimed</span>`, secret: sec } : { state: "none", html: "— nothing locked under these terms yet" };
    }
    return { state: "none", html: "" };
  } catch (e) { return { state: "error", html: "— could not read the lock: " + esc(String(e.message || e).slice(0, 80)) }; }
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
    const { keccak_256 } = await import("./vendor/noble-sha3.js?v=1");
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
/** Fill #hchk<o> with a verdict on the bound L1 lock: amount, hashlock, claimant, expiry, status. */
async function nadoHtlcCheck(od) {
  const el = $("hchk" + od.o); if (!el) return;
  const h = await nadoHtlc(od);
  if (!h) { el.textContent = "— not found on L1 yet"; return; }
  const sells = od.kind === OTC_ASK, wantClaimant = sells ? od.taker : od.maker;
  const bad = [];
  if (BigInt(h.amount || 0) < od.namtRaw) bad.push(`amount ${rawToNado(String(h.amount || 0))} < ${rawToNado(od.namtRaw.toString())}`);
  if (String(h.hashlock || "").toLowerCase() !== od.hsha) bad.push("hashlock differs");
  if (String(h.claimant || "") !== String(wantClaimant)) bad.push("claimant is not the counterparty");
  if (Number(h.expiry || 0) < od.expn) bad.push(`expires at ${h.expiry}, before this order's ${od.expn}`);
  if (h.status !== "open") bad.push("status " + h.status);
  el.innerHTML = bad.length
    ? `<span style="color:var(--danger)">DOES NOT MATCH: ${esc(bad.join("; "))} — do not fund your side</span>`
    : `<span style="color:var(--accent2)">verified: ${rawToNado(String(h.amount))} NADO, this hashlock, claimable by the counterparty until block ${Number(h.expiry)}</span>`;
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
  if (od.st === 5) return P({ done: "Cancelled", step: 6 });
  if (od.st === 4) return P({ done: "Refunded", step: 6 });
  if (od.st === 1) {
    if (expired) return isMaker ? P({ act: "cancel", label: "Close this expired order", step: 1 }) : P({ done: "Expired", step: 1 });
    return isMaker ? P({ wait: "Waiting for someone to take it", step: 1 }) : P({ act: "fillask", label: "Take this order", step: 1 });
  }
  const nadoOpen = S.nado === "open", nadoClaimed = S.nado === "claimed", fFunded = S.foreign === "funded", fClaimed = S.foreign === "claimed";
  // finished?
  if ((owesNado && fClaimed) || (owesF && nadoClaimed) || (od.st === 3 && (owesNado ? fClaimed || !!S.secret : nadoClaimed))) return P({ done: "Swap complete", step: 6 });
  // deadlines: reclaim what is yours
  if (owesNado && expired && od.hid && nadoOpen) return P({ act: "nadorefund", label: `Reclaim your ${nado}`, step: 5 });
  if (owesF && fexp && fFunded) return P({ act: refundF, label: `Reclaim your ${fam}`, step: 5 });
  if (expired || fexp) return P({ wait: "Expired — each side reclaims its own lock", step: 5 });
  // a fill costs nothing: if the taker never bound the NADO leg within the fill window, the maker may
  // release the order back to open (contract: release). Before that, say how long is left.
  if (isMaker && !od.hid) {
    const fillh = Number(od.fillh || 0), left = fillh ? fillh + 600 - (dapp.cursor || 0) : 600;
    const takerOwesNado = !sells;
    if (fillh && left <= 0 && (takerOwesNado || !fFunded)) return P({ act: "release", label: "Release this order — the taker never locked", step: 2 });
    if (takerOwesNado && !nadoOpen) return P({ wait: `Waiting for the taker to lock ${nado} (they have ~${blocksToTime(Math.max(0, left))} left, then you can release)`, step: 3 });
  }
  // the secret-holder (the maker) funds FIRST: ASK = maker's NADO, BID = maker's foreign coin
  if (sells) {
    if (isMaker) {
      if (!od.hid) return P({ act: "nadolock", label: `Lock ${nado}`, step: 2 });
      if (!fFunded) return P({ wait: `Waiting for the taker to lock ${fam}`, step: 3, hint: S.foreign === "short" ? "their lock is short — do not claim" : "" });
      if (S.secret) return P({ act: claimF, label: `Claim ${fam}`, auto: true, step: 4 });
      return P({ wait: "Your swap secret is not in this browser — restore it from your backup", step: 4 });
    }
    if (isTaker) {
      if (!od.hid || !nadoOpen) return P({ wait: `Waiting for the maker to lock ${nado}`, step: 2 });
      if (!fFunded && !fClaimed) return P({ act: fundAct, label: `Lock ${fam}`, step: 3, hint: S.foreign === "short" ? "your lock is short of the agreed amount" : "" });
      if (!S.secret) return P({ wait: `Waiting for the maker to claim the ${coin} — that reveals the secret`, step: 4 });
      return P({ act: "nadoclaim", label: `Claim ${nado}`, auto: true, step: 5 });
    }
  } else {
    if (isMaker) {
      if (!fFunded && !fClaimed) return P({ act: fundAct, label: `Lock ${fam}`, step: 2 });
      if (!od.hid || !nadoOpen) return P({ wait: `Waiting for the taker to lock ${nado}`, step: 3 });
      if (S.secret) return P({ act: "nadoclaim", label: `Claim ${nado}`, auto: true, step: 4 });
      return P({ wait: "Your swap secret is not in this browser — restore it from your backup", step: 4 });
    }
    if (isTaker) {
      if (!fFunded) return P({ wait: `Waiting for the maker to lock ${fam}`, step: 2, hint: S.foreign === "short" ? "their lock is short — do not lock yours" : "" });
      if (!od.hid) return P({ act: "nadolock", label: `Lock ${nado}`, step: 3 });
      if (!S.secret) return P({ wait: `Waiting for the maker to claim the NADO — that reveals the secret`, step: 4 });
      return P({ act: claimF, label: `Claim ${fam}`, auto: true, step: 5 });
    }
  }
  return P({ wait: "…", step: 0 });
}
const STEPS = (od) => ["Posted", "Taken", (od.kind === OTC_ASK ? "NADO" : coinOf(od)) + " locked", (od.kind === OTC_ASK ? coinOf(od) : "NADO") + " locked", "Claimed", "Done"];
function stepperHtml(od, plan) {
  const names = STEPS(od), cur = Math.max(1, Math.min(6, plan.step || 1));
  return `<div class="steps">${names.map((n, i) => `<span class="stp${i + 1 < cur ? " done" : i + 1 === cur ? " cur" : ""}">${esc(n)}</span>`).join("")}</div>`;
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
        alertBar(`${plan.label} — signing…`);
        try { await otcAction(plan.act, od.o, null); } catch (e) {}
      }
      // settle is bookkeeping (publishes the secret on NADO, returns tips): value-free, so a wallet with
      // auto-sign on signs it silently; either party may send it
      if (od.st === 2 && S.secret && S.nado !== "open" && !autoRecently("settle:" + od.o, 180000)) {
        autoMark("settle:" + od.o);
        dapp.call("settle", [od.o, ...otcLimbs(S.secret)], null, "Settling #" + od.o + "…", { otc: od.o }, { cid: OTC_CID });
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
  const head = sells
    ? `sells <b>${rawToNado(od.namtRaw.toString())} NADO</b> for <b>${esc(od.wamt)} ${chain}</b>`
    : `buys <b>${rawToNado(od.namtRaw.toString())} NADO</b> for <b>${esc(od.wamt)} ${chain}</b>`;
  const pill = od.st === 1
    ? (expired ? '<span class="pill warn">expired</span>' : '<span class="pill">open</span>')
    : `<span class="pill${od.st === 2 ? " warn" : ""}">${OTC_ST[od.st] || od.st}</span>`;
  const party = isMaker || isTaker;
  const acts = [];
  const settler = sells ? isTaker : isMaker;            // settle pays ASK->taker, BID->maker (otc.py)
  if (od.st === 2 && !expired && settler) acts.push(`<button class="primary" data-otc="settle" data-o="${od.o}">Settle…</button>`);
  if (od.st === 1 && !expired && !isMaker && me && !mine) acts.push(`<button class="primary" data-otc="fillask" data-o="${od.o}">Fill…</button>`);
  if (od.st === 1 && !expired && isMaker) acts.push(`<button class="ghost" data-otc="cancel" data-o="${od.o}">Cancel</button>`);
  if ((od.st === 1 || od.st === 2) && expired && party) acts.push(`<button class="ghost" data-otc="expire" data-o="${od.o}">Reclaim</button>`);
  if ((od.st === 1 || od.st === 2) && !expired && party) acts.push(`<button class="ghost" data-otc="boost" data-o="${od.o}">Tip</button>`);
  const owesNado = od.st === 2 && (sells ? isMaker : isTaker);   // who provides the NADO side of this swap
  const getsNado = (sells ? isTaker : isMaker);                   // ... and who takes it with the secret
  if (od.st >= 2 && od.st !== 4 && od.hid && getsNado && !expired) acts.unshift(`<button class="primary" data-otc="nadoclaim" data-o="${od.o}">Claim the NADO…</button>`);
  // the counterparty's foreign claim needs the secret: a BID taker can have it as soon as the NADO lock
  // is claimed on L1 (the row reads the preimage back), not only after the maker also calls settle
  const secretMayExist = od.st === 3 || (od.st === 2 && !!od.hid);
  if (owesNado && !expired && !od.hid) {
    acts.unshift(`<button class="primary" data-otc="nadolock" data-o="${od.o}">Lock the NADO…</button>`);
    acts.push(`<button class="ghost" data-otc="nadobind" data-o="${od.o}">I already locked it</button>`);
  }
  const isEth = chainOf(od) === "eth";
  if (isEth && tokAddrOf(od) && !erc20Names[tokAddrOf(od).toLowerCase()] && ethProv()) ethTokenMeta(tokAddrOf(od));
  const ethSender = isEth && (sells ? isTaker : isMaker), ethClaimer = isEth && (sells ? isMaker : isTaker);
  if (isEth && od.st === 2 && ethSender) acts.push(`<button class="primary" data-otc="ethfund" data-o="${od.o}">Lock the ETH…</button>`);
  if (isEth && ((sells && od.st === 2) || (!sells && secretMayExist)) && ethClaimer) acts.unshift(`<button class="primary" data-otc="ethclaim" data-o="${od.o}">Claim the ETH…</button>`);
  if (isEth && od.st >= 2 && ethSender && Date.now() / 1000 >= Number(od.expf)) acts.push(`<button class="ghost" data-otc="ethrefund" data-o="${od.o}">Reclaim ETH</button>`);
  const isSol = chainOf(od) === "sol";
  const solSender = isSol && (sells ? isTaker : isMaker), solClaimer = isSol && (sells ? isMaker : isTaker);
  if (isSol && od.st === 2 && solSender) acts.push(`<button class="primary" data-otc="solfund" data-o="${od.o}">Lock the ${chain}…</button>`);
  if (isSol && ((sells && od.st === 2) || (!sells && secretMayExist)) && solClaimer) acts.unshift(`<button class="primary" data-otc="solclaim" data-o="${od.o}">Claim the ${chain}…</button>`);
  if (isSol && od.st >= 2 && solSender && Date.now() / 1000 >= Number(od.expf)) acts.push(`<button class="ghost" data-otc="solrefund" data-o="${od.o}">Reclaim ${chain}</button>`);
  const btc = chainOf(od) === "btc" ? btcInfo(od) : null;
  const btcFunder = chainOf(od) === "btc" && (sells ? isTaker : isMaker);
  const btcClaimer = chainOf(od) === "btc" && (sells ? isMaker : isTaker);
  if (btc && od.st === 2 && btcClaimer && sells && otcRec(od.o).s) acts.unshift(`<button class="primary" data-otc="btcclaim" data-o="${od.o}">Claim the BTC…</button>`);
  if (btc && secretMayExist && btcClaimer && !sells) acts.unshift(`<button class="primary" data-otc="btcclaim" data-o="${od.o}">Claim your BTC…</button>`);
  if (btc && od.st >= 2 && btcFunder && Date.now() / 1000 >= Number(od.expf)) acts.push(`<button class="ghost" data-otc="btcrefund" data-o="${od.o}">Reclaim BTC</button>`);
  let detail = "";
  if (mine) {
    let hint = "";
    if (od.st === 1 && !expired && isMaker) hint = "Waiting for a taker — your funds stay reclaimable. Cancel any time.";
    else if (od.st === 2 && !expired) {
      const foreign = chain;
      const isBtc = chainOf(od) === "btc";
      const lockF = isBtc ? `send the ${foreign} to the address below` : `press Lock the ${foreign} (your wallet pays it into the swap)`;
      const claimF = isBtc ? `press Claim the ${foreign}` : `press Claim the ${foreign} — your wallet signs it`;
      if (sells && isMaker && !od.hid) hint = `Next: press Lock the NADO — it escrows your NADO on the main chain under this swap's hashlock, takeable only by the taker and only with the secret.`;
      else if (sells && isMaker) hint = `Next: once the taker's ${foreign} lock is CONFIRMED and holds the agreed amount, ${claimF}. Claiming reveals the secret, and that completes your side.`;
      else if (sells && isTaker && !od.hid) hint = `Next: wait — the maker must lock their NADO on the main chain first. Do not send any ${foreign} until that lock shows as verified below.`;
      else if (sells && isTaker) hint = `Next: once the NADO lock below reads "verified", ${lockF}. When the maker claims it the secret becomes public — then press Claim the NADO.`;
      else if (!sells && isMaker && !od.hid) hint = `Next: ${lockF} FIRST — you hold the secret, so your lock goes in before the taker's. The taker locks the NADO once they have checked yours.`;
      else if (!sells && isMaker) hint = `Next: once the NADO lock below reads "verified", press Claim the NADO — that reveals the secret, and the taker claims your ${foreign} with it.`;
      else if (!sells && isTaker && !od.hid) hint = `Next: wait for the maker's ${foreign} lock and CHECK it (the agreed amount, this hashlock, a deadline past this order's NADO expiry). Only then press Lock the NADO.`;
      else if (!sells && isTaker) hint = `Next: wait. When the maker claims your NADO the secret becomes public, and Claim the ${foreign} works here.`;
    } else if ((od.st === 1 || od.st === 2) && expired) hint = "Expired — reclaim each leg on its own chain (the NADO leg is an L1 HTLC refund).";
    if (hint) detail += `<div class="small mt" style="color:var(--accent2)">${hint}</div>`;
    if (chainOf(od) === "btc" && od.st >= 2 && (isMaker || isTaker)) {
      const b = btcInfo(od);
      if (b) detail += `<div class="small mt">${btcFunder && od.st === 2 ? `<b>Send exactly ${esc(od.wamt)} BTC to:</b><br>` : `Swap address: `}<span class="mono" style="word-break:break-all">${b.addr}</span>
        <a href="#" data-otc="btccopy" data-o="${od.o}">copy</a> · <a href="#" data-otc="btcverify" data-o="${od.o}">verify</a>
        <span id="btcv${od.o}" class="dim"></span></div>`;
      else if (!btcParts(od)) detail += `<div class="small dim mt">The counterparty's client didn't publish a Bitcoin key — finish this leg with scripts/otc_btc_leg.py.</div>`;
    }
    if ((chainOf(od) === "eth" || chainOf(od) === "sol") && od.st === 2 && (isMaker || isTaker)) {
      detail += `<div class="small mt">${esc(coinOf(od))} lock: <span id="fchk${od.o}" class="dim">checking…</span></div>`;
      setTimeout(() => foreignLockCheck(od), 0);
    }
    if (chainOf(od) === "eth" && od.st >= 2 && (isMaker || isTaker) && !ethProv()) detail += ethCliHint(od);
    if (chainOf(od) === "sol" && od.st >= 2 && (isMaker || isTaker)) {
      if (!solProgramOf(od)) detail += `<div class="small dim mt">No swap program is deployed on ${esc((netOf(od) || {}).label)} yet — this order cannot be completed here.</div>`;
      else if (!solHas()) detail += solCliHint(od);
    }
    const rec0 = otcRec(od.o);
    if ((rec0.k || rec0.s) && (od.st === 1 || od.st === 2))
      detail += `<div class="small dim mt"><a href="#" data-otc="showsecret" data-o="${od.o}">Back up this swap</a> — without it a lost browser means lost funds.</div>`;
    const secret = rec0.s;
    if (secret && (od.st === 1 || od.st === 2))
      detail += `<div class="small dim mt">Your swap secret: <span class="mono">${secret.slice(0, 16)}…</span>
        <a href="#" data-otc="showsecret" data-o="${od.o}">back up</a> — keep a copy: it is all this swap
        needs on any device (never share it before the counterparty's lock is CONFIRMED).</div>`;
    if (od.st === 2 && od.hid) {
      detail += `<div class="small mt">NADO leg locked on L1: <span class="mono">${esc(String(od.hid)).slice(0, 24)}…</span> <span id="hchk${od.o}" class="dim">checking…</span></div>`;
      setTimeout(() => nadoHtlcCheck(od), 0);
    }
    if (od.st === 2 && od.fref && od.fref !== "pending") detail += `<div class="small dim mt">Foreign leg ref: <span class="mono">${esc(od.fref).slice(0, 40)}</span>
      · counterparty ${esc(disp(isMaker ? od.taker : od.maker))}</div>`;
    if (od.st === 3 && od.limbs.some((x) => Number(x) > 0)) {
      const rs = otcSecretFromLimbs(od.limbs);
      detail += `<div class="small mt">Revealed secret (claims the ${chain} HTLC): <span class="mono" style="word-break:break-all">${rs}</span></div>`;
    }
  }
  let main = "", more = "";
  if (mine && party && od.kind !== OTC_INTRA) {
    const S = SWAP[od.o] || { nado: "none", foreign: "none", secret: null };
    if (!SWAP[od.o] || Date.now() - SWAP[od.o].at > 8000) probeSwap(od).then(() => render());
    const plan = swapPlan(od, S);
    const primary = plan.done ? `<span class="pill">${esc(plan.done)}</span>`
      : plan.act ? `<button class="primary" data-otc="${plan.act}" data-o="${od.o}">${esc(plan.label)}${plan.auto ? " (automatic)" : ""}</button>`
      : `<span class="waiting"><span class="spin"></span>${esc(plan.wait || "")}</span>`;
    main = stepperHtml(od, plan) + `<div class="nextact">${primary}${plan.hint ? `<div class="small" style="color:var(--danger)">${esc(plan.hint)}</div>` : ""}</div>`;
    more = `<details class="more"><summary>More</summary><div>${detail}<div class="loanacts" style="flex-direction:row;flex-wrap:wrap;margin-top:8px">${acts.join("")}</div></div></details>`;
    acts.length = 0; detail = "";
  }
  return `<div class="loan"><div class="loanmain">
      <div class="loantop">${pill} <b>#${od.o}</b> ${esc(disp(od.maker))} ${head}</div>
      ${main}
      <div class="loanterms">${od.prem > 0n ? `maker has ${rawToNado(od.prem.toString())} NADO at stake · ` : ""}${od.bnty > 0n ? `<span class="pill">+${rawToNado(od.bnty.toString())} NADO tip</span> · ` : ""}hashlock <span class="dim">${esc(od.hsha).slice(0, 18)}…</span> ·
        ${od.st <= 2 ? (expired ? "refundable now" : `expires in ${left} blocks (~${blocksToTime(left)})`) : ""}
        ${od.expf ? `· ${esc(coinOf(od))} deadline ${new Date(Number(od.expf) * 1000).toISOString().slice(0, 16).replace("T", " ")}Z` : ""}</div>
      <div class="loanwho dim small">on <b>${esc((netOf(od) || {}).label || od.wch)}</b> · ${sells ? "maker receives" : "taker receives"} ${chain} at ${esc((sells ? od.wadr : od.tadr || od.wadr).split("|")[0]) || "(swap key published)"}</div>
      ${detail}${more}
    </div><div class="loanacts">${acts.join("")}</div></div>`;
}
function renderOtc() {
  const book = $("otcBook"), mine = $("otcMine");
  if (!book || !mine) return;
  const all = otcOrders(), me = dapp.me;
  const open = all.filter((x) => x.st === 1 && x.kind !== OTC_INTRA && mktKeyOf(x) === xsel && otcLeft(x) > 0);
  book.innerHTML = open.length ? open.map((x) => otcRow(x, false)).join("")
    : `<p class="small dim">No open orders. Post one — the book is permissionless.</p>`;
  const my = all.filter((x) => me && x.kind !== OTC_INTRA && (x.maker === me || x.taker === me));
  mine.innerHTML = my.length ? my.map((x) => otcRow(x, true)).join("")
    : `<p class="small dim">Nothing yet — post or fill an order.</p>`;
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
      known[t.toLowerCase()] = { sym: (m && m.symbol) || "token", dec: (m && m.decimals) || 18 };
    }
  }
  const opts = [`<option value="">${esc((NETS[net] || {}).coin || "the coin")} itself — no token</option>`]
    .concat(Object.keys(known).map((a) => `<option value="${a}">${esc(known[a].sym)} · ${a.slice(0, 10)}…</option>`))
    .concat([`<option value="?">another token — paste its address</option>`]);
  const sig = opts.join("");
  if (tp.dataset.sig !== sig) { tp.dataset.sig = sig; tp.innerHTML = sig; }
}
function showTokenInfo(text, bad) {
  const el = $("otcTokenInfo");
  if (el) { el.innerHTML = text ? `<span style="color:var(--${bad ? "danger" : "accent2"})">${esc(text)}</span>` : ""; }
}
async function verifyPastedToken() {
  const a = (($("otcToken") || {}).value || "").trim(), net = ($("otcNet") || {}).value;
  if (!/^0x[0-9a-fA-F]{40}$/.test(a)) return showTokenInfo("A token address is 0x followed by 40 hex characters.", true);
  if (!ethProv()) return showTokenInfo("Connect an Ethereum wallet to check this token against the chain.", true);
  showTokenInfo("checking the contract…");
  try {
    const { chain } = await ethConnect();
    if (chain !== (NETS[net] || {}).evm) return showTokenInfo(`Switch your wallet to ${(NETS[net] || {}).label} to check a token there.`, true);
    const meta = await ethTokenMeta(a);
    if (!meta || meta.symbol === "TOKEN") return showTokenInfo("That address did not answer as an ERC-20 — check it on a block explorer.", true);
    tokenRemember(net, a, meta);
    fillTokenPicker();
    // A symbol is whatever the contract SAYS it is; the address is the only identity that matters.
    showTokenInfo(`${meta.symbol} · ${meta.decimals} decimals · ${a} — any contract can claim any symbol, so check the address.`);
  } catch (e) { showTokenInfo(String((e && e.message) || e).slice(0, 120), true); }
}

// The segmented switch carries the short label; the sentence explaining it lives underneath and follows
// the choice, instead of being crammed into a button.
function kindHint() {
  const el = $("otcKindHint"), k = (($("otcKind") || {}).value) || "1";
  const netK = ($("otcNet") || {}).value, tp = $("otcTokenPick");
  const tokSel = tp && tp.value && tp.value !== "?" ? (tokensFor(netK)[tp.value] || {}).sym || "the token" : "";
  const coin = tokSel || (NETS[netK] || {}).coin || "the coin";
  if (el) el.textContent = k === "1"
    ? `You give NADO and receive ${coin}. You generate the swap secret, so you finish the swap.`
    : `You give ${coin} and receive NADO. You generate the swap secret; your ${coin} lock must outlast the taker's NADO lock.`;
}

async function otcPost() {
  const kind = Number($("otcKind").value);
  const raw = (() => { try { return BigInt(nadoToRaw(($("otcNado").value || "").trim())); } catch (e) { return 0n; } })();
  const netSelV = $("otcNet").value, chain = (NETS[netSelV] || {}).chain;
  const tp2 = $("otcTokenPick");
  const tokenV = (tp2 && tp2.value && tp2.value !== "?") ? tp2.value : ((($("otcToken") || {}).value) || "").trim();
  if (tokenV && chain === "eth" && !/^0x[0-9a-fA-F]{40}$/.test(tokenV)) return alertBar("A token address looks like 0x followed by 40 hex characters.");
  if (tokenV && chain === "sol" && !isB58Addr(tokenV)) return alertBar("A Solana token is named by its mint address (32–44 base58 characters).");
  if (tokenV && !netSupportsTokens(netSelV)) return alertBar(`Token swaps are not available on ${(NETS[netSelV] || {}).label} yet.`);
  const net = tokenV ? netSelV + "|" + tokNorm(tokenV) : netSelV;   // the token rides in the network field
  const famt = ($("otcFAmt").value || "").trim(), faddr = ($("otcFAddr").value || "").trim();
  const blocks = Math.floor(Number($("otcExpiry").value || 0));
  if (raw <= 0n) return alertBar("Enter the NADO amount.");
  if (!famt || !(Number(famt) > 0)) return alertBar("Enter the foreign amount.");
  if (!faddr) return alertBar("Enter your " + (NETS[netSelV] || {}).label + " address.");
  // Validate the receiving address by chain NOW: a bad one is otherwise discovered only when the other
  // side locks to it (an EVM lock to a malformed address pads to 0x000…0 — unclaimable by anyone).
  if (chain === "eth" && !/^0x[0-9a-fA-F]{40}$/.test(faddr)) return alertBar("An Ethereum address is 0x followed by 40 hex characters.");
  if (chain === "sol" && !isB58Addr(faddr)) return alertBar("That is not a Solana address (32–44 base58 characters).");
  if (chain === "btc") { try { await addressToScript(faddr, (NETS[netSelV] || {}).hrp || "bc"); } catch (e) { return alertBar("That is not a valid " + (NETS[netSelV] || {}).label + " address: " + String(e.message || e)); } }
  faddrSet(netSelV, faddr);                                // typed once — reused for every future swap on this network
  if (!(blocks >= 20 && blocks <= 900000)) return alertBar("Expiry must be 20 … 900000 blocks.");
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
    return alertBar(`That expiry is too short for a ${(NETS[$("otcNet").value] || {}).coin || "cross-chain"} swap — use at least ${Math.ceil((FOREIGN_MIN_S + FOREIGN_MARGIN_S + 1800) / 6)} blocks.`);
  // §6.3 is KIND-DEPENDENT (otc.py post): the maker generates the secret for both kinds, and the leg the
  // maker FUNDS must outlast the leg they CLAIM. ASK: maker funds NADO, so the foreign deadline sits
  // inside the NADO window. BID: maker funds the foreign leg, so its deadline sits PAST the NADO window.
  let expf;
  if (kind === OTC_ASK) expf = Math.floor(nowSec + (FOREIGN_MIN_S + windowS - FOREIGN_MARGIN_S) / 2);
  else {
    expf = Math.floor(nowSec + windowS + FOREIGN_MARGIN_S + 3600);
    if (expf > nowSec + FOREIGN_MAX_S)
      return alertBar(`A buy order's ${(NETS[$("otcNet").value] || {}).coin || "foreign"} lock must outlast its NADO expiry, and that chain allows at most 30 days — use at most ${Math.floor((FOREIGN_MAX_S - FOREIGN_MARGIN_S - 3600) / 6)} blocks.`);
  }
  if (expf > nowSec + FOREIGN_MAX_S) expf = nowSec + FOREIGN_MAX_S;   // ASK: clamp long NADO windows; the margin still holds
  const expn = (dapp.cursor || 0) + blocks;
  const box = $("otcSecretBox"); if (box) { box.classList.remove("hidden"); $("otcSecretHex").textContent = sHex + (kp ? "  ·  BTC key: " + kp.k : ""); }
  // No VALUE: the NADO leg of a cross-chain swap is escrowed in an L1 HTLC under the SAME SHA-256
  // hashlock as the foreign leg, never in this contract (see otc.py WHERE THE MONEY SITS).
  dapp.call("post", [o, kind, raw, net, famt, packed, hsha, ...vmParts, expn, expf],
            null, "Posting order #" + o + "…", { otc: o }, { cid: OTC_CID });
}
async function runAction(btn, fn) {
  if (!btn) return fn();
  if (btn.dataset.busy) return;                        // ignore the double-click instead of firing twice
  const was = btn.textContent;
  btn.dataset.busy = "1"; btn.disabled = true; btn.textContent = "working…";
  try { return await fn(); }
  catch (e) { alertBar((e && e.message) || String(e)); }   // a click must never end in silence
  finally { delete btn.dataset.busy; btn.disabled = false; btn.textContent = was; }
}
async function otcAction(what, o, btn) {
  const od = otcOrders().find((x) => x.o === o);
  if (!od) return;
  if (what === "showsecret") {
    const r = otcRec(o);
    // Everything needed to rebuild the swap on another device — the key alone is not enough, because the
    // witness script also needs the counterparty's pubkey, the hashlock and the deadline (audit).
    const b = chainOf(od) === "btc" ? btcInfo(od) : null;
    const blob = JSON.stringify(Object.assign({ order: o, network: netKeyOf(od), kind: od.kind,
      hashlock: od.hsha, deadline: od.expf, amount: od.wamt },
      r.s ? { secret: r.s } : {}, r.k ? { key: r.k } : {}, r.pub ? { pubkey: r.pub } : {},
      b ? { script: b.script, address: b.addr } : {}));
    if (r.s || r.k) await uiPrompt({ title: `Back up swap #${o}`,
      body: "Copy this somewhere safe — it is everything this swap needs to be finished or reclaimed from another device.",
      value: blob, confirmText: "Done" });
    return;
  }
  if (what === "cancel") return dapp.call("cancel", [o], null, "Cancelling #" + o + "…", { otc: o }, { cid: OTC_CID });
  if (what === "boost") {
    // §8: attach a NADO bounty ANYONE can win by finishing this order (settle / expire / atomic fill).
    // It makes watchtowers work for you; cancel returns it to the maker.
    const typed = ((await uiPrompt({ title: "Tip whoever finishes this swap",
      body: "Paid to whoever completes or reclaims this order — you, the counterparty, or any watchtower running unattended.",
      placeholder: "amount in NADO" })) || "").trim();
    const amt = (() => { try { return BigInt(nadoToRaw(typed)); } catch (e) { return 0n; } })();
    if (amt <= 0n) return;
    return dapp.call("boost", [o], amt, "Boosting #" + o + "…", { otc: o }, { cid: OTC_CID });
  }
  if (what === "expire") return dapp.call("expire", [o], null, "Reclaiming #" + o + "…", { otc: o }, { cid: OTC_CID });
  if (what === "fillask") {
    // §6.3 from the TAKER's side (the contract enforces the same rule; this is the plain-language refusal).
    // ASK: the taker funds the foreign leg, so its deadline must sit safely INSIDE the NADO window.
    // BID: the taker funds the NADO leg, so the maker's foreign deadline must sit safely PAST it.
    const nowS = (dapp.chainNow && dapp.chainNow()) || Math.floor(Date.now() / 1000);
    const nadoWindowS = Math.max(0, (od.expn - (dapp.cursor || 0))) * 6;
    const fdl = Number(od.expf) || 0;
    const okAsk = fdl > nowS + 1800 && fdl < nowS + nadoWindowS * 0.75;
    const okBid = fdl > nowS + nadoWindowS + 7200;
    if (od.kind === OTC_ASK ? !okAsk : !okBid) {
      return alertBar("This order's foreign deadline does not line up with its NADO expiry — filling it "
        + "could let the maker reclaim their own lock and still take yours. Not safe to fill.");
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
        catch (e) { return alertBar("Your Ethereum wallet did not connect (" + ((e && e.message) || e) + "). Approve the connection in the wallet and click Fill again."); }
      } else {
        // No wallet extension: ASK where the coin should go. Never silently invent a receive key —
        // a taker who did not know a key was generated for them cannot back it up, and the coin it
        // receives is only as safe as this browser's storage.
        const typed = ((await uiPrompt({ title: `Where should the ${coin} be paid?`,
          body: `Enter an ${(netOf(od) || {}).label} address you control — it receives the ${od.wamt} ${coin} when the swap completes. Leave it empty to let this page keep a fresh key for you (you must then back it up from the row).`,
          value: faddrGet(netKeyOf(od)) || "", placeholder: "0x… address" })) || "").trim();
        if (typed && !/^0x[0-9a-fA-F]{40}$/.test(typed)) return alertBar("An Ethereum address is 0x followed by 40 hex characters.");
        if (typed) { myf = typed; faddrSet(netKeyOf(od), typed); }
        else { const ek = ethKeypair(); otcSaveRec(o, { k: ek.k }); myf = ek.addr;
          alertBar(`This page generated a receive key for you (${ek.addr.slice(0, 10)}…). Back it up from the row before the swap completes.`); }
      }
    } else if (ch === "sol" && solHas()) {
      try { myf = (await (await solMod()).solWalletConnect()).address; }   // the taker's own Solana account
      catch (e) { myf = ""; }
      if (!myf) return alertBar("Connect your Solana wallet to fill this order — it is the account the swap pays.");
    } else {
      myf = faddrGet(netKeyOf(od));                    // typed once per network, then never again
      if (!myf) {
        myf = await uiPrompt({ title: `Your ${(netOf(od) || {}).label || coin} address`,
          body: "Where this swap pays you on that chain. Saved for next time.", placeholder: "address" });
        if (!myf) return;
        faddrSet(netKeyOf(od), myf);
      }
    }
    // a BID fill carries the taker bond (1% of the NADO, min 0.01) — back the moment you lock the NADO,
    // to the maker if you never do. This is what makes a fill cost something.
    const bondRaw = od.kind === OTC_BID ? (od.namtRaw * 100n / 10000n > 100000000n ? od.namtRaw * 100n / 10000n : 100000000n) : 0n;
    if (bondRaw > 0n && !await uiConfirm({ title: "Take this order",
      body: `A ${rawToNado(bondRaw.toString())} NADO bond is held while you complete your side. It comes back in full when you lock the ${rawToNado(od.namtRaw.toString())} NADO; if you never do, it goes to the maker.`,
      rows: [{ k: "Bond", v: rawToNado(bondRaw.toString()) + " NADO" }], confirmText: "Take" })) return;
    dapp.call("fill", [o, myf, fref], bondRaw > 0n ? bondRaw : null, "Filling #" + o + "…", { otc: o }, { cid: OTC_CID });
    return;
  }
  if (what === "fillintra") {
    dapp.call("fill_intra", [o], od.want, "Filling limit order #" + o + "…", { otc: o },
              od.wast !== "0" ? { cid: OTC_CID, asset: od.wast } : { cid: OTC_CID });
    return;
  }
  if (what === "nadolock") {
    // The NADO leg of the swap: an L1 HTLC under the order's OWN SHA-256 hashlock, so the same secret
    // opens it and the foreign lock. The order-book contract never holds this money.
    const sells = od.kind === OTC_ASK;
    const owes = sells ? od.maker : od.taker;            // ASK: the maker sells NADO; BID: the taker provides it
    const to = sells ? od.taker : od.maker;
    if (dapp.me !== owes) return alertBar("The NADO side of this swap is not yours to lock.");
    if (!/^[0-9a-f]{46}$/.test(String(to))) return alertBar("The counterparty's NADO address isn't visible yet — wait for their fill to land.");
    const blocks = Math.max(1, od.expn - (dapp.cursor || 0));
    if (!await uiConfirm({ title: "Lock the NADO side",
      body: sells ? "They can only take it with the swap secret, and only before it expires — after that you reclaim it yourself."
                  : `Lock ONLY after you have checked the maker's ${coinOf(od)} lock: the agreed amount, this order's hashlock, and a deadline past this order's NADO expiry. The maker holds the secret — if their lock is missing or short, they can take your NADO and give nothing.`,
      rows: [{ k: "Amount", v: rawToNado(od.namtRaw.toString()) + " NADO" },
             { k: "Claimable by", v: String(to).slice(0, 16) + "…" },
             { k: "You can reclaim after", v: blocks + " blocks" }],
      confirmText: "Lock" })) return;
    dapp.htlcLock({ claimant: to, hashlock: od.hsha, amount: od.namtRaw, blocks }, { otc: o, phase: "htlc_lock" });
    return;
  }
  if (what === "btcsend") {                             // Bitcoin has no wallet extension to call: show where to send
    const b = btcInfo(od); if (!b) return alertBar("Still deriving the Bitcoin address — try again in a second.");
    await uiPrompt({ title: `Send exactly ${od.wamt} ${coinOf(od)} to`, body: "From any Bitcoin wallet. The row updates itself once the coin confirms.", value: b.addr, confirmText: "Done" });
    return;
  }
  if (what === "nadorefund") {                          // the L1 HTLC refund: an L1 tx signed by the wallet
    if (!od.hid) return alertBar("No NADO lock is recorded on this order.");
    if (dapp.htlcRefund) return dapp.htlcRefund({ htlcId: od.hid }, { otc: o, phase: "htlc_refund" });
    return alertBar("Reclaim the NADO lock from your wallet's Swap tab (lock " + od.hid.slice(0, 12) + "…).");
  }
  if (what === "release") return dapp.call("release", [o], null, "Releasing #" + o + "…", { otc: o }, { cid: OTC_CID });
  if (what === "nadoclaim") {
    // The NADO leg pays out through an L1 htlc_claim, not through this contract. ASK: the taker claims once
    // the maker revealed the secret on the foreign chain. BID: the maker claims with their own secret — and
    // that reveal is what lets the taker claim the foreign leg.
    const sells = od.kind === OTC_ASK;
    if (dapp.me !== (sells ? od.taker : od.maker)) return alertBar("The NADO side of this swap is not yours to claim.");
    let s = await otcKnownSecret(od);
    if (!s && sells) {
      alertBar(`Looking up the revealed secret on ${coinOf(od)}…`);
      const ch = chainOf(od);
      s = ch === "btc" ? await btcFoundSecret(od) : ch === "eth" ? await ethFoundSecret(od) : ch === "sol" ? await solFoundSecret(od) : null;
    }
    if (!s) s = ((await uiPrompt({ title: "Paste the swap secret",
      body: "The 64-character secret — this page could not find it on any chain yet.", placeholder: "64 hex characters" })) || "").trim().toLowerCase();
    if (!/^[0-9a-f]{64}$/.test(s || "") || (await sha256Hex(s)) !== od.hsha) return alertBar("That secret does not match this order's hashlock.");
    const h = await nadoHtlc(od);
    if (h && h.status !== "open") return alertBar(`That NADO lock is already ${h.status}.`);
    if (!sells && Number(od.expf) && Math.floor(Date.now() / 1000) > Number(od.expf) - 7200)
      return alertBar("Too close to your own foreign deadline — claiming now reveals the secret while the taker may no longer have time to claim your lock.");
    dapp.htlcClaim({ htlcId: od.hid, preimage: s }, { otc: o, phase: "htlc_claim" });
    return;
  }
  if (what === "nadobind") {
    const id = ((await uiPrompt({ title: "Record your NADO lock",
      body: "Paste the transaction id of the L1 HTLC you created, so the counterparty can find and check it.",
      placeholder: "transaction id" })) || "").trim();
    if (!/^[0-9a-f]{16,}$/.test(id)) return alertBar("That doesn't look like a transaction id.");
    return dapp.call("bind", [o, id], null, "Recording the NADO lock…", { otc: o }, { cid: OTC_CID });
  }
  if (what === "btccopy") { const b = btcInfo(od); if (b) navigator.clipboard.writeText(b.addr).then(() => alertBar("Address copied.")); return; }
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
      if (!s && chainOf(od) === "btc") { alertBar("Looking up the revealed secret on Bitcoin…"); s = await btcFoundSecret(od); }
      if (!s && chainOf(od) === "eth") { alertBar("Looking up the revealed secret on Ethereum…"); s = await ethFoundSecret(od); }
      if (!s && chainOf(od) === "sol") { alertBar("Looking up the revealed secret on Solana…"); s = await solFoundSecret(od); }
      if (!s) s = ((await uiPrompt({ title: "Paste the swap secret",
        body: "The 64-character secret revealed when the other leg was claimed — this page could not find it automatically.",
        placeholder: "64 hex characters" })) || "").trim().toLowerCase();
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
    el.onclick = (ev) => { ev.preventDefault();
      runAction(el.tagName === "BUTTON" ? el : null, () => otcAction(el.getAttribute("data-otc"), Number(el.getAttribute("data-o")), el)); };
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
function priceSeriesAll(id) {                          // the merged series, ignoring the range buttons
  const shared = (sharedPrices[id] || []).map((x) => [x[0] * 1000, x[1]]);
  const local = priceStore()[id] || [];
  const seen = new Set(), all = [];
  const sc = lastSto && /^\d+$/.test(String(id)) ? pScale(poolOf(lastSto, id).asset) : 1;   // pool series: units -> the token's decimals
  for (const pt of shared.concat(local).sort((a, b) => a[0] - b[0])) {
    const k = Math.round(pt[0] / 1000);
    if (seen.has(k)) continue;
    seen.add(k); all.push([pt[0], pt[1] * sc]);
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
const group = (s) => String(s).replace(/^(-?)(\d+)/, (m, sg, d) => sg + d.replace(/\B(?=(\d{3})+(?!\d))/g, ","));
// Compact for tight cells (axis labels, stat tiles): 668.27B reads; 668,269,230,769.23 does not fit.
const fmtShort = (v) => { const a = Math.abs(v); if (!(a >= 1e5)) return fmtPrice(v);
  const u = [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]].find(([k]) => a >= k); return (v / u[0]).toFixed(2) + u[1]; };
const fmtPrice = (v) => v > 0 && v < 1e-6 ? "< 0.000001" : group(v >= 1e15 ? v.toExponential(3) : v >= 1000 ? v.toFixed(2) : v >= 1 ? v.toFixed(4) : v.toPrecision(4));
const fmtAgo = (ts) => { const s = Math.max(0, (Date.now() - ts) / 1000); return s < 90 ? Math.round(s) + "s ago" : s < 5400 ? Math.round(s / 60) + "m ago" : s < 172800 ? Math.round(s / 3600) + "h ago" : Math.round(s / 86400) + "d ago"; };

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
    if (pick.dataset.sig !== opts) { pick.dataset.sig = opts; pick.innerHTML = opts || `<option>no markets yet</option>`; }
    if (sel) pick.value = String(sel);
  }
  gate({ marketCard: !!sel });
  const seg = $("envSeg"); if (seg) seg.classList.add("hidden");   // the mainnet/testnet switch belongs to cross-chain markets only
  if (!sel || !lastSto) return;
  const p = poolOf(lastSto, sel);
  const live = p.rn > 0n && p.rt > 0n && p.sup > 0n;
  const price = live ? midPrice(p) : 0;               // in the token's own decimals, like every other figure
  const sym = tokSym(p.asset);
  $("mktPair").textContent = `${sym} / NADO`;
  $("mktPrice").textContent = live ? fmtShort(price) : "—";
  $("mktPrice").title = live ? fmtPrice(price) + " " + sym + " per NADO" : "";
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
    ["1 NADO buys", live ? fmtShort(price) + " " + esc(sym) : "—"],
    [`1 ${esc(sym)} buys`, live ? fmtShort(1 / price) + " NADO" : "—"],
    ["24h high", st24 ? fmtShort(st24.hi) : "—"],
    ["24h low", st24 ? fmtShort(st24.lo) : "—"],
    ["NADO in pool", group(fromUnits(p.rn))],
    [esc(sym) + " in pool", fmtShort(Number(tokFromUnits(p.rt, p.asset)))],
    ["Pool value", "≈ " + tvlNado + " NADO"],
    ["LP shares", p.sup.toString()],
    ["Swap fee", "0.30%"],
  ].map(([l, v]) => `<div class="stat"><div class="l">${l}</div><div class="v">${v}</div></div>`).join("");
  const cap = $("depthCap"); if (cap) cap.textContent = "How much the rate moves as your trade gets bigger:";
  const mc = $("mktCap"); if (mc) mc.textContent = "Live price, straight from the pool. Nothing is back-filled — a gap means no trading happened.";
  renderChart(p.id, sym);
  renderDepth(p, price);
  syncUrl(false);
}

// --- the price line chart: SVG, crosshair + tooltip (dataviz interaction layer) ---
const CW = 600, CH = 220, CML = 6, CMR = 54, CMT = 12, CMB = 20;
let _mktBound = false, _mktPts = [], _ttSym = "token", _ttUnit = "";
function renderChart(key, sym, unit) {
  _ttSym = sym; _ttUnit = unit || "";
  const svg = $("mktChart"), empty = $("mktEmpty");
  const data = priceSeries(key);
  svg.parentElement.classList.toggle("empty", data.length < 2);
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
      if (!_mktPts.length) return;
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
    `<text x="8" y="${DH - 2}" fill="var(--danger)" font-size="9.5" font-family="ui-monospace,monospace">← bigger sells get a worse rate</text>` +
    `<text x="${DW - 8}" y="${DH - 2}" fill="var(--accent2)" font-size="9.5" text-anchor="end" font-family="ui-monospace,monospace">bigger buys get a worse rate →</text>`;
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
    samplePrices(lastSto);
    await otcRefresh();
    render();
    swapAutopilot().catch(() => {});
  } finally { refreshing = false; }
}

function wireUI() {
  wireWallet(dapp, render);
  stickyInputs(dapp, ["addN", "addT", "slip", "otcNado", "otcFAmt", "otcExpiry", "limGiveAsset", "limGiveAmt", "limWantAsset", "limWantAmt", "limExpiry"]);
  $("btnOpen").onclick = (e) => runAction(e.currentTarget, openPool);
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
      addrIn.placeholder = `your ${(NETS[netSel.value] || {}).label || ""} address (saved for next time)`; } };
    netSel.onchange = () => { netSel.dataset.touched = "1"; loadAddr(); kindHint(); };
    // LIVE address feedback: the field says what it thinks as you type — empty, wrong shape for this
    // network, or valid — and Post stays disabled until it is valid. Nobody should learn their address
    // was wrong from a refused button.
    const addrHint = $("otcFAddrHint");
    async function checkAddr() {
      const v = (addrIn.value || "").trim(), n = NETS[netSel.value] || {}, ch = n.chain;
      let ok = false, msg = "";
      if (!v) msg = `Enter your ${n.label || "network"} address — it is where this swap pays you.`;
      else if (ch === "eth") { ok = /^0x[0-9a-fA-F]{40}$/.test(v); msg = ok ? "Valid Ethereum address" : "An Ethereum address is 0x followed by 40 hex characters"; }
      else if (ch === "sol") { ok = isB58Addr(v); msg = ok ? "Valid Solana address" : "A Solana address is 32–44 base58 characters"; }
      else if (ch === "btc") { try { await addressToScript(v, n.hrp || "bc"); ok = true; msg = `Valid ${n.label} address`; } catch (e) { msg = `Not a ${n.label} address: ${String(e.message || e).slice(0, 60)}`; } }
      else { ok = v.length > 8; msg = ok ? "" : "Address looks too short"; }
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
      if (bal == null) return alertBar("Sign in to use your balance.");
      const pct = BigInt(b.getAttribute("data-pct"));
      amt.value = d === "n2t" ? fromUnits(bal * pct / 100n) : tokFromUnits(bal * pct / 100n, p.asset);
      renderSwap();
    };
  });
  const fl = $("btnFlip");
  if (fl) fl.onclick = () => { const d = $("dir"); if (!d) return;
    d.value = d.value === "n2t" ? "t2n" : "n2t"; if (amt) amt.value = ""; renderSwap(); };
  const mp = $("mktPick");
  if (mp) mp.onchange = () => { if (curMode === "cross") xsel = mp.value; else sel = mp.value; syncUrl(true); render(); };
  // the SDK sweeps every select on the page (including lists filled by a later poll); these two only
  // need their search wording set, so they are enhanced eagerly with a better placeholder
  enhanceSelect($("mktPick"), { searchPlaceholder: "Search markets" });
  ["newAsset", "limGiveAsset", "limWantAsset", "otcTokenPick"].forEach((id) =>
    enhanceSelect($(id), { searchPlaceholder: "Search tokens by name, symbol or id" }));
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
    share(url, `Trade ${pair} on a post-quantum chain — no listing, no admin, no rake.`, sh, pair + " on NADO DEX");
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
    expire: "Refund claim sent — confirming…",
    boost: "Bounty attached — confirming…",
    cancel: "Cancel sent — confirming…",
    release: "Order released — confirming…",
  });
  refresh();
});

async function boot() {
  try { await dapp.init(); } catch (e) {
    alertBar("Crypto bundle failed to load — reload.");
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
    { key: "swap", icon: "", label: "Swap", hint: "Trade NADO and tokens on the on-chain AMM — live price, depth, and pools.",
      cards: ["marketCard", "swapCard", "liqCard", "poolsCard", "otcLimitCard", "openCard"] },
    { key: "cross", icon: "", label: "Cross-chain", hint: "Atomic BTC / ETH / SOL ↔ NADO swaps — no custodian, no wrapped coins.",
      cards: ["marketCard", "otcBookCard", "otcPostCard", "otcMyCard"] },
  ], onChange: (k) => { curMode = k; syncUrl(true); } });
  curMode = modes.get();                                 // the SDK restores a remembered mode when the URL names none
  render = modes.wrap(doRender);
  window.addEventListener("popstate", () => {
    const m = new URLSearchParams(location.search).get("mode") === "cross" ? "cross" : "swap";
    if (m !== modes.get()) modes.set(m);
  });
  readUrl();
  refresh();
  setInterval(refresh, 3000);
}
boot();
