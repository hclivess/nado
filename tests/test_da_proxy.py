"""L1 forwards DA reads to its own exec node, so data availability can actually deliver on this fleet.

WHY IT EXISTS. Every piece of DA has been implemented for a long time — DaStore, /da/meta, /da/have,
/da/shard, /da/get, da_announce, da_fetch — and a settle whose proof is too large to inline is supposed to
publish the proof to DA and carry only a commitment. It never worked across this fleet, for one reason:
`_da_sources` asked peers on the EXEC port. Measured 2026-08-08 on the live fleet, every peer's :9273
refused the connection while :9173 answered. So the source list could never serve a shard, da_fetch returned
None, and "publish to DA" silently degraded into riding ~69 MiB of proof inline inside the transaction —
which every node then re-parses on every candidate build (py-spy caught exactly that: codec.unpack ->
json.loads on an asyncio thread while the node's tip sat frozen for ~8 minutes).

The fix asks on the port peers already expose. What these checks pin is that the proxy stays a NARROW,
loopback-only forwarder rather than becoming a general one:

  * the target host is hardcoded to 127.0.0.1 — a proxy that took a host from the request would be SSRF,
    and this endpoint is unauthenticated;
  * the path comes from a fixed allowlist, so it cannot be walked onto another exec route;
  * it STREAMS — a shard is blob/k, tens of MiB, and buffering it into L1 to write it out again would put
    that allocation on the event loop, which is the cost DA exists to remove;
  * a down exec node answers 503, because da_fetch treats a non-200 as "this source has nothing" and moves
    on; a 500 would be indistinguishable from a real fault.

Run: python3 tests/test_da_proxy.py
"""
import ast
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

NADO = open(os.path.join(ROOT, "nado.py")).read()
EXEC = open(os.path.join(ROOT, "execnode", "execnode.py")).read()

fails = 0


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


def _proxy_src():
    i = NADO.index("async def da_proxy")
    return NADO[i:NADO.index("async def make_app")]


def t_the_route_is_registered_on_l1():
    assert 'web.get("/da/{what}", da_proxy)' in NADO, "L1 must serve /da/<what>"


def t_the_target_host_is_hardcoded_loopback():
    """THE security property. This endpoint is unauthenticated; a host taken from the request would make
    every node an open proxy into its own network."""
    src = _proxy_src()
    assert 'f"http://127.0.0.1:{_EXEC_PORT}/da/{what}"' in src, (
        "the proxy target must be hardcoded to loopback")
    for bad in ("request.query.get(\"host\"", "request.query.get('host'", "request.match_info.get(\"host\""):
        assert bad not in src, "the target host must never come from the request"


def t_the_path_comes_from_an_allowlist():
    src = _proxy_src()
    assert "_DA_PROXY_PATHS" in src, "the forwarded path must be allowlisted"
    assert "if what not in _DA_PROXY_PATHS" in src, "a path outside the allowlist must be refused"
    i = NADO.index("_DA_PROXY_PATHS = ")
    allow = ast.literal_eval(NADO[i:NADO.index("\n", i)].split("=", 1)[1].strip())
    assert set(allow) == {"meta", "have", "shard", "get"}, f"unexpected allowlist: {allow}"
    # read-only: announce POSTs a commitment and must NOT be reachable through this GET forwarder
    assert "announce" not in allow, "the proxy is for READS; /da/announce must not be in it"


def t_it_streams_rather_than_buffering():
    src = _proxy_src()
    assert "web.StreamResponse" in src, "a tens-of-MiB shard must not be buffered into L1"
    assert "iter_chunked" in src, "the body must be forwarded in chunks"
    assert "await out.write_eof()" in src, "the stream must be closed"


def t_a_down_exec_node_is_503_not_500():
    src = _proxy_src()
    assert "status=503" in src, (
        "an exec node that is down is a normal state — da_fetch skips a non-200 source and moves on")


def t_da_sources_asks_the_reachable_port():
    """The actual defect: peers were asked on the exec port, which is not exposed between nodes."""
    i = EXEC.index("async def _da_sources")
    src = EXEC[i:EXEC.index("async def da_fetch")]
    assert "_l1_port" in src, "peer URLs must be built from the L1 port"
    assert 'f"http://{host}:{_l1_port}"' in src, "a peer must be asked on the port it actually exposes"
    assert 'f"http://{host}:{PORT}"' not in src, "peers must no longer be asked on the exec port"


def t_our_own_exec_node_is_still_tried_directly():
    """A local hop beats a proxied one, and it is the one DA endpoint we know is up."""
    i = EXEC.index("async def _da_sources")
    src = EXEC[i:EXEC.index("async def da_fetch")]
    assert 'f"http://127.0.0.1:{PORT}"' in src, "our own exec node should still be a direct source"
    assert src.index('127.0.0.1') < src.index("for p in (peers"), "local source must be tried FIRST"


for nm, fn in [("the route is registered on L1", t_the_route_is_registered_on_l1),
               ("target host is hardcoded loopback", t_the_target_host_is_hardcoded_loopback),
               ("path comes from an allowlist", t_the_path_comes_from_an_allowlist),
               ("it streams rather than buffering", t_it_streams_rather_than_buffering),
               ("a down exec node is 503", t_a_down_exec_node_is_503_not_500),
               ("da_sources asks the reachable port", t_da_sources_asks_the_reachable_port),
               ("our own exec node is tried directly first", t_our_own_exec_node_is_still_tried_directly)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
