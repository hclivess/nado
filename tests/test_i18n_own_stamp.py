"""i18n.js keeps its URL across a push that does not touch it.

i18n.js is a 7.7 MB classic script. Under the old JS-wide mtime epoch it got a new URL at every push: each CDN edge
re-pulled it cold from the origin in 10-22 s, and right after the betanet-8 pushes 2 of 5 fetches arrived truncated,
leaving the wallet in untranslated defaults. That was patched with an own-mtime exemption (_OWN_STAMP_JS); since
2026-10-10 every file is versioned by CONTENT (ops/static_versions.py), so the property holds for i18n.js — and for
everything else — by construction. Pins: i18n.js's version is a pure function of its bytes (it imports nothing), a
push that changes other modules leaves it alone, and touching its mtime without changing its bytes leaves it alone.
Run: python3 tests/test_i18n_own_stamp.py
"""
import os, re, shutil, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# ops/static_versions.py is pure, but the rule is one shape for every test that imports from ops/ (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-static-test-")
sys.path.insert(0, ROOT)
from ops.static_versions import StaticVersions  # noqa: E402

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


d = tempfile.mkdtemp(prefix="nado-i18nstamp-")
shutil.copy(os.path.join(ROOT, "static", "i18n.js"), os.path.join(d, "i18n.js"))
open(os.path.join(d, "interface.js"), "w").write('import "./nadodapp.js";')
open(os.path.join(d, "nadodapp.js"), "w").write("export const a = 1;")
open(os.path.join(d, "p.html"), "w").write('<script src="/static/i18n.js"></script><script src="/static/interface.js"></script>')
sv = StaticVersions(d, ttl=0)
p = os.path.join(d, "p.html")
v_i18n = re.search(rb'i18n\.js\?v=([0-9a-f]+)', sv.get(p)[0]).group(1)
v_ui = re.search(rb'interface\.js\?v=([0-9a-f]+)', sv.get(p)[0]).group(1)
open(os.path.join(d, "nadodapp.js"), "w").write("export const a = 2;")
os.utime(os.path.join(d, "nadodapp.js"), ns=(1, 2_000_000_000_000_000_000))
body = sv.get(p)[0]
check("a push that changes another module moves THAT module's importers", re.search(rb'interface\.js\?v=([0-9a-f]+)', body).group(1) != v_ui)
check("...and leaves i18n.js's URL alone", re.search(rb'i18n\.js\?v=([0-9a-f]+)', body).group(1) == v_i18n)
os.utime(os.path.join(d, "i18n.js"), ns=(1, 2_100_000_000_000_000_000))
check("touching i18n.js's mtime without changing its bytes keeps its URL",
      re.search(rb'i18n\.js\?v=([0-9a-f]+)', sv.get(p)[0]).group(1) == v_i18n)

i18n = open(os.path.join(ROOT, "static", "i18n.js")).read()
check("i18n.js imports nothing", not re.search(r"^\s*import\b|\bimport\s*\(", i18n, re.M))
importers = [f for f in os.listdir(os.path.join(ROOT, "static")) if f.endswith((".js", ".mjs", ".html"))
             and re.search(r"""(from|import)\s*\(?\s*["']\./i18n\.js""", open(os.path.join(ROOT, "static", f),
                                                                           errors="ignore").read())]
check("nothing imports i18n.js as a module", not importers, importers)

print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
