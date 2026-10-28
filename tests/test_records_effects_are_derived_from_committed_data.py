"""THE RECORDS-HALF EFFECTS ARE DERIVED FROM COMMITTED DATA (execnode/records_effects.py) — what incorporate_block
commits into each exec summary (L1 `meta`, the L1 state root) as a block's records effects and a dividend epoch's
accrual.

  * every derivable effect comes out of committed block data alone, and an effect it cannot derive FAILS CLOSED (the
    block is non-derivable), never silently dropped;
  * the dividend rule is DIFFERENTIAL against ExecState._accrue_dividend_epoch_inner — the function the exec node
    applies — rather than against hand-computed constants, so the two cannot drift while the test keeps passing;
  * the records-safe blob ops are the same allowlist as calls_commit's records-inert bit.

(Moved from tests/test_records_bind.py in G9 slice 4 with the module. Its binding half — net_records_updates and
bind_and_verify_records against a Goldilocks records transition — went with execnode/stark: its only reader, the
Goldilocks settle-proof verifier, was deleted in slice 2.)

Run: python3 tests/test_records_effects_are_derived_from_committed_data.py
"""
import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode import records_effects as RB, calls_commit as CC, exec_root_b2 as ER

import _harness
_report = _harness.Report()
check = _report.run


# ---- derivation ------------------------------------------------------------------------------------
def derive(txs, accruals=(), div_carry=0):
    """A span's records effects the way PRODUCTION derives them: per block via block_records_effects (what
    incorporate_block commits beside calls_commit.block_summary), then each epoch's accrual through
    dividend_accrual_effects with the carry chained. (records_bind.span_effects, which these tests used to
    call, was deleted: nothing in production called it, and it derived value-call escrows as [] where
    block_records_effects does not — as gen 28's execnode._build_records_half did, deleted in G9.) A non-derivable block raises
    Unbindable, which is how a span that cannot be bound is refused."""
    eff, ok = RB.block_records_effects({"block_transactions": list(txs or ())})
    if not ok:
        raise RB.Unbindable("block not derivable")
    eff = list(eff)
    carry = int(div_carry)
    for inflow, weights in accruals or ():
        e, carry = RB.dividend_accrual_effects(inflow, weights, carry)
        eff.extend(e)
    return eff


def t_bridge_deposit_derives():
    eff = derive([{"recipient": "bridge", "sender": "alice", "amount": 500}])
    assert eff == [(ER.T_BRIDGE_BAL, ("alice",), 500)], eff


def t_faucet_and_treasury_credit_the_faucet_cid():
    eff = derive([
        {"recipient": "faucet", "sender": "donor", "amount": 70},
        {"recipient": "treasury_execute", "data": {"spend": {"recipient": "faucet", "amount": 30}}},
    ])
    assert eff == [(ER.T_BRIDGE_BAL, ("faucet",), 70), (ER.T_BRIDGE_BAL, ("faucet",), 30)], eff


def t_treasury_execute_elsewhere_moves_nothing():
    """A treasury payout to any other recipient provably leaves records untouched — it must contribute no
    effect, NOT an Unbindable, or every governance payout would block the proof path."""
    eff = derive([{"recipient": "treasury_execute",
                            "data": {"spend": {"recipient": "somebody", "amount": 999}}}])
    assert eff == [], eff


def t_unknown_records_mover_fails_closed():
    for r in ("shield", "unshield", "xmsg", "bridge_withdraw", "dividend_withdraw"):
        try:
            derive([{"recipient": r, "sender": "a", "amount": 1}])
        except RB.Unbindable:
            continue
        raise AssertionError(f"'{r}' moves records but was not refused")


def t_non_records_tx_contributes_nothing():
    eff = derive([{"recipient": "ndoBob", "sender": "alice", "amount": 5},
                           {"recipient": "duty", "sender": "v"}])
    assert eff == [], eff


# ---- the dividend accrual, differentially against the real implementation ---------------------------
def t_dividend_matches_the_real_accrual():
    """Mirror-check: the derived per-address deltas must equal what the exec state actually applies."""
    from execnode.state import ExecState
    for inflow, weights, carry in [
        (1000, {"a": 1, "b": 3}, 0),
        (1000, {"a": 1, "b": 3}, 7),            # carry folds into the pot
        (0, {"a": 1}, 5),                       # pot from carry alone
        (10, {}, 0),                            # no present set -> everything carries
        (0, {}, 0),                             # nothing at all
        (7, {"a": 1, "b": 1, "c": 1}, 0),       # integer division leaves a remainder
        (100, {"a": 0}, 0),                     # weight floors at max(1, w)
    ]:
        st = ExecState.__new__(ExecState)        # bypass __init__/IO — only the accrual fields are used
        st.dividend = {}
        st.div_carry = int(carry)
        st._accrue_dividend_epoch_inner(inflow, weights)
        want = {a: v for a, v in st.dividend.items() if v}
        want_carry = st.div_carry

        eff, got_carry = RB.dividend_accrual_effects(inflow, weights, carry)
        got = {}
        for (tag, parts, delta) in eff:
            assert tag == ER.T_DIV_BAL, tag
            got[parts[0]] = got.get(parts[0], 0) + delta
        assert got == want, f"inflow={inflow} weights={weights} carry={carry}: {got} != {want}"
        assert got_carry == want_carry, f"carry {got_carry} != {want_carry}"


def t_dividend_carry_chains_across_epochs():
    """Epoch E's leftover is epoch E+1's pot — a per-epoch carry would derive the wrong second pot."""
    from execnode.state import ExecState
    st = ExecState.__new__(ExecState)
    st.dividend = {}
    st.div_carry = 0
    st._accrue_dividend_epoch_inner(7, {"a": 1, "b": 1, "c": 1})   # leaves a remainder
    st._accrue_dividend_epoch_inner(7, {"a": 1, "b": 1, "c": 1})
    want = {a: v for a, v in st.dividend.items() if v}

    eff = derive([], accruals=[(7, {"a": 1, "b": 1, "c": 1}),
                                        (7, {"a": 1, "b": 1, "c": 1})], div_carry=0)
    got = {}
    for (_tag, parts, delta) in eff:
        got[parts[0]] = got.get(parts[0], 0) + delta
    assert got == want, f"{got} != {want} — the carry did not chain"


# ---- the allowlist is shared ------------------------------------------------------------------------
def t_the_records_safe_blob_ops_are_the_inert_bits_allowlist():
    """Both halves of an exec summary judge a blob op by ONE allowlist: an op records_effects treats as records-safe
    and calls_commit does not (or the reverse) would commit a summary whose inert bit and effects disagree."""
    assert RB._RECORDS_SAFE_BLOB_OPS == CC._RECORDS_SAFE_BLOB_OPS


if __name__ == "__main__":
    check("bridge deposit derives to the depositor", t_bridge_deposit_derives)
    check("faucet + treasury->faucet credit the faucet cid", t_faucet_and_treasury_credit_the_faucet_cid)
    check("treasury payout elsewhere contributes no effect", t_treasury_execute_elsewhere_moves_nothing)
    check("an underived records mover FAILS CLOSED", t_unknown_records_mover_fails_closed)
    check("a non-records tx contributes nothing", t_non_records_tx_contributes_nothing)
    check("dividend derivation matches the REAL accrual", t_dividend_matches_the_real_accrual)
    check("dividend carry chains across epochs", t_dividend_carry_chains_across_epochs)
    check("the records-safe blob ops are the inert bit's allowlist", t_the_records_safe_blob_ops_are_the_inert_bits_allowlist)
    print()
    print("ALL PASS — the records effects are derived from committed data and fail closed"
          if not _report.fails else f"{_report.fails} FAILURES")
    sys.exit(1 if _report.fails else 0)
