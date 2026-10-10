"""A /static/ reference is stamped whether or not the HTML already carries a hand-written ?v= query (2026-09-06: a
literal ?v=<hash> on every page defeated the old mtime stamp for four days). The pattern lives in
ops/static_versions.py since 2026-10-10 (one content-hash scheme); both its canonical regex and the fast scanner the
server actually uses must swallow the literal."""
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# ops/static_versions.py is pure, but the rule is one shape for every test that imports from ops/ (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-static-test-")
sys.path.insert(0, ROOT)
from ops.static_versions import HTML_REF_RE, StaticVersions  # noqa: E402


def main():
    html = (b'<script type="module" src="/static/interface.js?v=24748b62"></script>'
            b'<link rel="stylesheet" href="/static/interface.css?v=58cf72f0" />'
            b'<script src="/static/i18n.js"></script><img src="/static/logo.png">')
    out = HTML_REF_RE.sub(lambda mm: mm.group(1) + mm.group(2) + b"?v=777" + mm.group(3), html)
    assert out.count(b"?v=777") == 4, out
    assert b"24748b62" not in out and b"58cf72f0" not in out, out
    assert b'src="/static/interface.js?v=777"' in out and b'href="/static/interface.css?v=777"' in out

    d = tempfile.mkdtemp(prefix="nado-stamp-")
    for n in ("interface.js", "interface.css", "i18n.js", "logo.png"):
        open(os.path.join(d, n), "w").write(n)
    open(os.path.join(d, "p.html"), "wb").write(html)
    sv = StaticVersions(d, ttl=0)
    body = sv.get(os.path.join(d, "p.html"))[0]
    stamps = re.findall(rb'(?:src|href)="/static/([a-z0-9_.]+)\?v=([0-9a-f]+)"', body)
    assert len(stamps) == 4, body
    assert all(v.decode() == sv.version(os.path.join(d, n.decode())) for n, v in stamps), stamps
    assert b"24748b62" not in body and b"58cf72f0" not in body, body
    print("ALL OK")


if __name__ == "__main__":
    main()
