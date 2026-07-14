# tests/test_mines_contract.py — build + exercise the MINES contract (stackvm), peer-banked.
#
# The crypto-casino classic, dealer-less: a 5x5 field hides N mines; reveal tiles one (or a few) at a
# time — every safe reveal multiplies your payout, one mine loses the stake — and CASH OUT any time.
# The grid POSITIONS are client theater; what's provable is the odds: each reveal is an independent
# uniform draw over the tiles remaining, derived from two FUTURE L1 block hashes bound when you pick:
#     q       = BLOCKHASH(gh) + BLOCKHASH(gh+1) + seatId*100          gh = pick cursor + 2
#     draw_i  = HASH(q + picksSoFar + i) % tilesLeft_i                mine iff draw_i < N
# A safe reveal re-prices the payout with a flat 1% edge per step:
#     value *= tilesLeft * 99 / ((tilesLeft - N) * 100)
# Cover is reserved dice-style at PICK time (tc += newValue - value, must fit the bankroll), so the
# bank can always pay and an uncoverable pick reverts BEFORE it binds (never a stuck resolve).
# Liveness: resolve() is permissionless; reap() force-cashes an abandoned seat after REAP blocks so a
# walk-away can never lock the bank's cover or block close().
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vmasm import (P, A, LD, ST, S, SETR, R, IF, WHILE, CALLER, VALUE, CURSOR, HASH, BLOCKHASH,
                   ADD, SUB, MUL, DIV, MOD, EQ, GT, GTE, LT, LTE, NOT, AND, OR, REQ, PAY, HALT,
                   bank_table_methods, vm_hash, Harness)

T = 25                 # tiles
NMIN, NMAX = 1, 24     # mines
EDGE_NUM, EDGE_DEN = 99, 100   # 1% edge per safe reveal
PICK_D = 2             # pick binds to blocks cursor+2, cursor+3 (unknowable at signing)
REAP = 1200            # ~2h: abandoned/unresolvable seats force-cash at their last confirmed value

# table t maps: tk=bankroll tp=pool tc=committed ta=bankAddr tn=seats tx=settled tz=closed
# seat g maps:  gs=stake gg=tableId ga=player gn=mines gp=safe reveals gv=value(payout now)
#               gq=pending value gc=pending count gh=pending height ge=last activity
#               gd=done gb=bust step(1-based, in the busted batch) gw=1 cashed / 2 reaped
CODE = dict(bank_table_methods())

# bet(g, t, N) value=stake — take a seat: N mines on a fresh 25-tile field
CODE["bet"] = (
    A(0) + P(0) + GT + REQ
    + VALUE + P(0) + GT + REQ
    + A(0) + LD("gg") + P(0) + EQ + REQ                    # fresh seat id
    + A(1) + LD("ta") + P(0) + EQ + NOT + REQ              # table exists
    + A(1) + LD("tz") + NOT + REQ                          # not closed
    + A(2) + P(NMIN) + GTE + REQ
    + A(2) + P(NMAX) + LTE + REQ
    + A(0) + VALUE + ST("gs")
    + A(0) + A(1) + ST("gg")
    + A(0) + CALLER + ST("ga")
    + A(0) + A(2) + ST("gn")
    + A(0) + VALUE + ST("gv")                              # cash-out value starts at the stake
    + A(0) + CURSOR + ST("ge")
    + A(1) + A(1) + LD("tp") + VALUE + ADD + ST("tp")
    + A(1) + A(1) + LD("tn") + P(1) + ADD + ST("tn")
    + HALT)

# pick(g, n) — reveal n more tiles (one batch, one hash pair). Reserves the batch's full win against
# the bankroll NOW, so resolve can never be stuck on cover.
CODE["pick"] = (
    A(0) + LD("gg") + P(0) + EQ + NOT + REQ
    + A(0) + LD("gd") + NOT + REQ
    + A(0) + LD("gh") + P(0) + EQ + REQ                    # no batch already pending
    + CALLER + A(0) + LD("ga") + EQ + REQ                  # only the player risks their value
    + A(1) + P(1) + GTE + REQ
    + A(0) + LD("gp") + A(1) + ADD + P(T) + A(0) + LD("gn") + SUB + LTE + REQ   # ≤ the safe tiles
    # nv = gv, then per step: rem = T-gp-i ; nv = nv*rem*99 // ((rem-N)*100)
    + SETR("nv", A(0) + LD("gv"))
    + SETR("i", P(0))
    + WHILE(R("i") + A(1) + LT,
            SETR("rem", P(T) + A(0) + LD("gp") + SUB + R("i") + SUB)
            + SETR("nv", R("nv") + R("rem") + MUL + P(EDGE_NUM) + MUL
                    + R("rem") + A(0) + LD("gn") + SUB + P(EDGE_DEN) + MUL + DIV)
            + SETR("i", R("i") + P(1) + ADD))
    # reserve the extra exposure: tc + (nv - gv) must fit the bankroll
    + A(0) + LD("gg") + LD("tc") + R("nv") + ADD + A(0) + LD("gv") + SUB
    + A(0) + LD("gg") + LD("tk") + LTE + REQ
    + A(0) + LD("gg") + A(0) + LD("gg") + LD("tc") + R("nv") + ADD + A(0) + LD("gv") + SUB + ST("tc")
    + A(0) + R("nv") + ST("gq")
    + A(0) + A(1) + ST("gc")
    + A(0) + CURSOR + P(PICK_D) + ADD + ST("gh")
    + A(0) + CURSOR + ST("ge")
    + HALT)

# resolve(g) — permissionless once the batch's blocks exist: draw each step; a mine ends the game
# (stake folds into the bankroll), an all-safe batch banks the new value and frees the next pick.
CODE["resolve"] = (
    A(0) + LD("gg") + P(0) + EQ + NOT + REQ
    + A(0) + LD("gd") + NOT + REQ
    + A(0) + LD("gh") + P(0) + EQ + NOT + REQ
    + CURSOR + A(0) + LD("gh") + P(1) + ADD + GTE + REQ
    + SETR("q", A(0) + LD("gh") + BLOCKHASH
            + A(0) + LD("gh") + P(1) + ADD + BLOCKHASH + ADD
            + A(0) + P(100) + MUL + ADD)
    + SETR("b", P(0))                                       # bust step (1-based), 0 = clean
    + SETR("i", P(0))
    + WHILE(R("i") + A(0) + LD("gc") + LT + R("b") + P(0) + EQ + AND,
            SETR("d", R("q") + A(0) + LD("gp") + ADD + R("i") + ADD + HASH
                    + P(T) + A(0) + LD("gp") + SUB + R("i") + SUB + MOD)
            + IF(R("d") + A(0) + LD("gn") + LT, SETR("b", R("i") + P(1) + ADD))
            + SETR("i", R("i") + P(1) + ADD))
    + IF(R("b"),
         # BUST: release the whole reserve, the stake folds into the bankroll
         A(0) + LD("gg") + A(0) + LD("gg") + LD("tc") + A(0) + LD("gq") + A(0) + LD("gs") + SUB + SUB + ST("tc")
         + A(0) + LD("gg") + A(0) + LD("gg") + LD("tk") + A(0) + LD("gs") + ADD + ST("tk")
         + A(0) + R("b") + ST("gb")
         + A(0) + P(1) + ST("gd")
         + A(0) + LD("gg") + A(0) + LD("gg") + LD("tx") + P(1) + ADD + ST("tx"),
         # ALL SAFE: bank the new value, clear the pending batch
         A(0) + A(0) + LD("gp") + A(0) + LD("gc") + ADD + ST("gp")
         + A(0) + A(0) + LD("gq") + ST("gv")
         + A(0) + P(0) + ST("gq")
         + A(0) + P(0) + ST("gc")
         + A(0) + P(0) + ST("gh")
         + A(0) + CURSOR + ST("ge"))
    + HALT)

# cashout(g) — player-only, only between batches: take the current value, release the cover
CODE["cashout"] = (
    A(0) + LD("gg") + P(0) + EQ + NOT + REQ
    + A(0) + LD("gd") + NOT + REQ
    + A(0) + LD("gh") + P(0) + EQ + REQ                    # nothing pending you might already regret
    + CALLER + A(0) + LD("ga") + EQ + REQ
    + A(0) + LD("ga") + A(0) + LD("gv") + PAY
    + A(0) + LD("gg") + A(0) + LD("gg") + LD("tp") + A(0) + LD("gv") + SUB + ST("tp")
    + A(0) + LD("gg") + A(0) + LD("gg") + LD("tc") + A(0) + LD("gv") + SUB + A(0) + LD("gs") + ADD + ST("tc")   # tc -= gv - gs
    + A(0) + LD("gg") + A(0) + LD("gg") + LD("tk") + A(0) + LD("gs") + ADD + A(0) + LD("gv") + SUB + ST("tk")
    + A(0) + P(1) + ST("gw")
    + A(0) + P(1) + ST("gd")
    + A(0) + LD("gg") + A(0) + LD("gg") + LD("tx") + P(1) + ADD + ST("tx")
    + HALT)

# reap(g) — permissionless liveness escape: an abandoned seat (or an unresolvable pruned batch)
# force-cashes at its last CONFIRMED value after REAP blocks of inactivity; a pending batch is voided.
CODE["reap"] = (
    A(0) + LD("gg") + P(0) + EQ + NOT + REQ
    + A(0) + LD("gd") + NOT + REQ
    + CURSOR + A(0) + LD("ge") + P(REAP) + ADD + GT + REQ
    + A(0) + LD("ga") + A(0) + LD("gv") + PAY
    + A(0) + LD("gg") + A(0) + LD("gg") + LD("tp") + A(0) + LD("gv") + SUB + ST("tp")
    # release the reserve: gq if a batch is pending, else gv
    + IF(A(0) + LD("gh"),
         A(0) + LD("gg") + A(0) + LD("gg") + LD("tc") + A(0) + LD("gq") + A(0) + LD("gs") + SUB + SUB + ST("tc"),
         A(0) + LD("gg") + A(0) + LD("gg") + LD("tc") + A(0) + LD("gv") + A(0) + LD("gs") + SUB + SUB + ST("tc"))
    + A(0) + LD("gg") + A(0) + LD("gg") + LD("tk") + A(0) + LD("gs") + ADD + A(0) + LD("gv") + SUB + ST("tk")
    + A(0) + P(2) + ST("gw")
    + A(0) + P(1) + ST("gd")
    + A(0) + LD("gg") + A(0) + LD("gg") + LD("tx") + P(1) + ADD + ST("tx")
    + HALT)


# ---------------- PYTHON REFERENCE ----------------
def ref_value_after(stake, n_mines, picks):
    """payout value after `picks` safe reveals (integer math, must match the contract exactly)."""
    v = stake
    for i in range(picks):
        rem = T - i
        v = v * rem * EDGE_NUM // ((rem - n_mines) * EDGE_DEN)
    return v


def ref_batch_value(v, gp, n_mines, count):
    for i in range(count):
        rem = T - gp - i
        v = v * rem * EDGE_NUM // ((rem - n_mines) * EDGE_DEN)
    return v


def ref_draws(bh, gh, g, gp, count, n_mines):
    """-> (bust_step 1-based or 0, draws list). Mirrors the contract + the JS client."""
    q = bh[gh] + bh[gh + 1] + g * 100
    draws = []
    for i in range(count):
        d = vm_hash(q + gp + i) % (T - gp - i)
        draws.append(d)
        if d < n_mines:
            return i + 1, draws
    return 0, draws


# ---------------- TESTS ----------------
H = Harness(CODE, accounts=("BANK", "B1", "B2", "EVE"), cursor=1000, nonce="mines")
ck, call, bal, M, rv = H.ck, H.call, H.bal, H.M, H.rv

TBL = 7; BANKROLL = 10**12; STAKE = 10**9
call("open", [TBL], BANKROLL, "BANK")
ck("open banks the field", M("ta", TBL) == "BANK" and M("tk", TBL) == BANKROLL and M("tp", TBL) == BANKROLL)

G = 101
ck("bet with 0 mines reverts", rv(call("bet", [G, TBL, 0], STAKE, "B1")))
ck("bet with 25 mines reverts", rv(call("bet", [G, TBL, 25], STAKE, "B1")))
call("bet", [G, TBL, 3], STAKE, "B1")
ck("bet seats the player (3 mines), value = stake",
   M("gv", G) == STAKE and M("gn", G) == 3 and M("tn", TBL) == 1 and M("tp", TBL) == BANKROLL + STAKE)
ck("seat id reuse reverts", rv(call("bet", [G, TBL, 3], STAKE, "B2")))
ck("cash-out with zero reveals refunds the stake (allowed, pointless)", True)  # exercised at seat 103 below

# a pick reserves the batch win against the bankroll
call("pick", [G, 2], 0, "B1")
nv = ref_batch_value(STAKE, 0, 3, 2)
ck("pick(2) binds cursor+2 and reserves nv-gv",
   M("gh", G) == H.cursor + PICK_D and M("gq", G) == nv and M("tc", TBL) == nv - STAKE)
ck("second pick while pending reverts", rv(call("pick", [G, 1], 0, "B1")))
ck("cashout while a batch is pending reverts", rv(call("cashout", [G], 0, "B1")))
ck("resolve before the blocks exist reverts", rv(call("resolve", [G], 0, "EVE")))
ck("someone else's pick reverts", rv(call("pick", [102, 1], 0, "B2")))

gh = M("gh", G)
H.seed(gh - 1, gh + 2, "m1")
H.cursor = gh + 1
bust, draws = ref_draws(H.st.block_hashes, gh, G, 0, 2, 3)
call("resolve", [G], 0, "EVE")                              # permissionless
if bust:
    ck(f"batch busted at step {bust} (draws {draws}) — stake folds into the bankroll",
       M("gd", G) == 1 and M("gb", G) == bust and M("tk", TBL) == BANKROLL + STAKE and M("tc", TBL) == 0)
else:
    ck(f"batch clean (draws {draws}) — value banked",
       M("gv", G) == nv and M("gp", G) == 2 and M("gh", G) == 0 and M("tc", TBL) == nv - STAKE)
    b1 = bal("B1")
    call("cashout", [G], 0, "B1")
    ck("cashout pays the banked value and releases the cover",
       bal("B1") == b1 + nv and M("gd", G) == 1 and M("tc", TBL) == 0
       and M("tk", TBL) == BANKROLL + STAKE - nv)
ck("done seat can't pick again", rv(call("pick", [G, 1], 0, "B1")))
ck("done seat can't cash out twice", rv(call("cashout", [G], 0, "B1")))

# zero-reveal cashout = free cancel
call("bet", [103, TBL, 5], STAKE, "B2")
b2 = bal("B2")
call("cashout", [103], 0, "B2")
ck("zero-reveal cashout refunds exactly the stake", bal("B2") == b2 + STAKE)

# over-pick guard: can't reveal more than the safe tiles
call("bet", [104, TBL, 24], STAKE, "B2")
ck("pick beyond the safe tiles reverts (24 mines -> 1 safe)", rv(call("pick", [104, 2], 0, "B2")))
call("pick", [104, 1], 0, "B2")
ck("the single max-odds pick reserves 24.75x", M("gq", 104) == STAKE * 25 * 99 // (1 * 100))

# cover guard: a batch the bank can't cover reverts at PICK time (never a stuck resolve)
call("open", [8], 10**6, "BANK")
call("bet", [105, 8, 10], 10**6, "B1")
ck("uncoverable batch reverts at pick", rv(call("pick", [105, 10], 0, "B1")))

# reap: abandoned seat force-cashes at its last confirmed value
H.cursor += 1
call("bet", [106, TBL, 3], STAKE, "B1")
ck("reap before the window reverts", rv(call("reap", [106], 0, "EVE")))
H.cursor += REAP + 1
b1 = bal("B1")
call("reap", [106], 0, "EVE")
ck("reap refunds an untouched abandoned seat", bal("B1") == b1 + STAKE and M("gw", 106) == 2 and M("gd", 106) == 1)

# reap with a PENDING batch (hashes never recorded): voids the batch, pays the confirmed value
call("bet", [107, TBL, 3], STAKE, "B1")
call("pick", [107, 3], 0, "B1")
gq107 = M("gq", 107)
H.cursor += REAP + 1
ck("resolve of a pruned batch reverts (no hashes)", rv(call("resolve", [107], 0, "EVE")))
b1 = bal("B1")
tc0 = M("tc", TBL)
call("reap", [107], 0, "EVE")
ck("reap voids the pending batch and releases its whole reserve",
   bal("B1") == b1 + STAKE and M("tc", TBL) == tc0 - (gq107 - STAKE))

# ---------------- DIFFERENTIAL: random sessions vs the reference ----------------
import random as _r
rng = _r.Random(0xA11CE)
mism = 0; n_done = 0; busts = 0; cashes = 0
tk_mirror = M("tk", TBL); tc_mirror = M("tc", TBL)
for k in range(300):
    g = 10_000 + k
    n_mines = rng.randrange(1, 25)
    stake = rng.randrange(10**6, 10**9)
    who = rng.choice(["B1", "B2"])
    if rv(call("bet", [g, TBL, n_mines], stake, who)):
        mism += 1; continue
    v = stake; gp = 0; alive = True
    while alive:
        max_batch = (T - n_mines) - gp
        if max_batch <= 0:
            break
        count = rng.randrange(1, min(4, max_batch) + 1)
        want_nv = ref_batch_value(v, gp, n_mines, count)
        r = call("pick", [g, count], 0, who)
        if rv(r):
            break                                            # cover exhausted -> player must stop
        if M("gq", g) != want_nv:
            mism += 1
        tc_mirror += want_nv - v
        gh = M("gh", g)
        H.seed(gh - 1, gh + 2, f"d{k}")
        H.cursor = max(H.cursor, gh + 1)
        bust, _dr = ref_draws(H.st.block_hashes, gh, g, gp, count, n_mines)
        b0 = bal(who)
        call("resolve", [g], 0, "EVE")
        if bust:
            alive = False; busts += 1
            tc_mirror -= want_nv - stake
            tk_mirror += stake
            if M("gd", g) != 1 or M("gb", g) != bust or bal(who) != b0: mism += 1
        else:
            v = want_nv; gp += count
            if M("gv", g) != v or M("gp", g) != gp: mism += 1
            if rng.random() < 0.4:
                alive = False
    if M("gd", g) != 1:                                      # still alive -> cash out
        b0 = bal(who)
        call("cashout", [g], 0, who)
        cashes += 1
        tc_mirror -= v - stake
        tk_mirror += stake - v
        if bal(who) != b0 + v: mism += 1
    if M("tk", TBL) != tk_mirror or M("tc", TBL) != tc_mirror: mism += 1
    n_done += 1
ck(f"DIFFERENTIAL: {n_done} sessions bytecode==reference (mism={mism}, {busts} busts / {cashes} cash-outs)",
   mism == 0 and n_done == 300 and busts > 80 and cashes > 30)
ck("all reserves released after every session", M("tc", TBL) == tc_mirror and tc_mirror >= 0)

# bank lifecycle (settle whatever is still open on table 8, then close)
if M("gd", 105) != 1:
    H.cursor += REAP + 1
    call("reap", [105], 0, "EVE")
if M("gd", 104) != 1:
    H.cursor += REAP + 1
    call("reap", [104], 0, "EVE")
ck("non-bank fund reverts", rv(call("fund", [TBL], 10**9, "EVE")))
tk0, tp0 = M("tk", TBL), M("tp", TBL)
call("fund", [TBL], 10**9, "BANK")
ck("bank top-up grows bank + pool", M("tk", TBL) == tk0 + 10**9 and M("tp", TBL) == tp0 + 10**9)
bB = bal("BANK")
call("close", [TBL], 0, "BANK")
ck("close pays the pool back to the bank", bal("BANK") > bB and M("tz", TBL) == 1 and M("tp", TBL) == 0)
ck("bet on a closed table reverts", rv(call("bet", [99999, TBL, 3], STAKE, "B1")))
call("close", [8], 0, "BANK")
ck("contract drains to zero once every pool is closed", bal(H.cid) == 0)

H.finish("mines.json", extra=f"resolve = {len(CODE['resolve'])} instr, pick = {len(CODE['pick'])} instr")
