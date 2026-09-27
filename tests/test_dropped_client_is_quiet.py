"""A client that hangs up mid-request is answered quietly, not with a traceback (nado.py _body_cap_mw).

MEASURED 2026-09-27 16:39:50: during the update wave to 59b949f1, peer 89.143.197.28 restarted while its gossip POST to
/submit_transaction was being read; request.read() raised ConnectionResetError and aiohttp logged a full traceback for
each, which the fleet health watch counts as an anomaly on every push. Nothing is lost (the peer re-gossips).

Pins, on a real aiohttp app wired with the node's own middleware code: a handler whose body read raises
ConnectionResetError yields a 499 response and no exception; any other exception still propagates (a real bug must stay
loud).

Run: python3 tests/test_dropped_client_is_quiet.py
"""
import os, sys, tempfile, asyncio, re, textwrap
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-dropped-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


src = open(os.path.join(ROOT, "nado.py")).read()
i, j = src.find("async def _body_cap_mw(request, handler):"), src.find("app = web.Application(client_max_size=_MAX_INLINE_TX")
check("the node's body-cap middleware is found", 0 < i < j)
if 0 < i < j:
    body = textwrap.dedent(src[src.rfind("\n", 0, i) + 1:src.rfind("\n", 0, j) + 1])
    from aiohttp import web
    from aiohttp.test_utils import make_mocked_request
    ns = {"web": web, "_MAX_INLINE_TX": 192 << 20, "_DEFAULT_MAX_BODY": 2 << 20, "_LARGE_BODY_PATHS": {"/submit_transaction"},
          "_resp": lambda text, status=200: web.Response(text=str(text), status=status)}
    exec(body, ns)
    mw = ns["_body_cap_mw"]

    async def dropped(request):
        raise ConnectionResetError("Connection lost")

    async def broken(request):
        raise KeyError("a real bug")

    req = make_mocked_request("POST", "/submit_transaction", headers={"Content-Length": "10"})
    try:
        r = asyncio.run(mw(req, dropped))
        check("a client that hangs up mid-body gets a quiet 499, not a traceback", r.status == 499, r.status)
    except Exception as e:
        check("a client that hangs up mid-body gets a quiet 499, not a traceback", False, repr(e))
    try:
        asyncio.run(mw(make_mocked_request("POST", "/submit_transaction", headers={"Content-Length": "10"}), broken))
        check("any other exception still propagates", False)
    except KeyError:
        check("any other exception still propagates", True)

print("ALL PASS — a dropped client is quiet" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
