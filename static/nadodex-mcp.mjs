#!/usr/bin/env node
// nadodex-mcp.mjs — the cross-chain DEX as an MCP server (stdio, no dependencies). Operator 2026-11-25: "also this dex
// needs an mcp server".
//
//   claude mcp add nado-dex -- node /path/to/nadodex-mcp.mjs                          # read-only: markets, books, orders
//   claude mcp add nado-dex -e NADO_BOT_SEED=<64-hex> -- node /path/to/nadodex-mcp.mjs   # + trading tools
//
// The key never leaves this process: tools sign locally through nadodex.mjs and post the signed transaction. Give it a
// DEDICATED trading key (`node nadodex.mjs keygen`) funded with only what an agent may trade — never your wallet's key.
// Swap secrets are written to NADO_DEX_SECRETS (default ./nado-dex-secrets/, mode 0600) BEFORE an order is posted: a
// secret that lived only in a model's context would be lost with it, and with it the swap. A remote, read-only MCP
// endpoint needs no install at all: https://get.nadochain.com/exec/otc/mcp (execnode/otc_api.py).
import { NadoDex } from "./nadodex.mjs";
import { mkdirSync, writeFileSync, readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const PROTOCOL = "2025-06-18";
const dex = new NadoDex({ relay: process.env.NADO_RELAY || undefined, exec: process.env.NADO_EXEC || undefined,
                          key: process.env.NADO_BOT_SEED || null });
const SECRETS = process.env.NADO_DEX_SECRETS || join(process.cwd(), "nado-dex-secrets");

function saveSecret(rec) {
  mkdirSync(SECRETS, { recursive: true, mode: 0o700 });
  writeFileSync(join(SECRETS, `order-${rec.id}.json`), JSON.stringify(rec), { mode: 0o600, flag: "wx" });   // never overwrite
}
function loadSecret(id) {
  const p = join(SECRETS, `order-${Number(id)}.json`);
  return existsSync(p) ? JSON.parse(readFileSync(p, "utf8")).secret : null;
}

const S = (props, req = []) => ({ type: "object", properties: props, required: req, additionalProperties: false });
const str = (d) => ({ type: "string", description: d }), int = (d) => ({ type: "integer", description: d });
const MARKET = str("ETH, BTC, USDC, a network key (eth, btc) or eth|0x<token>");

// [name, description, schema, run, needsKey]
const TOOLS = [
  ["dex_markets", "Every NADO cross-chain market: open depth, best ask/bid (foreign coin per 1 NADO), last price.", S({}), () => dex.markets()],
  ["dex_book", "The open order book of one market, best first. Asks sell NADO, bids buy NADO.", S({ market: MARKET }, ["market"]), (a) => dex.book(a.market)],
  ["dex_order", "One order in full: status, parties, amounts, locks, and the revealed secret once settled.", S({ id: int("order id") }, ["id"]), (a) => dex.order(a.id)],
  ["dex_orders", "A maker's (or taker's) orders; defaults to this server's own trading key.", S({ maker: str("NADO address"), status: str("open|filled|settled|expired|cancelled|refunded") }), (a) => dex.orders(a.maker || dex.address, a.status || "")],
  ["dex_trades", "Settled swaps, newest first.", S({ market: MARKET, limit: int("max rows, ≤ 500") }), (a) => dex.trades(a.market || "", a.limit || 50)],
  ["dex_limit_orders", "Open in-chain limit orders (any token or NADO for any other), best first. Asset id 0 = NADO.", S({ give: str("asset id"), want: str("asset id") }), (a) => dex.limitOrders(a.give ?? null, a.want ?? null)],
  ["dex_pools", "Every AMM pool and launchpad curve: reserves, prices, liquidity, curve progress.", S({}), () => dex.pools()],
  ["dex_quote", "Exact quote for one swap on a pool or curve. side buy spends NADO; sell spends the coin.", S({ pool: int("pool id"), side: { type: "string", enum: ["buy", "sell"] }, amount: str("decimal amount in") }, ["pool", "side", "amount"]), (a) => dex.quote(a.pool, a.side, a.amount)],
  ["dex_swap_order", "A pool/curve swap order: its batch, claimable or not, exact payout once cleared.", S({ id: int("order id") }, ["id"]), (a) => dex.swapOrder(a.id)],
  ["dex_position", "A liquidity position: shares, what they withdraw now, staged deposits.", S({ id: int("position id") }, ["id"]), (a) => dex.position(a.id)],
  ["dex_balance", "Exchange balances (NADO and tokens, raw); defaults to this server's key.", S({ address: str("NADO address") }), (a) => dex.balance(a.address || dex.address)],
  ["dex_pool_trades", "A pool's trade history (swaps, liquidity, launch fills), newest first.", S({ pool: int("pool id"), limit: int("rows") }), (a) => dex.poolTrades(a.pool ?? null, a.limit || 100)],
  ["dex_candles", "A pool's OHLCV candles.", S({ pool: int("pool id"), tf: int("seconds: 60 300 900 3600 14400 86400") }, ["pool"]), (a) => dex.candles(a.pool, a.tf || 300)],
  ["dex_whoami", "This server's trading address (empty when started without NADO_BOT_SEED).", S({}), async () => ({ address: dex.address || null, trading: !!dex.address })],
  ["dex_post_ask", "SELL NADO: post an ask of `nado` NADO for `foreign` units of the network's coin, paid to `payout`. Locks nothing until filled. The secret is saved locally first.",
    S({ nado: str("NADO amount, decimal string"), foreign: str("foreign amount, decimal string"), network: str("eth | btc | eth|0x<token>"), payout: str("your foreign receiving address"), blocks: int("order lifetime in blocks (6 s each), default 28330 ≈ 48 h") }, ["nado", "foreign", "network", "payout"]),
    (a) => dex.postAsk({ ...a, onSecret: (r) => saveSecret({ ...r, side: "ask", ...a }) }).then(({ secret, ...r }) => ({ ...r, secret_saved_to: SECRETS })), true],
  ["dex_post_bid", "BUY NADO: post a bid offering `foreign` of the network's coin for `nado` NADO. You fund the foreign lock after a taker fills.",
    S({ nado: str("NADO amount"), foreign: str("foreign amount"), network: str("eth | btc | eth|0x<token>"), payout: str("your foreign refund address"), blocks: int("lifetime in blocks") }, ["nado", "foreign", "network", "payout"]),
    (a) => dex.postBid({ ...a, onSecret: (r) => saveSecret({ ...r, side: "bid", ...a }) }).then(({ secret, ...r }) => ({ ...r, secret_saved_to: SECRETS })), true],
  ["dex_fill", "Take an open order. taker_foreign: your foreign address on that chain. A bid fill holds a 1 % bond (min 0.01 NADO) until you lock.",
    S({ id: int("order id"), taker_foreign: str("your foreign address"), fref: str("your foreign HTLC reference, if already funded") }, ["id", "taker_foreign"]),
    (a) => dex.fill(a.id, a.taker_foreign, a.fref || "pending").then((txid) => ({ txid })), true],
  ["dex_lock_nado", "Lock the NADO side of a filled order in an L1 HTLC under its hashlock (ask maker, or bid taker). Then call dex_bind with the txid.",
    S({ id: int("order id") }, ["id"]), (a) => dex.lockNado(a.id).then((txid) => ({ txid })), true],
  ["dex_bind", "Record which L1 HTLC carries an order's NADO leg.", S({ id: int("order id"), htlc: str("txid of the htlc_lock") }, ["id", "htlc"]), (a) => dex.bind(a.id, a.htlc).then((txid) => ({ txid })), true],
  ["dex_verify_nado_leg", "Before funding a foreign lock: check the order's NADO HTLC has the right amount, hashlock, claimant and time left.",
    S({ id: int("order id") }, ["id"]), (a) => dex.verifyNadoLeg(a.id), false],
  ["dex_settle", "Close a filled order with its secret (from the local secret store unless given).", S({ id: int("order id"), secret: str("64-hex secret, optional") }, ["id"]),
    (a) => { const s = a.secret || loadSecret(a.id); if (!s) throw new Error("no stored secret for this order"); return dex.settle(a.id, s).then((txid) => ({ txid })); }, true],
  ["dex_claim_nado", "Claim an L1 NADO HTLC with the swap secret (fee-exempt).", S({ htlc: str("HTLC id"), secret: str("64-hex secret") }, ["htlc", "secret"]), (a) => dex.claimNado(a.htlc, a.secret).then((txid) => ({ txid })), true],
  ["dex_refund_nado", "Reclaim your own expired L1 NADO HTLC.", S({ htlc: str("HTLC id") }, ["htlc"]), (a) => dex.refundNado(a.htlc).then((txid) => ({ txid })), true],
  ["dex_cancel", "Cancel your own open cross-chain or limit order.", S({ id: int("order id") }, ["id"]), (a) => dex.cancel(a.id).then((txid) => ({ txid })), true],
  ["dex_release", "Reopen your filled order whose taker never locked (after 600 blocks).", S({ id: int("order id") }, ["id"]), (a) => dex.release(a.id).then((txid) => ({ txid })), true],
  ["dex_expire", "Close an order at/after its expiry (anyone).", S({ id: int("order id") }, ["id"]), (a) => dex.expire(a.id).then((txid) => ({ txid })), true],
  ["dex_boost", "Tip whoever finishes an order (settle / expire / fill), in NADO.", S({ id: int("order id"), nado: str("tip") }, ["id", "nado"]), (a) => dex.boost(a.id, a.nado).then((txid) => ({ txid })), true],
  // the exchange balance
  ["dex_deposit", "Move NADO from this key's L1 balance onto the exchange (what pools, curves and limit orders spend).", S({ nado: str("amount") }, ["nado"]), (a) => dex.deposit(a.nado).then((txid) => ({ txid })), true],
  ["dex_withdraw", "Cash NADO out of the exchange; finish with dex_claim_withdrawals once the next settle covers it.", S({ nado: str("amount") }, ["nado"]), (a) => dex.withdraw(a.nado).then((txid) => ({ txid })), true],
  ["dex_claim_withdrawals", "Land every cash-out the settled root already proves, on L1 (fee-exempt).", S({}), () => dex.claimWithdrawals().then((txids) => ({ txids })), true],
  // pools and launch curves
  ["dex_swap", "Swap on a pool or launch curve: buy spends `amount` NADO, sell spends `amount` of the coin. Joins this block's one-price batch; collect with dex_claim_swap.",
    S({ pool: int("pool id"), side: { type: "string", enum: ["buy", "sell"] }, amount: str("decimal amount in"), slippage_bps: int("max slippage vs the quote, default 100 = 1 %") }, ["pool", "side", "amount"]),
    (a) => dex.swap({ pool: a.pool, side: a.side, amount: a.amount, slippageBps: a.slippage_bps ?? 100 }), true],
  ["dex_claim_swap", "Collect a swap once its block's batch has closed.", S({ id: int("order id") }, ["id"]), (a) => dex.claimSwap(a.id).then((txid) => ({ txid })), true],
  ["dex_add_liquidity", "Provide liquidity to a pool: stages NADO and the coin, then joins (three transactions, each awaited).",
    S({ pool: int("pool id"), nado: str("NADO amount"), coin: str("coin amount") }, ["pool", "nado", "coin"]), (a) => dex.addLiquidity(a), true],
  ["dex_remove_liquidity", "Withdraw a position's shares (all by default).", S({ position: int("position id"), shares: int("shares, default all") }, ["position"]), (a) => dex.removeLiquidity(a.position, a.shares ?? null).then((txid) => ({ txid })), true],
  ["dex_refund_liquidity", "Return a position's staged deposits that never joined.", S({ position: int("position id") }, ["position"]), (a) => dex.refundLiquidity(a.position).then((txid) => ({ txid })), true],
  ["dex_open_pool", "Open a NADO / token pool.", S({ pool: int("new pool id"), asset: str("token asset id") }, ["pool", "asset"]), (a) => dex.openPool(a.pool, a.asset).then((txid) => ({ txid })), true],
  ["dex_launch", "Launch a coin you hold the whole supply of on a bonding curve (10 NADO sealed fee).",
    S({ asset: str("asset id"), supply: str("whole supply, decimal"), virtual_nado: int("curve scale in 0.01-NADO units, default 50000") }, ["asset", "supply"]),
    (a) => dex.launch({ asset: a.asset, supply: a.supply, virtualNado: a.virtual_nado ?? undefined }), true],
  // in-chain limit orders
  ["dex_post_limit", "Post an in-chain limit order: give one asset for another (0 = NADO). The give side is escrowed until filled, cancelled or expired.",
    S({ give_asset: str("asset id or 0"), give_amount: str("decimal"), want_asset: str("asset id or 0"), want_amount: str("decimal"), blocks: int("lifetime in blocks, default 3000") }, ["give_asset", "give_amount", "want_asset", "want_amount"]),
    (a) => dex.postLimit({ give: { asset: a.give_asset, amount: a.give_amount }, want: { asset: a.want_asset, amount: a.want_amount }, blocks: a.blocks || 3000 }), true],
  ["dex_fill_limit", "Fill an open limit order (both sides swap atomically in one call).", S({ id: int("order id") }, ["id"]), (a) => dex.fillLimit(a.id).then((txid) => ({ txid })), true],
];

export function toolList() {
  return TOOLS.filter((t) => !t[4] || dex.address).map(([name, description, inputSchema]) => ({ name, description, inputSchema }));
}

export async function handle(msg) {
  const { id, method, params } = msg;
  const ok = (result) => ({ jsonrpc: "2.0", id, result });
  if (method === "initialize")
    return ok({ protocolVersion: PROTOCOL, capabilities: { tools: {} },
                serverInfo: { name: "nado-dex", version: "1" },
                instructions: "NADO DEX: cross-chain atomic swaps (BTC/ETH/SOL), in-chain limit orders, AMM pools with liquidity, and the launchpad. Cross-chain prices are foreign coin per 1 NADO. Trading tools sign locally with this server's own key; pools, curves and limit orders spend the exchange balance (dex_deposit)." });
  if (method === "ping") return ok({});
  if (method === "tools/list") return ok({ tools: toolList() });
  if (method === "tools/call") {
    const t = TOOLS.find((x) => x[0] === (params || {}).name);
    if (!t || (t[4] && !dex.address)) return { jsonrpc: "2.0", id, error: { code: -32602, message: "unknown tool" } };
    try {
      const r = await t[3]((params || {}).arguments || {});
      return ok({ content: [{ type: "text", text: JSON.stringify(r, (k, v) => (typeof v === "bigint" ? v.toString() : v), 2) }] });
    } catch (e) {
      return ok({ content: [{ type: "text", text: String((e && e.message) || e) }], isError: true });
    }
  }
  if (id === undefined) return null;                          // a notification (notifications/initialized …)
  return { jsonrpc: "2.0", id, error: { code: -32601, message: "method not found" } };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  let buf = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", async (chunk) => {
    buf += chunk;
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1);
      if (!line) continue;
      let msg; try { msg = JSON.parse(line); } catch { continue; }
      const out = await handle(msg);
      if (out) process.stdout.write(JSON.stringify(out) + "\n");
    }
  });
}
