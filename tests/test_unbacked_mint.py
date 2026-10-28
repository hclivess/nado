"""
Shielded pool — UNBACKED-MINT fence (doc/privacy.md, execnode/state.py).

Coins may only ENTER the shielded pool via an L1 `shield` tx, whose escrowed amount drives
apply_field_shield. A transfer BLOB is user-supplied and escrow-free, so a positive
`public_value` there would mint notes backed by nothing: the join-split circuit faithfully proves
`v_in + public_value == v_out + fee`, but `public_value` is a PUBLIC INPUT the prover chooses, not a
fact about escrow. Without the fence, one MIN_TX_FEE blob mints an arbitrary note and unshields it
straight back out against SHIELD_ESCROW — draining every other depositor (L1's `escrow.balance >=
amount` floor bounds the loss to the escrow, but that IS everyone's deposits).

These tests assert that the transparent blob path mints nothing: since G9 slice 5c the legacy `shielded_transfer` is a
skip at every height (the fence that refused public_value > 0 went with the pool it guarded), so a mint blob moves no
value, records no exit and leaves the exec root where it was — and that the LEGITIMATE escrow-driven deposit
(apply_field_shield, whose value comes from the authoritative on-chain amount) still works. A Stwo spend cannot carry
value in at all: its public values are an unshield and a fee, both u64.

Run: python3 tests/test_unbacked_mint.py
"""
import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_mint_")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)   # leave no /tmp home behind (9,600 leaked by 2026-09-22)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState

import _harness
_report = _harness.Report()
check = _report.run

MINT = 5_000_000_000_000                      # 500 NADO conjured from nothing
PATH = os.path.join(os.environ["HOME"], "exec_mint.json")


def _fresh():
    """A pristine ExecState — no shield deposit has ever been applied, so escrow backing is zero."""
    return ExecState(path=os.path.join(tempfile.mkdtemp(prefix="nado_mint_st_"), "s.json"))


def _mint_blob(value):
    """A transparent-path transfer blob with NO inputs and public_value > 0 — the mint attempt (the commitment and owner
    are opaque strings: the op is refused before anything is parsed)."""
    owner, rho = "ee" * 32, "r0"
    return {"op": "shielded_transfer",
            "public": {"root": None, "nullifiers": [], "out_commitments": ["cd" * 32],
                       "public_value": value, "fee": 0},
            "proof": {"inputs": [], "outputs": [{"value": value, "owner": owner, "rho": rho}]}}


def _value_state(st):
    """Everything a mint could move: the shielded supply, the exits, and the exec root."""
    return (st.pool_value, st.pool_fees, st.stwo_value, dict(st.unshield_withdrawals), st.uw_nonce,
            len(st.stwo_pool.commitments), st.state_root())


def t1():
    """A transparent transfer blob with public_value > 0 is skipped as the closed legacy op and mints nothing."""
    st = _fresh()
    st.cursor = 5000                                    # below the retired LEGACY_TRANSFER_CLOSE_HEIGHT: closed there too
    before = _value_state(st)
    res = st.apply_blob(_mint_blob(MINT), "ndoEve", "tx0")
    assert res == "skip shielded_transfer: the legacy shielded pool is closed (LEGACY_TRANSFER_CLOSE_HEIGHT)", res
    assert _value_state(st) == before, f"a refused mint moved value: {before} -> {_value_state(st)}"


def t2():
    """At every cursor (genesis included) a mint blob, small or large, leaves every value record and the root alone."""
    for cursor in (-1, 0, 13998, 13999, 10 ** 6):
        st = _fresh()
        st.cursor = cursor
        before = _value_state(st)
        st.apply_blob(_mint_blob(1), "ndoEve", "tx1")
        st.apply_blob(_mint_blob(MINT), "ndoEve", "tx2")
        assert _value_state(st) == before, f"cursor {cursor}: value moved on a refused mint: {before} -> {_value_state(st)}"


def t5():
    """REGRESSION GUARD: the escrow-driven field deposit is unaffected — from block 1 it lands in the Stwo pool, with the
    note's value taken from the on-chain amount. (The field-path mint check, t3, and the legacy deposit, t4, went with the
    field pool and ExecState.apply_shield in G9 slice 5; the legacy pool takes no deposit at any height.)"""
    st = _fresh()
    st.cursor = 5000                                    # a gen-29 height, past every gate
    res = st.apply_field_shield(4321, "ab" * 32, 0x2222)
    assert "stwo note" in res, f"legitimate field-shield deposit was wrongly rejected: {res!r}"
    assert len(st.stwo_pool.commitments) == 1 and st.pool_value == 4321, "legitimate field deposit did not append its note"


for name, fn in [("transparent mint (public_value > 0) is skipped as the closed legacy op", t1),
                 ("a refused mint moves no value at any cursor", t2),
                 ("legitimate field-shield deposit still works", t5)]:
    check(name, fn)

print("ALL PASSED" if not _report.fails else f"{_report.fails} FAILED")
sys.exit(1 if _report.fails else 0)
