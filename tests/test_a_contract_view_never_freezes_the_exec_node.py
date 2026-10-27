"""A contract view (GET /exec/view) runs off the exec node's event loop and at most _VIEW_SLOTS at a time, so no client
can freeze the exec node — or its block tail — by repeating views (execnode/execnode.py h_view; audit 2026-09-24 #25).

A view is a full contract call (up to GAS_LIMIT steps of the pure-Python VM) and it ran on the event loop. Pinned with
the real handler over a real ExecState and a contract whose view burns ~60k steps: the answer is unchanged; while views
run, another request on the same loop is answered at once; views beyond the slot count get 429, not a queue.

Run: python3 tests/test_a_contract_view_never_freezes_the_exec_node.py
"""
import _harness
HOME = _harness.isolate("nado-test-exec-view-")
import os
os.environ["NADO_ALLOW_PYTHON_KERNELS"] = "1"
import asyncio, json, tempfile, time
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient
import execnode.execnode as EN
from execnode.state import ExecState
from execnode import zkvmasm

T = _harness.Report()
A = "mldsa44" + "a" * 42
st = ExecState(os.path.join(tempfile.mkdtemp(dir=HOME), "s.json")); st.cursor = 10
code = {"burn": zkvmasm.assemble("movi r1 60000\n movi r2 1\n loop:\n sub r1 r2\n jnz r1 @loop\n movi r0 42\n ret r0")}
st.apply_blob({"op": "deploy", "code": code, "nonce": 1}, A, "d")
CID = next(iter(st.contracts))
EN.states = {"default": st}


async def ping(request):
    return web.json_response({"ok": True})


async def main():
    app = web.Application()
    app.add_routes([web.get("/exec/view", EN.h_view), web.get("/ping", ping)])
    async with TestClient(TestServer(app)) as c:
        r = await c.get(f"/exec/view?cid={CID}&method=burn")
        T.check("a view still answers exactly what the contract returns", (await r.json()).get("result") == "42")
        # EVERY VIEW HOLDS ITS SLOT FOR 0.5 s from here. The burn view was slow enough on the gen-28 VM to overlap; on the gen-29
        # one (zkvm2) it takes 0.022 s (measured), so the overlap this test needs was an accident of the VM's speed and broke
        # (2026-10-27): a slot freed before the fifth request arrived. Holding each view deterministically keeps the
        # property under test — the slot counter, not the VM's speed — the same on every generation.
        _real_view = st.view
        st.view = lambda *a, **k: (time.sleep(0.5), _real_view(*a, **k))[1]
        t0 = time.monotonic()
        views = [asyncio.create_task(c.get(f"/exec/view?cid={CID}&method=burn")) for _ in range(EN._VIEW_SLOTS + 3)]
        await asyncio.sleep(0.05)
        p0 = time.monotonic(); pr = await c.get("/ping"); lag = time.monotonic() - p0
        res = await asyncio.gather(*views)
        statuses = sorted(x.status for x in res)
        T.check("while views run, another request on the same loop is answered at once", pr.status == 200 and lag < 1.0, f"{lag:.2f}s")
        T.check(f"views beyond the {EN._VIEW_SLOTS} slots get 429 instead of queueing",
                statuses.count(429) >= 1 and statuses.count(200) <= EN._VIEW_SLOTS, statuses)
asyncio.run(main())
T.done("ALL PASS — a contract view never freezes the exec node")
