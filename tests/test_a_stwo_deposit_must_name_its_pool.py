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

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


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
P.STWO_POOL_HEIGHT = GATE
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
check("on the live value nothing changes at any height (dormant)",
      admitted({"owner": good_wide, "rho": "5"}, 10 ** 9) and not admitted({"owner": bad_lane, "rho": "5", "pool": "stwo"}, 10 ** 9))
print("ALL PASS — a Stwo deposit must name its pool" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
