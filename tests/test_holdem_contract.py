# tests/test_holdem_contract.py — MULTIPLAYER TEXAS HOLD'EM (stackvm) with PROPER TABLE STAKES: buy-in
# stacks, all-in, layered SIDE POTS with exact splits. Commit-reveal hole cards, beacon community cards,
# deadline-based betting streets, on-chain 7-card showdown. No house, no dealer, no turn order.
#
# THE HAND (all heights derived from d0 = the DEAL anchor; S=30 per street, R=60 reveal):
#   seating             open/join escrow buy-ins; seating stays open INDEFINITELY — there is NO timer.
#                       The HOST controls the start: start(t) sets d0 = td[t] = cursor+2 ("deal now" —
#                       two blocks that don't exist yet when the host signs, so the deal stays unknowable).
#                       Before the deal any NON-host seat may leave(g) for a full refund; the host cancels.
#   d0 = td[t]          hole cards seeded by BH(d0),BH(d0+1) + each player's SECRET (committed at
#                       open/join as HASH(x) — only you can compute your cards, the chain verifies later)
#   (d0,     d0+S ]     PREFLOP betting     flop   = BH(d0+S),BH(d0+S+1)   ← unknowable while you bet
#   (d0+S,   d0+2S]     FLOP betting        turn   = BH(d0+2S),BH(d0+2S+1)
#   (d0+2S,  d0+3S]     TURN betting        river  = BH(d0+3S),BH(d0+3S+1)
#   (d0+3S,  d0+4S]     RIVER betting
#   (d0+4S,  d0+4S+R]   SHOWDOWN: reveal(g, x) — verify commit, derive 7 cards, rank ON-CHAIN (eval7_ops,
#                       4000/4000 differential-verified incl. kickers).
#   after d0+4S+R       settle(t): SIDE-POT distribution (below) + every seat's unspent stack refunded.
#                       EARLY SETTLE: once EVERY seat has revealed (tx==tn) settle runs immediately —
#                       no dead waiting when the whole table already showed their hands.
#
# TABLE STAKES: open/join escrow a BUY-IN (>= the ante); the ante goes to the pot, the rest is your STACK
# gk[g]. bet(g, amt) moves amt from your stack into the street — no new escrow mid-hand. Betting is
# no-limit up to your stack; exceeding the street price ms[t*8+k] is a RAISE (blocked in the last GRACE
# blocks so it's always callable). ALL-IN = your stack hits 0: you stay eligible for every pot layer you
# funded even when you can't match later prices. Anyone else below the price at street close is FOLDED
# (their pot chips forfeit; their unspent stack always comes back at settle).
#
# SIDE POTS (settle): let C_i = ante + Σ street contributions. Process the distinct C levels ascending:
# layer j spans (L_{j-1}, L_j] and holds (L_j - L_{j-1}) × |{i: C_i >= L_j}|. The layer goes to the best
# revealed hand among seats with C_i >= L_j, SPLIT EVENLY on ties (remainder to the first winner in join
# order). A layer no revealed hand covers: refunded if it has a single contributor (the uncalled-bet rule),
# otherwise it goes to the best revealed hand overall. Every seat's leftover stack is refunded, folded or not.
import sys, os, json, tempfile, random
sys.path.insert(0, "/root/nado"); sys.path.insert(0, "/root/nado/tests")
from execnode.state import ExecState
from execnode.vm import GAS_LIMIT
from holdem_onchain import (vm_hash, draw, hole_ref, board_ref, eval7_ref, deal_ops, eval7_ops,
                            P, A, LD, STm, LDR, STR, LDK, STK, ADD, SUB, MUL, MOD, DIV, EQ, LT, GT, GTE,
                            AND, OR, NOT, HASH, JUMPI)

CURSOR=[["CURSOR"]]; VALUE=[["VALUE"]]; BLOCKHASH=[["BLOCKHASH"]]; CALLER=[["CALLER"]]
PAY=[["PAY"]]; REQ=[["REQUIRE"]]; HALT=[["HALT"]]; LTE=[["LTE"]]
S, GRACE, R = 30, 5, 60
MAXP = 9                     # poker-standard table cap; also bounds settle's O(n²) loops + the payout list

# table t: ta=host t0=openHeight td=dealAnchor(0=seating) ts=ante tp=pot tn=seats tx=reveals tw=bestValue
#          tb=leaderSeat tz=closed
#          ms[t*8+k]=street-k price (k=1..4) · ti[t*16+i]=seat id at join index i (0..tn-1)
# seat g:  gg=tableId ga=addr gc=commitHash gk=stack gd=revealed gsc=handValue gr=revealedSecret
#          cs[g*8+k]=street-k contribution
# scratch S arrays during settle (i = join index): 600+i=C_i 700+i=V_i 800+i=payout_i 900+i=seatId_i

def loop_i(n_expr_reg, body_fn):
    """i = 0 .. S[n_expr_reg]-1 (dynamic bound, e.g. tn)."""
    ops = STR("i", P(0))
    top = len(ops)
    ops = ops + body_fn() + STR("i", LDR("i") + P(1) + ADD)
    ops += LDR("i") + LDR(n_expr_reg) + LT
    j_at = len(ops) + 1
    ops += P(top - j_at) + JUMPI
    return ops

open_m = (VALUE+P(0)+GT+REQ
  + A(0)+P(0)+GT+REQ + A(0)+LD("ta")+P(0)+EQ+REQ          # fresh table id
  + A(1)+P(0)+GT+REQ + A(1)+LD("gg")+P(0)+EQ+REQ          # fresh seat id
  + A(2)+P(0)+EQ+NOT+REQ                                   # commit present
  + A(3)+P(0)+GT+REQ + VALUE+A(3)+GTE+REQ                  # ante > 0; buy-in covers the ante
  + A(0)+CALLER+STm("ta") + A(0)+CURSOR+STm("t0")
  + A(0)+A(3)+STm("ts") + A(0)+A(3)+STm("tp") + A(0)+P(1)+STm("tn")
  + A(1)+A(0)+STm("gg") + A(1)+CALLER+STm("ga") + A(1)+A(2)+STm("gc")
  + A(1)+VALUE+A(3)+SUB+STm("gk")                          # stack = buy-in - ante
  + (A(0)+P(16)+MUL) + A(1) + STm("ti")                    # join-order index 0
  + HALT)

join_m = (VALUE+P(0)+GT+REQ
  + A(1)+P(0)+GT+REQ + A(1)+LD("gg")+P(0)+EQ+REQ
  + A(0)+LD("ta")+P(0)+EQ+NOT+REQ + A(0)+LD("tz")+NOT+REQ
  + VALUE+A(0)+LD("ts")+GTE+REQ                            # buy-in covers the ante (rest = stack, your choice)
  + A(0)+LD("td")+P(0)+EQ+REQ                              # seating open until the HOST deals — no timer
  + A(0)+LD("tn")+P(MAXP)+LT+REQ                           # table cap
  + A(2)+P(0)+EQ+NOT+REQ
  + A(0)+A(0)+LD("tp")+A(0)+LD("ts")+ADD+STm("tp")
  + A(1)+A(0)+STm("gg") + A(1)+CALLER+STm("ga") + A(1)+A(2)+STm("gc")
  + A(1)+VALUE+A(0)+LD("ts")+SUB+STm("gk")
  + (A(0)+P(16)+MUL+A(0)+LD("tn")+ADD) + A(1) + STm("ti")
  + A(0)+A(0)+LD("tn")+P(1)+ADD+STm("tn")
  + HALT)

# start(t): the HOST deals — binds the hand to two blocks that don't exist yet (nobody, host included,
# can know the cards when signing). The game NEVER starts on its own; until then seats may leave().
start_m = (CALLER+A(0)+LD("ta")+EQ+REQ
  + A(0)+LD("tz")+NOT+REQ
  + A(0)+LD("td")+P(0)+EQ+REQ                              # deal once
  + A(0)+CURSOR+P(2)+ADD+STm("td")
  + HALT)

# leave(g): before the deal a NON-host seat exits with a FULL refund (ante + stack) — the liveness
# escape for a host who never deals. Join order stays compact: the last seat moves into the hole.
leave_m = (A(0)+LD("gg")+P(0)+EQ+NOT+REQ
  + CALLER+A(0)+LD("ga")+EQ+REQ
  + STR("t", A(0)+LD("gg"))
  + LDR("t")+LD("tz")+NOT+REQ
  + LDR("t")+LD("td")+P(0)+EQ+REQ                          # only while seating is open
  + CALLER + LDR("t")+LD("ta") + EQ+NOT+REQ                # the host cancels instead of leaving
  + STR("n", LDR("t")+LD("tn"))
  + STR("ix", P(0))
  + loop_i("n", lambda: STR("_h", (LDR("t")+P(16)+MUL+LDR("i")+ADD+LD("ti")) + A(0) + EQ)
                        + STR("ix", LDR("ix") + LDR("_h") + (LDR("i")+LDR("ix")+SUB) + MUL + ADD))
  + STR("lg", (LDR("t")+P(16)+MUL+LDR("n")+ADD+P(1)+SUB) + LD("ti"))
  + (LDR("t")+P(16)+MUL+LDR("ix")+ADD) + LDR("lg") + STm("ti")
  + LDR("t") + LDR("n")+P(1)+SUB + STm("tn")
  + LDR("t") + (LDR("t")+LD("tp")) + (LDR("t")+LD("ts")) + SUB + STm("tp")
  + CALLER + (LDR("t")+LD("ts")) + A(0)+LD("gk") + ADD + PAY
  + A(0)+P(0)+STm("gk") + A(0)+P(0)+STm("gg")
  + HALT)

def _match_loop_bet():
    """bet: REQUIRE cs[g*8+j]==ms[t*8+j] for closed streets j<k (an all-in player can never reach bet)."""
    ops = STR("j", P(1))
    top = len(ops)
    match = (A(0)+P(8)+MUL+LDR("j")+ADD+LD("cs")) + (LDR("t")+P(8)+MUL+LDR("j")+ADD+LD("ms")) + EQ
    ops += (LDR("j")+LDR("k")+GTE) + match + OR + REQ
    ops += STR("j", LDR("j")+P(1)+ADD)
    ops += LDR("j")+P(4)+LT
    j_at = len(ops)+1
    ops += P(top - j_at) + JUMPI
    return ops

# bet(g, amt): move amt from YOUR STACK into the current street. No value rides the call.
bet_m = (VALUE+P(0)+EQ+REQ
  + A(1)+P(0)+GT+REQ
  + A(0)+LD("gg")+P(0)+EQ+NOT+REQ
  + CALLER+A(0)+LD("ga")+EQ+REQ
  + STR("t", A(0)+LD("gg"))
  + LDR("t")+LD("tz")+NOT+REQ
  + A(1)+A(0)+LD("gk")+LTE+REQ                             # table stakes: you bet what you brought
  + STR("d0", LDR("t")+LD("td"))
  + LDR("d0")+P(0)+EQ+NOT+REQ                              # the host has dealt
  + CURSOR+LDR("d0")+GTE+REQ
  + CURSOR+LDR("d0")+P(4*S)+ADD+LT+REQ
  + STR("k", CURSOR+LDR("d0")+SUB+P(S)+DIV+P(1)+ADD)
  + _match_loop_bet()
  + A(0) + A(0)+LD("gk")+A(1)+SUB + STm("gk")
  + STR("nc", A(0)+P(8)+MUL+LDR("k")+ADD+LD("cs") + A(1) + ADD)
  + A(0)+P(8)+MUL+LDR("k")+ADD + LDR("nc") + STm("cs")
  + LDR("t") + LDR("t")+LD("tp")+A(1)+ADD + STm("tp")
  + STR("mk", LDR("t")+P(8)+MUL+LDR("k")+ADD+LD("ms"))
  + STR("isR", LDR("nc")+LDR("mk")+GT)
  + LDR("isR")+NOT + (CURSOR + LDR("d0")+LDR("k")+P(S)+MUL+ADD+P(GRACE)+SUB + LTE) + OR + REQ
  + LDR("t")+P(8)+MUL+LDR("k")+ADD + LDR("mk") + LDR("isR") + (LDR("nc")+LDR("mk")+SUB) + MUL + ADD + STm("ms")
  + HALT)

def _match_loop_reveal():
    """reveal: for every street, matched OR all-in (stack exhausted) — the table-stakes eligibility rule."""
    ops = STR("j", P(1))
    top = len(ops)
    match = (A(0)+P(8)+MUL+LDR("j")+ADD+LD("cs")) + (LDR("t")+P(8)+MUL+LDR("j")+ADD+LD("ms")) + EQ
    allin = A(0)+LD("gk")+P(0)+EQ
    ops += match + allin + OR + REQ
    ops += STR("j", LDR("j")+P(1)+ADD)
    ops += LDR("j")+P(5)+LT
    j_at = len(ops)+1
    ops += P(top - j_at) + JUMPI
    return ops

reveal_m = (A(0)+LD("gg")+P(0)+EQ+NOT+REQ
  + A(0)+LD("gd")+NOT+REQ
  + STR("t", A(0)+LD("gg"))
  + LDR("t")+LD("tz")+NOT+REQ
  + STR("d0", LDR("t")+LD("td"))
  + LDR("d0")+P(0)+EQ+NOT+REQ                              # the host has dealt
  + CURSOR+LDR("d0")+P(4*S)+ADD+GTE+REQ
  + CURSOR+LDR("d0")+P(4*S+R)+ADD+LT+REQ
  + A(1)+HASH + A(0)+LD("gc") + EQ + REQ
  + _match_loop_reveal()
  + deal_ops(
      LDR("d0")+BLOCKHASH + LDR("d0")+P(1)+ADD+BLOCKHASH + ADD + A(1) + ADD + HASH,
      LDR("d0")+P(S)+ADD+BLOCKHASH + LDR("d0")+P(S+1)+ADD+BLOCKHASH + ADD + LDR("t") + ADD + HASH,
      LDR("d0")+P(2*S)+ADD+BLOCKHASH + LDR("d0")+P(2*S+1)+ADD+BLOCKHASH + ADD + LDR("t") + ADD + HASH,
      LDR("d0")+P(3*S)+ADD+BLOCKHASH + LDR("d0")+P(3*S+1)+ADD+BLOCKHASH + ADD + LDR("t") + ADD + HASH)
  + eval7_ops("val")
  + A(0) + LDR("val") + STm("gsc")
  + A(0) + A(1) + STm("gr")
  + A(0) + P(1) + STm("gd")
  + LDR("t") + LDR("t")+LD("tx")+P(1)+ADD + STm("tx")
  + STR("w", A(0)+LD("gsc") + LDR("t")+LD("tw") + GT)
  + LDR("t") + LDR("t")+LD("tw") + LDR("w") + (A(0)+LD("gsc") + LDR("t")+LD("tw") + SUB) + MUL + ADD + STm("tw")
  + LDR("t") + LDR("t")+LD("tb") + LDR("w") + (A(0) + LDR("t")+LD("tb") + SUB) + MUL + ADD + STm("tb")
  + HALT)

def _gather_ops():
    """settle phase A (i = 0..tn-1): seatId->S[900+i]; payout_i = leftover stack (refund, folded or not),
    stack zeroed; C_i = ante + Σ street contributions -> S[600+i]; V_i = revealed hand value (0 = mucked)."""
    ops = []
    def b():
        o = STR("g", (A(0)+P(16)+MUL+LDR("i")+ADD) + LD("ti"))
        o += STK(P(900)+LDR("i")+ADD, LDR("g"))
        o += STK(P(800)+LDR("i")+ADD, LDR("g")+LD("gk"))
        o += LDR("g") + P(0) + STm("gk")
        csum = A(0)+LD("ts")
        for k in range(1, 5):
            csum = csum + (LDR("g")+P(8)+MUL+P(k)+ADD+LD("cs")) + ADD
        o += STK(P(600)+LDR("i")+ADD, csum)
        o += STK(P(700)+LDR("i")+ADD, (LDR("g")+LD("gd")) + (LDR("g")+LD("gsc")) + MUL)
        return o
    ops += loop_i("n", b)
    return ops

def _settle_core():
    """settle phase B: layered side pots into payout_i, then phase C: one PAY per seat."""
    ops = []
    # overall best (first argmax in join order) — fallback recipient for uncovered multi-way layers
    ops += STR("obv", P(0)) + STR("obi", P(0))
    def ob_body():
        gtv = LDK(P(700)+LDR("i")+ADD) + LDR("obv") + GT
        o = STR("_g", gtv)
        o += STR("obi", LDR("obi") + LDR("_g") + (LDR("i")+LDR("obi")+SUB) + MUL + ADD)
        o += STR("obv", LDR("obv") + LDR("_g") + (LDK(P(700)+LDR("i")+ADD)+LDR("obv")+SUB) + MUL + ADD)
        return o
    ops += loop_i("n", ob_body)
    # layers: at most n distinct levels; run MAXP+1 passes with an 'act' flag
    ops += STR("prev", P(0)) + STR("act", P(1))
    def layer_body():
        o = []
        # L = min C_i > prev (0 if none)
        o += STR("L", P(0))
        def minb():
            c = LDK(P(600)+LDR("i")+ADD)
            take = STR("_c", c) + STR("_t", (LDR("_c")+LDR("prev")+GT) + ((LDR("L")+P(0)+EQ) + (LDR("_c")+LDR("L")+LT) + OR) + AND)
            upd = STR("L", LDR("L") + LDR("_t") + (LDR("_c")+LDR("L")+SUB) + MUL + ADD)
            return take + upd
        o += loop_i("n", minb)
        o += STR("act", LDR("act") + (LDR("L")+P(0)+GT) + AND)
        # cnt = coverers; best = best revealed value among coverers
        o += STR("cnt", P(0)) + STR("best", P(0))
        def scanb():
            cov = LDK(P(600)+LDR("i")+ADD) + LDR("L") + GTE
            s1 = STR("_c", cov)
            s2 = STR("cnt", LDR("cnt") + LDR("_c") + ADD)
            ev = STR("_v", LDR("_c") + (LDK(P(700)+LDR("i")+ADD)) + MUL)
            s3 = STR("best", LDR("best") + (LDR("_v")+LDR("best")+GT) + (LDR("_v")+LDR("best")+SUB) + MUL + ADD)
            return s1 + s2 + ev + s3
        o += loop_i("n", scanb)
        o += STR("amt", LDR("act") + (LDR("L")+LDR("prev")+SUB) + MUL + LDR("cnt") + MUL)
        # wins = ties among covering winners; split share + remainder to the first
        o += STR("wins", P(0))
        def winb():
            w = (LDK(P(600)+LDR("i")+ADD)+LDR("L")+GTE) + (LDK(P(700)+LDR("i")+ADD)+LDR("best")+EQ) + AND + (LDR("best")+P(0)+GT) + AND
            return STR("wins", LDR("wins") + w + ADD)
        o += loop_i("n", winb)
        o += STR("wmax", LDR("wins") + (LDR("wins")+P(0)+EQ) + ADD)     # avoid div-by-zero
        o += STR("share", LDR("amt") + LDR("wmax") + DIV)
        o += STR("rem", LDR("amt") + LDR("wmax") + MOD)
        # uncovered-layer flags: single contributor -> refund; multi -> overall best
        o += STR("rf", (LDR("best")+P(0)+EQ) + (LDR("cnt")+P(1)+EQ) + AND)
        o += STR("ob", (LDR("best")+P(0)+EQ) + (LDR("cnt")+P(1)+GT) + AND)
        o += STR("fst", P(1))
        def payb():
            w = STR("_w", (LDK(P(600)+LDR("i")+ADD)+LDR("L")+GTE) + (LDK(P(700)+LDR("i")+ADD)+LDR("best")+EQ) + AND + (LDR("best")+P(0)+GT) + AND)
            pay = (LDR("_w") + LDR("share") + MUL) \
                + (LDR("_w") + LDR("fst") + AND + LDR("rem") + MUL) + ADD \
                + (LDR("rf") + (LDK(P(600)+LDR("i")+ADD)+LDR("L")+GTE) + AND + LDR("amt") + MUL) + ADD \
                + (LDR("ob") + (LDR("i")+LDR("obi")+EQ) + AND + LDR("amt") + MUL) + ADD
            add = STK(P(800)+LDR("i")+ADD, LDK(P(800)+LDR("i")+ADD) + pay + ADD)
            adv = STR("fst", LDR("fst") + LDR("_w") + NOT + AND)
            return w + add + adv
        o += loop_i("n", payb)
        o += STR("prev", LDR("prev") + LDR("act") + (LDR("L")+LDR("prev")+SUB) + MUL + ADD)
        return o
    # one layer pass per distinct contribution level — LOOPED (unrolling 10x blew the deploy blob cap)
    ops += STR("lc", P(MAXP + 1))
    _top = len(ops)
    body = layer_body() + STR("lc", LDR("lc") + P(1) + SUB)
    ops += body
    ops += LDR("lc") + P(0) + GT
    _j = len(ops) + 1
    ops += P(_top - _j) + JUMPI
    # phase C: one PAY per seat (PAY of 0 is a no-op; <= MAXP payouts, under the VM cap)
    def payout_body():
        return (LDK(P(900)+LDR("i")+ADD) + LD("ga")) + LDK(P(800)+LDR("i")+ADD) + PAY
    ops += loop_i("n", payout_body)
    return ops

settle_m = (A(0)+LD("ta")+P(0)+EQ+NOT+REQ
  + A(0)+LD("tz")+NOT+REQ
  + A(0)+LD("td")+P(0)+EQ+NOT+REQ                          # a hand was dealt
  # the reveal window ended — OR every seat already revealed (nothing left to wait for: settle NOW)
  + (CURSOR + A(0)+LD("td")+P(4*S+R)+ADD + GTE)
  + (A(0)+LD("tx") + A(0)+LD("tn") + EQ) + OR + REQ
  + A(0)+LD("tb")+P(0)+EQ+NOT+REQ                          # someone showed a hand
  + STR("n", A(0)+LD("tn"))
  + _gather_ops()
  + _settle_core()
  + A(0)+P(1)+STm("tz") + A(0)+P(0)+STm("tp")
  + HALT)

# reclaim: NOBODY revealed — every stack comes back, the dead pot goes to the host
reclaim_m = (CALLER+A(0)+LD("ta")+EQ+REQ
  + A(0)+LD("tz")+NOT+REQ
  + A(0)+LD("td")+P(0)+EQ+NOT+REQ                          # a hand was dealt (else cancel/leave)
  + CURSOR + A(0)+LD("td")+P(4*S+R)+ADD + GTE + REQ
  + A(0)+LD("tb")+P(0)+EQ+REQ
  + STR("n", A(0)+LD("tn"))
  + loop_i("n", lambda: (
      STR("g", (A(0)+P(16)+MUL+LDR("i")+ADD) + LD("ti"))
      + (LDR("g")+LD("ga")) + (LDR("g")+LD("gk")) + PAY
      + LDR("g") + P(0) + STm("gk")))
  + A(0)+LD("ta") + A(0)+LD("tp") + PAY
  + A(0)+P(1)+STm("tz") + A(0)+P(0)+STm("tp")
  + HALT)

cancel_m = (CALLER+A(0)+LD("ta")+EQ+REQ                    # host alone — refund ante + stack, close
  + A(0)+LD("tz")+NOT+REQ
  + A(0)+LD("tn")+P(1)+EQ+REQ
  + STR("g", (A(0)+P(16)+MUL) + LD("ti"))
  + A(0)+LD("ta") + A(0)+LD("tp") + (LDR("g")+LD("gk")) + ADD + PAY
  + LDR("g") + P(0) + STm("gk")
  + A(0)+P(1)+STm("tz") + A(0)+P(0)+STm("tp")
  + HALT)

# ONE-OFF RESCUE (remove in the NEXT upgrade): tables opened BEFORE the start-flow upgrade have no td and
# can never be played under the new rules — anyone may annul such a table, refunding every seat its FULL
# buy-in (ante + street chips + stack). Height-fenced so no post-upgrade table can ever match.
RESCUE_BEFORE = 7850         # the 2026-07-11 upgrade landed under this height on the live chain
rescue_m = (A(0)+LD("ta")+P(0)+EQ+NOT+REQ
  + A(0)+LD("tz")+NOT+REQ
  + A(0)+LD("td")+P(0)+EQ+REQ                              # never dealt under the new rules
  + A(0)+LD("t0")+P(RESCUE_BEFORE)+LT+REQ                  # pre-upgrade tables ONLY
  + STR("n", A(0)+LD("tn"))
  + loop_i("n", lambda: (
      STR("g", (A(0)+P(16)+MUL+LDR("i")+ADD) + LD("ti"))
      + STR("amt", A(0)+LD("ts") + (LDR("g")+LD("gk")) + ADD
                   + (LDR("g")+P(8)+MUL+P(1)+ADD+LD("cs")) + ADD
                   + (LDR("g")+P(8)+MUL+P(2)+ADD+LD("cs")) + ADD
                   + (LDR("g")+P(8)+MUL+P(3)+ADD+LD("cs")) + ADD
                   + (LDR("g")+P(8)+MUL+P(4)+ADD+LD("cs")) + ADD)
      + (LDR("g")+LD("ga")) + LDR("amt") + PAY
      + LDR("g") + P(0) + STm("gk")))
  + A(0)+P(1)+STm("tz") + A(0)+P(0)+STm("tp")
  + HALT)

CODE = {"open":open_m, "join":join_m, "start":start_m, "leave":leave_m, "bet":bet_m, "reveal":reveal_m,
        "settle":settle_m, "reclaim":reclaim_m, "cancel":cancel_m, "rescue":rescue_m}

# ---------------- PYTHON REFERENCE for the side-pot distribution (mirrors settle_m exactly) ----------------
def settle_ref(seats):
    """seats: [(C_i, V_i)] in JOIN ORDER — C = total pot contribution (ante+streets), V = revealed packed
    hand value (0 = folded/mucked). Returns pot payouts per index (stack refunds are separate)."""
    n = len(seats)
    pays = [0]*n
    obv, obi = 0, 0
    for i,(c,v) in enumerate(seats):
        if v > obv: obv, obi = v, i
    prev = 0
    for _ in range(MAXP + 1):
        L = 0
        for c,_ in seats:
            if c > prev and (L == 0 or c < L): L = c
        if L == 0: break
        cnt = sum(1 for c,_ in seats if c >= L)
        best = max([v for c,v in seats if c >= L], default=0)
        amt = (L - prev) * cnt
        winners = [i for i,(c,v) in enumerate(seats) if c >= L and v == best and best > 0]
        if winners:
            share, rem = divmod(amt, len(winners))
            for w in winners: pays[w] += share
            pays[winners[0]] += rem
        elif cnt == 1:
            for i,(c,v) in enumerate(seats):
                if c >= L: pays[i] += amt
        else:
            pays[obi] += amt
        prev = L
    return pays

# ---------------- TESTS ----------------
F=[]
def ck(n,c): print(("  ok  " if c else " FAIL ")+n); (F.append(n) if not c else None)

st=ExecState(tempfile.mktemp()); st.cursor=1000
for a in ["HOST"]+["P%d"%i for i in range(12)]: st.credit_deposit(a, 10**9)
st.apply_blob({"op":"deploy","code":CODE,"runtime":"stackvm","nonce":"holdem"},"HOST","d0")
CID=list(st.contracts)[0]
def bal(a): return st.bridge.get(a,0)
def M(m,k): return st.contracts[CID]["storage"].get(m,{}).get(str(k))
def call(m,args,val,who): return st.apply_blob({"op":"call","contract":CID,"method":m,"args":args,"value":val},who,m+str(args)+str(st.cursor))
def seed_bh(lo, hi, tag):
    for h in range(lo, hi+1): st.block_hashes[h] = vm_hash([tag, h])

# a pre-upgrade-style table for the one-off rescue (opened under RESCUE_BEFORE, never dealt)
call("open",[90, 900, vm_hash(31), 500], 500+6000, "HOST"); call("join",[90, 901, vm_hash(32)], 500+800, "P8")

ANTE=1000
T = 50
xs = {500: 111111, 501: 222222, 502: 333333, 503: 444444}
T0 = st.cursor
call("open",[T, 500, vm_hash(xs[500]), ANTE], 51000, "HOST")     # buy-in 51000 -> stack 50000
ck("open: table, ante, host stack", M("ta",T)=="HOST" and M("ts",T)==ANTE and M("gk",500)==50000 and M("tp",T)==ANTE and M("ti",T*16)==500)
call("join",[T, 501, vm_hash(xs[501])], 31000, "P1")             # stack 30000
call("join",[T, 502, vm_hash(xs[502])], 11000, "P2")             # stack 10000 (short — will be forced all-in)
call("join",[T, 503, vm_hash(xs[503])], ANTE, "P3")              # stack 0: ALL-IN from the ante alone
ck("join: 4 seats, join order recorded, stacks", M("tn",T)==4 and M("ti",T*16+3)==503 and M("gk",502)==10000 and (M("gk",503) or 0)==0)
ck("buy-in below ante reverts", "revert" in call("join",[T, 599, 7], ANTE-1, "P4"))
ck("table cap enforced (const)", MAXP==9)
# THE HOST DEALS — nothing starts on its own
ck("bet before the deal reverts", "revert" in call("bet",[501, 100], 0, "P1"))
ck("non-host start reverts", "revert" in call("start",[T], 0, "P1"))
st.cursor += 7                                                   # seating stayed open well past the old timer
call("start",[T], 0, "HOST")
D0 = M("td",T)
ck("start binds the deal to cursor+2 (unknowable when signed)", D0 == st.cursor + 2)
ck("join after the deal reverts", "revert" in call("join",[T, 598, vm_hash(7)], ANTE, "P4"))
ck("double start reverts", "revert" in call("start",[T], 0, "HOST"))
st.cursor = D0 + 2

# ---- PREFLOP: P1 raises 20000; HOST calls; P2 can only all-in 10000; P3 already all-in at 0 ----
ck("bet with value attached reverts", "revert" in call("bet",[501, 100], 5, "P1"))
call("bet",[501, 20000], 0, "P1")
ck("raise from stack sets price + shrinks stack", M("ms",T*8+1)==20000 and M("gk",501)==10000)
call("bet",[500, 20000], 0, "HOST")
ck("bet beyond stack reverts", "revert" in call("bet",[502, 10001], 0, "P2"))
call("bet",[502, 10000], 0, "P2")                                 # all-in call (below price -> eligible via gk==0)
ck("all-in call: stack empty, below price", (M("gk",502) or 0)==0 and M("cs",502*8+1)==10000)
POT = 4*ANTE + 20000 + 20000 + 10000
ck("pot accumulates from stacks", M("tp",T)==POT)
# ---- FLOP: HOST bets 5000 more; P1 calls all-in with his last 10000? (bets 5000, keeps 5000) ----
st.cursor = D0 + S + 2
call("bet",[500, 5000], 0, "HOST"); call("bet",[501, 5000], 0, "P1")
POT += 10000
# ---- TURN/RIVER: checks ----
seed_bh(D0, D0+3*S+1, "hand1")
st.cursor = D0 + 4*S + 1

# ---- SHOWDOWN: HOST, P1, P2 reveal; P3 (all-in from ante) reveals too ----
board = board_ref(st.block_hashes, D0, S, T)
vals={}
for g,who in ((500,"HOST"),(501,"P1"),(502,"P2")):
    res = call("reveal",[g, xs[g]], 0, who)
    vals[g] = eval7_ref(board + hole_ref(st.block_hashes, D0, xs[g]))
    ck(f"reveal ok for {who} (all-in eligibility incl.)", M("gd",g)==1 and M("gsc",g)==vals[g])
ck("settle blocked while reveals may still come (window open, 3/4 shown)", "revert" in call("settle",[T],0,"anyone"))
call("reveal",[503, xs[503]], 0, "P3")
vals[503] = eval7_ref(board + hole_ref(st.block_hashes, D0, xs[503]))
ck("reveal ok for P3 (all-in eligibility incl.)", M("gd",503)==1 and M("gsc",503)==vals[503])
# ---- SETTLE — EARLY: everyone revealed, so no waiting for the reveal window to close ----
C = [ANTE+25000, ANTE+25000, ANTE+10000, ANTE]
ref = settle_ref(list(zip(C, [vals[500],vals[501],vals[502],vals[503]])))
pre = {w: bal(w) for w in ("HOST","P1","P2","P3")}
stacks = {500: M("gk",500), 501: M("gk",501), 502: 0, 503: 0}
call("settle",[T],0,"anyone")
gains = {"HOST": bal("HOST")-pre["HOST"], "P1": bal("P1")-pre["P1"], "P2": bal("P2")-pre["P2"], "P3": bal("P3")-pre["P3"]}
expect = {"HOST": ref[0]+stacks[500], "P1": ref[1]+stacks[501], "P2": ref[2], "P3": ref[3]}
ck(f"SIDE POTS: on-chain payouts == reference (+stack refunds) {gains}", gains==expect)
ck("all pot money distributed (conservation)", sum(ref)==POT and M("tz",T)==1)
ck("re-settle reverts", "revert" in call("settle",[T],0,"anyone"))

# ---- randomized differential: many tables, random stacks/bets/folds/all-ins vs settle_ref ----
rng = random.Random(0x51DE)
mism = 0; hands = 0
for it in range(14):
    st.cursor = 40000 + it*1000
    t = 800+it; t0 = st.cursor
    ante = rng.randrange(100, 2000)
    seats = []
    for j in range(rng.randrange(2, 6)):
        g = t*10+j; x = rng.randrange(2**64); who = "P%d" % (j % 12)
        stack = rng.choice([0, ante, ante*3, ante*20, ante*50])
        if j==0: call("open",[t, g, vm_hash(x), ante], ante+stack, who)
        else:    call("join",[t, g, vm_hash(x)], ante+stack, who)
        seats.append({"g": g, "x": x, "who": who, "stack": stack, "spent": 0, "out": False})
    st.cursor += rng.randrange(0, 40)                       # the host deals whenever they feel like it
    call("start",[t], 0, seats[0]["who"])
    d0 = M("td",t)
    for k in range(1, 5):
        st.cursor = d0 + (k-1)*S + 2
        price = 0
        for sd in seats:
            if sd["out"] or sd["stack"] - sd["spent"] <= 0: continue
            r = rng.random()
            if r < 0.25: sd["out"] = (price > 0)  # check-fold: folded only if there's a price to duck
            elif r < 0.9:
                left = sd["stack"] - sd["spent"]
                amt = min(left, max(1, rng.randrange(1, max(2, price*2 or ante*3))))
                if "revert" in str(call("bet",[sd["g"], amt], 0, sd["who"])): continue
                sd["spent"] += amt
                price = max(price, M("cs", sd["g"]*8+k) or 0)
        # anyone below price with chips left is folded at street close
        for sd in seats:
            if not sd["out"] and sd["stack"]-sd["spent"] > 0 and (M("cs",sd["g"]*8+k) or 0) < (M("ms",t*8+k) or 0):
                sd["out"] = True
    seed_bh(d0, d0+3*S+1, "rt%d"%it)
    st.cursor = d0 + 4*S + 1
    board = board_ref(st.block_hashes, d0, S, t)
    anyrev = False
    for sd in seats:
        if sd["out"] or rng.random() < 0.12: continue           # some muck on purpose
        if "revert" not in str(call("reveal",[sd["g"], sd["x"]], 0, sd["who"])): anyrev = True
    st.cursor = d0 + 4*S + R + 1
    if not anyrev:
        call("reclaim",[t],0,seats[0]["who"]); continue
    Cs = [(ante + sum((M("cs",sd["g"]*8+k) or 0) for k in range(1,5)), (M("gsc",sd["g"]) or 0) if M("gd",sd["g"]) else 0) for sd in seats]
    ref = settle_ref(Cs)
    pre = {}; stk = {}
    for sd in seats: pre[sd["g"]] = bal(sd["who"]); stk[sd["g"]] = M("gk",sd["g"]) or 0
    call("settle",[t],0,"anyone")
    # NOTE: the same player name can hold several seats — compare per-player aggregate deltas
    exp = {}
    for i,sd in enumerate(seats):
        exp[sd["who"]] = exp.get(sd["who"], 0) + ref[i] + stk[sd["g"]]
    seen = set()
    okhand = True
    for sd in seats:
        if sd["who"] in seen: continue
        seen.add(sd["who"])
        if bal(sd["who"]) - pre[sd["g"]] != exp[sd["who"]]:
            okhand = False
    # pre was recorded per seat (same player overwrites — use first seat's snapshot per player)
    hands += 1
    if not okhand: mism += 1
ck(f"E2E DIFFERENTIAL: {hands-mism}/{hands} random side-pot settlements bytecode==reference", mism==0)

# reclaim + cancel refunds with stacks
st.cursor = 90000
call("open",[60, 600, vm_hash(9), ANTE], ANTE+7777, "HOST"); call("join",[60, 601, vm_hash(10)], ANTE+555, "P5")
ck("reclaim before any deal reverts (nothing to reclaim — leave/cancel instead)", "revert" in call("reclaim",[60],0,"HOST"))
call("start",[60],0,"HOST")
st.cursor = M("td",60) + 4*S + R + 1
b0=bal("HOST"); b1=bal("P5")
call("reclaim",[60],0,"HOST")
ck("reclaim: stacks refunded + dead pot to host", bal("HOST")==b0+7777+2*ANTE and bal("P5")==b1+555 and M("tz",60)==1)
st.cursor = 95000
call("open",[61, 610, vm_hash(11), ANTE], ANTE+4242, "HOST")
b0=bal("HOST"); call("cancel",[61],0,"HOST")
ck("cancel: full buy-in refunded", bal("HOST")==b0+ANTE+4242 and M("tz",61)==1)

# leave: pre-deal exit with a FULL refund; join order compacts; the host cannot leave
st.cursor = 97000
call("open",[70, 700, vm_hash(21), ANTE], ANTE+1111, "HOST")
call("join",[70, 701, vm_hash(22)], ANTE+2222, "P6")
call("join",[70, 702, vm_hash(23)], ANTE+3333, "P7")
ck("host cannot leave (cancel instead)", "revert" in call("leave",[700],0,"HOST"))
ck("you can only leave YOUR seat", "revert" in call("leave",[701],0,"P7"))
b=bal("P6")
call("leave",[701],0,"P6")
ck("leave: full refund, seat freed, order compacted, pot shrunk",
   bal("P6")==b+ANTE+2222 and M("tn",70)==2 and M("ti",70*16+1)==702 and (M("gg",701) or 0)==0 and M("tp",70)==2*ANTE)
ck("leave twice reverts", "revert" in call("leave",[701],0,"P6"))
call("start",[70],0,"HOST")
ck("leave after the deal reverts", "revert" in call("leave",[702],0,"P7"))
st.cursor = M("td",70) + 4*S + R + 1
b0=bal("HOST"); b1=bal("P7")
call("reclaim",[70],0,"HOST")
ck("reclaim honours the post-leave roster", bal("HOST")==b0+1111+2*ANTE and bal("P7")==b1+3333 and M("tz",70)==1)

# one-off rescue: the pre-upgrade table (90) annuls with FULL refunds; post-upgrade tables never match
call("open",[71, 710, vm_hash(24), ANTE], ANTE+100, "HOST")
ck("rescue of a POST-upgrade table reverts (height fence)", "revert" in call("rescue",[71],0,"anyone"))
call("cancel",[71],0,"HOST")
b0=bal("HOST"); b1=bal("P8")
call("rescue",[90],0,"anyone")
ck(f"rescue: pre-upgrade table annulled, full buy-ins refunded (HOST +{bal('HOST')-b0}/6500, P8 +{bal('P8')-b1}/1300)",
   bal("HOST")==b0+500+6000 and bal("P8")==b1+500+800 and M("tz",90)==1 and (M("tp",90) or 0)==0)
ck("double rescue reverts", "revert" in call("rescue",[90],0,"anyone"))

print("\n"+("ALL PASS" if not F else f"{len(F)} FAILED: {F}"))
if not F:
    outp = os.path.join(os.path.dirname(__file__),"..","execnode","contracts","holdem.json")
    blob = json.dumps({"op":"upgrade","contract":"25ca178d3d96db57a233af6012c38ce0","code":CODE}, sort_keys=True, separators=(",",":"))
    from protocol import BLOB_MAX_BYTES
    print(f"upgrade blob = {len(blob)} bytes (cap {BLOB_MAX_BYTES}); settle = {len(settle_m)} instr")
    assert len(blob) < BLOB_MAX_BYTES, "upgrade blob exceeds BLOB_MAX_BYTES"
    if os.environ.get("WRITE"): json.dump(CODE, open(outp,"w")); print("WROTE", outp)
    else:
        committed=json.load(open(outp)) if os.path.exists(outp) else None
        assert committed==CODE, "execnode/contracts/holdem.json is STALE — re-run with WRITE=1"
        print("committed holdem.json matches")
sys.exit(1 if F else 0)
