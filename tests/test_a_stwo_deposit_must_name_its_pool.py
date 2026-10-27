"""From block 1 a shield deposit must name the Stwo pool, and any BLAKE2s owner is admitted
(ops/transaction_ops.field_shield_check; gen 28's STWO_POOL_HEIGHT, 1 from gen 29, inlined in G9).

Two holes the wallet build found in L1 admission: the wide check parsed the owner as an alghash2 digest, refusing about
1 in 2^30 BLAKE2s owners (a user who simply could not deposit); and a wallet tab loaded before the gate builds a WIDE
owner that L1 cannot tell apart from a Stwo one — admitted, its coins would sit under an owner nobody can spend. Pins:
an untagged deposit is refused, a tagged one with an owner the wide parser rejects is admitted, rho is a u64, and
height 0 keeps its old verdict.

Run: python3 tests/test_a_stwo_deposit_must_name_its_pool.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-stwo-deposit-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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

GATE = 900                                 # a test height: the Stwo rule holds from block 1
good_wide = "0" * 63 + "1"
# the pre-gate half (the wide rule below the gate, generation 28's close / Stwo windows) retired in G9: generation 28's
# rules — STWO_POOL_HEIGHT and WIDE_DEPOSIT_CLOSE_HEIGHT are inlined as block 1
check("an UNTAGGED deposit is refused (an old tab's wide owner)", not admitted({"owner": good_wide, "rho": "5"}, GATE)
      and not admitted({"owner": good_wide, "rho": "5"}, 1))
check("...a tagged deposit with any 64-hex BLAKE2s owner is admitted, even one the wide parser refuses",
      admitted({"owner": bad_lane, "rho": "5", "pool": "stwo"}, GATE) and admitted({"owner": bad_lane, "rho": "5", "pool": "stwo"}, 1))
check("...rho is a u64: 2^64 - 1 admitted, 2^64 refused",
      admitted({"owner": bad_lane, "rho": str((1 << 64) - 1), "pool": "stwo"}, GATE)
      and not admitted({"owner": bad_lane, "rho": str(1 << 64), "pool": "stwo"}, GATE))
check("...an uppercase or short owner is refused", not admitted({"owner": bad_lane.upper(), "rho": "1", "pool": "stwo"}, GATE)
      and not admitted({"owner": "ab" * 31, "rho": "1", "pool": "stwo"}, GATE))
check("height 0 (mempool admission on a genesis tip) keeps its old verdict: no shape check",
      admitted({"owner": good_wide, "rho": "5"}, 0) and admitted({"owner": bad_lane, "rho": "5", "pool": "stwo"}, 0))
print("ALL PASS — a Stwo deposit must name its pool" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
