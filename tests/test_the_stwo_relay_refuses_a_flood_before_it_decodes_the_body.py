"""POST /stwo/relay refuses a rate-limited caller BEFORE it decodes the body, and never decodes on the event loop.

REVIEW 2026-10-12 (pre-push, stwo-on), reproduced here. The relay route accepts bodies up to STWO_RELAY_MAX_BODY (16 MiB)
from anyone, ON BY DEFAULT ON EVERY NODE. ops/stwo_relay.make_handlers reads the whole body and runs json.loads on it IN
THE COROUTINE — on the node's single aiohttp event loop — and only then hands it to StwoRelay.relay, whose FIRST check
is the per-IP rate limit. So the rate limit protects nothing on the expensive part: every request, rate-limited or not,
costs a full 16 MiB JSON decode on the loop that also serves peer gossip, /submit_transaction and the wallet API.

MEASURED on the review host (python3 json.loads of a 16 MiB body of `[[],[],...]`, the shape that maximises objects
per byte): 18.2 s of CPU and ~430 MB RSS for ONE body. On an idle box that is still ~1-2 s of a frozen event loop per
request, from any unauthenticated client, repeatable as fast as it can upload 16 MiB.

/submit_transaction (the other large-body route) already has the pattern this route lacks: the strict per-IP bucket for
a large body is taken BEFORE the body is read, and a node-wide cap bounds large bodies in flight.

Pins (real aiohttp handlers on a local test server, a relay whose rate limit refuses this caller):
  1. a rate-limited caller gets 429 and its body is never decoded;
  2. a body that IS decoded is decoded off the event loop (asyncio.to_thread, like relay.relay itself).
Run: python3 tests/test_the_stwo_relay_refuses_a_flood_before_it_decodes_the_body.py
"""
import os, sys, tempfile, shutil, asyncio, json as _json
_T = tempfile.mkdtemp(prefix="nado-test-stwo-relay-flood-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
import atexit; atexit.register(shutil.rmtree, _T, ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient
import ops.stwo_relay as R

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {str(detail)[:600]}"))
    fails += 0 if ok else 1


DECODES = []


class _CountingJson:
    """ops.stwo_relay's `json`, counting decodes and noting whether each ran ON the event loop thread."""
    def __getattr__(self, name):
        return getattr(_json, name)

    @staticmethod
    def loads(s, *a, **k):
        try:
            asyncio.get_running_loop()
            on_loop = True
        except RuntimeError:
            on_loop = False
        DECODES.append({"bytes": len(s), "on_loop": on_loop})
        return _json.loads(s, *a, **k)


R.json = _CountingJson()


def make(allow):
    return R.StwoRelay(keydict_fn=lambda: {"address": "n" * 10}, tip_fn=lambda: 1, exec_get=lambda p: None,
                       da_publish=lambda b: None, submit=lambda tx: {}, allow=allow)


async def post(relay, body):
    info_h, post_h = R.make_handlers(relay, lambda r: r.remote)
    app = web.Application(client_max_size=R.STWO_RELAY_MAX_BODY)
    app.add_routes([web.post("/stwo/relay", post_h)])
    async with TestClient(TestServer(app)) as c:
        r = await c.post("/stwo/relay", data=body, headers={"Content-Type": "application/json"})
        return r.status, await r.json()


# a 4 MiB body of the cheapest-to-send, most-expensive-to-decode shape
big = b'{"bundle": [' + b"[]," * (4 * 1024 * 1024 // 3) + b"[]]}"

DECODES.clear()
status, out = asyncio.run(post(make(lambda *_: False), big))
check("1. a rate-limited caller is answered 429", status == 429, (status, out))
check("...and its body is never decoded (the rate limit is taken before the expensive part)", not DECODES,
      f"decoded {len(DECODES)} body/bodies of {[d['bytes'] for d in DECODES]} bytes for a caller the relay then refused")

DECODES.clear()
status, out = asyncio.run(post(make(lambda *_: True), b'{"bundle": {}}'))
check("2. a body that is decoded is decoded OFF the event loop", DECODES and not any(d["on_loop"] for d in DECODES),
      f"decodes: {DECODES} (on_loop=True: json.loads ran on the aiohttp event loop)")

print("ALL PASS — the Stwo relay refuses a flood before it decodes the body" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
