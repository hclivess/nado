"""VALUE-CALL ESCROW derivation (protocol.SETTLE_PROOF_RECORDS_VALUE_CALLS), OFF by default.

A contract call carrying value>0 escrows sender -> cid (two T_BRIDGE_BAL positions) BEFORE the VM runs, and
the escrow is REFUNDED if the call reverts. So its net records effect is not a function of the calldata, and
records_bind marked such a block NON-DERIVABLE — which is why 78% of skipped spans (measured 2026-08-06)
were refused for "the RECORDS half moved across the span", on a chain where EVERY call carries value.

The proof is the missing verdict. zkvm.ZkVMRevert: "the interpreter reverts exactly where the AIR
constraints would have no satisfying witness, so 'provable' and 'executes successfully' are the same set of
calls." A VALID proof over a span therefore already establishes that every call in it succeeded, so every
escrow stuck — a pure function of the calldata. And `derivable` is consulted ONLY while a proof is being
validated, so a span that never gets one is unaffected.

FLAG STAYS OFF ON A LIVE CHAIN: exec summaries live in the `meta` sub-DB, which feeds the L1 state root, so
emitting effects where we used to write derivable=0 changes the root on upgraded nodes only — that
guarantees a fork, not risks one. It flips at a reroll.

Run: python3 tests/test_records_value_call.py
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol
from execnode.stark import records_bind as RB
from execnode import exec_root as ER

fails = 0


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


SENDER = "s" * 40
CID = "c" * 32


def _block(value, asset=0):
    return {"block_number": 10, "block_transactions": [
        {"recipient": "blob", "sender": SENDER,
         "data": {"op": "call", "contract": CID, "method": "open", "args": [],
                  "value": value, "asset": asset, "ns": "default"}}]}


def _with_flag(on, fn):
    old = getattr(protocol, "SETTLE_PROOF_RECORDS_VALUE_CALLS", False)
    protocol.SETTLE_PROOF_RECORDS_VALUE_CALLS = on
    try:
        return fn()
    finally:
        protocol.SETTLE_PROOF_RECORDS_VALUE_CALLS = old


# ---- default is OFF, behaviour unchanged --------------------------------------------------------------
def t_flag_defaults_off():
    assert getattr(protocol, "SETTLE_PROOF_RECORDS_VALUE_CALLS", None) is False, \
        "the flag must ship OFF — turning it on live guarantees a fork"


def t_off_keeps_value_call_non_derivable():
    eff, derivable = _with_flag(False, lambda: RB.block_records_effects(_block(20_000_000)))
    assert derivable is False and eff is None, \
        f"with the flag off a value call must stay non-derivable, got {derivable}/{eff}"


def t_zero_value_call_is_derivable_either_way():
    """A value=0 call escrows nothing, so it was always derivable and must remain so."""
    for on in (False, True):
        eff, derivable = _with_flag(on, lambda: RB.block_records_effects(_block(0)))
        assert derivable is True, f"a zero-value call must be derivable (flag={on}), got {derivable}"
        assert eff == [], f"a zero-value call must emit NO effects (flag={on}), got {eff}"


# ---- flag ON: the escrow is derived --------------------------------------------------------------------
def t_on_derives_both_positions():
    eff, derivable = _with_flag(True, lambda: RB.block_records_effects(_block(20_000_000)))
    assert derivable is True, "with the flag on a native value call must be derivable"
    assert eff is not None and len(eff) == 2, f"expected exactly two positions, got {eff}"
    by_addr = {parts[0]: delta for (_tag, parts, delta) in eff}
    assert by_addr.get(SENDER) == -20_000_000, f"sender must be debited, got {by_addr}"
    assert by_addr.get(CID) == 20_000_000, f"cid must be credited, got {by_addr}"
    assert all(tag == ER.T_BRIDGE_BAL for (tag, _p, _d) in eff), "both positions must be T_BRIDGE_BAL"


def t_escrow_is_zero_sum():
    """It MOVES units, it does not mint them — a records derivation that did not net to zero would settle a
    root with money created out of nothing."""
    eff, _ = _with_flag(True, lambda: RB.block_records_effects(_block(12_345)))
    assert sum(delta for (_t, _p, delta) in eff) == 0, f"escrow must net to zero, got {eff}"


# ---- fail-closed cases ---------------------------------------------------------------------------------
def t_asset_denominated_stays_non_derivable():
    """An asset-denominated value moves the ASSET ledger, not T_BRIDGE_BAL. Out of scope -> fail closed,
    rather than emitting half the effect."""
    eff, derivable = _with_flag(True, lambda: RB.block_records_effects(_block(5_000, asset=7)))
    assert derivable is False and eff is None, \
        f"an asset-denominated call must stay non-derivable, got {derivable}/{eff}"


def t_missing_sender_or_contract_fails_closed():
    for mutate in ("sender", "contract"):
        blk = _block(1_000)
        if mutate == "sender":
            blk["block_transactions"][0]["sender"] = None
        else:
            blk["block_transactions"][0]["data"]["contract"] = None
        eff, derivable = _with_flag(True, lambda: RB.block_records_effects(blk))
        assert derivable is False and eff is None, \
            f"a call with no {mutate} must fail closed, got {derivable}/{eff}"


for nm, fn in [("the flag ships OFF (live = guaranteed fork)", t_flag_defaults_off),
               ("flag OFF keeps a value call non-derivable", t_off_keeps_value_call_non_derivable),
               ("a zero-value call is derivable either way", t_zero_value_call_is_derivable_either_way),
               ("flag ON derives BOTH escrow positions", t_on_derives_both_positions),
               ("the derived escrow nets to ZERO (moves, not mints)", t_escrow_is_zero_sum),
               ("an asset-denominated value call fails closed", t_asset_denominated_stays_non_derivable),
               ("a call missing sender/contract fails closed", t_missing_sender_or_contract_fails_closed)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
