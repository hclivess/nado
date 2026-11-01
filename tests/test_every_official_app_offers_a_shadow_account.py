"""Every official app that signs through the wallet offers a Shadow Account (static/interface.js EXEC_SIGN_ALLOW,
2026-11-01).

The wallet's "Use apps privately" card lists EXACTLY EXEC_SIGN_ALLOW, and the restore scan (shadowCandidateOrigins) reads
the same list — so an official app missing from it has no private account at all. The DEX, lending and five games
(autogame, hamster, hexholm, pool, sovereign) were missing: they signed through the wallet as trusted *.nadochain.com
sites, but nobody could use them privately. Pins:
  1. every static page whose canonical URL is an official https://<app>.nadochain.com and that loads nadodapp.js (the
     SDK that signs through the wallet) — directly or through one of its own scripts — is in EXEC_SIGN_ALLOW;
  2. every origin in EXEC_SIGN_ALLOW is such a page (no stale entry);
  3. the card and the restore scan still read EXEC_SIGN_ALLOW, so the list is what the user is offered.

Run: python3 tests/test_every_official_app_offers_a_shadow_account.py
"""
import json
import os
import re
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-shadow-apps-")      # NEVER the live node's home (rule 4)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
STATIC = os.path.join(ROOT, "static")

import _harness
_report = _harness.Report()
check = _report.check

js = open(os.path.join(STATIC, "interface.js"), encoding="utf-8").read()
m = re.search(r"^const EXEC_SIGN_ALLOW = (\[[^\]]*\]);", js, re.M)
allow = set(json.loads(m.group(1))) if m else set()


def loads_sdk(html_path):
    html = open(html_path, encoding="utf-8").read()
    if "nadodapp" in html:
        return True
    for src in re.findall(r'<script[^>]+src="([^"?#]+)', html):
        p = os.path.join(STATIC, os.path.basename(src))
        if os.path.isfile(p) and "nadodapp" in open(p, encoding="utf-8", errors="replace").read():
            return True
    return False


apps = set()
for f in sorted(os.listdir(STATIC)):
    if not f.endswith(".html"):
        continue
    p = os.path.join(STATIC, f)
    c = re.search(r'rel="canonical" href="(https://[a-z0-9-]+\.nadochain\.com)/"', open(p, encoding="utf-8").read())
    # get.nadochain.com is the WALLET itself (interface.html): it is where a shadow account lives, not an app that
    # signs through one
    if c and c.group(1) != "https://get.nadochain.com" and loads_sdk(p):
        apps.add(c.group(1))

check("0. the list and the official app pages were found", len(allow) >= 17 and len(apps) >= 17, (len(allow), len(apps)))
check("1. every official app that signs through the wallet offers a private account", apps <= allow, sorted(apps - allow))
check("1. the DEX and lending are among them",
      {"https://dex.nadochain.com", "https://lend.nadochain.com"} <= (apps & allow))
check("2. no stale entry: every listed origin is an official app page", allow <= apps, sorted(allow - apps))
check("3. the card offers EXEC_SIGN_ALLOW and the restore scan reads it",
      re.search(r'for \(const o of EXEC_SIGN_ALLOW\) \{ const op = document\.createElement\("option"\)', js) is not None
      and "function shadowCandidateOrigins() { return [...new Set([...shadowOrigins(), ...EXEC_SIGN_ALLOW])]; }" in js)
_report.done()
