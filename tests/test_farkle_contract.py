# tests/test_farkle_contract.py — INTERACTIVE MULTIPLAYER FARKLE ("Ten Thousand") on the stackvm. A REAL,
# MULTI-ROUND game: you take turn after turn, banked points accumulate into a GRAND TOTAL, and the first
# player to cross TARGET (4000) triggers a FINAL ROUND — everyone else gets one last turn, then the highest
# grand total takes the whole pot. Within a turn you roll, SEE the dice, set aside scoring dice, and bank or
# push your luck; a roll that can't score FARKLES the turn (you lose everything unbanked THIS turn, but keep
# your grand total). No autoplay.
#
# THE GAME (heights from t0 = open height; JOIN join window, PLAY play window, GAP=2 randomness lookahead):
#   open/join(value=ante) during (t0, t0+JOIN): ante into the pot, take a seat, diceLeft=6, turnScore=0,
#                           grandScore=0.
#   After t0+JOIN the table is LIVE until t0+JOIN+PLAY. Each seat plays its OWN turns independently:
#     roll(g)             — commit to rolling your `diceLeft` dice. Binds them to block grh=cursor+GAP whose
#                           hash nobody knows yet, so the roll is unpredictable + ungrindable. One pending
#                           roll at a time.
#     hold(g,k1..k6,cont) — once grh+1 is finalized, the dice are fixed. If the roll scores NOTHING it's a
#                           FARKLE: the turn ends at 0 (grand total unchanged). Otherwise set aside keep
#                           counts k1..k6 (each kept die must be part of a scoring combo: 1s/5s any count,
#                           2/3/4/6 only as 3+ of a kind); the kept score adds to your turn. Used all six?
#                           HOT DICE — you get 6 back. cont=1 rolls again (same turn); cont=0 BANKS the turn
#                           into your grand total and starts a fresh turn.
#     MULTI-ROUND END:    banking is NOT the end — you keep taking turns. The FIRST bank that lifts a grand
#                           total to >= TARGET sets the table's final-round flag (tfr) and finishes THAT seat.
#                           From then on, every other seat's next turn is its LAST: the next bank OR farkle
#                           finishes it (locking its grand total). If nobody reaches TARGET, seats simply keep
#                           playing until the play window ends and timeout() locks them.
#     timeout(g)          — permissionless after t0+JOIN+PLAY: finalizes an abandoned/still-playing seat,
#                           locking its GRAND TOTAL (any unbanked in-progress turn is forfeit).
#   settle(t) after every seat is finished: the whole pot -> the highest GRAND TOTAL (strict >, first in join
#   order keeps ties). reclaim(t): all-zero edge, host takes the dead pot. cancel(t): host alone.
#
# DICE: die at position p of a roll = HASH(BLOCKHASH(grh)+BLOCKHASH(grh+1)+seatId*1000+rollNonce*10+p)%6+1.
# Two consecutive block hashes are mixed so a single producer can't grind a seat's roll.
import sys, os, json, tempfile, random
sys.path.insert(0, "/root/nado"); sys.path.insert(0, "/root/nado/tests")
from execnode.state import ExecState
from execnode.vm import GAS_LIMIT
from farkle_onchain import (vm_hash, score_roll, P, A, LD, STm, LDR, STR, MAP,
                            ADD, SUB, MUL, MOD, EQ, LT, GT, GTE, AND, OR, NOT, HASH)

CURSOR=[["CURSOR"]]; VALUE=[["VALUE"]]; BLOCKHASH=[["BLOCKHASH"]]; CALLER=[["CALLER"]]
PAY=[["PAY"]]; REQ=[["REQUIRE"]]; HALT=[["HALT"]]; LTE=[["LTE"]]; DIV=[["DIV"]]
JOIN, PLAY, GAP, MAXP, TARGET = 20, 600, 2, 8, 4000
BASE = {1: 1000, 2: 200, 3: 300, 4: 400, 5: 500, 6: 600}

def LDK(keyexpr): return keyexpr + LD(MAP)
def STK(keyexpr, valexpr): return keyexpr + valexpr + STm(MAP)

# ── DICE + per-face counts into scratch registers c1..c6 (rc) from `diceLeft` real dice ─────────────
def roll_counts_ops(seed_expr, dl_reg):
    """Derive up to 6 dice (positions >= diceLeft masked to face 0) and store per-face counts c1..c6."""
    ops = []
    for p in range(6):
        raw = seed_expr + P(p) + ADD + HASH + P(6) + MOD + P(1) + ADD     # (HASH(seed+p)%6)+1
        mask = P(p) + LDR(dl_reg) + LT                                     # 1 iff p < diceLeft
        ops += STR("e%d" % p, raw + mask + MUL)
    for f in range(1, 7):
        cnt = LDR("e0") + P(f) + EQ
        for p in range(1, 6):
            cnt += LDR("e%d" % p) + P(f) + EQ + ADD
        ops += STR("c%d" % f, cnt)
    return ops

def _pow2(c_reg):
    """2^(c-3) for c in 3..6 else 0  ==  (c==3)*1+(c==4)*2+(c==5)*4+(c==6)*8."""
    return (LDR(c_reg) + P(3) + EQ
            + LDR(c_reg) + P(4) + EQ + P(2) + MUL + ADD
            + LDR(c_reg) + P(5) + EQ + P(4) + MUL + ADD
            + LDR(c_reg) + P(6) + EQ + P(8) + MUL + ADD)

def greedy_score_ops(dl_reg):
    """MAX score of the whole roll (rc in c1..c6) -> register 'gm'. 0 == FARKLE. Mirrors farkle score_roll."""
    # straight (all six faces exactly once, needs diceLeft==6)
    st = LDR("c1") + P(1) + EQ
    for f in range(2, 7):
        st += LDR("c%d" % f) + P(1) + EQ + AND
    st = st + (LDR(dl_reg) + P(6) + EQ) + AND
    ops = STR("st", st)
    # per-face greedy: c>=3 -> base*2^(c-3); else 1s->c*100, 5s->c*50, others 0
    def face(f):
        cF = "c%d" % f
        nkind = P(BASE[f]) + _pow2(cF) + MUL
        if f == 1:
            single = (LDR(cF) + P(3) + LT) + LDR(cF) + MUL + P(100) + MUL
            return nkind + single + ADD
        if f == 5:
            single = (LDR(cF) + P(3) + LT) + LDR(cF) + MUL + P(50) + MUL
            return nkind + single + ADD
        return nkind
    summ = face(1)
    for f in range(2, 7):
        summ += face(f) + ADD
    ops += STR("gm", LDR("st") + P(1500) + MUL + (LDR("st") + NOT) + summ + MUL + ADD)
    return ops

def keep_score_valid_ops(dl_reg):
    """From keep counts k1..k6 (ARGs 1..6) + rc (c1..c6): compute kept score 'ks' and validity 'ok'.
    Kept dice must be scoring: 1s/5s any count; 2,3,4,6 only 0 or >=3. Every kept die must exist in rc.
    A full straight (all six kept, one of each) scores 1500."""
    ops = []
    for f in range(1, 7):
        ops += STR("k%d" % f, A(f))                        # keep count for face f (ARG f)
    # straight-keep: diceLeft==6, rc all ones, keep all ones
    stk = (LDR(dl_reg) + P(6) + EQ)
    for f in range(1, 7):
        stk += LDR("c%d" % f) + P(1) + EQ + AND + LDR("k%d" % f) + P(1) + EQ + AND
    ops += STR("stk", stk)
    def faceKeep(f):
        kF = "k%d" % f
        nkind = P(BASE[f]) + _pow2(kF) + MUL              # base*2^(k-3) for k>=3 else 0
        if f == 1:
            return nkind + ((LDR(kF) + P(3) + LT) + LDR(kF) + MUL + P(100) + MUL) + ADD
        if f == 5:
            return nkind + ((LDR(kF) + P(3) + LT) + LDR(kF) + MUL + P(50) + MUL) + ADD
        return nkind
    summ = faceKeep(1)
    for f in range(2, 7):
        summ += faceKeep(f) + ADD
    ops += STR("ks", LDR("stk") + P(1500) + MUL + (LDR("stk") + NOT) + summ + MUL + ADD)
    # validity: for 2,3,4,6 keep==0 or keep>=3; for all keep<=rc; keepSum>=1; kept score>0 (or straight)
    ok = P(1)
    for f in (2, 3, 4, 6):
        kF = "k%d" % f
        ok += ((LDR(kF) + P(0) + EQ) + (LDR(kF) + P(3) + GTE) + OR) + AND
    ksum = LDR("k1")
    for f in range(2, 7):
        kF = "k%d" % f
        ok += (LDR(kF) + LDR("c%d" % f) + LTE) + AND
        ksum += LDR(kF) + ADD
    ops += STR("ksum", ksum)
    ok += (LDR("k1") + LDR("c1") + LTE) + AND
    ok += (LDR("ksum") + P(1) + GTE) + AND
    ok += (LDR("ks") + P(0) + GT) + AND
    ops += STR("ok", ok)
    return ops

# seed expr for the current seat's pending roll (reads S regs seatId 'sid', grh 'rh', rollNonce 'rn')
def seed_expr():
    return (LDR("rh") + BLOCKHASH + LDR("rh") + P(1) + ADD + BLOCKHASH + ADD
            + LDR("sid") + P(1000) + MUL + ADD + LDR("rn") + P(10) + MUL + ADD)

# ── CONTRACT METHODS ────────────────────────────────────────────────────────────────────────────────
# table t: ta=host t0=open ts=ante tp=pot tn=seats tx=finished tw=best tb=leader tz=closed tfr=finalRound
#          ti[t*16+i]=seat
# seat g:  gg=table ga=addr gts=turnScore ggs=grandScore gdl=diceLeft grh=rollHeight(0=none) grn=rollNonce
#          gfin=done gsc=final(=grandScore at finish)
open_m = (VALUE+P(0)+GT+REQ
  + A(0)+P(0)+GT+REQ + A(0)+LD("ta")+P(0)+EQ+REQ
  + A(1)+P(0)+GT+REQ + A(1)+LD("gg")+P(0)+EQ+REQ
  + A(0)+CALLER+STm("ta") + A(0)+CURSOR+STm("t0")
  + A(0)+VALUE+STm("ts") + A(0)+VALUE+STm("tp") + A(0)+P(1)+STm("tn")
  + A(1)+A(0)+STm("gg") + A(1)+CALLER+STm("ga") + A(1)+P(6)+STm("gdl")
  + (A(0)+P(16)+MUL) + A(1) + STm("ti")
  + HALT)

join_m = (VALUE+P(0)+GT+REQ
  + A(1)+P(0)+GT+REQ + A(1)+LD("gg")+P(0)+EQ+REQ
  + A(0)+LD("ta")+P(0)+EQ+NOT+REQ + A(0)+LD("tz")+NOT+REQ
  + VALUE+A(0)+LD("ts")+EQ+REQ
  + CURSOR+A(0)+LD("t0")+P(JOIN)+ADD+LT+REQ
  + A(0)+LD("tn")+P(MAXP)+LT+REQ
  + A(0)+A(0)+LD("tp")+VALUE+ADD+STm("tp")
  + A(1)+A(0)+STm("gg") + A(1)+CALLER+STm("ga") + A(1)+P(6)+STm("gdl")
  + (A(0)+P(16)+MUL+A(0)+LD("tn")+ADD) + A(1) + STm("ti")
  + A(0)+A(0)+LD("tn")+P(1)+ADD+STm("tn")
  + HALT)

# roll(g): commit to rolling diceLeft dice; binds to a future block
roll_m = (A(0)+LD("gg")+P(0)+EQ+NOT+REQ
  + CALLER+A(0)+LD("ga")+EQ+REQ                              # only the seat owner rolls
  + A(0)+LD("gfin")+NOT+REQ                                   # turn not over
  + A(0)+LD("grh")+P(0)+EQ+REQ                                # no pending roll
  + A(0)+LD("gdl")+P(0)+GT+REQ                                # dice to roll
  + STR("t", A(0)+LD("gg"))
  + CURSOR+LDR("t")+LD("t0")+P(JOIN)+ADD+GTE+REQ              # play window open
  + CURSOR+LDR("t")+LD("t0")+P(JOIN+PLAY)+ADD+LT+REQ
  + A(0)+CURSOR+P(GAP)+ADD+STm("grh")
  + A(0)+A(0)+LD("grn")+P(1)+ADD+STm("grn")
  + HALT)

# hold(g, k1..k6, cont): resolve the pending roll — FARKLE, or set aside kept dice and bank/continue
hold_m = (A(0)+LD("gg")+P(0)+EQ+NOT+REQ
  + CALLER+A(0)+LD("ga")+EQ+REQ
  + A(0)+LD("gfin")+NOT+REQ
  + A(0)+LD("grh")+P(0)+EQ+NOT+REQ                            # a roll is pending
  + CURSOR+A(0)+LD("grh")+P(1)+ADD+GTE+REQ                    # its block is finalized
  + STR("t", A(0)+LD("gg"))
  + STR("sid", A(0)) + STR("rh", A(0)+LD("grh")) + STR("rn", A(0)+LD("grn"))
  + STR("dl", A(0)+LD("gdl"))
  + roll_counts_ops(seed_expr(), "dl")
  + greedy_score_ops("dl")
  # FARKLE branch (gm==0): bust to 0, finish. isF = (gm==0)
  + STR("isF", LDR("gm")+P(0)+EQ)
  + keep_score_valid_ops("dl")
  # a non-farkle roll REQUIRES a valid keep; a farkle ignores keep. require: isF OR ok
  + (LDR("isF") + LDR("ok") + OR) + REQ
  # ARG 7 = cont: 0 BANKS this turn, !=0 rolls again. A farkle always ends the turn.
  + STR("te", LDR("isF") + (A(7)+P(0)+EQ) + OR)              # turnEnd = farkle OR bank(arg7==0)
  # gtsN = turnScore + kept score (kept score is 0 on a farkle)
  + STR("gtsN", (A(0)+LD("gts")) + (LDR("isF")+NOT + LDR("ks") + MUL) + ADD)
  # nd = diceLeft - kept dice (0 on farkle); HOT DICE (0 left) -> fresh 6
  + STR("nd", LDR("dl") + (LDR("isF")+NOT + LDR("ksum") + MUL) + SUB)
  + STR("nd", LDR("nd") + (LDR("nd")+P(0)+EQ)+P(6)+MUL + ADD)
  + A(0) + P(0) + STm("grh")                                  # roll resolved
  # a BANK (turnEnd & not farkle) deposits the whole turn into the grand total; a farkle deposits 0
  + STR("dep", LDR("te") + LDR("isF")+NOT + LDR("gtsN") + MUL + MUL)
  + STR("og", A(0)+LD("ggs"))                                 # old grand total
  + STR("ng", LDR("og") + LDR("dep") + ADD)                  # new grand total
  # turn state: on turnEnd reset (turnScore 0, dice 6, start a fresh turn); on continue carry gtsN / nd
  + A(0) + (LDR("te")+NOT + LDR("gtsN") + MUL) + STm("gts")   # te ? 0 : gtsN
  + A(0) + (LDR("te") + P(6) + MUL) + (LDR("te")+NOT + LDR("nd") + MUL) + ADD + STm("gdl")  # te ? 6 : nd
  + A(0) + LDR("ng") + STm("ggs")
  # MULTI-ROUND end: cx = this bank first lifts the grand total to >= TARGET (only when not already final).
  # A seat FINISHES when the turn ends AND (the table is already in the final round OR this bank crossed).
  + STR("wf", LDR("t")+LD("tfr"))                             # was the table already in the final round?
  + STR("cx", LDR("te") + LDR("isF")+NOT + (LDR("ng")+P(TARGET)+GTE) + LDR("wf")+NOT + AND + AND + AND)
  + STR("fin", LDR("te") + (LDR("wf") + LDR("cx") + OR) + AND)
  + LDR("t") + (LDR("wf") + LDR("cx") + OR) + STm("tfr")      # trigger (and thereafter keep) the final round
  # lock the grand total as the final score and mark finished; bump the finished count
  + A(0) + ((A(0)+LD("gfin")) + LDR("fin") + OR) + STm("gfin")
  + A(0) + (LDR("fin") + LDR("ng") + MUL + ((A(0)+LD("gsc")) + LDR("fin")+NOT + MUL) + ADD) + STm("gsc")
  + LDR("t") + ((LDR("t")+LD("tx")) + LDR("fin") + ADD) + STm("tx")
  # leader update only when finishing with a grand total strictly greater than the current best
  + STR("w", LDR("fin") + (LDR("ng") + (LDR("t")+LD("tw")) + GT) + AND)
  + LDR("t") + ((LDR("t")+LD("tw")) + LDR("w") + (LDR("ng") + (LDR("t")+LD("tw")) + SUB) + MUL + ADD) + STm("tw")
  + LDR("t") + ((LDR("t")+LD("tb")) + LDR("w") + (A(0) + (LDR("t")+LD("tb")) + SUB) + MUL + ADD) + STm("tb")
  + HALT)

# timeout(g): permissionless after the play window — finalize a still-playing/abandoned seat by locking its
# GRAND TOTAL. Any unbanked in-progress turn is forfeit (only banked points count), so no roll to resolve.
timeout_m = (A(0)+LD("gg")+P(0)+EQ+NOT+REQ
  + A(0)+LD("gfin")+NOT+REQ
  + STR("t", A(0)+LD("gg"))
  + CURSOR+LDR("t")+LD("t0")+P(JOIN+PLAY)+ADD+GTE+REQ
  + STR("final", A(0)+LD("ggs"))                              # locked score = grand total banked so far
  + A(0) + LDR("final") + STm("gsc")
  + A(0) + P(1) + STm("gfin")
  + LDR("t") + ((LDR("t")+LD("tx")) + P(1) + ADD) + STm("tx")
  + STR("w", LDR("final") + (LDR("t")+LD("tw")) + GT)
  + LDR("t") + ((LDR("t")+LD("tw")) + LDR("w") + (LDR("final") + (LDR("t")+LD("tw")) + SUB) + MUL + ADD) + STm("tw")
  + LDR("t") + ((LDR("t")+LD("tb")) + LDR("w") + (A(0) + (LDR("t")+LD("tb")) + SUB) + MUL + ADD) + STm("tb")
  + HALT)

settle_m = (A(0)+LD("ta")+P(0)+EQ+NOT+REQ
  + A(0)+LD("tz")+NOT+REQ
  + A(0)+LD("tx")+A(0)+LD("tn")+EQ+REQ                        # every seat finished
  + A(0)+LD("tb")+P(0)+EQ+NOT+REQ                             # a leader exists
  + A(0)+LD("tb")+LD("ga") + A(0)+LD("tp") + PAY
  + A(0)+P(1)+STm("tz") + A(0)+P(0)+STm("tp")
  + HALT)

reclaim_m = (CALLER+A(0)+LD("ta")+EQ+REQ
  + A(0)+LD("tz")+NOT+REQ
  + A(0)+LD("tx")+A(0)+LD("tn")+EQ+REQ
  + A(0)+LD("tb")+P(0)+EQ+REQ
  + A(0)+LD("ta") + A(0)+LD("tp") + PAY
  + A(0)+P(1)+STm("tz") + A(0)+P(0)+STm("tp")
  + HALT)

cancel_m = (CALLER+A(0)+LD("ta")+EQ+REQ
  + A(0)+LD("tz")+NOT+REQ
  + A(0)+LD("tn")+P(1)+EQ+REQ
  + A(0)+LD("ta") + A(0)+LD("tp") + PAY
  + A(0)+P(1)+STm("tz") + A(0)+P(0)+STm("tp")
  + HALT)

CODE = {"open":open_m, "join":join_m, "roll":roll_m, "hold":hold_m,
        "timeout":timeout_m, "settle":settle_m, "reclaim":reclaim_m, "cancel":cancel_m}

# ── PYTHON REFERENCE (mirrors the bytecode) ───────────────────────────────────────────────────────────
def roll_dice(seatId, rollHeight, rollNonce, diceLeft, bh):
    seed = bh[rollHeight] + bh[rollHeight+1] + seatId*1000 + rollNonce*10
    return [(vm_hash(seed + p) % 6) + 1 for p in range(diceLeft)]
def counts(dice):
    c = {f: 0 for f in range(1, 7)}
    for d in dice: c[d] += 1
    return c
def greedy(dice):
    return score_roll(dice)[0]
def keep_score_valid(dice, keep, diceLeft):
    rc = counts(dice)
    straight = diceLeft == 6 and all(rc[f] == 1 for f in range(1,7)) and all(keep[f] == 1 for f in range(1,7))
    score = 0
    for f in range(1,7):
        k = keep[f]
        if k >= 3: score += BASE[f]*(2**(k-3))
        elif f == 1: score += k*100
        elif f == 5: score += k*50
    score = 1500 if straight else score
    ok = all(k <= rc[f] for f,k in [(f,keep[f]) for f in range(1,7)])
    ok = ok and all(keep[f] == 0 or keep[f] >= 3 for f in (2,3,4,6))
    ok = ok and sum(keep.values()) >= 1 and score > 0
    return score, ok

# ── PYTHON REFERENCE for one hold's state transition (mirrors hold_m EXACTLY) ───────────────────────────
# seat  = {id, gts, ggs, gdl, gfin, gsc};  table = {tfr, tx, tw, tb}. Mutated in place.
def ref_hold(seat, table, dice, keep, dl, cont):
    isF = greedy(dice) == 0
    ks, _ = (0, True) if isF else keep_score_valid(dice, keep, dl)
    ksum = 0 if isF else sum(keep.values())
    te = isF or cont == 0                                    # turn ends on farkle or a bank
    gtsN = seat["gts"] + (0 if isF else ks)
    nd = dl - ksum
    nd = 6 if nd == 0 else nd                                # hot dice
    dep = gtsN if (te and not isF) else 0                    # a bank deposits the whole turn; a farkle deposits 0
    ng = seat["ggs"] + dep
    seat["gts"] = 0 if te else gtsN
    seat["gdl"] = 6 if te else nd
    seat["ggs"] = ng
    wf = table["tfr"]
    cx = te and (not isF) and ng >= TARGET and not wf        # this bank first crosses the target
    fin = te and (wf or cx)                                  # finishes: final-round turn end, or the crossing bank
    table["tfr"] = 1 if (wf or cx) else 0
    seat["gfin"] = 1 if (seat["gfin"] or fin) else 0
    if fin:
        seat["gsc"] = ng
        table["tx"] += 1
        if ng > table["tw"]:
            table["tw"] = ng; table["tb"] = seat["id"]

def cmp_state(g, t, seat, table):
    """True iff every contract cell equals the reference."""
    return ((M("gts",g) or 0)==seat["gts"] and (M("ggs",g) or 0)==seat["ggs"]
        and (M("gdl",g) or 0)==seat["gdl"] and (M("gfin",g) or 0)==seat["gfin"]
        and (M("gsc",g) or 0)==seat["gsc"] and (M("tfr",t) or 0)==table["tfr"]
        and (M("tx",t) or 0)==table["tx"] and (M("tw",t) or 0)==table["tw"]
        and (M("tb",t) or 0)==table["tb"])

# ── TESTS ─────────────────────────────────────────────────────────────────────────────────────────────
F=[]
def ck(n,c): print(("  ok  " if c else " FAIL ")+n); (F.append(n) if not c else None)
ck(f"hold fits gas ({len(hold_m)} < {GAS_LIMIT})", len(hold_m) < GAS_LIMIT)

st=ExecState(tempfile.mktemp()); st.cursor=1000
for a in ["HOST"]+["P%d"%i for i in range(10)]: st.credit_deposit(a, 10**9)
st.apply_blob({"op":"deploy","code":CODE,"runtime":"stackvm","nonce":"farkle-i"},"HOST","d0")
CID=list(st.contracts)[0]
def M(m,k): return st.contracts[CID]["storage"].get(m,{}).get(str(k))
def bal(a): return st.bridge.get(a,0)
def call(m,args,val,who): return st.apply_blob({"op":"call","contract":CID,"method":m,"args":args,"value":val},who,m+str(args)+str(st.cursor)+who)
def setbh(h, tag): st.block_hashes[h] = vm_hash([tag, h])

ANTE=1000; T=5; T0=st.cursor
call("open",[T,100],ANTE,"HOST"); call("join",[T,101],ANTE,"P1")
ck("open/join: 2 seats, pot, diceLeft 6, grand 0", M("tn",T)==2 and M("tp",T)==2*ANTE and M("gdl",100)==6 and M("ti",T*16)==100 and (M("ggs",100) or 0)==0)
st.cursor=T0+JOIN

# roll `g` (owner `who`) and reveal its dice through a controlled block hash tagged `tag`
def turn_roll(g, who, tag="r"):
    call("roll",[g],0,who); rh=M("grh",g); rn=M("grn",g); dl=M("gdl",g)
    setbh(rh,tag); setbh(rh+1,tag+"b"); st.cursor=rh+1
    return roll_dice(g, rh, rn, dl, st.block_hashes), dl
# find a block-hash pair (b0,b1) whose 6-die roll satisfies pred(dice); returns (b0,b1)
def find_bh(g, rn, pred, tag):
    hh=0
    while True:
        b0=vm_hash([tag,hh]); b1=vm_hash([tag,hh+1]); seed=b0+b1+g*1000+rn*10
        dice=[(vm_hash(seed+p)%6)+1 for p in range(6)]
        if pred(dice): return b0,b1
        hh+=1
def forced_roll(g, who, pred, tag):
    call("roll",[g],0,who); rh=M("grh",g); rn=M("grn",g); dl=M("gdl",g)
    b0,b1=find_bh(g, rn, lambda d: len(d)>=dl and pred(d[:dl]), tag)
    st.block_hashes[rh]=b0; st.block_hashes[rh+1]=b1; st.cursor=rh+1
    return roll_dice(g, rh, rn, dl, st.block_hashes), dl

# --- CONTROLLED multi-round: seat 100 BANKS several turns; grand total accumulates, NEVER finishing early ---
seat100={"id":100,"gts":0,"ggs":0,"gdl":6,"gfin":0,"gsc":0}; tbl5={"tfr":0,"tx":0,"tw":0,"tb":0}
banked_turns=0
for tn_ in range(3):
    dice,dl=forced_roll(100,"HOST",lambda d: greedy(d)>0 and (counts(d)[1] or counts(d)[5]), "acc%d"%tn_)
    rc=counts(dice); keep={f:0 for f in range(1,7)}; keep[1]=rc[1]; keep[5]=rc[5]
    call("hold",[100,keep[1],keep[2],keep[3],keep[4],keep[5],keep[6],0],0,"HOST")  # BANK -> new turn, not finished
    ref_hold(seat100, tbl5, dice, keep, dl, 0); banked_turns+=1
ck("banking accumulates a grand total across turns (below target)", cmp_state(100,T,seat100,tbl5) and seat100["ggs"]>0 and tbl5["tfr"]==0)
ck("a banked seat is NOT finished and rolls a fresh 6", (M("gfin",100) or 0)==0 and M("gdl",100)==6 and (M("gts",100) or 0)==0)

# --- a farkle mid-game ends the TURN at 0 but keeps the grand total and does NOT finish the seat ---
grand_before=seat100["ggs"]
dice,dl=forced_roll(100,"HOST",lambda d: greedy(d)==0, "bust")
call("hold",[100,0,0,0,0,0,0,0],0,"HOST"); ref_hold(seat100, tbl5, dice, keep, dl, 0)
ck("a farkle keeps the grand total and does not finish", cmp_state(100,T,seat100,tbl5) and (M("ggs",100) or 0)==grand_before and (M("gfin",100) or 0)==0)

# --- CROSSING the target: a single huge bank (six 1s = 8000) triggers the final round AND finishes the crosser ---
dice,dl=forced_roll(100,"HOST",lambda d: counts(d)[1]==6, "six1")   # 8000 in one roll
keep={f:0 for f in range(1,7)}; keep[1]=6
call("hold",[100,6,0,0,0,0,0,0],0,"HOST"); ref_hold(seat100, tbl5, dice, keep, dl, 0)
ck("crossing TARGET triggers the final round + finishes the crosser", cmp_state(100,T,seat100,tbl5)
   and M("tfr",T)==1 and M("gfin",100)==1 and (M("gsc",100) or 0)==seat100["ggs"] and seat100["ggs"]>=TARGET)
ck("the crosser leads with its grand total", M("tb",T)==100 and M("tw",T)==seat100["ggs"])

# --- FINAL ROUND: seat 101's NEXT bank finishes it even far below the target ---
seat101={"id":101,"gts":0,"ggs":0,"gdl":6,"gfin":0,"gsc":0}
dice,dl=forced_roll(101,"P1",lambda d: greedy(d)>0 and counts(d)[5]>=1 and counts(d)[1]==0 and counts(d)[5]<3, "fin5")
rc=counts(dice); keep={f:0 for f in range(1,7)}; keep[5]=rc[5]
call("hold",[101,0,0,0,0,rc[5],0,0],0,"P1"); ref_hold(seat101, tbl5, dice, keep, dl, 0)
ck("in the final round, a small bank finishes the seat", cmp_state(101,T,seat101,tbl5)
   and M("gfin",101)==1 and (M("gsc",101) or 0)==seat101["ggs"] and seat101["ggs"]<TARGET)
ck("all seats finished -> table ready to settle", M("tx",T)==2 and M("tn",T)==2)

# settle pays the whole pot to the higher grand total (seat 100)
bw=bal("HOST"); pot=M("tp",T); call("settle",[T],0,"anyone")
ck("settle pays the whole pot to the highest grand total", bal("HOST")==bw+pot and M("tz",T)==1)
ck("re-settle reverts", "revert" in call("settle",[T],0,"anyone"))

# --- invalid keep still reverts (dice-keeping rules unchanged) ---
st.cursor=2000; call("open",[7,700],ANTE,"HOST"); st.cursor=2000+JOIN
dice,dl=forced_roll(700,"HOST",lambda d: greedy(d)>0 and any(0 < counts(d)[f] < 3 for f in (2,3,4,6)), "bad")
badface=next(f for f in (2,3,4,6) if 0 < counts(dice)[f] < 3)
k={f:0 for f in range(1,7)}; k[badface]=1
ck("keeping a non-scoring single 2/3/4/6 reverts", "revert" in call("hold",[700,k[1],k[2],k[3],k[4],k[5],k[6],0],0,"HOST"))

# --- FULL-GAME multi-seat differential: 3 seats play to completion; EVERY cell tracks the reference ---
rng=random.Random(0xFA5C)
mism=0; holds=0; games_final=0
for it in range(6):
    t=400+it; base=3000+it*4000; st.cursor=base; t0=base
    seats=[500+it*8+i for i in range(3)]
    call("open",[t,seats[0]],ANTE,"HOST")
    for i,g in enumerate(seats[1:],1): call("join",[t,g],ANTE,"P%d"%i)
    st.cursor=t0+JOIN
    ref={g:{"id":g,"gts":0,"ggs":0,"gdl":6,"gfin":0,"gsc":0} for g in seats}
    rtab={"tfr":0,"tx":0,"tw":0,"tb":0}
    who={seats[0]:"HOST"}; who.update({g:"P%d"%i for i,g in enumerate(seats[1:],1)})
    guard=0
    while any(not ref[g]["gfin"] for g in seats) and guard<400:
        guard+=1
        for g in seats:
            if ref[g]["gfin"]: continue
            # take ONE full turn: roll, then continue/bank until the turn ends
            while not ref[g]["gfin"]:
                dice,dl=turn_roll(g, who[g], "d%d_%d_%d"%(it,g,guard))
                assert dl==ref[g]["gdl"]
                rc=counts(dice)
                if greedy(dice)==0:
                    call("hold",[g,0,0,0,0,0,0,0],0,who[g]); ref_hold(ref[g],rtab,dice,{f:0 for f in range(1,7)},dl,0); holds+=1
                    if not cmp_state(g,t,ref[g],rtab): mism+=1
                    break
                keep={f:0 for f in range(1,7)}; keep[1]=rc[1]; keep[5]=rc[5]
                for f in (2,3,4,6):
                    if rc[f]>=3: keep[f]=rc[f]      # greedy: bank everything that scores -> reaches TARGET faster
                ks,ok=keep_score_valid(dice,keep,dl)
                if not ok: keep={f:0 for f in range(1,7)}; keep[1]=rc[1]; keep[5]=rc[5]
                # push on while the turn is small, else bank
                cont = 1 if (ref[g]["gts"]+ks < 350 and rng.random()<0.7) else 0
                call("hold",[g,keep[1],keep[2],keep[3],keep[4],keep[5],keep[6],cont],0,who[g])
                ref_hold(ref[g],rtab,dice,keep,dl,cont); holds+=1
                if not cmp_state(g,t,ref[g],rtab): mism+=1
                if cont==0: break
    # timeout any seat still unfinished (target never reached), then settle
    st.cursor=t0+JOIN+PLAY
    for g in seats:
        if not ref[g]["gfin"]:
            call("timeout",[g],0,"anyone")
            ref[g]["gfin"]=1; ref[g]["gsc"]=ref[g]["ggs"]; rtab["tx"]+=1
            if ref[g]["ggs"]>rtab["tw"]: rtab["tw"]=ref[g]["ggs"]; rtab["tb"]=g
            if not cmp_state(g,t,ref[g],rtab): mism+=1
    if rtab["tfr"]: games_final+=1
    if M("tb",t):
        winner=who[M("tb",t)]; bw=bal(winner); pot=M("tp",t); call("settle",[t],0,"anyone")
        if bal(winner)!=bw+pot or M("tz",t)!=1: mism+=1
ck(f"DIFFERENTIAL: {holds} holds across full multi-round games bytecode==reference (mism={mism}, {games_final} reached final round)", mism==0 and games_final>=1)

# --- timeout locks the grand total (in-progress turn forfeit) ---
st.cursor=50000; call("open",[9,900],ANTE,"HOST"); st.cursor=50000+JOIN
dice,dl=forced_roll(900,"HOST",lambda d: greedy(d)>0 and counts(d)[1]>=1, "tob")  # a scoring roll, but we DON'T bank it
grand=M("ggs",900) or 0
call("hold",[900,counts(dice)[1],0,0,0,counts(dice)[5],0,1],0,"HOST")  # continue -> the turn is now in progress, unbanked
inprogress_grand=M("ggs",900) or 0
st.cursor=50000+JOIN+PLAY; call("timeout",[900],0,"anyone")
ck("timeout locks the grand total and forfeits the in-progress turn", M("gfin",900)==1 and (M("gsc",900) or 0)==inprogress_grand)

# --- reclaim (all-zero) + cancel edges ---
st.cursor=70000; call("open",[10,1000],ANTE,"HOST"); st.cursor=70000+JOIN
dice,dl=forced_roll(1000,"HOST",lambda d: greedy(d)==0, "rc")   # farkle, then window ends -> grand 0
st.cursor=70000+JOIN+PLAY; call("timeout",[1000],0,"anyone")
hb=bal("HOST"); call("reclaim",[10],0,"HOST")
ck("host reclaims an all-zero table", M("tb",10) in (None,0) and bal("HOST")==hb+ANTE and M("tz",10)==1)

st.cursor=90000; call("open",[12,120],ANTE,"HOST")
bh0=bal("HOST"); call("cancel",[12],0,"HOST")
ck("host cancels a lonely table (refund)", bal("HOST")==bh0+ANTE and M("tz",12)==1)

print("\n"+("ALL PASS" if not F else f"{len(F)} FAILED: {F}"))
if not F:
    outp = os.path.join(os.path.dirname(__file__),"..","execnode","contracts","farkle.json")
    blob = json.dumps({"op":"upgrade","contract":"05ea18398f08373343f49a4f51daf78c","code":CODE}, sort_keys=True, separators=(",",":"))
    from protocol import BLOB_MAX_BYTES
    print(f"upgrade blob = {len(blob)} bytes (cap {BLOB_MAX_BYTES}); hold={len(hold_m)} instr")
    assert len(blob) < BLOB_MAX_BYTES
    if os.environ.get("WRITE"): json.dump(CODE, open(outp,"w")); print("WROTE", outp)
    else:
        committed=json.load(open(outp)) if os.path.exists(outp) else None
        assert committed==CODE, "execnode/contracts/farkle.json is STALE — re-run with WRITE=1"
        print("committed farkle.json matches")
sys.exit(1 if F else 0)
