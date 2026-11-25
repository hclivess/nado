"""THE DEX API COVERS EVERY MARKET — POOLS, LAUNCHES, LIMIT ORDERS AND THE EXCHANGE BALANCE — END TO END.

Operator 2026-11-25: "all sumbarkets need to be fully covered", "make sure to test everything end to end". The page
trades four markets; the cross-chain book is walked by test_the_dex_api_trades_end_to_end_…; this walks the other three
and the balance they all spend, each signed by the SDK in Node, checked by the node's own transaction checks, applied by
the REAL `dex` / `otc` contracts, and read back through /exec/amm/*, /exec/otc/intra and both MCP servers:

  * the exchange balance: deposit (L1 -> exchange), withdraw + claimWithdrawals (exchange -> L1);
  * a POOL: open, add liquidity in the contract's three awaited steps, an exact quote, a buy and a sell each paid
    EXACTLY its quote (alone in its batch the contract pays the quote's formula — amm_api.quote is that formula), a
    swap whose limit the batch cannot honour refused, liquidity withdrawn in full;
  * a LAUNCH: the sealed fee, the supply onto a curve, a buy in the opening batch that is NOT claimable until the
    opening window ends (the contract refuses it; the API must say so), then claimed for exactly its quote;
  * a LIMIT ORDER: posted with its give side escrowed, priced in the book, filled atomically, both sides paid;
  * the local MCP server doing the same as an agent would (deposit, swap, claim, limit order) and the remote one reading
    every market. And the page's DEX contract id is the API's.

Run: python3 tests/test_the_dex_api_covers_every_market_pools_launches_limit_orders_and_the_exchange_balance.py
"""
import _harness
HOME = _harness.isolate("nado-test-dex-api-markets-")
import os
os.environ["NADO_ALLOW_PYTHON_KERNELS"] = "1"
import asyncio, json, re

import _dex_api_fixture as F
from execnode import amm_api
from execnode.games import dex as D
from execnode.state import asset_id

T = _harness.Report()
C = F.Chain(HOME)
st = C.st
U = D.UNIT
NADO = 10 ** 10


def results_since(n):
    return C.results[n:]


async def main():
    import aiohttp
    base = await C.serve()
    http = aiohttp.ClientSession()
    get = lambda p: http.get(base + p)
    j = lambda p: get(p)

    async def J(p):
        return await (await j(p)).json()
    keys = await F.node("console.log(JSON.stringify([D.NadoDex.keygen(), D.NadoDex.keygen()]));")
    LP, TR = keys
    for k in keys:
        C.l1[k["address"]] = 10 ** 15                       # L1 money; the exchange starts empty
    lp, tr = F.sdk(base, LP["seed"]), F.sdk(base, TR["seed"])
    run = lambda who, js: F.node(who + js)

    # ---- the exchange balance: deposit ---------------------------------------------------------------------------
    await run(lp, 'console.log(JSON.stringify(await dex.deposit("500")));')
    await run(tr, 'console.log(JSON.stringify(await dex.deposit("200")));')
    b = await J(f"/exec/amm/balance?address={TR['address']}")
    T.check("deposit: an L1 'bridge' tx (with its min_block guard) moves NADO onto the exchange",
            b["nado_raw"] == str(200 * NADO) and C.l1[TR["address"]] == 10 ** 15 - 200 * NADO
            and C.submitted[-1].get("min_block") is not None, b)

    # ---- a POOL ----------------------------------------------------------------------------------------------------
    st.apply_blob({"op": "asset_create", "seed": 1, "name": "Moon", "sym": "MOON", "dec": 8, "supply": 10 ** 6 * 10 ** 8,
                   "mintable": False}, LP["address"], "ac1")
    AID = str(asset_id(LP["address"], 1))
    PID = 4242
    await run(lp, f'console.log(JSON.stringify(await dex.openPool({PID}, "{AID}")));')
    liq = await run(lp, f'console.log(JSON.stringify(await dex.addLiquidity({{ pool: {PID}, nado: "100", coin: "1000" }})));')
    pool = (await J(f"/exec/amm/pool?id={PID}"))["pool"]
    T.check("addLiquidity: open, stage NADO, stage the coin, join — a live pool of 100 NADO / 1000 MOON at 0.1 NADO a coin",
            pool["live"] and pool["reserve_nado"] == "100" and pool["reserve_coin"] == "1000" and pool["price_nado"] == "0.1"
            and pool["price_coin"] == "10" and pool["coin"] == "MOON", pool)
    pos = (await J(f"/exec/amm/position?id={liq['position']}"))["position"]
    T.check("the position holds the pool's shares and withdraws its reserves", pos["shares"] == pool["shares"] > 0
            and pos["withdraw_nado_units"] == 100 * NADO // U and pos["pending_nado_units"] == 0, pos)
    T.check("/exec/amm/pools lists it", any(p["id"] == PID for p in (await J("/exec/amm/pools"))["pools"]))

    q = await J(f"/exec/amm/quote?pool={PID}&side=buy&amount=10")
    rn, rt, dx = 100 * NADO // U, 1000 * 10 ** 8 // U, 10 * NADO // U
    want = rt * (dx * D.FEE_NUM // D.FEE_DEN) // (rn + dx * D.FEE_NUM // D.FEE_DEN)
    T.check("quote is the contract's formula: 10 NADO buys rt·dx'/(rn+dx') with 30 bps to the LPs",
            q["out_units"] == want and q["in"] == "10" and q["method"] == "obuy", q)
    tok0 = st.asset_balance(int(AID), TR["address"])
    s1 = await run(tr, f'console.log(JSON.stringify(await dex.swap({{ pool: {PID}, side: "buy", amount: "10" }})));')
    o = (await J(f"/exec/amm/order?id={s1['orderId']}"))["order"]
    T.check("swap: an obuy order in its block's batch, claimable once the block has passed", o["side"] == "buy" and o["claimable"], o)
    await run(tr, f'console.log(JSON.stringify(await dex.claimSwap({s1["orderId"]})));')
    got = st.asset_balance(int(AID), TR["address"]) - tok0
    T.check("claimSwap: alone in its batch the buyer is paid EXACTLY the quote", got == want * U, (got, want * U))
    T.check("a claimed order reads as claimed", (await J(f"/exec/amm/order?id={s1['orderId']}"))["order"]["claimed"])

    q2 = await J(f"/exec/amm/quote?pool={PID}&side=sell&amount=50")
    nb = st.bridge.get(TR["address"], 0)
    s2 = await run(tr, f'console.log(JSON.stringify(await dex.swap({{ pool: {PID}, side: "sell", amount: "50" }})));')
    await run(tr, f'console.log(JSON.stringify(await dex.claimSwap({s2["orderId"]})));')
    T.check("sell + claim: 50 MOON pays exactly its quote in NADO", st.bridge.get(TR["address"], 0) - nb == q2["out_units"] * U,
            (st.bridge.get(TR["address"], 0) - nb, q2["out_units"] * U))
    n0 = len(C.results)
    s3 = await run(tr, f'console.log(JSON.stringify(await dex.swap({{ pool: {PID}, side: "buy", amount: "1", minOut: 10 ** 9 }})));')
    r = await j(f"/exec/amm/order?id={s3['orderId']}")
    T.check("a limit the batch cannot honour is refused by the contract and no order exists",
            "revert" in " ".join(results_since(n0)) and r.status == 404, results_since(n0))

    # ---- the remote MCP reads the pool exactly as the API does -----------------------------------------------------
    post = lambda body: http.post(base + "/exec/otc/mcp", json=body)

    async def mcp(name, args):
        c = await (await post({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})).json()
        return json.loads(c["result"]["content"][0]["text"])
    mq = await mcp("dex_quote", {"pool": PID, "side": "buy", "amount": "10"})
    aq = await J(f"/exec/amm/quote?pool={PID}&side=buy&amount=10")
    T.check("remote MCP dex_quote = /exec/amm/quote", mq["out_units"] == aq["out_units"], (mq, aq["out_units"]))
    T.check("remote MCP dex_pools, dex_position, dex_balance, dex_swap_order read the same state",
            any(p["id"] == PID for p in (await mcp("dex_pools", {}))["pools"])
            and (await mcp("dex_position", {"id": liq["position"]}))["position"]["shares"] == pos["shares"]
            and (await mcp("dex_balance", {"address": TR["address"]}))["nado_raw"] == (await J(f"/exec/amm/balance?address={TR['address']}"))["nado_raw"]
            and (await mcp("dex_swap_order", {"id": s1["orderId"]}))["order"]["claimed"])

    nb, pool = st.bridge.get(LP["address"], 0), (await J(f"/exec/amm/pool?id={PID}"))["pool"]   # reserves after the trades
    await run(lp, f'console.log(JSON.stringify(await dex.removeLiquidity({liq["position"]})));')
    pool2 = (await J(f"/exec/amm/pool?id={PID}"))["pool"]
    T.check("removeLiquidity: every share out, the pool's NADO back to the provider",
            pool2["shares"] == 0 and pool2["reserve_nado_units"] == 0
            and st.bridge.get(LP["address"], 0) - nb == pool["reserve_nado_units"] * U, (pool2, st.bridge.get(LP["address"], 0) - nb))

    # ---- a LAUNCH -----------------------------------------------------------------------------------------------------
    st.apply_blob({"op": "asset_create", "seed": 2, "name": "Rocket", "sym": "RKT", "dec": 8, "supply": 100000 * 10 ** 8,
                   "mintable": False}, LP["address"], "ac2")
    AID2 = str(asset_id(LP["address"], 2))
    fee0 = st.bridge.get(LP["address"], 0)
    la = await run(lp, f'console.log(JSON.stringify(await dex.launch({{ asset: "{AID2}", supply: "100000", virtualNado: 1000 }})));')
    cv = (await J(f"/exec/amm/pool?id={la['pool']}"))["pool"]
    T.check("launch: the sealed 10 NADO fee, then the whole supply onto a curve in its opening batch",
            cv["kind"] == "curve" and cv["supply_units"] == 100000 * 10 ** 8 // U and cv["opening_batch"]
            and fee0 - st.bridge.get(LP["address"], 0) == D.CREATE_FEE * U and cv["coin"] == "RKT", cv)
    cq = await J(f"/exec/amm/quote?pool={la['pool']}&side=buy&amount=2")
    T.check("a curve quote is the curve formula net of its 1 % fee, placed with buy (not obuy)",
            cq["method"] == "buy" and cq["fee_units"] == (2 * NADO // U) // D.ORDER_FEE, cq)
    t0 = st.asset_balance(int(AID2), TR["address"])
    lb = await run(tr, f'console.log(JSON.stringify(await dex.swap({{ pool: {la["pool"]}, side: "buy", amount: "2" }})));')
    o = (await J(f"/exec/amm/order?id={lb['orderId']}"))["order"]
    T.check("in the opening window the order is NOT claimable (the contract refuses it there)", not o["claimable"], o)
    bad = await run(tr, f'try {{ await dex.claimSwap({lb["orderId"]}); console.log("null"); }} catch (e) {{ console.log(JSON.stringify(String(e.message))); }}')
    T.check("…and claimSwap says to wait instead of sending a doomed claim", isinstance(bad, str) and "not closed" in bad, bad)
    st.cursor += D.WINDOW; C.tip += D.WINDOW                 # the opening window passes
    T.check("after the window it is claimable", (await J(f"/exec/amm/order?id={lb['orderId']}"))["order"]["claimable"])
    await run(tr, f'console.log(JSON.stringify(await dex.claimSwap({lb["orderId"]})));')
    T.check("claimed: alone in the opening batch the buyer gets exactly the curve quote",
            st.asset_balance(int(AID2), TR["address"]) - t0 == cq["out_units"] * U,
            (st.asset_balance(int(AID2), TR["address"]) - t0, cq["out_units"] * U))

    # ---- a LIMIT ORDER ------------------------------------------------------------------------------------------------
    lim = await run(lp, f'console.log(JSON.stringify(await dex.postLimit({{ give: {{ asset: "{AID}", amount: "100" }}, want: {{ asset: "0", amount: "5" }}, blocks: 3000 }})));')
    book = (await J(f"/exec/otc/intra?give={AID}&want=0"))["orders"]
    T.check("postLimit: the give side escrowed, listed at 0.05 NADO per MOON", [x["id"] for x in book] == [lim["id"]]
            and book[0]["price"] == "0.05" and book[0]["give"] == "100" and book[0]["give_coin"] == "MOON", book)
    T.check("remote MCP dex_limit_orders reads the same book",
            [x["id"] for x in (await mcp("dex_limit_orders", {"give": AID, "want": "0"}))["orders"]] == [lim["id"]])
    n_lp, t_tr = st.bridge.get(LP["address"], 0), st.asset_balance(int(AID), TR["address"])
    await run(tr, f'console.log(JSON.stringify(await dex.fillLimit({lim["id"]})));')
    T.check("fillLimit: both sides swap in one call — the taker gets 100 MOON, the maker 5 NADO",
            st.asset_balance(int(AID), TR["address"]) - t_tr == 100 * 10 ** 8 and st.bridge.get(LP["address"], 0) - n_lp == 5 * NADO
            and not (await J(f"/exec/otc/intra?give={AID}&want=0"))["orders"])

    # ---- the exchange balance: withdraw + claim -----------------------------------------------------------------------
    l1 = C.l1[TR["address"]]
    await run(tr, 'console.log(JSON.stringify(await dex.withdraw("1")));')
    cl = await run(tr, 'console.log(JSON.stringify(await dex.claimWithdrawals()));')
    T.check("withdraw + claimWithdrawals: the cash-out lands on L1 by a fee-exempt self-claim with its proof",
            len(cl) == 1 and C.l1[TR["address"]] - l1 == NADO and C.submitted[-1]["recipient"] == "bridge_withdraw"
            and C.submitted[-1]["fee"] == 0, (cl, C.l1[TR["address"]] - l1))

    # ---- the local MCP server as an agent ------------------------------------------------------------------------------
    async with F.Mcp({"DEX_RELAY": base, "DEX_BOT_SEED": TR["seed"], "DEX_SECRETS": os.path.join(HOME, "sec")}) as m:
        await m.rpc("initialize", {})
        names = {t["name"] for t in (await m.rpc("tools/list"))["result"]["tools"]}
        need = {"dex_deposit", "dex_withdraw", "dex_claim_withdrawals", "dex_swap", "dex_claim_swap", "dex_add_liquidity",
                "dex_remove_liquidity", "dex_refund_liquidity", "dex_open_pool", "dex_launch", "dex_post_limit",
                "dex_fill_limit", "dex_pools", "dex_quote", "dex_balance", "dex_limit_orders", "dex_candles", "dex_pool_trades"}
        T.check("local MCP with a key offers every market's tools", need <= names, need - names)
        r, txt = await m.call("dex_deposit", {"nado": "3"})
        T.check("dex_deposit lands", not r.get("isError"), txt)
        r, txt = await m.call("dex_swap", {"pool": la["pool"], "side": "buy", "amount": "1"})
        oid = json.loads(txt)["orderId"]
        r2, txt2 = await m.call("dex_claim_swap", {"id": oid})
        T.check("dex_swap then dex_claim_swap on the curve, as an agent would", not r.get("isError") and not r2.get("isError")
                and (await J(f"/exec/amm/order?id={oid}"))["order"]["claimed"], (txt, txt2))
        r, txt = await m.call("dex_quote", {"pool": PID, "side": "sell", "amount": "5"})
        T.check("dex_quote on the emptied pool is a readable tool error, not a crash", r.get("isError") and "liquidity" in txt, txt)
        r, txt = await m.call("dex_quote", {"pool": la["pool"], "side": "sell", "amount": "5"})
        T.check("dex_quote through the local server", json.loads(txt)["side"] == "sell", txt)
        r, txt = await m.call("dex_post_limit", {"give_asset": "0", "give_amount": "1", "want_asset": AID, "want_amount": "30"})
        T.check("dex_post_limit: NADO for MOON", not r.get("isError") and
                any(x["id"] == json.loads(txt)["id"] for x in (await J(f"/exec/otc/intra?give=0&want={AID}"))["orders"]), txt)

    idx = await J("/exec/dexapi")
    T.check("/exec/dexapi indexes every market with its reads and writes", set(idx["markets"]) == {"cross_chain", "limit_orders", "pools", "launchpad"}
            and "/exec/amm/quote" in json.dumps(idx["markets"]["pools"]["reads"]) and idx["contracts"]["pools_and_launchpad"] == C.dex)
    await http.close()
    await C.srv.close()


asyncio.run(main())

dexjs = open(os.path.join(F.STATIC, "dex.js")).read()
T.check("the API's pool contract is the page's (static/dex.js CID)",
        re.search(r'^const CID = "([0-9a-f]+)"', dexjs, re.M).group(1) == re.search(
            r'DEX_CID = "([0-9a-f]+)"', open(os.path.join(F.REPO, "execnode", "amm_api.py")).read()).group(1))
# ---- the page shows that all of this exists (operator: "on the page itself there should be cues that these things exist")
html = open(os.path.join(F.STATIC, "dex.html")).read()
for card in ("marketsCard", "poolsCard", "lpFeedCard", "otcBookCard", "otcLimitCard"):
    i = html.index(f'id="{card}"')
    body = html[i:html.index("\n  <div class=\"card", i + 1) if "\n  <div class=\"card" in html[i + 1:] else len(html)]
    T.check(f"the {card} card carries the API · MCP cue to the docs page", 'href="/static/dex-api.html"' in body)
T.check("the header and the footer link the docs page too", 'class="hub apihub" href="/static/dex-api.html"' in html
        and 'data-i18n="dex.apiFoot"' in html)
docs = open(os.path.join(F.STATIC, "dex-api.html")).read()
en = open(os.path.join(F.REPO, "execnode", "execnode.py")).read()
paths = set(re.findall(r"(/exec/[a-z_/]+)", docs))
T.check("every endpoint the docs page names is a real route", paths and all(f'"{p}"' in en for p in paths), paths)
T.check("the docs page names the remote MCP URL and the local server", "/exec/otc/mcp" in docs and "nadodex-mcp.mjs" in docs)
ref = open(os.path.join(F.REPO, "doc", "dex-api.md")).read()
rpaths = {p.rstrip("/") for p in re.findall(r"`(/exec/[a-z_/]+)", ref)}
T.check("every endpoint the reference names is a real route", rpaths and all(f'"{p}"' in en for p in rpaths), {p for p in rpaths if f'"{p}"' not in en})
T.done("ALL PASS — the DEX API covers every market end to end")
