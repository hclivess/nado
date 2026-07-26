"""
Fund-lock regression test — the two permanent-lock scenarios found in the game contracts, driven on a
fresh ExecState through the same apply_blob path the live exec node runs.

Both are "the one address allowed to unlock this walked away" bugs:

  F1  holdem.reclaim(t) was gated on `caller == host`. reclaim is the ONLY exit when the showdown window
      lapses with nobody revealed (settle requires tb != 0, reclaim requires tb == 0 — disjoint). Host
      goes dark => every seat's stack AND the pot are unrecoverable forever.

  F2  hexholm.cancel(g) is gated on `caller == creator`, and it is the only exit from a lobby that never
      fills: leave(g) pops the LAST joiner only, abort(g) is _FULL-gated. Creator + last joiner both go
      dark => the middle seats' stakes are unrecoverable forever.

Run: python3 tests/fund_lock_test.py
"""
import os, sys, tempfile, traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.state import ExecState
from execnode.games import holdem as hd
from execnode.games import hexholm as hx

fails = 0


def check(name, fn):
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


A = "ndoAAAA" + "A" * 41          # host / creator — walks away in both scenarios
B = "ndoBBBB" + "B" * 41          # the victim: seated, funded, no way out
C = "ndoCCCC" + "C" * 41
D = "ndoDDDD" + "D" * 41
START_BAL = 1_000_000


def _deploy(mod, cursor):
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json")); st.cursor = cursor
    code = mod.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": mod.ABI, "nonce": "n"}, A, "d")
    cid = st.contract_id(A, code, "n")
    for who in (A, B, C, D):
        st.credit_deposit(who, START_BAL)
    rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
    n = [0]

    def call(who, method, args, value=0):
        n[0] += 1
        return st.apply_blob(
            {"op": "call", "contract": cid, "method": method, "args": args,
             **({"value": value} if value else {})}, who, f"n{n[0]}")
    return st, cid, rd, call


# ---------------------------------------------------------------------------------------------------
# F1 — hold'em: the showdown window lapses with nobody revealed and the host is gone.
# ---------------------------------------------------------------------------------------------------
def t_holdem_reclaim_without_host():
    st, cid, rd, call = _deploy(hd, 100)
    T, GA_, GB_ = 1, 11, 12
    ANTE, BUYIN = 100, 1000
    call(A, "open", [T, GA_, 0xAAAA, ANTE], BUYIN)
    call(B, "join", [T, GB_, 0xBBBB], BUYIN)
    assert rd(hd.TN, T) == 2, "two seats"
    assert rd(hd.TP, T) == 2 * ANTE, f"pot = both antes, got {rd(hd.TP, T)}"
    call(A, "start", [T])
    td = rd(hd.TD, T)
    assert td == 102, f"td = cursor+2, got {td}"

    escrowed = st.bridge[cid]
    assert escrowed == 2 * BUYIN, f"contract holds both buy-ins, got {escrowed}"

    # timeline: b0 = td+F0, then four unforced streets at +S each -> c4 = td+F0+4S
    c4 = td + hd.F0 + 4 * hd.S
    st.cursor = c4 + hd.R + 1                      # showdown window fully lapsed
    assert rd(hd.TB, T) == 0, "nobody revealed"

    # settle cannot help: it requires tb != 0.
    call(B, "settle", [T])
    assert rd(hd.TZ, T) == 0 and st.bridge[cid] == escrowed, "settle must be a no-op with tb == 0"

    # THE LOCK: the host is gone; a seated player must still be able to unwind the table.
    call(B, "reclaim", [T])
    assert rd(hd.TZ, T) == 1, "non-host reclaim must settle the table (F1)"
    assert st.bridge.get(cid, 0) == 0, f"contract must be drained, {st.bridge.get(cid, 0)} left (F1)"

    # the hand was never shown, so every seat is made whole — nobody wins, nobody loses.
    assert st.bridge[A] == START_BAL, f"A got {st.bridge[A]}"
    assert st.bridge[B] == START_BAL, f"B got {st.bridge[B]}"


def t_holdem_reclaim_refunds_unequal_bets():
    """The void-hand refund must follow CONTRIBUTION, not seat count — a big bettor gets their bets back."""
    st, cid, rd, call = _deploy(hd, 100)
    T, GA_, GB_, GC_ = 1, 11, 12, 13
    ANTE, BUYIN = 100, 1000
    call(A, "open", [T, GA_, 0xAAAA, ANTE], BUYIN)
    call(B, "join", [T, GB_, 0xBBBB], BUYIN)
    call(C, "join", [T, GC_, 0xCCCC], BUYIN)
    call(A, "start", [T])
    td = rd(hd.TD, T)
    st.cursor = td + hd.F0                         # first betting street is open
    call(A, "bet", [GA_, 300])
    call(B, "bet", [GB_, 300])
    call(C, "bet", [GC_, 50])                      # C is short and never covers
    pot = rd(hd.TP, T)
    assert pot == 3 * ANTE + 650, f"pot tracks every contribution, got {pot}"
    assert st.bridge[cid] == 3 * BUYIN, "escrow is still the three buy-ins"

    st.cursor = td + hd.F0 + 4 * hd.S + hd.R + 1
    assert rd(hd.TB, T) == 0, "nobody revealed"
    call(C, "reclaim", [T])
    assert rd(hd.TZ, T) == 1 and rd(hd.TP, T) == 0
    assert st.bridge.get(cid, 0) == 0, f"pot drains exactly, {st.bridge.get(cid, 0)} left"
    for who in (A, B, C):
        assert st.bridge[who] == START_BAL, f"{who[:7]} made whole, got {st.bridge[who]}"


def t_holdem_reclaim_gates_still_hold():
    """Opening reclaim to everyone must not open it EARLY, twice, or when someone revealed."""
    st, cid, rd, call = _deploy(hd, 100)
    T, GA_, GB_ = 1, 11, 12
    call(A, "open", [T, GA_, 0xAAAA, 100], 1000)
    call(B, "join", [T, GB_, 0xBBBB], 1000)
    call(A, "start", [T])
    td = rd(hd.TD, T)
    c4 = td + hd.F0 + 4 * hd.S

    st.cursor = c4 + hd.R - 1                      # window not yet closed (opens AT c4+R, as settle does)
    call(C, "reclaim", [T])
    assert rd(hd.TZ, T) == 0, "reclaim before the window must revert"
    assert st.bridge[cid] == 2000, "escrow untouched"

    st.cursor = c4 + hd.R
    call(C, "reclaim", [T])                        # a non-seat may unwind an abandoned table
    assert rd(hd.TZ, T) == 1, "reclaim after the window succeeds"
    assert st.bridge.get(cid, 0) == 0
    assert st.bridge[C] == START_BAL, "the caller gets nothing for calling"

    before = dict(st.bridge)
    call(B, "reclaim", [T])                        # double reclaim
    assert st.bridge == before, "second reclaim must be a no-op (tz already 1)"


def t_holdem_reclaim_blocked_when_revealed():
    st, cid, rd, call = _deploy(hd, 100)
    T, GA_, GB_ = 1, 11, 12
    call(A, "open", [T, GA_, 0xAAAA, 100], 1000)
    call(B, "join", [T, GB_, 0xBBBB], 1000)
    call(A, "start", [T])
    st.contracts[cid]["storage"]["slots"][str(hd.TB * (1 << 32) + T)] = 1   # someone showed
    td = rd(hd.TD, T)
    st.cursor = td + hd.F0 + 4 * hd.S + hd.R + 1
    call(B, "reclaim", [T])
    assert rd(hd.TZ, T) == 0, "reclaim must stay closed once a hand is revealed — settle owns that path"


# ---------------------------------------------------------------------------------------------------
# F2 — hexholm: a lobby that never fills, creator and last joiner both gone.
# ---------------------------------------------------------------------------------------------------
def t_hexholm_stuck_lobby():
    st, cid, rd, call = _deploy(hx, 100)
    G, STAKE = 777, 500
    call(A, "open", [G, 4, 111], STAKE)            # cap 4
    call(B, "join", [G, 222], STAKE)
    call(C, "join", [G, 333], STAKE)
    assert rd(hx.NN, G) == 3 and rd(hx.CAP, G) == 4, "3 of 4 seated"
    assert st.bridge[cid] == 3 * STAKE

    # B is trapped: not the last joiner, not the creator, table never filled.
    call(B, "leave", [G])
    assert rd(hx.NN, G) == 3, "leave only pops the last joiner"
    call(B, "abort", [G])
    assert rd(hx.SD, G) == 0, "abort is FULL-gated"

    # the lobby deadline must exist even while the table is unfilled (F2)
    dl = rd(hx.DL, G)
    assert dl == 100 + hx.MOVE_CLOCK, f"join must stamp the lobby deadline, got {dl} (F2)"

    call(B, "cancel", [G])
    assert rd(hx.SD, G) == 0, "before the deadline only the creator may cancel"
    assert st.bridge[cid] == 3 * STAKE

    st.cursor = dl + 1
    call(B, "cancel", [G])
    assert rd(hx.SD, G) == 1, "after the deadline any caller may dissolve the dead lobby (F2)"
    assert st.bridge.get(cid, 0) == 0, f"contract must be drained, {st.bridge.get(cid, 0)} left (F2)"
    for who in (A, B, C):
        assert st.bridge[who] == START_BAL, f"{who[:7]} refunded in full, got {st.bridge[who]}"
    assert st.bridge[D] == START_BAL


def t_hexholm_creator_cancel_still_immediate():
    """The creator keeps the immediate exit — the deadline only ADDS a permissionless path."""
    st, cid, rd, call = _deploy(hx, 100)
    G, STAKE = 778, 500
    call(A, "open", [G, 3, 111], STAKE)
    call(B, "join", [G, 222], STAKE)
    call(A, "cancel", [G])                         # well before the deadline
    assert rd(hx.SD, G) == 1 and rd(hx.WR, G) == 5
    assert st.bridge.get(cid, 0) == 0
    assert st.bridge[A] == START_BAL and st.bridge[B] == START_BAL


def t_hexholm_cancel_still_blocked_on_full_table():
    """A FULL table must never be cancellable — the move clock / abort path owns it."""
    st, cid, rd, call = _deploy(hx, 100)
    G, STAKE = 779, 500
    call(A, "open", [G, 2, 111], STAKE)
    call(B, "join", [G, 222], STAKE)
    assert rd(hx.NN, G) == 2 and rd(hx.KH, G) == 102, "table full, kh pinned"
    assert rd(hx.DL, G) == 100 + hx.MOVE_CLOCK, "the filling join sets the move clock"
    st.cursor = 100 + hx.MOVE_CLOCK + 1
    call(A, "cancel", [G])
    assert rd(hx.SD, G) == 0, "creator cancel is nn < cap only"
    call(C, "cancel", [G])
    assert rd(hx.SD, G) == 0, "and so is the deadline path"
    assert st.bridge[cid] == 2 * STAKE
    call(B, "abort", [G])                          # the correct exit for a full, stalled table
    assert rd(hx.SD, G) == 1 and st.bridge.get(cid, 0) == 0


def t_hexholm_move_clock_unaffected():
    """DL on an unfilled lobby must not shorten or lengthen the in-game move clock."""
    st, cid, rd, call = _deploy(hx, 100)
    G, STAKE = 780, 500
    call(A, "open", [G, 2, 111], STAKE)
    st.cursor = 500
    call(B, "join", [G, 222], STAKE)
    assert rd(hx.DL, G) == 500 + hx.MOVE_CLOCK, "clock starts at the filling join, not at open"
    st.cursor = 600
    call(A, "move", [G, 5, 0])
    assert rd(hx.DL, G) == 600 + hx.MOVE_CLOCK, "each move refreshes the clock"


if __name__ == "__main__":
    check("holdem: reclaim works without the host (F1)", t_holdem_reclaim_without_host)
    check("holdem: void-hand refund follows contribution", t_holdem_reclaim_refunds_unequal_bets)
    check("holdem: reclaim gates still hold", t_holdem_reclaim_gates_still_hold)
    check("holdem: reclaim blocked once revealed", t_holdem_reclaim_blocked_when_revealed)
    check("hexholm: stuck lobby is escapable (F2)", t_hexholm_stuck_lobby)
    check("hexholm: creator cancel still immediate", t_hexholm_creator_cancel_still_immediate)
    check("hexholm: cancel still blocked on a full table", t_hexholm_cancel_still_blocked_on_full_table)
    check("hexholm: move clock unaffected", t_hexholm_move_clock_unaffected)
    print("FAILURES:", fails)
    sys.exit(1 if fails else 0)
