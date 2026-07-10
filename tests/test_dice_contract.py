# tests/test_dice_contract.py — build + exercise the AUTO-ROLLING DICE CONTRACT (stackvm), peer-banked.
#
# Same self-spinning skeleton as the new Roulette (open/bet/settle/close/fund, no house reveal), but a seat is a
# "roll under M" bet and each seat gets its OWN roll from finalized L1 block hashes + its seat id, so every seat
# resolves objectively and independently with no bank action:
#     roll_g = HASH( BLOCKHASH(sh) + BLOCKHASH(sh+1) + seatId ) % 100      (0..99)
#     win iff roll_g < M  ;  payout = stake * 99 / M      (EV = 0.99*stake -> a flat 1% house edge for any M)
# The seat's settle height sh is fixed when the bet lands, and the block hashes don't exist yet — nobody (bettor,
# bank, or block producer) can know or steer the roll while betting is open. Two blocks are mixed vs grinding.
import sys, json, tempfile, hashlib
sys.path.insert(0, "/root/nado")
from execnode.state import ExecState

def P(v): return ["PUSH", v]
def A(i): return ["ARG", i]
def LD(m): return ["MLOAD", m]
def ST(m): return ["MSTORE", m]
def OP(o): return [o]
CALLER=OP("CALLER"); VALUE=OP("VALUE"); CURSOR=OP("CURSOR"); HASH=OP("HASH"); BLOCKHASH=OP("BLOCKHASH")
ADD=OP("ADD"); SUB=OP("SUB"); MUL=OP("MUL"); DIV=OP("DIV"); MOD=OP("MOD")
EQ=OP("EQ"); GT=OP("GT"); GTE=OP("GTE"); LT=OP("LT"); LTE=OP("LTE"); NOT=OP("NOT")
REQ=OP("REQUIRE"); PAY=OP("PAY"); HALT=OP("HALT")

PN = 100; EDGE_NUM = 99           # 100 outcomes; a win returns 99/M -> flat 1% edge
MMIN, MMAX = 2, 98
ROUND = 20                        # blocks per auto-roll round (must match the contract)

# table t maps: tk=bankroll tp=pool tc=committed ta=bankAddr t0=round0-start tn=seatCount tx=settledCount tz=closed
# seat g maps:  gs=stake gm=threshold(M) gg=tableId ga=bettor gh=settleHeight gd=settled gr=roll+1 gw=win
open_m = [
  VALUE, P(0), GT, REQ,
  A(0), P(0), GT, REQ,
  A(0), LD("ta"), P(0), EQ, REQ,
  A(0), VALUE, ST("tk"),
  A(0), VALUE, ST("tp"),
  A(0), CALLER, ST("ta"),
  A(0), CURSOR, ST("t0"),
  HALT ]

# bet(g, t, M)  value=stake  — take a seat with a roll-under target M; binds to the current round
bet_m = [
  A(0), P(0), GT, REQ,
  A(1), P(0), GT, REQ,
  VALUE, P(0), GT, REQ,
  A(0), LD("gg"), P(0), EQ, REQ,
  A(1), LD("ta"), P(0), EQ, NOT, REQ,
  A(1), LD("tz"), NOT, REQ,                     # not closed (blocks bet-after-close drain)
  A(2), P(MMIN), GTE, REQ,
  A(2), P(MMAX), LTE, REQ,
  A(0), A(2), ST("gm"),
  # cover: tc + (stake*99//M - stake) <= tk
  A(1), LD("tc"), VALUE, P(EDGE_NUM), MUL, A(2), DIV, VALUE, SUB, ADD, A(1), LD("tk"), LTE, REQ,
  A(1), A(1), LD("tc"), VALUE, P(EDGE_NUM), MUL, A(2), DIV, VALUE, SUB, ADD, ST("tc"),
  A(1), A(1), LD("tp"), VALUE, ADD, ST("tp"),
  A(0), VALUE, ST("gs"),
  A(0), A(1), ST("gg"),
  A(0), CALLER, ST("ga"),
  A(0), CURSOR, A(1), LD("t0"), SUB, P(ROUND), DIV, P(1), ADD, P(ROUND), MUL, A(1), LD("t0"), ADD, ST("gh"),
  A(1), A(1), LD("tn"), P(1), ADD, ST("tn"),
  HALT ]

# settle(g): roll = HASH(BLOCKHASH(sh)+BLOCKHASH(sh+1)+seatId) % 100 ; win iff roll < M ; pay stake*99//M
settle_m = [
  A(0), LD("gg"), P(0), EQ, NOT, REQ,
  A(0), LD("gd"), NOT, REQ,
  CURSOR, A(0), LD("gh"), P(1), ADD, GTE, REQ,   # sh+1 finalized
  A(0),
  A(0), LD("gh"), BLOCKHASH,
  A(0), LD("gh"), P(1), ADD, BLOCKHASH, ADD,
  A(0), ADD, HASH, P(PN), MOD, P(1), ADD, ST("gr"),   # gr[g]=roll+1  (+seatId for a per-seat roll)
  A(0), A(0), LD("gr"), P(1), SUB, A(0), LD("gm"), LT, ST("gw"),   # gw = (roll < M)
  A(0), LD("ga"),
  A(0), LD("gs"), P(EDGE_NUM), MUL, A(0), LD("gm"), DIV, A(0), LD("gw"), MUL, PAY,   # stake*99//M * win
  A(0), LD("gg"), A(0), LD("gg"), LD("tp"),
      A(0), LD("gs"), P(EDGE_NUM), MUL, A(0), LD("gm"), DIV, A(0), LD("gw"), MUL, SUB, ST("tp"),
  A(0), LD("gg"), A(0), LD("gg"), LD("tc"),
      A(0), LD("gs"), P(EDGE_NUM), MUL, A(0), LD("gm"), DIV, A(0), LD("gs"), SUB, SUB, ST("tc"),
  A(0), LD("gg"), A(0), LD("gg"), LD("tk"),
      A(0), LD("gs"), ADD,
      A(0), LD("gs"), P(EDGE_NUM), MUL, A(0), LD("gm"), DIV, A(0), LD("gw"), MUL, SUB, ST("tk"),
  A(0), P(1), ST("gd"),
  A(0), LD("gg"), A(0), LD("gg"), LD("tx"), P(1), ADD, ST("tx"),
  HALT ]

close_m = [
  CALLER, A(0), LD("ta"), EQ, REQ,
  A(0), LD("tz"), NOT, REQ,
  A(0), LD("tx"), A(0), LD("tn"), EQ, REQ,
  A(0), LD("ta"), A(0), LD("tp"), PAY,
  A(0), P(1), ST("tz"),
  A(0), P(0), ST("tp"),
  HALT ]

fund_m = [
  CALLER, A(0), LD("ta"), EQ, REQ,
  A(0), LD("tz"), NOT, REQ,
  VALUE, P(0), GT, REQ,
  A(0), A(0), LD("tk"), VALUE, ADD, ST("tk"),
  A(0), A(0), LD("tp"), VALUE, ADD, ST("tp"),
  HALT ]
CODE = {"open":open_m, "bet":bet_m, "settle":settle_m, "close":close_m, "fund":fund_m}

def vm_hash(v): return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")
def settle_height(t0, h): return t0 + ((h - t0)//ROUND + 1)*ROUND
def roll_of(bh, sh, g): return vm_hash(bh[sh] + bh[sh+1] + g) % PN

F=[]
def ck(n,c): print(("  ok  " if c else " FAIL ")+n); (F.append(n) if not c else None)
st=ExecState(tempfile.mktemp()); T0=100; st.cursor=T0
for a in ("BANK","B1","B2","B3"): st.credit_deposit(a, 2000000000)
st.apply_blob({"op":"deploy","code":CODE,"runtime":"stackvm","nonce":"dice-beacon"},"BANK","d0")
CID=list(st.contracts)[0]
def set_hashes(upto):
    for h in range(T0, upto+2): st.block_hashes[h] = vm_hash(["blk", h])
def bal(a): return st.bridge.get(a,0)
def Mv(m,g): return st.contracts[CID]["storage"].get(m,{}).get(str(g),0)
def call(m,args,val,who): return st.apply_blob({"op":"call","contract":CID,"method":m,"args":args,"value":val},who,m+str(args))

T=1; BANKROLL=100000000
call("open",[T],BANKROLL,"BANK")
ck("open escrows bankroll", bal("BANK")==2000000000-BANKROLL and bal(CID)==BANKROLL)
ck("t0 set to cursor", Mv("t0",T)==T0)

STAKE=100000
seats=[(11,50,"B1"),(12,25,"B2"),(13,90,"B3")]   # (seatId, threshold M, bettor)
for g,Mth,who in seats: call("bet",[g,T,Mth],STAKE,who)
sh = settle_height(T0, st.cursor)
for g,Mth,who in seats:
    ck(f"seat {g} escrowed (M={Mth}) bound to round", Mv("gm",g)==Mth and Mv("gg",g)==T and Mv("gh",g)==sh)
ret = lambda M: STAKE*EDGE_NUM//M
ck("committed = sum of net exposures", Mv("tc",T)==sum(ret(M)-STAKE for _,M,_ in seats))
ck("contract holds bankroll + 3 stakes", bal(CID)==BANKROLL+3*STAKE)

# M range + cover guard
ck("M<2 rejected", "revert" in call("bet",[21,T,1],STAKE,"B1"))
ck("M>98 rejected", "revert" in call("bet",[22,T,99],STAKE,"B1"))
call("open",[3],1000,"BANK")
ck("under-bankrolled low-M bet reverts", "revert" in call("bet",[31,3,2],STAKE,"B1") and Mv("gg",31)==0)

# settle too early reverts
ck("settle before settle-height reverts", "revert" in call("settle",[11],0,"B1"))

# advance the chain past sh+1 with block hashes, settle each seat by its OWN roll
st.cursor = sh + 2; set_hashes(st.cursor)
for g,Mth,who in seats:
    r_g = roll_of(st.block_hashes, sh, g); win = r_g < Mth
    b=bal(who); call("settle",[g],0,who)
    ck(f"seat {g} roll={r_g} {'WIN' if win else 'lose'} paid correctly",
       bal(who)==b+(ret(Mth) if win else 0) and Mv("gw",g)==(1 if win else 0) and Mv("gr",g)==r_g+1)
ck("committed released to 0 after all settle", (Mv("tc",T) or 0)==0)
ck("all seats settled", Mv("tx",T)==3 and Mv("tn",T)==3)
poolLeft=Mv("tp",T); bp=bal("BANK"); call("close",[T],0,"BANK")
ck("bank reclaims leftover pool", bal("BANK")==bp+poolLeft and Mv("tz",T)==1)
ck("bet on a CLOSED table rejected (no drain)", "revert" in call("bet",[301,T,50],STAKE,"B1"))

# MULTI-ROUND: a later bet lands in a later round automatically
st.cursor = sh + 5*ROUND + 3; set_hashes(st.cursor + 2*ROUND)
call("open",[7],BANKROLL,"BANK"); t07=Mv("t0",7)
call("bet",[71,7,50],STAKE,"B1")
sh7 = settle_height(t07, st.cursor)
ck("multi-round: later bet binds to a later settle height", Mv("gh",71)==sh7 and sh7>sh)

# fund
st.cursor=Mv("t0",7)+1; call("open",[20],1000,"BANK")
ck("small bankroll blocks a low-M bet", "revert" in call("bet",[201,20,2],STAKE,"B1"))
ck("non-bank cannot fund", "revert" in call("fund",[20],5000000,"B1"))
call("fund",[20],5000000,"BANK")
ck("fund raised bankroll + pool", Mv("tk",20)==1000+5000000 and Mv("tp",20)==1000+5000000)
call("bet",[201,20,2],STAKE,"B1")
ck("bigger bet fits after top-up", Mv("gg",201)==20)

print("\n"+("ALL PASS" if not F else f"{len(F)} FAILED: {F}"))
if not F:
    import os
    outp = os.path.join(os.path.dirname(__file__),"..","execnode","contracts","dice.json")
    if os.environ.get("WRITE"): json.dump(CODE, open(outp,"w")); print("WROTE", outp)
    else:
        committed=json.load(open(outp)) if os.path.exists(outp) else None
        assert committed==CODE, "execnode/contracts/dice.json is STALE — re-run with WRITE=1"
        print("committed dice.json matches")
sys.exit(1 if F else 0)
