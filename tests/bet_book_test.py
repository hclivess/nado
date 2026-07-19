"""Bet: fixed-odds BOOK beside the tote, plus a regression on the resolution rule the book required.

The tote pays a share of the pool (unknown until betting closes); the book quotes a PRICE you can see
before you take it. Adding the book meant narrowing the auto-void — a market traded only on the book has
no tote pot to strand — so the existing tote paths are re-checked here too.
Run: HOME=/root python tests/bet_book_test.py
"""
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode.games import bet as B

BANK, A, C, R1 = "ndoBANK", "ndoAAA", "ndoCCC", "ndoRES1"
UNIT = B.UNIT
passed = failed = 0
def ok(c, m):
    global passed, failed
    if c: passed += 1
    else: failed += 1; print("  FAIL:", m)

def fresh():
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json")); st.cursor = 100
    st.block_ts = int(time.time())
    code = B.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": B.ABI, "nonce": "n"}, A, "d")
    cid = st.contract_id(A, code, "n")
    rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
    return st, cid, rd

def call(st, cid, who, method, args, value=None, tag=""):
    p = {"op": "call", "contract": cid, "method": method, "args": args}
    if value: p["value"] = value
    st.apply_blob(p, who, method + tag + who)

def supply(st): return sum(st.bridge.values())

def market(st, cid, m, outcomes=3):
    lock = st.block_ts + 3600
    call(st, cid, A, "create_market", [m, outcomes, lock, lock + 7200, 1, 1, 1, 1, R1, 0, 0])
    return lock


def test_book_pays_on_a_market_with_no_tote_action():
    """The case the narrowing exists for: nobody used the tote, so the old rule would have auto-voided a
    market whose oracle answer was perfectly payable — cancelling the book with it."""
    st, cid, rd = fresh()
    for w, amt in ((BANK, 500 * UNIT), (C, 100 * UNIT)):
        st.credit_deposit(w, amt)
    start = supply(st)
    M = 9001
    lock = market(st, cid, M)
    call(st, cid, BANK, "book", [M], 200 * UNIT)
    ok(rd(B.BR, M) == 200, "bankroll posted")
    call(st, cid, BANK, "quote", [M, 1, 300])
    ok(rd(B.OD_BASE + 1, M) == 300, "outcome priced at 3.00x")
    call(st, cid, C, "back", [M, 1], 20 * UNIT)
    ok(rd(B.BS, M) == 20 and rd(B.BP_BASE + 1, M) == 60, "backed: 20u staked, 60u owed")

    st.block_ts = lock + 1
    call(st, cid, R1, "resolve", [M, 1])
    ok(rd(B.DN, M) == 1, "market RESOLVED even with an empty tote pot")
    ok(rd(B.VD, M) == 0, "and did NOT auto-void (there was no pot to strand)")

    before = st.bridge.get(C, 0)
    call(st, cid, C, "bclaim", [M])
    ok(st.bridge.get(C, 0) - before == 60 * UNIT, "book paid the quoted price")
    call(st, cid, C, "bclaim", [M], tag="2")
    ok(st.bridge.get(C, 0) - before == 60 * UNIT, "no double collect")
    bb = st.bridge.get(BANK, 0)
    call(st, cid, BANK, "bsweep", [M])
    ok(st.bridge.get(BANK, 0) - bb == (200 + 20 - 60) * UNIT, "bank swept roll + stake - payout")
    ok(st.bridge.get(cid, 0) == 0, "contract drained")
    ok(supply(st) == start, "value conserved")


def test_tote_still_auto_voids_when_its_pot_is_unpayable():
    """Regression: with a real tote pot whose winner had no backers, the market must still auto-void."""
    st, cid, rd = fresh()
    st.credit_deposit(A, 100 * UNIT)
    start = supply(st)
    M = 9002
    lock = market(st, cid, M)
    call(st, cid, A, "bet", [M, 0], 10 * UNIT)        # everyone on outcome 0…
    st.block_ts = lock + 1
    call(st, cid, R1, "resolve", [M, 2])              # …but outcome 2 wins
    ok(rd(B.VD, M) == 1, "unpayable tote pot auto-voids")
    ok(rd(B.DN, M) == 0, "and is not marked resolved")
    b4 = st.bridge.get(A, 0)
    call(st, cid, A, "claim", [M])
    ok(st.bridge.get(A, 0) - b4 == 10 * UNIT, "tote stake refunded 1:1")
    ok(supply(st) == start, "value conserved")


def test_tote_pays_normally():
    """Regression: an ordinary resolution still pays tote backers pro-rata."""
    st, cid, rd = fresh()
    st.credit_deposit(A, 100 * UNIT); st.credit_deposit(C, 100 * UNIT)
    start = supply(st)
    M = 9003
    lock = market(st, cid, M)
    call(st, cid, A, "bet", [M, 0], 30 * UNIT)
    call(st, cid, C, "bet", [M, 1], 10 * UNIT)
    st.block_ts = lock + 1
    call(st, cid, R1, "resolve", [M, 0])
    ok(rd(B.DN, M) == 1 and rd(B.VD, M) == 0, "resolved normally")
    b4 = st.bridge.get(A, 0)
    call(st, cid, A, "claim", [M])
    ok(st.bridge.get(A, 0) - b4 == 40 * UNIT, "sole winner takes the whole pot (30+10)")
    ok(supply(st) == start, "value conserved")


def test_book_solvency_and_guards():
    st, cid, rd = fresh()
    st.credit_deposit(BANK, 200 * UNIT); st.credit_deposit(C, 200 * UNIT); st.credit_deposit(A, 50 * UNIT)
    M = 9004
    lock = market(st, cid, M)
    call(st, cid, BANK, "book", [M], 100 * UNIT)
    call(st, cid, A, "book", [M], 50 * UNIT)
    ok(rd(B.BR, M) == 100, "a non-bank cannot add to the roll")
    call(st, cid, A, "quote", [M, 0, 200])
    ok(rd(B.OD_BASE + 0, M) == 0, "a punter cannot set the price")
    call(st, cid, BANK, "quote", [M, 0, 100])
    ok(rd(B.OD_BASE + 0, M) == 0, "odds must beat 1.00x")
    call(st, cid, C, "back", [M, 0], 10 * UNIT)
    ok(rd(B.BS, M) == 0, "cannot back an unpriced outcome")
    call(st, cid, BANK, "quote", [M, 0, 1000])         # 10x
    call(st, cid, C, "back", [M, 0], 20 * UNIT)        # would owe 200u vs 100+20 -> refuse
    ok(rd(B.BP_BASE + 0, M) == 0, "a bet the bank could not cover is refused")
    call(st, cid, C, "back", [M, 0], 10 * UNIT)        # owes 100u vs 100+10 -> fine
    ok(rd(B.BP_BASE + 0, M) == 100, "a covered bet is accepted")
    st.block_ts = lock + 1
    call(st, cid, C, "back", [M, 0], 10 * UNIT, tag="late")
    ok(rd(B.BS, M) == 10, "cannot back after the lock")


def test_book_position_views_report_what_the_punter_actually_holds():
    """The three views the site needs to show a book position instead of a blind "collect" button:
    what you staked, what it pays if it comes in, and whether you already took it. A view that
    disagreed with bclaim's payout would have players chasing money that isn't there."""
    st, cid, rd = fresh()
    M = 61
    lock = market(st, cid, M)
    for w, amt in ((BANK, 500 * UNIT), (C, 40 * UNIT)):
        st.credit_deposit(w, amt)
    call(st, cid, BANK, "book", [M], 500 * UNIT)
    call(st, cid, BANK, "quote", [M, 2, 250])                 # 2.50x on the away side
    call(st, cid, C, "back", [M, 2], 40 * UNIT)               # stake 40u -> payout 100u
    v = lambda meth, args: st.view(cid, meth, args)
    ok(v("bstake_of", [M, 2, C]) == 40 * UNIT, "bstake_of reports the stake in raw NADO")
    ok(v("bpay_of", [M, 2, C]) == 100 * UNIT, "bpay_of reports stake x price")
    ok(v("bstake_of", [M, 0, C]) == 0, "an outcome the punter did not back reads zero")
    ok(v("bstake_of", [M, 2, A]) == 0, "another address's position is not reported as mine")
    ok(v("bclaimed_of", [M, C]) == 0, "not collected yet")
    st.block_ts = lock + 1
    call(st, cid, R1, "resolve", [M, 2])
    before = st.bridge.get(C, 0)
    call(st, cid, C, "bclaim", [M])
    ok(st.bridge.get(C, 0) - before == 100 * UNIT, "bclaim pays exactly what bpay_of promised")
    ok(v("bclaimed_of", [M, C]) == 1, "bclaimed_of flips once collected")
    call(st, cid, C, "bclaim", [M], tag="again")
    ok(st.bridge.get(C, 0) - before == 100 * UNIT, "a second bclaim pays nothing")


for t in (test_book_pays_on_a_market_with_no_tote_action, test_tote_still_auto_voids_when_its_pot_is_unpayable,
          test_tote_pays_normally, test_book_solvency_and_guards,
          test_book_position_views_report_what_the_punter_actually_holds):
    t()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
