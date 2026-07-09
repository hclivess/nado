# tests/test_roulette_contract.py — build + exhaustively exercise the ROULETTE CONTRACT (stackvm).
#
# PEER-BANKED European (single-zero) roulette, reusing Coin Flip's exact commit-reveal skeleton
# (open/join/reveal/settle/claim/cancel) but with a house/bettor asymmetry and FIXED-ODDS payouts:
#
#   * The BANK opens a table, escrowing a bankroll and committing HASH(bankSecret).
#   * The BETTOR joins, escrowing their stake, committing HASH(bettorSecret), and declaring their bet as a
#     SET of covered numbers (any roulette bet — straight/split/street/corner/line/dozen/column/red/black/
#     even/odd/low/high — is just a set of the numbers it covers; the UI translates table clicks into a set).
#   * One shared spin  r = HASH(s1 + s2) % 37  (0..36), fair because neither secret is revealed before both
#     are committed — identical guarantee to Coin Flip.
#   * UNIVERSAL PAYOUT RULE: a winning bet returns  stake * 36 / count  (count = how many numbers it covers).
#     straight(1)->36x  split(2)->18x  street(3)->12x  corner(4)->9x  line(6)->6x  dozen/col(12)->3x
#     even-money(18)->2x.  With 37 pockets this yields the exact single-zero house edge (1/37 ~ 2.70%) for
#     EVERY bet — the 0 is simply in no even-money/group set, so the contract never needs to know bet TYPES.
#   * Winnings PAY out of the bank's bankroll to the bettor; a loss sweeps the bettor's stake into the bank.
#     Both sides land in the winner's exec (bridge) balance, withdrawable to L1 — the bank withdraws its
#     capital +/- results, so house wins are returned fairly to whoever funded that table's bankroll.
#   * Forfeit (claim after deadline) mirrors Coin Flip: a withholding bank pays the bettor their MAX win; a
#     withholding bettor forfeits their stake to the bank; if neither revealed, both are refunded. cancel lets
#     a lone bank reclaim its bankroll before anyone joins.
import sys, json, tempfile, hashlib
sys.path.insert(0, "/root/nado")
from execnode.state import ExecState

# ---- tiny assembler (same style as test_coinflip_contract.py) ----
def P(v): return ["PUSH", v]
def A(i): return ["ARG", i]
def LD(m): return ["MLOAD", m]
def ST(m): return ["MSTORE", m]
def OP(o): return [o]
CALLER=OP("CALLER"); VALUE=OP("VALUE"); CURSOR=OP("CURSOR"); HASH=OP("HASH")
ADD=OP("ADD"); SUB=OP("SUB"); MUL=OP("MUL"); DIV=OP("DIV"); MOD=OP("MOD")
EQ=OP("EQ"); GT=OP("GT"); GTE=OP("GTE"); LTE=OP("LTE"); AND=OP("AND"); NOT=OP("NOT")
REQ=OP("REQUIRE"); PAY=OP("PAY"); HALT=OP("HALT")

MAXSLOTS = 18            # the biggest roulette bet covers 18 numbers (red/black/even/odd/low/high)
SLOT0 = 2               # covered numbers arrive as ARG 2..19 (ARG0=gid, ARG1=commit); pad unused with a sentinel
SENTINEL = 99           # any value outside [0,36]; sentinel slots contribute nothing (inRange==0)
REVEAL_WINDOW = 1000    # blocks until a stalled game can be force-resolved by claim (matches Coin Flip)
PN = 37                 # pockets: 0..36 (European, single zero)

# maps: bk=bankroll st=stake cn=count sd=settled nn=count(0/1/2) dl=deadline
#       p1/c1/s1/r1 = bank addr/commit/secret/revealed   p2/c2/s2/r2 = bettor …
#       cov[gid*37+n]=1 marks a covered number   ro[gid]=result+1 (1..37)   wn[gid]=win flag  (UI reads)
def inRange(i):   # (v_i >= 0) AND (v_i <= 36) -> 1 for a real number, 0 for the sentinel
    return [A(i), P(0), GTE, A(i), P(36), LTE, AND]

# open(gid, bankCommit)  value=bankroll  -> fresh table, the bank sits in slot 1
open_m = [
  VALUE, P(0), GT, REQ,                         # bankroll > 0
  A(0), LD("nn"), P(0), EQ, REQ,                # gid is fresh (single-use ids)
  A(0), VALUE, ST("bk"),                        # bk[gid]=bankroll
  A(0), CALLER, ST("p1"),                       # p1[gid]=bank
  A(0), A(1), ST("c1"),                         # c1[gid]=bankCommit
  A(0), P(1), ST("nn"),                         # nn[gid]=1
  HALT ]

# join(gid, bettorCommit, n0..n17)  value=stake  -> the bettor sits in slot 2 with a covered-number set
join_m  = [ A(0), LD("nn"), P(1), EQ, REQ,      # table is open (bank present, no bettor yet)
            VALUE, P(0), GT, REQ,               # stake > 0
            CALLER, A(0), LD("p1"), EQ, NOT, REQ ]  # the bank can't bet against itself
# cov[gid*37 + n_i] = inRange(n_i)   (sentinel -> value 0 -> stored as absence; no junk, no stale keys)
for i in range(MAXSLOTS):
    join_m += [ A(0), P(PN), MUL, A(SLOT0+i), ADD ] + inRange(SLOT0+i) + [ ST("cov") ]
# count = sum of inRange over all slots ; cn[gid]=count  (DERIVED, so the bettor can't understate coverage)
join_m += [ A(0), P(0) ]                        # [gid, acc] — gid stays at the bottom as the cn key
for i in range(MAXSLOTS):
    join_m += inRange(SLOT0+i) + [ ADD ]        # acc += inRange(n_i)
join_m += [ ST("cn"),                           # cn[gid]=count
            A(0), LD("cn"), P(0), GT, REQ ]     # at least one number covered
# bank must cover the NET win: bk >= stake * ((36 // count) - 1)   (M=36//count is the total return factor)
join_m += [ A(0), LD("bk"),
            VALUE, P(36), A(0), LD("cn"), DIV, P(1), SUB, MUL,
            GTE, REQ ]
join_m += [ A(0), VALUE, ST("st"),
            A(0), CALLER, ST("p2"),
            A(0), A(1), ST("c2"),
            A(0), P(2), ST("nn"),
            A(0), CURSOR, P(REVEAL_WINDOW), ADD, ST("dl"),
            HALT ]

def reveal(slot):
    p,c,s,r = "p"+slot,"c"+slot,"s"+slot,"r"+slot
    return [ CALLER, A(0), LD(p), EQ, REQ,      # only that seat's player
             A(1), HASH, A(0), LD(c), EQ, REQ,  # HASH(secret) == commit
             A(0), LD(r), NOT, REQ,             # not already revealed
             A(0), A(1), ST(s),
             A(0), P(1), ST(r),
             HALT ]

# settle(gid): both revealed -> spin r=HASH(s1+s2)%37, pay the bettor 36/count on a win else sweep to the bank
settle_m = [
  A(0), LD("nn"), P(2), EQ, REQ,
  A(0), LD("r1"), REQ,
  A(0), LD("r2"), REQ,
  A(0), LD("sd"), NOT, REQ,
  A(0), A(0), LD("s1"), A(0), LD("s2"), ADD, HASH, P(PN), MOD, P(1), ADD, ST("ro"),   # ro[gid]=r+1 (1..37)
  A(0), A(0), P(PN), MUL, A(0), LD("ro"), P(1), SUB, ADD, LD("cov"), ST("wn"),        # wn[gid]=cov[gid*37+r]
  # PAY bettor  stake * (36//count) * win
  A(0), LD("p2"),
  A(0), LD("st"), P(36), A(0), LD("cn"), DIV, MUL, A(0), LD("wn"), MUL, PAY,
  # PAY bank  (bankroll + stake) - bettorPayout
  A(0), LD("p1"),
  A(0), LD("bk"), A(0), LD("st"), ADD,
  A(0), LD("st"), P(36), A(0), LD("cn"), DIV, MUL, A(0), LD("wn"), MUL, SUB, PAY,
  A(0), P(1), ST("sd"),
  A(0), P(0), ST("bk"),
  A(0), P(0), ST("st"),
  HALT ]

# claim(gid): after the deadline, resolve a stalled game (NOT both revealed). Withholding bank -> bettor's max
# win; withholding bettor -> forfeits stake to bank; neither revealed -> refund both.
claim_m = [
  CURSOR, A(0), LD("dl"), GT, REQ,              # past deadline
  A(0), LD("sd"), NOT, REQ,                     # not settled
  A(0), LD("nn"), P(2), EQ, REQ,                # both committed
  A(0), LD("r1"), A(0), LD("r2"), MUL, NOT, REQ,  # NOT(both revealed) — that case is settle()
  # bettor gets:  stake*M*bettorOnly  +  stake*none        (bettorOnly=(1-r1)*r2 ; none=(1-r1)*(1-r2))
  A(0), LD("p2"),
  A(0), LD("st"), P(36), A(0), LD("cn"), DIV, MUL,                       # stake*M
      P(1), A(0), LD("r1"), SUB, A(0), LD("r2"), MUL, MUL,              #   * bettorOnly
  A(0), LD("st"), P(1), A(0), LD("r1"), SUB, MUL, P(1), A(0), LD("r2"), SUB, MUL,   # stake*none
  ADD, PAY,
  # bank gets:  (bk+st)*bankOnly + (bk+st - stake*M)*bettorOnly + bk*none   (bankOnly=r1*(1-r2))
  A(0), LD("p1"),
  A(0), LD("bk"), A(0), LD("st"), ADD, A(0), LD("r1"), MUL, P(1), A(0), LD("r2"), SUB, MUL,   # (bk+st)*bankOnly
  A(0), LD("bk"), A(0), LD("st"), ADD, A(0), LD("st"), P(36), A(0), LD("cn"), DIV, MUL, SUB,  # (bk+st-stake*M)
      P(1), A(0), LD("r1"), SUB, A(0), LD("r2"), MUL, MUL,              #   * bettorOnly
  A(0), LD("bk"), P(1), A(0), LD("r1"), SUB, MUL, P(1), A(0), LD("r2"), SUB, MUL,   # bk*none
  ADD, ADD, PAY,
  A(0), P(1), ST("sd"),
  A(0), P(0), ST("bk"),
  A(0), P(0), ST("st"),
  HALT ]

# cancel(gid): the bank reclaims its bankroll from a table nobody joined (nn==1, not settled)
cancel_m = [
  A(0), LD("nn"), P(1), EQ, REQ,
  CALLER, A(0), LD("p1"), EQ, REQ,
  A(0), LD("sd"), NOT, REQ,
  A(0), LD("p1"), A(0), LD("bk"), PAY,
  A(0), P(1), ST("sd"),
  A(0), P(0), ST("bk"),
  HALT ]

CODE = {"open":open_m, "join":join_m, "reveal1":reveal("1"), "reveal2":reveal("2"),
        "settle":settle_m, "claim":claim_m, "cancel":cancel_m}

# ---- client-side result predictor must match the VM: HASH(s1+s2) % 37, HASH=blake2b(json.dumps(v)) ----
def vm_hash(v): return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")
def spin(s1, s2): return vm_hash(s1 + s2) % PN

# roulette layout helpers (for building covered-number sets in the tests, mirrored by the UI)
RED = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
def pad(nums):
    nums = sorted(set(nums))
    return nums + [SENTINEL]*(MAXSLOTS-len(nums))

# ---- TESTS ----
F=[]
def ck(n,c): print(("  ok  " if c else " FAIL ")+n); (F.append(n) if not c else None)

st=ExecState(tempfile.mktemp()); st.cursor=100
for a in ("BANK","BET","C"): st.credit_deposit(a, 100000)
st.apply_blob({"op":"deploy","code":CODE,"runtime":"stackvm","nonce":"roulette"},"BANK","d0")
CID=list(st.contracts)[0]
def bal(a): return st.bridge.get(a,0)
def sto(m,g): return st.contracts[CID]["storage"].get(m,{}).get(str(g),0)
def call(m,args,val,who): return st.apply_blob({"op":"call","contract":CID,"method":m,"args":args,"value":val},who,m+str(args))

sB, sP = 555, 777                     # bank + bettor secrets
cB, cP = vm_hash(sB), vm_hash(sP)
res = spin(sB, sP)                    # the deterministic wheel result for this secret pair
print(f"[wheel result for the test secret pair = {res}]")

# --- straight-up bet on a single number, bankroll must cover 35:1 ---
GID=1; BANKROLL=5000; STAKE=100
call("open",[GID,cB],BANKROLL,"BANK")
ck("open escrows bankroll 5000", bal("BANK")==100000-BANKROLL and bal(CID)==BANKROLL)
# bettor bets the number that WILL come up (res) straight-up -> must win 36x
call("join",[GID,cP]+pad([res]),STAKE,"BET")
ck("join escrows stake (contract holds bankroll+stake)", bal(CID)==BANKROLL+STAKE)
ck("count derived = 1 (straight)", sto("cn",GID)==1)
call("reveal1",[GID,sB],0,"BANK"); call("reveal2",[GID,sP],0,"BET")
ck("both revealed", sto("r1",GID)==1 and sto("r2",GID)==1)
bBankBefore, bBetBefore = bal("BANK"), bal("BET")
call("settle",[GID],0,"BANK")
ck(f"result stored ro=res+1 ({res+1})", sto("ro",GID)==res+1)
ck("straight-up WIN pays bettor 36x stake (3600)", bal("BET")==bBetBefore+STAKE*36)
ck("bank pays net 3500 from bankroll", bal("BANK")==bBankBefore+(BANKROLL+STAKE)-STAKE*36)
ck("contract balance back to 0", bal(CID)==0)
ck("win flag set", sto("wn",GID)==1)
ck("settled + escrow cleared", sto("sd",GID)==1 and sto("bk",GID)==0 and sto("st",GID)==0)

# --- straight-up bet on the WRONG number -> bank sweeps the stake ---
G2=2; call("open",[G2,cB],5000,"BANK");
wrong = (res+1)%PN
call("join",[G2,cP]+pad([wrong]),100,"BET")
call("reveal1",[G2,sB],0,"BANK"); call("reveal2",[G2,sP],0,"BET")
bBank=bal("BANK")
call("settle",[G2],0,"BET")
ck("losing bet: bank keeps bankroll + stake", bal("BANK")==bBank+5000+100)
ck("losing bet: win flag unset", sto("wn",G2)==0)

# --- even-money RED bet (18 numbers), pays 2x ---
G3=3; call("open",[G3,cB],5000,"BANK")
redwin = res in RED
call("join",[G3,cP]+pad(sorted(RED)),200,"BET")
ck("count derived = 18 (red)", sto("cn",G3)==18)
call("reveal1",[G3,sB],0,"BANK"); call("reveal2",[G3,sP],0,"BET")
bBet=bal("BET"); bBank=bal("BANK")
call("settle",[G3],0,"BANK")
if redwin:
    ck("RED win pays 2x (400)", bal("BET")==bBet+400 and bal("BANK")==bBank+(5000+200)-400)
else:
    ck("RED loss sweeps stake to bank", bal("BANK")==bBank+5000+200 and bal("BET")==bBet)

# --- a dozen bet (12 numbers) pays 3x, and understating coverage is impossible (count is derived) ---
G4=4; call("open",[G4,cB],5000,"BANK")
dozen1 = list(range(1,13))
call("join",[G4,cP]+pad(dozen1),150,"BET")
ck("count derived = 12 (dozen)", sto("cn",G4)==12)

# --- bank-cover guard: a stake whose 36x win exceeds the bankroll is REJECTED (bettor refunded) ---
G5=5; call("open",[G5,cB],1000,"BANK")   # bankroll only 1000
bBet=bal("BET")
r=call("join",[G5,cP]+pad([res]),100,"BET")   # straight-up needs bank to cover 3500 > 1000 -> revert
ck("under-bankrolled straight-up join reverts + refunds", "revert" in r and bal("BET")==bBet and sto("nn",G5)==1)
# but an even-money bet (needs only 1x cover) on the same 1000 bankroll is fine
call("join",[G5,cP]+pad(sorted(RED)),100,"BET")
ck("even-money join fits the small bankroll", sto("nn",G5)==2 and sto("cn",G5)==18)

# --- claim: bank withholds (only bettor revealed) after deadline -> bettor gets MAX win ---
G6=6; call("open",[G6,cB],5000,"BANK")
call("join",[G6,cP]+pad([7]),100,"BET")   # straight-up on 7 -> M=36
call("reveal2",[G6,sP],0,"BET")           # bettor reveals, bank goes dark
st.cursor = 100 + REVEAL_WINDOW + 5
bBet=bal("BET"); bBank=bal("BANK"); cCID=bal(CID)
call("claim",[G6],0,"BET")
ck("withholding bank -> bettor claims max win (3600)", bal("BET")==bBet+3600)
ck("withholding bank -> bank gets bk+st-3600", bal("BANK")==bBank+(5000+100)-3600 and bal(CID)==cCID-5100)

# --- claim: bettor withholds (only bank revealed) -> bettor forfeits stake to bank ---
st.cursor=100
G7=7; call("open",[G7,cB],5000,"BANK")
call("join",[G7,cP]+pad([7]),100,"BET")
call("reveal1",[G7,sB],0,"BANK")          # bank reveals, bettor goes dark
st.cursor = 100 + REVEAL_WINDOW + 5
bBank=bal("BANK"); cCID=bal(CID)
call("claim",[G7],0,"BANK")
ck("withholding bettor -> bank takes bankroll + stake", bal("BANK")==bBank+5000+100 and bal(CID)==cCID-5100)

# --- claim: neither revealed -> refund both ---
st.cursor=100
G8=8; bBankStart=bal("BANK"); bBetStart=bal("BET"); cCID=bal(CID)
call("open",[G8,cB],5000,"BANK"); call("join",[G8,cP]+pad([7]),100,"BET")
st.cursor = 100 + REVEAL_WINDOW + 5
call("claim",[G8],0,"C")
ck("neither revealed -> both refunded", bal("BANK")==bBankStart and bal("BET")==bBetStart and bal(CID)==cCID)

# --- cancel: lone bank reclaims its bankroll ---
st.cursor=100
G9=9; bBank=bal("BANK"); cCID=bal(CID); call("open",[G9,cB],5000,"BANK")
ck("open escrows 5000", bal("BANK")==bBank-5000)
ck("non-bank cannot cancel", "revert" in call("cancel",[G9],0,"BET") and sto("sd",G9)==0)
call("cancel",[G9],0,"BANK")
ck("bank cancels un-joined table -> refunded", bal("BANK")==bBank and bal(CID)==cCID)

# --- wrong-secret reveal reverts (no state change) ---
G10=10; call("open",[G10,cB],5000,"BANK"); call("join",[G10,cP]+pad([7]),100,"BET")
call("reveal1",[G10, 999999],0,"BANK")
ck("wrong-secret reveal reverts", sto("r1",G10)==0)

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
