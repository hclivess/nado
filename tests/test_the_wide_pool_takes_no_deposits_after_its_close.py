"""The wide shielded pool takes no deposits (review 2026-10-11, gate blocker 2; ops/transaction_ops.field_shield_check).

Only a `stwo_js` bundle spends, so a wide note deposited could never move again. WIDE_DEPOSIT_CLOSE_HEIGHT (175000 on gen
28) and STWO_POOL_HEIGHT (269000 there) were both 1 from gen 29 and G9 inlined them; generation 28's window pins (a wide
deposit below the close, the order of the two gates, the close exported to clients) retired with them. Pins:

  1. L1 refuses a well-formed wide deposit at every height from block 1;
  2. a Stwo deposit is judged by the Stwo rules (an untagged deposit is that branch's refusal);
  3. height 0 (mempool admission on a genesis tip) keeps its old verdict: no shape check;
  4. the wallet builds no wide deposit at all, and stops every deposit unless the Stwo pool is live.

Run: python3 tests/test_the_wide_pool_takes_no_deposits_after_its_close.py
"""
import os, sys, tempfile, json, re, shutil, subprocess
_T = tempfile.mkdtemp(prefix="nado-test-wide-close-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
import atexit; atexit.register(shutil.rmtree, _T, ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import protocol as P
from ops.transaction_ops import field_shield_check

import _harness
_report = _harness.Report()
check = _report.check


def verdict(data, h):
    try:
        field_shield_check(data, h)
        return "admitted"
    except Exception as e:                                             # noqa: BLE001
        return str(e)


WIDE = {"field": True, "owner": "00" * 31 + "01", "rho": "12345"}
STWO = {"field": True, "pool": "stwo", "owner": "ab" * 32, "rho": "7"}
check("1. a wide deposit is refused from block 1", all(verdict(WIDE, h) != "admitted" for h in (1, 2, 175000, 10 ** 9)),
      [verdict(WIDE, h) for h in (1, 2, 175000, 10 ** 9)])
check("2. a Stwo deposit is judged by the Stwo rules", all(verdict(STWO, h) == "admitted" for h in (1, 10 ** 9)),
      verdict(STWO, 1))
check("...and an untagged deposit is the Stwo branch's refusal", "must name pool" in verdict(WIDE, 1), verdict(WIDE, 1))
check("3. height 0 keeps its old verdict (no shape check)", verdict(WIDE, 0) == "admitted", verdict(WIDE, 0))
check("...and the retired gates are not exported to clients",
      not {"WIDE_DEPOSIT_CLOSE_HEIGHT", "STWO_POOL_HEIGHT"} & set(P.CLIENT_EXPORTS))

SRC = open(os.path.join(ROOT, "static", "interface.js"), encoding="utf-8").read()
# THE WALLET BUILDS NO WIDE DEPOSIT AT ALL (G6): the wide pool is closed and was measured empty, so the wallet dropped it.
# Every deposit is built in shieldDeposit (doShield, and a shadow account returning its coins), which stops before the
# note is built unless the Stwo pool is live, and tags what it builds as a Stwo deposit.
body = SRC[SRC.index("async function shieldDeposit("):]
body = body[:body.index("\nasync function ", 10)]
i_gate, i_build = body.find("if (!shieldStwo()) { shieldPaused(); return false; }"), body.find("noteCommit(")
check("4. every wallet deposit stops before it is built unless the Stwo pool is live", 0 < i_gate < i_build, (i_gate, i_build))
check("...and is tagged a Stwo deposit", 'data.pool = "stwo";' in body)
check("...and the wallet has no wide-deposit path left", "alghash2" not in SRC.split("\n// THE WALLET IMPORTS NO RETIRED-POOL CODE")[0]
      and "wideDepositClosed" not in SRC and "shieldWide" not in SRC)

print("ALL PASS" if not _report.fails else f"{_report.fails} FAILED")
sys.exit(1 if _report.fails else 0)
