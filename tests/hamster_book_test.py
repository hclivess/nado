"""Hamster fixed-odds BOOK test — the bank-backed market that lets a lone player race immediately.
Covers: bankroll posting + bank-only guards, quoting, backing at the locked price, the per-bet SOLVENCY
invariant (a lane can never be committed to more than bankroll+stakes), payout on the winning lane, the
bank's sweep, void refunds, and global value conservation (the contract never mints).
Run: HOME=/root python tests/hamster_book_test.py
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode.games import hamster as H

BANK, A, B = "ndoBANK", "ndoAAA", "ndoBBB"
UNIT = H.UNIT
passed = failed = 0
def ok(c, m):
    global passed, failed
    if c: passed += 1
    else: failed += 1; print("  FAIL:", m)

def fresh(cursor=100):
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json")); st.cursor = cursor
    code = H.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": H.ABI, "nonce": "n"}, A, "d")
    cid = st.contract_id(A, code, "n")
    rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
    return st, cid, rd

def call(st, cid, who, method, args, value=None, tag=""):
    p = {"op": "call", "contract": cid, "method": method, "args": args}
    if value: p["value"] = value
    st.apply_blob(p, who, method + tag + who)

def supply(st): return sum(st.bridge.values())
def hashes(st, gh, lk, seed=0xABCDEF):
    st.block_hashes[gh] = seed ^ 0x1111
    for bi in range(1, H.RACE_LEN + 1):
        st.block_hashes[lk + bi] = (seed * (bi + 7) + 0x9E3779B9) & ((1 << 64) - 1)


def test_book_flow():
    st, cid, rd = fresh()
    for w, amt in ((BANK, 500 * UNIT), (A, 100 * UNIT), (B, 100 * UNIT)):
        st.credit_deposit(w, amt)
    start = supply(st)
    R = 4242
    call(st, cid, A, "open", [R])
    gh = rd(H.GH, R)

    # only a real bank may top up: BANK posts first, so B must not be able to add
    call(st, cid, BANK, "book", [R], 200 * UNIT)
    ok(rd(H.BR, R) == 200, f"bankroll posted ({rd(H.BR, R)}u)")
    call(st, cid, B, "book", [R], 50 * UNIT)
    ok(rd(H.BR, R) == 200, "a non-bank cannot add to the book")
    call(st, cid, BANK, "book", [R], 50 * UNIT)
    ok(rd(H.BR, R) == 250, "the bank can top up")

    # quoting is bank-only, must beat evens, and must be sane
    call(st, cid, A, "quote", [R, 0, 300])
    ok(rd(H.OD_BASE + 0, R) == 0, "a punter cannot set the price")
    call(st, cid, BANK, "quote", [R, 0, 100])
    ok(rd(H.OD_BASE + 0, R) == 0, "odds must beat 1.00x")
    call(st, cid, BANK, "quote", [R, 0, H.ODDS_CAP + 1])
    ok(rd(H.OD_BASE + 0, R) == 0, "absurd odds rejected")
    for lane, price in ((0, 300), (1, 250), (2, 900)):
        call(st, cid, BANK, "quote", [R, lane, price])
    ok(rd(H.OD_BASE + 0, R) == 300 and rd(H.OD_BASE + 2, R) == 900, "prices stored")

    # backing before the genes lock is refused — the price only means something once speeds are public
    call(st, cid, A, "back", [R, 0], 10 * UNIT)
    ok(rd(H.BS, R) == 0, "cannot back before the genes lock")
    st.cursor = gh
    ok(rd(H.LK, R) == 0, "clock still unstarted before any bet")

    # ONE backed bet starts the race — the whole point of the book
    call(st, cid, A, "back", [R, 0], 10 * UNIT)
    ok(rd(H.BS, R) == 10, "stake recorded")
    ok(rd(H.BP_BASE + 0, R) == 30, "payout locked at 3.00x (10u -> 30u)")
    lk, fh = rd(H.LK, R), rd(H.FH, R)
    ok(lk == gh + H.BET_BLOCKS and fh == lk + H.RACE_LEN, "a single backed bet starts the countdown")

    # an unpriced lane cannot be backed
    call(st, cid, B, "back", [R, 5], 5 * UNIT)
    ok(rd(H.BP_BASE + 5, R) == 0, "cannot back a lane with no price")

    # SOLVENCY: bankroll 250 + stakes. Lane 2 at 9.00x — 40u would commit 360u against 250+10+40=300 -> refuse
    call(st, cid, B, "back", [R, 2], 40 * UNIT)
    ok(rd(H.BP_BASE + 2, R) == 0, "a bet the bank could not cover is refused")
    call(st, cid, B, "back", [R, 2], 25 * UNIT)   # 225u payout vs 250+10+25 = 285 -> fine
    ok(rd(H.BP_BASE + 2, R) == 225, "a covered bet is accepted")
    ok(rd(H.BS, R) == 35, "stakes total tracked")

    # every lane stays covered by bankroll + stakes — the invariant that keeps the bank good for it
    covered = all(rd(H.BP_BASE + l, R) <= rd(H.BR, R) + rd(H.BS, R) for l in range(H.NH))
    ok(covered, "EVERY lane's committed payout is covered by bankroll + stakes")

    hashes(st, gh, lk)
    st.cursor = fh
    call(st, cid, A, "settle", [R])
    ok(rd(H.SD, R) == 1, "race settled")
    w = rd(H.WN, R) - 1

    # punters collect, then the bank sweeps
    before = {x: st.bridge.get(x, 0) for x in (A, B, BANK)}
    call(st, cid, A, "bclaim", [R]); call(st, cid, B, "bclaim", [R])
    gotA = st.bridge.get(A, 0) - before[A]
    gotB = st.bridge.get(B, 0) - before[B]
    expA = 30 * UNIT if w == 0 else 0
    expB = 225 * UNIT if w == 2 else 0
    ok(gotA == expA, f"A paid {gotA} (winner lane {w}, expected {expA})")
    ok(gotB == expB, f"B paid {gotB} (expected {expB})")
    call(st, cid, A, "bclaim", [R], tag="2")
    ok(st.bridge.get(A, 0) - before[A] == expA, "no double collect")

    call(st, cid, BANK, "bsweep", [R])
    gotBank = st.bridge.get(BANK, 0) - before[BANK]
    expBank = (250 + 35) * UNIT - (expA + expB)
    ok(gotBank == expBank, f"bank swept {gotBank}, expected {expBank}")
    call(st, cid, BANK, "bsweep", [R], tag="2")
    ok(st.bridge.get(BANK, 0) - before[BANK] == expBank, "bank cannot sweep twice")
    ok(st.bridge.get(cid, 0) == 0, "contract fully drained")
    ok(supply(st) == start, "value conserved — nothing minted or lost")


def test_void_refunds():
    st, cid, rd = fresh()
    st.credit_deposit(BANK, 200 * UNIT); st.credit_deposit(A, 50 * UNIT)
    start = supply(st)
    R = 77
    call(st, cid, A, "open", [R])
    gh = rd(H.GH, R)
    call(st, cid, BANK, "book", [R], 100 * UNIT)
    call(st, cid, BANK, "quote", [R, 3, 200])
    st.cursor = gh
    call(st, cid, A, "back", [R, 3], 20 * UNIT)
    # never settled -> voided long after the finish
    st.cursor = rd(H.FH, R) + H.VOID_AFTER + 1
    call(st, cid, A, "void", [R])
    ok(rd(H.VD, R) == 1, "stale race voided")
    b4 = st.bridge.get(A, 0)
    call(st, cid, A, "bclaim", [R])
    ok(st.bridge.get(A, 0) - b4 == 20 * UNIT, "void refunds the punter's stake, not the payout")
    b4b = st.bridge.get(BANK, 0)
    call(st, cid, BANK, "bsweep", [R])
    ok(st.bridge.get(BANK, 0) - b4b == 100 * UNIT, "void returns the bank's roll")
    ok(st.bridge.get(cid, 0) == 0, "contract drained after a void")
    ok(supply(st) == start, "value conserved on void")



def test_autovoid_does_not_refund_the_book():
    """A parimutuel AUTO-VOID (its winner had no pool backers) must NOT refund book bets: the race still
    RAN and has a winner. Refunding there would hand punters a free option — back a lane, and if some
    unbacked lane wins, get the stake back instead of losing it — which the bank would be paying for."""
    st, cid, rd = fresh()
    st.credit_deposit(BANK, 400 * UNIT); st.credit_deposit(A, 100 * UNIT); st.credit_deposit(B, 100 * UNIT)
    start = supply(st)
    R = 5150
    call(st, cid, A, "open", [R])
    gh = rd(H.GH, R)
    call(st, cid, BANK, "book", [R], 200 * UNIT)
    for lane in range(H.NH):
        call(st, cid, BANK, "quote", [R, lane, 200], tag=str(lane))
    st.cursor = gh
    # parimutuel action on ONE lane only, so most outcomes leave the pot unpayable -> auto-void
    call(st, cid, A, "bet", [R, 0], 10 * UNIT)
    call(st, cid, B, "bet", [R, 0], 10 * UNIT)
    # book action on EVERY lane, so exactly one book bet is a winner whatever happens
    for lane in range(H.NH):
        call(st, cid, A, "back", [R, lane], 5 * UNIT, tag="bk" + str(lane))
    lk, fh = rd(H.LK, R), rd(H.FH, R)
    hashes(st, gh, lk, seed=0x1234)
    st.cursor = fh
    call(st, cid, A, "settle", [R])
    w = rd(H.WN, R) - 1
    voided = rd(H.VD, R) == 1
    ok(rd(H.SD, R) == 1, "the race settled (it ran, so there IS a result)")
    before = st.bridge.get(A, 0)
    call(st, cid, A, "bclaim", [R])
    got = st.bridge.get(A, 0) - before
    # A backed every lane at 2.00x with 5u, so the book owes exactly one 10u payout — never the 30u of
    # refunded stakes, no matter what the parimutuel side did
    ok(got == 10 * UNIT, f"book pays the WINNER only ({got} raw, auto-voided={voided}, lane {w})")
    call(st, cid, B, "claim", [R], tag="p")   # parimutuel side settles on its own terms
    call(st, cid, A, "claim", [R], tag="p")
    call(st, cid, BANK, "bsweep", [R])
    ok(st.bridge.get(cid, 0) == 0, "contract fully drained across BOTH markets")
    ok(supply(st) == start, "value conserved across both markets")


for t in (test_book_flow, test_void_refunds, test_autovoid_does_not_refund_the_book):
    t()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
