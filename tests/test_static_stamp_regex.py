"""nado._STATIC_REF_RE must stamp a /static/ reference whether or not the HTML already carries a hand-written
?v= query (2026-09-06: a literal ?v=<hash> on every page defeated the mtime stamp for four days)."""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "nado.py")).read()
m = re.search(r"^_STATIC_REF_RE = re\.compile\((rb'.*')\)$", src, re.M)
assert m, "regex definition moved"
RE = re.compile(eval(m.group(1)))


def main():
    html = (b'<script type="module" src="/static/interface.js?v=24748b62"></script>'
            b'<link rel="stylesheet" href="/static/interface.css?v=58cf72f0" />'
            b'<script src="/static/i18n.js"></script><img src="/static/logo.png">')
    out = RE.sub(lambda mm: mm.group(1) + mm.group(2) + b"?v=777" + mm.group(3), html)
    assert out.count(b"?v=777") == 4, out
    assert b"24748b62" not in out and b"58cf72f0" not in out, out
    assert b'src="/static/interface.js?v=777"' in out and b'href="/static/interface.css?v=777"' in out
    print("ALL OK")


if __name__ == "__main__":
    main()
