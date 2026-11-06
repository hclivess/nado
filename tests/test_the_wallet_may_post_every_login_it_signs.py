"""
The wallet may POST every login it signs: each site the wallet signs a login challenge for (static/interface.js
FORUM_ORIGIN_ALLOW, LAND_ORIGIN_ALLOW) is also allowed by the wallet page's own Content-Security-Policy form-action
(static/interface.html). The signed login goes back as a top-level form POST; an origin missing from form-action is
blocked by the browser AFTER the user approved — Land sign-in reached the wallet, was approved, and silently went
nowhere until 2026-11-06 ("signing in doesnt really work").

Run: python3 tests/test_the_wallet_may_post_every_login_it_signs.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-wallet-form-action-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _harness
_report = _harness.Report()
check = _report.check

js = open(os.path.join(ROOT, "static", "interface.js")).read()
html = open(os.path.join(ROOT, "static", "interface.html")).read()
signs = set()
for name in re.findall(r"^const ([A-Z]+_ORIGIN_ALLOW) = ", js, re.M):
    signs |= set(re.findall(r'"(https://[^"]+)"', re.search(rf"^const {name} = \[(.*?)\];", js, re.M).group(1)))
csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html).group(1)
fa = re.search(r"form-action ([^;]+)", csp).group(1).split()
check("the wallet signs logins for the forum and for Land", {"https://forum.nadochain.com", "https://land.nadochain.com"} <= signs, signs)
check("its form-action allows every one of them", signs <= set(fa), (sorted(signs - set(fa)), fa))
_report.done()
