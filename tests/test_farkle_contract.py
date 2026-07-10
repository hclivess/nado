# tests/test_farkle_contract.py — INTERACTIVE MULTIPLAYER FARKLE ("Ten Thousand") on the stackvm. A REAL
# game: you roll, SEE the dice, choose which scoring dice to set aside, and decide to BANK or push your luck.
# A roll that can't score anything FARKLES your turn (you lose everything you hadn't banked). No autoplay.
#
# THE HAND (heights from t0 = open height; JOIN join window, PLAY play window, GAP=2 randomness lookahead):
#   open/join(value=ante) during (t0, t0+JOIN): ante into the pot, take a seat, diceLeft=6, turnScore=0.
#   After t0+JOIN the table is LIVE until t0+JOIN+PLAY. Each seat plays its own turn independently:
#     roll(g)             — commit to rolling your `diceLeft` dice. Binds them to block grh=cursor+GAP whose
#                           hash nobody knows yet, so the roll is unpredictable + ungrindable. One pending
#                           roll at a time.
#     hold(g,k1..k6,cont) — once grh+1 is finalized, the dice are fixed. If the roll scores NOTHING it's a
#                           FARKLE: turn ends at 0. Otherwise set aside keep counts k1..k6 (each kept die
#                           must be part of a scoring combo: 1s/5s any count, 2/3/4/6 only as 3+ of a kind);
#                           the kept score adds to your turn. Used all six? HOT DICE — you get 6 back.
#                           cont=1 rolls again; cont=0 BANKS (turn ends, score locked).
#     timeout(g)          — permissionless after t0+JOIN+PLAY: finalizes an abandoned seat (a hidden farkle
#                           busts to 0; otherwise the un-held roll is discarded and you keep what you banked).
#   settle(t) after every seat is finished: the whole pot -> the highest banked score (strict >, first in
#   join order keeps ties). reclaim(t): all-farkle edge, host takes the dead pot. cancel(t): host alone.
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
JOIN, PLAY, GAP, MAXP = 20, 600, 2, 8
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
# table t: ta=host t0=open ts=ante tp=pot tn=seats tx=finished tw=best tb=leader tz=closed · ti[t*16+i]=seat
# seat g:  gg=table ga=addr gts=turnScore gdl=diceLeft grh=rollHeight(0=none) grn=rollNonce gfin=done gsc=final
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
  # cont flag (ARG 7): bank when 0, roll again when 1 — but a farkle always finishes
  + STR("cont", A(7)+P(0)+EQ+NOT+LDR("isF")+NOT+AND)          # cont = (arg7!=0) AND !farkle
  + STR("fin", LDR("isF") + (A(7)+P(0)+EQ) + OR)              # finish on farkle OR bank
  # add kept score (0 on farkle) to turnScore
  + STR("add", LDR("isF")+NOT + LDR("ks") + MUL)
  + A(0) + A(0)+LD("gts") + LDR("add") + ADD + STm("gts")
  # diceLeft -= kept (0 on farkle); hot dice -> 6 when it reaches 0
  + STR("nd", LDR("dl") + (LDR("isF")+NOT + LDR("ksum") + MUL) + SUB)
  + STR("nd", LDR("nd") + (LDR("nd")+P(0)+EQ)+P(6)+MUL + ADD)
  + A(0) + LDR("nd") + STm("gdl")
  + A(0) + P(0) + STm("grh")                                  # roll resolved
  # finalize on farkle/bank: gsc = farkle?0:turnScore ; mark finished ; leaderboard
  + STR("final", LDR("isF")+NOT + (A(0)+LD("gts")) + MUL)     # 0 if farkle else turnScore
  + A(0) + (LDR("fin") + LDR("final") + MUL) + STm("gsc")
  + A(0) + (A(0)+LD("gfin")) + LDR("fin") + OR + STm("gfin")
  + LDR("t") + (LDR("t")+LD("tx")) + LDR("fin") + ADD + STm("tx")
  # leader update only when finishing with a score > current best
  + STR("w", LDR("fin") + (LDR("final") + (LDR("t")+LD("tw")) + GT) + AND)
  + LDR("t") + (LDR("t")+LD("tw")) + LDR("w") + (LDR("final") + (LDR("t")+LD("tw")) + SUB) + MUL + ADD + STm("tw")
  + LDR("t") + (LDR("t")+LD("tb")) + LDR("w") + (A(0) + (LDR("t")+LD("tb")) + SUB) + MUL + ADD + STm("tb")
  + HALT)

# timeout(g): permissionless after the play window — finalize an abandoned seat
timeout_m = (A(0)+LD("gg")+P(0)+EQ+NOT+REQ
  + A(0)+LD("gfin")+NOT+REQ
  + STR("t", A(0)+LD("gg"))
  + CURSOR+LDR("t")+LD("t0")+P(JOIN+PLAY)+ADD+GTE+REQ
  # if a resolvable pending roll is a FARKLE -> bust to 0; otherwise keep the banked turnScore
  + STR("busted", P(0))
  + STR("rh", A(0)+LD("grh"))
  + STR("resolvable", LDR("rh")+P(0)+EQ+NOT + (CURSOR+LDR("rh")+P(1)+ADD+GTE) + AND)
  # only if resolvable do we score the pending roll (else assume safe)
  + STR("sid", A(0)) + STR("rn", A(0)+LD("grn")) + STR("dl", A(0)+LD("gdl"))
  + roll_counts_ops(seed_expr(), "dl")
  + greedy_score_ops("dl")
  + STR("busted", LDR("resolvable") + (LDR("gm")+P(0)+EQ) + AND)
  + STR("final", LDR("busted")+NOT + (A(0)+LD("gts")) + MUL)
  + A(0) + LDR("final") + STm("gsc")
  + A(0) + P(1) + STm("gfin")
  + LDR("t") + (LDR("t")+LD("tx")) + P(1) + ADD + STm("tx")
  + STR("w", LDR("final") + (LDR("t")+LD("tw")) + GT)
  + LDR("t") + (LDR("t")+LD("tw")) + LDR("w") + (LDR("final") + (LDR("t")+LD("tw")) + SUB) + MUL + ADD + STm("tw")
  + LDR("t") + (LDR("t")+LD("tb")) + LDR("w") + (A(0) + (LDR("t")+LD("tb")) + SUB) + MUL + ADD + STm("tb")
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
ck("open/join: 2 seats, pot, diceLeft 6", M("tn",T)==2 and M("tp",T)==2*ANTE and M("gdl",100)==6 and M("ti",T*16)==100)
st.cursor=T0+JOIN

# --- a controlled turn for seat 100: roll, keep, continue, bank ---
def do_roll(g):
    call("roll",[g],0,g//0 if False else "HOST" if g==100 else "P1")
def turn_roll(g, who):
    call("roll",[g],0,who); rh=M("grh",g); rn=M("grn",g); dl=M("gdl",g)
    setbh(rh,"r"); setbh(rh+1,"r"); st.cursor=rh+1
    return roll_dice(g, rh, rn, dl, st.block_hashes), dl

dice, dl = turn_roll(100,"HOST")
rc = counts(dice)
# choose to keep exactly the 1s and 5s (always valid if present); if none, it's a farkle
keep = {f:0 for f in range(1,7)}
if rc[1] or rc[5]:
    keep[1]=rc[1]; keep[5]=rc[5]
    ks, ok = keep_score_valid(dice, keep, dl)
    ck("client keep is valid", ok)
    before=M("gts",100) or 0
    call("hold",[100,keep[1],keep[2],keep[3],keep[4],keep[5],keep[6],1],0,"HOST")  # continue
    ck("hold adds kept score to turnScore", (M("gts",100) or 0)==before+ks)
    ck("hold consumes kept dice (or hot-dice reset)", M("gdl",100) in (dl-(rc[1]+rc[5]), 6))
    ck("not finished after continue", not M("gfin",100))
else:
    call("hold",[100,0,0,0,0,0,0,0],0,"HOST")
    ck("farkle finishes at 0", M("gfin",100)==1 and (M("gsc",100) or 0)==0)

# invalid keep must revert: keeping a non-scoring single 2/3/4/6
if not M("gfin",100):
    call("roll",[100],0,"HOST"); rh=M("grh",100); rn=M("grn",100); dl2=M("gdl",100)
    setbh(rh,"r2"); setbh(rh+1,"r2"); st.cursor=rh+1
    dice2=roll_dice(100,rh,rn,dl2,st.block_hashes); rc2=counts(dice2)
    if greedy(dice2)>0:
        badface=next((f for f in (2,3,4,6) if 0 < rc2[f] < 3), None)
        if badface:
            k={f:0 for f in range(1,7)}; k[badface]=1
            ck("keeping a non-scoring single reverts", "revert" in call("hold",[100,k[1],k[2],k[3],k[4],k[5],k[6],0],0,"HOST"))
        # bank whatever scores
        k={f:0 for f in range(1,7)}
        if rc2[1] or rc2[5]: k[1]=rc2[1]; k[5]=rc2[5]
        else:
            f3=next(f for f in range(1,7) if rc2[f]>=3); k[f3]=rc2[f3]
        call("hold",[100,k[1],k[2],k[3],k[4],k[5],k[6],0],0,"HOST")  # BANK
    else:
        call("hold",[100,0,0,0,0,0,0,0],0,"HOST")
ck("seat 100 finished", M("gfin",100)==1)

# --- randomized differential: many seats play greedy-random turns; every hold matches the reference ---
rng=random.Random(0xFA5C)
mism=0; holds=0
for it in range(40):
    g=200+it; st.cursor=3000+it*800; t0=st.cursor
    call("open",[300+it,g],ANTE,"HOST")
    st.cursor=t0+JOIN
    dl=6; ts=0; busted=False
    for step in range(8):
        call("roll",[g],0,"HOST")
        rh=M("grh",g); rn=M("grn",g)
        setbh(rh,"x%d"%it); setbh(rh+1,"y%d"%it); st.cursor=rh+1
        dice=roll_dice(g,rh,rn,dl,st.block_hashes); rc=counts(dice)
        if greedy(dice)==0:
            call("hold",[g,0,0,0,0,0,0,0],0,"HOST"); busted=True
            if (M("gsc",g) or 0)!=0 or M("gfin",g)!=1: mism+=1
            holds+=1; break
        # random valid keep: always take 1s/5s, sometimes a trip
        keep={f:0 for f in range(1,7)}
        keep[1]=rc[1]; keep[5]=rc[5]
        for f in (2,3,4,6):
            if rc[f]>=3 and rng.random()<0.6: keep[f]=rc[f]
        if sum(keep.values())==0:
            f3=next((f for f in (2,3,4,6) if rc[f]>=3),None)
            if f3: keep[f3]=rc[f3]
            else: keep[1]=rc[1]; keep[5]=rc[5]
        ks,ok=keep_score_valid(dice,keep,dl)
        if not ok: keep={f:0 for f in range(1,7)}; keep[1]=rc[1]; keep[5]=rc[5]; ks,ok=keep_score_valid(dice,keep,dl)
        cont = 1 if rng.random()<0.6 else 0
        call("hold",[g,keep[1],keep[2],keep[3],keep[4],keep[5],keep[6],cont],0,"HOST")
        holds+=1
        ts+=ks
        consumed=sum(keep.values()); dl=dl-consumed; dl=6 if dl==0 else dl
        if (M("gts",g) or 0)!=ts: mism+=1
        if cont==0:
            if (M("gsc",g) or 0)!=ts or M("gfin",g)!=1: mism+=1
            break
    if not M("gfin",g):   # ran out of steps without banking -> timeout keeps turnScore
        st.cursor=t0+JOIN+PLAY
        call("timeout",[g],0,"anyone")
ck(f"DIFFERENTIAL: {holds} interactive holds bytecode==reference (mism={mism})", mism==0)

# --- timeout busts a hidden farkle ---
st.cursor=50000; call("open",[9,900],ANTE,"HOST"); st.cursor=50000+JOIN
call("roll",[900],0,"HOST"); rh=M("grh",900); rn=M("grn",900)
# find a bh that makes the 6-dice roll a farkle
h=70000
while True:
    b0=vm_hash(["f",h]); b1=vm_hash(["f",h+1])
    seed=b0+b1+900*1000+rn*10
    dice=[(vm_hash(seed+p)%6)+1 for p in range(6)]
    if greedy(dice)==0: break
    h+=1
st.block_hashes[rh]=b0; st.block_hashes[rh+1]=b1
st.cursor=50000+JOIN+PLAY
call("timeout",[900],0,"anyone")
ck("timeout busts a hidden farkle to 0", M("gfin",900)==1 and (M("gsc",900) or 0)==0)

# --- settle pays the leader; reclaim + cancel ---
st.cursor=60000; call("open",[11,110],ANTE,"HOST"); call("join",[11,111],ANTE,"P1"); st.cursor=60000+JOIN
for g,who,pts in ((110,"HOST",1),(111,"P1",2)):
    call("roll",[g],0,who); rh=M("grh",g); rn=M("grn",g)
    # force a scoring roll: search a bh with at least one 1
    hh=80000+g
    while True:
        b0=vm_hash(["s",hh]); b1=vm_hash(["s",hh+1]); seed=b0+b1+g*1000+rn*10
        dice=[(vm_hash(seed+p)%6)+1 for p in range(6)]
        if counts(dice)[1]>=pts and greedy(dice)>0: break
        hh+=1
    st.block_hashes[rh]=b0; st.block_hashes[rh+1]=b1; st.cursor=rh+1
    k={f:0 for f in range(1,7)}; k[1]=counts(roll_dice(g,rh,rn,6,st.block_hashes))[1]; k[5]=counts(roll_dice(g,rh,rn,6,st.block_hashes))[5]
    call("hold",[g,k[1],k[2],k[3],k[4],k[5],k[6],0],0,who)  # bank
lead=M("tb",11); best=M("tw",11)
ck("leader tracked across seats", lead in (110,111) and best>0)
winner="HOST" if lead==110 else "P1"; bw=bal(winner); pot=M("tp",11)
call("settle",[11],0,"anyone")
ck("settle pays the whole pot to the leader", bal(winner)==bw+pot and M("tz",11)==1)
ck("re-settle reverts", "revert" in call("settle",[11],0,"anyone"))

st.cursor=90000; call("open",[12,120],ANTE,"HOST")
bh0=bal("HOST"); call("cancel",[12],0,"HOST")
ck("host cancels a lonely table (refund)", bal("HOST")==bh0+ANTE and M("tz",12)==1)

print("\n"+("ALL PASS" if not F else f"{len(F)} FAILED: {F}"))
if not F:
    outp = os.path.join(os.path.dirname(__file__),"..","execnode","contracts","farkle.json")
    blob = json.dumps({"op":"upgrade","contract":"143db4a8ff9f01f95ad0b82a1e950e90","code":CODE}, sort_keys=True, separators=(",",":"))
    from protocol import BLOB_MAX_BYTES
    print(f"upgrade blob = {len(blob)} bytes (cap {BLOB_MAX_BYTES}); hold={len(hold_m)} instr")
    assert len(blob) < BLOB_MAX_BYTES
    if os.environ.get("WRITE"): json.dump(CODE, open(outp,"w")); print("WROTE", outp)
    else:
        committed=json.load(open(outp)) if os.path.exists(outp) else None
        assert committed==CODE, "execnode/contracts/farkle.json is STALE — re-run with WRITE=1"
        print("committed farkle.json matches")
sys.exit(1 if F else 0)
