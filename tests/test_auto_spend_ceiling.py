"""
No unattended path may commit more than HALF the spendable balance in one action
(core_loop.auto_spend_allowed / AUTO_SPEND_MAX_FRACTION).

WHY A HARD CEILING AND NOT A HEURISTIC. The automated paths compute their amounts from EARNINGS —
auto-bond takes a percentage of newly mined coins, auto-collect and auto-vote pay a flat fee. Every one of
those is a rounding error against any node's balance today. The ceiling is not for today: it is so that an
earnings model that is wrong, or a balance that has collapsed while a loop keeps running, cannot empty an
account with nobody watching. Halving bounds the worst single unattended mistake to something a human can
still recover from.

SCOPE: it governs OUTFLOWS (fees). Auto-bond is exempt on purpose — bonding moves coins between the
owner's own columns and returns after the unbond timelock, so it is not a spend; it is bounded by a
liquidity reserve instead. That distinction is load-bearing: applying the ceiling to auto-bond capped a
99% setting at ~50% for fresh nodes, throttling exactly the nodes trying to compound their bond.

WHAT THESE CHECKS PIN: the boundary itself (exactly half is allowed, one raw unit more is not), that it
fails CLOSED on degenerate inputs rather than dividing by zero or waving through a zero-balance account,
and that each path consults the rule that actually applies to it — a ceiling nothing calls is decoration,
and a ceiling on the wrong path is worse than none.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fails = []


def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        _fails.append(name)


def main():
    with tempfile.TemporaryDirectory() as d:
        os.environ["HOME"] = d
        os.makedirs(os.path.join(d, "nado"), exist_ok=True)
        from loops.core_loop import auto_spend_allowed, AUTO_SPEND_MAX_FRACTION

        check("the ceiling is one half", AUTO_SPEND_MAX_FRACTION == 2)

        # ---- the boundary, to the raw unit -----------------------------------------------------------
        check("exactly half is allowed", auto_spend_allowed(1000, 500))
        check("one raw unit past half is refused", not auto_spend_allowed(1000, 501))
        check("well under half is allowed", auto_spend_allowed(10 ** 12, 1000))
        check("the whole balance is refused", not auto_spend_allowed(1000, 1000))
        check("more than the balance is refused", not auto_spend_allowed(1000, 5000))

        # odd balances must not round in the spender's favour
        check("an odd balance floors (501 of 1001 refused)", not auto_spend_allowed(1001, 501))
        check("...and 500 of 1001 is allowed", auto_spend_allowed(1001, 500))

        # ---- degenerate inputs fail CLOSED -----------------------------------------------------------
        check("a zero balance spends nothing", not auto_spend_allowed(0, 1))
        check("a zero commit is not 'allowed' (nothing to do)", not auto_spend_allowed(1000, 0))
        check("a negative balance is refused", not auto_spend_allowed(-5, 1))
        check("a negative commit is refused", not auto_spend_allowed(1000, -1))
        check("a 1-raw balance cannot pay 1 raw (half of 1 is 0)", not auto_spend_allowed(1, 1))

        # ---- both spending paths must actually consult it --------------------------------------------
        import inspect
        from loops import core_loop
        src = inspect.getsource(core_loop)

        def body(name, end):
            i = src.index("def " + name)
            b = src[i:src.index("def " + end, i)]
            return "\n".join(l.split("#", 1)[0] for l in b.splitlines())

        # AUTO-BOND IS DELIBERATELY EXEMPT FROM THE CEILING. It is not an outflow — coins move between the
        # owner's own columns and return after the unbond timelock. Applying the half-rule here silently
        # capped a 99% auto-bond at ~50% for fresh nodes (whose new earnings ARE most of their balance),
        # i.e. it would have throttled exactly the nodes trying to compound their bond. It gets a LIQUIDITY
        # RESERVE instead: always leave enough behind to keep paying fees.
        bond = body("maybe_auto_bond", "maybe_auto_collect")
        check("auto-bond is NOT gated by the outflow ceiling", "auto_spend_allowed" not in bond)
        check("auto-bond keeps a liquidity reserve", "AUTO_COLLECT_MIN_RAW" in bond)
        check("auto-bond still guarantees it can pay its own fee", "MIN_TX_FEE" in bond)

        vote = body("maybe_auto_vote", "maybe_auto_register")
        check("auto-vote consults the ceiling", "auto_spend_allowed" in vote)

        # auto-register must remain fee-exempt: it is the one unattended path that costs nothing to send,
        # and it is now ON BY DEFAULT on every node, so a fee creeping in here would bill the whole fleet.
        reg = body("maybe_auto_register", "validate_transactions_in_block")
        check("auto-register still sends no fee", "fee=" not in reg and "MIN_TX_FEE" not in reg)

    print()
    print("ALL AUTO-SPEND CEILING CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
