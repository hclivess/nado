# tests/test_blackjack_contract.py — build + exercise the BLACKJACK contract (stackvm), peer-banked.
#
# Fully provable blackjack with NO dealer to trust: the "dealer" is a fixed on-chain strategy (stands on
# 17, soft or hard) whose cards come from block hashes bound AFTER you stand — so there is nothing to
# peek at and nothing to rig. Infinite-deck draws (each card an independent uniform 0..51, the only
# sound dealer-less scheme — the hold'em multi-deck rule), European no-hole-card timing.
#   deal(g,t)+stake  binds dh=cursor+2:   player cards = HASH(q+0),HASH(q+1)  dealer up = HASH(q+16)
#                                          with q = BH(dh)+BH(dh+1)+g*64
#   hit(g)           binds hh:             card k (k = cards so far) = HASH(BH(hh)+BH(hh+1)+g*64 + k)
#   stand(g)         binds sh:             dealer hole+hits = HASH(BH(sh)+BH(sh+1)+g*64+32 + j)
#   reveal/draw/settle are PERMISSIONLESS resolutions of the pending binding.
# Payouts: win 2x stake, push refunds, natural blackjack 5:2 (3:2 winnings), dealer natural beats a
# non-natural 21. Cover: every hand reserves the 3/2 worst case against the bankroll at deal time.
# reap(): an undealt abandoned hand refunds; a hand abandoned AFTER seeing cards forfeits (any refund
# of a seen hand lets a player keep only good hands — that kills the edge; resolution stays publicly
# available for ~33h before hashes prune, so honest players never hit this).
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vmasm import (P, A, LD, ST, S, SETR, R, IF, WHILE, CALLER, VALUE, CURSOR, HASH, BLOCKHASH,
                   ADD, SUB, MUL, DIV, MOD, EQ, GT, GTE, LT, LTE, NOT, AND, OR, REQ, PAY, HALT,
                   bank_table_methods, vm_hash, Harness)

DEAL_D = 2
MAXCARDS = 11          # a 12th card can never keep a hand ≤21 (11 aces = hard 11 = best 21)
REAP = 1200
COVER_NUM, COVER_DEN = 3, 2    # worst-case exposure = stake*3/2 (a 5:2 natural)

# table t maps: tk=bankroll tp=pool tc=committed ta=bankAddr tn=hands tx=settled tz=closed
# seat g maps:  gs=stake gg=table ga=player gf=phase(1 deal-pending 2 your-turn 3 hit-pending
#               4 stand-pending) gh=pending height gp=player HARD total gq=player aces gn=player cards
#               du=dealer up card+1 ge=last activity gd=done gr=dealer final best (display)
#               gw=result 1 win · 2 push · 3 blackjack · 4 lose · 5 bust · 6 forfeited
# card maps (display/audit — the UI reconstructs the exact hand from chain state alone):
#               pc[g*16+k]=player card k +1 · dk[g*16+j]=dealer card j +1 (0=hole, then hits)
CODE = dict(bank_table_methods())

def _card_val(card_ops, vreg, areg):
    """append: r = card%13 ; vreg = hard value (A=1, 2..9 face, 10 for 10/J/Q/K) ; areg = isAce"""
    return (SETR("r", card_ops + P(13) + MOD)
            + SETR(vreg, R("r") + P(2) + ADD + R("r") + P(8) + LTE + MUL
                   + P(10) + R("r") + P(9) + GTE + MUL + R("r") + P(11) + LTE + MUL + ADD
                   + R("r") + P(12) + EQ + ADD)
            + SETR(areg, R("r") + P(12) + EQ))

def _best(hreg, areg):
    """push best(h,a) = h + 10 if (a>0 and h+10<=21)"""
    return (R(hreg) + P(10) + R(areg) + P(0) + GT + MUL
            + R(hreg) + P(10) + ADD + P(21) + LTE + MUL + ADD)

# deal(g, t) value=stake — take a hand; reserves the 3/2 worst case, binds the deal to cursor+2
CODE["deal"] = (
    A(0) + P(0) + GT + REQ
    + VALUE + P(0) + GT + REQ
    + A(0) + LD("gg") + P(0) + EQ + REQ
    + A(1) + LD("ta") + P(0) + EQ + NOT + REQ
    + A(1) + LD("tz") + NOT + REQ
    + A(1) + LD("tc") + VALUE + P(COVER_NUM) + MUL + P(COVER_DEN) + DIV + ADD + A(1) + LD("tk") + LTE + REQ
    + A(1) + A(1) + LD("tc") + VALUE + P(COVER_NUM) + MUL + P(COVER_DEN) + DIV + ADD + ST("tc")
    + A(1) + A(1) + LD("tp") + VALUE + ADD + ST("tp")
    + A(0) + VALUE + ST("gs")
    + A(0) + A(1) + ST("gg")
    + A(0) + CALLER + ST("ga")
    + A(0) + P(1) + ST("gf")
    + A(0) + CURSOR + P(DEAL_D) + ADD + ST("gh")
    + A(0) + CURSOR + ST("ge")
    + A(1) + A(1) + LD("tn") + P(1) + ADD + ST("tn")
    + HALT)

# reveal(g) — permissionless: derive the two player cards + the dealer's up card
CODE["reveal"] = (
    A(0) + LD("gf") + P(1) + EQ + REQ
    + CURSOR + A(0) + LD("gh") + P(1) + ADD + GTE + REQ
    + SETR("q", A(0) + LD("gh") + BLOCKHASH + A(0) + LD("gh") + P(1) + ADD + BLOCKHASH + ADD
            + A(0) + P(64) + MUL + ADD)
    + SETR("c0", R("q") + P(0) + ADD + HASH + P(52) + MOD)
    + SETR("c1", R("q") + P(1) + ADD + HASH + P(52) + MOD)
    + _card_val(R("c0"), "v0", "a0")
    + _card_val(R("c1"), "v1", "a1")
    + A(0) + R("v0") + R("v1") + ADD + ST("gp")
    + A(0) + R("a0") + R("a1") + ADD + ST("gq")
    + A(0) + P(2) + ST("gn")
    + A(0) + P(16) + MUL + P(0) + ADD + R("c0") + P(1) + ADD + ST("pc")
    + A(0) + P(16) + MUL + P(1) + ADD + R("c1") + P(1) + ADD + ST("pc")
    + A(0) + R("q") + P(16) + ADD + HASH + P(52) + MOD + P(1) + ADD + ST("du")
    + A(0) + P(2) + ST("gf")
    + A(0) + P(0) + ST("gh")
    + A(0) + CURSOR + ST("ge")
    + HALT)

# hit(g) — player-only: bind the next card to future blocks
CODE["hit"] = (
    A(0) + LD("gf") + P(2) + EQ + REQ
    + CALLER + A(0) + LD("ga") + EQ + REQ
    + A(0) + LD("gn") + P(MAXCARDS) + LT + REQ
    + A(0) + P(3) + ST("gf")
    + A(0) + CURSOR + P(DEAL_D) + ADD + ST("gh")
    + A(0) + CURSOR + ST("ge")
    + HALT)

# draw(g) — permissionless: land the bound hit; a hard total over 21 is a bust (stake to the bank)
CODE["draw"] = (
    A(0) + LD("gf") + P(3) + EQ + REQ
    + CURSOR + A(0) + LD("gh") + P(1) + ADD + GTE + REQ
    + SETR("c", A(0) + LD("gh") + BLOCKHASH + A(0) + LD("gh") + P(1) + ADD + BLOCKHASH + ADD
            + A(0) + P(64) + MUL + ADD + A(0) + LD("gn") + ADD + HASH + P(52) + MOD)
    + _card_val(R("c"), "v", "a")
    + A(0) + P(16) + MUL + A(0) + LD("gn") + ADD + R("c") + P(1) + ADD + ST("pc")
    + A(0) + A(0) + LD("gp") + R("v") + ADD + ST("gp")
    + A(0) + A(0) + LD("gq") + R("a") + ADD + ST("gq")
    + A(0) + A(0) + LD("gn") + P(1) + ADD + ST("gn")
    + IF(A(0) + LD("gp") + P(21) + GT,
         # BUST: stake folds into the bankroll, cover released
         A(0) + P(5) + ST("gw")
         + A(0) + P(1) + ST("gd")
         + A(0) + P(0) + ST("gf")
         + A(0) + P(0) + ST("gh")
         + A(0) + LD("gg") + A(0) + LD("gg") + LD("tc")
             + A(0) + LD("gs") + P(COVER_NUM) + MUL + P(COVER_DEN) + DIV + SUB + ST("tc")
         + A(0) + LD("gg") + A(0) + LD("gg") + LD("tk") + A(0) + LD("gs") + ADD + ST("tk")
         + A(0) + LD("gg") + A(0) + LD("gg") + LD("tx") + P(1) + ADD + ST("tx"),
         A(0) + P(2) + ST("gf")
         + A(0) + P(0) + ST("gh")
         + A(0) + CURSOR + ST("ge"))
    + HALT)

# stand(g) — player-only: bind the dealer's cards to future blocks
CODE["stand"] = (
    A(0) + LD("gf") + P(2) + EQ + REQ
    + CALLER + A(0) + LD("ga") + EQ + REQ
    + A(0) + P(4) + ST("gf")
    + A(0) + CURSOR + P(DEAL_D) + ADD + ST("gh")
    + A(0) + CURSOR + ST("ge")
    + HALT)

# settle(g) — permissionless: play out the dealer (S17) and pay the table
CODE["settle"] = (
    A(0) + LD("gf") + P(4) + EQ + REQ
    + CURSOR + A(0) + LD("gh") + P(1) + ADD + GTE + REQ
    + SETR("dq", A(0) + LD("gh") + BLOCKHASH + A(0) + LD("gh") + P(1) + ADD + BLOCKHASH + ADD
            + A(0) + P(64) + MUL + ADD + P(32) + ADD)
    + _card_val(A(0) + LD("du") + P(1) + SUB, "dv", "da0")   # the up card (stored +1)
    + SETR("dh", R("dv")) + SETR("dc", R("da0"))             # dh hard total · dc aces
    + SETR("cd", R("dq") + P(0) + ADD + HASH + P(52) + MOD)  # the hole card
    + A(0) + P(16) + MUL + P(0) + ADD + R("cd") + P(1) + ADD + ST("dk")
    + _card_val(R("cd"), "dv", "da0")
    + SETR("dh", R("dh") + R("dv") + ADD) + SETR("dc", R("dc") + R("da0") + ADD)
    + SETR("j", P(1))
    + WHILE(_best("dh", "dc") + P(17) + LT,
            SETR("cd", R("dq") + R("j") + ADD + HASH + P(52) + MOD)
            + A(0) + P(16) + MUL + R("j") + ADD + R("cd") + P(1) + ADD + ST("dk")
            + _card_val(R("cd"), "dv", "da0")
            + SETR("dh", R("dh") + R("dv") + ADD) + SETR("dc", R("dc") + R("da0") + ADD)
            + SETR("j", R("j") + P(1) + ADD))
    + SETR("db", _best("dh", "dc"))
    + SETR("dnat", R("j") + P(1) + EQ + R("db") + P(21) + EQ + AND)
    + SETR("ph", A(0) + LD("gp")) + SETR("pa", A(0) + LD("gq"))
    + SETR("pb", _best("ph", "pa"))
    + SETR("pnat", A(0) + LD("gn") + P(2) + EQ + R("pb") + P(21) + EQ + AND)
    # pay + result, most specific first
    + IF(R("pnat") + R("dnat") + AND,
         SETR("pay", A(0) + LD("gs")) + SETR("res", P(2)),
         IF(R("pnat"),
            SETR("pay", A(0) + LD("gs") + P(5) + MUL + P(2) + DIV) + SETR("res", P(3)),
            IF(R("dnat"),
               SETR("pay", P(0)) + SETR("res", P(4)),
               IF(R("db") + P(21) + GT + R("db") + R("pb") + LT + OR,
                  SETR("pay", A(0) + LD("gs") + P(2) + MUL) + SETR("res", P(1)),
                  IF(R("db") + R("pb") + EQ,
                     SETR("pay", A(0) + LD("gs")) + SETR("res", P(2)),
                     SETR("pay", P(0)) + SETR("res", P(4)))))))
    + A(0) + LD("ga") + R("pay") + PAY
    + A(0) + R("res") + ST("gw")
    + A(0) + R("db") + ST("gr")
    + A(0) + P(1) + ST("gd")
    + A(0) + P(0) + ST("gf")
    + A(0) + LD("gg") + A(0) + LD("gg") + LD("tp") + R("pay") + SUB + ST("tp")
    + A(0) + LD("gg") + A(0) + LD("gg") + LD("tc")
        + A(0) + LD("gs") + P(COVER_NUM) + MUL + P(COVER_DEN) + DIV + SUB + ST("tc")
    + A(0) + LD("gg") + A(0) + LD("gg") + LD("tk") + A(0) + LD("gs") + ADD + R("pay") + SUB + ST("tk")
    + A(0) + LD("gg") + A(0) + LD("gg") + LD("tx") + P(1) + ADD + ST("tx")
    + HALT)

# reap(g) — liveness escape: undealt refunds; a hand abandoned after seeing cards forfeits
CODE["reap"] = (
    A(0) + LD("gg") + P(0) + EQ + NOT + REQ
    + A(0) + LD("gd") + NOT + REQ
    + CURSOR + A(0) + LD("ge") + P(REAP) + ADD + GT + REQ
    + IF(A(0) + LD("gf") + P(1) + EQ,
         A(0) + LD("ga") + A(0) + LD("gs") + PAY
         + A(0) + LD("gg") + A(0) + LD("gg") + LD("tp") + A(0) + LD("gs") + SUB + ST("tp"),
         A(0) + LD("gg") + A(0) + LD("gg") + LD("tk") + A(0) + LD("gs") + ADD + ST("tk"))
    + A(0) + LD("gg") + A(0) + LD("gg") + LD("tc")
        + A(0) + LD("gs") + P(COVER_NUM) + MUL + P(COVER_DEN) + DIV + SUB + ST("tc")
    + A(0) + P(6) + ST("gw")
    + A(0) + P(1) + ST("gd")
    + A(0) + P(0) + ST("gf")
    + A(0) + LD("gg") + A(0) + LD("gg") + LD("tx") + P(1) + ADD + ST("tx")
    + HALT)


# ---------------- PYTHON REFERENCE ----------------
def card_val(c):
    r = c % 13
    return (1 if r == 12 else 10 if r >= 9 else r + 2), (1 if r == 12 else 0)

def best(h, a):
    return h + (10 if a > 0 and h + 10 <= 21 else 0)

def ref_deal(bh, dh_, g):
    q = bh[dh_] + bh[dh_ + 1] + g * 64
    c0, c1 = vm_hash(q + 0) % 52, vm_hash(q + 1) % 52
    up = vm_hash(q + 16) % 52
    return c0, c1, up

def ref_hit(bh, hh, g, k):
    return vm_hash(bh[hh] + bh[hh + 1] + g * 64 + k) % 52

def ref_dealer(bh, sh, g, up):
    dq = bh[sh] + bh[sh + 1] + g * 64 + 32
    v, a = card_val(up)
    hh, aa = v, a
    v, a = card_val(vm_hash(dq + 0) % 52)
    hh += v; aa += a
    j = 1
    while best(hh, aa) < 17:
        v, a = card_val(vm_hash(dq + j) % 52)
        hh += v; aa += a; j += 1
    return best(hh, aa), (j == 1 and best(hh, aa) == 21)

def ref_outcome(stake, pb, pnat, db, dnat):
    """-> (pay, result-code)"""
    if pnat and dnat: return stake, 2
    if pnat: return stake * 5 // 2, 3
    if dnat: return 0, 4
    if db > 21 or db < pb: return stake * 2, 1
    if db == pb: return stake, 2
    return 0, 4


# ---------------- TESTS ----------------
H = Harness(CODE, accounts=("BANK", "B1", "B2", "EVE"), cursor=1000, nonce="blackjack")
ck, call, bal, M, rv = H.ck, H.call, H.bal, H.M, H.rv

TBL = 3; BANKROLL = 10**12; STAKE = 10**9
call("open", [TBL], BANKROLL, "BANK")
ck("open banks the table", M("ta", TBL) == "BANK" and M("tk", TBL) == BANKROLL)

G = 201
call("deal", [G, TBL], STAKE, "B1")
ck("deal binds cursor+2 and reserves the 3/2 worst case",
   M("gh", G) == H.cursor + DEAL_D and M("gf", G) == 1 and M("tc", TBL) == STAKE * 3 // 2)
ck("hit before the deal resolves reverts", rv(call("hit", [G], 0, "B1")))
ck("reveal before the blocks exist reverts", rv(call("reveal", [G], 0, "EVE")))
gh = M("gh", G)
H.seed(gh - 1, gh + 2, "bj1")
H.cursor = gh + 1
c0, c1, up = ref_deal(H.st.block_hashes, gh, G)
call("reveal", [G], 0, "EVE")
v0, a0 = card_val(c0); v1, a1 = card_val(c1)
ck(f"reveal derives the hand (cards {c0},{c1} up {up}) — hard {v0+v1}, aces {a0+a1}",
   M("gp", G) == v0 + v1 and M("gq", G) == a0 + a1 and M("gn", G) == 2 and M("du", G) == up + 1 and M("gf", G) == 2)
ck("the exact cards are on-chain for the UI", M("pc", G * 16 + 0) == c0 + 1 and M("pc", G * 16 + 1) == c1 + 1)
ck("only the player may hit", rv(call("hit", [G], 0, "EVE")))
ck("only the player may stand", rv(call("stand", [G], 0, "EVE")))

# play the hand: hit while best < 15, then stand — differentially against the reference
ph, pa, pn = v0 + v1, a0 + a1, 2
while best(ph, pa) < 15 and ph <= 21:
    call("hit", [G], 0, "B1")
    hh = M("gh", G)
    H.seed(hh - 1, hh + 2, "bjh%d" % pn)
    H.cursor = hh + 1
    c = ref_hit(H.st.block_hashes, hh, G, pn)
    call("draw", [G], 0, "EVE")
    v, a = card_val(c)
    ph += v; pa += a; pn += 1
    ck(f"draw lands card {c} (hard {ph})", M("gp", G) == ph and M("gn", G) == pn)
    if ph > 21:
        ck("hard bust settles instantly to the bank", M("gd", G) == 1 and M("gw", G) == 5
           and M("tk", TBL) == BANKROLL + STAKE and M("tc", TBL) == 0)
if ph <= 21:
    call("stand", [G], 0, "B1")
    sh = M("gh", G)
    H.seed(sh - 1, sh + 2, "bjs")
    H.cursor = sh + 1
    db, dnat = ref_dealer(H.st.block_hashes, sh, G, up)
    pay, res = ref_outcome(STAKE, best(ph, pa), pn == 2 and best(ph, pa) == 21, db, dnat)
    b0 = bal("B1")
    call("settle", [G], 0, "EVE")
    ck(f"settle: dealer {db}{' natural' if dnat else ''} vs player {best(ph, pa)} → pay {pay}",
       bal("B1") == b0 + pay and M("gw", G) == res and M("gr", G) == db and M("tc", TBL) == 0)
    hole = vm_hash(H.st.block_hashes[sh] + H.st.block_hashes[sh + 1] + G * 64 + 32 + 0) % 52
    ck("the dealer's hole card is on-chain for the UI", M("dk", G * 16 + 0) == hole + 1)

# cover guard: a hand the bank can't 3/2-cover reverts at deal
call("open", [4], 10**6, "BANK")
ck("uncoverable deal reverts", rv(call("deal", [301, 4], 10**6, "B1")))

# reap: an undealt hand (pruned deal) refunds; a seen hand forfeits
call("deal", [302, TBL], STAKE, "B1")
H.cursor += REAP + 1
b1 = bal("B1")
call("reap", [302], 0, "EVE")
ck("reap refunds an undealt hand", bal("B1") == b1 + STAKE and M("gw", 302) == 6)
call("deal", [303, TBL], STAKE, "B1")
gh = M("gh", 303); H.seed(gh - 1, gh + 2, "bjr"); H.cursor = gh + 1
call("reveal", [303], 0, "EVE")
H.cursor += REAP + 1
b1 = bal("B1"); tk0 = M("tk", TBL)
call("reap", [303], 0, "EVE")
ck("reap FORFEITS a hand abandoned after seeing cards (anti keep-only-good-hands)",
   bal("B1") == b1 and M("tk", TBL) == tk0 + STAKE and M("gw", 303) == 6)

# ---------------- DIFFERENTIAL: random hands vs the reference ----------------
import random as _r
rng = _r.Random(0xB1AC)
mism = 0; n_done = 0; outcomes = [0] * 7
tk_mirror = M("tk", TBL); tc_mirror = 0
for k in range(400):
    g = 20_000 + k
    stake = rng.randrange(10**6, 10**9)
    who = rng.choice(["B1", "B2"])
    if rv(call("deal", [g, TBL], stake, who)): mism += 1; continue
    tc_mirror += stake * 3 // 2
    gh = M("gh", g); H.seed(gh - 1, gh + 2, "dd%d" % k); H.cursor = gh + 1
    call("reveal", [g], 0, "EVE")
    c0, c1, up = ref_deal(H.st.block_hashes, gh, g)
    (v0, a0), (v1, a1) = card_val(c0), card_val(c1)
    ph, pa, pn = v0 + v1, a0 + a1, 2
    if M("gp", g) != ph or M("du", g) != up + 1: mism += 1
    hit_to = rng.randrange(12, 20)          # a random strategy: hit until best >= hit_to
    busted = False
    while best(ph, pa) < hit_to and pn < MAXCARDS:
        call("hit", [g], 0, who)
        hh = M("gh", g); H.seed(hh - 1, hh + 2, "dh%d.%d" % (k, pn)); H.cursor = hh + 1
        c = ref_hit(H.st.block_hashes, hh, g, pn)
        call("draw", [g], 0, "EVE")
        v, a = card_val(c); ph += v; pa += a; pn += 1
        if M("gp", g) != ph or M("gn", g) != pn: mism += 1
        if ph > 21:
            busted = True
            tc_mirror -= stake * 3 // 2; tk_mirror += stake
            if M("gd", g) != 1 or M("gw", g) != 5: mism += 1
            break
    if not busted:
        call("stand", [g], 0, who)
        sh = M("gh", g); H.seed(sh - 1, sh + 2, "ds%d" % k); H.cursor = sh + 1
        db, dnat = ref_dealer(H.st.block_hashes, sh, g, up)
        pay, res = ref_outcome(stake, best(ph, pa), pn == 2 and best(ph, pa) == 21, db, dnat)
        b0 = bal(who)
        call("settle", [g], 0, "EVE")
        tc_mirror -= stake * 3 // 2; tk_mirror += stake - pay
        if bal(who) != b0 + pay or M("gw", g) != res or M("gr", g) != db: mism += 1
    outcomes[M("gw", g)] += 1
    if M("tk", TBL) != tk_mirror or M("tc", TBL) != tc_mirror: mism += 1
    n_done += 1
ck(f"DIFFERENTIAL: {n_done} hands bytecode==reference (mism={mism}; win {outcomes[1]} push {outcomes[2]} "
   f"BJ {outcomes[3]} lose {outcomes[4]} bust {outcomes[5]})",
   mism == 0 and n_done == 400 and outcomes[1] > 80 and outcomes[4] > 80 and outcomes[5] > 30 and outcomes[3] > 2)
ck("all covers released", M("tc", TBL) == 0)

# bank lifecycle
call("close", [4], 0, "BANK")
bB = bal("BANK")
call("close", [TBL], 0, "BANK")
ck("close pays the pool back to the bank", bal("BANK") > bB and M("tz", TBL) == 1)
ck("deal on a closed table reverts", rv(call("deal", [99999, TBL], STAKE, "B1")))
ck("contract drains to zero", bal(H.cid) == 0)

H.finish("blackjack.json", extra=f"settle = {len(CODE['settle'])} instr")
