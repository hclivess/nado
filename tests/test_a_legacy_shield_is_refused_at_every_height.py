"""A legacy shield (`out_commitments`, no `field`) is refused by L1 and skipped by the exec layer at EVERY height; a Stwo
deposit is unaffected (G9 slice 5c).

LEGACY_SHIELD_CLOSE_HEIGHT (10000 on gen 29) closed the legacy BLAKE2b pool to deposits: from it L1 refused one and the
exec layer skipped it. Below it L1 still accepted one — mempool admission at None/0 included — but the gen-29 chain
carries NO legacy shield below the gate (measured: none in 0..12411), so with the pool deleted the refusal is
unconditional and the gate is retired. Pins:
  1. L1 refuses a legacy shield at every height kind — None (mempool admission), 0 (a genesis tip), 1, one block below
     the retired gate, the gate, far past it — naming the gate, with or without commitments;
  2. the exec layer adds no note and moves no root for one, below and at the retired gate;
  3. a Stwo-pool deposit (`field`) still validates from block 1 (and at 0, where the shape check never ran);
  4. the gate constant is retired from protocol.py (tests/test_gate_reroll_transfer.py keeps it in DELETED).

Run: python3 tests/test_a_legacy_shield_is_refused_at_every_height.py
"""
import _harness
HOME = _harness.isolate("nado-test-legacy-shield-refused-")
import os

import protocol as P
from execnode import block_apply
from execnode.state import ExecState
from ops import transaction_ops as TO

T = _harness.Report()
OLD_GATE = 10000                        # the retired LEGACY_SHIELD_CLOSE_HEIGHT on generation 29
A = "ndo" + "A" * 45

opening = {"value": 700, "owner": "ab" * 16, "rho": "cd" * 16}
legacy = {"recipient": "shield", "sender": A, "amount": 700, "fee": P.MIN_TX_FEE, "txid": "l1",
          "data": {"out_commitments": ["ef" * 32], "openings": [opening]}}
bare = dict(legacy, txid="l2", data={"out_commitments": []})
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
    before = (st.state_root(), st.pool_value, list(st.stwo_pool.commitments))
    blk = {"block_number": h, "block_hash": "%064x" % h, "block_transactions": [tx]}
    block_apply.begin({"default": st}, h)
    block_apply.dispatch({"default": st}, st, blk, {}, set(), verbose=False)
    return before, (st.state_root(), st.pool_value, list(st.stwo_pool.commitments))


heights = (None, 0, 1, OLD_GATE - 1, OLD_GATE, OLD_GATE + 10 ** 6)
verdicts = {(h, tx["txid"]): l1(tx, h) for h in heights for tx in (legacy, bare)}
T.check("1. L1 refuses a legacy shield at every height kind (None, 0, 1, below/at/past the retired gate), naming the gate",
        len(verdicts) == 2 * len(heights)
        and all(v.startswith("refused") and "LEGACY_SHIELD_CLOSE" in v for v in verdicts.values()), verdicts)
moved = {h: exec_apply(legacy, h) for h in (1, OLD_GATE - 1, OLD_GATE)}
T.check("2. the exec layer adds no note and moves no root for one, below and at the retired gate",
        all(b == a for b, a in moved.values()) and len(moved) == 3, moved)
T.check("3. a Stwo-pool deposit (field) validates at 0, 1, below and from the retired gate",
        [l1(field, h) for h in (0, 1, OLD_GATE - 1, OLD_GATE)] == ["ok"] * 4,
        [l1(field, h) for h in (0, 1, OLD_GATE - 1, OLD_GATE)])
T.check("4. LEGACY_SHIELD_CLOSE_HEIGHT is retired", not hasattr(P, "LEGACY_SHIELD_CLOSE_HEIGHT"))
T.done()
