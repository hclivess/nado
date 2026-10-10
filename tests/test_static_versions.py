"""ONE CACHE-BUSTING SCHEME: every static reference carries ?v=<the referenced file's content version>, and only the
server writes it (ops/static_versions.py, served by nado.py's static_handler / _html_response).

Four schemes used to overlap — a JS-wide mtime epoch, md5 literals written into sources by merge_games.py, hand labels
(?v=mlkem, ?v=ratchet2, ?v=1) and interface.js's HW_STAMP. Measured consequences: vendor/nado-crypto.js loaded under
two URLs and ran twice; noble-secp256k1.js?v=1 was served immutable for a year. Pins:
  * NO ?v= in any static source (js/mjs/html/css), no HW_STAMP, no bust_* helpers left in merge_games.py;
  * across the WHOLE import graph of every page — static imports, dynamic import(), <script src>, <link href> — each
    file is referenced under exactly ONE URL, its current version, and no relative import is left unversioned;
  * a version moves when the file's bytes OR any dependency's bytes move, and an unrelated edit moves nothing (i18n.js
    keeps its URL across a push that does not touch it — the 7.7 MB file a CDN edge must not re-pull for nothing);
  * a literal ?v= in source is swallowed, never kept (2026-09-06: one on every page defeated the stamp for four days);
  * an import cycle still yields one consistent URL per member;
  * THE CACHE RULE: immutable only when ?v= equals the current version; stale, hand-written or absent -> no-cache;
    and static_handler applies it.
Pure: imports only ops/static_versions.py (no node state); nado.py is read as text, never imported.
Run: python3 tests/test_static_versions.py
"""
import ast
import os
import re
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# ops/static_versions.py is pure, but the rule is one shape for every test that imports from ops/ (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-static-test-")
sys.path.insert(0, ROOT)
from ops.static_versions import StaticVersions, cache_control  # noqa: E402

STATIC = os.path.join(ROOT, "static")
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {str(detail)[:600]}"))
    fails += 0 if ok else 1


# ---- 1. the sources carry no version of their own ---------------------------------------------------------------
lit = []
for d, _dirs, names in os.walk(STATIC):
    for n in names:
        if n.endswith((".js", ".mjs", ".html", ".css")):
            p = os.path.join(d, n)
            for i, line in enumerate(open(p, encoding="utf-8", errors="replace"), 1):
                if "?v=" in line:
                    lit.append(f"{os.path.relpath(p, ROOT)}:{i}")
check("no static source carries a literal ?v= (the server writes every version)", not lit, lit[:10])
ui = open(os.path.join(STATIC, "interface.js"), encoding="utf-8").read()
check("interface.js has no HW_STAMP of its own", "HW_STAMP" not in ui)
mg = open(os.path.join(STATIC, "i18n_games", "merge_games.py"), encoding="utf-8").read()
check("merge_games.py no longer writes stamps (bust_pages / bust_module_imports are gone)",
      "def bust_pages" not in mg and "def bust_module_imports" not in mg)

# ---- 2. one URL per module across the whole graph ---------------------------------------------------------------
sv = StaticVersions(STATIC)
URL = re.compile(rb'(?:(?:src|href)="|["\'])((?:/static/|\.\.?/)[A-Za-z0-9_./-]+?\.(?:m?js|css|svg|png|html))(\?v=[0-9a-f]+)?["\']')
IMPORT = re.compile(rb'(?:\bfrom\s*|\bimport\s*\(\s*|\bimport\s*)["\'](\.\.?/[A-Za-z0-9_./-]+?\.m?js)(\?v=[^"\']*)?["\']')
seen = {}            # abs path -> set of versions it was referenced under
bare = []
pages = sorted(f for f in os.listdir(STATIC) if f.endswith(".html"))
todo = [os.path.join(STATIC, p) for p in pages]
visited = set()
while todo:
    full = todo.pop()
    if full in visited:
        continue
    visited.add(full)
    got = sv.get(full)
    if got is None or got[0] is None:
        continue
    body = got[0]
    base = os.path.dirname(full)
    for m in IMPORT.finditer(body):
        if not m.group(2) and os.path.normpath(os.path.join(base, m.group(1).decode())) != full:   # a usage comment
            bare.append(f"{os.path.relpath(full, STATIC)} -> {m.group(1).decode()}")
    for m in URL.finditer(body):
        spec = m.group(1).decode()
        tgt = os.path.normpath(os.path.join(STATIC, spec[8:]) if spec.startswith("/static/") else os.path.join(base, spec))
        if not os.path.isfile(tgt) or tgt == full:
            continue
        seen.setdefault(tgt, set()).add((m.group(2) or b"").decode())
        if tgt.endswith((".js", ".mjs", ".html")):
            todo.append(tgt)
multi = {os.path.relpath(k, STATIC): sorted(v) for k, v in seen.items() if len(v) != 1}
check(f"every file in the graph of {len(pages)} pages is loaded under exactly ONE URL ({len(seen)} files)", not multi, multi)
wrong = {os.path.relpath(k, STATIC): (sorted(v), sv.version(k)) for k, v in seen.items()
         if len(v) == 1 and next(iter(v)) != "?v=" + sv.version(k)}
check("...and that URL names the file's CURRENT version", not wrong, wrong)
crypto = os.path.join(STATIC, "vendor", "nado-crypto.js")
check("vendor/nado-crypto.js (once ?v=mlkem in two importers and bare in others) has one URL",
      len(seen.get(crypto, ())) == 1, seen.get(crypto))
check("no relative import in a served module is left unversioned", not bare, bare[:10])
# every module on disk, reachable from a page or not, serves with versioned relative imports
unv = []
for d, _dirs, names in os.walk(STATIC):
    for n in names:
        if n.endswith((".js", ".mjs")):
            got = sv.get(os.path.join(d, n))
            for m in IMPORT.finditer(got[0]):
                t = os.path.normpath(os.path.join(d, m.group(1).decode()))
                if not m.group(2) and os.path.isfile(t) and t != os.path.join(d, n):
                    unv.append(f"{os.path.relpath(os.path.join(d, n), STATIC)} -> {m.group(1).decode()}")
check("every module under static/ serves its existing relative imports versioned", not unv, unv[:10])

# ---- 3. propagation, isolation, swallowing, cycles (a throwaway static/) ----------------------------------------
T = tempfile.mkdtemp(prefix="nado-static-")


def w(rel, text):
    p = os.path.join(T, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(text)
    st = os.stat(p)
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))   # a distinct mtime even within one tick
    return p


page = w("page.html", '<script src="/static/i18n.js?v=cc667a3f"></script><script type="module" src="/static/app.js"></script>'
                      '<link rel="stylesheet" href="/static/site.css?v=1">')
w("i18n.js", "window.t = 1;")
w("site.css", "body{}")
app = w("app.js", 'import { b } from "./lib/b.js?v=deadbeef";\nconst x = () => import("./lib/c.js");\n'
                  'const css = "/static/site.css"; fetch("/static/data/prices.json");\n// usage: import "./app.js"\n')
b = w("lib/b.js", 'export const b = 1; import "../shared.js";')
w("lib/c.js", 'import { b } from "./b.js"; export const c = b;')
w("shared.js", "export const s = 1;")
w("data/prices.json", "{}")
x = w("cyc/x.js", 'import "./y.js"; export const x = 1;')
y = w("cyc/y.js", 'import "./x.js"; export const y = 1;')

s1 = StaticVersions(T, ttl=0)
pb, pv = s1.get(page)
ab, av = s1.get(app)
check("a hand-written ?v= on a page is replaced by the content version, never kept",
      b"cc667a3f" not in pb and b"?v=1\"" not in pb and ('/static/i18n.js?v=%s"' % s1.version(os.path.join(T, "i18n.js"))).encode() in pb)
check("a literal ?v= on a static import is replaced too", b"deadbeef" not in ab and ('./lib/b.js?v=%s"' % s1.version(b)).encode() in ab)
check("a dynamic import() is versioned", ('import("./lib/c.js?v=%s")' % s1.version(os.path.join(T, "lib/c.js"))).encode() in ab)
check("an absolute asset literal in JS is versioned; a data file is not",
      ('"/static/site.css?v=%s"' % s1.version(os.path.join(T, "site.css"))).encode() in ab and b'"/static/data/prices.json"' in ab)
check("a module's mention of itself is left as written (no self-dependency)", b'import "./app.js"\n' in ab)
c_body = s1.get(os.path.join(T, "lib/c.js"))[0]
check("c.js and app.js reference b.js under the same URL",
      ('./b.js?v=%s"' % s1.version(b)).encode() in c_body and ('./lib/b.js?v=%s"' % s1.version(b)).encode() in ab)

# RACY TIMESTAMP: a same-length rewrite that keeps the file's mtime (one timestamp tick, forced here with os.utime) must
# still move the version. The memo used to key on (mtime, size) alone and kept serving the old bytes.
_r = w("racy.js", "export const r = 1;")
_st = os.stat(_r)
_rv = s1.version(_r)
w("racy.js", "export const r = 2;")
os.utime(_r, ns=(_st.st_atime_ns, _st.st_mtime_ns))
check("a same-size rewrite inside one timestamp tick still moves the version", s1.version(_r) != _rv)

b_v = s1.version(b)
i18n_v, shared_v = s1.version(os.path.join(T, "i18n.js")), s1.version(os.path.join(T, "shared.js"))
w("shared.js", "export const s = 2;")                        # a leaf two hops below app.js
check("editing a leaf moves its own version", s1.version(os.path.join(T, "shared.js")) != shared_v)
check("...and every module that imports it, transitively: b.js -> app.js -> page.html all move",
      s1.version(b) != b_v and s1.version(app) != av and s1.version(page) != pv)
check("...and a file that does not depend on it keeps its URL (i18n.js is not re-pulled by a CDN for nothing)",
      s1.version(os.path.join(T, "i18n.js")) == i18n_v)
w("i18n.js", "window.t = 2;")
check("i18n.js's URL moves exactly when its bytes do", s1.version(os.path.join(T, "i18n.js")) != i18n_v)

xv, yv = s1.version(x), s1.version(y)
xb, yb = s1.get(x)[0], s1.get(y)[0]
check("an import cycle gives each member one distinct, consistent URL",
      xv != yv and ('./y.js?v=%s"' % yv).encode() in xb and ('./x.js?v=%s"' % xv).encode() in yb)
w("cyc/y.js", 'import "./x.js"; export const y = 2;')
check("...and editing one member moves both", s1.version(x) != xv and s1.version(y) != yv)

s2 = StaticVersions(T, ttl=60)
v0 = s2.version(app)
check("within the TTL a version is served from memory (no re-walk per request)", s2.version(app) == v0)
t0 = time.perf_counter()
for _ in range(200):
    s2.get(page)
check("a warm lookup is cheap", (time.perf_counter() - t0) / 200 < 0.002, (time.perf_counter() - t0) / 200)
check("a path outside static/ is refused", s2.get(os.path.join(ROOT, "nado.py")) is None)

# ---- 4. THE CACHE RULE ----------------------------------------------------------------------------------------
cur = sv.version(os.path.join(STATIC, "interface.js"))
check("?v= equal to the current version -> immutable for a year", cache_control(cur, cur) == "public, max-age=31536000, immutable")
check("a stale version -> no-cache (a CDN never pins old bytes under it)", cache_control("0" * 16, cur) == "no-cache")
check("a hand-written label (?v=1 / ?v=mlkem) -> no-cache", cache_control("1", cur) == "no-cache" and cache_control("mlkem", cur) == "no-cache")
check("no ?v= at all -> no-cache", cache_control("", cur) == "no-cache")

src = open(os.path.join(ROOT, "nado.py"), encoding="utf-8").read()
tree = ast.parse(src)
sh = next(ast.get_source_segment(src, n) for n in tree.body
          if isinstance(n, ast.AsyncFunctionDef) and n.name == "static_handler")
check("static_handler decides Cache-Control by that rule against the file's current version",
      '_static_cache_control(request.query.get("v", ""), ver)' in sh and "_static_versions.get" in sh)
check("...and answers If-None-Match on the version ETag with a 304", "_etag_matches(request, etag)" in sh and "status=304" in sh)
check("the old schemes are gone from nado.py", not re.search(r"_js_epoch|_OWN_STAMP_JS|_stamp_js_imports|isdigit\(\)\s*\n?\s*headers", src))

print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
