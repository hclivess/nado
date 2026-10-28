"""The legacy pool's `shielded_transfer` is a skip at every height and moves nothing (G9 slice 5c).

The phase-1 BLAKE2b pool (execnode/shielded.py) is deleted. Its transparent transfer was live below
LEGACY_TRANSFER_CLOSE_HEIGHT (14000 on gen 29) — a no-input, zero-value transfer balanced (0 + 0 == 0 + 0), so any
sender could append notes and move the exec root — and from that gate the exec layer skipped it before parsing. The gen-29
chain carries no `shielded_transfer` below the gate (measured), so the op now returns the gate's skip at EVERY height,
which is the same verdict on every block the chain holds. Pins:
  1. at cursor -1 (genesis), 0, a mid-chain height, one block below the retired gate, the gate itself and far past it,
     every blob shape — the zero-value append that kept the pool live, a value mint, an unshield, a stark bundle, a bare
     op — returns exactly the gate's skip string;
  2. and moves nothing: the exec root, the shielded supply, the exits and the whole snapshot are byte-identical;
  3. the op stays its own op (never "unknown op"), and the retired gate constants are gone from protocol.py.

Run: python3 tests/test_shielded_transfer_is_a_skip_at_every_height.py
"""
import _harness
HOME = _harness.isolate("nado-test-legacy-transfer-skip-")
import json
import os

import protocol as P
from execnode.state import ExecState

T = _harness.Report()
CLOSED = "skip shielded_transfer: the legacy shielded pool is closed (LEGACY_TRANSFER_CLOSE_HEIGHT)"
OLD_GATE = 14000                       # the retired LEGACY_TRANSFER_CLOSE_HEIGHT on generation 29

BLOBS = (
    # the zero-value append (no inputs, a value-0 output) that kept the legacy pool live before the gate
    ("zero-value append", {"op": "shielded_transfer",
                           "public": {"root": "3494ed478a1577a5dad291006765ffcbf43096c44f1cec9121c302cf6b767f92",
                                      "nullifiers": [], "out_commitments": ["ab" * 32], "public_value": 0, "fee": 0},
                           "proof": {"inputs": [], "outputs": [{"value": 0, "owner": "cd" * 32, "rho": "r0"}]}}),
    ("value mint", {"op": "shielded_transfer",
                    "public": {"root": None, "nullifiers": [], "out_commitments": ["ef" * 32],
                               "public_value": 5 * 10 ** 12, "fee": 0},
                    "proof": {"inputs": [], "outputs": [{"value": 5 * 10 ** 12, "owner": "cd" * 32, "rho": "r1"}]}}),
    ("unshield", {"op": "shielded_transfer",
                  "public": {"root": "00" * 32, "nullifiers": ["11" * 32], "out_commitments": [], "public_value": -40,
                             "fee": 0, "withdraw_addr": "ndo" + "A" * 46},
                  "proof": {"inputs": [{"value": 40, "pubkey": "x", "rho": "r", "pos": 0, "path": [], "sig": "s"}],
                            "outputs": []}}),
    ("stark bundle", {"op": "shielded_transfer", "public": {"public_value": 0}, "proof": {"stark": {"joinsplit2": {}}}}),
    ("bare op", {"op": "shielded_transfer"}),
)


def _state(cursor):
    st = ExecState(os.path.join(HOME, f"s{cursor}.json"))
    st.cursor = cursor
    return st


def _everything(st):
    return st.state_root(), json.dumps(st._snapshot(), sort_keys=True, default=str)


def t_every_blob_is_the_gates_skip_and_moves_nothing():
    cursors = [-1, 0, 5000, OLD_GATE - 2, OLD_GATE - 1, OLD_GATE + 10 ** 6]
    seen = []
    for cursor in cursors:
        st = _state(cursor)
        before = _everything(st)
        for name, blob in BLOBS:
            res = st.apply_blob(json.loads(json.dumps(blob)), "ndoAnyone", f"{cursor}-{name}")
            assert res == CLOSED, (cursor, name, res)
            seen.append((cursor, name))
        assert _everything(st) == before, f"cursor {cursor}: a skipped legacy transfer moved the state"
        assert st.pool_value == 0 and st.pool_fees == 0 and not st.unshield_withdrawals and st.uw_nonce == 0
    assert len(seen) == len(cursors) * len(BLOBS), seen


def t_the_op_is_its_own_op_and_the_gate_constants_are_retired():
    st = _state(OLD_GATE - 2)                         # below the retired gate: the transfer applied there before 5c
    assert st.apply_blob({"op": "shielded_transfer"}, "ndoAnyone", "x") == CLOSED
    assert st.apply_blob({"op": "no_such_op"}, "ndoAnyone", "y").startswith("skip: unknown op"), "a real unknown op"
    assert not hasattr(P, "LEGACY_TRANSFER_CLOSE_HEIGHT") and not hasattr(P, "LEGACY_SHIELD_CLOSE_HEIGHT")
    assert not hasattr(st, "shielded"), "the legacy pool is gone from the exec state"


T.run("1+2. every blob, at every cursor: the gate's skip, and nothing moves",
      t_every_blob_is_the_gates_skip_and_moves_nothing)
T.run("3. the op stays its own op; the gate constants are retired",
      t_the_op_is_its_own_op_and_the_gate_constants_are_retired)
T.done()
