"""RECORDS BINDING (execnode/stark/records_bind.py) — the records analogue of exec_state_bind.

records_transition proves the records half ADVANCED over a stated update set; it does not prove that set is
the one the span's transactions imply. This checks the piece that closes it: the update set is DERIVED from
committed data and the transition must prove exactly that set.

The two properties that matter are opposites, and both are tested here:

  * an honest span BINDS — the derived set equals what the real state transition produces, so a correct
    proof is accepted (if this breaks, the binding refuses honest spans and settlement silently regresses
    to quorum with nobody noticing);
  * anything else FAILS CLOSED — an effect the module cannot derive, an invented update, a dropped update,
    or a tampered value all mismatch and are refused.

The dividend check is DIFFERENTIAL against ExecState._accrue_dividend_epoch_inner rather than against
hand-computed constants. That function is the thing being mirrored; pinning constants would let the two
drift apart while the test kept passing, and the drift's symptom (honest spans refused) is invisible.

Run: python3 tests/test_records_bind.py
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.stark import records_bind as RB, records_transition as RT
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


class FakeState:
    """Duck-typed exec state — records_projection reads these plus real (empty) pools."""

    def __init__(self, bridge=None, dividend=None, div_carry=0):
        from execnode.shielded import ShieldedPool
        from execnode.shielded_field import FieldShieldedPool
        self.bridge = dict(bridge or {})
        self.dividend = dict(dividend or {})
        self.div_carry = int(div_carry)
        self.abal = {}
        self.assets = {}
        self.allow = {}
        self.withdrawals = {}
        self.dividend_withdrawals = {}
        self.unshield_withdrawals = {}
        self.shielded = ShieldedPool()
        self.field_pool = FieldShieldedPool()
        self.outbox = {}
        self.inbox = []


def pre_getter(st):
    """pre_get(tag, parts) over a FakeState — only the tags this module derives."""
    def _get(tag, parts):
        if tag == ER.T_BRIDGE_BAL:
            return int(st.bridge.get(parts[0], 0))
        if tag == ER.T_DIV_BAL:
            return int(st.dividend.get(parts[0], 0))
        raise AssertionError(f"pre_get asked for an underived tag {tag}")
    return _get


# ---- derivation ------------------------------------------------------------------------------------
def t_bridge_deposit_derives():
    eff = RB.span_effects([{"recipient": "bridge", "sender": "alice", "amount": 500}])
    assert eff == [(ER.T_BRIDGE_BAL, ("alice",), 500)], eff


def t_faucet_and_treasury_credit_the_faucet_cid():
    eff = RB.span_effects([
        {"recipient": "faucet", "sender": "donor", "amount": 70},
        {"recipient": "treasury_execute", "data": {"spend": {"recipient": "faucet", "amount": 30}}},
    ])
    assert eff == [(ER.T_BRIDGE_BAL, ("faucet",), 70), (ER.T_BRIDGE_BAL, ("faucet",), 30)], eff


def t_treasury_execute_elsewhere_moves_nothing():
    """A treasury payout to any other recipient provably leaves records untouched — it must contribute no
    effect, NOT an Unbindable, or every governance payout would block the proof path."""
    eff = RB.span_effects([{"recipient": "treasury_execute",
                            "data": {"spend": {"recipient": "somebody", "amount": 999}}}])
    assert eff == [], eff


def t_unknown_records_mover_fails_closed():
    for r in ("shield", "unshield", "xmsg", "bridge_withdraw", "dividend_withdraw"):
        try:
            RB.span_effects([{"recipient": r, "sender": "a", "amount": 1}])
        except RB.Unbindable:
            continue
        raise AssertionError(f"'{r}' moves records but was not refused")


def t_non_records_tx_contributes_nothing():
    eff = RB.span_effects([{"recipient": "ndoBob", "sender": "alice", "amount": 5},
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

    eff = RB.span_effects([], accruals=[(7, {"a": 1, "b": 1, "c": 1}),
                                        (7, {"a": 1, "b": 1, "c": 1})], div_carry=0)
    got = {}
    for (_tag, parts, delta) in eff:
        got[parts[0]] = got.get(parts[0], 0) + delta
    assert got == want, f"{got} != {want} — the carry did not chain"


# ---- net update folding ----------------------------------------------------------------------------
def t_updates_are_net_and_sorted():
    st = FakeState(bridge={"alice": 100})
    eff = RB.span_effects([{"recipient": "bridge", "sender": "alice", "amount": 10},
                           {"recipient": "bridge", "sender": "alice", "amount": 5},
                           {"recipient": "bridge", "sender": "bob", "amount": 1}])
    ups = RB.net_records_updates(pre_getter(st), eff)
    keys = [k for k, _o, _n in ups]
    assert keys == sorted(keys), "updates must be key-sorted to match records_updates"
    assert len(ups) == 2, f"alice twice is ONE net update; got {len(ups)}"
    by_key = {k: (o, n) for k, o, n in ups}
    ak = ER.record_key(ER.T_BRIDGE_BAL, "alice")
    assert by_key[ak] == (100, 115), f"alice net should be 100->115, got {by_key[ak]}"


# ---- the binding itself ----------------------------------------------------------------------------
DEPTH = ER.DEPTH
NQ = 2


def _honest_case():
    """A span with one bridge deposit, and the real records transition it implies."""
    pre = FakeState(bridge={"alice": 100, "bob": 50})
    post = FakeState(bridge={"alice": 130, "bob": 50})          # alice deposits 30
    txs = [{"recipient": "bridge", "sender": "alice", "amount": 30}]
    tr = RT.prove_records_transition(pre, post, num_queries=NQ, depth=DEPTH)
    pre_root = tuple(RT.records_store(pre, DEPTH).root())
    post_root = tuple(tr["roots"][-1])
    return pre, txs, tr, pre_root, post_root


def t_honest_span_binds():
    pre, txs, tr, pre_root, post_root = _honest_case()
    ok, why = RB.bind_and_verify_records(tr, pre_root, post_root, pre_getter(pre),
                                         RB.span_effects(txs), depth=DEPTH, num_queries=NQ)
    assert ok, why


def t_transition_moving_an_underived_record_is_refused():
    """THE property. The span says alice deposited 30; the transition also pays carol. Rejected."""
    pre = FakeState(bridge={"alice": 100})
    post = FakeState(bridge={"alice": 130, "carol": 999})       # an extra payout nothing authorises
    txs = [{"recipient": "bridge", "sender": "alice", "amount": 30}]
    tr = RT.prove_records_transition(pre, post, num_queries=NQ, depth=DEPTH)
    pre_root = tuple(RT.records_store(FakeState(bridge={"alice": 100}), DEPTH).root())
    post_root = tuple(tr["roots"][-1])
    ok, why = RB.bind_and_verify_records(tr, pre_root, post_root,
                                         pre_getter(FakeState(bridge={"alice": 100})),
                                         RB.span_effects(txs), depth=DEPTH, num_queries=NQ)
    assert not ok, "a transition crediting an unauthorised address must be refused"
    assert "do not match" in why, why


def t_wrong_amount_is_refused():
    pre, _txs, tr, pre_root, post_root = _honest_case()
    lying = [{"recipient": "bridge", "sender": "alice", "amount": 31}]   # span claims 31, proof did 30
    ok, why = RB.bind_and_verify_records(tr, pre_root, post_root, pre_getter(pre),
                                         RB.span_effects(lying), depth=DEPTH, num_queries=NQ)
    assert not ok, "a derived amount that disagrees with the proven transition must be refused"


def t_dropped_effect_is_refused():
    pre, _txs, tr, pre_root, post_root = _honest_case()
    ok, why = RB.bind_and_verify_records(tr, pre_root, post_root, pre_getter(pre),
                                         [], depth=DEPTH, num_queries=NQ)
    assert not ok, "a span deriving NO effects cannot bind a transition that moved records"


def t_unbindable_surfaces_as_refusal_not_a_crash():
    pre, _txs, tr, pre_root, post_root = _honest_case()

    def boom(_tag, _parts):
        raise RB.Unbindable("synthetic")
    ok, why = RB.bind_and_verify_records(tr, pre_root, post_root, boom,
                                         RB.span_effects([{"recipient": "bridge", "sender": "a",
                                                           "amount": 1}]), depth=DEPTH, num_queries=NQ)
    assert not ok and "underivable" in why, why


if __name__ == "__main__":
    check("bridge deposit derives to the depositor", t_bridge_deposit_derives)
    check("faucet + treasury->faucet credit the faucet cid", t_faucet_and_treasury_credit_the_faucet_cid)
    check("treasury payout elsewhere contributes no effect", t_treasury_execute_elsewhere_moves_nothing)
    check("an underived records mover FAILS CLOSED", t_unknown_records_mover_fails_closed)
    check("a non-records tx contributes nothing", t_non_records_tx_contributes_nothing)
    check("dividend derivation matches the REAL accrual", t_dividend_matches_the_real_accrual)
    check("dividend carry chains across epochs", t_dividend_carry_chains_across_epochs)
    check("net updates are folded and key-sorted", t_updates_are_net_and_sorted)
    check("an honest span BINDS", t_honest_span_binds)
    check("a transition moving an unauthorised record is REFUSED",
          t_transition_moving_an_underived_record_is_refused)
    check("a disagreeing derived amount is REFUSED", t_wrong_amount_is_refused)
    check("a dropped effect is REFUSED", t_dropped_effect_is_refused)
    check("Unbindable surfaces as a refusal, not a crash", t_unbindable_surfaces_as_refusal_not_a_crash)
    print()
    print("ALL PASS — records updates are bound to the span, not merely proven"
          if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
