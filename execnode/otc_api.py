"""The cross-chain order book as a TRADING API — free, public, and keyless to the server.

Operator, 2026-11-25: "does this have an api?? … we need a free authenticated secure api!" The `otc` contract's
raw storage was readable at /exec/contract, but only as parallel slot maps a bot had to zip by hand; nothing
named a market, sorted a book or priced an order. This module is that translation, and nothing else:

  * READS are free and need no account: markets, book, one order, a maker's orders, settled trades. They
    are pure functions of the contract's decoded storage plus the exec cursor, so every exec node answers
    the same question with the same JSON and a bot can cross-check two of them.
  * WRITES are not here, and never will be. Authentication is the transaction signature itself: a bot
    builds and signs an `otc` call (or an L1 htlc_lock / htlc_claim / htlc_refund) with ITS OWN key on its
    own machine and posts it to /submit_transaction, where every node verifies it. There is no API key, no
    session and no server-side secret — nothing here can be stolen to trade as someone, and no endpoint
    ever takes a private key (CLAUDE.md §8; the Z7 rule in execnode.main). static/nadodex.mjs is the SDK.

INVARIANT: no float anywhere a client might do arithmetic. Amounts are raw integer strings next to their
decimal rendering, and prices are Decimal strings, because a bot that trusts a rounded float price posts a
lock for the wrong amount.
"""
from decimal import Decimal, InvalidOperation, getcontext

from execnode.games import otc as O

getcontext().prec = 60

# The live order book (static/dex.js OTC_CID). Mirrored, not looked up: a contract id is identity, and a
# page and an API that disagree on it would show two different books. tests/test_the_dex_api_* pin the two.
OTC_CID = "83562ce0cf5ee023d98b366bfcbc6e57"
RAW = 10 ** 10                                     # raw units per NADO (doc nado-raw-units)

# The foreign NETWORKS a market can trade against — static/dex.js NETS (coin symbol and mainnet/testnet),
# mirrored so `?market=ETH` (the page's own URL form) and `?market=eth` both name the same book.
NETS = {
    "btc": ("BTC", False), "btct": ("tBTC", True),
    "eth": ("ETH", False), "eths": ("SepETH", True),
    "sol": ("SOL", False), "sold": ("devSOL", True),
}
# The tokens a market can name, as static/dex.js SEED_TOKENS (every address there was verified against its chain:
# symbol() and decimals() read over JSON-RPC). Mirrored for the LABEL only — the address is the market's identity and
# rides in `token`, because any contract can claim any symbol. An unlisted token is labelled "TOKEN", never guessed.
TOKENS = {
    "eth": {"0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": ("USDC", 6), "0xdac17f958d2ee523a2206206994597c13d831ec7": ("USDT", 6),
            "0x6b175474e89094c44da98b954eedeac495271d0f": ("DAI", 18), "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": ("WBTC", 8),
            "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": ("WETH", 18), "0x514910771af9ca656af840dff83e8264ecf986ca": ("LINK", 18),
            "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984": ("UNI", 18), "0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9": ("AAVE", 18),
            "0xae7ab96520de3a18e5e111b5eaab095312d7fe84": ("stETH", 18), "0x6982508145454ce325ddbe47a25d4ec3d2311933": ("PEPE", 18),
            "0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce": ("SHIB", 18), "0x9f8f72aa9304c8b593d555f12ef6589cc3a579a2": ("MKR", 18),
            "0xb50721bcf8d664c30412cfbc6cf7a15145234ad1": ("ARB", 18), "0xfaba6f8e4a5e8ab82f62fe7c39859fa577269be3": ("ONDO", 18)},
    "eths": {"0x1c7d4b196cb0c7b01d743fbc6116a902379c7238": ("USDC", 6), "0xfff9976782d46cc05630d1f6ebab18b2324d6b14": ("WETH", 18),
             "0x779877a7b0d9e8603169ddbd7836e478b4624789": ("LINK", 18), "0xff34b3d4aee8ddcd6f9afffb6fe49bd371b8a357": ("DAI", 18),
             "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984": ("UNI", 18)},
    "sold": {"4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU": ("USDC", 6)},
}


def coin_of(market):
    """The label of what a market trades against NADO: the token's symbol for a token market, else the network's coin."""
    net, _, tok = str(market or "").partition("|")
    if tok:
        return (TOKENS.get(net, {}).get(tok) or ("TOKEN", 0))[0]
    return NETS.get(net, (net.upper(), False))[0]


STATUS = {O.OPEN: "open", O.FILLED: "filled", O.SETTLED: "settled", O.REFUNDED: "refunded", O.CANCELLED: "cancelled"}
SIDE = {O.ASK: "ask", O.BID: "bid", O.INTRA: "intra"}

# The fields an order row carries, in the decoded view's names (otc.py ABI["_view"]).
_FIELDS = ("kind", "maker", "esc", "namt", "wch", "wamt", "wadr", "hsha", "expn", "expf", "st", "taker", "tadr",
           "fref", "hid", "fillh", "tb", "gast", "wast", "want", "bnty", "prem", "pheld")


def _m(storage, name):
    """One named map of the decoded view; a pair list (msgpack-ordered) is read as a dict."""
    v = (storage or {}).get(name)
    if isinstance(v, list):
        return dict(v)
    return v or {}


def nado_str(raw):
    """Raw units as an exact decimal NADO string — never a float."""
    return format((Decimal(int(raw)) / RAW).normalize(), "f")


def market_of(wch):
    """The market an order trades in: its network key, plus a lowercased EVM token address when it names one
    (static/dex.js mktKeyOf — Solana mints are base58 and case-SENSITIVE, so only 0x addresses are lowered)."""
    net, _, tok = str(wch or "").partition("|")
    if tok:
        return net + "|" + (tok.lower() if tok.lower().startswith("0x") else tok)
    return net


def resolve_market(q):
    """`?market=` as a bot or the page's URL writes it — a network key (eth), a coin symbol (ETH), or a full token
    market (eth|0x…) — as the market key, or None when it names nothing known."""
    q = str(q or "").strip()
    if not q:
        return None
    if "|" in q:
        net = q.split("|", 1)[0].lower()
        return market_of(net + "|" + q.split("|", 1)[1]) if net in NETS else None
    if q.lower() in NETS:
        return q.lower()
    for k, (coin, _test) in NETS.items():
        if coin.lower() == q.lower():
            return k
    for net in ("eth", "sol"):                     # a MAINNET token by symbol (USDC → eth|0xa0b8…); testnets need the key
        for tok, (sym, _d) in TOKENS.get(net, {}).items():
            if sym.lower() == q.lower():
                return net + "|" + tok
    return None


def _price(namt_raw, wamt):
    """The foreign amount per ONE NADO, as an exact Decimal string, or None when either side is unpriceable."""
    try:
        n, w = Decimal(int(namt_raw)) / RAW, Decimal(str(wamt))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if n <= 0 or w <= 0:
        return None
    return format((w / n).quantize(Decimal("1e-18")).normalize(), "f")


def _secret(limbs):
    """The revealed swap secret (64 hex) from the settle() limbs, or None before a settle."""
    if not all(limbs):
        return None
    v = 0
    for i, l in enumerate(limbs):
        v |= int(l) << (O.LIMB_BITS * i)
    return format(v, "064x")


def orders(storage, cursor):
    """Every order in the contract as a self-describing row. `cursor` is the exec cursor the storage was read at:
    an open or filled order at/after its `expn` is shown as `expired` (only `expire` can still move it)."""
    g = {f: _m(storage, f) for f in _FIELDS}
    lim = [_m(storage, "s%d" % i) for i in range(O.LIMBS)]
    out = []
    for o in _m(storage, "mk"):
        kind = int(g["kind"].get(o) or 0)
        if not kind:
            continue
        st, expn = int(g["st"].get(o) or 0), int(g["expn"].get(o) or 0)
        status = STATUS.get(st, "unknown")
        if st in (O.OPEN, O.FILLED) and cursor is not None and int(cursor) >= expn:
            status = "expired"
        row = {"id": int(o), "side": SIDE.get(kind, "unknown"), "status": status, "maker": str(g["maker"].get(o) or ""),
               "expn": expn, "blocks_left": (expn - int(cursor)) if cursor is not None else None}
        if kind == O.INTRA:
            row.update({"give_asset": str(g["gast"].get(o) or "0"), "give_raw": str(int(g["esc"].get(o) or 0)),
                        "want_asset": str(g["wast"].get(o) or "0"), "want_raw": str(int(g["want"].get(o) or 0))})
        else:
            namt = int(g["namt"].get(o) or 0)
            wch = str(g["wch"].get(o) or "")
            net = wch.split("|")[0]
            row.update({
                "market": market_of(wch), "network": net, "coin": coin_of(market_of(wch)),
                "testnet": NETS.get(net, ("", False))[1],
                "nado": nado_str(namt), "nado_raw": str(namt), "foreign": str(g["wamt"].get(o) or ""),
                "price": _price(namt, g["wamt"].get(o)),
                "maker_foreign_address": str(g["wadr"].get(o) or ""), "hashlock_sha256": str(g["hsha"].get(o) or ""),
                "expf": str(g["expf"].get(o) or ""),
                "taker": str(g["taker"].get(o) or "") or None, "taker_foreign_address": str(g["tadr"].get(o) or "") or None,
                "foreign_ref": str(g["fref"].get(o) or "") or None, "nado_htlc": str(g["hid"].get(o) or "") or None,
                "filled_at": int(g["fillh"].get(o) or 0) or None, "taker_bond_raw": str(int(g["tb"].get(o) or 0)),
                "secret": _secret([m.get(o) for m in lim]),
            })
        if int(g["bnty"].get(o) or 0):
            row["bounty_raw"] = str(int(g["bnty"].get(o)))
        out.append(row)
    out.sort(key=lambda r: r["id"])
    return out


def _px(r):
    return Decimal(r["price"]) if r.get("price") else None


def book(rows, market):
    """The OPEN orders of one market, best first: asks (makers SELLING NADO) cheapest first, bids (makers BUYING
    NADO) dearest first — the order a taker walks them. Expired and filled orders are not on a book."""
    live = [r for r in rows if r.get("market") == market and r["status"] == "open" and _px(r) is not None]
    asks = sorted((r for r in live if r["side"] == "ask"), key=lambda r: (_px(r), r["id"]))
    bids = sorted((r for r in live if r["side"] == "bid"), key=lambda r: (-_px(r), r["id"]))
    return {"market": market, "asks": asks, "bids": bids}


def intra(rows, assets, give=None, want=None):
    """The OPEN in-chain limit orders (SWAP_INTRA, §7 — both sides on the exec layer, filled atomically in one call):
    asset ids as strings (0 = native NADO), raw amounts beside decimals in each asset's own decimals, and the price as
    want per ONE give. Optionally one pair. Best (cheapest want per give) first."""
    def dec(a):
        return 10 if str(a) == "0" else int(((assets or {}).get(str(a)) or {}).get("dec", 0) or 0)

    def sym(a):
        return "NADO" if str(a) == "0" else (((assets or {}).get(str(a)) or {}).get("sym") or "?")
    out = []
    for r in rows:
        if r["side"] != "intra" or r["status"] != "open":
            continue
        if (give is not None and r["give_asset"] != str(give)) or (want is not None and r["want_asset"] != str(want)):
            continue
        gd, wd = dec(r["give_asset"]), dec(r["want_asset"])
        g, w = Decimal(int(r["give_raw"])) / (Decimal(10) ** gd), Decimal(int(r["want_raw"])) / (Decimal(10) ** wd)
        out.append(dict(r, give_coin=sym(r["give_asset"]), want_coin=sym(r["want_asset"]),
                        give=format(g.normalize(), "f"), want=format(w.normalize(), "f"),
                        price=format((w / g).quantize(Decimal("1e-18")).normalize(), "f") if g > 0 else None))
    out.sort(key=lambda r: (Decimal(r["price"]) if r["price"] else Decimal("Infinity"), r["id"]))
    return out


def _sum_raw(rs):
    return sum(int(r["nado_raw"]) for r in rs)


def markets(rows):
    """One summary row per market that has ever held an order: open depth and best prices on each side, and the
    last settled price. Testnet markets are flagged, never mixed in silently."""
    keys = sorted({r["market"] for r in rows if r.get("market")})
    out = []
    for k in keys:
        b = book(rows, k)
        done = sorted((r for r in rows if r.get("market") == k and r["status"] == "settled"),
                      key=lambda r: (r.get("filled_at") or 0, r["id"]))
        net = k.split("|")[0]
        out.append({"market": k, "network": net, "coin": coin_of(k),
                    "token": k.split("|", 1)[1] if "|" in k else None, "testnet": NETS.get(net, ("", False))[1],
                    "asks": len(b["asks"]), "bids": len(b["bids"]),
                    "best_ask": b["asks"][0]["price"] if b["asks"] else None,
                    "best_bid": b["bids"][0]["price"] if b["bids"] else None,
                    "ask_depth_nado": nado_str(_sum_raw(b["asks"])), "bid_depth_nado": nado_str(_sum_raw(b["bids"])),
                    "last_price": done[-1]["price"] if done else None, "trades": len(done)})
    return out


def trades(rows, market=None, limit=100):
    """Settled swaps, newest first (by the block their fill landed in). A settled order's secret is public — it
    was revealed on-chain to finish the swap — so it rides along for any watchtower."""
    done = [r for r in rows if r["status"] == "settled" and r.get("market") and (market is None or r["market"] == market)]
    done.sort(key=lambda r: (-(r.get("filled_at") or 0), -r["id"]))
    return done[:max(1, min(500, int(limit)))]


def index(base=""):
    """The API's own description, served at GET /exec/otc (and /exec/dexapi) — so every endpoint of every market is
    found from the API itself, not from the source (CLAUDE.md §9)."""
    from execnode import amm_api
    return {
        "name": "NADO DEX API",
        "free": True, "api_key": None,
        "auth": "Every write is a transaction signed by your own key on your own machine and posted to "
                "POST /submit_transaction; every node verifies the signature. No account, no API key, and no "
                "endpoint ever takes a private key. Use a dedicated trading key, never your wallet's.",
        "contracts": {"cross_chain_and_limit_orders": OTC_CID, "pools_and_launchpad": amm_api.DEX_CID},
        "contract": OTC_CID,
        "rate_limit": "%d requests / minute / IP per endpoint" % READ_LIMIT,
        "markets": {
            "cross_chain": {
                "about": "NADO against real BTC / ETH / SOL / ERC-20 by atomic swap (HTLC on both chains, no custodian)",
                "reads": {
                    base + "/exec/otc/markets": "every market: open depth, best ask/bid, last price",
                    base + "/exec/otc/book?market=ETH": "open orders of one market, best first (ETH, BTC, USDC, eth, eth|0x…)",
                    base + "/exec/otc/order?id=<id>": "one order in full, including the revealed secret once settled",
                    base + "/exec/otc/orders?maker=<address>&status=open": "an address's orders, made or taken",
                    base + "/exec/otc/trades?market=ETH&limit=100": "settled swaps, newest first",
                },
                "writes": "post · fill · bind · settle · cancel · release · expire · boost (otc contract) + L1 htlc_lock / "
                          "htlc_claim / htlc_refund",
            },
            "limit_orders": {
                "about": "in-chain limit orders: any exec asset (or NADO) for any other, filled atomically in one call",
                "reads": {base + "/exec/otc/intra?give=<asset id>&want=<asset id>": "open limit orders, best first (0 = NADO)"},
                "writes": "post_intra · fill_intra · cancel · expire (otc contract)",
            },
            "pools": {
                "about": "constant-product pools, NADO ↔ token, swaps cleared at one price per block; liquidity positions",
                "reads": {k: v for k, v in amm_api.index(base).items()},
                "writes": "obuy · osell · claim · open · fundn · fundt · join · exit · refund (dex contract)",
            },
            "launchpad": {
                "about": "bonding-curve launches that graduate into locked pools",
                "reads": {base + "/exec/amm/pools": "curves are the rows with kind = curve (raise, sold %, opening batch)"},
                "writes": "prelaunch · launch · buy · sell · claim (dex contract)",
            },
        },
        "balances": {
            "exchange": base + "/exec/amm/balance?address=<address>",
            "deposit": "L1 tx to recipient 'bridge' (NadoDex.deposit)",
            "cash_out": "blob bridge_withdraw, then L1 bridge_withdraw with the proof from /exec/withdrawals (NadoDex.withdraw / claimWithdrawals)",
        },
        "reads": {
            base + "/exec/otc/markets": "cross-chain markets",
            base + "/exec/otc/book?market=ETH": "cross-chain book",
            base + "/exec/otc/order?id=<id>": "one cross-chain or limit order",
            base + "/exec/otc/orders?maker=<address>": "an address's orders",
            base + "/exec/otc/trades?market=ETH": "settled cross-chain swaps",
            base + "/exec/otc/intra": "limit orders",
            base + "/exec/amm/pools": "pools and launch curves",
            base + "/exec/amm/quote?pool=<id>&side=buy&amount=1": "exact quote",
        },
        "sdk": "/static/nadodex.mjs (Node 18+ or a browser; signs locally with nadotx.js)",
        "mcp": {"remote (read-only)": base + "/exec/otc/mcp",
                "local (trading, your own key)": "node nadodex-mcp.mjs  (/static/nadodex-mcp.mjs; NADO_BOT_SEED=<seed>)"},
        "docs": {"page": "https://dex.nadochain.com/static/dex-api.html",
                 "reference": "https://github.com/hclivess/nado/blob/main/doc/dex-api.md"},
        "prices": "exact decimal strings; amounts are raw integer strings or contract units beside decimals",
    }


READ_LIMIT = 120                                   # per IP per endpoint per minute: a bot polling every second fits


# ---- the remote MCP endpoint: POST /exec/otc/mcp ---------------------------------------------------------------------
# Operator 2026-11-25: "also this dex needs an mcp server". A Streamable-HTTP MCP server (JSON responses, no session)
# that ANY MCP client adds by URL alone. READ-ONLY by construction: its tools are these reads and nothing else, so a
# remote endpoint can never be asked to sign — trading tools live only in the LOCAL server, static/nadodex-mcp.mjs,
# where the bot's key stays in the bot's own process (CLAUDE.md §8).
MCP_PROTOCOL = "2025-06-18"
_MS = lambda props, req=(): {"type": "object", "properties": props, "required": list(req), "additionalProperties": False}
_MARKET = {"type": "string", "description": "ETH, BTC, USDC, a network key (eth, btc) or eth|0x<token>"}
MCP_TOOLS = [
    {"name": "dex_markets", "description": "Every NADO cross-chain market: open depth, best ask/bid (foreign coin per 1 NADO), last price.",
     "inputSchema": _MS({})},
    {"name": "dex_book", "description": "The open order book of one market, best first. Asks sell NADO, bids buy NADO.",
     "inputSchema": _MS({"market": _MARKET}, ["market"])},
    {"name": "dex_order", "description": "One order in full: status, parties, amounts, locks, and the revealed secret once settled.",
     "inputSchema": _MS({"id": {"type": "integer"}}, ["id"])},
    {"name": "dex_orders", "description": "The orders a NADO address made or took.",
     "inputSchema": _MS({"maker": {"type": "string"}, "status": {"type": "string"}}, ["maker"])},
    {"name": "dex_trades", "description": "Settled cross-chain swaps, newest first.",
     "inputSchema": _MS({"market": _MARKET, "limit": {"type": "integer"}})},
    {"name": "dex_limit_orders", "description": "Open in-chain limit orders (any token or NADO for any other), best first. Asset id 0 = NADO.",
     "inputSchema": _MS({"give": {"type": "string"}, "want": {"type": "string"}})},
    {"name": "dex_pools", "description": "Every AMM pool and launchpad curve: reserves, price (NADO per coin and coin per NADO), liquidity, curve progress.",
     "inputSchema": _MS({})},
    {"name": "dex_quote", "description": "Exact quote for one swap on a pool or curve: side buy spends NADO, sell spends the coin; amount is a decimal.",
     "inputSchema": _MS({"pool": {"type": "integer"}, "side": {"type": "string", "enum": ["buy", "sell"]}, "amount": {"type": "string"}}, ["pool", "side", "amount"])},
    {"name": "dex_swap_order", "description": "A pool/curve swap order by id: its batch, whether it can be claimed, and its exact payout once cleared.",
     "inputSchema": _MS({"id": {"type": "integer"}}, ["id"])},
    {"name": "dex_position", "description": "A liquidity position by id: shares, what they withdraw now, staged deposits.",
     "inputSchema": _MS({"id": {"type": "integer"}}, ["id"])},
    {"name": "dex_balance", "description": "An address's exchange balances: NADO and every token (raw).",
     "inputSchema": _MS({"address": {"type": "string"}}, ["address"])},
]


def _mcp_tool(name, a, ctx):
    """One read tool's result (a JSON-able dict). `ctx` holds the node-side readers (execnode.h_otc_mcp). Raises
    ValueError with a user-facing reason on bad input."""
    if name in ctx.get("extra", {}):
        return ctx["extra"][name](a)
    rows, cursor = ctx["rows"]()
    if name == "dex_markets":
        return {"cursor": cursor, "markets": markets(rows)}
    if name == "dex_book":
        mk = resolve_market(a.get("market"))
        if mk is None:
            raise ValueError("unknown market — try ETH, BTC, USDC or eth|0x<token>")
        return dict(book(rows, mk), cursor=cursor)
    if name == "dex_order":
        row = next((r for r in rows if r["id"] == int(a.get("id", -1))), None)
        if row is None:
            raise ValueError("no such order")
        return {"cursor": cursor, "order": row}
    if name == "dex_orders":
        who, status = str(a.get("maker") or ""), str(a.get("status") or "")
        return {"cursor": cursor, "orders": [r for r in rows if (r["maker"] == who or r.get("taker") == who)
                                             and (not status or r["status"] == status)]}
    if name == "dex_trades":
        mk = resolve_market(a["market"]) if a.get("market") else None
        if a.get("market") and mk is None:
            raise ValueError("unknown market")
        return {"cursor": cursor, "trades": trades(rows, mk, int(a.get("limit") or 50))}
    raise KeyError(name)


def mcp_handle(msg, ctx):
    """Answer one JSON-RPC message, or None for a notification. ctx = {"rows": () -> (rows, cursor), "extra": {tool:
    fn(args)}} — called only by a tool call, so initialize/tools/list never decode a book. Pure apart from ctx."""
    import json
    if not isinstance(msg, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    ok = lambda result: {"jsonrpc": "2.0", "id": mid, "result": result}
    if method == "initialize":
        return ok({"protocolVersion": MCP_PROTOCOL, "capabilities": {"tools": {}},
                   "serverInfo": {"name": "nado-dex", "version": "1"},
                   "instructions": "NADO DEX, read-only: cross-chain atomic swaps (BTC/ETH/SOL), in-chain limit orders, "
                                   "AMM pools and the launchpad. Cross-chain prices are foreign coin per 1 NADO. To trade, "
                                   "run the local server static/nadodex-mcp.mjs with the bot's own key."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": MCP_TOOLS})
    if method == "tools/call":
        name, a = params.get("name"), params.get("arguments") or {}
        if name not in {t["name"] for t in MCP_TOOLS}:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}}
        try:
            out = _mcp_tool(name, a, ctx)
            return ok({"content": [{"type": "text", "text": json.dumps(out, indent=1)}]})
        except (ValueError, TypeError) as e:
            return ok({"content": [{"type": "text", "text": str(e)}], "isError": True})
    if mid is None:
        return None
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}
