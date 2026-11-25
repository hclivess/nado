// nadodex.mjs — the cross-chain DEX API client for bots and market makers. Node 18+ or a browser.
//
// FREE, and AUTHENTICATED BY SIGNATURE, not by an API key (operator 2026-11-25: "we need a free authenticated secure
// api!"). Reads are the public /exec/otc/* endpoints (execnode/otc_api.py). Every write is a transaction this file builds
// and signs ON YOUR MACHINE with nadotx.js — byte-identical to the node's signing — and posts to /submit_transaction,
// where every node verifies it. Nothing secret ever leaves the process: there is no login, no token, no endpoint that
// takes a key. Give a bot its OWN key (NadoDex.keygen()) and fund it with what it may trade; never your wallet's key.
//
//   import { NadoDex } from "./nadodex.mjs";
//   const dex = new NadoDex({ key: process.env.BOT_SEED });          // 64-hex seed of the bot's own key
//   const { asks } = await dex.book("ETH");
//   const { id, secret } = await dex.postAsk({ nado: "50", foreign: "0.0335", network: "eth", payout: "0x…", blocks: 28330 });
//   await dex.deposit("100");                                          // L1 NADO -> the exchange balance trades draw on
//   const s = await dex.swap({ pool: 402820643, side: "buy", amount: "10", slippageBps: 100 });   // a pool or a launch curve
//   await dex.claimSwap(s.orderId);                                    // after its block's batch clears
//   await dex.postLimit({ give: { asset: "0", amount: "5" }, want: { asset: "<token id>", amount: "120" }, blocks: 3000 });
//
// EVERY MARKET THE PAGE TRADES (operator: "all sumbarkets need to be fully covered"): cross-chain atomic swaps and the
// in-chain limit orders (`otc` contract), the AMM pools with their liquidity positions and the launchpad curves (`dex`
// contract), and the exchange balance in and out (deposit / withdraw / claimWithdrawals).
//
// THE SECRET IS YOUR MONEY. postAsk/postBid return the swap secret; persist it BEFORE the order can be taken (the page
// writes it before the wallet redirect, scripts/otc_mm.py writes it to disk before posting). Lose it and the swap can
// only expire. Lifecycle and the foreign legs: doc/dex-bridge.md §6; the foreign-chain halves are
// scripts/otc_eth_leg.mjs and scripts/otc_btc_leg.py.
import { canonicalize, finalizeTx, randNonce, nowSeconds, keyFromSeed, genKey } from "./nadotx.js";
import { hashWords } from "./blake2s.js";

// The book's contract as of this file (execnode/otc_api.py OTC_CID = static/dex.js OTC_CID). The client does NOT sign
// against it blindly: it asks the API which contract the book is (GET /exec/otc → contract), so a reroll or a redeploy
// that moves the book cannot leave a bot posting into a contract nobody reads. Pass { cid } to pin one yourself.
export const OTC_CID = "83562ce0cf5ee023d98b366bfcbc6e57";
export const ASK = 1, BID = 2;                                // otc.py: ASK = maker sells NADO, BID = maker buys NADO
const RAW = 10000000000n;                     // protocol DENOMINATION — pinned by tests/test_constant_mirrors.py (PINNED)
const LIMB_BITS = 52n, LIMBS = 5;                             // otc.py preimage_limbs
const WORD = 1n << 256n;
const FOREIGN_MIN_S = 3600, FOREIGN_MARGIN_S = 7200, FOREIGN_MAX_S = 29 * 24 * 3600, BLOCK_S = 6;   // otc.py §6.3
const TARGET_MARGIN = 40;                                     // blocks a signed tx stays valid (scripts/otc_mm.py)
const UNIT = 10n ** 8n;                                       // execnode/games/dex.py UNIT: pools count both sides in these
const CREATE_FEE_UNITS = 1000n;                               // dex.py CREATE_FEE (10 NADO, sealed): the price of a launch
const VN0 = 50000;                                            // dex.py VN0: the default virtual NADO of a launch curve
const INCLUSION_DELAY = 8;                                    // protocol.TX_INCLUSION_DELAY: min_block guard for flexible txs
const randId = () => (new DataView(rand(4).buffer).getUint32(0)) || 7;   // a slot id < 2^32 (the contracts' slot model)
export function decToRaw(s, dec) {                            // exact decimal string -> raw BigInt in `dec` decimals
  const m = /^(\d+)(?:\.(\d+))?$/.exec(String(s).trim());
  if (!m || (m[2] || "").length > dec) throw new Error(`not an amount with at most ${dec} decimals: ${s}`);
  return BigInt(m[1]) * 10n ** BigInt(dec) + BigInt((m[2] || "").padEnd(dec, "0") || "0");
}

const hex = (u8) => Array.from(u8, (x) => x.toString(16).padStart(2, "0")).join("");
const rand = (n) => globalThis.crypto.getRandomValues(new Uint8Array(n));

// ---- the dual hashlock (one secret opens both chains; doc/dex-bridge.md §4.2) ----------------------------------------
export const secretLimbs = (sHex) => {                        // 32-byte secret -> five 52-bit limbs, the settle() args
  const v = BigInt("0x" + sHex), m = (1n << LIMB_BITS) - 1n;
  return Array.from({ length: LIMBS }, (_, i) => Number((v >> (LIMB_BITS * BigInt(i))) & m));
};
export const vmHashlockParts = (sHex) => {                    // otc.py vm_hashlock_parts: 8 × 32-bit, most significant first
  const h = hashWords(secretLimbs(sHex).map((x) => ((BigInt(x) % WORD) + WORD) % WORD));
  return Array.from({ length: 8 }, (_, i) => Number((h >> (32n * BigInt(7 - i))) & 0xFFFFFFFFn));
};
export async function sha256Hex(h) {
  const b = new Uint8Array(h.match(/../g).map((x) => parseInt(x, 16)));
  return hex(new Uint8Array(await globalThis.crypto.subtle.digest("SHA-256", b)));
}
export function nadoToRaw(s) {                                // exact decimal string -> raw BigInt (never a float)
  const m = /^(\d+)(?:\.(\d{1,10}))?$/.exec(String(s).trim());
  if (!m) throw new Error(`not a NADO amount: ${s}`);
  return BigInt(m[1]) * RAW + BigInt((m[2] || "").padEnd(10, "0"));
}

export class NadoDex {
  // relay: the L1 node (submit + tip); exec: where /exec/otc/* answers. Both default to the public relay.
  constructor({ relay = "https://get.nadochain.com", exec = null, key = null, cid = null, fetch: f = null } = {}) {
    this._cid = cid;
    this._dexCid = null;
    this.relay = relay.replace(/\/$/, "");
    this.exec = (exec || relay).replace(/\/$/, "");
    this.wallet = key ? keyFromSeed(key) : null;              // {privateKey (seed), publicKey, address} — stays in memory
    this._fetch = f || globalThis.fetch.bind(globalThis);
    this._chainId = null;
  }
  static keygen() { const k = genKey(); return { seed: k.privateKey, address: k.address }; }   // a fresh TRADING key
  get address() { return this.wallet && this.wallet.address; }

  async _get(base, path) {
    const r = await this._fetch(base + path, { cache: "no-store" });
    const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
    if (!r.ok) throw new Error(j.error || j.message || `HTTP ${r.status}`);
    return j;
  }

  // ---- reads (free, no key) ----------------------------------------------------------------------------------------
  api() { return this._get(this.exec, "/exec/otc"); }
  markets() { return this._get(this.exec, "/exec/otc/markets?provisional=1"); }
  book(market) { return this._get(this.exec, "/exec/otc/book?provisional=1&market=" + encodeURIComponent(market)); }
  async order(id) { return (await this._get(this.exec, "/exec/otc/order?provisional=1&id=" + encodeURIComponent(id))).order; }
  async orders(maker = this.address, status = "") {
    return (await this._get(this.exec, "/exec/otc/orders?provisional=1&maker=" + encodeURIComponent(maker)
      + (status ? "&status=" + encodeURIComponent(status) : ""))).orders;
  }
  trades(market = "", limit = 100) {
    return this._get(this.exec, "/exec/otc/trades?limit=" + limit + (market ? "&market=" + encodeURIComponent(market) : ""));
  }
  // pools + launchpad + limit orders + balances (free)
  async pools() { return (await this._get(this.exec, "/exec/amm/pools?provisional=1")).pools; }
  async pool(id) { return (await this._get(this.exec, "/exec/amm/pool?provisional=1&id=" + Number(id))).pool; }
  quote(pool, side, amount) {
    return this._get(this.exec, `/exec/amm/quote?provisional=1&pool=${Number(pool)}&side=${side}&amount=${encodeURIComponent(amount)}`);
  }
  async swapOrder(id) { return (await this._get(this.exec, "/exec/amm/order?provisional=1&id=" + Number(id))).order; }
  async position(id) { return (await this._get(this.exec, "/exec/amm/position?provisional=1&id=" + Number(id))).position; }
  balance(address = this.address) { return this._get(this.exec, "/exec/amm/balance?provisional=1&address=" + encodeURIComponent(address)); }
  async limitOrders(give = null, want = null) {
    return (await this._get(this.exec, "/exec/otc/intra?provisional=1" + (give != null ? "&give=" + give : "") + (want != null ? "&want=" + want : ""))).orders;
  }
  poolTrades(pid = null, limit = 200) { return this._get(this.exec, "/exec/dex_trades?limit=" + limit + (pid != null ? "&pid=" + pid : "")); }
  candles(pid, tf = 300) { return this._get(this.exec, `/exec/dex_candles?pid=${Number(pid)}&tf=${tf}`); }
  stats() { return this._get(this.exec, "/exec/dex_stats"); }
  async assetDecimals(aid) {
    if (String(aid) === "0") return 10;
    // /exec/asset answers {asset: {…, dec}}. NEVER default a missing dec to 0: an amount scaled by the wrong decimals is
    // a wrong amount sent (a launch went out with 0 units that way, 2026-11-25, caught by the e2e test).
    const r = await this._get(this.exec, "/exec/asset?id=" + encodeURIComponent(aid));
    const d = (r.asset || {}).dec;
    if (!Number.isInteger(d)) throw new Error(`asset ${aid}: decimals unknown`);
    return d;
  }
  async htlc(id) { return (await this._get(this.relay, "/get_htlc?id=" + encodeURIComponent(id))).htlc || null; }
  async chainNow() {                                          // CHAIN time and cursor — what the contract checks against
    const r = await this._get(this.exec, "/exec/root?ns=default&provisional=1");
    return { cursor: Number(r.cursor), time: Number(r.block_ts) };
  }

  // ---- signing (local) ---------------------------------------------------------------------------------------------
  async _chain() {                                            // read from the node, never hard-coded (it changes at a reroll)
    if (!this._chainId) this._chainId = (await this._get(this.relay, "/status")).chain_id;
    return this._chainId;
  }
  async _tip() { return Number((await this._get(this.relay, "/get_latest_block")).block_number); }
  async _submit(recipient, amountRaw, data, fee, guard = false) {
    if (!this.wallet) throw new Error("no key: new NadoDex({ key: <64-hex seed of the bot's own key> })");
    const tip = await this._tip();
    const draft = { sender: this.wallet.address, recipient, amount: amountRaw, timestamp: nowSeconds(), data,
      nonce: randNonce(), public_key: this.wallet.publicKey, max_block: tip + TARGET_MARGIN, chain_id: await this._chain() };
    if (guard) draft.min_block = tip + INCLUSION_DELAY;        // flexibly-landing txs carry the propagation guard
    const tx = finalizeTx(draft, this.wallet.privateKey, fee);
    const r = await this._fetch(this.relay + "/submit_transaction", { method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json" }, body: canonicalize(tx) });
    const j = await r.json().catch(() => ({ result: false, message: `HTTP ${r.status}` }));
    if (!j.result) throw new Error(`refused: ${j.message || r.status}`);
    return tx.txid;
  }
  // an `otc` contract call: a `blob` tx; valueRaw (BigInt) escrows from the bot's EXEC balance (only a BID fill's bond)
  async cid() { if (!this._cid) this._cid = (await this.api()).contract; return this._cid; }
  async dexCid() { if (!this._dexCid) this._dexCid = (await this.api()).contracts.pools_and_launchpad; return this._dexCid; }
  // an `otc` contract call (cross-chain + limit orders); value escrows from the EXCHANGE balance, `asset` names a token
  async call(method, args, valueRaw = null, asset = null) {
    return this._blob({ op: "call", contract: await this.cid(), method, args }, valueRaw, asset);
  }
  // a `dex` contract call (pools + launchpad)
  async dexCall(method, args, valueRaw = null, asset = null) {
    return this._blob({ op: "call", contract: await this.dexCid(), method, args }, valueRaw, asset);
  }
  _blob(p, valueRaw, asset) {
    if (valueRaw != null) p.value = BigInt(valueRaw);
    if (asset && String(asset) !== "0") p.asset = String(asset);
    return this._submit("blob", 0n, p, 1000);
  }
  // wait until `probe()` returns truthy (a landed effect read back from the chain) — sequential steps need it
  async waitFor(probe, { timeoutMs = 180000, everyMs = 3000 } = {}) {
    const t0 = Date.now();
    for (;;) {
      try { const v = await probe(); if (v) return v; } catch (e) { /* not there yet */ }
      if (Date.now() - t0 > timeoutMs) throw new Error("timed out waiting for the chain");
      await new Promise((r) => setTimeout(r, everyMs));
    }
  }

  // ---- makers ------------------------------------------------------------------------------------------------------
  // Sell `nado` NADO for `foreign` of the network's coin, paid to `payout` (for btc: "<address>|<33-byte pubkey hex>",
  // the key that signs the Bitcoin claim — scripts/otc_btc_leg.py). Posting locks nothing; the NADO goes into an L1 HTLC
  // after a taker fills (lockNado). Returns { id, secret, hashlock, txid } — STORE THE SECRET FIRST (see the header).
  postAsk(o) { return this._post(ASK, o); }
  postBid(o) { return this._post(BID, o); }
  async _post(kind, { nado, foreign, network, payout, blocks = 28330, secret = null, onSecret = null }) {
    const raw = nadoToRaw(nado);
    if (raw <= 0n) throw new Error("nado must be > 0");
    if (!/^\d+(\.\d+)?$/.test(String(foreign)) || !(Number(foreign) > 0)) throw new Error("foreign must be a positive decimal string");
    if (!network || !payout) throw new Error("network and payout are required");
    const windowS = blocks * BLOCK_S;
    if (windowS < FOREIGN_MIN_S + FOREIGN_MARGIN_S + 1800) throw new Error(`blocks too short for a cross-chain swap (≥ ${Math.ceil((FOREIGN_MIN_S + FOREIGN_MARGIN_S + 1800) / BLOCK_S)})`);
    const { cursor, time } = await this.chainNow();
    // §6.3, kind-dependent exactly as static/dex.js postOrder: the leg the maker FUNDS outlasts the leg they CLAIM
    let expf = kind === ASK ? Math.floor(time + (FOREIGN_MIN_S + windowS - FOREIGN_MARGIN_S) / 2)
                            : Math.floor(time + windowS + FOREIGN_MARGIN_S + 3600);
    if (kind === BID && expf > time + FOREIGN_MAX_S) throw new Error("a BID's foreign lock must outlast the NADO window and foreign HTLCs cap at 30 days — use fewer blocks");
    expf = Math.min(expf, time + FOREIGN_MAX_S);
    const s = secret || hex(rand(32));
    if (!/^[0-9a-f]{64}$/.test(s)) throw new Error("secret must be 64 lowercase hex");
    const id = (new DataView(rand(4).buffer).getUint32(0)) || 7;
    const hashlock = await sha256Hex(s);
    if (onSecret) await onSecret({ id, secret: s, hashlock });   // persist BEFORE the order exists
    const txid = await this.call("post", [id, kind, raw, network, String(foreign), payout, hashlock, ...vmHashlockParts(s), cursor + blocks, expf]);
    return { id, secret: s, hashlock, txid, expn: cursor + blocks, expf };
  }
  cancel(id) { return this.call("cancel", [Number(id)]); }    // open orders only, maker only
  release(id) { return this.call("release", [Number(id)]); }  // maker: a taker filled and never locked (after 600 blocks)
  expire(id) { return this.call("expire", [Number(id)]); }    // anyone, at/after expn
  bind(id, htlcTxid) { return this.call("bind", [Number(id), htlcTxid]); }   // record the L1 HTLC carrying the NADO leg
  settle(id, secret) { return this.call("settle", [Number(id), ...secretLimbs(secret)]); }

  // ---- takers ------------------------------------------------------------------------------------------------------
  // fill: take an open order. takerForeign = where the taker is paid (ASK) or the taker's refund side (BID); fref = the
  // taker's foreign HTLC reference once it exists ("pending" before — static/dex.js fills the same way). A BID fill carries the taker bond (1 %, min 0.01 NADO).
  // fref must be non-empty (the contract refuses a zero digest): "pending" until the foreign lock exists, as the page does.
  async fill(id, takerForeign, fref = "pending") {
    const od = await this.order(id);
    if (!od || od.status !== "open") throw new Error(`order ${id} is not open (${od && od.status})`);
    let bond = null;
    if (od.side === "bid") { const b = BigInt(od.nado_raw) * 100n / 10000n; bond = b > 100000000n ? b : 100000000n; }
    return this.call("fill", [Number(id), takerForeign, fref], bond);
  }

  // ---- the NADO leg: an L1 HTLC under the order's SHA-256 hashlock -------------------------------------------------
  // ASK: the MAKER locks namt for the taker; BID: the TAKER locks it for the maker. Then bind(id, txid).
  async lockNado(id) {
    const od = await this.order(id);
    const claimant = od.side === "ask" ? od.taker : od.maker;
    if (!claimant) throw new Error("no counterparty yet — the order must be filled first");
    const now = await this.chainNow(), tip = await this._tip(), left = od.expn - now.cursor;
    if (left < 20) throw new Error("too close to the order's expiry to lock");
    // C3 at lock time (static/dex.js nadolock): a BID taker locks only while the maker's foreign deadline still sits
    // safely past this lock's expiry — otherwise the maker can reclaim their foreign coin AND take this NADO.
    if (od.side === "bid" && !(Number(od.expf) > now.time + left * 8 + FOREIGN_MARGIN_S))
      throw new Error("unsafe: the maker's foreign deadline no longer outlasts this NADO lock");
    const target = tip + TARGET_MARGIN;
    return this._submit("htlc_lock", BigInt(od.nado_raw), { claimant, hashlock: od.hashlock_sha256, expiry: target + left }, 1000);
  }
  claimNado(htlcId, secret) { return this._submit("htlc_claim", 0n, { htlc_id: htlcId, preimage: secret }, 0); }   // fee-exempt
  refundNado(htlcId) { return this._submit("htlc_refund", 0n, { htlc_id: htlcId }, 0); }

  // ---- the exchange balance (every pool, curve and limit order draws on it) -------------------------------------------
  deposit(nado) { return this._submit("bridge", nadoToRaw(nado), "", 1000, true); }        // L1 -> exchange
  withdraw(nado) { return this._blob({ op: "bridge_withdraw", amount: nadoToRaw(nado) }); } // exchange -> a cash-out record
  // finish every cash-out the settled root already covers: an L1 bridge_withdraw with its proof, fee-exempt, self-paid
  async claimWithdrawals() {
    const settled = await this._get(this.relay, "/get_settled");
    const root = settled && settled.state_root;
    if (!root) return [];
    const d = await this._get(this.exec, "/exec/withdrawals?address=" + encodeURIComponent(this.address) + "&root=" + root);
    const out = [];
    for (const p of d.pending || []) {
      if (!p.proof || p.state_root !== root) continue;
      out.push(await this._submit("bridge_withdraw", 0n,
        { addr: this.address, amount: BigInt(p.amount), nonce: String(p.nonce), proof: p.proof }, 0, true));
    }
    return out;
  }

  // ---- pools and launch curves ----------------------------------------------------------------------------------------
  // swap: side "buy" spends `amount` NADO for the coin, "sell" spends `amount` of the coin for NADO. The order joins this
  // block's batch (one price per block); minOut protects it — given, or the quote less slippageBps. Collect with claimSwap.
  async swap({ pool, side, amount, slippageBps = 100, minOut = null }) {
    const p = await this.pool(pool);
    if (!p.live) throw new Error(`pool ${pool} is not trading`);
    const q = await this.quote(pool, side, amount);
    const units = BigInt(q.in_units);
    if (units <= 0n) throw new Error("amount is below one pool unit (0.01 NADO / 10^8 raw of the coin)");
    const orderId = randId();
    const asset = side === "sell" ? p.asset : null;
    let txid;
    if (p.kind === "curve") txid = await this.dexCall(side === "buy" ? "buy" : "sell", [Number(pool), orderId, Number(units)], units * UNIT, asset);
    else {
      const lim = minOut != null ? BigInt(minOut) : BigInt(q.out_units) * BigInt(10000 - slippageBps) / 10000n;
      txid = await this.dexCall(side === "buy" ? "obuy" : "osell", [Number(pool), orderId, Number(units), Number(lim)], units * UNIT, asset);
    }
    return { orderId, txid, quote: q };
  }
  async claimSwap(orderId) {
    const o = await this.swapOrder(orderId);
    if (!o.claimable) throw new Error(o.claimed ? "already claimed" : "its batch has not closed yet — retry next block");
    const p = await this.pool(o.pool);
    return this.dexCall("claim", [Number(orderId), BigInt(p.asset)]);
  }
  openPool(poolId, assetId) { return this.dexCall("open", [Number(poolId), BigInt(assetId)]); }
  // add liquidity in the contract's three steps — stage NADO, stage the coin, join — each waited for on chain
  async addLiquidity({ pool, nado, coin, position = null }) {
    const p = await this.pool(pool), pos = position || randId();
    const nu = nadoToRaw(nado) / UNIT, tu = decToRaw(coin, p.decimals) / UNIT;
    if (nu <= 0n || tu <= 0n) throw new Error("both sides must be at least one pool unit");
    await this.dexCall("fundn", [pos, Number(pool), Number(nu)], nu * UNIT);
    await this.waitFor(async () => { const x = await this.position(pos); return x && BigInt(x.pending_nado_units) >= nu; });
    await this.dexCall("fundt", [pos, Number(pool), Number(tu)], tu * UNIT, p.asset);
    await this.waitFor(async () => { const x = await this.position(pos); return x && BigInt(x.pending_coin_units) >= tu; });
    const txid = await this.dexCall("join", [pos, Number(pool)]);
    return { position: pos, txid };
  }
  async removeLiquidity(position, shares = null) {
    const x = await this.position(position), p = await this.pool(x.pool);
    return this.dexCall("exit", [Number(position), x.pool, Number(shares != null ? shares : x.shares), BigInt(p.asset)]);
  }
  async refundLiquidity(position) {                         // return staged sides that never joined
    const x = await this.position(position), p = await this.pool(x.pool);
    return this.dexCall("refund", [Number(position), x.pool, BigInt(p.asset)]);
  }
  // launch a coin you hold the whole supply of onto a bonding curve: the sealed 10 NADO fee reserves the id, then the
  // supply goes in. virtualNado (in pool units) sets the opening price and the raise at graduation (4×).
  async launch({ asset, supply, virtualNado = VN0 }) {
    const dec = await this.assetDecimals(asset), units = decToRaw(supply, dec) / UNIT, pid = randId();
    await this.dexCall("prelaunch", [pid], CREATE_FEE_UNITS * UNIT);
    await this.waitFor(async () => (await this._get(this.exec, "/exec/amm/pool?provisional=1&id=" + pid)).reserved);
    const txid = await this.dexCall("launch", [pid, Number(units), Number(virtualNado)], units * UNIT, asset);
    return { pool: pid, txid };
  }

  // ---- in-chain limit orders (otc SWAP_INTRA) --------------------------------------------------------------------------
  // give/want: { asset: "<id>" | "0" (NADO), amount: "<decimal>" }. The give side is escrowed now; cancel or expiry returns it.
  async postLimit({ give, want, blocks = 3000 }) {
    if (String(give.asset) === String(want.asset)) throw new Error("pick two different assets");
    const gv = decToRaw(give.amount, await this.assetDecimals(give.asset)), wv = decToRaw(want.amount, await this.assetDecimals(want.asset));
    const id = randId(), { cursor } = await this.chainNow();
    const txid = await this.call("post_intra", [id, BigInt(give.asset), gv, BigInt(want.asset), wv, cursor + blocks], gv, give.asset);
    return { id, txid };
  }
  async fillLimit(id) {
    const od = await this.order(id);
    if (!od || od.side !== "intra" || od.status !== "open") throw new Error(`limit order ${id} is not open`);
    return this.call("fill_intra", [Number(id)], BigInt(od.want_raw), od.want_asset);
  }
  boost(id, nado) { return this.call("boost", [Number(id)], nadoToRaw(nado)); }   // a tip for whoever finishes the order

  // Before funding a FOREIGN lock against an order, check the NADO lock it points at is real: right amount, right
  // hashlock, claimable by you, open, and not about to expire. Returns the HTLC; throws on any mismatch.
  async verifyNadoLeg(id, minBlocksLeft = 600) {
    const od = await this.order(id);
    if (!od.nado_htlc) throw new Error("no NADO lock bound to this order yet");
    const h = await this.htlc(od.nado_htlc);
    if (!h) throw new Error("bound NADO lock not found on L1");
    const tip = await this._tip();
    const bad = [];
    if (String(h.amount) !== od.nado_raw) bad.push(`amount ${h.amount} ≠ ${od.nado_raw}`);
    if (h.hashlock !== od.hashlock_sha256) bad.push("hashlock differs");
    if (this.address && h.claimant !== this.address) bad.push("not claimable by this key");
    if (h.status && h.status !== "open") bad.push(`status ${h.status}`);
    if (Number(h.expiry) - tip < minBlocksLeft) bad.push(`expires in ${Number(h.expiry) - tip} blocks`);
    if (bad.length) throw new Error("NADO leg fails: " + bad.join("; "));
    return h;
  }
}

// CLI: `node nadodex.mjs keygen` prints a fresh trading key; `node nadodex.mjs book ETH` prints a book.
if (typeof process !== "undefined" && process.argv && import.meta.url === `file://${process.argv[1]}`) {
  const [cmd, a] = process.argv.slice(2);
  const dex = new NadoDex({ relay: process.env.DEX_RELAY || undefined, key: process.env.DEX_BOT_SEED || null });
  const out = (x) => console.log(JSON.stringify(x, null, 2));
  if (cmd === "keygen") out(NadoDex.keygen());
  else if (cmd === "markets") out(await dex.markets());
  else if (cmd === "book") out(await dex.book(a || "ETH"));
  else if (cmd === "order") out(await dex.order(a));
  else if (cmd === "mine") out(await dex.orders());
  else console.log("usage: node nadodex.mjs keygen | markets | book <ETH|BTC|eth|0x…> | order <id> | mine (DEX_BOT_SEED)");
}
