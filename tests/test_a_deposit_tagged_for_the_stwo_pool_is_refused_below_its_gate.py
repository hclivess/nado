"""A shield deposit that names the Stwo pool (`pool: "stwo"`) is refused below STWO_POOL_HEIGHT, exactly as an untagged
one is refused from it (ops/transaction_ops.field_shield_check).

REVIEW 2026-10-11 (integration, reproduced, NOT FIXED — consensus code). The tag exists because a wide owner and a Stwo
owner are both 64-hex and L1 cannot tell them apart; from the gate an untagged deposit is refused. The other direction
is open: below the gate the wide branch ignores `pool`, so a tagged deposit is admitted and the exec layer
(apply_field_shield, which never sees the tag) puts the coins in the WIDE pool under a BLAKE2s owner — a note no key
can ever spend, coins stranded in SHIELD_ESCROW. The wallet tags by the RELAY's tip + 1 (stwoGateLive); a relay ahead of
the block that includes the tx (failover to a lagging relay, a reorg to a shorter branch) lands it at gate - 1.
The fix is one assert in the wide branch; the refusal moves no coin (L1 refuses the tx outright).

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

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def admitted(data, h):
    try:
        field_shield_check(data, h)
        return True
    except Exception:
        return False


GATE = 900
live = P.STWO_POOL_HEIGHT
P.STWO_POOL_HEIGHT = GATE
owner = SP.owner_of("33" * 32)                 # a real Stwo owner, as the wallet's shieldOwner() builds it
tagged = {"field": True, "owner": owner, "rho": "5", "pool": "stwo"}
check("setup: the tagged deposit is admitted at the gate", admitted(tagged, GATE))
check("setup: and the same owner passes the wide parser (the common case, ~1 - 2^-30)", admitted({"field": True, "owner": owner, "rho": "5"}, GATE - 1))
st = ExecState(os.path.join(tempfile.mkdtemp(dir=H), "s.json"))
st.cursor = GATE - 2
r = st.apply_field_shield(10 ** 10, owner, 5)
check("(what admission at gate - 1 would do: the coins become a WIDE note under a Stwo owner)",
      "wide note" in r and not st.stwo_pool.commitments, r)
check("a deposit tagged for the Stwo pool is refused at gate - 1", not admitted(tagged, GATE - 1))
P.STWO_POOL_HEIGHT = live
print("ALL PASS — a Stwo-tagged deposit is refused below the gate" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
