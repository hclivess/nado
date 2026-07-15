"""
TX LANDING WINDOW (max_block is an EXPIRY DEADLINE, not a target). Guards the "Target block too low" flood
fix: a FLEXIBLY-landing tx (value transfer / blob / bridge / dividend_withdraw) may be mined in ANY block in
[min_block, max_block], so wallets/CLI/auto-txs aim max_block generously (TX_TARGET_MARGIN) and it no longer
expires + re-gossip-floods before inclusion; a TIMING-CRITICAL tx (bond/register/attest/settle/governance)
still lands at exactly max_block. Also pins the mempool gate to TX_LANDING_WINDOW and confirms dividend_withdraw
was moved into the flexibly-landing class (proof-gated, at-most-once, no landing-timing invariant).

(Run: python3 tests/test_tx_landing_window.py — pure logic, no node, fast.)
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from protocol import TX_TARGET_MARGIN, TX_LANDING_WINDOW
from ops.block_ops import _lands_flexibly, check_target_match, match_transactions_target
import logging
_LOG = logging.getLogger("t"); _LOG.addHandler(logging.NullHandler())

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def _tx(recipient, max_block, min_block=0, txid=None):
    return {"recipient": recipient, "max_block": max_block, "min_block": min_block,
            "txid": txid or f"{recipient}:{max_block}:{min_block}"}


FLEX = ["ndoabc123", "blob", "bridge", "bridge_withdraw", "dividend_withdraw"]
EXACT = ["bond", "unbond", "withdraw", "register", "msgkey", "attest", "commit", "reveal", "duty",
         "settle", "alias", "htlc_lock"]


def t_classification():
    for r in FLEX:
        assert _lands_flexibly(_tx(r, 100)), f"{r} must be flexibly-landing"
    for r in EXACT:
        assert not _lands_flexibly(_tx(r, 100)), f"{r} must be exact-landing"


def t_dividend_withdraw_now_flexible():
    """The fix moved dividend_withdraw (proof-gated, at-most-once) out of exact-landing."""
    assert _lands_flexibly(_tx("dividend_withdraw", 100))


def t_flex_lands_anywhere_in_window():
    """A flexibly-landing tx targeting tip + TX_TARGET_MARGIN is includable at every height in its window,
    NOT only at max_block — the whole point of a generous deadline."""
    tip = 1000
    mx = tip + TX_TARGET_MARGIN
    tx = _tx("ndoabc", mx, min_block=tip + 2)
    included = [n for n in range(tip, mx + 3)
                if match_transactions_target([tx], n, _LOG) == [tx]]
    # eligible exactly across [min_block, max_block]
    assert included[0] == tip + 2 and included[-1] == mx, included
    assert len(included) == mx - (tip + 2) + 1, "must be includable at EVERY height in the window"
    # verifier agrees at an interior height (not just the deadline)
    assert check_target_match([tx], tip + 50, _LOG)
    assert not check_target_match([tx], mx + 1, _LOG), "past the deadline is invalid"
    assert not check_target_match([tx], tip + 1, _LOG), "before min_block is invalid"


def t_exact_lands_only_at_max_block():
    """A timing-critical tx must still land at EXACTLY max_block (widening its margin would only move the
    single target, so those keep small margins)."""
    tip, mx = 1000, 1006
    tx = _tx("bond", mx)
    assert match_transactions_target([tx], mx, _LOG) == [tx]
    for n in (mx - 1, mx + 1, tip):
        assert match_transactions_target([tx], n, _LOG) == [], f"bond must not land at {n}"
    assert check_target_match([tx], mx, _LOG)
    assert not check_target_match([tx], mx - 1, _LOG)


def t_window_is_generous():
    """The generous margin must give a real multi-block window yet stay safely inside the mempool cap."""
    assert TX_TARGET_MARGIN >= 60, "margin should be generous (>= ~6 min at 6s blocks)"
    assert TX_TARGET_MARGIN < TX_LANDING_WINDOW, "margin must fit under the admission window with headroom"
    assert TX_LANDING_WINDOW - TX_TARGET_MARGIN >= 30, "leave headroom for peers slightly ahead at admission"


if __name__ == "__main__":
    check("flexibly-landing vs exact-landing classification", t_classification)
    check("dividend_withdraw is now flexibly-landing", t_dividend_withdraw_now_flexible)
    check("flexibly-landing tx includable at EVERY height in [min,max]", t_flex_lands_anywhere_in_window)
    check("timing-critical tx lands only at exactly max_block", t_exact_lands_only_at_max_block)
    check("margin is generous and fits under the landing window", t_window_is_generous)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
