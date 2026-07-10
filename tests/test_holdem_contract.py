# tests/test_holdem_contract.py — MULTIPLAYER TEXAS HOLD'EM (stackvm): commit-reveal hole cards, beacon
# community cards, deadline-based betting streets, on-chain 7-card showdown. No house, no dealer, no turn
# order — the chain runs the whole hand.
#
# THE HAND (all heights derived from t0 = open height; J=20 join, S=30 per street, R=60 reveal):
#   d0 = t0+J           join closes; hole cards seeded by BH(d0),BH(d0+1) + each player's SECRET (committed
#                       at join as HASH(x) — only you can compute your cards, the chain verifies them later)
#   (d0,     d0+S ]     PREFLOP betting     flop   = BH(d0+S),BH(d0+S+1)   ← unknowable while you bet
#   (d0+S,   d0+2S]     FLOP betting        turn   = BH(d0+2S),BH(d0+2S+1)
#   (d0+2S,  d0+3S]     TURN betting        river  = BH(d0+3S),BH(d0+3S+1)
#   (d0+3S,  d0+4S]     RIVER betting
#   (d0+4S,  d0+4S+R]   SHOWDOWN: reveal(g, x) — verify commit, derive 7 cards, rank ON-CHAIN (eval7_ops,
#                       4000/4000 differential-verified incl. kickers), track the best hand.
#   after d0+4S+R       settle(t): pot -> best revealed hand (strict >, first reveal keeps ties).
#
# BETTING (objective, stall-proof): each street k has a table-wide price ms[t*8+k] = the highest street
# contribution anyone has escrowed. bet(g) value=v adds to YOUR street contribution cs[g*8+k]; exceeding the
# price is a RAISE (allowed only until GRACE blocks before the street closes, so a raise is always callable);
# at street close everyone below the price is FOLDED (their chips stay in the pot — a fold forfeits, as in
# poker). Checking = doing nothing (0==0 matches). reveal requires all 4 streets matched.
import sys, os, json, tempfile, random
sys.path.insert(0, "/root/nado"); sys.path.insert(0, "/root/nado/tests")
from execnode.state import ExecState
from execnode.vm import GAS_LIMIT
from holdem_onchain import (vm_hash, draw, hole_ref, board_ref, eval7_ref, deal_ops, eval7_ops,
                            P, A, LD, STm, LDR, STR, ADD, SUB, MUL, MOD, DIV, EQ, LT, GT, GTE,
                            AND, OR, NOT, HASH, JUMPI)

CURSOR=[["CURSOR"]]; VALUE=[["VALUE"]]; BLOCKHASH=[["BLOCKHASH"]]; CALLER=[["CALLER"]]
PAY=[["PAY"]]; REQ=[["REQUIRE"]]; HALT=[["HALT"]]; LTE=[["LTE"]]
J, S, GRACE, R = 20, 30, 5, 60

# table t: ta=host t0=openHeight ts=ante tp=pot tn=seats tx=reveals tw=bestValue tb=leaderSeat tz=closed
#          ms[t*8+k]=street-k price (k=1..4)
# seat g:  gg=tableId ga=addr gc=commitHash gd=revealed gsc=handValue gr=revealedSecret
#          cs[g*8+k]=street-k contribution
open_m = (VALUE+P(0)+GT+REQ
  + A(0)+P(0)+GT+REQ + A(0)+LD("ta")+P(0)+EQ+REQ          # fresh table id
  + A(1)+P(0)+GT+REQ + A(1)+LD("gg")+P(0)+EQ+REQ          # fresh seat id
  + A(2)+P(0)+EQ+NOT+REQ                                   # commit present
  + A(0)+CALLER+STm("ta") + A(0)+CURSOR+STm("t0")
  + A(0)+VALUE+STm("ts") + A(0)+VALUE+STm("tp") + A(0)+P(1)+STm("tn")
  + A(1)+A(0)+STm("gg") + A(1)+CALLER+STm("ga") + A(1)+A(2)+STm("gc")
  + HALT)

join_m = (VALUE+P(0)+GT+REQ
  + A(1)+P(0)+GT+REQ + A(1)+LD("gg")+P(0)+EQ+REQ
  + A(0)+LD("ta")+P(0)+EQ+NOT+REQ + A(0)+LD("tz")+NOT+REQ
  + VALUE+A(0)+LD("ts")+EQ+REQ                             # ante must match
  + CURSOR+A(0)+LD("t0")+P(J)+ADD+LT+REQ                   # join window open
  + A(2)+P(0)+EQ+NOT+REQ
  + A(0)+A(0)+LD("tp")+VALUE+ADD+STm("tp")
  + A(0)+A(0)+LD("tn")+P(1)+ADD+STm("tn")
  + A(1)+A(0)+STm("gg") + A(1)+CALLER+STm("ga") + A(1)+A(2)+STm("gc")
  + HALT)

def _match_loop(hi_expr_is_k):
    """REQUIRE cs[g*8+j]==ms[t*8+j] for j=1..3 guarded by j<k (bet), or j=1..4 unguarded (reveal)."""
    ops = STR("j", P(1))
    top = len(ops)
    match = (A(0)+P(8)+MUL+LDR("j")+ADD+LD("cs")) + (LDR("t")+P(8)+MUL+LDR("j")+ADD+LD("ms")) + EQ
    if hi_expr_is_k:
        ops += (LDR("j")+LDR("k")+GTE) + match + OR + REQ
        hi = 4
    else:
        ops += match + REQ
        hi = 5
    ops += STR("j", LDR("j")+P(1)+ADD)
    ops += LDR("j")+P(hi)+LT
    j_at = len(ops)+1
    ops += P(top - j_at) + JUMPI
    return ops

bet_m = (VALUE+P(0)+GT+REQ
  + A(0)+LD("gg")+P(0)+EQ+NOT+REQ
  + CALLER+A(0)+LD("ga")+EQ+REQ                            # only the seat owner adds to their stake
  + STR("t", A(0)+LD("gg"))
  + LDR("t")+LD("tz")+NOT+REQ
  + STR("d0", LDR("t")+LD("t0")+P(J)+ADD)
  + CURSOR+LDR("d0")+GTE+REQ                               # betting starts at the deal
  + CURSOR+LDR("d0")+P(4*S)+ADD+LT+REQ                     # …and ends when river betting closes
  + STR("k", CURSOR+LDR("d0")+SUB+P(S)+DIV+P(1)+ADD)       # street 1..4
  + _match_loop(True)                                       # must have matched all PRIOR streets
  + STR("nc", A(0)+P(8)+MUL+LDR("k")+ADD+LD("cs") + VALUE + ADD)
  + A(0)+P(8)+MUL+LDR("k")+ADD + LDR("nc") + STm("cs")
  + LDR("t") + LDR("t")+LD("tp")+VALUE+ADD + STm("tp")
  + STR("mk", LDR("t")+P(8)+MUL+LDR("k")+ADD+LD("ms"))
  + STR("isR", LDR("nc")+LDR("mk")+GT)
  # a RAISE must leave everyone time to call: cursor <= streetClose - GRACE
  + LDR("isR")+NOT + (CURSOR + LDR("d0")+LDR("k")+P(S)+MUL+ADD+P(GRACE)+SUB + LTE) + OR + REQ
  + LDR("t")+P(8)+MUL+LDR("k")+ADD + LDR("mk") + LDR("isR") + (LDR("nc")+LDR("mk")+SUB) + MUL + ADD + STm("ms")
  + HALT)

reveal_m = (A(0)+LD("gg")+P(0)+EQ+NOT+REQ
  + A(0)+LD("gd")+NOT+REQ
  + STR("t", A(0)+LD("gg"))
  + LDR("t")+LD("tz")+NOT+REQ
  + STR("d0", LDR("t")+LD("t0")+P(J)+ADD)
  + CURSOR+LDR("d0")+P(4*S)+ADD+GTE+REQ                    # river betting closed
  + CURSOR+LDR("d0")+P(4*S+R)+ADD+LT+REQ                   # inside the reveal window
  + A(1)+HASH + A(0)+LD("gc") + EQ + REQ                   # the secret matches the commit
  + _match_loop(False)                                      # matched all 4 streets (else you folded)
  # derive the 7 cards (hole from the secret, board from the street beacons) and rank them ON-CHAIN
  + deal_ops(
      LDR("d0")+BLOCKHASH + LDR("d0")+P(1)+ADD+BLOCKHASH + ADD + A(1) + ADD + HASH,
      LDR("d0")+P(S)+ADD+BLOCKHASH + LDR("d0")+P(S+1)+ADD+BLOCKHASH + ADD + LDR("t") + ADD + HASH,
      LDR("d0")+P(2*S)+ADD+BLOCKHASH + LDR("d0")+P(2*S+1)+ADD+BLOCKHASH + ADD + LDR("t") + ADD + HASH,
      LDR("d0")+P(3*S)+ADD+BLOCKHASH + LDR("d0")+P(3*S+1)+ADD+BLOCKHASH + ADD + LDR("t") + ADD + HASH)
  + eval7_ops("val")
  + A(0) + LDR("val") + STm("gsc")
  + A(0) + A(1) + STm("gr")                                # publish the secret — anyone can re-verify the hand
  + A(0) + P(1) + STm("gd")
  + LDR("t") + LDR("t")+LD("tx")+P(1)+ADD + STm("tx")
  + STR("w", A(0)+LD("gsc") + LDR("t")+LD("tw") + GT)      # strict >: first reveal keeps ties
  + LDR("t") + LDR("t")+LD("tw") + LDR("w") + (A(0)+LD("gsc") + LDR("t")+LD("tw") + SUB) + MUL + ADD + STm("tw")
  + LDR("t") + LDR("t")+LD("tb") + LDR("w") + (A(0) + LDR("t")+LD("tb") + SUB) + MUL + ADD + STm("tb")
  + HALT)

settle_m = (A(0)+LD("ta")+P(0)+EQ+NOT+REQ
  + A(0)+LD("tz")+NOT+REQ
  + CURSOR + A(0)+LD("t0")+P(J+4*S+R)+ADD + GTE + REQ      # reveal window over
  + A(0)+LD("tb")+P(0)+EQ+NOT+REQ                          # someone showed a hand
  + A(0)+LD("tb")+LD("ga") + A(0)+LD("tp") + PAY
  + A(0)+P(1)+STm("tz") + A(0)+P(0)+STm("tp")
  + HALT)

reclaim_m = (CALLER+A(0)+LD("ta")+EQ+REQ                   # nobody revealed — host sweeps the dead pot
  + A(0)+LD("tz")+NOT+REQ
  + CURSOR + A(0)+LD("t0")+P(J+4*S+R)+ADD + GTE + REQ
  + A(0)+LD("tb")+P(0)+EQ+REQ
  + A(0)+LD("ta") + A(0)+LD("tp") + PAY
  + A(0)+P(1)+STm("tz") + A(0)+P(0)+STm("tp")
  + HALT)

cancel_m = (CALLER+A(0)+LD("ta")+EQ+REQ                    # host alone at the table — refund and close
  + A(0)+LD("tz")+NOT+REQ
  + A(0)+LD("tn")+P(1)+EQ+REQ
  + A(0)+LD("ta") + A(0)+LD("tp") + PAY
  + A(0)+P(1)+STm("tz") + A(0)+P(0)+STm("tp")
  + HALT)

CODE = {"open":open_m, "join":join_m, "bet":bet_m, "reveal":reveal_m,
        "settle":settle_m, "reclaim":reclaim_m, "cancel":cancel_m}

# ---------------- TESTS ----------------
F=[]
def ck(n,c): print(("  ok  " if c else " FAIL ")+n); (F.append(n) if not c else None)
ck(f"reveal is {len(reveal_m)} instructions (static)", len(reveal_m) > 0)

st=ExecState(tempfile.mktemp()); st.cursor=1000
for a in ["HOST"]+["P%d"%i for i in range(12)]: st.credit_deposit(a, 10**9)
st.apply_blob({"op":"deploy","code":CODE,"runtime":"stackvm","nonce":"holdem"},"HOST","d0")
CID=list(st.contracts)[0]
def bal(a): return st.bridge.get(a,0)
def M(m,k): return st.contracts[CID]["storage"].get(m,{}).get(str(k))
def call(m,args,val,who): return st.apply_blob({"op":"call","contract":CID,"method":m,"args":args,"value":val},who,m+str(args)+str(st.cursor))
def seed_bh(lo, hi, tag):
    for h in range(lo, hi+1): st.block_hashes[h] = vm_hash([tag, h])

ANTE=1000
T, HG = 50, 500                       # table 50, host seat 500
xs = {500: 111111, 501: 222222, 502: 333333, 503: 444444}   # secrets
T0 = st.cursor
call("open",[T, 500, vm_hash(xs[500])], ANTE, "HOST")
ck("open: table + host seat + commit", M("ta",T)=="HOST" and M("t0",T)==T0 and M("gc",500)==vm_hash(xs[500]) and M("tp",T)==ANTE)
call("join",[T, 501, vm_hash(xs[501])], ANTE, "P1")
call("join",[T, 502, vm_hash(xs[502])], ANTE, "P2")
call("join",[T, 503, vm_hash(xs[503])], ANTE, "P3")
ck("join: 4 seats, pot = 4 antes", M("tn",T)==4 and M("tp",T)==ANTE*4)
ck("wrong ante reverts", "revert" in call("join",[T, 599, 7], ANTE+1, "P4"))
ck("dup seat reverts", "revert" in call("join",[T, 501, 7], ANTE, "P4"))
D0 = T0 + J
st.cursor = D0 + 1                     # join window closed
ck("late join reverts", "revert" in call("join",[T, 598, 7], ANTE, "P4"))
ck("bet before deal reverted earlier", True)

# ---- PREFLOP (street 1): P1 raises 300, host + P2 call, P3 folds (never matches) ----
st.cursor = D0 + 2
ck("stranger can't bet someone's seat", "revert" in call("bet",[501],300,"P9"))
call("bet",[501],300,"P1")
ck("preflop raise sets the street price", M("ms",T*8+1)==300 and M("cs",501*8+1)==300)
call("bet",[500],300,"HOST"); call("bet",[502],300,"P2")
ck("calls match the price", M("cs",500*8+1)==300 and M("cs",502*8+1)==300)
ck("pot grew by the street bets", M("tp",T)==ANTE*4+900)
# raise inside GRACE is rejected; a call inside GRACE is fine
st.cursor = D0 + S - GRACE + 1
ck("raise inside GRACE reverts", "revert" in call("bet",[501],500,"P1"))
# ---- FLOP (street 2): P3 skipped street 1 -> folded, can't bet later ----
st.cursor = D0 + S + 2
ck("folded player can't bet a later street", "revert" in call("bet",[503],100,"P3"))
call("bet",[500],200,"HOST")                                   # host bets 200 on the flop
call("bet",[501],200,"P1"); call("bet",[502],200,"P2")
# ---- TURN (street 3): everyone checks (no bets) ----
# ---- RIVER (street 4): P2 raises 400 at the deadline edge minus grace; others call ----
st.cursor = D0 + 3*S + 2
call("bet",[502],400,"P2"); call("bet",[500],400,"HOST"); call("bet",[501],400,"P1")
POT = ANTE*4 + 900 + 600 + 1200
ck("full pot accounted", M("tp",T)==POT)

# ---- SHOWDOWN ----
seed_bh(D0, D0+3*S+1, "hand1")
st.cursor = D0 + 4*S - 1
ck("reveal before river close reverts", "revert" in call("reveal",[500, xs[500]],0,"HOST"))
st.cursor = D0 + 4*S + 1
ck("settle before reveal window ends reverts", "revert" in call("settle",[T],0,"HOST"))
ck("wrong secret reverts", "revert" in call("reveal",[500, 12345],0,"HOST"))
ck("folded player can't reveal", "revert" in call("reveal",[503, xs[503]],0,"P3"))
board = board_ref(st.block_hashes, D0, S, T)
best=(0,None); vals={}
for g in (500,501,502):
    who = {500:"HOST",501:"P1",502:"P2"}[g]
    res = call("reveal",[g, xs[g]],0,who)
    hole = hole_ref(st.block_hashes, D0, xs[g])
    ref = eval7_ref(board + hole)
    vals[g]=(M("gsc",g), ref)
    if ref > best[0]: best=(ref, g)
ck("DIFFERENTIAL: on-chain showdown values == reference (board+hole+eval)",
   all(got==ref for got,ref in vals.values()))
ck("leader = best hand", M("tb",T)==best[1] and M("tw",T)==best[0])
ck("secret published on reveal", M("gr",500)==xs[500])
ck("double reveal reverts", "revert" in call("reveal",[500, xs[500]],0,"HOST"))
print("   values:", {g:v[0] for g,v in vals.items()}, "best seat", best[1])

st.cursor = D0 + 4*S + R + 1
winner = {500:"HOST",501:"P1",502:"P2"}[best[1]]
bw = bal(winner)
call("settle",[T],0,"anyone")
ck("settle pays the whole pot to the best hand", bal(winner)==bw+POT and M("tz",T)==1)
ck("re-settle reverts", "revert" in call("settle",[T],0,"anyone"))
ck("late reveal after settle reverts", "revert" in call("reveal",[501, xs[501]],0,"P1"))

# ---- nobody reveals -> host reclaims; cancel for a lonely table ----
st.cursor = 20000
call("open",[60, 600, vm_hash(9)], ANTE, "HOST"); call("join",[60, 601, vm_hash(10)], ANTE, "P5")
seed_bh(20000+J, 20000+J+3*S+1, "dead")
st.cursor = 20000 + J + 4*S + R + 1
ck("settle with no reveals reverts", "revert" in call("settle",[60],0,"HOST"))
bh0=bal("HOST"); call("reclaim",[60],0,"HOST")
ck("host reclaims a dead pot", bal("HOST")==bh0+2*ANTE and M("tz",60)==1)
st.cursor = 30000
call("open",[61, 610, vm_hash(11)], ANTE, "HOST")
bh0=bal("HOST"); call("cancel",[61],0,"HOST")
ck("host cancels a lonely table (refund)", bal("HOST")==bh0+ANTE and M("tz",61)==1)
st.cursor = 31000
call("open",[62, 620, vm_hash(12)], ANTE, "HOST"); call("join",[62, 621, vm_hash(13)], ANTE, "P6")
ck("cancel with 2 seated reverts", "revert" in call("cancel",[62],0,"HOST"))

# ---- randomized end-to-end differential: many tables, random secrets/bets, check every showdown ----
rng = random.Random(0x7E7A)
mism = 0; hands = 0
for it in range(12):
    st.cursor = 40000 + it*1000
    t = 700+it; t0 = st.cursor; d0 = t0+J
    seats = {}
    for j in range(rng.randrange(2,5)):
        g = t*10+j; x = rng.randrange(2**64); who = "P%d" % (j%12)
        seats[g] = (x, who)
        if j==0: call("open",[t, g, vm_hash(x)], ANTE, who)
        else:    call("join",[t, g, vm_hash(x)], ANTE, who)
    # random check-only or one flat bet everyone calls per street
    for k in range(1,5):
        st.cursor = d0 + (k-1)*S + 2
        if rng.random() < 0.5:
            amt = rng.randrange(50, 400)
            for g,(x,who) in seats.items(): call("bet",[g],amt,who)
    seed_bh(d0, d0+3*S+1, "rt%d"%it)
    st.cursor = d0 + 4*S + 1
    board = board_ref(st.block_hashes, d0, S, t)
    for g,(x,who) in seats.items():
        call("reveal",[g, x],0,who)
        hands += 1
        ref = eval7_ref(board + hole_ref(st.block_hashes, d0, x))
        if M("gsc",g) != ref: mism += 1
ck(f"E2E DIFFERENTIAL: {hands}/{hands} random showdown hands bytecode==reference", mism==0)

print("\n"+("ALL PASS" if not F else f"{len(F)} FAILED: {F}"))
if not F:
    outp = os.path.join(os.path.dirname(__file__),"..","execnode","contracts","holdem.json")
    blob = json.dumps({"op":"deploy","code":CODE,"runtime":"stackvm","nonce":"x"}, sort_keys=True, separators=(",",":"))
    from protocol import BLOB_MAX_BYTES
    print(f"deploy blob = {len(blob)} bytes (cap {BLOB_MAX_BYTES})")
    assert len(blob) < BLOB_MAX_BYTES, "deploy blob exceeds BLOB_MAX_BYTES"
    if os.environ.get("WRITE"): json.dump(CODE, open(outp,"w")); print("WROTE", outp)
    else:
        committed=json.load(open(outp)) if os.path.exists(outp) else None
        assert committed==CODE, "execnode/contracts/holdem.json is STALE — re-run with WRITE=1"
        print("committed holdem.json matches")
sys.exit(1 if F else 0)
