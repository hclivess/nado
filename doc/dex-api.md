# The DEX API, SDK and MCP servers

Every market the DEX page trades is open to bots and AI agents: **free, no sign-up, no API key**. Reads are public
HTTP; every write is a transaction your program signs **with its own key on its own machine**. There is nothing on the
server to steal, and no endpoint ever takes a key.

| | |
|---|---|
| Human docs page | <https://dex.nadochain.com/static/dex-api.html> (linked from the DEX page) |
| API index (machine-readable) | `GET https://dex.nadochain.com/exec/dexapi` (also `/exec/otc`) |
| SDK (Node 18+ / browser) | [`static/nadodex.mjs`](../static/nadodex.mjs) |
| MCP server, local (trades) | [`static/nadodex-mcp.mjs`](../static/nadodex-mcp.mjs) |
| MCP server, remote (read-only) | `POST https://dex.nadochain.com/exec/otc/mcp` |
| Code | `execnode/otc_api.py` (cross-chain + limit orders), `execnode/amm_api.py` (pools + launchpad), routes in `execnode/execnode.py` |
| Tests | `tests/test_the_dex_api_trades_end_to_end_…`, `tests/test_the_dex_api_covers_every_market_…` |

Any host that serves the exec node answers the same paths: `https://get.nadochain.com/exec/…` and a node's own
`:9273` work too. The SDK defaults to `https://get.nadochain.com`.

---

## 1. Security model — why "free" and "authenticated" are not in tension

* **Authentication is the signature.** A trade is an ordinary NADO transaction: ML-DSA-44 over `create_txid(body)`
  (`static/nadotx.js`, byte-identical to the node). Every node verifies the txid, that the public key derives the
  sender address, and the signature, before anything is applied. Forging a trade means forging the signature.
* **No API keys, sessions or accounts.** There is nothing a server could leak that lets someone trade as you.
* **No key ever crosses the wire.** No endpoint accepts a private key or seed (pinned by the tests). The remote MCP
  endpoint can only read; trading tools exist only in the local MCP server, where the key stays in your process.
* **Use a dedicated trading key.** `node nadodex.mjs keygen` makes one. Fund it with only what the bot may trade. Never
  give a bot your wallet's key.
* **Reads are rate-limited**: 120 requests per minute per IP per endpoint (HTTP 429 beyond). A bot polling once a
  second fits. Decoding is cached per block, so polling costs the node one decode a block.
* **Every amount is exact.** Prices are decimal strings, amounts are raw integer strings or contract units beside a
  decimal rendering. Never parse a price into a float before computing an amount you sign.

## 2. The markets

| market | contract | what it is |
|---|---|---|
| **cross-chain** | `otc` | NADO ↔ real BTC / ETH / SOL / ERC-20 by atomic swap: an L1 HTLC and a foreign HTLC under one SHA-256 hashlock ([dex-bridge.md](dex-bridge.md)) |
| **limit orders** | `otc` (SWAP_INTRA) | any exec-layer asset (or NADO) for any other, both sides swapped atomically in one call |
| **pools** | `dex` | constant-product pools NADO ↔ token; swaps clear at **one price per block** (batch); liquidity positions |
| **launchpad** | `dex` (kind = curve) | bonding-curve launches that graduate into locked pools ([launchpad.md](launchpad.md)) |

Pools, curves and limit orders spend your **exchange balance** (the exec-layer bridge balance). Move NADO onto it with a
deposit, and off it with a withdrawal plus its L1 claim (§5).

## 3. Reads (free)

All `GET`. Add `provisional=1` to read state about one block old instead of the finalized state (about 5 minutes); the
SDK does. Every response carries the `cursor` (block) it was read at.

### Cross-chain

| path | returns |
|---|---|
| `/exec/otc/markets` | one row per market: `market`, `coin`, `token`, `testnet`, `asks`, `bids`, `best_ask`, `best_bid`, `ask_depth_nado`, `bid_depth_nado`, `last_price`, `trades` |
| `/exec/otc/book?market=ETH` | `{market, asks, bids}`: open orders, asks cheapest first, bids dearest first. `market` = `ETH`, `BTC`, `SOL`, a mainnet token symbol (`USDC`), a network key (`eth`, `btct`) or `eth\|0x<token>` |
| `/exec/otc/order?id=` | one order: `side` (ask = maker sells NADO, bid = maker buys NADO), `status` (open, filled, settled, cancelled, refunded, expired), `nado`, `nado_raw`, `foreign`, `price` (foreign per 1 NADO), `hashlock_sha256`, `expn` (NADO-side expiry block), `expf` (foreign deadline, unix s), `taker`, `nado_htlc`, `secret` (once settled) … |
| `/exec/otc/orders?maker=<address>[&status=]` | orders the address made **or** took |
| `/exec/otc/trades[?market=&limit=]` | settled swaps, newest first |

### Limit orders

| path | returns |
|---|---|
| `/exec/otc/intra[?give=<asset>&want=<asset>]` | open limit orders, cheapest first: `give_asset`, `give`, `give_raw`, `want_asset`, `want`, `want_raw`, `price` (want per 1 give), `give_coin`, `want_coin`. Asset `0` is NADO |

### Pools and launchpad

| path | returns |
|---|---|
| `/exec/amm/pools` | every pool and curve. Pools: `reserve_nado`, `reserve_coin`, `shares`, `price_nado` (NADO per coin), `price_coin` (coin per NADO), `live`, `locked_liquidity`. Curves (`kind: "curve"`): `raised_nado`, `sold_pct`, `graduates_at_raise_nado`, `opening_batch`, `price_nado`, `creator` |
| `/exec/amm/pool?id=` | one of them; a prelaunched (reserved, not yet launched) id answers `{pool: null, reserved: true}` |
| `/exec/amm/quote?pool=&side=buy\|sell&amount=` | what ONE order alone in its batch receives: `in`, `out`, `in_units`, `out_units`, `fee_units`, and the `method` to call. **The contract's exact formula.** A batch nets buys against sells first, so a real fill is the quote or better on the side with fewer orders |
| `/exec/amm/order?id=` | a swap order: `side`, `amount_units`, `batch_block`, `claimable`, `claimed`, `cleared`, and `payout_units` once cleared |
| `/exec/amm/position?id=` | a liquidity position: `shares`, `withdraw_nado_units`, `withdraw_coin_units`, `pending_*_units` (staged, not joined) |
| `/exec/amm/balance?address=` | exchange balances: `nado_raw`, `tokens_raw` per asset |
| `/exec/dex_trades?pid=&trader=&limit=` | trade history (swaps, liquidity, launch fills, graduations), finalized blocks only |
| `/exec/dex_candles?pid=&tf=` | OHLCV candles, tf ∈ 60 300 900 3600 14400 86400 |
| `/exec/dex_stats` | per pool: volume, buys, sells and price change over 5 m / 1 h / 6 h / 24 h |

**Units.** The `dex` contract counts both sides in units of 10^8 raw (0.01 NADO; for a token, 10^8 of its raw units).
NADO has 10 decimals; a token's decimals are in `/exec/asset?id=`.

## 4. Writes (signed by you)

Every write is `POST /submit_transaction` with a signed transaction. A contract call is a `blob`:

```json
{ "sender": "<your address>", "recipient": "blob", "amount": 0, "fee": 1000,
  "data": { "op": "call", "contract": "<cid from /exec/dexapi>", "method": "obuy", "args": [pool, order, units, minOut],
            "value": <raw escrowed from your exchange balance>, "asset": "<asset id when the value is a token>" },
  "timestamp": …, "nonce": "<random>", "max_block": <tip + 40>, "chain_id": "<from /status>",
  "public_key": "<hex>", "txid": "<blake2b of the canonical body minus public_key, txid, signature>", "signature": "<ML-DSA-44 over txid>" }
```

The SDK builds all of this. Contract ids come from `/exec/dexapi` (`contracts`), so a redeploy cannot leave a bot
posting into a contract nobody reads.

| market | method (args) — value |
|---|---|
| cross-chain | `post(o, kind, namt, network, foreign, payout, sha256, h0…h7, expn, expf)` · `fill(o, takerForeign, fref)` (bid: 1 % bond) · `bind(o, htlcTxid)` · `settle(o, l0…l4)` · `cancel(o)` · `release(o)` · `expire(o)` · `boost(o)` (NADO tip) |
| cross-chain, L1 | recipient `htlc_lock` {claimant, hashlock, expiry} (fee 1000) · `htlc_claim` {htlc_id, preimage} (fee 0) · `htlc_refund` {htlc_id} (fee 0) |
| limit orders | `post_intra(o, giveAsset, giveRaw, wantAsset, wantRaw, expn)` — value giveRaw of giveAsset · `fill_intra(o)` — value wantRaw of wantAsset · `cancel` · `expire` |
| pools | `obuy(pid, o, units, minOut)` — NADO · `osell(pid, o, units, minOut)` — the coin · `claim(o, assetId)` · `open(pid, assetId)` · `fundn(pos, pid, units)` — NADO · `fundt(pos, pid, units)` — the coin · `join(pos, pid)` · `exit(pos, pid, shares, assetId)` · `refund(pos, pid, assetId)` |
| launchpad | `prelaunch(pid)` — 10 NADO, sealed · `launch(pid, units, virtualNado)` — the whole supply · `buy(pid, o, units)` — NADO · `sell(pid, o, units)` — the coin · `claim(o, assetId)` |
| balance | L1 recipient `bridge` (deposit, fee 1000, `min_block` = tip + 8) · blob `{op: "bridge_withdraw", amount}` · L1 recipient `bridge_withdraw` {addr, amount, nonce, proof} (fee 0, proof from `/exec/withdrawals?address=&root=<GET /get_settled state_root>`) |

Ids (`o`, `pid`, `pos`) are numbers below 2^32 that **you** choose at random. Keep them: they are how you find your
order or position again.

## 5. The SDK

```bash
mkdir -p nado-dex/vendor && cd nado-dex
for f in nadodex.mjs nadodex-mcp.mjs nadotx.js blake2s.js vendor/nado-crypto.js; do
  curl -fsS --create-dirs -o "$f" "https://dex.nadochain.com/static/$f"; done
node nadodex.mjs keygen        # {"seed": "…", "address": "…"}: fund the address, keep the seed secret
node nadodex.mjs markets       # reads need no key
```

```js
import { NadoDex } from "./nadodex.mjs";
const dex = new NadoDex({ key: process.env.DEX_BOT_SEED });     // relay defaults to https://get.nadochain.com

// exchange balance
await dex.deposit("100");                                       // L1 -> exchange
await dex.withdraw("5"); await dex.claimWithdrawals();          // exchange -> L1 (claim once a settle covers it)

// pools and curves
const pools = await dex.pools();
const q = await dex.quote(pid, "buy", "10");                    // exact
const { orderId } = await dex.swap({ pool: pid, side: "buy", amount: "10", slippageBps: 100 });
await dex.claimSwap(orderId);                                   // once its block has passed
const { position } = await dex.addLiquidity({ pool: pid, nado: "100", coin: "1000" });
await dex.removeLiquidity(position);
const { pool } = await dex.launch({ asset: "<id>", supply: "1000000", virtualNado: 50000 });

// limit orders
const { id } = await dex.postLimit({ give: { asset: "0", amount: "5" }, want: { asset: "<id>", amount: "120" } });
await dex.fillLimit(id); await dex.cancel(id);

// cross-chain (the foreign halves: scripts/otc_eth_leg.mjs, scripts/otc_btc_leg.py)
const o = await dex.postAsk({ nado: "50", foreign: "0.0335", network: "eth", payout: "0x…",
                              onSecret: (r) => saveSomewhereDurable(r) });   // BEFORE the order exists
await dex.fill(orderId, "0xMyEthAddress");
await dex.lockNado(orderId); await dex.bind(orderId, lockTxid);
await dex.verifyNadoLeg(orderId);                               // before funding a foreign lock
await dex.settle(orderId, secret); await dex.claimNado(htlcId, secret);
```

The multi-step helpers (`addLiquidity`, `launch`) wait for each step to land before sending the next, with
`waitFor` (default 3 minutes).

**The swap secret is the money.** `postAsk` / `postBid` return the secret that opens both chains. Store it durably
**before** the order can be filled (`onSecret` runs before the post is sent). Lose it and the swap can only expire.

## 6. MCP

### Remote, read-only: nothing to install

Add `https://dex.nadochain.com/exec/otc/mcp` as a Streamable-HTTP MCP server (JSON responses, no session). For
example, `claude mcp add --transport http nado-dex https://dex.nadochain.com/exec/otc/mcp`. Tools:
`dex_markets`, `dex_book`, `dex_order`, `dex_orders`, `dex_trades`, `dex_limit_orders`, `dex_pools`, `dex_quote`,
`dex_swap_order`, `dex_position`, `dex_balance`. None of them can sign.

### Local: trades with your bot's key

```bash
claude mcp add nado-dex -- node /path/to/nado-dex/nadodex-mcp.mjs                            # reads only
claude mcp add nado-dex -e DEX_BOT_SEED=<seed> -- node /path/to/nado-dex/nadodex-mcp.mjs     # + trading
```

With a key it adds `dex_deposit`, `dex_withdraw`, `dex_claim_withdrawals`, `dex_swap`, `dex_claim_swap`,
`dex_add_liquidity`, `dex_remove_liquidity`, `dex_refund_liquidity`, `dex_open_pool`, `dex_launch`, `dex_post_limit`,
`dex_fill_limit`, `dex_post_ask`, `dex_post_bid`, `dex_fill`, `dex_lock_nado`, `dex_bind`, `dex_verify_nado_leg`,
`dex_settle`, `dex_claim_nado`, `dex_refund_nado`, `dex_cancel`, `dex_release`, `dex_expire`, `dex_boost`, plus
`dex_pool_trades`, `dex_candles` and `dex_whoami`. Cross-chain swap secrets are written to `DEX_SECRETS`
(default `./nado-dex-secrets/`, files mode 0600) **before** the order is posted. They are never returned into the
model's context, and `dex_settle` reads them from there.

Environment: `DEX_RELAY` (default `https://get.nadochain.com`), `DEX_EXEC` (default = relay), `DEX_BOT_SEED`,
`DEX_SECRETS`.

## 7. Errors

* `400` with `{"error": "…"}`: a bad parameter, which the message names.
* `404`: no such order, pool or position.
* `429`: over the read limit. Back off for a minute.
* MCP: a bad argument is a tool result with `isError: true` and a readable message; an unknown tool is JSON-RPC
  `-32602`.
* A refused transaction: the SDK throws `refused: <the node's reason>`. A contract call that **reverts** (for example
  a swap whose `minOut` its batch cannot honour) still lands as a no-op, and its order never appears. Check with
  `/exec/amm/order` or `/exec/otc/order`.
