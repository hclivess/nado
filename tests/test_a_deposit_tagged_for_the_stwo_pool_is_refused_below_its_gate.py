"""A shield deposit that names the Stwo pool (`pool: "stwo"`) is refused below STWO_POOL_HEIGHT, exactly as an untagged
one is refused from it (ops/transaction_ops.field_shield_check).

REVIEW 2026-10-11 (integration, reproduced). The tag exists because a wide owner and a Stwo owner are both 64-hex and
L1 cannot tell them apart; from the gate an untagged deposit is refused. The other direction was open: below the gate
the wide branch ignores `pool`, so a tagged deposit was admitted and the exec layer (apply_field_shield, which never
sees the tag) put the coins in the WIDE pool under a BLAKE2s owner — a note no key can ever spend. The wallet tags by
the RELAY's tip + 1 (stwoGateLive); a relay ahead of the block that includes the tx lands it at gate - 1.

CLOSED BY WIDE_DEPOSIT_CLOSE_HEIGHT, not by a new rule: from the close no deposit reaches the wide pool at all, so as
long as the Stwo gate is at or above the close, the window between them refuses everything. An assert on the tag below
the close would have changed a LIVE rule ungated. Pins: the refusal in that window, the scheduled gates keep
STWO >= CLOSE, and the exec-layer consequence that made it matter.

Run: python3 tests/test_a_deposit_tagged_for_the_stwo_pool_is_refused_below_its_gate.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-stwo-tag-below-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
H = os.environ["HOME"]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import protocol as P
from ops.transaction_ops import field_shield_check
from execnode.state import ExecState
from execnode import shielded_stwo as SP

import _harness
_report = _harness.Report()
check = _report.check


def admitted(data, h):
    try:
        field_shield_check(data, h)
        return True
    except Exception:
        return False


live_gate, live_close = P.STWO_POOL_HEIGHT, P.WIDE_DEPOSIT_CLOSE_HEIGHT
check("the scheduled Stwo gate is at or above the wide close (else the tagged window reopens)",
      not live_gate or live_gate >= live_close, f"STWO_POOL_HEIGHT {live_gate} < WIDE_DEPOSIT_CLOSE_HEIGHT {live_close}")
GATE, CLOSE = 900, 800
P.STWO_POOL_HEIGHT, P.WIDE_DEPOSIT_CLOSE_HEIGHT = GATE, CLOSE
owner = SP.owner_of("33" * 32)                 # a real Stwo owner, as the wallet's shieldOwner() builds it
tagged = {"field": True, "owner": owner, "rho": "5", "pool": "stwo"}
check("setup: the tagged deposit is admitted at the gate", admitted(tagged, GATE))
check("a deposit tagged for the Stwo pool is refused at gate - 1", not admitted(tagged, GATE - 1))
check("and anywhere between the wide close and the gate", not admitted(tagged, CLOSE))
check("(below the close the wide pool still takes a wide deposit, as live history did)",
      admitted({"field": True, "owner": owner, "rho": "5"}, CLOSE - 1))
st = ExecState(os.path.join(tempfile.mkdtemp(dir=H), "s.json"))
st.cursor = GATE - 2
r = st.apply_field_shield(10 ** 10, owner, 5)
check("(why it matters: admitted below the gate, the coins become a WIDE note under a Stwo owner)",
      "wide note" in r and not st.stwo_pool.commitments, r)
P.STWO_POOL_HEIGHT, P.WIDE_DEPOSIT_CLOSE_HEIGHT = live_gate, live_close
print("ALL PASS — a Stwo-tagged deposit is refused below the gate" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
