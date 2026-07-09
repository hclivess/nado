# tests/test_dice_contract.py — build + exercise the DICE CONTRACT (stackvm), a peer-banked multiplayer dice.
#
# Same shared-bank skeleton as multiplayer Roulette (open/bet/reveal/settle/claim/close), but a seat is a
# simple "roll under M" bet and each seat gets its OWN roll (all derived from the bank's single committed
# secret + the seat id, so ONE bank reveal resolves every seat independently):
#     roll_g = HASH(bankSecret + seatId) % 100      (0..99)
#     win iff roll_g < M  ;  payout = stake * 99 / M      (EV = 0.99*stake -> a flat 1% house edge for any M)
# The number is fixed at commit (before any bet) and hidden (bettors see only HASH(secret)), and the seat id a
# bettor picks can't be ground for advantage (they don't know the secret) — the standard provably-fair model.
import sys, json, tempfile, hashlib
sys.path.insert(0, "/root/nado")
from execnode.state import ExecState

def P(v): return ["PUSH", v]
def A(i): return ["ARG", i]
def LD(m): return ["MLOAD", m]
def ST(m): return ["MSTORE", m]
def OP(o): return [o]
CALLER=OP("CALLER"); VALUE=OP("VALUE"); CURSOR=OP("CURSOR"); HASH=OP("HASH")
ADD=OP("ADD"); SUB=OP("SUB"); MUL=OP("MUL"); DIV=OP("DIV"); MOD=OP("MOD")
EQ=OP("EQ"); GT=OP("GT"); GTE=OP("GTE"); LT=OP("LT"); LTE=OP("LTE"); NOT=OP("NOT")
REQ=OP("REQUIRE"); PAY=OP("PAY"); HALT=OP("HALT")

PN = 100; EDGE_NUM = 99           # 100 outcomes; a win returns 99/M -> flat 1% edge
MMIN, MMAX = 2, 98
JOIN_WINDOW = 30; REVEAL_WINDOW = 100

# table t maps (identical to roulette): tk tp tc ta th ts tr tj tv tn tx tz
# seat g maps: gs=stake gm=threshold(M) gg=tableId ga=bettor gd=settled gr=roll+1 gw=win
def ret_expr(gk):    # stake*99//M  (total return on a win)  — uses gs[gk],gm[gk]
    return [A(gk) if isinstance(gk,int) else gk]  # placeholder (unused); explicit forms written inline below

open_m = [
  VALUE, P(0), GT, REQ,
  A(0), P(0), GT, REQ,
  A(0), LD("ta"), P(0), EQ, REQ,
  A(0), VALUE, ST("tk"),
  A(0), VALUE, ST("tp"),
  A(0), CALLER, ST("ta"),
  A(0), A(1), ST("th"),
  A(0), CURSOR, P(JOIN_WINDOW), ADD, ST("tj"),
  A(0), CURSOR, P(JOIN_WINDOW + REVEAL_WINDOW), ADD, ST("tv"),
  HALT ]

# bet(g, t, M)  value=stake  — take a seat at table t with a roll-under target M
bet_m = [
  A(0), P(0), GT, REQ,                          # seat id > 0
  A(1), P(0), GT, REQ,                          # table id > 0
  VALUE, P(0), GT, REQ,                         # stake > 0
  A(0), LD("gg"), P(0), EQ, REQ,                # seat fresh
  A(1), LD("ta"), P(0), EQ, NOT, REQ,           # table exists
  A(1), LD("tz"), NOT, REQ,                     # table NOT closed (blocks the bet-after-close drain)
  A(1), LD("tr"), NOT, REQ,                     # bank not revealed
  CURSOR, A(1), LD("tj"), LTE, REQ,             # within window
  A(2), P(MMIN), GTE, REQ,                      # M >= 2
  A(2), P(MMAX), LTE, REQ,                      # M <= 98
  A(0), A(2), ST("gm"),                         # gm[g]=M
  # netmax = stake*99//M - stake ; cover: tc[t]+netmax <= tk[t]
  A(1), LD("tc"), VALUE, P(EDGE_NUM), MUL, A(2), DIV, VALUE, SUB, ADD, A(1), LD("tk"), LTE, REQ,
  A(1), A(1), LD("tc"), VALUE, P(EDGE_NUM), MUL, A(2), DIV, VALUE, SUB, ADD, ST("tc"),
  A(1), A(1), LD("tp"), VALUE, ADD, ST("tp"),
  A(0), VALUE, ST("gs"),
  A(0), A(1), ST("gg"),
  A(0), CALLER, ST("ga"),
  A(1), A(1), LD("tn"), P(1), ADD, ST("tn"),
  HALT ]

reveal_m = [
  CALLER, A(0), LD("ta"), EQ, REQ,
  A(1), HASH, A(0), LD("th"), EQ, REQ,
  A(0), LD("tr"), NOT, REQ,
  CURSOR, A(0), LD("tj"), GT, REQ,
  A(0), A(1), ST("ts"),
  A(0), P(1), ST("tr"),
  HALT ]

# settle(g): roll_g = HASH(ts[tab] + g) % 100 ; win iff roll_g < M ; pay stake*99//M on a win
settle_m = [
  A(0), LD("gg"), P(0), EQ, NOT, REQ,
  A(0), LD("gd"), NOT, REQ,
  A(0), LD("gg"), LD("tr"), REQ,                # table revealed
  A(0),
  A(0), LD("gg"), LD("ts"), A(0), ADD, HASH, P(PN), MOD, P(1), ADD, ST("gr"),   # gr[g]=roll+1
  A(0), A(0), LD("gr"), P(1), SUB, A(0), LD("gm"), LT, ST("gw"),                # gw = (roll < M)
  # PAY bettor  stake*99//M * win
  A(0), LD("ga"),
  A(0), LD("gs"), P(EDGE_NUM), MUL, A(0), LD("gm"), DIV, A(0), LD("gw"), MUL, PAY,
  # tp[tab] -= payout ; tc[tab] -= (stake*99//M - stake) ; settled ; tx++
  A(0), LD("gg"), A(0), LD("gg"), LD("tp"),
      A(0), LD("gs"), P(EDGE_NUM), MUL, A(0), LD("gm"), DIV, A(0), LD("gw"), MUL, SUB, ST("tp"),
  A(0), LD("gg"), A(0), LD("gg"), LD("tc"),
      A(0), LD("gs"), P(EDGE_NUM), MUL, A(0), LD("gm"), DIV, A(0), LD("gs"), SUB, SUB, ST("tc"),
  A(0), P(1), ST("gd"),
  A(0), LD("gg"), A(0), LD("gg"), LD("tx"), P(1), ADD, ST("tx"),
  HALT ]

# claim(g): forfeit — bank never revealed by the deadline, seat takes its MAX win (stake*99//M)
claim_m = [
  A(0), LD("gg"), P(0), EQ, NOT, REQ,
  A(0), LD("gd"), NOT, REQ,
  A(0), LD("gg"), LD("tr"), NOT, REQ,
  CURSOR, A(0), LD("gg"), LD("tv"), GT, REQ,
  A(0), LD("ga"),
  A(0), LD("gs"), P(EDGE_NUM), MUL, A(0), LD("gm"), DIV, PAY,
  A(0), LD("gg"), A(0), LD("gg"), LD("tp"),
      A(0), LD("gs"), P(EDGE_NUM), MUL, A(0), LD("gm"), DIV, SUB, ST("tp"),
  A(0), LD("gg"), A(0), LD("gg"), LD("tc"),
      A(0), LD("gs"), P(EDGE_NUM), MUL, A(0), LD("gm"), DIV, A(0), LD("gs"), SUB, SUB, ST("tc"),
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

# fund(t)  value=extra  -> the bank tops up its table's bankroll (more coverage for bigger bets) during betting
fund_m = [
  CALLER, A(0), LD("ta"), EQ, REQ,
  A(0), LD("tr"), NOT, REQ,
  A(0), LD("tz"), NOT, REQ,
  VALUE, P(0), GT, REQ,
  A(0), A(0), LD("tk"), VALUE, ADD, ST("tk"),
  A(0), A(0), LD("tp"), VALUE, ADD, ST("tp"),
  HALT ]
CODE = {"open":open_m, "bet":bet_m, "reveal":reveal_m, "settle":settle_m, "claim":claim_m, "close":close_m, "fund":fund_m}

def vm_hash(v): return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")
def roll(secret, g): return vm_hash(secret + g) % PN

F=[]
def ck(n,c): print(("  ok  " if c else " FAIL ")+n); (F.append(n) if not c else None)
st=ExecState(tempfile.mktemp()); st.cursor=100
for a in ("BANK","B1","B2","B3"): st.credit_deposit(a, 2000000000)
st.apply_blob({"op":"deploy","code":CODE,"runtime":"stackvm","nonce":"dice"},"BANK","d0")
CID=list(st.contracts)[0]
def bal(a): return st.bridge.get(a,0)
def Mv(m,g): return st.contracts[CID]["storage"].get(m,{}).get(str(g),0)
def call(m,args,val,who): return st.apply_blob({"op":"call","contract":CID,"method":m,"args":args,"value":val},who,m+str(args))

T=1; BANKROLL=100000000; sB=1122334455; cB=vm_hash(sB)
call("open",[T,cB],BANKROLL,"BANK")
ck("open escrows bankroll", bal("BANK")==2000000000-BANKROLL and bal(CID)==BANKROLL)

# three seats, each with its OWN roll (different seat ids -> different results from the one bank secret)
STAKE=100000
seats=[(11,50,"B1"),(12,25,"B2"),(13,90,"B3")]   # (seatId, threshold M, bettor)
for g,Mth,who in seats: call("bet",[g,T,Mth],STAKE,who)
for g,Mth,who in seats:
    ck(f"seat {g} escrowed (M={Mth})", Mv("gm",g)==Mth and Mv("gg",g)==T)
ret = lambda M: STAKE*EDGE_NUM//M
ck("committed = sum of net exposures", Mv("tc",T)==sum(ret(M)-STAKE for _,M,_ in seats))
ck("contract holds bankroll + 3 stakes", bal(CID)==BANKROLL+3*STAKE)

# cannot reveal during the window; cannot bet after it
r=call("reveal",[T,sB],0,"BANK"); ck("reveal blocked in window", "revert" in r)
st.cursor=100+JOIN_WINDOW+1
r=call("bet",[99,T,50],STAKE,"B1"); ck("bet blocked after window", "revert" in r and Mv("gg",99)==0)
# M out of range rejected (fresh table, in-window)
call("open",[2,cB],1000000,"BANK"); st.cursor=100
ck("M<2 rejected", "revert" in call("bet",[21,2,1],STAKE,"B1"))
ck("M>98 rejected", "revert" in call("bet",[22,2,99],STAKE,"B1"))
# cover guard: tiny bankroll can't cover a low-M (huge payout) bet
call("open",[3,cB],1000,"BANK")
ck("under-bankrolled low-M bet reverts", "revert" in call("bet",[31,3,2],STAKE,"B1") and Mv("gg",31)==0)

# reveal table T and settle each seat by its OWN roll
st.cursor=100+JOIN_WINDOW+1
call("reveal",[T,sB],0,"BANK")
ck("bank revealed", Mv("tr",T)==1 and Mv("ts",T)==sB)
for g,Mth,who in seats:
    r_g = roll(sB,g); win = r_g < Mth
    b=bal(who); call("settle",[g],0,who)
    ck(f"seat {g} roll={r_g} {'WIN' if win else 'lose'} paid correctly",
       bal(who)==b+(ret(Mth) if win else 0) and Mv("gw",g)==(1 if win else 0) and Mv("gr",g)==r_g+1)
ck("committed released to 0 after all settle", Mv("tc",T)==0)
ck("all seats settled", Mv("tx",T)==3 and Mv("tn",T)==3)
poolLeft=Mv("tp",T); bp=bal("BANK"); call("close",[T],0,"BANK")
ck("bank reclaims leftover pool", bal("BANK")==bp+poolLeft and Mv("tz",T)==1)

# forfeit: bank never reveals -> seats claim MAX win
st.cursor=500; call("open",[4,cB],100000000,"BANK")
call("bet",[41,4,50],STAKE,"B1"); call("bet",[42,4,10],STAKE,"B2")
st.cursor=500+JOIN_WINDOW+REVEAL_WINDOW+1
b1,b2=bal("B1"),bal("B2")
call("claim",[41],0,"B1"); call("claim",[42],0,"B2")
ck("forfeit seat M=50 claims max", bal("B1")==b1+ret(50))
ck("forfeit seat M=10 claims max", bal("B2")==b2+ret(10))
ck("claim before deadline blocked", "revert" in (lambda: (st.__setattr__('cursor',700), call("open",[5,cB],100000000,"BANK"), call("bet",[51,5,50],STAKE,"B1"), call("claim",[51],0,"B1"))[-1])())

# close cancels an empty table
st.cursor=900; bp=bal("BANK"); call("open",[6,cB],5000,"BANK"); call("close",[6],0,"BANK")
ck("empty table close refunds bankroll", bal("BANK")==bp)
ck("non-bank cannot close", "revert" in call("close",[4],0,"B1"))

# fund: the bank tops up a table's bankroll mid-window
st.cursor=2000; call("open",[20,cB],1000,"BANK")
ck("small bankroll blocks a low-M bet", "revert" in call("bet",[201,20,2],STAKE,"B1") and Mv("gg",201)==0)
ck("non-bank cannot fund", "revert" in call("fund",[20],5000000,"B1"))
call("fund",[20],5000000,"BANK")
ck("fund raised bankroll + pool", Mv("tk",20)==1000+5000000 and Mv("tp",20)==1000+5000000)
call("bet",[201,20,2],STAKE,"B1")
ck("bigger bet fits after top-up", Mv("gg",201)==20)

# SECURITY: bet-after-close cross-table drain must be blocked
st.cursor=3000; call("open",[30,cB],5000,"BANK"); call("close",[30],0,"BANK")   # empty table, bank reclaims
ck("bet on a CLOSED dice table is rejected (no cross-table drain)", "revert" in call("bet",[301,30,50],STAKE,"B1") and Mv("gg",301)==0)

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
