"""Every module a static page can load names a file that exists — no page's module graph can 404.

WHY. G9 slice 6 (2026-10-28) deleted the browser's Goldilocks code (static/stark/{bhash,field,fri,hashing,merkle,stark,
transcript,tree}.js, static/alghash2.js, static/vendor/goldilocks-wasm.js). `node --check` passes a module whose import
names a deleted file — the failure only shows when a browser walks the graph, as a module that never runs and a page
that silently does nothing. test_static_versions checks that every reference is VERSIONED, not that it RESOLVES. This
pins the property for every page, every module, and every test that imports a static module:
  1. every ES import (`from "..."`, `import "..."`, `import("...")`), `new Worker("...")`, `new URL("...",
     import.meta.url)` and `/static/...` asset literal in static/**/*.js|mjs resolves to an existing file;
  2. every `src=` / `href=` under /static/ (or relative) in static/**/*.html, and every import inside an inline
     <script type="module">, resolves to an existing file;
  3. every relative import of a static module from tests/*.mjs|js resolves;
  4. the deleted Goldilocks files stay deleted and nothing names them (their paths are never reused).
Pure: reads files only, imports no node module.
Run: python3 tests/test_every_static_import_resolves_to_a_file.py
"""
import os
import re
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-static-imports-")   # CLAUDE.md rule 4 (nothing here needs it)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "static")
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {str(detail)[:1500]}"))
    fails += 0 if ok else 1


SPEC = r"""["']((?:\.\.?/|/static/)[A-Za-z0-9_./@-]+?)(?:[?#][^"']*)?["']"""
JS_PATTERNS = [
    re.compile(r"\bfrom\s*" + SPEC),
    re.compile(r"\bimport\s*\(\s*" + SPEC),
    re.compile(r"(?:^|[;\s])import\s*" + SPEC, re.M),
    re.compile(r"\bnew\s+Worker\s*\(\s*(?:new\s+URL\s*\(\s*)?" + SPEC),
    re.compile(r"\bnew\s+URL\s*\(\s*" + SPEC + r"\s*,\s*import\.meta\.url"),
    re.compile(r"\bimportScripts\s*\(\s*" + SPEC),
    re.compile(r"""["'](/static/[A-Za-z0-9_./-]+?\.(?:m?js|css|wasm|svg|png|jpe?g|webp|gif|ico|woff2?))(?:[?#][^"']*)?["']"""),
]
HTML_ATTR = re.compile(r"""\b(?:src|href)\s*=\s*["']((?:/static/|\.\.?/)[A-Za-z0-9_./-]+?)(?:[?#][^"']*)?["']""")
INLINE_MODULE = re.compile(r"""<script\b[^>]*type\s*=\s*["']module["'][^>]*>(.*?)</script>""", re.S | re.I)
COMMENT = re.compile(r"/\*.*?\*/|(?<![:\"'\\])//[^\n]*", re.S)


def resolve(base_dir, spec):
    if spec.startswith("/static/"):
        return os.path.normpath(os.path.join(STATIC, spec[len("/static/"):]))
    return os.path.normpath(os.path.join(base_dir, spec))


def js_specs(text):
    text = COMMENT.sub(" ", text)                    # a usage example in a comment is not an import
    out = set()
    for pat in JS_PATTERNS:
        out.update(m.group(1) for m in pat.finditer(text))
    return out


broken, scanned = [], 0
for d, dirs, names in os.walk(STATIC):
    dirs[:] = [x for x in dirs if x not in ("i18n", "i18n_games")]   # JSON translation sources, not modules
    for n in names:
        p = os.path.join(d, n)
        if n.endswith((".js", ".mjs")):
            specs = js_specs(open(p, encoding="utf-8", errors="replace").read())
        elif n.endswith(".html"):
            body = open(p, encoding="utf-8", errors="replace").read()
            specs = {m.group(1) for m in HTML_ATTR.finditer(body)}
            for m in INLINE_MODULE.finditer(body):
                specs |= js_specs(m.group(1))
        else:
            continue
        scanned += 1
        for s in sorted(specs):
            if not os.path.isfile(resolve(d, s)):
                broken.append(f"{os.path.relpath(p, ROOT)} -> {s}")
check(f"1-2. every import / src / href in static/ resolves to a file ({scanned} files scanned)",
      not broken and scanned > 50, broken)

tbroken = []
TESTS = os.path.join(ROOT, "tests")
for n in sorted(os.listdir(TESTS)):
    if n.endswith((".mjs", ".js")):
        p = os.path.join(TESTS, n)
        for s in js_specs(open(p, encoding="utf-8", errors="replace").read()):
            r = resolve(TESTS, s)
            if r.startswith(STATIC + os.sep) and not os.path.isfile(r):
                tbroken.append(f"tests/{n} -> {s}")
check("3. every static module a test imports exists", not tbroken, tbroken)

GONE = ["stark/bhash.js", "stark/field.js", "stark/fri.js", "stark/hashing.js", "stark/merkle.js", "stark/stark.js",
        "stark/transcript.js", "stark/tree.js", "alghash2.js", "vendor/goldilocks-wasm.js"]
back = [g for g in GONE if os.path.exists(os.path.join(STATIC, g))]
check("4a. the deleted Goldilocks browser files stay deleted", not back, back)
KEEP = ["stark/stwo_js.js", "stark/stwo_worker.js", "vendor/stwo_js.wasm", "alghash.js"]   # Stwo wallet + the Gauntlet
gone_keep = [k for k in KEEP if not os.path.isfile(os.path.join(STATIC, k))]
check("4b. the Stwo wallet prover and static/alghash.js (the Daily Gauntlet pins it) are still served", not gone_keep,
      gone_keep)

print("ALL PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
