"""OUTBOUND REDIRECT GUARD — every outbound HTTP request a process on a node host makes. STDLIB ONLY, no node
imports and no side effects at import, so the read-only incident tools (scripts/fleet_tips.py,
scripts/diagnose_wedge.py) can use it without touching the chain database."""
# ---------------------------------------------------------------------------------------------------------------
# OUTBOUND REDIRECT GUARD (bandit B310 triage, 2026-09-30). THE BUG IT CLOSES: urllib and aiohttp both FOLLOW
# REDIRECTS by default, and a followed redirect to http://127.0.0.1:9173/... arrives at this node from the loopback
# socket with a loopback Host header — exactly what nado._is_local_request() accepts as the operator's own curl. So
# ANY peer this node polls (anyone can become one through /announce_peer), any third party a job fetches (the sports
# feed, the ETH RPC), and any AIA URL inside a certificate POSTed to /tpm_enrol_id could answer `302 Location:
# http://127.0.0.1:9173/terminate` and the node shut itself down — or `/force_sync?ip=<attacker>` and it pinned its
# sync to the attacker. Reproduced with both clients against a loopback sink before this was written.
#
# The rule, for every outbound HTTP request a node process makes:
#   * urllib: install_redirect_guard() at process start. The FIRST hop is whatever the code built (deliberate
#     loopback calls to the local exec node keep working); every REDIRECTED hop may only connect to a PUBLIC address,
#     checked AT CONNECT TIME against the address actually dialled (so DNS rebinding between a check and the connect
#     cannot slip through), and only to http/https.
#   * a URL an outsider supplied (AIA): public_only_opener() applies the same connect-time rule to EVERY hop.
#   * aiohttp: every client call passes allow_redirects=False (tests/test_outbound_never_follows_redirect_to_loopback.py
#     walks the tree and fails on a call site without it) — honest peers never redirect an API path.
# ---------------------------------------------------------------------------------------------------------------
import http.client as _http_client
import ipaddress as _ipaddress
import socket as _socket
import urllib.error as _urlerror
import urllib.parse as _urlparse
import urllib.request as _urlrequest


def is_public_address(ip) -> bool:
    """True only for a globally-routable unicast address. Loopback, RFC1918, CGNAT (100.64/10), link-local (the cloud
    metadata service at 169.254.169.254), unspecified (0.0.0.0 dials loopback on Linux), reserved and multicast are all
    refused; an IPv4-mapped IPv6 address is judged as the IPv4 address it maps (::ffff:127.0.0.1 is loopback)."""
    try:
        a = _ipaddress.ip_address(str(ip).split("%", 1)[0])
    except ValueError:
        return False
    mapped = getattr(a, "ipv4_mapped", None)
    if mapped is not None:
        a = mapped
    return bool(a.is_global) and not a.is_multicast


def public_create_connection(address, timeout=_socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, *args, **kwargs):
    """socket.create_connection that resolves ONCE, refuses if ANY answer is non-public, and dials exactly the
    addresses it checked. Resolving here — not in a pre-flight check — is the point: a separate check resolves once
    and the connect resolves again, and a TTL-0 name answers public to the first and 127.0.0.1 to the second."""
    host, port = address[0], address[1]
    infos = _socket.getaddrinfo(host, port, 0, _socket.SOCK_STREAM)
    if not infos or any(not is_public_address(sa[0]) for _f, _t, _p, _c, sa in infos):
        raise OSError(f"refused to connect: {host!r} resolves to a non-public address")
    err = None
    for fam, stype, proto, _cn, sa in infos:
        s = None
        try:
            s = _socket.socket(fam, stype, proto)
            if timeout is not _socket._GLOBAL_DEFAULT_TIMEOUT:
                s.settimeout(timeout)
            if source_address:
                s.bind(source_address)
            s.connect(sa)
            return s
        except OSError as e:
            err = e
            if s is not None:
                s.close()
    raise err if err is not None else OSError(f"no address for {host!r}")


class _PublicHTTPConnection(_http_client.HTTPConnection):
    """HTTPConnection whose socket can only reach a public address (checked on the dialled address)."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._create_connection = public_create_connection


class _PublicHTTPSConnection(_http_client.HTTPSConnection):
    """HTTPSConnection whose socket can only reach a public address; TLS/SNI still use the URL's host name."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._create_connection = public_create_connection


class _RedirectGuard(_urlrequest.HTTPRedirectHandler):
    """Follows a redirect only to http/https (never ftp/file) and marks the new request so its connection is
    public-only. A redirect that would land on loopback therefore fails at connect, it never reaches the node."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _urlparse.urlsplit(newurl).scheme.lower() not in ("http", "https"):
            raise _urlerror.HTTPError(newurl, code, "redirect to a non-HTTP scheme refused", headers, fp)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new._nado_redirected = True
        return new


class _GuardedHTTPHandler(_urlrequest.HTTPHandler):
    public_only = False

    def http_open(self, req):
        if self.public_only or getattr(req, "_nado_redirected", False):
            return self.do_open(_PublicHTTPConnection, req)
        return super().http_open(req)


class _GuardedHTTPSHandler(_urlrequest.HTTPSHandler):
    public_only = False

    def https_open(self, req):
        if self.public_only or getattr(req, "_nado_redirected", False):
            return self.do_open(_PublicHTTPSConnection, req, context=self._context)
        return super().https_open(req)


def install_redirect_guard():
    """Make every urllib.request.urlopen() in this process redirect-safe (see the block comment above). Idempotent.
    Call at process start in anything that runs on a node host and fetches a URL it does not fully control."""
    _urlrequest.install_opener(_urlrequest.build_opener(_RedirectGuard, _GuardedHTTPHandler, _GuardedHTTPSHandler))


def public_only_opener():
    """An opener for a URL an OUTSIDER chose (a certificate's AIA field): every hop, the first included, may only
    connect to a public address; environment proxies are ignored so the check applies to the host actually dialled."""
    h, hs = _GuardedHTTPHandler(), _GuardedHTTPSHandler()
    h.public_only = hs.public_only = True
    return _urlrequest.build_opener(_urlrequest.ProxyHandler({}), _RedirectGuard, h, hs)
