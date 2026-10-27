"""The legacy BLAKE2b shielded pool takes no new deposits from LEGACY_SHIELD_CLOSE_HEIGHT; a Stwo deposit is unaffected.

G9 (doc/stwo-migration.md 9.7) deletes the legacy pool, which is only sound if it stays empty. Its transfers were paused
and the wallet no longer offered it, yet L1 still accepted a `shield` with `out_commitments` and the exec layer added the
notes: coins that could only be locked. Measured, generation 29 never carried one (blocks 0..7608). Both rule sets:
  1. BELOW the gate a valid legacy shield validates on L1 (mempool admission on a genesis tip keeps its verdict), and the
     exec layer skips it there too since G9 slice 5 deleted the deposit path: no legacy shield exists in 0..10533
     (measured 2026-10-28), a final range, so history replays unchanged (tools/replay_exec.py, IDENTICAL);
  2. FROM the gate L1 refuses it, naming the gate, and the exec layer skips it: the pool, its root records and the exec
     root do not move;
  3. a Stwo-pool deposit (`field`) validates on both sides of the gate;
  4. the gate is the generation-keyed form, live on generation 29 and from block 1 at a reroll.

Run: python3 tests/test_the_legacy_shielded_pool_takes_no_deposits_from_its_gate.py
"""
import _harness
HOME = _harness.isolate("nado-test-legacy-shield-close-")
import os

import protocol as P
from execnode import block_apply
from execnode.shielded import note_commitment
from execnode.state import ExecState
from ops import transaction_ops as TO

T = _harness.Report()
GATE = P.LEGACY_SHIELD_CLOSE_HEIGHT
A = "ndo" + "A" * 45

opening = {"value": 700, "owner": "ab" * 16, "rho": "cd" * 16}
cm = note_commitment(opening["value"], opening["owner"], opening["rho"])
legacy = {"recipient": "shield", "sender": A, "amount": 700, "fee": P.MIN_TX_FEE, "txid": "l1",
          "data": {"out_commitments": [cm], "openings": [opening]}}
field = {"recipient": "shield", "sender": A, "amount": 700, "fee": P.MIN_TX_FEE, "txid": "f1",
         "data": {"field": True, "pool": "stwo", "owner": "ef" * 32, "rho": 7}}


def l1(tx, h):
    try:
        TO._validate_shield(tx, h)
        return "ok"
    except AssertionError as e:
        return f"refused: {e}"


def exec_apply(tx, h):
    st = ExecState(os.path.join(HOME, f"st{h}{tx['txid']}.json"))
    st.cursor = h - 1
    before = (st.state_root(), list(st.shielded.commitments))
    blk = {"block_number": h, "block_hash": "%064x" % h, "block_transactions": [tx]}
    block_apply.begin({"default": st}, h)
    block_apply.dispatch({"default": st}, st, blk, {}, set(), verbose=False)
    return before, (st.state_root(), list(st.shielded.commitments))


T.check("4. the gate is generation-keyed: live on 29, from block 1 at a reroll",
        _harness.gate_at("LEGACY_SHIELD_CLOSE_HEIGHT", 29) == GATE and _harness.gate_at("LEGACY_SHIELD_CLOSE_HEIGHT", 30) == 1
        and GATE > 1, GATE)
T.check("1a. below the gate a valid legacy shield validates on L1", l1(legacy, GATE - 1) == "ok", l1(legacy, GATE - 1))
b, a = exec_apply(legacy, GATE - 1)
T.check("1b. ...but the exec layer adds no note at any height (the deposit path is deleted)", a == b and a[1] == [], (b, a))
r = l1(legacy, GATE)
T.check("2a. from the gate L1 refuses a legacy shield, naming the gate", r.startswith("refused") and "LEGACY_SHIELD_CLOSE" in r, r)
b, a = exec_apply(legacy, GATE)
T.check("2b. ...and the exec layer skips it: no note, no root change", a == b, (b, a))
T.check("3. a Stwo-pool deposit (field) validates below and from the gate",
        l1(field, GATE - 1) == "ok" and l1(field, GATE) == "ok", (l1(field, GATE - 1), l1(field, GATE)))
T.done()
