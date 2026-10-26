"""The wallet never tells a user to set a node setting that nothing reads (static/interface.js renderSettlement).

The Settlement tab told every bonded user whose exec node did not answer to "Set NADO_EXEC_SETTLE=1 on your exec node".
That flag was deleted (execnode.SETTLE is unconditional): the advice was a no-op, sending the user to fix something that
was not broken (doc review 2026-10-26). The installer still writes the dead line into nado-exec.service, so "is the name
mentioned anywhere" is not the test — something must READ it.

Pins: every NADO_* name in the served wallet (static/*.js, static/*.html, static/i18n/*.json) is read through
os.environ / os.getenv by a program outside tests/ and static/; and the tab's bonded-not-settling note carries none.

Run: python3 tests/test_the_wallet_names_no_setting_nothing_reads.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-wallet-settings-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import glob, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


served = [p for pat in ("static/*.js", "static/*.html", "static/i18n/*.json") for p in glob.glob(os.path.join(ROOT, pat))
          if not p.endswith("i18n.js")]          # i18n.js is generated from static/i18n/*.json, read there
named = set()
for p in served:
    named |= set(re.findall(r"\bNADO_[A-Z0-9_]{3,}\b", open(p, encoding="utf-8").read()))

readers = ""
for dp, dn, fn in os.walk(ROOT):
    dn[:] = [d for d in dn if d not in (".git", "tests", "static", "node_modules", "target", "nado_venv")]
    for f in fn:
        if f.endswith(".py"):
            try:
                readers += open(os.path.join(dp, f), encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                pass


def is_read(v):
    return re.search(r"(environ\.get\(|environ\[|getenv\()\s*[\"']" + re.escape(v) + r"[\"']", readers) is not None


unread = sorted(v for v in named if not is_read(v))
check("every NADO_* setting the wallet names is read by the node or the exec node", not unread, unread)
check("...the check sees the settings the wallet does name (NADO_EXEC_PORT is read by nado.py)",
      "NADO_EXEC_PORT" in named and is_read("NADO_EXEC_PORT"), sorted(named))
check("...and would catch the deleted flag (NADO_EXEC_SETTLE is read by nothing)", not is_read("NADO_EXEC_SETTLE"))

src = open(os.path.join(ROOT, "static", "interface.js"), encoding="utf-8").read()
m = re.search(r'i18\("rollup\.noteBonded", "([^"]*)"', src)
check("the bonded-not-settling note is translated and names no setting", m is not None and "NADO_" not in m.group(1),
      m and m.group(1))

print("\nALL PASS — the wallet names no setting nothing reads" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
