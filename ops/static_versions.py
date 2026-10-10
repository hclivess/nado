"""ONE cache-busting scheme for static/: every reference carries ?v=<the referenced file's content hash>.

The server computes, per static file, a version = a hash of the bytes it SERVES, and the served bytes of an HTML page
or a JS module have every reference rewritten to the referenced file's version — so a module's version covers its own
imports, recursively, and editing a leaf module changes the URL of everything that (transitively) imports it, and
nothing else. Rewritten:
  * HTML: src="/static/<file>" and href="/static/<file>";
  * JS:   relative ES-module specifiers — `from "./x.js"`, `import "./x.js"`, `import("./x.js")` (static AND dynamic)
          — and absolute "/static/<asset>" string literals for code/style/image assets (theme.css built by
          nadodapp.js). Data files (market/prices.json, the helper's .sha256) are left alone: their version would move
          every minute and drag the importer's URL with it.
A literal ?v= already in the source is SWALLOWED and replaced: tests/test_static_versions.py refuses one in source,
and this is the second line of defence (2026-09-06: a hand-written ?v= on every page defeated the old mtime stamp for
four days).

WHY ONE SCHEME (2026-10-10). Four overlapped: the server stamped HTML with a JS-wide mtime epoch (and i18n.js by its own
mtime); merge_games.py wrote md5 literals into 148 module imports and into the HTML; hand labels (?v=mlkem,
?v=ratchet2, ?v=1) sat on a few imports; and interface.js imported hwattest.js with its own page stamp. Measured: the
wallet loaded vendor/nado-crypto.js under TWO URLs — so the module ran twice, two module instances — and
vendor/noble-secp256k1.js?v=1 was served immutable for a year, so a fix to it could never reach a browser. Here every
module has exactly one URL per content, and a URL is only immutable while it names the current bytes.

Caching rule (static_handler): ?v= equal to the file's CURRENT version -> immutable for a year; anything else (absent,
stale, hand-written) -> no-cache with an ETag of the version, so a stale URL never pins old bytes in a CDN.

Pure: os/re/hashlib only, no node state — tests import it directly. Thread-safe (called from asyncio.to_thread).
"""
import hashlib
import os
import re
import stat as _stat
import threading
import time

# HTML attribute references. The optional (?:\?v=...) group SWALLOWS a hand-written stamp — keep it (see above).
# (The canonical form; the scanner below finds the same matches anchored on the literal ="/static/ — the alternation
# at the front of this pattern costs ~0.5 s over the 7.7 MB i18n.js, and a cold page walks the whole graph.)
HTML_REF_RE = re.compile(rb'((?:src|href)=")(/static/[A-Za-z0-9_./-]+)(?:\?v=[A-Za-z0-9_.-]*)?(")')
_HTML_FAST = re.compile(rb'="(/static/[A-Za-z0-9_./-]+)(?:\?v=[A-Za-z0-9_.-]*)?"')
# ES-module specifiers inside a served .js: from "./x.js" · import "./x.js" · import("./x.js") (and ../). Found by the
# quoted relative path first (fast), then kept only when `from` / `import` / `import(` precedes it.
JS_IMPORT_RE = re.compile(rb'(["\'])(\.\.?/[A-Za-z0-9_./-]+?\.m?js)(?:\?v=[A-Za-z0-9_.-]*)?(["\'])')
_IMPORT_CTX = re.compile(rb'(?:\bfrom|\bimport)\s*\(?\s*$')
# Absolute asset literals in JS ("/static/theme.css"). Only code/style/image types — never data.
JS_ASSET_RE = re.compile(rb'(["\'])(/static/[A-Za-z0-9_./-]+?\.(?:m?js|css|svg|png|jpe?g|webp|gif|ico|woff2?|wasm))'
                         rb'(?:\?v=[A-Za-z0-9_.-]*)?(["\'])')


def scan_refs(raw, kind):
    """[(start, end, head, spec, tail)] — every reference in an HTML page or JS module that gets a version."""
    out = []
    if kind == "html":
        if b'="/static/' in raw:
            for m in _HTML_FAST.finditer(raw):
                s = m.start()
                if raw[max(0, s - 4):s] == b"href" or raw[max(0, s - 3):s] == b"src":
                    out.append((s, m.end(), b'="', m.group(1), b'"'))
    else:
        if b"./" in raw:
            for m in JS_IMPORT_RE.finditer(raw):
                if m.group(1) == m.group(3) and _IMPORT_CTX.search(raw, max(0, m.start() - 40), m.start()):
                    out.append((m.start(), m.end(), m.group(1), m.group(2), m.group(3)))
        if b"/static/" in raw:
            for m in JS_ASSET_RE.finditer(raw):
                if m.group(1) == m.group(3):
                    out.append((m.start(), m.end(), m.group(1), m.group(2), m.group(3)))
    out.sort()
    return out


TTL = 2.0            # seconds a computed version is trusted before the files are re-statted (a deploy lands within it)
VERSION_LEN = 16     # hex chars


def _h(*parts):
    d = hashlib.blake2b(digest_size=VERSION_LEN // 2)
    for p in parts:
        d.update(p)
    return d.hexdigest()


# RACY TIMESTAMPS (git's rule): a file modified within this window of the moment we read it may be rewritten again with
# the same size inside one filesystem timestamp tick, leaving (mtime, size) unchanged. Such a node is re-read and its
# bytes compared before the memo is trusted. Found 2026-10-10: test_static_versions failed under load when a same-length
# edit landed in the tick of the previous read, and production would have kept serving the old version of that file.
RACY_NS = 2_000_000_000


class _Node:
    __slots__ = ("key", "kind", "raw", "refs", "leaf_ver", "memo", "seen")

    def __init__(self, key, kind, raw, refs, leaf_ver):
        self.key, self.kind, self.raw, self.refs, self.leaf_ver = key, kind, raw, refs, leaf_ver
        self.memo = None
        self.seen = time.time_ns()     # when these bytes were read (the racy-timestamp check compares mtime with it)     # (tuple of dep versions, body, version) — the rewrite is redone only when a dep moves


class StaticVersions:
    """Content versions + rewritten bodies for the files under `root` (the static/ directory)."""

    def __init__(self, root, ttl=TTL):
        self.root = os.path.abspath(root)
        self.ttl = ttl
        self._lock = threading.RLock()
        self._nodes = {}     # abs path -> _Node (memoised on mtime_ns + size)
        self._fresh = {}     # abs path -> (checked_at, version, body or None)

    # ---- file graph -----------------------------------------------------------------------------------------
    def _inside(self, full):
        return full == self.root or full.startswith(self.root + os.sep)

    def _target(self, base_dir, spec):
        """Absolute path for a reference, or None when it leaves static/ or names no regular file."""
        spec = spec.decode("utf-8", "replace")
        full = os.path.normpath(os.path.join(self.root, spec[len("/static/"):]) if spec.startswith("/static/")
                                else os.path.join(base_dir, spec))
        return full if self._inside(full) and os.path.isfile(full) else None

    def _node(self, full):
        try:
            st = os.stat(full)
        except OSError:
            return None
        if not _stat.S_ISREG(st.st_mode):
            return None
        key = (st.st_mtime_ns, st.st_size)
        n = self._nodes.get(full)
        # INVARIANT: the memo is trusted only when the file's mtime is clearly older than the read that filled it, because
        # a same-size rewrite inside one timestamp tick leaves (mtime, size) unchanged (RACY_NS above).
        if n is not None and n.key == key and st.st_mtime_ns + RACY_NS < n.seen:
            return n
        with open(full, "rb") as f:
            raw = f.read()
        if n is not None and n.key == key and (n.raw == raw if n.raw is not None else n.leaf_ver == _h(raw)):
            n.seen = time.time_ns()       # unchanged bytes: keep the node (and its memo), re-stamp the read
            return n
        if full.endswith(".html"):
            kind = "html"
        elif full.endswith((".js", ".mjs")):
            kind = "js"
        else:
            n = _Node(key, "leaf", None, (), _h(raw))       # the bytes are not kept: FileResponse streams them
            self._nodes[full] = n
            return n
        base = os.path.dirname(full)
        clean, end = [], -1
        for (s, e, head, spec, tail) in scan_refs(raw, kind):
            t = self._target(base, spec)
            if t is None or t == full or s < end:            # a self-reference (a usage comment) is left as written
                continue
            clean.append((s, e, head, spec, tail, t))
            end = e
        n = _Node(key, kind, raw, tuple(clean), None)
        self._nodes[full] = n
        return n

    @staticmethod
    def _rewrite(n, vers):
        if not n.refs:
            return n.raw
        out, pos = [], 0
        for (s, e, head, spec, tail, t) in n.refs:
            out.append(n.raw[pos:s])
            v = vers.get(t)          # absent only if the target vanished mid-pass: leave it unstamped, never crash
            out.append(head + spec + (b"?v=" + v.encode() if v else b"") + tail)
            pos = e
        out.append(n.raw[pos:])
        return b"".join(out)

    # ---- versions -------------------------------------------------------------------------------------------
    def _compute(self, start, now):
        """Version every file reachable from `start` that is not already fresh. Tarjan's SCCs come out dependencies
        first, so each file's dependencies are versioned before it. A cycle (no static/ module has one today) gets a
        shared seed over its members' bytes and outside deps, and each member a distinct version derived from it —
        every member still has ONE URL, and any member's edit moves them all."""
        index, low, onstack, stack, sccs, nodes = {}, {}, set(), [], [], {}
        known = {}           # path -> version, for fresh nodes treated as leaves of this pass

        def deps(v):
            n = nodes[v]
            return [r[5] for r in n.refs] if n is not None else []

        def strong(v):
            index[v] = low[v] = len(index)
            stack.append(v)
            onstack.add(v)
            nodes[v] = self._node(v)
            for w in deps(v):
                if w in known:
                    continue
                f = self._fresh.get(w)
                if f is not None and now - f[0] < self.ttl:
                    known[w] = f[1]
                    continue
                if w not in index:
                    strong(w)
                    low[v] = min(low[v], low[w])
                elif w in onstack:
                    low[v] = min(low[v], index[w])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    onstack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                sccs.append(comp)

        strong(start)
        vers = dict(known)
        for comp in sccs:
            if len(comp) == 1 and comp[0] not in deps(comp[0]):
                v = comp[0]
                n = nodes[v]
                if n is None:
                    continue
                if n.kind == "leaf":
                    vers[v] = n.leaf_ver
                    self._fresh[v] = (now, n.leaf_ver, None)
                    continue
                dv = tuple(vers.get(r[5], "") for r in n.refs)
                if n.memo is None or n.memo[0] != dv:
                    body = self._rewrite(n, vers)
                    n.memo = (dv, body, _h(body))
                vers[v] = n.memo[2]
                self._fresh[v] = (now, n.memo[2], n.memo[1])
            else:
                members = sorted(comp)
                outside = sorted({r[5] for m in members if nodes[m] for r in nodes[m].refs} - set(members))
                seed = _h(b"scc", *[m.encode() + b"\0" + (nodes[m].raw or b"") for m in members if nodes[m]],
                          *[vers.get(o, "").encode() for o in outside])
                for m in members:
                    vers[m] = _h(seed.encode(), m.encode())
                for m in members:
                    n = nodes[m]
                    if n is None:
                        continue
                    body = self._rewrite(n, vers) if n.kind != "leaf" else None
                    self._fresh[m] = (now, vers[m], body)

    def get(self, full):
        """(body bytes or None, version) for a file under root; body is None for a leaf (serve the file as is).
        None when the file does not exist."""
        full = os.path.abspath(full)
        if not self._inside(full):
            return None
        with self._lock:
            now = time.monotonic()
            f = self._fresh.get(full)
            if f is None or now - f[0] >= self.ttl:
                if self._node(full) is None:
                    self._fresh.pop(full, None)
                    return None
                self._compute(full, now)
                f = self._fresh.get(full)
            if f is None:
                return None
            return f[2], f[1]

    def version(self, full):
        got = self.get(full)
        return got[1] if got else None


def cache_control(requested_v, current_version):
    """THE immutability rule: only a URL naming the CURRENT bytes may be cached forever. A stale or hand-written ?v=
    (or none) is no-cache — stored, but revalidated against the ETag — so it can never pin old bytes at a CDN edge."""
    if requested_v and current_version and requested_v == current_version:
        return "public, max-age=31536000, immutable"
    return "no-cache"
