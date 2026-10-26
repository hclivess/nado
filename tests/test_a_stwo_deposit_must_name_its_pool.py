"""From STWO_POOL_HEIGHT a shield deposit must name the Stwo pool, and any BLAKE2s owner is admitted
(ops/transaction_ops.field_shield_check).

Two holes the wallet build found in L1 admission: the wide check parsed the owner as an alghash2 digest, refusing about
1 in 2^30 BLAKE2s owners (a user who simply could not deposit); and a wallet tab loaded before the gate builds a WIDE
owner that L1 cannot tell apart from a Stwo one — admitted, its coins would sit under an owner nobody can spend. Pins:
below the gate the wide rule is unchanged; from it an untagged deposit is refused, a tagged one with an owner the wide
parser rejects is admitted, and rho is a u64; and the live value keeps all of it dormant.

Run: python3 tests/test_a_stwo_deposit_must_name_its_pool.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-stwo-deposit-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import protocol as P
from ops.transaction_ops import field_shield_check
from execnode.stark import znote as Z

import _harness
_report = _harness.Report()
check = _report.check


def admitted(data, h):
    try:
        field_shield_check(data, h)
        return True
    except Exception:                          # validation treats any raise as a refusal (the wide parser raises ValueError)
        return False


# an owner the wide (alghash2) parser refuses: a lane at or above the field prime
bad_lane = ("ff" * 8) + ("00" * 24)
try:
    Z.from_hex(bad_lane); wide_refuses = False
except Exception:
    wide_refuses = True
check("setup: the wide parser refuses this 64-hex owner", wide_refuses)

GATE = 900
live = P.STWO_POOL_HEIGHT
live_close = P.WIDE_DEPOSIT_CLOSE_HEIGHT
P.STWO_POOL_HEIGHT = GATE
P.WIDE_DEPOSIT_CLOSE_HEIGHT = 1 << 62      # the wide rule BELOW the Stwo gate, with no close in the way (gen 29's is 1)
good_wide = "0" * 63 + "1"
check("below the gate the wide rule is unchanged: an untagged deposit with a field-valid owner is admitted",
      admitted({"owner": good_wide, "rho": "5"}, GATE - 1))
check("...and an owner the wide parser refuses is still refused there", not admitted({"owner": bad_lane, "rho": "5"}, GATE - 1))
check("from the gate an UNTAGGED deposit is refused (an old tab's wide owner)", not admitted({"owner": good_wide, "rho": "5"}, GATE))
check("...a tagged deposit with any 64-hex BLAKE2s owner is admitted, even one the wide parser refuses",
      admitted({"owner": bad_lane, "rho": "5", "pool": "stwo"}, GATE))
check("...rho is a u64: 2^64 - 1 admitted, 2^64 refused",
      admitted({"owner": bad_lane, "rho": str((1 << 64) - 1), "pool": "stwo"}, GATE)
      and not admitted({"owner": bad_lane, "rho": str(1 << 64), "pool": "stwo"}, GATE))
check("...an uppercase or short owner is refused", not admitted({"owner": bad_lane.upper(), "rho": "1", "pool": "stwo"}, GATE)
      and not admitted({"owner": "ab" * 31, "rho": "1", "pool": "stwo"}, GATE))
P.STWO_POOL_HEIGHT = live
P.WIDE_DEPOSIT_CLOSE_HEIGHT = live_close
# GENERATION 28'S WINDOWS (its history replays through them): below WIDE_DEPOSIT_CLOSE_HEIGHT the wide pool takes its
# deposits; from it no pool does until the Stwo gate (tests/test_the_wide_pool_takes_no_deposits_after_its_close.py)
import _harness
_WC, _G = _harness.gate_at("WIDE_DEPOSIT_CLOSE_HEIGHT", 28), _harness.gate_at("STWO_POOL_HEIGHT", 28)
with _harness.pinned(WIDE_DEPOSIT_CLOSE_HEIGHT=_WC, STWO_POOL_HEIGHT=_G):
    check("generation 28: a wide deposit below the close, none between the close and the Stwo gate, a tagged one from it",
          admitted({"owner": good_wide, "rho": "5"}, _WC - 1)
          and not admitted({"owner": good_wide, "rho": "5"}, _G - 1) and not admitted({"owner": bad_lane, "rho": "5", "pool": "stwo"}, _G - 1)
          and admitted({"owner": bad_lane, "rho": "5", "pool": "stwo"}, _G) and not admitted({"owner": good_wide, "rho": "5"}, _G))
# GENERATION 29 (both gates 1): the Stwo pool from block 1, the wide pool never
with _harness.pinned(WIDE_DEPOSIT_CLOSE_HEIGHT=_harness.gate_at("WIDE_DEPOSIT_CLOSE_HEIGHT", 29),
                     STWO_POOL_HEIGHT=_harness.gate_at("STWO_POOL_HEIGHT", 29)):
    check("generation 29: from block 1 a tagged deposit is admitted and an untagged (wide) one never is",
          admitted({"owner": bad_lane, "rho": "5", "pool": "stwo"}, 1) and not admitted({"owner": good_wide, "rho": "5"}, 1))
print("ALL PASS — a Stwo deposit must name its pool" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
