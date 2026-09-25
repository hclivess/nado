"""i18n.js keeps its URL across a push that does not touch it (nado.py _stamp_static_refs, _OWN_STAMP_JS).

Every .js reference is stamped with the global JS epoch so a module graph busts together. i18n.js is a 7.4 MB classic
script that imports nothing and nothing imports, and on the epoch it got a new URL at every push: each CDN edge then
re-pulled it cold from the origin in 10-22 s, and right after the betanet-8 pushes 2 of 5 fetches arrived truncated,
leaving the wallet in untranslated defaults. Pins: i18n.js is stamped by its own mtime, every other .js by the epoch,
and i18n.js really is standalone (the exemption would break coherency otherwise).

The functions are lifted from nado.py's source: importing nado.py opens the node's database.
Run: python3 tests/test_i18n_own_stamp.py
"""
import os, re, ast, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "nado.py")).read()
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


tree = ast.parse(SRC)
wanted = {"_STATIC_REF_RE", "_OWN_STAMP_JS", "_stamp_static_refs"}
parts = [ast.get_source_segment(SRC, n) for n in tree.body
         if (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in wanted for t in n.targets))
         or (isinstance(n, ast.FunctionDef) and n.name in wanted)]
check("the stamper and its constants are found in nado.py", len(parts) == 3, len(parts))

static = tempfile.mkdtemp(prefix="nado-stamp-")
for name, mtime in (("i18n.js", 1_700_000_000), ("interface.js", 1_700_000_500)):
    p = os.path.join(static, name)
    open(p, "w").write("//")
    os.utime(p, (mtime, mtime))
EPOCH = 1_790_000_000
ns = {"re": re, "os": os, "_STATIC_DIR": static, "_js_epoch": lambda: EPOCH}
exec("\n".join(parts), ns)

html = b'<script src="/static/i18n.js?v=cc667a3f"></script><script src="/static/interface.js"></script>'
out = ns["_stamp_static_refs"](html)
check("i18n.js is stamped by its own mtime, replacing a literal stamp", b'/static/i18n.js?v=1700000000"' in out, out)
check("every other .js still carries the global epoch", b'/static/interface.js?v=%d"' % EPOCH in out, out)

i18n = open(os.path.join(ROOT, "static", "i18n.js")).read()
check("i18n.js imports nothing", not re.search(r"^\s*import\b|\bimport\s*\(", i18n, re.M))
importers = [f for f in os.listdir(os.path.join(ROOT, "static")) if f.endswith((".js", ".mjs", ".html"))
             and re.search(r"""(from|import)\s*\(?\s*["']\./i18n\.js""", open(os.path.join(ROOT, "static", f),
                                                                           errors="ignore").read())]
check("nothing imports i18n.js as a module", not importers, importers)

print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
