"""betanet-7 (gen 25), the REAL-DEVICE reroll: every register tx carries a hardware attestation, and the measures
that only existed to make identities expensive without one are gone — sequential work (PoSW) and its difficulty
machinery, the per-IP entry budget and identity cap, probation, the node's open-lane auto-register, the gen-24
gate constants. This pins that none of them survives (doc/device-attestation.md, "What the reroll retires")."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import protocol as P
import config as C
from ops import ratelimit


def main():
    assert P.CHAIN_GENERATION == 25 and P.CHAIN_ID == "betanet-7", (P.CHAIN_GENERATION, P.CHAIN_ID)
    assert C.get_protocol() >= 12, "pre-reroll nodes must be shed at handshake"
    assert P.DEVICE_ATTEST_HEIGHT == 1, "the device rule is unconditional from block 1"
    assert P.on_probation(0, 5) is False and P.on_probation(1, 5) is False, "probation retired"
    assert P.dividend_weight(1, 5) == 1, "an attested identity earns from its first lease"
    assert P.POSW_ENTRY_COUNT_HEIGHT == 0 and P.DIV_CARRY_METER_EPOCH == 0, "gen-24 gates retired"
    assert not hasattr(ratelimit, "allow_registration") and not hasattr(ratelimit, "allow_identity"), "per-IP budgets retired"
    assert hasattr(ratelimit, "allow"), "the plain API rate limiter stays"
    tx = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
    reg = tx[tx.index('elif recipient == "register":'):tx.index('elif recipient == "msgkey":')]
    assert "posw.verify" not in reg and "required_posw_t" not in reg, "PoSW must not be validated"
    assert "verify_register_device(transaction, anchor)" in reg and "DEVICE_ATTEST_HEIGHT" not in reg, "attestation unconditional"
    cl = open(os.path.join(ROOT, "loops", "core_loop.py")).read()
    body = cl[cl.index("def maybe_auto_register(self):"):cl.index("\n    def ", cl.index("def maybe_auto_register(self):") + 10)]
    assert "construct_register_tx" not in body, "nodes do not self-register in the open lane"
    nd = open(os.path.join(ROOT, "nado.py")).read()
    assert "allow_identity(" not in nd and "allow_registration(" not in nd
    cfg = open(os.path.join(ROOT, "config.py")).read()
    assert "max_registrations_per_ip" not in cfg and "max_identities_per_ip" not in cfg
    js = open(os.path.join(ROOT, "static", "interface.js")).read()
    seg = js[js.index("async function computeRegisterTx"):js.index("// What this device last proved")]
    assert "poswProveAsync" not in seg and "attestDevice(" in seg, "the wallet's registration proof is the attestation"
    print("ALL OK")


if __name__ == "__main__":
    main()
