# tests/test_roulette_contract.py — build + exhaustively exercise the MULTI-SEAT ROULETTE CONTRACT (stackvm).
#
# SHARED-WHEEL, peer-banked European (single-zero) roulette: ONE bank opens a table with a bankroll and a
# committed secret; up to many BETTORS take independent seats during a betting WINDOW, each staking a bet on a
# set of covered numbers. When the window closes the bank reveals its secret and ONE shared spin
#   result = HASH(bankSecret + tableId) % 37   (0..36)
# resolves every seat. Fairness is the standard provably-fair "server seed" model: the number is fixed the
# moment the bank commits (before any bet) and hidden from bettors (they see only HASH(secret)), so the bank
# can neither change it nor tailor it to the bets, and bettors bet blind — no bettor secret is needed, which is
# what lets each seat settle INDEPENDENTLY (a no-show can never stall the table).
#
# Payout is the universal roulette rule: a winning seat returns stake * 36/count (count = numbers covered) —
# the exact 2.70% single-zero edge for every bet. Winners are paid from the bankroll; losing stakes stay with
# the bank. The bank escrows enough to cover every outstanding seat's max win (a running `committed` guard), so
# even if the bank stalls, each seat can force-claim its MAX win after the reveal deadline (forfeit). The bank
# reclaims its remaining pool with `close` once every seat is resolved.
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
EQ=OP("EQ"); GT=OP("GT"); GTE=OP("GTE"); LTE=OP("LTE"); AND=OP("AND"); NOT=OP("NOT")
REQ=OP("REQUIRE"); PAY=OP("PAY"); HALT=OP("HALT")

MAXSLOTS = 18; PN = 37; SENTINEL = 99
JOIN_WINDOW = 30            # blocks the betting window stays open (~3 min at 6s)
REVEAL_WINDOW = 100         # blocks after the window for the bank to reveal before seats can force-claim (~10 min)

# table t maps: tk=bankroll tp=pool tc=committed(exposure) ta=bankAddr th=commit ts=secret tr=revealed
#               tj=joinDeadline tv=revealDeadline tn=seatCount tx=settledCount tz=closed
# seat g maps:  gs=stake gc=count gg=tableId(0=unused) ga=bettor gd=settled  cov[g*37+n]=covered  gr/gw=UI
def inRange(i): return [A(i), P(0), GTE, A(i), P(36), LTE, AND]
def netmax(gkey_idx):   # stake*(M-1) = VALUE*((36//count)-1)  (only valid while VALUE == this seat's stake)
    return [VALUE, P(36), A(gkey_idx), LD("gc"), DIV, P(1), SUB, MUL]

# open(t, bankCommit)  value=bankroll  -> a fresh table with a betting window
open_m = [
  VALUE, P(0), GT, REQ,
  A(0), P(0), GT, REQ,                          # table id > 0
  A(0), LD("ta"), P(0), EQ, REQ,                # table id is fresh (single-use)
  A(0), VALUE, ST("tk"),                        # bankroll
  A(0), VALUE, ST("tp"),                        # pool starts = bankroll
  A(0), CALLER, ST("ta"),
  A(0), A(1), ST("th"),
  A(0), CURSOR, P(JOIN_WINDOW), ADD, ST("tj"),
  A(0), CURSOR, P(JOIN_WINDOW + REVEAL_WINDOW), ADD, ST("tv"),
  HALT ]

# bet(g, t, n0..n17)  value=stake  -> take a seat at table t during the window (no bettor secret needed)
bet_m  = [ A(0), P(0), GT, REQ,                 # seat id > 0
           A(1), P(0), GT, REQ,                 # table id > 0
           VALUE, P(0), GT, REQ,                # stake > 0
           A(0), LD("gg"), P(0), EQ, REQ,       # seat id fresh
           A(1), LD("ta"), P(0), EQ, NOT, REQ,  # table exists
           A(1), LD("tr"), NOT, REQ,            # bank not revealed yet
           CURSOR, A(1), LD("tj"), LTE, REQ ]   # within the betting window
for i in range(MAXSLOTS):                       # cov[g*37+n_i] = inRange(n_i)
    bet_m += [ A(0), P(PN), MUL, A(2+i), ADD ] + inRange(2+i) + [ ST("cov") ]
bet_m += [ A(0), P(0) ]                          # [g, acc] -> derive count
for i in range(MAXSLOTS):
    bet_m += inRange(2+i) + [ ADD ]
bet_m += [ ST("gc"),
           A(0), LD("gc"), P(0), GT, REQ ]       # >=1 number
# bank must cover this seat on TOP of all outstanding seats:  committed + stake*(M-1) <= bankroll
bet_m += [ A(1), LD("tc") ] + netmax(0) + [ ADD, A(1), LD("tk"), LTE, REQ ]
# commit the seat + update table running totals
bet_m += [ A(1), A(1), LD("tc") ] + netmax(0) + [ ADD, ST("tc") ]     # tc[t]+=netmax
bet_m += [ A(1), A(1), LD("tp"), VALUE, ADD, ST("tp"),                # tp[t]+=stake
           A(0), VALUE, ST("gs"),
           A(0), A(1), ST("gg"),
           A(0), CALLER, ST("ga"),
           A(1), A(1), LD("tn"), P(1), ADD, ST("tn"),                 # tn[t]++
           HALT ]

# reveal(t, secret)  -> the bank reveals AFTER the window; fixes the one shared result for every seat
reveal_m = [
  CALLER, A(0), LD("ta"), EQ, REQ,
  A(1), HASH, A(0), LD("th"), EQ, REQ,          # HASH(secret)==commit
  A(0), LD("tr"), NOT, REQ,                      # not already revealed
  CURSOR, A(0), LD("tj"), GT, REQ,              # only after the betting window closed
  A(0), A(1), ST("ts"),
  A(0), P(1), ST("tr"),
  HALT ]

# settle(g)  -> resolve seat g after its table revealed: pay stake*36/count on a win, else stake stays w/ bank
settle_m = [
  A(0), LD("gg"), P(0), EQ, NOT, REQ,           # seat exists
  A(0), LD("gd"), NOT, REQ,                      # not settled
  A(0), LD("gg"), LD("tr"), REQ,                # its table's bank revealed
  # r = HASH(ts[tab] + tab) % 37 ; gr[g]=r+1
  A(0),
  A(0), LD("gg"), LD("ts"), A(0), LD("gg"), ADD, HASH, P(PN), MOD, P(1), ADD, ST("gr"),
  # win = cov[g*37 + r]
  A(0), A(0), P(PN), MUL, A(0), LD("gr"), P(1), SUB, ADD, LD("cov"), ST("gw"),
  # PAY bettor  stake * (36//count) * win
  A(0), LD("ga"),
  A(0), LD("gs"), P(36), A(0), LD("gc"), DIV, MUL, A(0), LD("gw"), MUL, PAY,
  # tp[tab] -= payout ; tc[tab] -= stake*(M-1) ; mark settled ; tx[tab]++
  A(0), LD("gg"), A(0), LD("gg"), LD("tp"),
      A(0), LD("gs"), P(36), A(0), LD("gc"), DIV, MUL, A(0), LD("gw"), MUL, SUB, ST("tp"),
  A(0), LD("gg"), A(0), LD("gg"), LD("tc"),
      A(0), LD("gs"), P(36), A(0), LD("gc"), DIV, P(1), SUB, MUL, SUB, ST("tc"),
  A(0), P(1), ST("gd"),
  A(0), LD("gg"), A(0), LD("gg"), LD("tx"), P(1), ADD, ST("tx"),
  HALT ]

# claim(g)  -> forfeit: bank never revealed by the reveal deadline, so seat g takes its MAX win
claim_m = [
  A(0), LD("gg"), P(0), EQ, NOT, REQ,
  A(0), LD("gd"), NOT, REQ,
  A(0), LD("gg"), LD("tr"), NOT, REQ,           # bank did NOT reveal
  CURSOR, A(0), LD("gg"), LD("tv"), GT, REQ,    # past the reveal deadline
  A(0), LD("ga"),
  A(0), LD("gs"), P(36), A(0), LD("gc"), DIV, MUL, PAY,          # PAY stake*M
  A(0), LD("gg"), A(0), LD("gg"), LD("tp"),
      A(0), LD("gs"), P(36), A(0), LD("gc"), DIV, MUL, SUB, ST("tp"),
  A(0), LD("gg"), A(0), LD("gg"), LD("tc"),
      A(0), LD("gs"), P(36), A(0), LD("gc"), DIV, P(1), SUB, MUL, SUB, ST("tc"),
  A(0), P(1), ST("gd"),
  A(0), LD("gg"), A(0), LD("gg"), LD("tx"), P(1), ADD, ST("tx"),
  HALT ]

# close(t)  -> the bank reclaims the remaining pool once EVERY seat is resolved (tx==tn); also cancels an
# empty table (tn==0). Requires the caller be the bank and the table not already closed.
close_m = [
  CALLER, A(0), LD("ta"), EQ, REQ,
  A(0), LD("tz"), NOT, REQ,                      # not already closed
  A(0), LD("tx"), A(0), LD("tn"), EQ, REQ,       # all seats settled/claimed
  A(0), LD("ta"), A(0), LD("tp"), PAY,           # pay the bank the leftover pool
  A(0), P(1), ST("tz"),
  A(0), P(0), ST("tp"),
  HALT ]

CODE = {"open":open_m, "bet":bet_m, "reveal":reveal_m, "settle":settle_m, "claim":claim_m, "close":close_m}

def vm_hash(v): return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")
def spin(secret, t): return vm_hash(secret + t) % PN
RED = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
def pad(nums): nums = sorted(set(nums)); return nums + [SENTINEL]*(MAXSLOTS-len(nums))

# ---- TESTS ----
F=[]
def ck(n,c): print(("  ok  " if c else " FAIL ")+n); (F.append(n) if not c else None)
st=ExecState(tempfile.mktemp()); st.cursor=100
for a in ("BANK","B1","B2","B3"): st.credit_deposit(a, 1000000)
st.apply_blob({"op":"deploy","code":CODE,"runtime":"stackvm","nonce":"roulette-multi"},"BANK","d0")
CID=list(st.contracts)[0]
def bal(a): return st.bridge.get(a,0)
def M(m,g): return st.contracts[CID]["storage"].get(m,{}).get(str(g),0)
def call(m,args,val,who): return st.apply_blob({"op":"call","contract":CID,"method":m,"args":args,"value":val},who,m+str(args))

T=1; BANKROLL=200000
sB = 987654321
cB = vm_hash(sB)
res = spin(sB, T)
print(f"[shared wheel result for this table = {res}]")

call("open",[T,cB],BANKROLL,"BANK")
ck("open escrows bankroll", bal("BANK")==1000000-BANKROLL and bal(CID)==BANKROLL)
ck("betting window open (tj set)", M("tj",T)==100+JOIN_WINDOW and M("tr",T)==0)

# three bettors take seats during the window: one on the winning number (straight), one on RED, one on a dozen
G1,G2,G3 = 11,12,13
onwin = res                             # straight-up on the number that will hit
call("bet",[G1,T]+pad([onwin]),1000,"B1")
ck("seat1 straight-up escrowed", M("gg",G1)==T and M("gc",G1)==1 and bal(CID)==BANKROLL+1000)
call("bet",[G2,T]+pad(sorted(RED)),2000,"B2")
ck("seat2 RED escrowed (count 18)", M("gc",G2)==18)
call("bet",[G3,T]+pad(list(range(1,13))),3000,"B3")
ck("seat3 dozen escrowed (count 12)", M("gc",G3)==12)
ck("committed tracks outstanding max net exposure",
   M("tc",T)==1000*35 + 2000*1 + 3000*2)     # stake*(M-1) per seat

# cannot reveal during the window
r=call("reveal",[T,sB],0,"BANK"); ck("reveal blocked during window", "revert" in r and M("tr",T)==0)
# cannot bet after the window; and cover guard blocks an over-large bet
st.cursor = 100 + JOIN_WINDOW + 1
rlate=call("bet",[99,T]+pad([5]),1000,"B1"); ck("bet blocked after window closes", "revert" in rlate and M("gg",99)==0)

# a fresh table to test the cover guard precisely
call("open",[2,cB],1000,"BANK"); st.cursor=100  # reset cursor to be inside the new window
# straight-up needs bank to cover 35x; stake 100 -> 3500 > 1000 bankroll -> revert
rc=call("bet",[21,2]+pad([7]),100,"B1"); ck("under-bankrolled straight-up seat reverts", "revert" in rc and M("gg",21)==0)
call("bet",[22,2]+pad(sorted(RED)),100,"B1"); ck("even-money seat fits the small bankroll", M("gg",22)==2 and M("gc",22)==18)

# ---- resolve table T: bank reveals after the window, one shared spin decides all three seats ----
st.cursor = 100 + JOIN_WINDOW + 1
call("reveal",[T,sB],0,"BANK")
ck("bank revealed after window", M("tr",T)==1 and M("ts",T)==sB)

b1,b2,b3,bBank = bal("B1"),bal("B2"),bal("B3"),bal("BANK")
call("settle",[G1],0,"B1")
ck("seat1 result stored (r+1)", M("gr",G1)==res+1)
ck("seat1 straight-up WON pays 36x (36000)", bal("B1")==b1+1000*36 and M("gw",G1)==1)
call("settle",[G2],0,"B2")
redwin = res in RED
if redwin: ck("seat2 RED win pays 2x", bal("B2")==b2+4000)
else:      ck("seat2 RED lost -> stake kept by bank pool", bal("B2")==b2 and M("gw",G2)==0)
call("settle",[G3],0,"B3")
dozwin = res in set(range(1,13))
if dozwin: ck("seat3 dozen win pays 3x", bal("B3")==b3+9000)
else:      ck("seat3 dozen lost", bal("B3")==b3 and M("gw",G3)==0)
ck("all three seats settled (tx==tn)", M("tx",T)==3 and M("tn",T)==3)

# committed released to 0 after all settle
ck("committed released to zero", M("tc",T)==0)
# bank closes -> reclaims the remaining pool; contract conserves exactly
poolLeft = M("tp",T)
bankBefore = bal("BANK")
call("close",[T],0,"BANK")
ck("bank reclaims leftover pool on close", bal("BANK")==bankBefore+poolLeft and M("tz",T)==1)
# conservation across table T: bank net = bankroll +/- (all seat results), nothing minted/lost
# (verified implicitly: contract balance only holds table 2's escrow now)
ck("only table-2 escrow remains in the contract", bal(CID)==1000+100)  # table2 bankroll + its one seat stake

# ---- forfeit: a bank that never reveals -> seats force-claim their MAX win ----
st.cursor = 500
call("open",[3,cB],200000,"BANK")
call("bet",[31,3]+pad([res]),1000,"B1")     # straight-up
call("bet",[32,3]+pad(sorted(RED)),2000,"B2")
st.cursor = 500 + JOIN_WINDOW + REVEAL_WINDOW + 1   # past reveal deadline, bank silent
q1,q2=bal("B1"),bal("B2")
call("claim",[31],0,"B1"); call("claim",[32],0,"B2")
ck("forfeit: straight-up seat claims max 36x", bal("B1")==q1+36000)
ck("forfeit: RED seat claims max 2x", bal("B2")==q2+4000)
ck("forfeit seats marked settled", M("tx",3)==2)
# cannot claim before the deadline on another table
st.cursor=700; call("open",[4,cB],200000,"BANK"); call("bet",[41,4]+pad([1]),1000,"B1")
rce=call("claim",[41],0,"B1"); ck("claim blocked before deadline", "revert" in rce and M("gd",41)==0)

# close cancels an empty table (tn==0) -> bank reclaims full bankroll
st.cursor=900; bankPre=bal("BANK"); call("open",[5,cB],5000,"BANK")
ck("empty open escrows 5000", bal("BANK")==bankPre-5000)
call("close",[5],0,"BANK")
ck("close on an empty table refunds the bankroll", bal("BANK")==bankPre)
ck("non-bank cannot close", "revert" in call("close",[3],0,"B1"))

# wrong-secret reveal reverts
st.cursor=1100; call("open",[6,cB],5000,"BANK"); st.cursor=1100+JOIN_WINDOW+1
ck("wrong-secret reveal reverts", "revert" in call("reveal",[6,111],0,"BANK") and M("tr",6)==0)

print("\n"+("ALL PASS" if not F else f"{len(F)} FAILED: {F}"))
if not F:
    import os
    outp = os.path.join(os.path.dirname(__file__),"..","execnode","contracts","roulette.json")
    if os.environ.get("WRITE"):
        json.dump(CODE, open(outp,"w")); print("WROTE", outp)
    else:
        committed=json.load(open(outp)) if os.path.exists(outp) else None
        assert committed==CODE, "execnode/contracts/roulette.json is STALE — re-run with WRITE=1 to regenerate"
        print("committed roulette.json matches the assembled contract")
sys.exit(1 if F else 0)
