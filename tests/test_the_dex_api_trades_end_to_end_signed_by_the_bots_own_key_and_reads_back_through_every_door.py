"""THE DEX API TRADES END TO END, SIGNED BY THE BOT'S OWN KEY, AND READS BACK THROUGH EVERY DOOR.

Operator 2026-11-25: "does this have an api?? … we need a free authenticated secure api!", "also this dex needs an mcp
server", "make sure to test everything end to end". The API is four parts — the free reads (execnode/otc_api.py behind
/exec/otc/*), the SDK (static/nadodex.mjs) that builds and SIGNS locally, the local MCP server (static/nadodex-mcp.mjs)
and the remote read-only MCP endpoint (/exec/otc/mcp). Each is driven here as its user drives it, across every hop:

  node SDK / MCP server  --signed tx-->  an L1 stand-in that checks what the node checks (txid, sender = key, ML-DSA
  signature, the real _validate_htlc_lock)  -->  the REAL otc contract in a REAL ExecState  -->  the REAL exec
  handlers  -->  read back by the SDK, by curl-style GETs, and by both MCP servers.

A full swap walks through it: two asks and a bid posted, the book sorted and priced exactly, a fill, the NADO leg
locked in an L1 HTLC and bound, the taker's pre-funding check, settle, the secret public, the HTLC claimed, a cancel,
a BID fill carrying its bond. Then the doors: unknown market 400, the per-IP read limit 429, MCP initialize / list /
call / notification / batch, the remote MCP offering nothing that signs, the local one offering trading tools only
with a key and writing the swap secret to disk BEFORE the order exists (and never returning it into a model's
context). And the mirrors that keep the page and the API one book: OTC_CID, NETS and the token list.

Run: python3 tests/test_the_dex_api_trades_end_to_end_signed_by_the_bots_own_key_and_reads_back_through_every_door.py
"""
import _harness
HOME = _harness.isolate("nado-test-dex-api-")
import os
os.environ["NADO_ALLOW_PYTHON_KERNELS"] = "1"
import asyncio, hashlib, json, re, tempfile

import _dex_api_fixture as F
from execnode import otc_api as A

T = _harness.Report()
REPO, STATIC = F.REPO, F.STATIC
C = F.Chain(HOME)
st, CID = C.st, C.otc
HTLCS, SUBMITTED = C.htlcs, C.submitted
node, Mcp = F.node, F.Mcp


async def main():
    base = await C.serve()
    mk = lambda seed: F.sdk(base, seed)
    import aiohttp
    http = aiohttp.ClientSession()
    get = lambda path: http.get(base + path)

    # ---- keys: each bot makes its OWN (NadoDex.keygen) — no wallet key anywhere ----------------------------------
    keys = await node("console.log(JSON.stringify([D.NadoDex.keygen(), D.NadoDex.keygen(), D.NadoDex.keygen()]));")
    (M, TK, B) = keys
    for k in keys:
        st.bridge[k["address"]] = 10 ** 14
    T.check("NadoDex.keygen makes a fresh 64-hex seed and its address", all(re.fullmatch(r"[0-9a-f]{64}", k["seed"]) for k in keys)
            and len({k["address"] for k in keys}) == 3)

    # ---- the free reads describe themselves --------------------------------------------------------------------------
    idx = await (await get("/exec/otc")).json()
    T.check("GET /exec/otc describes the API: free, no API key, every market's reads, the SDK, both MCP servers",
            idx["free"] is True and idx["api_key"] is None and set(idx["markets"]) == {"cross_chain", "limit_orders", "pools", "launchpad"} and "nadodex.mjs" in idx["sdk"]
            and "/exec/otc/mcp" in json.dumps(idx["mcp"]) and "nadodex-mcp.mjs" in json.dumps(idx["mcp"]), idx)

    # ---- makers post through the SDK, signed locally ------------------------------------------------------------------
    a1 = await node(mk(M["seed"]) + 'console.log(JSON.stringify(await dex.postAsk({ nado: "50", foreign: "0.0335", network: "eth", payout: "0x406Ed37679f237EA099985D8C9CE96B538F916b0" })));')
    a2 = await node(mk(M["seed"]) + 'console.log(JSON.stringify(await dex.postAsk({ nado: "50", foreign: "0.035175", network: "eth", payout: "0x406Ed37679f237EA099985D8C9CE96B538F916b0" })));')
    b1 = await node(mk(B["seed"]) + 'console.log(JSON.stringify(await dex.postBid({ nado: "10", foreign: "0.0001", network: "btc", payout: "bc1qbid|02aa", blocks: 3000 })));')
    T.check("three SDK-signed posts passed the node's txid / sender / signature checks and landed",
            len(SUBMITTED) == 3 and all(t["recipient"] == "blob" and t["data"]["method"] == "post" for t in SUBMITTED))
    T.check("the SDK's hashlock is the one the contract checks (the posted order holds hsha = SHA-256(secret))",
            hashlib.sha256(bytes.fromhex(a1["secret"])).hexdigest() == a1["hashlock"])

    mkts = (await (await get("/exec/otc/markets")).json())["markets"]
    eth = next(m for m in mkts if m["market"] == "eth")
    btc = next(m for m in mkts if m["market"] == "btc")
    T.check("markets: ETH has two asks, best 0.00067 ETH per NADO, 100 NADO deep; BTC one bid at 0.00001",
            eth["asks"] == 2 and eth["best_ask"] == "0.00067" and eth["ask_depth_nado"] == "100" and eth["coin"] == "ETH"
            and btc["bids"] == 1 and btc["best_bid"] == "0.00001", mkts)
    bk = await (await get("/exec/otc/book?market=ETH")).json()
    bk2 = await (await get("/exec/otc/book?market=eth")).json()
    T.check("book: asks cheapest first, prices exact decimal strings, amounts raw beside decimal",
            [r["price"] for r in bk["asks"]] == ["0.00067", "0.0007035"] and bk["asks"][0]["nado"] == "50"
            and bk["asks"][0]["nado_raw"] == str(50 * 10 ** 10) and isinstance(bk["asks"][0]["price"], str), bk["asks"][:1])
    T.check("?market=ETH (the page's URL form) and ?market=eth name the same book", bk["asks"] == bk2["asks"])
    T.check("the book names the maker by address, as the SDK reads it", bk["asks"][0]["maker"] == M["address"], bk["asks"][0]["maker"])
    r = await get("/exec/otc/book?market=DOGE")
    T.check("an unknown market is a 400 that says what to try", r.status == 400 and "ETH" in (await r.json())["error"])

    # ---- a full ASK swap: fill -> NADO lock -> bind -> taker's check -> settle -> claim ---------------------------------
    o1 = a1["id"]
    await node(mk(TK["seed"]) + f'console.log(JSON.stringify(await dex.fill({o1}, "0x1111111111111111111111111111111111111111")));')
    od = (await (await get(f"/exec/otc/order?id={o1}")).json())["order"]
    T.check("fill: the order is filled and names the taker", od["status"] == "filled" and od["taker"] == TK["address"], od["status"])
    T.check("a filled order is off the book", o1 not in [x["id"] for x in (await (await get("/exec/otc/book?market=eth")).json())["asks"]])

    lock = await node(mk(M["seed"]) + f'console.log(JSON.stringify(await dex.lockNado({o1})));')
    h = HTLCS.get(lock)
    T.check("lockNado: an L1 htlc_lock the node's own validator accepts — the order's amount and hashlock, for the taker",
            h and h["amount"] == 50 * 10 ** 10 and h["hashlock"] == a1["hashlock"] and h["claimant"] == TK["address"], h)
    await node(mk(M["seed"]) + f'console.log(JSON.stringify(await dex.bind({o1}, "{lock}")));')
    od = (await (await get(f"/exec/otc/order?id={o1}")).json())["order"]
    T.check("bind: the order points at the L1 lock by the id /get_htlc answers", od["nado_htlc"] == lock, od["nado_htlc"])
    ok = await node(mk(TK["seed"]) + f'console.log(JSON.stringify(await dex.verifyNadoLeg({o1})));')
    T.check("verifyNadoLeg: the taker's pre-funding check passes on the real lock", ok["claimant"] == TK["address"])
    bad = await node(mk(B["seed"]) + f'try {{ await dex.verifyNadoLeg({o1}); console.log("null"); }} catch (e) {{ console.log(JSON.stringify(String(e.message))); }}')
    T.check("…and refuses a key the lock does not pay", isinstance(bad, str) and "not claimable" in bad, bad)

    await node(mk(M["seed"]) + f'console.log(JSON.stringify(await dex.settle({o1}, "{a1["secret"]}")));')
    od = (await (await get(f"/exec/otc/order?id={o1}")).json())["order"]
    T.check("settle: the order is settled and its secret is public in the API", od["status"] == "settled" and od["secret"] == a1["secret"], od["status"])
    tr = (await (await get("/exec/otc/trades?market=ETH")).json())["trades"]
    T.check("trades lists the swap at its price", [t["id"] for t in tr] == [o1] and tr[0]["price"] == "0.00067")
    T.check("markets carries the last price", next(m for m in (await (await get("/exec/otc/markets")).json())["markets"]
                                                 if m["market"] == "eth")["last_price"] == "0.00067")
    await node(mk(TK["seed"]) + f'console.log(JSON.stringify(await dex.claimNado("{lock}", "{od["secret"]}")));')
    T.check("claimNado: the taker takes the NADO with the published secret (fee-exempt)", HTLCS[lock]["status"] == "claimed"
            and SUBMITTED[-1]["fee"] == 0)

    # ---- cancel and a BID fill with its bond -------------------------------------------------------------------------
    await node(mk(M["seed"]) + f'console.log(JSON.stringify(await dex.cancel({a2["id"]})));')
    T.check("cancel: the order is cancelled and leaves the book",
            (await (await get(f"/exec/otc/order?id={a2['id']}")).json())["order"]["status"] == "cancelled"
            and not (await (await get("/exec/otc/book?market=eth")).json())["asks"])
    bal0 = st.bridge[TK["address"]]
    await node(mk(TK["seed"]) + f'console.log(JSON.stringify(await dex.fill({b1["id"]}, "bc1qtaker")));')
    od = (await (await get(f"/exec/otc/order?id={b1['id']}")).json())["order"]
    T.check("a BID fill carries the 1 % taker bond (10 NADO -> 0.1 NADO), held by the contract",
            od["status"] == "filled" and bal0 - st.bridge[TK["address"]] == 10 ** 9 and od["taker_bond_raw"] == str(10 ** 9),
            (bal0 - st.bridge[TK["address"]], od["taker_bond_raw"]))
    mine = await node(mk(M["seed"]) + 'console.log(JSON.stringify(await dex.orders()));')
    T.check("orders(): a maker's own orders, by its own key's address", sorted(x["id"] for x in mine) == sorted([o1, a2["id"]]))
    r = await get("/exec/otc/orders")
    T.check("?maker= is required (no dump of every party)", r.status == 400)

    # ---- the remote MCP endpoint: read-only by construction ----------------------------------------------------------
    post = lambda body: http.post(base + "/exec/otc/mcp", json=body)
    ini = await (await post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})).json()
    T.check("remote MCP: initialize names the server and the protocol", ini["result"]["serverInfo"]["name"] == "nado-dex"
            and ini["result"]["protocolVersion"] == A.MCP_PROTOCOL)
    tl = (await (await post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})).json())["result"]["tools"]
    T.check("remote MCP lists every market's reads and NOTHING that signs", sorted(t["name"] for t in tl) ==
            sorted(["dex_book", "dex_markets", "dex_order", "dex_orders", "dex_trades", "dex_limit_orders", "dex_pools",
                    "dex_quote", "dex_swap_order", "dex_position", "dex_balance"]))
    c = (await (await post({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "dex_trades", "arguments": {"market": "ETH"}}})).json())
    T.check("remote MCP tools/call answers from the live book", json.loads(c["result"]["content"][0]["text"])["trades"][0]["id"] == o1)
    c = (await (await post({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "dex_post_ask", "arguments": {}}})).json())
    T.check("remote MCP refuses a trading tool by name", c.get("error", {}).get("code") == -32602)
    c = (await (await post({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "dex_book", "arguments": {"market": "DOGE"}}})).json())
    T.check("remote MCP: a bad argument is a tool error the model can read, not a crash", c["result"]["isError"] is True)
    r = await post({"jsonrpc": "2.0", "method": "notifications/initialized"})
    T.check("remote MCP: a notification gets 202 and no body", r.status == 202)
    bt = await (await post([{"jsonrpc": "2.0", "id": 6, "method": "ping"}, {"jsonrpc": "2.0", "id": 7, "method": "tools/list"}])).json()
    T.check("remote MCP answers a batch", [x["id"] for x in bt] == [6, 7])
    T.check("GET on the MCP endpoint says to POST", (await get("/exec/otc/mcp")).status == 405)

    # ---- the local MCP server over stdio -----------------------------------------------------------------------------
    sec = tempfile.mkdtemp(dir=HOME)
    async with Mcp({"DEX_RELAY": base}) as m:
        await m.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
        await m.rpc("notifications/initialized", notify=True)
        names = {t["name"] for t in (await m.rpc("tools/list"))["result"]["tools"]}
        T.check("local MCP without a key: reads only", "dex_book" in names and not any(n.startswith("dex_post") for n in names), names)
        _r, txt = await m.call("dex_book", {"market": "ETH"})
        T.check("local MCP reads the book", json.loads(txt)["market"] == "eth")
    async with Mcp({"DEX_RELAY": base, "DEX_BOT_SEED": M["seed"], "DEX_SECRETS": sec}) as m:
        await m.rpc("initialize", {})
        names = {t["name"] for t in (await m.rpc("tools/list"))["result"]["tools"]}
        T.check("local MCP with the bot's key adds the trading tools",
                {"dex_post_ask", "dex_post_bid", "dex_fill", "dex_lock_nado", "dex_bind", "dex_settle", "dex_cancel"} <= names)
        _r, txt = await m.call("dex_whoami")
        T.check("dex_whoami is the key's address", json.loads(txt)["address"] == M["address"])
        n0 = len(SUBMITTED)
        r, txt = await m.call("dex_post_ask", {"nado": "25", "foreign": "0.02", "network": "eth", "payout": "0x406Ed37679f237EA099985D8C9CE96B538F916b0"})
        got = json.loads(txt)
        f = os.path.join(sec, f"order-{got['id']}.json")
        rec = json.load(open(f)) if os.path.exists(f) else {}
        T.check("dex_post_ask lands a signed post", not r.get("isError") and len(SUBMITTED) == n0 + 1, txt[:200])
        T.check("the swap secret is on disk (0600) and matches the order's hashlock",
                rec.get("secret") and hashlib.sha256(bytes.fromhex(rec["secret"])).hexdigest() == got["hashlock"]
                and (os.stat(f).st_mode & 0o777) == 0o600)
        T.check("the secret is NOT returned into the model's context", rec.get("secret", "x") not in txt and "secret" not in got)
        T.check("the order is on the book the remote MCP reads", got["id"] in
                [x["id"] for x in json.loads((await (await post({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                    "params": {"name": "dex_book", "arguments": {"market": "ETH"}}})).json())["result"]["content"][0]["text"])["asks"]])
        r, txt = await m.call("dex_cancel", {"id": got["id"]})
        T.check("dex_cancel takes it off", not r.get("isError") and
                (await (await get(f"/exec/otc/order?id={got['id']}")).json())["order"]["status"] == "cancelled", txt)

    # ---- the read limit: free, but not a free flood ------------------------------------------------------------------
    codes = [(await get("/exec/otc/trades")).status for _ in range(A.READ_LIMIT + 2)]
    T.check(f"per IP, each read answers {A.READ_LIMIT} a minute and then 429s", codes.count(429) >= 1 and codes[0] == 200, codes[-3:])
    await http.close()
    await C.srv.close()


asyncio.run(main())

# ---- one book: the page, the API and the SDK name the same contract, networks and tokens ---------------------------------
dexjs = open(os.path.join(STATIC, "dex.js")).read()
sdk = open(os.path.join(STATIC, "nadodex.mjs")).read()
api_src = open(os.path.join(REPO, "execnode", "otc_api.py")).read()
cid = re.search(r'const OTC_CID = "([0-9a-f]+)"', dexjs).group(1)
T.check("OTC_CID is one id in the page, the API and the SDK",
        re.search(r'OTC_CID = "([0-9a-f]+)"', api_src).group(1) == cid == re.search(r'OTC_CID = "([0-9a-f]+)"', sdk).group(1))
nets = dict(re.findall(r'^\s+(\w+):\s+\{ chain: "\w+", coin: "(\w+)"', dexjs, re.M))
T.check("NETS mirrors the page's networks and coins", nets == {k: v[0] for k, v in A.NETS.items()}, nets)
seed = dexjs[dexjs.index("const SEED_TOKENS = {"):]
seed = seed[:seed.index("\n};")]
page_tok, net = set(), None
for line in seed.splitlines():
    hd = re.match(r"^  (\w+): \{", line)
    net = hd.group(1) if hd else net
    for addr, sym in re.findall(r'"([0-9a-zA-Zx]+)": \{ sym: "(\w+)"', line):
        page_tok.add((net, addr, sym))
api_tok = {(net, addr, sym) for net, t in A.TOKENS.items() for addr, (sym, _d) in t.items()}
T.check("TOKENS mirrors the page's verified token list", page_tok == api_tok, page_tok ^ api_tok)
en = open(os.path.join(REPO, "execnode", "execnode.py")).read()
T.check("every API route is registered in the exec node",
        all(f'"/exec/otc{p}"' in en for p in ("", "/markets", "/book", "/order", "/orders", "/trades", "/mcp")))
handlers = "".join(re.findall(r"\nasync def h_otc.*?(?=\n(?:async )?def |\n# ----)", en, re.S)) + \
    "".join(re.findall(r"\ndef _otc.*?(?=\n(?:async )?def |\n# ----)", en, re.S))
props = {k for t in A.MCP_TOOLS for k in t["inputSchema"]["properties"]}
T.check("no API door can take a key: no remote MCP tool input and no /exec/otc handler parameter names a key or seed",
        not any(re.search(r"key|seed|priv|secret", k) for k in props) and handlers
        and not re.search(r"query\.get\(\"(?:key|seed|priv\w*|secret)\"|private_key|privateKey", handlers), props)
T.done("ALL PASS — the DEX API trades end to end and reads back through every door")
