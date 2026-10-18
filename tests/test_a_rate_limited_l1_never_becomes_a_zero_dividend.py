"""A rate-limited or failing L1 answer never becomes a dividend input: the exec node holds its cursor instead of
accruing an epoch with inflow 0 (execnode/execnode.py _get_l1_accrual_inputs, _accrue_owed; audit 2026-09-24 #25).

_get_json decoded any body whatever the status, so a 429 on /get_dividend_inflow became inflow 0 and that exec node
accrued the epoch with nothing — its exec root left every other node's. Pinned against a real local HTTP server
playing L1: 429, an error body, a body without the field, and malformed values all raise L1Unavailable; _accrue_owed
then returns False and does not advance last_div_epoch; a real answer accrues exactly what it says.

Run: python3 tests/test_a_rate_limited_l1_never_becomes_a_zero_dividend.py
"""
import _harness
HOME = _harness.isolate("nado-test-accrual-l1-")
import asyncio, os, tempfile
from aiohttp import web, ClientSession
from aiohttp.test_utils import TestServer
import execnode.execnode as EN
from execnode.state import ExecState

T = _harness.Report()
MODE = {"inflow": "ok", "weights": "ok"}
A = "a" * 50


async def inflow(request):
    m, e = MODE["inflow"], int(request.query["epoch"])
    if m == "429": return web.json_response({"error": "rate limited"}, status=429)
    if m == "errbody": return web.json_response({"error": "busy"})
    if m == "nofield": return web.json_response({"epoch": e})
    if m == "float": return web.json_response({"epoch": e, "inflow": 1.5})
    return web.json_response({"epoch": e, "inflow": 1000})


async def weights(request):
    if MODE["weights"] == "429": return web.json_response({"error": "rate limited"}, status=429)
    return web.json_response({"epoch": int(request.query["epoch"]), "weights": {A: 1}})


async def main():
    app = web.Application()
    app.add_routes([web.get("/get_dividend_inflow", inflow), web.get("/get_open_weights", weights)])
    srv = TestServer(app); await srv.start_server()
    EN.L1 = str(srv.make_url("")).rstrip("/")
    async with ClientSession() as s:
        for m in ("429", "errbody", "nofield", "float"):
            MODE["inflow"] = m
            try:
                await EN._get_l1_accrual_inputs(s, 5); T.check(f"inflow answer '{m}' is refused", False, "accepted")
            except EN.L1Unavailable:
                T.check(f"inflow answer '{m}' is refused, never read as 0", True)
        MODE["inflow"], MODE["weights"] = "ok", "429"
        try:
            await EN._get_l1_accrual_inputs(s, 5); T.check("a rate-limited weights answer is refused", False)
        except EN.L1Unavailable:
            T.check("a rate-limited weights answer is refused", True)
        st = ExecState(os.path.join(tempfile.mkdtemp(dir=HOME), "s.json"))
        st.last_div_epoch = 4
        MODE["inflow"], MODE["weights"] = "429", "ok"
        ok = await EN._accrue_owed(s, st, 5)
        T.check("_accrue_owed holds the cursor on a 429: returns False, epoch 5 not accrued", ok is False and st.last_div_epoch == 4,
                (ok, st.last_div_epoch))
        MODE["inflow"] = "ok"
        ok = await EN._accrue_owed(s, st, 5)
        T.check("...and accrues exactly what L1 says once it answers", ok is True and st.last_div_epoch == 5, (ok, st.last_div_epoch))
    await srv.close()

asyncio.run(main())
T.done("ALL PASS — a rate-limited L1 never becomes a zero dividend")
