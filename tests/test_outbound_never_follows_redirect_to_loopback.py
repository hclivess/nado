import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-redirect-guard-")   # BEFORE any node import (CLAUDE.md rule 4)
"""A PEER'S REDIRECT NEVER BECOMES A LOOPBACK-AUTHORIZED REQUEST (bandit B310 triage, 2026-09-30).

urllib and aiohttp follow redirects by default. A followed redirect to http://127.0.0.1:9173/<x> reaches the node from
a loopback socket with a loopback Host header — exactly what nado._is_local_request() accepts as the operator's curl —
so any peer the node polls, any third-party feed a job reads, and any AIA URL inside a certificate POSTed to
/tpm_enrol_id could answer `302 Location: http://127.0.0.1:9173/terminate` (node shuts down) or
`/force_sync?ip=<attacker>` (node pins its sync to the attacker). Reproduced with both clients before the fix.

Pins, with real sockets (a redirector on 127.0.0.2 pointing at a sink on 127.0.0.1):
  * the harness itself can see the attack (an unguarded client DOES reach the sink) — so a green run means something;
  * under ops.outbound_guard.install_redirect_guard() a redirect to loopback never reaches the sink, a deliberate
    first-hop loopback call still works, and a redirect to a non-HTTP scheme is refused;
  * public_only_opener() (the AIA path) refuses a non-public FIRST hop, and nado._fetch_der refuses a redirect to
    loopback even when the first hop is allowed;
  * the connect-time check resolves ONCE and dials exactly the address it checked (no DNS-rebinding window);
  * is_public_address() refuses loopback / RFC1918 / CGNAT / link-local (cloud metadata) / unspecified / mapped;
  * aiohttp with allow_redirects=False stops at the 302 (this venv's aiohttp honours it), and EVERY awaited aiohttp
    request in the node and exec-node code carries allow_redirects=False;
  * nado.py installs the guard at import, and the unit-run / incident scripts install it in main().
Run: python3 tests/test_outbound_never_follows_redirect_to_loopback.py
"""
import ast
import http.server
import socket
import sys
import threading
import types
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ops import outbound_guard as og                                   # noqa: E402  (stdlib-only module)

_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


# ---- a loopback sink and a redirector ----------------------------------------------------------------------------
HITS = []


class _Sink(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        HITS.append(self.path)
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def _serve(host, handler):
    srv = http.server.ThreadingHTTPServer((host, 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


SINK, SINK_PORT = _serve("127.0.0.1", _Sink)
TARGET = {"url": f"http://127.0.0.1:{SINK_PORT}/terminate"}


class _Redirector(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", TARGET["url"])
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = do_GET

    def log_message(self, *a):
        pass


REDIR, REDIR_PORT = _serve("127.0.0.2", _Redirector)
REDIR_URL = f"http://127.0.0.2:{REDIR_PORT}/status"


def _fresh():
    HITS.clear()
    TARGET["url"] = f"http://127.0.0.1:{SINK_PORT}/terminate"


def t1_harness_sees_the_attack():
    _fresh()
    try:
        urllib.request.build_opener().open(REDIR_URL, timeout=5).read()
    except Exception as e:
        check("an unguarded urllib opener follows a peer's 302 to loopback (harness sanity)", False, repr(e))
        return
    check("an unguarded urllib opener follows a peer's 302 to loopback (harness sanity)", HITS == ["/terminate"], HITS)


def t2_installed_guard_refuses_redirect_to_loopback():
    saved = urllib.request._opener
    try:
        og.install_redirect_guard()
        _fresh()
        err = None
        try:
            urllib.request.urlopen(REDIR_URL, timeout=5).read()
        except Exception as e:
            err = e
        check("under the installed guard a peer's 302 to loopback never reaches the loopback endpoint",
              err is not None and HITS == [], f"err={err!r} hits={HITS}")
        _fresh()
        body = urllib.request.urlopen(f"http://127.0.0.1:{SINK_PORT}/ok", timeout=5).read()
        check("a deliberate first-hop loopback call still works under the guard (local exec node, local L1)",
              body == b"ok" and HITS == ["/ok"], HITS)
        for scheme_url in ("ftp://127.0.0.1/x", "file:///etc/hostname"):
            _fresh()
            TARGET["url"] = scheme_url
            err = None
            try:
                urllib.request.urlopen(REDIR_URL, timeout=5).read()
            except urllib.error.HTTPError as e:
                err = e
            except Exception as e:
                err = e
            check(f"a redirect to a non-HTTP scheme is refused ({scheme_url.split(':')[0]})",
                  isinstance(err, urllib.error.HTTPError) and err.code == 302 and HITS == [], repr(err))
        og.install_redirect_guard()                      # idempotent
        check("install_redirect_guard is idempotent", urllib.request._opener is not None)
    finally:
        urllib.request.install_opener(saved)


def t3_public_only_opener_refuses_nonpublic_first_hop():
    _fresh()
    err = None
    try:
        og.public_only_opener().open(f"http://127.0.0.1:{SINK_PORT}/aia.crt", timeout=5).read()
    except Exception as e:
        err = e
    check("public_only_opener refuses a loopback FIRST hop (an AIA URL an outsider chose)",
          err is not None and HITS == [], f"err={err!r} hits={HITS}")


def t4_fetch_der_refuses_redirect_to_loopback():
    """nado._fetch_der, exec'd from source (importing nado would start a node): let 127.0.0.2 count as public so the
    first hop is made, and prove the redirect to 127.0.0.1 is still refused."""
    src = open(os.path.join(ROOT, "nado.py")).read()
    seg = src[src.index("def _fetch_der(url: str):"):src.index("def _complete_ek_chain(chain):")]
    check("_fetch_der has no bare urlopen (every hop goes through public_only_opener)",
          "urlopen(" not in seg and "public_only_opener().open(" in seg)
    ns = {"_AIA_TIMEOUT": 5, "_AIA_MAX_BYTES": 64_000, "_tbs_name": lambda b, i: True}
    exec(seg, ns)
    real = og.is_public_address
    og.is_public_address = lambda ip: str(ip) == "127.0.0.2"
    try:
        _fresh()
        out = ns["_fetch_der"](f"http://127.0.0.2:{REDIR_PORT}/issuer.crt")
        check("an AIA host answering 302 -> loopback gets no request through and yields no certificate",
              out is None and HITS == [], f"out={out!r} hits={HITS}")
    finally:
        og.is_public_address = real


def t5_connect_time_check_dials_what_it_checked():
    calls, dialled = [], []

    class _FakeSock:
        def __init__(self, *a):
            pass

        def settimeout(self, t):
            pass

        def bind(self, a):
            pass

        def connect(self, sa):
            dialled.append(sa)

        def close(self):
            pass

    answers = [[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 80))],
               [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]]

    served = []

    def _gai(host, port, *a):
        calls.append(host)
        served.append(1)
        return answers[min(len(served) - 1, 1)]          # a rebinding name: public first, loopback after

    fake = types.SimpleNamespace(getaddrinfo=_gai, socket=_FakeSock, SOCK_STREAM=socket.SOCK_STREAM,
                                 _GLOBAL_DEFAULT_TIMEOUT=socket._GLOBAL_DEFAULT_TIMEOUT)
    real = og._socket
    og._socket = fake
    try:
        og.public_create_connection(("rebind.example", 80), 3)
        check("the connect-time check resolves ONCE and dials exactly the address it checked (no rebinding window)",
              calls == ["rebind.example"] and dialled == [("1.1.1.1", 80)], f"calls={calls} dialled={dialled}")
        calls.clear(); dialled.clear()
        err = None
        try:
            og.public_create_connection(("rebind.example", 80), 3)   # now answers loopback
        except OSError as e:
            err = e
        check("a name resolving to loopback is refused before any connect", err is not None and dialled == [],
              f"err={err!r} dialled={dialled}")
    finally:
        og._socket = real


def t6_public_address_table():
    refused = ["127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "100.64.0.1", "169.254.169.254", "0.0.0.0",
               "::1", "::ffff:127.0.0.1", "fe80::1", "224.0.0.1", "240.0.0.1", "fd00::1", "not-an-ip"]
    allowed = ["1.1.1.1", "8.8.8.8", "2606:4700:4700::1111"]
    bad = [a for a in refused if og.is_public_address(a)] + [a for a in allowed if not og.is_public_address(a)]
    check("is_public_address refuses loopback/private/CGNAT/metadata/unspecified/mapped/multicast, allows public",
          not bad, bad)


def t7_aiohttp_honours_allow_redirects_false():
    try:
        import asyncio
        import aiohttp
    except ImportError:
        print("SKIP  aiohttp not importable here — run under nado_venv for the live aiohttp check")
        return

    async def _go():
        async with aiohttp.ClientSession() as s:
            _fresh()
            async with s.get(REDIR_URL) as r:
                await r.read()
            followed = list(HITS)
            _fresh()
            async with s.get(REDIR_URL, allow_redirects=False) as r:
                status = r.status
            return followed, status, list(HITS)

    followed, status, hits = asyncio.run(_go())
    check("aiohttp's default follows a peer's 302 to loopback (harness sanity)", followed == ["/terminate"], followed)
    check("aiohttp with allow_redirects=False stops at the 302 and never reaches loopback", status == 302 and hits == [],
          f"status={status} hits={hits}")


NODE_FILES = ["nado.py", "compounder.py", "memserver.py"]
HTTP_METHODS = {"get", "post", "put", "delete", "head", "patch", "request", "options"}


def _node_files():
    out = list(NODE_FILES)
    for d in ("ops", "loops", "execnode"):
        for base, _dirs, files in os.walk(os.path.join(ROOT, d)):
            out += [os.path.relpath(os.path.join(base, f), ROOT) for f in files if f.endswith(".py")]
    return sorted(set(out))


def t8_every_aiohttp_request_refuses_redirects():
    """An awaited / async-with'd .get/.post/... is an aiohttp client request (dict.get is never awaited)."""
    open_sites, n = [], 0
    for rel in _node_files():
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            calls = ([i.context_expr for i in node.items] if isinstance(node, ast.AsyncWith)
                     else [node.value] if isinstance(node, ast.Await) else [])
            for c in calls:
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr in HTTP_METHODS:
                    n += 1
                    kw = {k.arg: k.value for k in c.keywords}
                    v = kw.get("allow_redirects")
                    if not (isinstance(v, ast.Constant) and v.value is False):
                        open_sites.append(f"{rel}:{c.lineno}")
    check(f"every awaited aiohttp request in node/exec-node code passes allow_redirects=False ({n} sites)",
          n >= 30 and not open_sites, open_sites or f"only {n} sites found — did the walk break?")


def _calls_guard(tree_body):
    for node in ast.walk(ast.Module(body=tree_body, type_ignores=[])):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "install_redirect_guard":
            return True
    return False


def t9_processes_install_the_guard():
    tree = ast.parse(open(os.path.join(ROOT, "nado.py"), encoding="utf-8").read())
    top = [s for s in tree.body if isinstance(s, ast.Expr)]
    check("nado.py calls install_redirect_guard() at module level (before any loop starts)", _calls_guard(top))
    ex = ast.parse(open(os.path.join(ROOT, "execnode", "execnode.py"), encoding="utf-8").read())
    mains = [s for s in ex.body if isinstance(s, ast.If) and "__main__" in ast.unparse(s.test)
             and "asyncio.run(main())" in ast.unparse(s)]
    check("execnode.py installs the redirect guard before asyncio.run(main())",
          bool(mains) and _calls_guard(mains[-1].body))
    for rel in ("scripts/bet_oracle.py", "scripts/otc_watchtower.py", "scripts/fleet_tips.py",
                "scripts/diagnose_wedge.py"):
        t = ast.parse(open(os.path.join(ROOT, rel), encoding="utf-8").read())
        mains = [f for f in t.body if isinstance(f, ast.FunctionDef) and f.name == "main"]
        check(f"{rel} installs the redirect guard in main()", bool(mains) and _calls_guard(mains[0].body))
    src = open(os.path.join(ROOT, "ops", "outbound_guard.py"), encoding="utf-8").read()
    imports = [n for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = {(a.name if isinstance(n, ast.Import) else (n.module or "")).split(".")[0]
             for n in imports for a in n.names}
    check("ops/outbound_guard.py imports only the stdlib (read-only incident tools may import it)",
          names <= {"http", "ipaddress", "socket", "urllib"}, names)


if __name__ == "__main__":
    t1_harness_sees_the_attack()
    t2_installed_guard_refuses_redirect_to_loopback()
    t3_public_only_opener_refuses_nonpublic_first_hop()
    t4_fetch_der_refuses_redirect_to_loopback()
    t5_connect_time_check_dials_what_it_checked()
    t6_public_address_table()
    t7_aiohttp_honours_allow_redirects_false()
    t8_every_aiohttp_request_refuses_redirects()
    t9_processes_install_the_guard()
    SINK.shutdown(); REDIR.shutdown()
    print("ALL PASS" if not _fails else f"FAILED: {len(_fails)}: {_fails}")
    sys.exit(1 if _fails else 0)
