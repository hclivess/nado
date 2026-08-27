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
import { htlcAbi, htlcErc20Abi, erc20Abi, erc20Meta, toUnitsDec, fromUnitsDec } from "./ethsign.js?v=2";
import { NadoDapp, rawToNado, nadoToRaw, _m, $, gate, wireWallet, stickyInputs, alertBar, loadQR,
         orderCards, disp, share, installModes, algHashn, base, esc, randId, enhanceSelect, refreshPickers,
         uiConfirm, uiPrompt,
         blocksToTime } from "./nadodapp.js?v=86f13b65";

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
  // A comma decimal ("0,5") or any junk used to throw here — BEFORE the dataset below was written — so
  // the button kept signing the PREVIOUS amount while the box showed something else (audit).
  const slipRaw = String((($("slip") || {}).value) || "1").replace(",", ".");
  const slipNum = Number(slipRaw);
  const slipPct = Number.isFinite(slipNum) ? Math.min(50, Math.max(0, slipNum)) : 1;
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
  btct: { chain: "btc", coin: "tBTC", label: "Bitcoin testnet", hrp: "tb",  explorer: "https://mempool.space/testnet" },
  eths: { chain: "eth", coin: "SepETH", label: "Ethereum Sepolia", evm: "0xaa36a7", htlc: "0xd5f47927999c31ce4fe3de11bc560678094486e7", erc20: "0x6d6104704e1956c36851d4c36fdad77ce75a6106" },
  eth:  { chain: "eth", coin: "ETH", label: "Ethereum mainnet",  evm: "0x1",     htlc: "", erc20: "" },
};
// An ERC-20 swap names its token inside the network field: wch = "<network>|<token address>". Everything
// below reads the network through netKeyOf, so a token order behaves exactly like a native one.
const netKeyOf = (od) => String(od.wch || "").split("|")[0];
const tokAddrOf = (od) => { const t = String(od.wch || "").split("|")[1] || ""; return /^0x[0-9a-fA-F]{40}$/.test(t) ? t : ""; };
const netOf = (od) => NETS[netKeyOf(od)] || null;
const chainOf = (od) => (NETS[netKeyOf(od)] || {}).chain || netKeyOf(od);
const erc20Names = {};                               // "0xtoken" -> {symbol, decimals}, read from the chain
const coinOf = (od) => { const t = tokAddrOf(od);
  if (t) return (erc20Names[t.toLowerCase()] || {}).symbol || "TOKEN";
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
const SEED_TOKENS = {
  eths: {
    "0x1c7d4b196cb0c7b01d743fbc6116a902379c7238": { sym: "USDC", dec: 6 },      // name() "USDC", 6 dp
    "0xfff9976782d46cc05630d1f6ebab18b2324d6b14": { sym: "WETH", dec: 18 },     // name() "Wrapped Ether"
  },
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
    fref: String(g("fref", o) || ""), hid: String(g("hid", o) || ""), limbs: [0, 1, 2, 3, 4].map((i) => g("s" + i, o) || 0),
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
          alertBar(`Approving ${meta.symbol}… confirm the first transaction, then the lock.`);
          await ethReq("eth_sendTransaction", [{ from: addr, to: token, data: erc20Abi.approve(htlc, amt) }]);
        }
        data = htlcErc20Abi.fund(token, claimAddr, addr, od.hsha, dl, amt);
      } else {
        data = htlcAbi.fund(claimAddr, addr, od.hsha, dl);
        valueHex = "0x" + amtWei.toString(16);
      }
    } else if (mode === "claim") {
      let sHex = sells ? otcRec(od.o).s : otcSecretFromLimbs(od.limbs);
      if (!/^[0-9a-f]{64}$/.test(sHex || "")) return alertBar("The swap secret isn't available yet.");
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

// ---- cross-chain markets: a BTC/NADO book IS a market, so it gets the same header, chart and stats ----
let xsel = "btc";                                    // selected cross-chain network
const XKEY = (net) => "x:" + net;
const otcPrice = (od) => {                           // NADO per 1 foreign coin
  const f = Number(od.wamt); const nado = Number(od.namtRaw) / 1e10;
  return f > 0 && nado > 0 ? nado / f : 0;
};
function bookOf(net) {
  const bids = [], asks = [];                        // bid = someone paying NADO for the coin (ASK_NADO)
  for (const od of otcOrders()) {
    if (netKeyOf(od) !== net || od.st !== 1 || od.kind === OTC_INTRA || otcLeft(od) <= 0) continue;
    const px = otcPrice(od);
    if (!px) continue;
    (od.kind === OTC_ASK ? bids : asks).push({ px, size: Number(od.wamt), o: od.o, od });
  }
  bids.sort((a, b) => b.px - a.px); asks.sort((a, b) => a.px - b.px);
  const bb = bids[0] ? bids[0].px : 0, ba = asks[0] ? asks[0].px : 0;
  return { bids, asks, bb, ba, mid: bb && ba ? (bb + ba) / 2 : (bb || ba) };
}
function renderXMarket() {
  const nets = Object.keys(NETS);
  const pick = $("mktPick");
  if (pick) {
    const opts = nets.map((k) => `<option value="${k}">${esc(NETS[k].coin)} / NADO — ${esc(NETS[k].label)}</option>`).join("");
    if (pick.dataset.sig !== opts) { pick.dataset.sig = opts; pick.innerHTML = opts; }
    if (!nets.includes(xsel)) xsel = nets[0];
    pick.value = xsel;
  }
  const net = NETS[xsel] || {}, b = bookOf(xsel);
  $("mktPair").textContent = `${net.coin} / NADO`;
  $("mktPrice").textContent = b.mid ? fmtPrice(b.mid) : "—";
  const st24 = stats24(XKEY(xsel), b.mid);
  const chgEl = $("mktChg");
  if (st24 && b.mid) {
    chgEl.textContent = (st24.pct >= 0 ? "+" : "") + st24.pct.toFixed(2) + "%  24h";
    chgEl.className = "chg " + (Math.abs(st24.pct) < 0.005 ? "flat" : st24.pct > 0 ? "up" : "dn");
  } else { chgEl.textContent = b.bids.length || b.asks.length ? "one side quoted" : "no open orders"; chgEl.className = "chg flat"; }
  const mine = otcOrders().filter((x) => netKeyOf(x) === xsel && dapp.me && (x.maker === dapp.me || x.taker === dapp.me)).length;
  $("mktStats").innerHTML = [
    ["Best bid", b.bb ? fmtPrice(b.bb) + " NADO" : "—"],
    ["Best ask", b.ba ? fmtPrice(b.ba) + " NADO" : "—"],
    ["Spread", b.bb && b.ba ? ((b.ba - b.bb) / b.ba * 100).toFixed(2) + "%" : "—"],
    ["Buy orders", String(b.bids.length)],
    ["Sell orders", String(b.asks.length)],
    ["Your orders", String(mine)],
  ].map(([l, v]) => `<div class="stat"><div class="l">${l}</div><div class="v">${v}</div></div>`).join("");
  const cap = $("depthCap"); if (cap) cap.textContent = "Live order book — how much is offered at each price:";
  renderChart(XKEY(xsel), "NADO", `1 ${net.coin} =`);
  renderBookDepth(b, net.coin);
  syncUrl(false);
}
// the order book as cumulative depth — the classic book view, drawn from live open orders
function renderBookDepth(b, coin) {
  const svg = $("mktDepth");
  if (!svg) return;
  if (!b.bids.length && !b.asks.length) {
    svg.innerHTML = `<text x="${DW / 2}" y="${DH / 2}" fill="var(--faint)" font-size="11" text-anchor="middle">no open orders — post one below</text>`;
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
  if (owesNado && !expired && !od.hid) {
    acts.unshift(`<button class="primary" data-otc="nadolock" data-o="${od.o}">Lock the NADO…</button>`);
    acts.push(`<button class="ghost" data-otc="nadobind" data-o="${od.o}">I already locked it</button>`);
  }
  const isEth = chainOf(od) === "eth";
  if (isEth && tokAddrOf(od) && !erc20Names[tokAddrOf(od).toLowerCase()] && ethProv()) ethTokenMeta(tokAddrOf(od));
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
      else if (sells && isMaker && !od.hid) hint = `Next: press Lock the NADO — it escrows your NADO on the main chain under this swap's hashlock, takeable only by the taker and only with the secret.`;
      else if (sells && isMaker) hint = `Next: press Verify below — once the taker's ${foreign} lock shows CONFIRMED, press Claim the BTC. Claiming completes your side.`;
      else if (sells && isTaker && !od.hid) hint = `Next: wait — the maker must lock their NADO on the main chain first. Do not send any ${foreign} until you can see and check that lock.`;
      else if (sells && isTaker) hint = `Next: check the maker's NADO lock (id below), then send the ${foreign}. When the maker claims it the secret becomes public, and you claim the NADO with it.`;
      else if (!sells && isMaker) hint = `Next: send the ${foreign} to the address below, wait for confirmations, then press Settle to collect your NADO.`;
      else if (!sells && isTaker) hint = `Next: wait — when the maker collects their NADO here, a Claim your BTC button appears on this row.`;
    } else if ((od.st === 1 || od.st === 2) && expired) hint = "Expired — reclaim each leg on its own chain (the NADO leg is an L1 HTLC refund).";
    if (hint) detail += `<div class="small mt" style="color:var(--accent2)">${hint}</div>`;
    if (chainOf(od) === "btc" && od.st >= 2 && (isMaker || isTaker)) {
      const b = btcInfo(od);
      if (b) detail += `<div class="small mt">${btcFunder && od.st === 2 ? `<b>Send exactly ${esc(od.wamt)} BTC to:</b><br>` : `Swap address: `}<span class="mono" style="word-break:break-all">${b.addr}</span>
        <a href="#" data-otc="btccopy" data-o="${od.o}">copy</a> · <a href="#" data-otc="btcverify" data-o="${od.o}">verify</a>
        <span id="btcv${od.o}" class="dim"></span></div>`;
      else if (!btcParts(od)) detail += `<div class="small dim mt">The counterparty's client didn't publish a Bitcoin key — finish this leg with scripts/otc_btc_leg.py.</div>`;
    }
    if (chainOf(od) === "eth" && od.st >= 2 && (isMaker || isTaker) && !ethProv()) detail += ethCliHint(od);
    const rec0 = otcRec(od.o);
    if ((rec0.k || rec0.s) && (od.st === 1 || od.st === 2))
      detail += `<div class="small dim mt"><a href="#" data-otc="showsecret" data-o="${od.o}">Back up this swap</a> — without it a lost browser means lost funds.</div>`;
    const secret = rec0.s;
    if (secret && (od.st === 1 || od.st === 2))
      detail += `<div class="small dim mt">Your swap secret: <span class="mono">${secret.slice(0, 16)}…</span>
        <a href="#" data-otc="showsecret" data-o="${od.o}">back up</a> — keep a copy: it is all this swap
        needs on any device (never share it before the counterparty's lock is CONFIRMED).</div>`;
    if (od.st === 2 && od.hid) detail += `<div class="small mt">NADO leg locked on L1: <span class="mono">${esc(String(od.hid)).slice(0, 24)}…</span> — check its amount, hashlock and expiry in your wallet's Swap tab before sending anything.</div>`;
    if (od.st === 2 && od.fref && od.fref !== "pending") detail += `<div class="small dim mt">Foreign leg ref: <span class="mono">${esc(od.fref).slice(0, 40)}</span>
      · counterparty ${esc(disp(isMaker ? od.taker : od.maker))}</div>`;
    if (od.st === 3 && od.limbs.some((x) => Number(x) > 0)) {
      const rs = otcSecretFromLimbs(od.limbs);
      detail += `<div class="small mt">Revealed secret (claims the ${chain} HTLC): <span class="mono" style="word-break:break-all">${rs}</span></div>`;
    }
  }
  return `<div class="loan"><div class="loanmain">
      <div class="loantop">${pill} <b>#${od.o}</b> ${esc(disp(od.maker))} ${head}</div>
      <div class="loanterms">${od.prem > 0n ? `maker has ${rawToNado(od.prem.toString())} NADO at stake · ` : ""}${od.bnty > 0n ? `<span class="pill">+${rawToNado(od.bnty.toString())} NADO tip</span> · ` : ""}hashlock <span class="dim">${esc(od.hsha).slice(0, 18)}…</span> ·
        ${od.st <= 2 ? (expired ? "refundable now" : `expires in ${left} blocks (~${blocksToTime(left)})`) : ""}
        ${od.expf ? `· ${esc(coinOf(od))} deadline ${new Date(Number(od.expf) * 1000).toISOString().slice(0, 16).replace("T", " ")}Z` : ""}</div>
      <div class="loanwho dim small">on <b>${esc((netOf(od) || {}).label || od.wch)}</b> · ${sells ? "maker receives" : "taker receives"} ${chain} at ${esc((sells ? od.wadr : od.tadr || od.wadr).split("|")[0]) || "(swap key published)"}</div>
      ${detail}
    </div><div class="loanacts">${acts.join("")}</div></div>`;
}
function renderOtc() {
  const book = $("otcBook"), mine = $("otcMine");
  if (!book || !mine) return;
  const all = otcOrders(), me = dapp.me;
  const open = all.filter((x) => x.st === 1 && x.kind !== OTC_INTRA && netKeyOf(x) === xsel && otcLeft(x) > 0);
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

async function otcPost() {
  const kind = Number($("otcKind").value);
  const raw = (() => { try { return BigInt(nadoToRaw(($("otcNado").value || "").trim())); } catch (e) { return 0n; } })();
  const netSelV = $("otcNet").value, chain = (NETS[netSelV] || {}).chain;
  const tp2 = $("otcTokenPick");
  const tokenV = (tp2 && tp2.value && tp2.value !== "?") ? tp2.value : ((($("otcToken") || {}).value) || "").trim();
  if (tokenV && !/^0x[0-9a-fA-F]{40}$/.test(tokenV)) return alertBar("A token address looks like 0x followed by 40 hex characters.");
  if (tokenV && !(NETS[netSelV] || {}).erc20) return alertBar(`Token swaps are not available on ${(NETS[netSelV] || {}).label} yet.`);
  const net = tokenV ? netSelV + "|" + tokenV.toLowerCase() : netSelV;   // the token rides in the network field
  const famt = ($("otcFAmt").value || "").trim(), faddr = ($("otcFAddr").value || "").trim();
  const blocks = Math.floor(Number($("otcExpiry").value || 0));
  if (raw <= 0n) return alertBar("Enter the NADO amount.");
  if (!famt || !(Number(famt) > 0)) return alertBar("Enter the foreign amount.");
  if (!faddr) return alertBar("Enter your " + (NETS[netSelV] || {}).label + " address.");
  faddrSet(netSelV, faddr);                                // typed once — reused for every future swap on this network
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
  const vmParts = otcVmParts(sHex);            // the four hashlocks, eight 32-bit halves
  // expf: the FOREIGN leg's deadline both parties sign. Advisory to the VM (it cannot read that chain);
  // the wallet suggests ~60% of the NADO window in unix seconds so the foreign refund opens first (§6.3).
  // Derive the foreign deadline from CHAIN time, not the poster's clock, and keep it comfortably inside
  // the NADO window (§6.3): the foreign side must be refundable BEFORE the NADO escrow unlocks.
  const nowSec = (dapp.chainNow && dapp.chainNow()) || Math.floor(Date.now() / 1000);
  // Land in the middle of the window the contract enforces (§6.3, otc.py FOREIGN_MIN_S/FOREIGN_MARGIN_S):
  // late enough for the foreign leg to be funded and confirmed, early enough to refund before the NADO side.
  const FOREIGN_MIN_S = 3600, FOREIGN_MARGIN_S = 7200, windowS = blocks * 6;
  if (windowS < FOREIGN_MIN_S + FOREIGN_MARGIN_S + 1800)
    return alertBar(`That expiry is too short for a ${(NETS[$("otcNet").value] || {}).coin || "cross-chain"} swap — use at least ${Math.ceil((FOREIGN_MIN_S + FOREIGN_MARGIN_S + 1800) / 6)} blocks.`);
  const expf = Math.floor(nowSec + (FOREIGN_MIN_S + windowS - FOREIGN_MARGIN_S) / 2);
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
  if (what === "prem") {
    const raw = ((await uiPrompt({ title: "Put collateral behind this order",
      body: "You escrow this yourself. It comes back when the swap completes or if nobody fills the order — and goes to the taker if you walk away after they have committed.",
      placeholder: "amount in NADO" })) || "").trim();
    let amt;
    try { amt = raw === "0" ? 0n : BigInt(nadoToRaw(raw)); } catch (e) { return; }
    if (amt == null || amt < 0n) return;
    return dapp.call("set_premium", [o, amt], null, "Setting deposit on #" + o + "…", { otc: o }, { cid: OTC_CID });
  }
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
    // §6.3: refuse to fund a foreign leg whose deadline is not safely INSIDE the NADO refund window.
    // Nothing on chain enforces this, so a maker can otherwise strand the taker's coin (audit).
    const nowS = (dapp.chainNow && dapp.chainNow()) || Math.floor(Date.now() / 1000);
    const nadoWindowS = Math.max(0, (od.expn - (dapp.cursor || 0))) * 6;
    const fdl = Number(od.expf) || 0;
    if (!(fdl > nowS + 1800 && fdl < nowS + nadoWindowS * 0.75)) {
      return alertBar("This order's foreign deadline does not line up with its NADO expiry — filling it "
        + "could let the maker reclaim their NADO and still take your coin. Not safe to fill.");
    }
    const chain = coinOf(od);
    let myf, fref = "pending";
    const ch = chainOf(od);
    if (ch === "btc") {
      const kp = genKeypair();                          // the swap's own key; the address to fund appears on the row after the fill lands
      otcSaveRec(o, { k: kp.k, pub: kp.pub });
      myf = kp.pub;
    } else if (ch === "eth") {
      if (ethProv()) { const { addr } = await ethConnect(); myf = addr; }   // the taker's own EVM account
      else { const ek = (await import("./ethsign.js?v=1")).ethKeypair(); otcSaveRec(o, { k: ek.k }); myf = ek.addr; }
    } else {
      myf = faddrGet(netKeyOf(od));                    // typed once per network, then never again
      if (!myf) {
        myf = await uiPrompt({ title: `Your ${(netOf(od) || {}).label || chain} address`,
          body: "Where this swap pays you on that chain. Saved for next time.", placeholder: "address" });
        if (!myf) return;
        faddrSet(netKeyOf(od), myf);
      }
    }
    dapp.call("fill", [o, myf, fref], null, "Filling #" + o + "…", { otc: o }, { cid: OTC_CID });
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
      body: "They can only take it with the swap secret, and only before it expires — after that you reclaim it yourself.",
      rows: [{ k: "Amount", v: rawToNado(od.namtRaw.toString()) + " NADO" },
             { k: "Claimable by", v: String(to).slice(0, 16) + "…" },
             { k: "You can reclaim after", v: blocks + " blocks" }],
      confirmText: "Lock" })) return;
    dapp.htlcLock({ claimant: to, hashlock: od.hsha, amount: od.namtRaw, blocks }, { otc: o, phase: "htlc_lock" });
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
  if (what === "ethfund") { ethLeg(od, "fund"); return; }
  if (what === "ethclaim") { ethLeg(od, "claim"); return; }
  if (what === "ethrefund") { ethLeg(od, "refund"); return; }
  if (what === "settle") {
    (async () => {
      let s = otcRec(o).s;                              // a maker settles with their own stored secret
      if (!s && chainOf(od) === "btc") { alertBar("Looking up the revealed secret on Bitcoin…"); s = await btcFoundSecret(od); }
      if (!s && chainOf(od) === "eth") { alertBar("Looking up the revealed secret on Ethereum…"); s = await ethFoundSecret(od); }
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
    + "?market=" + encodeURIComponent((NETS[xsel] || {}).coin || xsel) + "&mode=cross";
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
  if (wantMarket) for (const k of Object.keys(NETS))          // a coin symbol also names a cross-chain market
    if ((NETS[k].coin || "").toUpperCase() === wantMarket) { xsel = k; break; }
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
    ["1 NADO buys", live ? fmtPrice(price) + " " + esc(sym) : "—"],
    [`1 ${esc(sym)} buys`, live ? fmtPrice(1 / price) + " NADO" : "—"],
    ["24h high", st24 ? fmtPrice(st24.hi) : "—"],
    ["24h low", st24 ? fmtPrice(st24.lo) : "—"],
    ["NADO in pool", fromUnits(p.rn)],
    [esc(sym) + " in pool", fromUnits(p.rt)],
    ["Pool value", "≈ " + tvlNado + " NADO"],
    ["LP shares", p.sup.toString()],
    ["Swap fee", "0.30%"],
  ].map(([l, v]) => `<div class="stat"><div class="l">${l}</div><div class="v">${v}</div></div>`).join("");
  const cap = $("depthCap"); if (cap) cap.textContent = "How much the rate moves as your trade gets bigger:";
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
      netSel.innerHTML = Object.keys(NETS).map((k) => `<option value="${k}">${NETS[k].coin} · ${NETS[k].label}</option>`).join("");
      loadAddr();
    };
    const showTok = () => {
      const row = $("otcTokenRow"), on = !!(NETS[netSel.value] || {}).erc20;
      if (row) row.classList.toggle("hidden", !on);
      if (!on && $("otcToken")) $("otcToken").value = "";
    };
    const loadAddr = () => { showTok(); if (addrIn) { addrIn.value = faddrGet(netSel.value); 
      addrIn.placeholder = `your ${(NETS[netSel.value] || {}).label || ""} address (saved for next time)`; } };
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
  if (mp) mp.onchange = () => { if (curMode === "cross") xsel = mp.value; else sel = mp.value; syncUrl(true); render(); };
  // the SDK sweeps every select on the page (including lists filled by a later poll); these two only
  // need their search wording set, so they are enhanced eagerly with a better placeholder
  enhanceSelect($("mktPick"), { searchPlaceholder: "Search markets" });
  ["newAsset", "limGiveAsset", "limWantAsset", "otcTokenPick"].forEach((id) =>
    enhanceSelect($(id), { searchPlaceholder: "Search tokens by name, symbol or id" }));
  // ONE token control: pick a known token, or pick "another token" and paste it — the paste box checks
  // itself as you type, so no separate button repeats the job.
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
  wireUI(); loadQR(); orderCards(["tradeRow", "liqCard", "poolsCard", "otcLimitCard", "openCard", "otcBookCard", "otcPostCard", "otcMyCard", "walletcard"]);
  window.addEventListener("popstate", () => { wantMarket = null; readUrl(); render(); });
  const modes = installModes(dapp, { modes: [
    { key: "swap", icon: "🔄", label: "Swap", hint: "Trade NADO and tokens on the on-chain AMM — live price, depth, and pools.",
      cards: ["marketCard", "swapCard", "liqCard", "poolsCard", "otcLimitCard", "openCard"] },
    { key: "cross", icon: "🌉", label: "Cross-chain", hint: "Atomic BTC/ETH ↔ NADO swaps — no custodian, no wrapped coins.",
      cards: ["marketCard", "otcBookCard", "otcPostCard", "otcMyCard"] },
  ], onChange: (k) => { curMode = k; syncUrl(true); } });
  curMode = new URLSearchParams(location.search).get("mode") === "cross" ? "cross" : "swap";
  render = modes.wrap(doRender);
  readUrl();
  refresh();
  setInterval(refresh, 3000);
}
boot();
