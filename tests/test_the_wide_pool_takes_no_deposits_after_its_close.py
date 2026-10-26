"""The wide shielded pool takes no deposits from WIDE_DEPOSIT_CLOSE_HEIGHT (review 2026-10-11, gate blocker 2).

From STWO_POOL_HEIGHT only a `stwo_js` bundle spends, so a wide note deposited before that gate could never move again.
The wide pool never held a note, so closing its deposits well ahead of the Stwo gate keeps it provably empty:

  1. L1 admits a well-formed wide deposit one block below the close and refuses it at the close (both rule sets);
  2. a Stwo deposit at the Stwo gate is still judged by the Stwo rules (the close sits after that branch);
  3. the live gates keep their order: the Stwo gate is never (0) or above the close;
  4. the wallet reads the close from /protocol.js and stops a wide deposit at tip + 1 >= close with a translated
     reason, but never once the Stwo pool is live.

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
# 1-3 ARE GENERATION 28'S WINDOWS (close 175000, Stwo gate 269000; its history replays through them): run under its
# gates explicitly — on gen 29 both are block 1 and there is no window between them (gen-29 rehearsal)
CLOSE = _harness.gate_at("WIDE_DEPOSIT_CLOSE_HEIGHT", 28)
with _harness.pinned(WIDE_DEPOSIT_CLOSE_HEIGHT=CLOSE, STWO_POOL_HEIGHT=_harness.gate_at("STWO_POOL_HEIGHT", 28)):

    check("1. a wide deposit one block below the close is admitted", verdict(WIDE, CLOSE - 1) == "admitted",
          verdict(WIDE, CLOSE - 1))
    v = verdict(WIDE, CLOSE)
    check("...and refused at the close", "takes no new deposits" in v, v)
    check("...and after it", "takes no new deposits" in verdict(WIDE, CLOSE + 5000))
    _old = P.STWO_POOL_HEIGHT
    P.STWO_POOL_HEIGHT = CLOSE + 100
    check("2. a Stwo deposit at the Stwo gate is judged by the Stwo rules", verdict(STWO, CLOSE + 100) == "admitted",
          verdict(STWO, CLOSE + 100))
    check("...and an untagged deposit there is still the Stwo branch's refusal", "must name pool" in verdict(WIDE, CLOSE + 100))
    P.STWO_POOL_HEIGHT = _old
    check("3. generation 28's gates keep their order: the Stwo gate is never or above the close",
          P.STWO_POOL_HEIGHT == 0 or P.STWO_POOL_HEIGHT > CLOSE, (P.STWO_POOL_HEIGHT, CLOSE))
# GENERATION 29: the Stwo pool and the close are both block 1 — the Stwo gate is never below the close, a wide deposit
# is never admitted, a Stwo deposit is from the first block
_c29, _s29 = _harness.gate_at("WIDE_DEPOSIT_CLOSE_HEIGHT", 29), _harness.gate_at("STWO_POOL_HEIGHT", 29)
check("3'. generation 29: the Stwo gate is not below the close", _s29 >= _c29, (_s29, _c29))
with _harness.pinned(WIDE_DEPOSIT_CLOSE_HEIGHT=_c29, STWO_POOL_HEIGHT=_s29):
    check("...a wide deposit is refused from block 1 and a Stwo deposit admitted",
          verdict(WIDE, 1) != "admitted" and verdict(STWO, 1) == "admitted", (verdict(WIDE, 1), verdict(STWO, 1)))
check("...and the close reaches clients through /protocol.js", "WIDE_DEPOSIT_CLOSE_HEIGHT" in P.CLIENT_EXPORTS)

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
