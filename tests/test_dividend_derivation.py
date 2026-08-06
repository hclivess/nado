"""The presence-dividend accrual must be DERIVABLE from committed L1 state.

WHY THIS IS THE BIGGEST ONE. Measured over a full day on alphanet-15, "span crosses a dividend epoch
boundary" was 55 of 146 settle refusals — the single largest class, larger than "the RECORDS half moved"
(36). It is also the only records movement with NO transaction behind it: the exec node's tail loop calls
state.accrue_dividend_epoch once per EPOCH_LENGTH blocks, writing st.dividend, which no per-block body scan
can ever see. So L1 refused the span outright rather than binding it.

IT WAS ALWAYS DERIVABLE. The accrual is a pure function of two COMMITTED L1 values — dividend_inflow_get(E)
and weights_at_epoch(E) — which is exactly what the exec node fetches over HTTP before accruing. The one
input that is not on L1 is the carried sub-unit remainder, so the derivation chains it itself: each
boundary block stores its carry-out in its own exec summary and reads the previous boundary's as carry-in.

THE CARRY LIVES IN THE SUMMARY ON PURPOSE. exec_summary_put already commits inside incorporate_block's
atomic write txn and rollback_one_block already reverts it, so the chain inherits an EXACT rollback
inverse. A separate accumulator row would have needed its own — and "rollback_one_block is not the inverse
of incorporate_block for a meta row" is precisely what corrupted the L1 state root at h4260.

Run: python3 tests/test_dividend_derivation.py
"""
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from execnode.stark.records_bind import epoch_accrual_due, dividend_accrual_effects
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


def t_attribution_matches_the_tail_loop():
    """The exec node accrues epoch E when its cursor first reaches epoch E+1, i.e. at block (E+1)*L.
    VERIFIED AGAINST A LIVE ACCRUAL: "dividend epoch 760" was logged as the cursor passed 45660 = 761*60.
    An off-by-one here refuses every honest boundary span instead of binding it."""
    assert epoch_accrual_due(45660, 60) == 760, "the live 45660 -> epoch 760 attribution must hold"
    assert epoch_accrual_due(60, 60) == 0, "the first boundary accrues epoch 0"
    assert epoch_accrual_due(120, 60) == 1
    for h in (45659, 45661, 1, 59, 61):
        assert epoch_accrual_due(h, 60) is None, f"{h} is not a boundary and must accrue nothing"
    assert epoch_accrual_due(0, 60) is None, "genesis accrues nothing (there is no epoch -1)"


def t_mirrors_the_accrual_arithmetic():
    """Line for line against state._accrue_dividend_epoch_inner: integer-only, sorted(weights.items()),
    max(1, w) flooring, the pot carrying the previous remainder."""
    eff, carry = dividend_accrual_effects(100, {"a": 1, "b": 3}, 0)
    assert eff == [(ER.T_DIV_BAL, ("a",), 25), (ER.T_DIV_BAL, ("b",), 75)], eff
    assert carry == 0, carry
    # a pot that does not divide evenly leaves the remainder as carry, losing nothing
    eff, carry = dividend_accrual_effects(10, {"a": 1, "b": 1, "c": 1}, 0)
    assert sum(d for _t, _p, d in eff) + carry == 10, "raw must be conserved: distributed + carry == pot"
    assert carry == 1, carry


def t_carry_chains_across_epochs():
    """Epoch E's leftover is epoch E+1's pot — the property that makes a multi-epoch span derivable."""
    _e1, c1 = dividend_accrual_effects(10, {"a": 1, "b": 1, "c": 1}, 0)
    e2, c2 = dividend_accrual_effects(0, {"a": 1}, c1)
    assert c1 == 1
    assert sum(d for _t, _p, d in e2) == 1 and c2 == 0, "the carried remainder must be distributed later"


def t_no_present_set_carries_everything_forward():
    """No weights -> the whole inflow carries; no raw is lost or minted."""
    eff, carry = dividend_accrual_effects(500, {}, 7)
    assert eff == [] and carry == 507, (eff, carry)


def t_zero_weight_is_floored_to_one():
    """max(1, w) — a present miner with weight 0 still counts, exactly as the accrual does."""
    eff, carry = dividend_accrual_effects(2, {"a": 0, "b": 0}, 0)
    assert sum(d for _t, _p, d in eff) + carry == 2
    assert len(eff) == 2, "both zero-weight miners must receive a share"


def t_effects_are_div_bal_positions():
    eff, _ = dividend_accrual_effects(100, {"a": 1}, 0)
    assert all(t == ER.T_DIV_BAL for t, _p, _d in eff), "the accrual writes T_DIV_BAL, not T_BRIDGE_BAL"


def t_carry_is_stored_in_the_summary_not_a_new_meta_row():
    """The rollback-inverse argument. A new meta row would need its own inverse; reusing the summary means
    rollback_one_block already restores it."""
    kv = open(os.path.join(ROOT, "ops", "kv_ops.py")).read()
    assert 'doc["dc"] = int(div_carry)' in kv, "the carry must be written into the exec summary doc"
    assert "div_carry=None" in kv, "exec_summary_put must accept the carry"
    core = open(os.path.join(ROOT, "loops", "core_loop.py")).read()
    assert "div_carry=_dcarry" in core, "incorporate_block must pass the carry through"


def t_fails_closed_on_every_missing_input():
    """A missing previous summary, a refused weights_at_epoch, or any error must mark the block
    NON-derivable so it rides the bonded quorum — never emit partial effects."""
    core = open(os.path.join(ROOT, "loops", "core_loop.py")).read()
    i = core.index("def _accrual_effects")
    body = core[i:i + 2000]
    assert "return None, False, None" in body, "every failure path must return non-derivable"
    assert "except Exception" in body, "it must never raise into incorporate_block"
    assert body.count("return None, False, None") >= 2, \
        "both the missing-carry path and the error path must fail closed"


def t_l1_epoch_refusal_is_conditional_now():
    """The blanket refusal was the 55-refusal class. It must remain for a records-FROZEN proof, which pins
    one records root across the span and so would assert something false, and lift only for a bound one."""
    tx = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
    assert "if not _records_bound:" in tx, "the epoch refusal must be conditional on the records binding"
    i = tx.index("if not _records_bound:")
    assert "crosses an epoch boundary" in tx[i:i + 600], "the conditional must guard the epoch assert"


for nm, fn in [("attribution matches the tail loop", t_attribution_matches_the_tail_loop),
               ("mirrors the accrual arithmetic", t_mirrors_the_accrual_arithmetic),
               ("the carry chains across epochs", t_carry_chains_across_epochs),
               ("no present set carries everything forward", t_no_present_set_carries_everything_forward),
               ("zero weight is floored to one", t_zero_weight_is_floored_to_one),
               ("effects are T_DIV_BAL positions", t_effects_are_div_bal_positions),
               ("the carry rides the summary, not a new meta row", t_carry_is_stored_in_the_summary_not_a_new_meta_row),
               ("every missing input fails closed", t_fails_closed_on_every_missing_input),
               ("the L1 epoch refusal is conditional", t_l1_epoch_refusal_is_conditional_now)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
