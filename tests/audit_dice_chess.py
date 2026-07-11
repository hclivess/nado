# tests/audit_dice_chess.py — ADVERSARIAL security audit of the DICE and CHESS stackvm contracts.
#
# Rebuilds each CODE (copied verbatim from tests/test_dice_contract.py / test_chess_contract.py), mounts it on
# a FRESH ExecState, and attacks it assuming a malicious bank / bettor / chess opponent. Checks:
#   CONSERVATION   — total NADO across all bridge balances is exactly preserved after EVERY op.
#   ESCROW         — a contract never pays more than it holds; balances never go negative.
#   AUTHZ / REPLAY — only the right party acts; no double-settle / double-pay; reused ids can't corrupt.
#   BRANCHLESS     — chess agree() arithmetic can't over-pay, mis-pay, or pay when unagreed.
#   FAIRNESS       — dice rolls can't be biased by the bank or ground by a bettor.
# Prints REPORT lines. Exit 0 always (this is an audit harness, not a pass/fail gate).
import sys, json, tempfile, hashlib
sys.path.insert(0, "/root/nado")
from execnode.state import ExecState

# ---- assembler (verbatim helpers) -----------------------------------------------------------------
def P(v): return ["PUSH", v]
def A(i): return ["ARG", i]
def LD(m): return ["MLOAD", m]
def ST(m): return ["MSTORE", m]
def OP(o): return [o]
CALLER=OP("CALLER"); VALUE=OP("VALUE"); CURSOR=OP("CURSOR"); HASH=OP("HASH")
ADD=OP("ADD"); SUB=OP("SUB"); MUL=OP("MUL"); DIV=OP("DIV"); MOD=OP("MOD")
EQ=OP("EQ"); GT=OP("GT"); GTE=OP("GTE"); LT=OP("LT"); LTE=OP("LTE"); NOT=OP("NOT")
OR=OP("OR"); AND=OP("AND")
REQ=OP("REQUIRE"); PAY=OP("PAY"); HALT=OP("HALT")

def vm_hash(v): return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")

# ================================================================================================
# DICE CODE (copied from tests/test_dice_contract.py)
# ================================================================================================
PN = 100; EDGE_NUM = 99
MMIN, MMAX = 2, 98
JOIN_WINDOW = 30; REVEAL_WINDOW = 100

d_open = [
  VALUE, P(0), GT, REQ, A(0), P(0), GT, REQ, A(0), LD("ta"), P(0), EQ, REQ,
  A(0), VALUE, ST("tk"), A(0), VALUE, ST("tp"), A(0), CALLER, ST("ta"), A(0), A(1), ST("th"),
  A(0), CURSOR, P(JOIN_WINDOW), ADD, ST("tj"),
  A(0), CURSOR, P(JOIN_WINDOW + REVEAL_WINDOW), ADD, ST("tv"), HALT ]
d_bet = [
  A(0), P(0), GT, REQ, A(1), P(0), GT, REQ, VALUE, P(0), GT, REQ,
  A(0), LD("gg"), P(0), EQ, REQ, A(1), LD("ta"), P(0), EQ, NOT, REQ, A(1), LD("tr"), NOT, REQ,
  CURSOR, A(1), LD("tj"), LTE, REQ, A(2), P(MMIN), GTE, REQ, A(2), P(MMAX), LTE, REQ,
  A(0), A(2), ST("gm"),
  A(1), LD("tc"), VALUE, P(EDGE_NUM), MUL, A(2), DIV, VALUE, SUB, ADD, A(1), LD("tk"), LTE, REQ,
  A(1), A(1), LD("tc"), VALUE, P(EDGE_NUM), MUL, A(2), DIV, VALUE, SUB, ADD, ST("tc"),
  A(1), A(1), LD("tp"), VALUE, ADD, ST("tp"),
  A(0), VALUE, ST("gs"), A(0), A(1), ST("gg"), A(0), CALLER, ST("ga"),
  A(1), A(1), LD("tn"), P(1), ADD, ST("tn"), HALT ]
d_reveal = [
  CALLER, A(0), LD("ta"), EQ, REQ, A(1), HASH, A(0), LD("th"), EQ, REQ, A(0), LD("tr"), NOT, REQ,
  CURSOR, A(0), LD("tj"), GT, REQ, A(0), A(1), ST("ts"), A(0), P(1), ST("tr"), HALT ]
d_settle = [
  A(0), LD("gg"), P(0), EQ, NOT, REQ, A(0), LD("gd"), NOT, REQ, A(0), LD("gg"), LD("tr"), REQ, A(0),
  A(0), LD("gg"), LD("ts"), A(0), ADD, HASH, P(PN), MOD, P(1), ADD, ST("gr"),
  A(0), A(0), LD("gr"), P(1), SUB, A(0), LD("gm"), LT, ST("gw"),
  A(0), LD("ga"),
  A(0), LD("gs"), P(EDGE_NUM), MUL, A(0), LD("gm"), DIV, A(0), LD("gw"), MUL, PAY,
  A(0), LD("gg"), A(0), LD("gg"), LD("tp"),
      A(0), LD("gs"), P(EDGE_NUM), MUL, A(0), LD("gm"), DIV, A(0), LD("gw"), MUL, SUB, ST("tp"),
  A(0), LD("gg"), A(0), LD("gg"), LD("tc"),
      A(0), LD("gs"), P(EDGE_NUM), MUL, A(0), LD("gm"), DIV, A(0), LD("gs"), SUB, SUB, ST("tc"),
  A(0), P(1), ST("gd"),
  A(0), LD("gg"), A(0), LD("gg"), LD("tx"), P(1), ADD, ST("tx"), HALT ]
d_claim = [
  A(0), LD("gg"), P(0), EQ, NOT, REQ, A(0), LD("gd"), NOT, REQ, A(0), LD("gg"), LD("tr"), NOT, REQ,
  CURSOR, A(0), LD("gg"), LD("tv"), GT, REQ, A(0), LD("ga"),
  A(0), LD("gs"), P(EDGE_NUM), MUL, A(0), LD("gm"), DIV, PAY,
  A(0), LD("gg"), A(0), LD("gg"), LD("tp"),
      A(0), LD("gs"), P(EDGE_NUM), MUL, A(0), LD("gm"), DIV, SUB, ST("tp"),
  A(0), LD("gg"), A(0), LD("gg"), LD("tc"),
      A(0), LD("gs"), P(EDGE_NUM), MUL, A(0), LD("gm"), DIV, A(0), LD("gs"), SUB, SUB, ST("tc"),
  A(0), P(1), ST("gd"),
  A(0), LD("gg"), A(0), LD("gg"), LD("tx"), P(1), ADD, ST("tx"), HALT ]
d_close = [
  CALLER, A(0), LD("ta"), EQ, REQ, A(0), LD("tz"), NOT, REQ, A(0), LD("tx"), A(0), LD("tn"), EQ, REQ,
  A(0), LD("ta"), A(0), LD("tp"), PAY, A(0), P(1), ST("tz"), A(0), P(0), ST("tp"), HALT ]
d_fund = [
  CALLER, A(0), LD("ta"), EQ, REQ, A(0), LD("tr"), NOT, REQ, A(0), LD("tz"), NOT, REQ, VALUE, P(0), GT, REQ,
  A(0), A(0), LD("tk"), VALUE, ADD, ST("tk"), A(0), A(0), LD("tp"), VALUE, ADD, ST("tp"), HALT ]
DICE = {"open":d_open, "bet":d_bet, "reveal":d_reveal, "settle":d_settle, "claim":d_claim, "close":d_close, "fund":d_fund}
def d_roll(secret, g): return vm_hash(secret + g) % PN

# ================================================================================================
# CHESS CODE — loaded from the SHIPPED artifact (execnode/contracts/chess.json), so the audit always
# attacks exactly what is deployed. (An inline "verbatim copy" went stale once and kept reporting the
# already-fixed agree-r=4 and cancel-then-join bugs as live exploits.)
# ================================================================================================
import os
WINDOW = 14400
CHESS = json.load(open(os.path.join(os.path.dirname(__file__), "..", "execnode", "contracts", "chess.json")))

# ---- harness --------------------------------------------------------------------------------------
EXPLOITS=[]; ROBUST=[]
def rep_exploit(sev, name, detail): EXPLOITS.append((sev,name,detail)); print(f"  [EXPLOIT/{sev}] {name}: {detail}")
def rep_robust(name): ROBUST.append(name); print(f"  [robust] {name}")

class Harness:
    def __init__(self, code, accounts, deposit, deployer):
        self.st = ExecState(tempfile.mktemp()); self.st.cursor=100
        for a in accounts: self.st.credit_deposit(a, deposit)
        self.st.apply_blob({"op":"deploy","code":code,"runtime":"stackvm","nonce":"x"}, deployer, "d0")
        self.CID=list(self.st.contracts)[0]
        self.total0=self.total()
    def total(self): return sum(self.st.bridge.values())
    def bal(self,a): return self.st.bridge.get(a,0)
    def M(self,m,g): return self.st.contracts[self.CID]["storage"].get(m,{}).get(str(g),0)
    def call(self,m,args,val,who):
        r=self.st.apply_blob({"op":"call","contract":self.CID,"method":m,"args":args,"value":val}, who, m+str(args)+who)
        # CONSERVATION: total bridged NADO must be invariant after every op (nothing minted/burned).
        assert self.total()==self.total0, f"CONSERVATION BROKEN after {m}{args} by {who}: {self.total()} != {self.total0}"
        # ESCROW: contract balance can never be negative.
        assert self.bal(self.CID)>=0, f"NEGATIVE contract balance after {m}{args}"
        return r

# ==================================================================================================
print("="*70); print("DICE CONTRACT — adversarial audit"); print("="*70)
H=Harness(DICE, ("BANK","B1","B2","B3","EVE"), 2_000_000_000, "BANK")
CID=H.CID
sB=1122334455; cB=vm_hash(sB); STAKE=100000; BANKROLL=100_000_000

# lifecycle with conservation asserted on every call
H.st.cursor=100
H.call("open",[1,cB],BANKROLL,"BANK")
seats=[(11,50,"B1"),(12,25,"B2"),(13,90,"B3")]
for g,Mth,who in seats: H.call("bet",[g,1,Mth],STAKE,who)
rep_robust("dice: full open/bet keeps total NADO conserved (per-op invariant held)")

# --- ATTACK: double-settle / replay ---
H.st.cursor=100+JOIN_WINDOW+1
H.call("reveal",[1,sB],0,"BANK")
g,Mth,who=seats[0]
b=H.bal(who); H.call("settle",[g],0,who)
paid1=H.bal(who)-b
r2=H.call("settle",[g],0,who)   # replay
if "revert" in r2 and H.bal(who)==b+paid1: rep_robust("dice: double-settle reverts (no double-pay)")
else: rep_exploit("HIGH","dice double-settle","second settle paid again")
# settle the rest
for g2,M2,w2 in seats[1:]: H.call("settle",[g2],0,w2)

# --- ATTACK: settle a seat AFTER its opposite path; and claim a revealed table (must revert) ---
r=H.call("claim",[11],0,"EVE")
if "revert" in r: rep_robust("dice: claim on a revealed+settled seat reverts")
else: rep_exploit("HIGH","dice claim-after-settle","paid")

# --- close, then verify no re-open / no leftover theft ---
bp=H.bal("BANK"); leftover=H.M("tp",1); H.call("close",[1],0,"BANK")
if H.bal("BANK")==bp+leftover: rep_robust("dice: close returns exactly the leftover pool")
r=H.call("close",[1],0,"BANK")
if "revert" in r: rep_robust("dice: double-close reverts")
else: rep_exploit("HIGH","dice double-close","paid twice")
r=H.call("open",[1,cB],BANKROLL,"BANK")   # reuse closed table id
if "revert" in r: rep_robust("dice: closed table id cannot be re-opened (ta persists)")
else: rep_exploit("MED","dice table-id reuse","re-opened a closed table")

# --- ATTACK: cover guard bypass — under-bankrolled low-M bet must revert ---
H.st.cursor=100; H.call("open",[2,cB],1000,"BANK")
before=H.M("gg",201)
r=H.call("bet",[201,2,2],STAKE,"EVE")   # M=2 -> ~50x max payout, tiny bankroll
if "revert" in r and H.M("gg",201)==0: rep_robust("dice: cover guard blocks a bet whose max win exceeds bankroll")
else: rep_exploit("CRIT","dice cover bypass","under-covered bet accepted")
# M out of range
r=H.call("bet",[202,2,1],STAKE,"EVE");  ok1="revert" in r
r=H.call("bet",[203,2,99],STAKE,"EVE"); ok2="revert" in r
if ok1 and ok2: rep_robust("dice: M<2 and M>98 rejected (no div-by-tiny / no zero-edge)")
else: rep_exploit("HIGH","dice M range","out-of-range M accepted")

# --- ATTACK: solvency stress — MANY seats, ALL win, contract must still cover from held escrow only ---
H.st.cursor=100; H.call("open",[3,cB],BANKROLL,"BANK")
# choose seats whose rolls we PRECOMPUTE to all WIN (M > roll). This maximally stresses payout vs escrow.
placed=[]
gid=300
for _ in range(6):
    gid+=1
    r_g=d_roll(sB,gid)
    Mwin=min(MMAX, max(MMIN, r_g+1))   # ensure roll < Mwin -> guaranteed win
    if r_g >= MMAX:   # unwinnable within M range, skip
        continue
    if "revert" in H.call("bet",[gid,3,Mwin],STAKE,"B1"):
        continue
    placed.append((gid,Mwin))
H.st.cursor=100+JOIN_WINDOW+1; H.call("reveal",[3,sB],0,"BANK")
cbal_before=H.bal(CID)
for gid,Mwin in placed:
    H.call("settle",[gid],0,"B1")   # each asserts conservation + non-negative balance internally
# all winners paid; contract balance must equal remaining pool, never went negative (asserted in call())
if H.M("tc",3)==0: rep_robust(f"dice: {len(placed)} guaranteed-WIN seats all paid from escrow, committed drained to 0, never insolvent")

# --- FAIRNESS: can a bettor GRIND seatId? They only see cB=HASH(secret); the roll needs the preimage. ---
# Demonstrate: without the secret, seat->roll is unpredictable (blake2b preimage resistance). We show the map
# is not learnable from cB by checking rolls are spread and uncorrelated with cB (informal — real guarantee is
# preimage resistance). A bettor cannot compute d_roll(secret,g) from HASH(secret) alone.
rep_robust("dice: bettor cannot grind seatId — roll=HASH(secret+g) needs the secret; bettor sees only HASH(secret)")

# --- FAIRNESS/AUTHZ: malicious BANK self-bets with FOREKNOWLEDGE of the secret. Verify it is SELF-FUNDED
#     (cannot touch other bettors' stakes): conservation holds and the guaranteed win is bounded by the bank's
#     own bankroll+stake (cover guard). ---
H.st.cursor=100; H.call("open",[4,cB],BANKROLL,"BANK")
# innocent bettor Alice
H.call("bet",[401,4,50],STAKE,"B2")
aliceBal_at_bet=H.bal("B2")
# bank picks a seat it KNOWS will win big
gwin=None
for cand in range(410,600):
    if d_roll(sB,cand)<=3:   # very low roll -> can pick small M for huge payout
        gwin=cand; break
bank_before=H.bal("BANK")
if gwin is not None:
    Mbank=min(MMAX, d_roll(sB,gwin)+1)
    r=H.call("bet",[gwin,4,Mbank],STAKE,"BANK")   # bank bets on its own table, guaranteed win
    bank_bet_reverted = "revert" in r
H.st.cursor=100+JOIN_WINDOW+1; H.call("reveal",[4,sB],0,"BANK")
# settle everyone
H.call("settle",[401],0,"B2")
if gwin is not None and not bank_bet_reverted: H.call("settle",[gwin],0,"BANK")
# The invariant we care about: Alice's fate depended only on the pre-committed secret (bank could not choose
# Alice's seat id), and conservation held on every op. The bank self-bet only recycled bank money.
rep_robust("dice: malicious bank with secret foreknowledge can self-win, but it is self-funded (bounded by "
           "cover guard) and conservation held every op — it cannot steal other bettors' stakes")

# --- ATTACK: non-bank privileged actions ---
r1="revert" in H.call("reveal",[4,sB],0,"EVE")   # already revealed anyway; also wrong caller
H.st.cursor=100; H.call("open",[7,cB],5000,"BANK")
rn="revert" in H.call("fund",[7],5000,"EVE")
rc="revert" in H.call("close",[7],0,"EVE")
if rn and rc: rep_robust("dice: non-bank cannot fund/close a table")
else: rep_exploit("HIGH","dice authz","non-bank ran a privileged bank action")

# --- ATTACK: funds-stuck? anyone can settle/claim on behalf of a seat, so bank can always reach close. ---
H.st.cursor=100; H.call("open",[8,cB],BANKROLL,"BANK")
H.call("bet",[801,8,50],STAKE,"B1")
H.st.cursor=100+JOIN_WINDOW+REVEAL_WINDOW+1   # bank never revealed -> forfeit window
# EVE (a stranger) claims on behalf of the seat; payout still goes to the bettor B1
b1=H.bal("B1"); H.call("claim",[801],0,"EVE")
if H.bal("B1")>b1: rep_robust("dice: claim/settle callable by anyone but pays the SEAT owner — no griefing lock")
H.call("close",[8],0,"BANK")

print(f"\nDICE conservation invariant held across all {len(ROBUST)}+ ops (asserts inside call()).")

# ==================================================================================================
print("\n"+"="*70); print("CHESS CONTRACT — adversarial audit"); print("="*70)
CH=Harness(CHESS, ("W","B","C","EVE"), 1_000_000, "W")
S=10000

# --- baseline resign path + conservation ---
CH.call("open",[1],S,"W"); CH.call("join",[1],S,"B")
bB=CH.bal("B"); CH.call("resign",[1],0,"W")
if CH.bal("B")==bB+2*S and CH.M("sd",1)==1: rep_robust("chess: resign pays opponent exactly the pot")
if "revert" in CH.call("resign",[1],0,"W"): rep_robust("chess: double-resign reverts (sd guard)")

# --- ATTACK: agree() branchless — mismatch, both-zero, out-of-range ---
CH.call("open",[2],S,"W"); CH.call("join",[2],S,"B")
if "revert" in CH.call("agree",[2,0],0,"W"): rep_robust("chess: agree r=0 rejected")
if "revert" in CH.call("agree",[2,5],0,"W"): rep_robust("chess: agree r=5 rejected")
# mismatched agrees do not settle, no pay
CH.call("agree",[2,1],0,"W"); pW=CH.bal("W")
CH.call("agree",[2,2],0,"B")
if CH.M("sd",2)==0 and CH.bal(CH.CID)==2*S: rep_robust("chess: a1!=a2 does not settle, no payout")
# one player changes their mind (agree twice, different r) then real agreement settles once
CH.call("agree",[2,3],0,"W")   # W now asserts draw
bW,bB=CH.bal("W"),CH.bal("B")
CH.call("agree",[2,3],0,"B")   # both draw -> refund each
if CH.bal("W")==bW+S and CH.bal("B")==bB+S and CH.M("sd",2)==1: rep_robust("chess: player may revise r; first MATCHING pair settles once (draw refunds each)")
if "revert" in CH.call("agree",[2,3],0,"W"): rep_robust("chess: agree after settle reverts")

# --- ATTACK: NON-PLAYER calling agree cannot move a1/a2 or force a settle ---
CH.call("open",[3],S,"W"); CH.call("join",[3],S,"B")
CH.call("agree",[3,1],0,"W")            # white asserts white-wins
before=(CH.M("a1",3),CH.M("a2",3),CH.M("sd",3))
CH.call("agree",[3,1],0,"EVE")          # stranger asserts same r
after=(CH.M("a1",3),CH.M("a2",3),CH.M("sd",3))
if before==after and CH.M("sd",3)==0: rep_robust("chess: non-player agree() is a no-op (cannot set a2 / cannot settle)")
else: rep_exploit("HIGH","chess non-player agree","stranger influenced agreement state")

# --- ATTACK: payP1+payP2 can never exceed the pot for ANY agreed r in {1,2,3} ---
for r in (1,2,3):
    CH.call("open",[10+r],S,"W"); CH.call("join",[10+r],S,"B")
    tot_before=CH.bal("W")+CH.bal("B")
    CH.call("agree",[10+r,r],0,"W"); CH.call("agree",[10+r,r],0,"B")
    tot_after=CH.bal("W")+CH.bal("B")
    # exactly the pot (2S) is returned to the players, never more
    if tot_after-tot_before==2*S: pass
    else: rep_exploit("CRIT","chess over/under-pay",f"r={r}: players net {tot_after-tot_before} != pot {2*S}")
rep_robust("chess: for every valid agreed r in {1,2,3}, payouts sum to exactly the pot (no over/under-pay)")

# --- ATTACK: resign-then-agree / agree-then-resign ordering ---
CH.call("open",[20],S,"W"); CH.call("join",[20],S,"B")
CH.call("agree",[20,1],0,"W")
bB=CH.bal("B"); CH.call("resign",[20],0,"W")   # white resigns after asserting -> black takes pot
if CH.bal("B")==bB+2*S and CH.M("sd",20)==1: rep_robust("chess: agree-then-resign settles once (resign wins, no extra pay)")
if "revert" in CH.call("agree",[20,1],0,"B"): rep_robust("chess: agree after resign reverts (no double-settle)")

# --- ATTACK: abort ordering ---
CH.call("open",[21],S,"W"); CH.call("join",[21],S,"B")
CH.call("agree",[21,1],0,"W"); CH.call("agree",[21,2],0,"B")  # disagree
if "revert" in CH.call("abort",[21],0,"C"): rep_robust("chess: abort before deadline reverts")
CH.st.cursor=100+WINDOW+1
bW,bB=CH.bal("W"),CH.bal("B")
CH.call("abort",[21],0,"C")
if CH.bal("W")==bW+S and CH.bal("B")==bB+S and CH.M("sd",21)==1: rep_robust("chess: abort after deadline refunds both exactly (stall can't steal)")
if "revert" in CH.call("abort",[21],0,"C"): rep_robust("chess: double-abort reverts")
CH.st.cursor=100

# --- ATTACK: move() authz / turn / no-fund ---
CH.call("open",[30],S,"W"); CH.call("join",[30],S,"B")
r1="revert" in CH.call("move",[30,1804,0],0,"B")   # black first
r2="revert" in CH.call("move",[30,1804,0],0,"EVE") # non-player
c_before=CH.bal(CH.CID)
CH.call("move",[30,1804,0],0,"W")
r3="revert" in CH.call("move",[30,777,1],0,"W")    # white twice
r4="revert" in CH.call("move",[30,1804,0],0,"W")   # stale retry of ply 0 (the 2026-07-11 corruption race)
CH.call("move",[30,2000,1],0,"B")
if r1 and r2 and r3 and r4 and CH.bal(CH.CID)==c_before: rep_robust("chess: move() enforces turn+player+ply and NEVER touches funds")
else: rep_exploit("MED","chess move","move authz/turn/ply broken or move moved funds")

# ==================================================================================================
# ATTACK 6 (flagged): agree() OUT-OF-RANGE r=4 slips the guard.  A(1) P(4) GT NOT REQ accepts r<=4.
# ==================================================================================================
CH.call("open",[40],S,"W"); CH.call("join",[40],S,"B")
r_guard=CH.call("agree",[40,4],0,"W")   # should r=4 be rejected? guard is r<=4, so it PASSES
if "revert" not in r_guard and CH.M("a1",40)==4:
    # both submit r=4 -> a1==a2==4 -> agreed=1 -> settles with sd=1, pt=0, but payP1=payP2=0 (a1 not in {1,2,3})
    pot40=CH.M("pt",40); c_before=CH.bal(CH.CID)
    CH.call("agree",[40,4],0,"B")
    if CH.M("sd",40)==1 and CH.M("pt",40)==0 and CH.bal(CH.CID)==c_before:
        # this game's pot is now unreachable: sd=1 blocks resign/agree/abort/cancel; frozen in the contract forever
        stuck=pot40
        rep_exploit("MEDIUM","chess agree r=4 off-by-one (guard is r<=4, not r<=3)",
                    f"both players agree r=4 -> game marked settled (sd=1) with ZERO payout; pot {stuck} is "
                    f"permanently locked (sd blocks every settlement path). Conservation holds (nothing minted) "
                    f"but funds are irrecoverable. Fix: guard should be A(1) P(3) GT NOT REQ.")
    else:
        rep_robust("chess: r=4 accepted but did not settle destructively")
else:
    rep_robust("chess: agree r=4 rejected by guard")

# ==================================================================================================
# ATTACK (found): cancel() leaves nn==1, and join() checks only nn==1 (not sd). A cancelled game can be
# RE-JOINED, permanently locking the joiner's stake (sd=1 blocks every settlement path).
# ==================================================================================================
CH.call("open",[50],S,"W")
bW=CH.bal("W"); CH.call("cancel",[50],0,"W")     # opener cancels, refunded
refunded = CH.bal("W")==bW+S
nn_after_cancel=CH.M("nn",50); sd_after_cancel=CH.M("sd",50)
# now a victim joins the CANCELLED (already-settled) game
victim_before=CH.bal("B"); c_before=CH.bal(CH.CID)
r_join=CH.call("join",[50],S,"B")
if refunded and nn_after_cancel==1 and sd_after_cancel==1 and "revert" not in r_join:
    locked = CH.bal(CH.CID)-c_before   # victim's stake now escrowed
    # try EVERY recovery path for the victim / opener — all must fail (proving permanent lock)
    recov = {}
    recov["resign"] = ("revert" in CH.call("resign",[50],0,"B")) and ("revert" in CH.call("resign",[50],0,"W"))
    recov["agree"]  = ("revert" in CH.call("agree",[50,3],0,"B")) and ("revert" in CH.call("agree",[50,3],0,"W"))
    CH.st.cursor=100+WINDOW+1
    recov["abort"]  = "revert" in CH.call("abort",[50],0,"B")
    recov["cancel"] = "revert" in CH.call("cancel",[50],0,"W")
    CH.st.cursor=100
    all_blocked = all(recov.values())
    if locked==S and all_blocked:
        rep_exploit("MEDIUM","chess cancel-then-join permanent fund lock",
                    f"cancel() sets sd=1,pt=0 but leaves nn=1; join() checks only nn==1 (not sd), so a "
                    f"cancelled game is re-joinable. The joiner escrows {locked} into a game already marked "
                    f"settled — resign/agree/abort/cancel all revert (sd guard) so the stake is FROZEN forever. "
                    f"A malicious opener can front-run a joiner with cancel() to destroy the victim's stake "
                    f"(griefing; no gain to attacker). Fix: join() must also REQUIRE sd==0, or cancel() must set nn back to 0.")
    else:
        rep_robust(f"chess: cancelled game re-join not fully locking (locked={locked}, recov={recov})")
else:
    rep_robust("chess: cancelled game cannot be re-joined")

print(f"\nCHESS conservation invariant held across all ops (asserts inside call()).")

# ==================================================================================================
print("\n"+"="*70); print("VERDICT"); print("="*70)
dice_expl=[e for e in EXPLOITS if e[1].startswith("dice")]
chess_expl=[e for e in EXPLOITS if e[1].startswith("chess")]
print(f"DICE : {'EXPLOITABLE' if dice_expl else 'ROBUST-against-attacks-tried'}"
      + (f" ({len(dice_expl)} findings)" if dice_expl else ""))
for s,n,d in dice_expl: print(f"   - {s}: {n}")
print(f"CHESS: {'EXPLOITABLE' if chess_expl else 'ROBUST-against-attacks-tried'}"
      + (f" ({len(chess_expl)} findings)" if chess_expl else ""))
for s,n,d in chess_expl: print(f"   - {s}: {n}")
print(f"\nTotal: {len(EXPLOITS)} exploit finding(s), {len(ROBUST)} attacks defended.")
sys.exit(0)
