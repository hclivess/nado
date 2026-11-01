"""Every page calls the SDK's canPay(dapp, raw, what) with the dapp FIRST (static/nadodapp.js).

lend.js called canPay(stakeRaw, notify) from its first commit (0c205181, 2026-08-02): the amount sat where the dapp
belongs, `dapp.me` of a BigInt is undefined, so the check said "needs a wallet — sign in first" to every signed-in
user and returned false. Offer, borrow and repay — all three money paths of the page — could never run; found
2026-11-01 while building the NFT page on the same helper. Pins: every canPay( call in static/*.js passes `dapp` or
`this.dapp` as its first argument (the declaration in nadodapp.js is the only exception).

Run: python3 tests/test_every_page_passes_the_dapp_to_canpay.py
"""
import os
import re
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-canpay-")      # NEVER the live node's home (rule 4)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
STATIC = os.path.join(ROOT, "static")

import _harness
_report = _harness.Report()
check = _report.check

bad, n = [], 0
for f in sorted(os.listdir(STATIC)):
    if not f.endswith(".js"):
        continue
    for i, line in enumerate(open(os.path.join(STATIC, f), encoding="utf-8", errors="replace"), 1):
        code = line.split("//", 1)[0]
        for m in re.finditer(r"\bcanPay\(\s*([^,)]*)", code):
            if f == "nadodapp.js" and "function canPay" in code:
                continue
            n += 1
            if m.group(1).strip() not in ("dapp", "this.dapp"):
                bad.append(f"{f}:{i}: {line.strip()[:120]}")

check("0. the scan found the pages' canPay calls", n >= 20, n)
check("1. every canPay call passes the dapp first", not bad, bad)
lend = open(os.path.join(STATIC, "lend.js"), encoding="utf-8").read()
check("2. lend's offer, borrow and repay reach the balance check with the dapp",
      lend.count("canPay(dapp, ") == 3 and "canPay(stakeRaw" not in lend)
_report.done()
