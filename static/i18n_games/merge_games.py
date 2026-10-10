#!/usr/bin/env python3
"""
The OLD entry point, kept so redeploy.py, docs and muscle memory keep working: it now runs tools/build_i18n.py, which
generates the WHOLE static/i18n.js from static/i18n/*.json + static/i18n_games/*.json + static/i18n/runtime.js.tmpl.

Before 2026-10-10 this script only spliced a T_GAMES block into a hand-layered i18n.js; the rest of the file was
edited by hand and 129 keys ended up defined more than once. After editing any <game>.json (or a namespace file),
run this — or tools/build_i18n.py directly — and commit the regenerated i18n.js with the JSON.

Run: python3 static/i18n_games/merge_games.py
"""
import glob, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
I18N = os.path.join(HERE, "..", "i18n.js")
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
import build_i18n  # noqa: E402


def main():
    rc = build_i18n.main([])
    if rc:
        sys.exit(rc)


def bust_pages():
    """Stamp every static/*.html with content hashes — Cloudflare serves /static js with max-age=14400, so
    without this a fresh bundle never reaches visitors (the 'translations missing' bug).

    Two stamps, for the same reason:
      * i18n.js — the merged translation bundle;
      * each page's OWN game module, static/<game>.js. That one used to go unstamped, which means a shipped
        JS BUGFIX was invisible for four hours to exactly the people who had already hit the bug. The page
        itself is served no-cache, so stamping the module reference inside it takes effect on the next
        reload.
    """
    import hashlib, re as _re

    def h8(path):
        return hashlib.md5(open(path, "rb").read(), usedforsecurity=False).hexdigest()[:8]

    h = h8(I18N)
    stamped = 0
    for page in glob.glob(os.path.join(HERE, "..", "*.html")):
        src = open(page, encoding="utf-8").read()
        out = _re.sub(r'src="/static/i18n\.js[^"]*"', 'src="/static/i18n.js?v=%s"' % h, src)
        # the page's own module, matched by filename so a page never stamps someone else's script
        name = os.path.splitext(os.path.basename(page))[0]
        mod = os.path.join(HERE, "..", name + ".js")
        if os.path.exists(mod):
            out = _re.sub(r'src="/static/%s\.js[^"]*"' % _re.escape(name),
                          'src="/static/%s.js?v=%s"' % (name, h8(mod)), out)
        if out != src:
            open(page, "w", encoding="utf-8").write(out)
            stamped += 1
    print("stamped i18n.js?v=%s + each page's own module into %d pages" % (h, stamped))

def bust_module_imports():
    """Content-hash-stamp every LOCAL module import inside static/*.js — `from "./x.js?v=…"` — so no
    human ever hand-bumps a ?v again. Hand-bumping was the standing failure mode: an edited module
    behind an unbumped (or absent) stamp ships stale for four CDN hours to exactly the people who
    already hit the bug it fixes (the unversioned nadodapp.js import hid an SDK fix that way).

    Stamps must propagate leaf-first: a module's hash depends on its own import stamps, so iterate to
    a fixpoint (a DAG converges in depth+1 passes; a cycle would not, hence the capped loop + warning).
    """
    import hashlib, re as _re

    mods = {p: open(p, encoding="utf-8").read()
            for p in glob.glob(os.path.join(HERE, "..", "*.js"))}
    imp = _re.compile(r'(from\s+["\'])\./([A-Za-z0-9_.-]+?\.js)(?:\?v=[^"\']*)?(["\'])')
    for _round in range(12):
        hashes = {os.path.basename(p): hashlib.md5(s.encode(), usedforsecurity=False).hexdigest()[:8] for p, s in mods.items()}
        changed = False
        for p, s in mods.items():
            me = os.path.basename(p)
            # a module never stamps its own name — the only place that appears is documentation (the
            # usage-example comment), and stamping it makes the file's hash depend on itself: no fixpoint
            out = imp.sub(lambda m: (m.group(1) + "./" + m.group(2)
                                     + ("?v=" + hashes[m.group(2)] if m.group(2) in hashes and m.group(2) != me else "")
                                     + m.group(3)), s)
            if out != s:
                mods[p] = out
                changed = True
        if not changed:
            break
    else:
        print("WARNING: import stamps did not converge (circular import?) — left at last pass")
    n = 0
    for p, s in mods.items():
        if open(p, encoding="utf-8").read() != s:
            open(p, "w", encoding="utf-8").write(s)
            n += 1
    print("stamped local module imports in %d module files" % n)

if __name__ == "__main__":
    main()
    bust_module_imports()   # module-internal stamps FIRST — page stamps hash the finished modules
    bust_pages()
