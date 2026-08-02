"""
Offline lifecycle test of the Lend contract (execnode/games/lend.py) on a fresh ExecState — the same
apply_blob path the live exec node runs.

This contract holds other people's escrowed money in four different states, so the tests that matter are
not the happy paths — they are the ones that prove money can always get OUT. Two fund-lock classes have
bitten this codebase before (a privileged-only escape hatch, and pin-now/resolve-later with no horizon
refund), and the sweep below asserts their absence structurally: for EVERY terminal state, the party
entitled to the money extracts it with their own transaction, and the contract's balance returns to zero.

It also checks CONSERVATION — that the contract never pays out more than it took in — because a lending
contract that can overpay by one unit is a contract that drains, and no individual lifecycle test would
notice.

Run: python3 tests/lend_contract_test.py
"""
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode.games import lend as L

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


LENDER = "ndoLLLL" + "L" * 41
BORROW = "ndoBBBB" + "B" * 41
STRANGER = "ndoSSSS" + "S" * 41

U = L.UNIT
T0 = 1_000_000            # base wall-clock for the sim
FUND = 100_000 * U


def _fresh():
    st = ExecState(os.path.join(tempfile.mkdtemp(prefix="nado_lend_"), "s.json"))
    st.cursor = 100
    st.block_ts = T0
    code = L.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": L.ABI, "nonce": "n"}, LENDER, "d")
    cid = st.contract_id(LENDER, code, "n")
    for who in (LENDER, BORROW, STRANGER):
        st.credit_deposit(who, FUND)
    rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
    nonce = [0]

    def call(who, method, args, value=0):
        nonce[0] += 1
        blob = {"op": "call", "contract": cid, "method": method, "args": args}
        if value:
            blob["value"] = value
        return st.apply_blob(blob, who, f"n{nonce[0]}")
    return st, cid, rd, call


def _ok(res):
    """apply_blob returns a string; a revert is reported rather than raised."""
    s = str(res)
    assert not s.startswith("skip:") and "revert" not in s.lower(), f"call failed: {s}"
    return res


def _reverts(res):
    s = str(res)
    assert s.startswith("skip:") or "revert" in s.lower(), f"expected a revert, got: {s}"


def bal(st, who):
    return int(st.bridge.get(who, 0))


# terms used throughout: lend 100 units, want 20 interest, require 150 collateral, 7 days
LOAN, PRIN, INT, COLL, DUR = 7, 100, 20, 150, 7 * 86400


def _offered():
    st, cid, rd, call = _fresh()
    _ok(call(LENDER, "offer", [LOAN, PRIN, INT, COLL, DUR], PRIN * U))
    return st, cid, rd, call


def _taken():
    st, cid, rd, call = _offered()
    _ok(call(BORROW, "take", [LOAN], COLL * U))
    return st, cid, rd, call


# ---- happy paths -------------------------------------------------------------------------------------
def t_offer_escrows_and_records_terms():
    st, cid, rd, call = _offered()
    assert rd(L.ST, LOAN) == L.ST_OPEN, rd(L.ST, LOAN)
    assert rd(L.PR, LOAN) == PRIN and rd(L.IT, LOAN) == INT and rd(L.CO, LOAN) == COLL
    assert bal(st, cid) == PRIN * U, "the principal must be escrowed at offer time, not promised"
    assert bal(st, LENDER) == FUND - PRIN * U


def t_take_pays_the_principal_out():
    st, cid, rd, call = _taken()
    assert rd(L.ST, LOAN) == L.ST_TAKEN
    assert rd(L.DL, LOAN) == T0 + DUR, "due time must be now + duration"
    # borrower is up the principal and down the collateral; contract holds only the collateral
    assert bal(st, BORROW) == FUND + PRIN * U - COLL * U
    assert bal(st, cid) == COLL * U, "after take the contract holds exactly the collateral"


def t_repay_settles_both_sides():
    st, cid, rd, call = _taken()
    st.block_ts = T0 + DUR - 1                       # just inside the deadline
    _ok(call(BORROW, "repay", [LOAN], (PRIN + INT) * U))
    assert rd(L.ST, LOAN) == L.ST_REPAID
    assert rd(L.LC, LOAN) == PRIN + INT, "lender is owed principal + interest"
    assert rd(L.BC, LOAN) == COLL, "borrower is owed the collateral back"
    _ok(call(LENDER, "claim", [LOAN]))
    _ok(call(BORROW, "claim", [LOAN]))
    assert bal(st, LENDER) == FUND + INT * U, "lender ends up ahead by exactly the interest"
    assert bal(st, BORROW) == FUND - INT * U, "borrower ends up down by exactly the interest"
    assert bal(st, cid) == 0, "contract must be empty once both sides have claimed"


def t_cancel_refunds_the_lender():
    st, cid, rd, call = _offered()
    _ok(call(LENDER, "cancel", [LOAN]))
    assert rd(L.ST, LOAN) == L.ST_CANCELLED
    _ok(call(LENDER, "claim", [LOAN]))
    assert bal(st, LENDER) == FUND, "a cancelled offer refunds the principal in full"
    assert bal(st, cid) == 0


def t_default_gives_the_lender_the_collateral():
    st, cid, rd, call = _taken()
    st.block_ts = T0 + DUR                            # exactly at the deadline: the lender's claim vests
    _ok(call(STRANGER, "default", [LOAN]))            # permissionless
    assert rd(L.ST, LOAN) == L.ST_DEFAULT
    _ok(call(LENDER, "claim", [LOAN]))
    assert bal(st, LENDER) == FUND - PRIN * U + COLL * U, "lender recovers the collateral"
    assert bal(st, BORROW) == FUND + PRIN * U - COLL * U, "borrower keeps the principal, loses collateral"
    assert bal(st, cid) == 0
    assert bal(st, STRANGER) == FUND, "the caller of default() gains nothing"


# ---- terms enforcement -------------------------------------------------------------------------------
def t_declared_principal_must_equal_escrow():
    """An offer advertising 100 while escrowing 1 would let a borrower post collateral against nothing."""
    st, cid, rd, call = _fresh()
    _reverts(call(LENDER, "offer", [LOAN, 100, INT, COLL, DUR], 1 * U))


def t_collateral_must_exceed_principal():
    """Otherwise walking away is free and the lender is guaranteed to eat the loss."""
    st, cid, rd, call = _fresh()
    _reverts(call(LENDER, "offer", [LOAN, 100, INT, 100, DUR], 100 * U))
    _reverts(call(LENDER, "offer", [LOAN, 100, INT, 99, DUR], 100 * U))


def t_take_requires_exact_collateral():
    for wrong in (COLL - 1, COLL + 1):
        st, cid, rd, call = _offered()
        _reverts(call(BORROW, "take", [LOAN], wrong * U))
        assert rd(L.ST, LOAN) == L.ST_OPEN, "a rejected take must leave the offer open"


def t_lender_cannot_take_own_offer():
    st, cid, rd, call = _offered()
    _reverts(call(LENDER, "take", [LOAN], COLL * U))


def t_repay_requires_exact_amount_and_the_borrower():
    st, cid, rd, call = _taken()
    _reverts(call(BORROW, "repay", [LOAN], PRIN * U))                 # forgot the interest
    _reverts(call(BORROW, "repay", [LOAN], (PRIN + INT + 1) * U))     # overpaid
    _reverts(call(STRANGER, "repay", [LOAN], (PRIN + INT) * U))       # not the borrower


def t_repay_after_the_deadline_is_refused():
    st, cid, rd, call = _taken()
    st.block_ts = T0 + DUR                                            # deadline reached
    _reverts(call(BORROW, "repay", [LOAN], (PRIN + INT) * U))


def t_default_before_the_deadline_is_refused():
    st, cid, rd, call = _taken()
    st.block_ts = T0 + DUR - 1
    _reverts(call(STRANGER, "default", [LOAN]))


def t_cancel_only_open_and_only_lender():
    st, cid, rd, call = _offered()
    _reverts(call(STRANGER, "cancel", [LOAN]))
    st2, cid2, rd2, call2 = _taken()
    _reverts(call2(LENDER, "cancel", [LOAN]))                         # already taken


def t_stranger_cannot_claim():
    st, cid, rd, call = _taken()
    st.block_ts = T0 + DUR
    _ok(call(STRANGER, "default", [LOAN]))
    _reverts(call(STRANGER, "claim", [LOAN]))
    assert bal(st, STRANGER) == FUND


def t_double_claim_pays_once():
    st, cid, rd, call = _offered()
    _ok(call(LENDER, "cancel", [LOAN]))
    _ok(call(LENDER, "claim", [LOAN]))
    after = bal(st, LENDER)
    _reverts(call(LENDER, "claim", [LOAN]))                           # bucket is empty -> revert, not 0-pay
    assert bal(st, LENDER) == after, "a second claim must not move money"


def t_duplicate_loan_id_refused():
    st, cid, rd, call = _offered()
    _reverts(call(STRANGER, "offer", [LOAN, PRIN, INT, COLL, DUR], PRIN * U))


# ---- the properties this contract is actually about --------------------------------------------------
def t_no_terminal_state_strands_money():
    """FUND-LOCK SWEEP. For every way a loan can end, the entitled party extracts their money with their
    OWN transaction and the contract returns to zero. Nothing waits on a creator, a host, or a
    counterparty who may have walked away."""
    # 1. cancelled by the lender
    st, cid, rd, call = _offered()
    _ok(call(LENDER, "cancel", [LOAN])); _ok(call(LENDER, "claim", [LOAN]))
    assert bal(st, cid) == 0, "cancelled loan stranded money"

    # 2. repaid on time
    st, cid, rd, call = _taken()
    st.block_ts = T0 + 1
    _ok(call(BORROW, "repay", [LOAN], (PRIN + INT) * U))
    _ok(call(LENDER, "claim", [LOAN])); _ok(call(BORROW, "claim", [LOAN]))
    assert bal(st, cid) == 0, "repaid loan stranded money"

    # 3. defaulted, and the LENDER has vanished — a stranger can still resolve the state, and the money
    #    remains claimable by the lender forever rather than being frozen by their absence.
    st, cid, rd, call = _taken()
    st.block_ts = T0 + DUR + 10 * 86400
    _ok(call(STRANGER, "default", [LOAN]))
    assert rd(L.LC, LOAN) == COLL, "a third party must be able to resolve an expired loan"
    _ok(call(LENDER, "claim", [LOAN]))
    assert bal(st, cid) == 0, "defaulted loan stranded money"

    # 4. defaulted very late — no horizon exists past which the claim expires (the pin-now/resolve-later
    #    class). Ten years on, the collateral is still claimable.
    st, cid, rd, call = _taken()
    st.block_ts = T0 + DUR + 3650 * 86400
    _ok(call(STRANGER, "default", [LOAN]))
    _ok(call(LENDER, "claim", [LOAN]))
    assert bal(st, cid) == 0, "a very old loan stranded money"


def t_contract_never_pays_out_more_than_it_took_in():
    """CONSERVATION across every path. Sum of participant balances is invariant, and the contract's own
    balance never goes negative — a lending contract that can overpay by one unit drains."""
    for name, drive in (
        ("repay", lambda st, call: (setattr(st, "block_ts", T0 + 1),
                                    call(BORROW, "repay", [LOAN], (PRIN + INT) * U),
                                    call(LENDER, "claim", [LOAN]), call(BORROW, "claim", [LOAN]))),
        ("default", lambda st, call: (setattr(st, "block_ts", T0 + DUR),
                                      call(STRANGER, "default", [LOAN]),
                                      call(LENDER, "claim", [LOAN]))),
    ):
        st, cid, rd, call = _taken()
        before = bal(st, LENDER) + bal(st, BORROW) + bal(st, STRANGER) + bal(st, cid)
        drive(st, call)
        after = bal(st, LENDER) + bal(st, BORROW) + bal(st, STRANGER) + bal(st, cid)
        assert before == after, f"{name}: money was minted or burned ({before} -> {after})"
        assert bal(st, cid) >= 0, f"{name}: contract balance went negative"


def t_views_agree_with_storage():
    st, cid, rd, call = _taken()
    st.block_ts = T0 + DUR
    _ok(call(STRANGER, "default", [LOAN]))
    assert rd(L.ST, LOAN) == L.ST_DEFAULT
    assert rd(L.DL, LOAN) == T0 + DUR
    assert rd(L.LC, LOAN) == COLL


if __name__ == "__main__":
    check("offer escrows the principal and records the terms", t_offer_escrows_and_records_terms)
    check("take pays the principal out and holds the collateral", t_take_pays_the_principal_out)
    check("repay settles both sides exactly", t_repay_settles_both_sides)
    check("cancel refunds the lender in full", t_cancel_refunds_the_lender)
    check("default hands the collateral to the lender", t_default_gives_the_lender_the_collateral)
    check("declared principal must equal the escrow", t_declared_principal_must_equal_escrow)
    check("collateral must exceed principal", t_collateral_must_exceed_principal)
    check("take requires the exact collateral", t_take_requires_exact_collateral)
    check("a lender cannot take their own offer", t_lender_cannot_take_own_offer)
    check("repay requires the exact amount, from the borrower", t_repay_requires_exact_amount_and_the_borrower)
    check("repay after the deadline is refused", t_repay_after_the_deadline_is_refused)
    check("default before the deadline is refused", t_default_before_the_deadline_is_refused)
    check("cancel is lender-only and open-only", t_cancel_only_open_and_only_lender)
    check("a stranger cannot claim", t_stranger_cannot_claim)
    check("a second claim moves no money", t_double_claim_pays_once)
    check("a duplicate loan id is refused", t_duplicate_loan_id_refused)
    check("NO TERMINAL STATE STRANDS MONEY", t_no_terminal_state_strands_money)
    check("the contract never pays out more than it took in", t_contract_never_pays_out_more_than_it_took_in)
    check("views agree with storage", t_views_agree_with_storage)
    print()
    print("ALL PASS — every escrow state has a live exit for the party owed"
          if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
