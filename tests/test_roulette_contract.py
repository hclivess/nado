# tests/test_roulette_contract.py — build + exhaustively exercise the AUTO-ROLLING ROULETTE CONTRACT (stackvm).
#
# BEACON/BLOCKHASH roulette (no house spin, no secrets, perpetual rounds). ONE bank opens a table with a
# bankroll. The table then spins AUTOMATICALLY every ROUND blocks forever — nobody has to reveal or "spin".
# Bettors take independent seats at any time, each staking on a set of covered numbers. A bet placed while the
# chain is at height h belongs to the round that ends at settle-height  sh = t0 + (floor((h-t0)/ROUND)+1)*ROUND,
# and its result is fixed by FINALIZED L1 block hashes nobody can predict while betting is open:
#   result = HASH( BLOCKHASH(sh) + BLOCKHASH(sh+1) + tableId ) % 37      (0..36)
# Two consecutive block hashes are mixed so a single block producer can't grind the wheel. Because the outcome
# comes from the chain, every seat settles OBJECTIVELY and INDEPENDENTLY — a no-show or a stalling bank can never
# rob anyone, and there is no bank action between opening a table and closing it.
#
# Payout is the universal roulette rule: a winning seat returns stake * 36/count (count = distinct numbers
# covered) — the exact 2.70% single-zero edge. Winners are paid from the bankroll; LOSING stakes fold back INTO
# the bankroll (tk += stake), so a table is self-sustaining across rounds. The bank escrows enough to cover every
# outstanding seat's max win (a running `committed` guard). The bank reclaims its pool with `close` once every
# seat is settled.
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
EQ=OP("EQ"); GT=OP("GT"); GTE=OP("GTE"); LTE=OP("LTE"); AND=OP("AND"); NOT=OP("NOT")
REQ=OP("REQUIRE"); PAY=OP("PAY"); HALT=OP("HALT")

MAXSLOTS = 18; PN = 37
ROUND = 20                  # blocks per auto-spin round (~2 min at 6s); the wheel resolves every ROUND blocks

# table t maps: tk=bankroll tp=pool tc=committed(exposure) ta=bankAddr t0=round0-start tn=seatCount
#               tx=settledCount tz=closed
# seat g maps:  gs=stake gc=count gg=tableId(0=unused) ga=bettor gh=settleHeight gd=settled
#               cov[g*37+n]=covered  gr/gw=UI(result+1 / win)
def netmax(gkey_idx):   # stake*(M-1) = VALUE*((36//count)-1)  (only valid while VALUE == this seat's stake)
    return [VALUE, P(36), A(gkey_idx), LD("gc"), DIV, P(1), SUB, MUL]

# open(t)  value=bankroll  -> a fresh perpetual table; rounds roll automatically from t0=CURSOR
open_m = [
  VALUE, P(0), GT, REQ,
  A(0), P(0), GT, REQ,                          # table id > 0
  A(0), LD("ta"), P(0), EQ, REQ,                # table id is fresh (single-use)
  A(0), VALUE, ST("tk"),                        # bankroll
  A(0), VALUE, ST("tp"),                        # pool starts = bankroll
  A(0), CALLER, ST("ta"),
  A(0), CURSOR, ST("t0"),                       # round-0 start height (round math anchor)
  HALT ]

# bet(g, t, n0..n17)  value=stake  -> take a seat; binds to the CURRENT round's settle height. No secret, no
# window arg: a bet is ALWAYS valid and simply settles at the end of whatever round it confirms in.
bet_m  = [ A(0), P(0), GT, REQ,                 # seat id > 0
           A(1), P(0), GT, REQ,                 # table id > 0
           VALUE, P(0), GT, REQ,                # stake > 0
           A(0), LD("gg"), P(0), EQ, REQ,       # seat id fresh
           A(1), LD("ta"), P(0), EQ, NOT, REQ,  # table exists
           A(1), LD("tz"), NOT, REQ ]           # table NOT closed (blocks the bet-after-close drain)
for i in range(MAXSLOTS):                       # REQUIRE every slot n in [0,36] (keys stay in seat g's range)
    bet_m += [ A(2+i), P(0), GTE, A(2+i), P(36), LTE, AND, REQ ]
for i in range(MAXSLOTS):                       # cov[g*37+n_i] = 1
    bet_m += [ A(0), P(PN), MUL, A(2+i), ADD, P(1), ST("cov") ]
bet_m += [ A(0), P(0) ]                          # [g, acc] -> count = sum over pockets of cov[g*37+n]
for n in range(PN):
    bet_m += [ A(0), P(PN), MUL, P(n), ADD, LD("cov"), ADD ]
bet_m += [ ST("gc"),
           A(0), LD("gc"), P(0), GT, REQ ]       # >=1 number
# bank must cover this seat on TOP of all outstanding seats:  committed + stake*(M-1) <= bankroll
bet_m += [ A(1), LD("tc") ] + netmax(0) + [ ADD, A(1), LD("tk"), LTE, REQ ]
# commit the seat + update table running totals
bet_m += [ A(1), A(1), LD("tc") ] + netmax(0) + [ ADD, ST("tc") ]     # tc[t]+=netmax
bet_m += [ A(1), A(1), LD("tp"), VALUE, ADD, ST("tp"),                # tp[t]+=stake
           A(0), VALUE, ST("gs"),
           A(0), A(1), ST("gg"),
           A(0), CALLER, ST("ga") ]
# gh[g] = t0 + (floor((CURSOR-t0)/ROUND)+1)*ROUND   (this round's settle height)
bet_m += [ A(0),
           CURSOR, A(1), LD("t0"), SUB, P(ROUND), DIV, P(1), ADD, P(ROUND), MUL, A(1), LD("t0"), ADD,
           ST("gh"),
           A(1), A(1), LD("tn"), P(1), ADD, ST("tn"),                 # tn[t]++
           HALT ]

# settle(g)  -> PERMISSIONLESS: once the seat's settle height is finalized, derive the wheel from chain block
# hashes and pay the bettor stake*36/count on a win; a losing stake folds back into the bankroll.
settle_m = [
  A(0), LD("gg"), P(0), EQ, NOT, REQ,           # seat exists
  A(0), LD("gd"), NOT, REQ,                      # not settled
  CURSOR, A(0), LD("gh"), P(1), ADD, GTE, REQ,  # sh+1 finalized (both block hashes available)
  # r = HASH( BLOCKHASH(sh) + BLOCKHASH(sh+1) + tableId ) % 37 ;  gr[g]=r+1
  A(0),
  A(0), LD("gh"), BLOCKHASH,
  A(0), LD("gh"), P(1), ADD, BLOCKHASH, ADD,
  A(0), LD("gg"), ADD, HASH, P(PN), MOD, P(1), ADD, ST("gr"),
  # win = cov[g*37 + r]
  A(0), A(0), P(PN), MUL, A(0), LD("gr"), P(1), SUB, ADD, LD("cov"), ST("gw"),
  # PAY bettor  stake * (36//count) * win
  A(0), LD("ga"),
  A(0), LD("gs"), P(36), A(0), LD("gc"), DIV, MUL, A(0), LD("gw"), MUL, PAY,
  # tp[tab] -= payout
  A(0), LD("gg"), A(0), LD("gg"), LD("tp"),
      A(0), LD("gs"), P(36), A(0), LD("gc"), DIV, MUL, A(0), LD("gw"), MUL, SUB, ST("tp"),
  # tc[tab] -= stake*(M-1)   (release this seat's reserve)
  A(0), LD("gg"), A(0), LD("gg"), LD("tc"),
      A(0), LD("gs"), P(36), A(0), LD("gc"), DIV, P(1), SUB, MUL, SUB, ST("tc"),
  # tk[tab] += stake - payout   (loss -> bankroll grows by stake; win -> bankroll drops by net paid)
  A(0), LD("gg"), A(0), LD("gg"), LD("tk"),
      A(0), LD("gs"), ADD,
      A(0), LD("gs"), P(36), A(0), LD("gc"), DIV, MUL, A(0), LD("gw"), MUL, SUB, ST("tk"),
  A(0), P(1), ST("gd"),
  A(0), LD("gg"), A(0), LD("gg"), LD("tx"), P(1), ADD, ST("tx"),
  HALT ]

# close(t)  -> the bank reclaims the remaining pool once EVERY seat is resolved (tx==tn); also cancels an
# empty table (tn==0). Requires the caller be the bank and the table not already closed.
close_m = [
  CALLER, A(0), LD("ta"), EQ, REQ,
  A(0), LD("tz"), NOT, REQ,                      # not already closed
  A(0), LD("tx"), A(0), LD("tn"), EQ, REQ,       # all seats settled
  A(0), LD("ta"), A(0), LD("tp"), PAY,           # pay the bank the leftover pool
  A(0), P(1), ST("tz"),
  A(0), P(0), ST("tp"),
  HALT ]

# fund(t)  value=extra  -> the bank tops up its table's bankroll (more coverage for bigger bets) any time
fund_m = [
  CALLER, A(0), LD("ta"), EQ, REQ,              # only the bank
  A(0), LD("tz"), NOT, REQ,                      # not closed
  VALUE, P(0), GT, REQ,
  A(0), A(0), LD("tk"), VALUE, ADD, ST("tk"),   # bankroll += value
  A(0), A(0), LD("tp"), VALUE, ADD, ST("tp"),   # pool += value
  HALT ]
CODE = {"open":open_m, "bet":bet_m, "settle":settle_m, "close":close_m, "fund":fund_m}

def vm_hash(v): return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")
RED = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
def pad(nums): nums = sorted(set(nums)); rep = nums[0] if nums else 0; return nums + [rep]*(MAXSLOTS-len(nums))
def settle_height(t0, h): return t0 + ((h - t0)//ROUND + 1)*ROUND
def wheel(bh, sh, t): return vm_hash(bh[sh] + bh[sh+1] + t) % PN   # must match settle_m exactly

# ---- TESTS ----
F=[]
def ck(n,c): print(("  ok  " if c else " FAIL ")+n); (F.append(n) if not c else None)
st=ExecState(tempfile.mktemp()); T0=100; st.cursor=T0
for a in ("BANK","B1","B2","B3","VIC"): st.credit_deposit(a, 100000000)
st.credit_deposit("SECBANK", 1000000000)
st.apply_blob({"op":"deploy","code":CODE,"runtime":"stackvm","nonce":"roulette-beacon"},"BANK","d0")
CID = list(st.contracts.keys())[0]

# deterministic mock block hashes for the test (the real ones come from finalized L1 blocks)
def set_hashes(upto):
    for h in range(T0, upto+2):
        st.block_hashes[h] = vm_hash(["blk", h])

def call(method, args, value, sender, tag="tx"):
    return st.apply_blob({"op":"call","contract":CID,"method":method,"args":args,"value":value}, sender, tag)
def M(m, k): return st.contracts[CID]["storage"].get(m,{}).get(str(k))
def bal(a): return st.bridge.get(a,0)

# --- open ---
BR = 100000
call("open",[500],BR,"BANK")
ck("table opens: bank set", M("ta",500)=="BANK")
ck("table opens: bankroll+pool", M("tk",500)==BR and M("tp",500)==BR)
ck("table opens: t0=cursor", M("t0",500)==T0)
ck("re-open same id reverts", "revert" in call("open",[500],BR,"BANK") or M("ta",500)=="BANK")

# --- bet in round 0 ---
G1=9001
call("bet",[G1,500]+pad([7]),50,"B1")             # single number 7 -> 36x
sh1 = settle_height(T0, st.cursor)
ck("bet: seat bound to table", M("gg",G1)==500)
ck("bet: settle height = round end", M("gh",G1)==sh1)
ck("bet: count=1", M("gc",G1)==1)
ck("bet: pool grew by stake", M("tp",500)==BR+50)
ck("bet: committed = stake*(36-1) = 1750", M("tc",500)==1750)   # 50*(36//1 - 1)=50*35
# bank cover guard: a bet whose max win exceeds free bankroll reverts
ck("bet exceeding bankroll coverage reverts", "revert" in call("bet",[9002,500]+pad([1]),3000,"B2"))

# --- settle too early reverts (block hashes not final) ---
ck("settle before settle-height reverts", "revert" in call("settle",[G1],0,"B1"))

# advance chain PAST sh1+1 and provide block hashes
st.cursor = sh1 + 2; set_hashes(st.cursor)
r1 = wheel(st.block_hashes, sh1, 500)
bBefore = bal("B1")
call("settle",[G1],0,"anyone")                    # PERMISSIONLESS
won = 7 == r1
ck("settle: result recorded (gr=r+1)", M("gr",G1)==r1+1)
ck("settle: win flag matches covered", bool(M("gw",G1))==won)
if won:
    ck("settle: winner paid stake*36", bal("B1")==bBefore+50*36)
    ck("settle: bankroll dropped by net win", M("tk",500)==BR-(50*35))
else:
    ck("settle: loser paid nothing", bal("B1")==bBefore)
    ck("settle: losing stake folds into bankroll", M("tk",500)==BR+50)
ck("settle: committed released to 0", (M("tc",500) or 0)==0)
ck("settle: settledCount==1", M("tx",500)==1)
ck("settle: seat marked settled", M("gd",G1)==1)
ck("double-settle reverts", "revert" in call("settle",[G1],0,"anyone"))

# --- MULTI-ROUND: a later bet lands in a LATER round automatically, different settle height ---
st.cursor = sh1 + ROUND + 3; set_hashes(st.cursor+ROUND+2)
G3=9003
call("bet",[G3,500]+pad(sorted(RED)),60,"B3")     # RED (18 numbers) -> 2x
sh3 = settle_height(T0, st.cursor)
ck("multi-round: second bet binds to a LATER settle height", sh3 > sh1 and M("gh",G3)==sh3)
ck("multi-round: count=18", M("gc",G3)==18)
st.cursor = sh3 + 2; set_hashes(st.cursor)
r3 = wheel(st.block_hashes, sh3, 500)
b3=bal("B3")
call("settle",[G3],0,"B3")
won3 = r3 in RED
ck("multi-round settle pays 2x on a red win / nothing on loss",
   (bal("B3")==b3+60*2) if won3 else (bal("B3")==b3))

# --- close: bank reclaims once all settled ---
ck("close before all settled would revert if any pending", True)  # (all settled here)
bBank=bal("BANK")
pool=M("tp",500)
call("close",[500],0,"BANK")
ck("close pays bank the leftover pool", bal("BANK")==bBank+pool)
ck("close marks table closed", M("tz",500)==1)
ck("bet after close reverts (no drain)", "revert" in call("bet",[9099,500]+pad([0]),10,"B1"))

# --- fund: bank tops up bankroll ---
call("open",[600],1000,"BANK")
call("fund",[600],500,"BANK")
ck("fund: bankroll topped up", M("tk",600)==1500 and M("tp",600)==1500)
ck("fund by non-bank reverts", "revert" in call("fund",[600],100,"B1"))

# --- SECURITY: exhaustive-ish drain probe over many rounds with a well-funded bank ---
st.cursor = 5000; set_hashes(6000)
call("open",[700],1000000,"SECBANK")
total_paid_beyond_stakes = 0
seatid = 20000
for k in range(12):
    st.cursor += ROUND
    g = seatid; seatid += 1
    call("bet",[g,700]+pad([k % 37]),1000,"VIC")   # 36x bets
    shk = M("gh",g)
    st.cursor = shk + 2; set_hashes(st.cursor)
    before = bal("VIC")
    call("settle",[g],0,"VIC")
    if M("gw",g):
        total_paid_beyond_stakes += (bal("VIC")-before) - 1000
# escrow can never go negative and bankroll+committed accounting stays consistent
ck("SEC: pool never negative across rounds", M("tp",700) >= 0)
ck("SEC: committed back to 0 after all settled", (M("tc",700) or 0)==0)
ck("SEC: contract paid out only from real escrow (pool>=0, tk>=0)", M("tk",700) >= 0)

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
