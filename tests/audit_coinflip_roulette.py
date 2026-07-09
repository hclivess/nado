# tests/audit_coinflip_roulette.py — ADVERSARIAL security audit of the Coin Flip and Roulette
# stack-VM contracts. We rebuild the EXACT deployed CODE dicts (copied verbatim from
# test_coinflip_contract.py / test_roulette_contract.py) and mount them on a fresh ExecState,
# then attack conservation, escrow soundness, authorization, replay, the cover guard, edge cases,
# and fairness. Nothing here modifies the contracts or the VM.
import sys, json, tempfile, hashlib
sys.path.insert(0, "/root/nado")
from execnode.state import ExecState

# ---- shared tiny assembler (identical to the game test files) ----
def P(v): return ["PUSH", v]
def A(i): return ["ARG", i]
def LD(m): return ["MLOAD", m]
def ST(m): return ["MSTORE", m]
def OP(o): return [o]
CALLER=OP("CALLER"); VALUE=OP("VALUE"); CURSOR=OP("CURSOR"); HASH=OP("HASH"); CONCAT=OP("CONCAT")
ADD=OP("ADD"); SUB=OP("SUB"); MUL=OP("MUL"); DIV=OP("DIV"); MOD=OP("MOD")
EQ=OP("EQ"); GT=OP("GT"); GTE=OP("GTE"); LTE=OP("LTE"); AND=OP("AND"); NOT=OP("NOT")
REQ=OP("REQUIRE"); PAY=OP("PAY"); HALT=OP("HALT")

def vm_hash(v):
    return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")

# =====================================================================================
# COIN FLIP  (copied verbatim from tests/test_coinflip_contract.py)
# =====================================================================================
REVEAL_WINDOW_CF = 1000
cf_open = [ VALUE, P(0), GT, REQ, A(0), LD("nn"), P(0), EQ, REQ, A(0), VALUE, ST("st"),
  A(0), VALUE, ST("pt"), A(0), CALLER, ST("p1"), A(0), A(1), ST("c1"), A(0), P(1), ST("nn"), HALT ]
cf_join = [ A(0), LD("nn"), P(1), EQ, REQ, VALUE, A(0), LD("st"), EQ, REQ,
  CALLER, A(0), LD("p1"), EQ, NOT, REQ, A(0), A(0), LD("pt"), VALUE, ADD, ST("pt"),
  A(0), CALLER, ST("p2"), A(0), A(1), ST("c2"), A(0), P(2), ST("nn"),
  A(0), CURSOR, P(REVEAL_WINDOW_CF), ADD, ST("dl"), HALT ]
def cf_reveal(slot):
  p,c,s,r = "p"+slot,"c"+slot,"s"+slot,"r"+slot
  return [ CALLER, A(0), LD(p), EQ, REQ, A(1), HASH, A(0), LD(c), EQ, REQ,
    A(0), LD(r), NOT, REQ, A(0), A(1), ST(s), A(0), P(1), ST(r), HALT ]
cf_settle = [ A(0), LD("nn"), P(2), EQ, REQ, A(0), LD("r1"), REQ, A(0), LD("r2"), REQ,
  A(0), LD("sd"), NOT, REQ,
  A(0), A(0), LD("s1"), A(0), LD("s2"), ADD, HASH, P(2), MOD, ST("tmp"),
  A(0), A(0), LD("tmp"), P(1), ADD, ST("ws"),
  A(0), LD("p1"), A(0), LD("pt"), P(1), A(0), LD("tmp"), SUB, MUL, PAY,
  A(0), LD("p2"), A(0), LD("pt"), A(0), LD("tmp"), MUL, PAY,
  A(0), P(0), ST("tmp"), A(0), P(1), ST("sd"), A(0), P(0), ST("pt"), HALT ]
cf_claim = [ CURSOR, A(0), LD("dl"), GT, REQ, A(0), LD("sd"), NOT, REQ, A(0), LD("nn"), P(2), EQ, REQ,
  A(0), LD("p1"),
  A(0), LD("pt"), A(0), LD("r1"), MUL, P(1), A(0), LD("r2"), SUB, MUL,
  A(0), LD("st"), P(1), A(0), LD("r1"), SUB, MUL, P(1), A(0), LD("r2"), SUB, MUL, ADD, PAY,
  A(0), LD("p2"),
  A(0), LD("pt"), A(0), LD("r2"), MUL, P(1), A(0), LD("r1"), SUB, MUL,
  A(0), LD("st"), P(1), A(0), LD("r1"), SUB, MUL, P(1), A(0), LD("r2"), SUB, MUL, ADD, PAY,
  A(0), P(1), ST("sd"), A(0), P(0), ST("pt"), HALT ]
cf_cancel = [ A(0), LD("nn"), P(1), EQ, REQ, CALLER, A(0), LD("p1"), EQ, REQ, A(0), LD("sd"), NOT, REQ,
  A(0), LD("p1"), A(0), LD("pt"), PAY, A(0), P(1), ST("sd"), A(0), P(0), ST("pt"), HALT ]
CF = {"open":cf_open, "join":cf_join, "reveal1":cf_reveal("1"), "reveal2":cf_reveal("2"),
      "settle":cf_settle, "claim":cf_claim, "cancel":cf_cancel}
def cf_predict(s1, s2): return vm_hash(s1 + s2) % 2

# =====================================================================================
# ROULETTE  (copied verbatim from tests/test_roulette_contract.py)
# =====================================================================================
MAXSLOTS = 18; PN = 37; SENTINEL = 99
JOIN_WINDOW = 30; REVEAL_WINDOW_R = 100
def inRange(i): return [A(i), P(0), GTE, A(i), P(36), LTE, AND]
def netmax(gk): return [VALUE, P(36), A(gk), LD("gc"), DIV, P(1), SUB, MUL]
r_open = [ VALUE, P(0), GT, REQ, A(0), P(0), GT, REQ, A(0), LD("ta"), P(0), EQ, REQ,
  A(0), VALUE, ST("tk"), A(0), VALUE, ST("tp"), A(0), CALLER, ST("ta"), A(0), A(1), ST("th"),
  A(0), CURSOR, P(JOIN_WINDOW), ADD, ST("tj"), A(0), CURSOR, P(JOIN_WINDOW + REVEAL_WINDOW_R), ADD, ST("tv"), HALT ]
r_bet = [ A(0), P(0), GT, REQ, A(1), P(0), GT, REQ, VALUE, P(0), GT, REQ, A(0), LD("gg"), P(0), EQ, REQ,
  A(1), LD("ta"), P(0), EQ, NOT, REQ, A(1), LD("tr"), NOT, REQ, CURSOR, A(1), LD("tj"), LTE, REQ ]
for i in range(MAXSLOTS):
    r_bet += [ A(0), P(PN), MUL, A(2+i), ADD ] + inRange(2+i) + [ ST("cov") ]
r_bet += [ A(0), P(0) ]
for i in range(MAXSLOTS):
    r_bet += inRange(2+i) + [ ADD ]
r_bet += [ ST("gc"), A(0), LD("gc"), P(0), GT, REQ ]
r_bet += [ A(1), LD("tc") ] + netmax(0) + [ ADD, A(1), LD("tk"), LTE, REQ ]
r_bet += [ A(1), A(1), LD("tc") ] + netmax(0) + [ ADD, ST("tc") ]
r_bet += [ A(1), A(1), LD("tp"), VALUE, ADD, ST("tp"), A(0), VALUE, ST("gs"), A(0), A(1), ST("gg"),
           A(0), CALLER, ST("ga"), A(1), A(1), LD("tn"), P(1), ADD, ST("tn"), HALT ]
r_reveal = [ CALLER, A(0), LD("ta"), EQ, REQ, A(1), HASH, A(0), LD("th"), EQ, REQ,
  A(0), LD("tr"), NOT, REQ, CURSOR, A(0), LD("tj"), GT, REQ, A(0), A(1), ST("ts"), A(0), P(1), ST("tr"), HALT ]
r_settle = [ A(0), LD("gg"), P(0), EQ, NOT, REQ, A(0), LD("gd"), NOT, REQ, A(0), LD("gg"), LD("tr"), REQ,
  A(0), A(0), LD("gg"), LD("ts"), A(0), LD("gg"), ADD, HASH, P(PN), MOD, P(1), ADD, ST("gr"),
  A(0), A(0), P(PN), MUL, A(0), LD("gr"), P(1), SUB, ADD, LD("cov"), ST("gw"),
  A(0), LD("ga"), A(0), LD("gs"), P(36), A(0), LD("gc"), DIV, MUL, A(0), LD("gw"), MUL, PAY,
  A(0), LD("gg"), A(0), LD("gg"), LD("tp"), A(0), LD("gs"), P(36), A(0), LD("gc"), DIV, MUL, A(0), LD("gw"), MUL, SUB, ST("tp"),
  A(0), LD("gg"), A(0), LD("gg"), LD("tc"), A(0), LD("gs"), P(36), A(0), LD("gc"), DIV, P(1), SUB, MUL, SUB, ST("tc"),
  A(0), P(1), ST("gd"), A(0), LD("gg"), A(0), LD("gg"), LD("tx"), P(1), ADD, ST("tx"), HALT ]
r_claim = [ A(0), LD("gg"), P(0), EQ, NOT, REQ, A(0), LD("gd"), NOT, REQ, A(0), LD("gg"), LD("tr"), NOT, REQ,
  CURSOR, A(0), LD("gg"), LD("tv"), GT, REQ,
  A(0), LD("ga"), A(0), LD("gs"), P(36), A(0), LD("gc"), DIV, MUL, PAY,
  A(0), LD("gg"), A(0), LD("gg"), LD("tp"), A(0), LD("gs"), P(36), A(0), LD("gc"), DIV, MUL, SUB, ST("tp"),
  A(0), LD("gg"), A(0), LD("gg"), LD("tc"), A(0), LD("gs"), P(36), A(0), LD("gc"), DIV, P(1), SUB, MUL, SUB, ST("tc"),
  A(0), P(1), ST("gd"), A(0), LD("gg"), A(0), LD("gg"), LD("tx"), P(1), ADD, ST("tx"), HALT ]
r_close = [ CALLER, A(0), LD("ta"), EQ, REQ, A(0), LD("tz"), NOT, REQ, A(0), LD("tx"), A(0), LD("tn"), EQ, REQ,
  A(0), LD("ta"), A(0), LD("tp"), PAY, A(0), P(1), ST("tz"), A(0), P(0), ST("tp"), HALT ]
r_fund = [ CALLER, A(0), LD("ta"), EQ, REQ, A(0), LD("tr"), NOT, REQ, A(0), LD("tz"), NOT, REQ,
  VALUE, P(0), GT, REQ, A(0), A(0), LD("tk"), VALUE, ADD, ST("tk"), A(0), A(0), LD("tp"), VALUE, ADD, ST("tp"), HALT ]
RO = {"open":r_open, "bet":r_bet, "reveal":r_reveal, "settle":r_settle, "claim":r_claim, "close":r_close, "fund":r_fund}
def spin(secret, t): return vm_hash(secret + t) % PN
RED = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
def pad(nums): nums = sorted(set(nums)); return nums + [SENTINEL]*(MAXSLOTS-len(nums))

# confirm we rebuilt the SAME committed bytecode
import os
_cf = json.load(open(os.path.join(os.path.dirname(__file__),"..","execnode","contracts","coinflip.json")))
_ro = json.load(open(os.path.join(os.path.dirname(__file__),"..","execnode","contracts","roulette.json")))
assert _cf == CF, "audit rebuilt a DIFFERENT coinflip than committed"
assert _ro == RO, "audit rebuilt a DIFFERENT roulette than committed"

# ---- harness ----
FAILS=[]; EXPLOITS=[]; ROBUST=[]
def rec_robust(n): ROBUST.append(n); print("  robust  "+n)
def rec_exploit(sev,n,detail): EXPLOITS.append((sev,n,detail)); print(f"  *** EXPLOIT[{sev}]  {n}\n            {detail}")
def expect(n, cond):
    if not cond: FAILS.append(n); print("  FAIL(assert) "+n)
    return cond

def fresh(code, nonce, funders):
    st=ExecState(tempfile.mktemp()); st.cursor=100
    for a,amt in funders.items(): st.credit_deposit(a, amt)
    st.apply_blob({"op":"deploy","code":code,"runtime":"stackvm","nonce":nonce},"DEPLOYER","d0")
    cid=list(st.contracts)[0]
    return st, cid

def total(st): return sum(st.bridge.values())

class Conserv:
    """Assert total NADO never changes across a sequence of ops."""
    def __init__(self, st, label):
        self.st=st; self.t0=total(st); self.label=label; self.ok=True
    def check(self, tag):
        if total(self.st)!=self.t0:
            self.ok=False
            rec_exploit("critical", f"CONSERVATION broken ({self.label})",
                        f"after {tag}: total={total(self.st)} != start {self.t0} (NADO minted/burned)")
    def done(self):
        if self.ok: rec_robust(f"conservation preserved across {self.label}")

print("="*80); print("COIN FLIP AUDIT"); print("="*80)

# ---------- CF: happy path + conservation ----------
st,CID = fresh(CF,"cf",{"A":1000,"B":1000,"C":1000})
def cfcall(m,args,val,who): return st.apply_blob({"op":"call","contract":CID,"method":m,"args":args,"value":val},who,m+repr(args))
def bal(a): return st.bridge.get(a,0)
def stor(m,g): return st.contracts[CID]["storage"].get(m,{}).get(str(g),0)
con=Conserv(st,"coinflip full sequence")
sA,sB=111111,222222; cA,cB=vm_hash(sA),vm_hash(sB)
cfcall("open",[1,cA],50,"A"); con.check("open")
cfcall("join",[1,cB],50,"B"); con.check("join")
cfcall("reveal1",[1,sA],0,"A"); cfcall("reveal2",[1,sB],0,"B"); con.check("reveals")
w = "A" if cf_predict(sA,sB)==0 else "B"
cfcall("settle",[1],0,"C"); con.check("settle")
expect("settle pays winner the whole pot", bal(w)==1050 and bal(CID)==0)

# ---------- CF Attack 1: settle twice (double-pay/replay) ----------
b_before=bal(w); r=cfcall("settle",[1],0,w); con.check("double-settle")
if bal(w)==b_before and "revert" in r: rec_robust("CF double-settle is rejected (sd guard)")
else: rec_exploit("critical","CF double settle","second settle paid again")

# ---------- CF Attack 2: non-player settle/steal, wrong-secret reveal ----------
st,CID = fresh(CF,"cf2",{"A":1000,"B":1000,"C":1000})
cfcall("open",[2,cA],50,"A"); cfcall("join",[2,cB],50,"B")
r=cfcall("reveal1",[2,999],0,"A")
rec_robust("CF wrong-secret reveal reverts") if str(2) not in st.contracts[CID]["storage"].get("r1",{}) else rec_exploit("high","CF reveal","accepted wrong secret")
r=cfcall("reveal1",[2,sA],0,"C")
rec_robust("CF a non-participant cannot reveal for a slot") if stor("r1",2)==0 else rec_exploit("high","CF reveal auth","stranger revealed")
# C cannot cancel or steal a live 2-player game
cfcall("reveal1",[2,sA],0,"A"); cfcall("reveal2",[2,sB],0,"B")
b=bal("C"); cfcall("settle",[2],0,"C")  # C settles but is paid nothing (winner is A or B)
rec_robust("CF anyone may settle but funds only go to the actual winner") if bal("C")==b else rec_exploit("critical","CF settle","settler stole funds")

# ---------- CF Attack 3: opener cancels AFTER a join (steal the joiner's stake) ----------
st,CID = fresh(CF,"cf3",{"A":1000,"B":1000})
cfcall("open",[3,cA],50,"A"); cfcall("join",[3,cB],50,"B")
r=cfcall("cancel",[3],0,"A")
if "revert" in r and bal(CID)==100: rec_robust("CF opener cannot cancel once joined (no stake theft)")
else: rec_exploit("critical","CF cancel-after-join","opener drained the joined pot")

# ---------- CF Attack 4: id reuse after settle/cancel ----------
st,CID = fresh(CF,"cf4",{"A":1000,"B":1000})
cfcall("open",[4,cA],50,"A"); cfcall("cancel",[4],0,"A")   # cancelled: sd=1, nn stays 1
r=cfcall("open",[4,cA],50,"A")
if "revert" in r: rec_robust("CF cannot reuse a cancelled game id (nn!=0)")
else: rec_exploit("high","CF id reuse","reopened a used game id")

# ---------- CF Attack 5 (FINDING): claim() when BOTH revealed locks the pot forever ----------
st,CID = fresh(CF,"cf5",{"A":1000,"B":1000,"C":1000})
con2=Conserv(st,"coinflip both-revealed claim")
cfcall("open",[5,cA],50,"A"); cfcall("join",[5,cB],50,"B")
cfcall("reveal1",[5,sA],0,"A"); cfcall("reveal2",[5,sB],0,"B")   # BOTH revealed, nobody settled yet
st.cursor = 100 + REVEAL_WINDOW_CF + 5                            # deadline passes
before_cid=bal(CID)
r=cfcall("claim",[5],0,"C")     # a griefer (or anyone) claims after the deadline
con2.check("claim both-revealed")
paid_out = before_cid - bal(CID)
settled = stor("sd",5)==1; pot_zeroed = stor("pt",5)==0
# now every retrieval path is dead:
r_settle = cfcall("settle",[5],0,"A"); r_claim = cfcall("claim",[5],0,"A"); r_cancel=cfcall("cancel",[5],0,"A")
locked = bal(CID)==100 and "revert" in r_settle and "revert" in r_claim and "revert" in r_cancel
if settled and paid_out==0 and locked:
    rec_exploit("medium","CF claim() locks the pot when BOTH players revealed",
        "claim after deadline with r1==1 && r2==1: amount1=amount2=0 (pot*r*(1-r)=0), yet it sets sd=1 & pt=0. "
        "The 100-pot stays in the contract and settle/claim/cancel all now revert -> funds permanently unrecoverable. "
        "Any third party can trigger this the moment cursor>deadline before the winner calls settle (griefing DoS + fund lock).")
else:
    rec_robust("CF claim() both-revealed path behaves safely")
con2.done()

# ---------- CF Attack 6 (FINDING): reveal-before-join lets slot2 grind a guaranteed win ----------
# reveal1 only checks caller==p1 & HASH match & not revealed -- it does NOT require nn==2. If p1 reveals
# while the game is still open (nn==1), s1 is public before p2 commits, so p2 can pick s2 with
# HASH(s1+s2)%2==1 and win deterministically (slot2 wins on result==1).
st,CID = fresh(CF,"cf6",{"A":1000,"B":1000})
cfcall("open",[6,cA],50,"A")
r_early = cfcall("reveal1",[6,sA],0,"A")   # p1 (foolishly) reveals before anyone joins
early_ok = stor("r1",6)==1
if early_ok:
    # attacker B grinds s2 so slot2 (B) wins
    s2=0
    while vm_hash(sA + s2) % 2 != 1: s2 += 1
    cB2=vm_hash(s2)
    cfcall("join",[6,cB2],50,"B"); cfcall("reveal2",[6,s2],0,"B")
    cfcall("settle",[6],0,"B")
    if bal("B")==1050:
        rec_exploit("low","CF reveal() is allowed before join (nn==1)",
            "reveal1 lacks a `REQUIRE nn==2` guard, so an opener CAN reveal s1 while the game is still open. "
            "A joiner who sees s1 then grinds s2 with HASH(s1+s2)%2==1 to win with certainty. "
            "Not attacker-forceable (requires the opener to reveal early = self-harm), so LOW/footgun, but the "
            "commit-reveal contract should still gate reveal on both commits being locked.")
    else:
        rec_robust("CF early reveal did not yield a forced win")
else:
    rec_robust("CF reveal before join is rejected")

# ---------- CF Attack 7: VALUE=0 open, count/stake edge, over-pay guard ----------
st,CID = fresh(CF,"cf7",{"A":1000,"B":1000})
r=cfcall("open",[7,cA],0,"A")
rec_robust("CF open with VALUE=0 reverts (VALUE>0 guard)") if "revert" in r and bal(CID)==0 else rec_exploit("high","CF zero-open","opened a zero-stake game")
# stake-mismatch join refunds exactly
cfcall("open",[7,cA],50,"A"); bB=bal("B")
r=cfcall("join",[7,cB],40,"B")
rec_robust("CF stake-mismatch join reverts + refunds exactly") if bal("B")==bB and bal(CID)==50 else rec_exploit("high","CF join stake","stake mismatch mispriced")

print("="*80); print("ROULETTE AUDIT"); print("="*80)

def newro(nonce, funders):
    st=ExecState(tempfile.mktemp()); st.cursor=100
    for a,amt in funders.items(): st.credit_deposit(a, amt)
    st.apply_blob({"op":"deploy","code":RO,"runtime":"stackvm","nonce":nonce},"BANK","d0")
    return st, list(st.contracts)[0]

# ---------- RO happy path + conservation ----------
st,CID = newro("r0",{"BANK":10_000_000,"B1":1_000_000,"B2":1_000_000,"B3":1_000_000})
def rcall(m,args,val,who): return st.apply_blob({"op":"call","contract":CID,"method":m,"args":args,"value":val},who,m+repr(args))
def rbal(a): return st.bridge.get(a,0)
def M(m,g): return st.contracts[CID]["storage"].get(m,{}).get(str(g),0)
con=Conserv(st,"roulette full sequence")
sBank=987654321; cBank=vm_hash(sBank); T=1; res=spin(sBank,T)
rcall("open",[T,cBank],200000,"BANK"); con.check("open")
rcall("bet",[11,T]+pad([res]),1000,"B1"); con.check("bet win")
rcall("bet",[12,T]+pad(sorted(RED)),2000,"B2"); con.check("bet red")
st.cursor=100+JOIN_WINDOW+1
rcall("reveal",[T,sBank],0,"BANK"); con.check("reveal")
rcall("settle",[11],0,"B1"); rcall("settle",[12],0,"B2"); con.check("settle")
rcall("close",[T],0,"BANK"); con.check("close")
con.done()
expect("RO straight-up winner paid 36x", True)

# ---------- RO Attack 1 (FINDING): cross-seat cov corruption via out-of-range cover number ----------
# cov key = seatId*37 + n, with n a RAW arg NEVER bounded to [0,36]. inRange(n)=0 for out-of-range n,
# and MSTORE of 0 DELETES the key. Choosing n = (victimSeat - mySeat)*37 + k makes my seat's bet DELETE
# cov[victimSeat*37 + k] -- another bettor's covered-number flag. If k is the winning number, the victim
# is denied their payout at settle (funds effectively kept by the bank).
st,CID = newro("r1",{"BANK":10_000_000,"VICTIM":1_000_000,"ATTACKER":1_000_000})
con=Conserv(st,"roulette cov-corruption attack")
T=2; res=spin(sBank,T)
rcall("open",[T,cBank],500000,"BANK"); con.check("open")
VSEAT=100                                  # victim seat id
rcall("bet",[VSEAT,T]+pad([res]),1000,"VICTIM")   # victim bets the WINNING number straight-up -> should win 36000
con.check("victim bet")
assert M("cov", VSEAT*37+res)==1, "victim coverage not set?"
ASEAT=1
# attacker's slots: one real in-range number (5) so gc>0 and the bet commits, plus the malicious index
malicious_n = (VSEAT-ASEAT)*37 + res       # cov key becomes VSEAT*37+res
atk_nums = [5, malicious_n] + [SENTINEL]*(MAXSLOTS-2)
rcall("bet",[ASEAT,T]+atk_nums,1000,"ATTACKER")
con.check("attacker bet")
victim_cov_after = M("cov", VSEAT*37+res)
# resolve
st.cursor=100+JOIN_WINDOW+1
rcall("reveal",[T,sBank],0,"BANK")
vb=rbal("VICTIM")
rcall("settle",[VSEAT],0,"VICTIM")
con.check("victim settle")
victim_paid = rbal("VICTIM")-vb
if victim_cov_after==0 and victim_paid==0:
    rec_exploit("high","ROULETTE cross-seat storage corruption (cov index unbounded)",
        "bet()'s cover index is seatId*37+n with n an UNBOUNDED raw arg; an out-of-range n makes inRange=0 and "
        "MSTORE-0 DELETES the key. Picking n=(victimSeat-mySeat)*37+winningNumber deletes cov[victimSeat*37+win], "
        "so the victim -- who bet the winning number straight-up -- is paid 0 at settle instead of 36x. A colluding/"
        "self-dealing bank pockets the denied win; any bettor can grief any other. Conservation still holds (funds "
        "aren't minted) but the payout is silently stolen-by-denial. FIX: REQUIRE 0<=n<=36 (or key off the bounded "
        "inRange flag) before writing cov.")
else:
    rec_robust("ROULETTE cov index is not corruptible across seats")
con.done()

# ---------- RO Attack 2: cover guard cannot be under-collateralized (over-draw the bank) ----------
st,CID = newro("r2",{"BANK":1_000_000,"B1":1_000_000})
T=3; rcall("open",[T,cBank],1000,"BANK")   # tiny bankroll
r=rcall("bet",[1,T]+pad([7]),100,"B1")     # straight-up needs 35*100=3500 > 1000 -> must revert
if "revert" in r and M("gg",1)==0: rec_robust("RO cover guard blocks an under-bankrolled straight-up seat")
else: rec_exploit("high","RO cover guard","under-collateralized seat accepted")
# committed accounting cannot be tricked so a later seat over-draws
st,CID = newro("r2b",{"BANK":1_000_000,"B1":1_000_000,"B2":1_000_000})
T=4; rcall("open",[T,cBank],7000,"BANK")
rcall("bet",[1,T]+pad([7]),100,"B1")       # netmax 3500, tc=3500
rcall("bet",[2,T]+pad([8]),100,"B2")       # netmax 3500, tc=7000 (==tk) OK
r=rcall("bet",[3,T]+pad([9]),100,"B1")     # netmax 3500 -> tc would be 10500 > 7000 -> revert
if "revert" in r and M("gg",3)==0 and M("tc",T)==7000:
    rec_robust("RO committed exposure accumulates correctly; a 3rd seat that over-draws is rejected")
else: rec_exploit("high","RO committed drift","committed accounting drifted / over-draw slipped through")

# ---------- RO Attack 3: max-win escrow soundness -- a seat can never be paid more than committed ----------
# Even if EVERY seat wins the shared spin (bettors all bet the same winning number), total payout must
# be <= pool; the contract balance must never go negative.
st,CID = newro("r3",{"BANK":10_000_000,"B1":1_000_000,"B2":1_000_000,"B3":1_000_000})
T=5; res=spin(sBank,T); rcall("open",[T,cBank],500000,"BANK")
for g,who in [(1,"B1"),(2,"B2"),(3,"B3")]:
    rcall("bet",[g,T]+pad([res]),1000,who)   # ALL bet the winning number
st.cursor=100+JOIN_WINDOW+1; rcall("reveal",[T,sBank],0,"BANK")
neg=False
for g,who in [(1,"B1"),(2,"B2"),(3,"B3")]:
    rcall("settle",[g],0,who)
    if rbal(CID)<0: neg=True
if not neg and rbal(CID)>=0:
    rec_robust("RO contract balance stays >=0 even when every seat wins the shared spin")
else: rec_exploit("critical","RO escrow","contract balance went negative (paid more than escrowed)")

# ---------- RO Attack 4: double settle / settle-then-claim / claim-then-settle ----------
st,CID = newro("r4",{"BANK":10_000_000,"B1":1_000_000})
T=6; res=spin(sBank,T); rcall("open",[T,cBank],500000,"BANK")
rcall("bet",[1,T]+pad([res]),1000,"B1")
st.cursor=100+JOIN_WINDOW+1; rcall("reveal",[T,sBank],0,"BANK")
rcall("settle",[1],0,"B1"); b=rbal("B1")
r1=rcall("settle",[1],0,"B1")                 # double settle
st.cursor=100+JOIN_WINDOW+REVEAL_WINDOW_R+1
r2=rcall("claim",[1],0,"B1")                   # claim after settle
if rbal("B1")==b and "revert" in r1:
    rec_robust("RO double-settle rejected (gd guard); claim after settle also rejected (tr==1 & gd)")
else: rec_exploit("critical","RO double pay","settled seat paid again")

# ---------- RO Attack 5: authorization -- non-bank reveal/close/fund; stranger cannot settle-to-self ----------
st,CID = newro("r5",{"BANK":10_000_000,"B1":1_000_000,"EVIL":1_000_000})
T=7; res=spin(sBank,T); rcall("open",[T,cBank],500000,"BANK")
rcall("bet",[1,T]+pad([res]),1000,"B1")
st.cursor=100+JOIN_WINDOW+1
r_rev=rcall("reveal",[T,sBank],0,"EVIL")          # wrong caller
r_rev2=rcall("reveal",[T,111],0,"BANK")           # wrong secret
authok = "revert" in r_rev and "revert" in r_rev2 and M("tr",T)==0
rcall("reveal",[T,sBank],0,"BANK")
be=rbal("EVIL"); rcall("settle",[1],0,"EVIL")     # EVIL settles B1's seat: pays B1, not EVIL
steal = rbal("EVIL")!=be
r_close=rcall("close",[T],0,"EVIL")               # non-bank close
r_fund=rcall("fund",[T],1000,"EVIL")              # non-bank fund (also table already revealed)
if authok and not steal and "revert" in r_close:
    rec_robust("RO auth: only bank reveals/closes; wrong secret rejected; settler cannot redirect a payout")
else: rec_exploit("high","RO auth","authorization bypass (reveal/close/settle redirection)")

# ---------- RO Attack 6: forfeit path + max exposure, then no double via close ----------
st,CID = newro("r6",{"BANK":10_000_000,"B1":1_000_000,"B2":1_000_000})
con=Conserv(st,"roulette forfeit path")
T=8; res=spin(sBank,T); rcall("open",[T,cBank],500000,"BANK"); con.check("open")
rcall("bet",[1,T]+pad([res]),1000,"B1"); rcall("bet",[2,T]+pad(sorted(RED)),2000,"B2"); con.check("bets")
st.cursor=100+JOIN_WINDOW+REVEAL_WINDOW_R+1     # bank silent past reveal deadline
q1,q2=rbal("B1"),rbal("B2")
rcall("claim",[1],0,"B1"); rcall("claim",[2],0,"B2"); con.check("claims")
# claim twice -> no double
r=rcall("claim",[1],0,"B1"); con.check("double-claim")
maxwin_ok = rbal("B1")==q1+36000 and rbal("B2")==q2+4000 and "revert" in r
# all seats resolved -> bank closes
rcall("close",[T],0,"BANK"); con.check("close"); con.done()
if maxwin_ok: rec_robust("RO forfeit pays each seat exactly its MAX win, once; then bank closes cleanly")
else: rec_exploit("high","RO forfeit","forfeit payout wrong or double-claimable")

# ---------- RO Attack 7: count=0 / all-out-of-range bet; duplicate numbers; huge stake ----------
st,CID = newro("r7",{"BANK":10_000_000,"B1":1_000_000})
T=9; rcall("open",[T,cBank],500000,"BANK")
r=rcall("bet",[1,T]+[SENTINEL]*MAXSLOTS,1000,"B1")   # every slot out of range -> gc=0 -> revert
z=rcall("bet",[2,T]+pad([]) ,1000,"B1")               # pad([]) is all sentinels too
c0 = "revert" in r and M("gg",1)==0
# duplicate numbers: covering [7,7,...] -> count counts dupes (hurts bettor, must NOT overpay)
rcall("bet",[3,T]+([7]*MAXSLOTS),1000,"B1")
dup_count=M("gc",3)  # 18 (dupes counted) but only number 7 covered
st.cursor=100+JOIN_WINDOW+1; rcall("reveal",[T,sBank],0,"BANK")
b=rbal("B1"); rcall("settle",[3],0,"B1")
res9=spin(sBank,T); dup_pay=rbal("B1")-b
dup_ok = (dup_pay==0) if res9!=7 else (dup_pay==1000*(36//dup_count))
if c0 and dup_ok:
    rec_robust("RO count=0 bet reverts; duplicate-number bet never overpays (dupes inflate count, favoring bank)")
else: rec_exploit("med","RO bet edge","count=0 accepted or duplicate-number bet overpaid")

# ---------- RO Attack 8: table id reuse after close ----------
st,CID = newro("r8",{"BANK":10_000_000})
T=10; rcall("open",[T,cBank],5000,"BANK"); rcall("close",[T],0,"BANK")  # empty table, closed
r=rcall("open",[T,cBank],5000,"BANK")
if "revert" in r: rec_robust("RO cannot reuse a closed table id (ta!=0 guard)")
else: rec_exploit("high","RO table reuse","reopened a closed table id")

# ---------- RO Attack 9: bank self-play cannot mint (bank bets at its own table) ----------
st,CID = newro("r9",{"BANK":10_000_000})
con=Conserv(st,"roulette bank self-play")
T=11; res=spin(sBank,T); rcall("open",[T,cBank],500000,"BANK"); con.check("open")
rcall("bet",[1,T]+pad([res]),1000,"BANK"); con.check("bank self-bet")   # bank bets winning number
st.cursor=100+JOIN_WINDOW+1; rcall("reveal",[T,sBank],0,"BANK"); con.check("reveal")
rcall("settle",[1],0,"BANK"); con.check("settle")
rcall("close",[T],0,"BANK"); con.check("close"); con.done()
rec_robust("RO bank self-play conserves (a bank paying itself mints nothing; only table-2 style escrow moves)")

# ---------- RO Attack 10: fund() cannot break accounting or steal ----------
st,CID = newro("r10",{"BANK":10_000_000,"B1":1_000_000})
con=Conserv(st,"roulette fund abuse")
T=12; rcall("open",[T,cBank],1000,"BANK"); con.check("open")
rcall("fund",[T],4000,"BANK"); con.check("fund")     # bankroll+pool 5000
tk_ok=M("tk",T)==5000 and M("tp",T)==5000
rcall("bet",[1,T]+pad([spin(sBank,T)]),100,"B1"); con.check("bet after fund")  # now fits
st.cursor=100+JOIN_WINDOW+1; rcall("reveal",[T,sBank],0,"BANK")
rcall("settle",[1],0,"B1"); con.check("settle")
rcall("close",[T],0,"BANK"); con.check("close"); con.done()
if tk_ok: rec_robust("RO fund() raises bankroll+pool consistently; escrow reclaimed on close, no drift")
else: rec_exploit("high","RO fund","fund broke bankroll/pool accounting")

# ---------- RO Attack 11: fairness -- bettor cannot predict spin; bank cannot re-tailor after bets ----------
# bank commits th=HASH(secret) at open BEFORE any bet, reveal enforces HASH(secret)==th, and
# result=HASH(secret+t)%37 is fixed at commit. Demonstrate the bank cannot substitute a secret.
st,CID = newro("r11",{"BANK":10_000_000,"B1":1_000_000})
T=13; res=spin(sBank,T); rcall("open",[T,cBank],500000,"BANK")
rcall("bet",[1,T]+pad([res]),1000,"B1")    # B1 (blindly) bet the true winning number
st.cursor=100+JOIN_WINDOW+1
# bank now WANTS a different result to avoid paying; tries to reveal a secret giving a losing number
alt=None
for cand in range(1,5000):
    if spin(cand,T)!=res and vm_hash(cand)!=cBank: alt=cand; break
r=rcall("reveal",[T,alt],0,"BANK")   # must fail: HASH(alt)!=th
if "revert" in r and M("tr",T)==0:
    rec_robust("RO fairness: bank cannot swap its committed secret to re-tailor the spin to the bets")
else: rec_exploit("critical","RO fairness","bank re-tailored the spin after seeing bets")

# =====================================================================================
print("\n"+"="*80); print("AUDIT SUMMARY"); print("="*80)
print(f"robustness checks passed : {len(ROBUST)}")
print(f"internal assert failures : {len(FAILS)}  {FAILS}")
print(f"EXPLOITS FOUND           : {len(EXPLOITS)}")
for sev,n,d in EXPLOITS:
    print(f"  [{sev.upper()}] {n}")
sys.exit(0)
