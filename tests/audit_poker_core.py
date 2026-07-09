# tests/audit_poker_core.py — ADVERSARIAL audit of the NADO POKER wager contract AND the shared
# VALUE/PAY escrow core in execnode/state.py apply_blob("call"). We (a) rebuild the exact poker bytecode
# and attack it, and (b) deploy tiny malicious contracts to attack the escrow core directly.
#
# Invariants under test:
#   CONSERVATION  : total = sum(bridge) + sum(withdrawals) is constant except for explicit deposits.
#   NO-MINT       : a contract can never pay out more than it holds; a revert never double-refunds nor strands.
#   POKER SAFETY  : branchless agree() math conserves; no double-settle; auth enforced; fairness by commit-reveal.
#
# Run: python3 tests/audit_poker_core.py
import sys, json, tempfile, hashlib
sys.path.insert(0, "/root/nado")
from execnode.state import ExecState

# ---- opcode helpers (mirror the committed poker test) ---------------------------------------------
def P(v): return ["PUSH", v]
def A(i): return ["ARG", i]
def LD(m): return ["MLOAD", m]
def ST(m): return ["MSTORE", m]
def OP(o): return [o]
CALLER=OP("CALLER"); VALUE=OP("VALUE"); CURSOR=OP("CURSOR"); HASH=OP("HASH")
ADD=OP("ADD"); SUB=OP("SUB"); MUL=OP("MUL"); EQ=OP("EQ"); GT=OP("GT"); NOT=OP("NOT"); OR=OP("OR")
REQ=OP("REQUIRE"); PAY=OP("PAY"); HALT=OP("HALT")
WINDOW = 1000

# ---- exact poker bytecode (copied verbatim from tests/test_poker_contract.py) ---------------------
open_m = [
  VALUE, P(0), GT, REQ,
  A(0), LD("nn"), P(0), EQ, REQ,
  A(0), VALUE, ST("st"),
  A(0), VALUE, ST("pt"),
  A(0), CALLER, ST("p1"),
  A(0), A(1), ST("c1"),
  A(0), P(1), ST("nn"),
  HALT ]
join_m = [
  A(0), LD("nn"), P(1), EQ, REQ,
  VALUE, A(0), LD("st"), EQ, REQ,
  CALLER, A(0), LD("p1"), EQ, NOT, REQ,
  A(0), A(0), LD("pt"), VALUE, ADD, ST("pt"),
  A(0), CALLER, ST("p2"),
  A(0), A(1), ST("c2"),
  A(0), P(2), ST("nn"),
  A(0), CURSOR, P(WINDOW), ADD, ST("dl"),
  HALT ]
def reveal(slot):
    p,c,s,r = "p"+slot,"c"+slot,"s"+slot,"r"+slot
    return [ CALLER, A(0), LD(p), EQ, REQ,
             A(1), HASH, A(0), LD(c), EQ, REQ,
             A(0), LD(r), NOT, REQ,
             A(0), A(1), ST(s),
             A(0), P(1), ST(r),
             HALT ]
resign_m = [
  A(0), LD("nn"), P(2), EQ, REQ,
  A(0), LD("sd"), NOT, REQ,
  CALLER, A(0), LD("p1"), EQ, CALLER, A(0), LD("p2"), EQ, OR, REQ,
  A(0), LD("p2"), A(0), LD("pt"), CALLER, A(0), LD("p1"), EQ, MUL, PAY,
  A(0), LD("p1"), A(0), LD("pt"), CALLER, A(0), LD("p2"), EQ, MUL, PAY,
  A(0), P(1), ST("sd"),
  A(0), P(0), ST("pt"),
  HALT ]
agree_m = [
  A(0), LD("nn"), P(2), EQ, REQ,
  A(0), LD("sd"), NOT, REQ,
  A(1), P(0), GT, REQ, A(1), P(4), GT, NOT, REQ,
  A(0),
      A(0), LD("a1"), CALLER, A(0), LD("p1"), EQ, NOT, MUL,
      A(1), CALLER, A(0), LD("p1"), EQ, MUL, ADD, ST("a1"),
  A(0),
      A(0), LD("a2"), CALLER, A(0), LD("p2"), EQ, NOT, MUL,
      A(1), CALLER, A(0), LD("p2"), EQ, MUL, ADD, ST("a2"),
  A(0), LD("p1"),
      A(0), LD("pt"), A(0), LD("a1"), P(1), EQ, MUL,
      A(0), LD("st"), A(0), LD("a1"), P(3), EQ, MUL, ADD,
      A(0), LD("a1"), A(0), LD("a2"), EQ, A(0), LD("a1"), P(0), GT, MUL, MUL,
  PAY,
  A(0), LD("p2"),
      A(0), LD("pt"), A(0), LD("a1"), P(2), EQ, MUL,
      A(0), LD("st"), A(0), LD("a1"), P(3), EQ, MUL, ADD,
      A(0), LD("a1"), A(0), LD("a2"), EQ, A(0), LD("a1"), P(0), GT, MUL, MUL,
  PAY,
  A(0), A(0), LD("a1"), A(0), LD("a2"), EQ, A(0), LD("a1"), P(0), GT, MUL, ST("sd"),
  A(0), A(0), LD("pt"), P(1), A(0), LD("a1"), A(0), LD("a2"), EQ, A(0), LD("a1"), P(0), GT, MUL, SUB, MUL, ST("pt"),
  HALT ]
abort_m = [
  A(0), LD("nn"), P(2), EQ, REQ,
  A(0), LD("sd"), NOT, REQ,
  CURSOR, A(0), LD("dl"), GT, REQ,
  A(0), LD("p1"), A(0), LD("st"), PAY,
  A(0), LD("p2"), A(0), LD("st"), PAY,
  A(0), P(1), ST("sd"),
  A(0), P(0), ST("pt"),
  HALT ]
cancel_m = [
  A(0), LD("nn"), P(1), EQ, REQ,
  CALLER, A(0), LD("p1"), EQ, REQ,
  A(0), LD("sd"), NOT, REQ,
  A(0), LD("p1"), A(0), LD("pt"), PAY,
  A(0), P(1), ST("sd"),
  A(0), P(0), ST("pt"),
  HALT ]
POKER = {"open":open_m, "join":join_m, "reveal1":reveal("1"), "reveal2":reveal("2"),
         "resign":resign_m, "agree":agree_m, "abort":abort_m, "cancel":cancel_m}

def vm_hash(v): return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")

# ---- harness --------------------------------------------------------------------------------------
FAIL=[]; EXPLOIT=[]; PASSED=[]
def rec(ok, name):
    (PASSED if ok else FAIL).append(name)
    print(("  ok   " if ok else " FAIL ")+name)
    return ok
def note_exploit(sev, name, detail):
    EXPLOIT.append((sev, name, detail)); print(f"  !!!  [{sev}] {name}: {detail}")

def sysvalue(st):
    """Total conserved value = bridged balances + burned-but-provable withdrawals."""
    return sum(st.bridge.values()) + sum(w["amount"] for w in st.withdrawals.values())

class Conserver:
    """Wrap apply_blob to assert conservation across EVERY op (baseline only changes on credit_deposit)."""
    def __init__(self, st): self.st=st; self.base=sysvalue(st); self.broken=False
    def rebase(self): self.base=sysvalue(self.st)
    def call(self, payload, sender, txid):
        r=self.st.apply_blob(payload, sender, txid)
        v=sysvalue(self.st)
        if v!=self.base:
            self.broken=True
            note_exploit("CRITICAL","conservation broken",
                         f"op={payload.get('op')} {payload.get('method','')} total {self.base}->{v} (Δ{v-self.base})")
        return r

st=ExecState(tempfile.mktemp()); st.cursor=100
for a in ("A","B","C","D"): st.credit_deposit(a, 1_000_000)
CON=Conserver(st); CON.rebase()
st.apply_blob({"op":"deploy","code":POKER,"runtime":"stackvm","nonce":"poker"},"A","d0")
CID=list(st.contracts)[0]
CON.rebase()
def bal(a): return st.bridge.get(a,0)
def M(m,g): return st.contracts[CID]["storage"].get(m,{}).get(str(g),0)
def call(m,args,val,who): return CON.call({"op":"call","contract":CID,"method":m,"args":args,"value":val},who,m+str(args)+who)
STAKE=10000
sa,sb=111,222; ca,cb=vm_hash(sa),vm_hash(sb)

print("\n=== POKER: happy-path sanity (must settle exactly) ===")
call("open",[1,ca],STAKE,"A"); call("join",[1,cb],STAKE,"B")
rec(M("pt",1)==2*STAKE and bal(CID)==2*STAKE, "join escrows 2*stake into contract")
bB=bal("B"); call("resign",[1],0,"A")
rec(bal("B")==bB+2*STAKE and M("sd",1)==1 and bal(CID)==0, "resign pays whole pot to opponent, contract emptied")

print("\n=== POKER attack: agree() branchless conservation ===")
# both agree p1 wins
call("open",[2,ca],STAKE,"A"); call("join",[2,cb],STAKE,"B")
bA=bal("A"); call("agree",[2,1],0,"A"); rec(M("sd",2)==0, "one-sided agree does NOT settle")
call("agree",[2,1],0,"B"); rec(bal("A")==bA+2*STAKE and M("sd",2)==1, "both agree p1 -> exact pot to p1")
# split
call("open",[3,ca],STAKE,"A"); call("join",[3,cb],STAKE,"B")
bA,bB=bal("A"),bal("B"); call("agree",[3,3],0,"A"); call("agree",[3,3],0,"B")
rec(bal("A")==bA+STAKE and bal("B")==bB+STAKE and M("sd",3)==1, "both agree split -> exact refund each (no double-pay)")
# mismatched agree never settles / pays
call("open",[7,ca],STAKE,"A"); call("join",[7,cb],STAKE,"B")
call("agree",[7,1],0,"A"); call("agree",[7,2],0,"B")
rec(M("sd",7)==0 and bal(CID)>= 2*STAKE, "disagree (1 vs 2) -> no settle, no pay")
# agree-twice-different then match on 2nd value
call("agree",[7,1],0,"A"); call("agree",[7,1],0,"B")   # A now re-agrees 1, B re-agrees 1
rec(M("sd",7)==1, "re-agree to a common r settles (a1 overwrites)")
# out-of-range r
call("open",[8,ca],STAKE,"A"); call("join",[8,cb],STAKE,"B")
rec("revert" in call("agree",[8,0],0,"A") and M("a1",8)==0, "agree r=0 rejected")
rec("revert" in call("agree",[8,9],0,"A") and M("a1",8)==0, "agree r=9 rejected")
# r=4 IN-RANGE per guard (r<=4) but pays nothing -> pot stranded
preCID=bal(CID)
call("agree",[8,4],0,"A"); r4=call("agree",[8,4],0,"B")
if M("sd",8)==1 and M("pt",8)==0 and bal(CID)==preCID:
    note_exploit("LOW","agree r=4 strands the pot",
        "guard is r>0 AND r<=4 (allows 4, comment says {1,2,3}); both agreeing r=4 sets sd=1,pt=0 with ZERO payout -> 2*stake locked in contract forever. Requires mutual agreement (both burn).")
    rec(True, "confirmed: agree r=4 settles with no payout (funds stranded, conservation intact)")
else:
    rec(False, "agree r=4 expected to strand pot")

print("\n=== POKER attack: authorization ===")
call("open",[9,ca],STAKE,"A"); call("join",[9,cb],STAKE,"B")
rec("revert" in call("resign",[9],0,"C"), "non-player cannot resign")
rec("revert" in call("reveal1",[9,sa],0,"B"), "wrong-slot reveal (p2 calling reveal1) reverts")
rec("revert" in call("reveal1",[9,999],0,"A"), "wrong-secret reveal reverts")
call("reveal1",[9,sa],0,"A")
rec(M("s1",9)==sa and "revert" in call("reveal1",[9,sa],0,"A"), "re-reveal (r1 already set) reverts")
# non-player agree is inert (cannot inject a1/a2)
call("agree",[9,1],0,"C")
rec(M("a1",9)==0 and M("a2",9)==0, "non-player agree cannot set a1/a2")
# join your own game / unequal stake
call("open",[10,ca],STAKE,"A")
rec("revert" in call("join",[10,cb],STAKE,"A"), "cannot join your own game (caller==p1)")
rec("revert" in call("join",[10,cb],STAKE+1,"B"), "unequal stake join reverts")
rec("revert" in call("join",[10,cb],STAKE-1,"B"), "under stake join reverts")
call("cancel",[10],0,"A")  # clean up game 10 (opener refunds)

print("\n=== POKER attack: double-settle / replay ===")
call("open",[11,ca],STAKE,"A"); call("join",[11,cb],STAKE,"B")
call("resign",[11],0,"A")   # settled -> B has pot
rec("revert" in call("agree",[11,1],0,"A"), "agree after resign reverts (sd set)")
rec("revert" in call("resign",[11],0,"B"), "resign after resign reverts")
st.cursor=100+WINDOW+1
rec("revert" in call("abort",[11],0,"C"), "abort after settle reverts")
st.cursor=100
rec("revert" in call("open",[11,ca],STAKE,"A"), "reopen a used game id reverts (nn!=0)")

print("\n=== POKER attack: cancel then JOIN (nn stays 1, sd not checked by join) ===")
call("open",[12,ca],STAKE,"A"); bA=bal("A")
call("cancel",[12],0,"A")
rec(bal("A")==bA+STAKE and M("sd",12)==1, "opener cancels -> refunded, sd=1")
# now a DIFFERENT player tries to join the cancelled game
pre_B=bal("B"); pre_CID=bal(CID)
res=call("join",[12,cb],STAKE,"B")
if M("nn",12)==2 and M("pt",12)==STAKE and M("sd",12)==1:
    # B's stake is now escrowed but EVERY settlement path requires sd==0 -> unreachable
    settle_paths_blocked = all("revert" in call(m,[12] if m!="agree" else [12,1],0,"B")
                               for m in ("resign","agree"))
    st.cursor=100+WINDOW+1
    ab="revert" in call("abort",[12],0,"B"); st.cursor=100
    stuck = bal(CID)==pre_CID+STAKE and settle_paths_blocked and ab
    if stuck:
        note_exploit("MEDIUM","join-after-cancel strands the joiner's stake",
            "cancel() leaves nn=1 AND sd=1; join() checks nn==1 but NOT sd. A third party who joins an "
            "already-cancelled game escrows STAKE into the contract, but resign/agree/abort all REQUIRE sd==0, "
            "so the stake is permanently locked (no theft; joiner loss / griefing via cancel-race).")
    rec(stuck, "confirmed: joiner's stake locked, no settlement path exists")
else:
    rec(False, f"expected join-after-cancel to escrow B's stake (got {res})")

print("\n=== ESCROW CORE: direct attacks with malicious contracts ===")
# A permissionless 'bank': deposit (value stays), pay(to,amt) draws from contract holdings with NO auth,
# payN pays the same/other recipient repeatedly, self(cid) pays the contract itself.
BANK = {
  "deposit": [HALT],                                   # accept value, keep it
  "pay":     [A(0), A(1), PAY, HALT],                  # PAY to=arg0 amount=arg1 (permissionless)
  "pay2":    [A(0), A(1), PAY, A(0), A(1), PAY, HALT], # pay arg0 amount arg1 TWICE (same recipient)
  "overval": [A(0), VALUE, P(2), MUL, PAY, HALT],      # pay arg0 = 2*value (more than escrowed)
  "mint":    [A(0), P(1000000), PAY, HALT],            # pay 1e6 to arg0 from a (possibly) empty contract
}
st.apply_blob({"op":"deploy","code":BANK,"runtime":"stackvm","nonce":"bank"},"D","db")
BID=[c for c in st.contracts if c!=CID][0]
def bcall(m,args,val,who): return CON.call({"op":"call","contract":BID,"method":m,"args":args,"value":val},who,m+str(args)+who+str(val))

# 1) NO-MINT from an empty contract
pre=bal("D"); r=bcall("mint",["D"],0,"D")
rec("revert" in r and bal(BID)==0 and bal("D")==pre, "empty contract cannot mint a payout (revert, no-op)")

# 2) overpay > escrowed value with no other holdings -> revert + exact refund
pre_A=bal("A"); r=bcall("overval",["A"],5000,"A")
rec("revert" in r and bal(BID)==0 and bal("A")==pre_A, "PAY 2*value with no reserve -> revert + full refund (no strand)")

# 3) fund the bank, then confirm PAY can never exceed HOLDINGS
bcall("deposit",[],50000,"D")           # D parks 50000 in the bank
rec(bal(BID)==50000, "bank holds 50000")
pre_A=bal("A")
r=bcall("pay",["A",50001],0,"A")        # try to draw 1 over holdings
rec("revert" in r and bal(BID)==50000 and bal("A")==pre_A, "draw > holdings reverts (contract balance can't go negative)")
r=bcall("pay",["A",50000],0,"A")        # draw exactly holdings (permissionless -> A drains D's deposit)
rec(bal(BID)==0 and bal("A")==pre_A+50000, "draw == holdings succeeds (permissionless contract IS drainable by design)")

# 4) pay SAME recipient twice: guard sums payouts vs holdings
bcall("deposit",[],30000,"D")
pre_A=bal("A")
r=bcall("pay2",["A",20000],0,"A")       # 2*20000=40000 > 30000 -> revert
rec("revert" in r and bal(BID)==30000 and bal("A")==pre_A, "pay2 (2x20000>30000) reverts as a whole (no partial pay)")
r=bcall("pay2",["A",15000],0,"A")       # 2*15000=30000 == holdings -> ok, A gets 30000
rec(bal(BID)==0 and bal("A")==pre_A+30000, "pay2 (2x15000==30000) both payouts land")

# 5) PAY to == cid (contract pays ITSELF): must net zero, no self-mint enabling later over-withdraw
bcall("deposit",[],10000,"D")
pre=bal(BID)
r=bcall("pay",[BID,10000],0,"A")        # pay the contract its own 10000
rec(bal(BID)==10000 and "ok" in r, "PAY to==cid nets zero (no self-mint)")
# now the self-credit did NOT let anyone withdraw more than 10000
r=bcall("pay",["A",10001],0,"A")
rec("revert" in r and bal(BID)==10000, "self-credit does not inflate withdrawable holdings")
bcall("pay",["A",10000],0,"A")          # drain back out cleanly

# 6) revert must refund the incoming VALUE exactly (not strand it, not double-refund)
pre_A=bal("A"); pre_BID=bal(BID)
r=bcall("overval",["A"],7777,"A")       # value 7777 debited, pay 15554 attempted -> revert
rec("revert" in r and bal("A")==pre_A and bal(BID)==pre_BID, "revert refunds VALUE exactly once (no strand / no double)")

# 7) bridge_withdraw cannot touch a contract's escrow (no private key controls a cid)
bcall("deposit",[],12345,"D")
pre_total=sysvalue(st)
r=CON.call({"op":"bridge_withdraw","amount":12345}, BID, "wd")   # 'sender'==cid: does a hash-address exist as balance holder?
# The contract DOES hold 12345 under key==BID, and bridge_withdraw keys off `sender`. If someone could submit
# a blob whose L1 sender == the cid, they could burn the contract's escrow to a withdrawal. Report reachability.
if "bridge_withdraw" in r and str(st.withdrawals.get(str(st.wd_nonce),{}).get("addr"))==BID:
    note_exploit("INFO","bridge_withdraw keys off sender==cid",
        "If an L1 sender string can ever equal a 32-hex contract id, that party withdraws the contract's whole "
        "escrow. cids are blake2b[:32] hex with no known private key, so unreachable in practice; conservation "
        "holds (moved bridge->withdrawal). Flagged as a trust assumption, not a live exploit.")
    rec(sysvalue(st)==pre_total, "bridge_withdraw(sender==cid) conserves value (moved to withdrawal record)")
else:
    rec(bal(BID)==12345, "bridge_withdraw with sender==cid did not fire (no exploit)")
    bcall("pay",["D",12345],0,"D")

print("\n=== ESCROW CORE: insufficient-value skip is a clean no-op ===")
pre=dict(st.bridge)
r=CON.call({"op":"call","contract":BID,"method":"deposit","args":[],"value":10**9}, "A","toobig")
rec("insufficient" in r and st.bridge==pre, "call value > sender balance -> skip, zero state change")

print("\n=== FAIRNESS reasoning (commit-reveal) ===")
# Demonstrate: with c1,c2 committed at open/join, neither secret can be changed. The deck = HASH(s1+s2)
# is unknown to either player until BOTH secrets are on-chain, and cannot be ground (needs the OTHER's secret).
call("open",[20,ca],STAKE,"A"); call("join",[20,cb],STAKE,"B")
rec(M("c1",20)==ca and M("c2",20)==cb, "both commits locked before any reveal (no post-hoc deck bias)")
rec(("revert" in call("reveal1",[20,sa+1],0,"A")), "cannot reveal a secret != committed (HASH check binds it)")
print("  note  a losing last-revealer can REFUSE to reveal/agree and force abort->refund (never theft):")
print("        settlement is concede/mutual-agree/deadline-refund, so an unwilling loser escapes only to a REFUND.")

# ---- final conservation check + verdict -----------------------------------------------------------
print("\n=== FINAL ===")
rec(not CON.broken, "CONSERVATION held across every operation")
print(f"\nPASSED {len(PASSED)}  FAILED {len(FAIL)}  EXPLOIT-NOTES {len(EXPLOIT)}")
for sev,name,detail in EXPLOIT: print(f"  [{sev}] {name}\n       {detail}")
if FAIL: print("FAILED CHECKS:", FAIL)
crit = [e for e in EXPLOIT if e[0] in ("CRITICAL","HIGH")]
print("\nVERDICT escrow-core:", "EXPLOITABLE" if (crit or CON.broken) else "SOUND (conserves; no mint; revert exact)")
print("VERDICT poker      :", "EXPLOITABLE(fund-loss)" if any(e[0] in ("MEDIUM","HIGH","CRITICAL") for e in EXPLOIT)
                                else "ROBUST")
sys.exit(1 if FAIL else 0)
