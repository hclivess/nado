"""PRIVACY_PAUSE_HEIGHT closes every value path a forged or malformed privacy proof could reach (2026-09-24).

A review of the proof system found value-creating flaws on the privacy paths (a shielded-contract deposit that could
commit a note worth more than it paid, reproduced against a 1,000,000-unit contract balance, among others). None of
these paths carries value today, so they close at a gate while the fixes ship:

  * the exec layer refuses `private_call`, the LEGACY field pool's `field_transfer`, and a `stark` bundle on the
    transparent `shielded_transfer` op — before parsing anything or moving any balance, so a refusal is a no-op;
  * the wide pool (SHIELD_WIDE_HEIGHT) stays open;
  * L1 refuses a legacy field-shield deposit from REVIEW_R2_HEIGHT (transaction_ops.field_shield_check), judged at
    the block's own height. That check used to read an unbound `h` and raised on EVERY field shield, wide ones
    included — this file drives it at every height kind, so a NameError/UnboundLocalError fails here first.

Run: python3 tests/test_privacy_pause.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-privacy-pause-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")   # never the live exec files
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import json, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol as P
from execnode.state import ExecState

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

G = int(P.PRIVACY_PAUSE_HEIGHT)
USER = "ndo" + "A" * 45


def _state_at(h):
    st = ExecState(os.path.join(os.environ["HOME"], f"s{h}.json"))
    st._applying = h
    st.bridge[USER] = 10 ** 6
    return st


def t_the_gate_is_registered_and_keyed_on_the_generation():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocol.py")).read()
    assert "PRIVACY_PAUSE_HEIGHT = 226400 if CHAIN_GENERATION == 25 else 1" in src
    assert G > P.REVIEW_R2_HEIGHT and P.SHIELD_WIDE_HEIGHT == (1 << 62), "the wide pool is still reroll-only"


def t_private_call_is_refused_from_the_gate_before_any_parsing():
    blob = {"op": "private_call", "public_json": json.dumps({"cid": "c" * 32, "public_delta": 5}),
            "proof_json": json.dumps({"stark": {}})}
    st = _state_at(G)
    r = st.apply_blob(dict(blob), USER, "t1")
    assert "paused" in r, r
    assert st.bridge[USER] == 10 ** 6, "a refused private call moves nothing"
    r = _state_at(G - 1).apply_blob(dict(blob), USER, "t2")
    assert "paused" not in r, f"below the gate the pause must not apply: {r}"


def t_legacy_field_transfer_is_refused_from_the_gate_and_the_wide_pool_is_not():
    blob = {"op": "field_transfer", "bundle_json": json.dumps({"kind": "joinsplit2"})}
    assert "paused" in _state_at(G).apply_blob(dict(blob), USER, "t3")
    assert "paused" not in _state_at(G - 1).apply_blob(dict(blob), USER, "t4")
    saved = P.SHIELD_WIDE_HEIGHT
    try:
        P.SHIELD_WIDE_HEIGHT = 1                                  # a chain where the wide pool is live
        r = _state_at(G).apply_blob(dict(blob), USER, "t5")
        assert "paused" not in r, f"the wide pool must stay open under the pause: {r}"
    finally:
        P.SHIELD_WIDE_HEIGHT = saved


def t_stark_bundles_are_refused_on_the_transparent_op_but_signed_transfers_are_not():
    stark_blob = {"op": "shielded_transfer", "public": {"public_value": 0}, "proof": {"stark": {"joinsplit2": {}}}}
    assert "stark bundles are refused" in _state_at(G).apply_blob(dict(stark_blob), USER, "t6")
    signed = {"op": "shielded_transfer", "public": {"public_value": 0}, "proof": {"sig": "x"}}
    assert "stark bundles are refused" not in _state_at(G).apply_blob(dict(signed), USER, "t7")


def t_field_shield_admission_is_judged_at_the_block_height_and_never_raises_a_name_error():
    from ops.transaction_ops import field_shield_check
    legacy = {"field": True, "owner": "123", "rho": "456"}
    for h in (1, P.REVIEW_R2_HEIGHT - 1):
        field_shield_check(dict(legacy), h)                       # below REVIEW_R2 the legacy pool took deposits
    for h in (P.REVIEW_R2_HEIGHT, G, G + 10 ** 6):
        try:
            field_shield_check(dict(legacy), h)
            raise RuntimeError(f"a legacy field shield at {h} was admitted")
        except AssertionError as e:
            assert "closed to deposits" in str(e), e
    saved = P.SHIELD_WIDE_HEIGHT
    try:
        P.SHIELD_WIDE_HEIGHT = 1
        field_shield_check({"field": True, "owner": "0" * 64, "rho": "7"}, G)      # the wide pool's own deposit
        for bad in ({"field": True, "owner": "123", "rho": "7"}, {"field": True, "owner": "0" * 64, "rho": "x"}):
            try:
                field_shield_check(dict(bad), G); raise RuntimeError(f"malformed wide deposit admitted: {bad}")
            except AssertionError:
                pass
    finally:
        P.SHIELD_WIDE_HEIGHT = saved


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("t_"):
            check(name[2:].replace("_", " "), fn)
    print("ALL PASS" if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
