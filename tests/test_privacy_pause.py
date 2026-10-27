"""PRIVACY_PAUSE_HEIGHT closes every value path a forged or malformed privacy proof could reach (2026-09-24).

A review of the proof system found value-creating flaws on the privacy paths (a shielded-contract deposit that could
commit a note worth more than it paid, reproduced against a 1,000,000-unit contract balance, among others). None of
these paths carries value today, so they closed at a gate while the fixes ship. On gen 25 that gate was 226400; from
gen 26 it (and the wide pool's and REVIEW_R2's) was 1, and all three were deleted after the betanet-8 reroll. G9 slice 5
deleted the field, wide and shielded-contract pools, and with them the height-0 exception: the refusals below hold at
EVERY height (below block 1 only genesis is applied, which carries no transaction on generation 29):

  * the exec layer refuses `private_call` and a `stark` bundle on the transparent `shielded_transfer` op — before
    parsing anything or moving any balance, so a refusal is a no-op;
  * `field_transfer` is a Stwo spend from block 1 and is never refused as paused;
  * L1 admits only a WIDE field-shield deposit from block 1 (transaction_ops.field_shield_check), judged at the block's
    own height. That check used to read an unbound `h` and raised on EVERY field shield, wide ones included — this
    file drives it at every height kind, so a NameError/UnboundLocalError fails here first.

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

import _harness
_report = _harness.Report()
check = _report.run

G = 1                       # the pause holds from block 1 (gen 25's PRIVACY_PAUSE_HEIGHT, deleted); height 0 is below it
USER = "ndo" + "A" * 45


def _state_at(h):
    st = ExecState(os.path.join(os.environ["HOME"], f"s{h}.json"))
    st._applying = h
    st.bridge[USER] = 10 ** 6
    return st


def t_the_gates_are_deleted_and_the_rules_hold_from_block_1():
    for name in ("PRIVACY_PAUSE_HEIGHT", "SHIELD_WIDE_HEIGHT", "REVIEW_R2_HEIGHT"):
        assert not hasattr(P, name), f"{name} is back"
    st0, st1 = _state_at(0), _state_at(1)
    assert not st0.rules_r2() and st1.rules_r2(), "REVIEW_R2: below at height 0, in force from block 1"
    # the pause and wide-pool helpers went with their pools (G9 slice 5): nothing may consult them again
    assert not hasattr(st1, "rules_privacy_pause") and not hasattr(st1, "rules_shield_wide")


def t_private_call_is_refused_at_every_height_before_any_parsing():
    blob = {"op": "private_call", "public_json": json.dumps({"cid": "c" * 32, "public_delta": 5}),
            "proof_json": json.dumps({"stark": {}})}
    st = _state_at(G)
    r = st.apply_blob(dict(blob), USER, "t1")
    assert "paused" in r, r
    assert st.bridge[USER] == 10 ** 6, "a refused private call moves nothing"
    st0 = _state_at(G - 1)                       # height 0 too since G9 slice 5: the transition code is deleted
    r = st0.apply_blob(dict(blob), USER, "t2")
    assert "paused" in r, f"a private call is refused at every height: {r}"
    assert st0.bridge[USER] == 10 ** 6


def t_field_transfer_is_a_stwo_spend_and_is_never_refused_as_paused():
    blob = {"op": "field_transfer", "bundle_json": json.dumps({"kind": "joinsplit2"})}
    r = _state_at(G).apply_blob(dict(blob), USER, "t5")
    assert "paused" not in r and "stwo_js" in r, f"a field_transfer is judged as a Stwo spend: {r}"
    assert "paused" not in _state_at(G - 1).apply_blob(dict(blob), USER, "t4")


def t_stark_bundles_are_refused_on_the_transparent_op_but_signed_transfers_are_not():
    stark_blob = {"op": "shielded_transfer", "public": {"public_value": 0}, "proof": {"stark": {"joinsplit2": {}}}}
    assert "stark bundles are refused" in _state_at(G).apply_blob(dict(stark_blob), USER, "t6")
    signed = {"op": "shielded_transfer", "public": {"public_value": 0}, "proof": {"sig": "x"}}
    assert "stark bundles are refused" not in _state_at(G).apply_blob(dict(signed), USER, "t7")
    assert "stark bundles are refused" in _state_at(G - 1).apply_blob(dict(stark_blob), USER, "t8"), "at every height"


def t_field_shield_admission_is_judged_at_the_block_height_and_never_raises_a_name_error():
    from ops.transaction_ops import field_shield_check
    legacy = {"field": True, "owner": "123", "rho": "456"}
    field_shield_check(dict(legacy), 0)                           # height 0: below every deleted gate, no shape check
    for h in (G, G + 10 ** 6):
        try:
            field_shield_check(dict(legacy), h)
            raise RuntimeError(f"a legacy field shield at {h} was admitted")
        except AssertionError as e:
            # refused because an untagged deposit is not a Stwo one (the wide pool takes no deposits at all)
            assert ("wide shield owner" in str(e) or "takes no new deposits" in str(e)
                    or 'must name pool "stwo"' in str(e)), e
    # THE WIDE POOL'S OWN DEPOSITS (generation 28's WIDE_DEPOSIT_CLOSE_HEIGHT / STWO_POOL_HEIGHT window) retired in G9:
    # generation 28's rules. Both gates are inlined as block 1, where no wide deposit is ever admitted.
    try:
        field_shield_check({"field": True, "owner": "0" * 64, "rho": "7"}, G)
        raise RuntimeError("a wide (untagged) deposit was admitted")
    except AssertionError:
        pass                                                                       # the Stwo pool only


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("t_"):
            check(name[2:].replace("_", " "), fn)
    print("ALL PASS" if not _report.fails else f"{_report.fails} FAILURES")
    sys.exit(1 if _report.fails else 0)
