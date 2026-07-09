# tests/test_poker_contract.py — build + exercise the POKER WAGER contract (stackvm).
#
# Heads-up 5-card poker SHOWDOWN for stakes. Fairness = commit-reveal: both players commit HASH(secret) before
# either reveals, then reveal; both browsers derive the SAME shuffled deck from HASH(s1+s2) and deal 5 cards
# each (nobody can pick their hand). The hand is evaluated in the browser (poker-engine.js); the contract is a
# theft-proof escrow that settles by:
#   * resign(g): concede -> opponent takes the pot (the loser pays the winner; unilateral, always safe).
#   * agree(g, r): both submit the SAME result (1=p1 wins, 2=p2 wins, 3=split) -> settle (split refunds each).
#   * abort(g): after the deadline, refund both (a stall never steals — only voids).
# Because outcomes are only concede / mutual-agree / refund, a wrong or disputed showdown can at worst refund —
# never mis-pay. (The result is deterministic + public from the two revealed secrets, so honest play settles.)
import sys, json, tempfile, hashlib
sys.path.insert(0, "/root/nado")
from execnode.state import ExecState

def P(v): return ["PUSH", v]
def A(i): return ["ARG", i]
def LD(m): return ["MLOAD", m]
def ST(m): return ["MSTORE", m]
def OP(o): return [o]
CALLER=OP("CALLER"); VALUE=OP("VALUE"); CURSOR=OP("CURSOR"); HASH=OP("HASH")
ADD=OP("ADD"); SUB=OP("SUB"); MUL=OP("MUL"); EQ=OP("EQ"); GT=OP("GT"); NOT=OP("NOT"); OR=OP("OR")
REQ=OP("REQUIRE"); PAY=OP("PAY"); HALT=OP("HALT")
WINDOW = 1000    # blocks until an unresolved (un-revealed / un-agreed) game can be aborted -> refunded

# maps: p1/p2 c1/c2 s1/s2 r1/r2  st pt nn sd dl  a1/a2(asserted result 1/2/3)
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
  A(0), LD("sd"), NOT, REQ,                    # not settled (cancelled game keeps nn==1; block re-join)
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
    return [ A(0), LD("nn"), P(2), EQ, REQ,          # both joined before any reveal (no early-reveal grind)
             CALLER, A(0), LD(p), EQ, REQ,
             A(1), HASH, A(0), LD(c), EQ, REQ,
             A(0), LD(r), NOT, REQ,
             A(0), A(1), ST(s),
             A(0), P(1), ST(r),
             HALT ]
# resign(g): concede -> the OTHER player takes the pot
resign_m = [
  A(0), LD("nn"), P(2), EQ, REQ,
  A(0), LD("sd"), NOT, REQ,
  CALLER, A(0), LD("p1"), EQ, CALLER, A(0), LD("p2"), EQ, OR, REQ,
  A(0), LD("p2"), A(0), LD("pt"), CALLER, A(0), LD("p1"), EQ, MUL, PAY,
  A(0), LD("p1"), A(0), LD("pt"), CALLER, A(0), LD("p2"), EQ, MUL, PAY,
  A(0), P(1), ST("sd"),
  A(0), P(0), ST("pt"),
  HALT ]
# agree(g, r): 1=p1 wins,2=p2 wins,3=split ; both agree same r -> settle
agree_m = [
  A(0), LD("nn"), P(2), EQ, REQ,
  A(0), LD("sd"), NOT, REQ,
  A(1), P(0), GT, REQ, A(1), P(3), GT, NOT, REQ,          # r in {1,2,3}
  A(0),
      A(0), LD("a1"), CALLER, A(0), LD("p1"), EQ, NOT, MUL,
      A(1), CALLER, A(0), LD("p1"), EQ, MUL, ADD, ST("a1"),
  A(0),
      A(0), LD("a2"), CALLER, A(0), LD("p2"), EQ, NOT, MUL,
      A(1), CALLER, A(0), LD("p2"), EQ, MUL, ADD, ST("a2"),
  # payP1 = agreed*( pt*(a==1) + st*(a==3) ) ; payP2 = agreed*( pt*(a==2) + st*(a==3) )
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

CODE = {"open":open_m, "join":join_m, "reveal1":reveal("1"), "reveal2":reveal("2"),
        "resign":resign_m, "agree":agree_m, "abort":abort_m, "cancel":cancel_m}

def vm_hash(v): return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")
F=[]
def ck(n,c): print(("  ok  " if c else " FAIL ")+n); (F.append(n) if not c else None)
st=ExecState(tempfile.mktemp()); st.cursor=100
for a in ("A","B","C"): st.credit_deposit(a, 1000000)
st.apply_blob({"op":"deploy","code":CODE,"runtime":"stackvm","nonce":"poker"},"A","d0")
CID=list(st.contracts)[0]
def bal(a): return st.bridge.get(a,0)
def M(m,g): return st.contracts[CID]["storage"].get(m,{}).get(str(g),0)
def call(m,args,val,who): return st.apply_blob({"op":"call","contract":CID,"method":m,"args":args,"value":val},who,m+str(args))
STAKE=10000
sa,sb=111,222; ca,cb=vm_hash(sa),vm_hash(sb)

# full showdown: both commit + reveal, A concedes -> B wins pot
call("open",[1,ca],STAKE,"A"); call("join",[1,cb],STAKE,"B")
ck("join -> pot 2*stake", M("pt",1)==2*STAKE and bal(CID)==2*STAKE)
call("reveal1",[1,sa],0,"A"); call("reveal2",[1,sb],0,"B")
ck("both revealed (secrets on-chain for the shared deck)", M("s1",1)==sa and M("s2",1)==sb)
ck("wrong-secret reveal reverts", "revert" in call("reveal1",[1,999],0,"A"))   # already revealed anyway
bB=bal("B"); call("resign",[1],0,"A")
ck("A concedes -> B takes pot", bal("B")==bB+2*STAKE and M("sd",1)==1)

# agreement path: both agree A(p1) wins
call("open",[2,ca],STAKE,"A"); call("join",[2,cb],STAKE,"B")
call("reveal1",[2,sa],0,"A"); call("reveal2",[2,sb],0,"B")
call("agree",[2,1],0,"A"); ck("one-sided agree does not settle", M("sd",2)==0)
bA=bal("A"); call("agree",[2,1],0,"B")
ck("both agree p1 -> p1 takes pot", bal("A")==bA+2*STAKE and M("sd",2)==1)

# split: both agree draw -> refund each
call("open",[3,ca],STAKE,"A"); call("join",[3,cb],STAKE,"B")
bA,bB=bal("A"),bal("B"); call("agree",[3,3],0,"A"); call("agree",[3,3],0,"B")
ck("both agree split -> refund each", bal("A")==bA+STAKE and bal("B")==bB+STAKE and M("sd",3)==1)

# disagreement -> abort refunds after deadline
call("open",[4,ca],STAKE,"A"); call("join",[4,cb],STAKE,"B")
call("agree",[4,1],0,"A"); call("agree",[4,2],0,"B")
ck("disagreement does not settle", M("sd",4)==0)
ck("abort before deadline blocked", "revert" in call("abort",[4],0,"C"))
st.cursor=100+WINDOW+1
bA,bB=bal("A"),bal("B"); call("abort",[4],0,"C")
ck("abort after deadline refunds both", bal("A")==bA+STAKE and bal("B")==bB+STAKE and M("sd",4)==1)

# cancel un-joined
st.cursor=100; call("open",[5,ca],STAKE,"A"); bA=bal("A")
ck("non-opener cannot cancel", "revert" in call("cancel",[5],0,"B"))
call("cancel",[5],0,"A"); ck("opener cancels -> refunded", bal("A")==bA+STAKE and M("sd",5)==1)
# guards
call("open",[6,ca],STAKE,"A"); call("join",[6,cb],STAKE,"B")
ck("non-player cannot resign", "revert" in call("resign",[6],0,"C"))
ck("bad result rejected", "revert" in call("agree",[6,9],0,"A") and M("a1",6)==0)

# --- SECURITY regressions (audit fixes) ---
st.cursor=100
call("open",[50,ca],STAKE,"A"); call("cancel",[50],0,"A")
ck("SEC: cannot join a cancelled game", "revert" in call("join",[50,cb],STAKE,"B") and M("nn",50)==1)
call("open",[51,ca],STAKE,"A")
ck("SEC: reveal before join rejected", "revert" in call("reveal1",[51,sa],0,"A") and M("r1",51)==0)
call("join",[51,cb],STAKE,"B")
ck("SEC: agree(r=4) rejected (no frozen pot)", "revert" in call("agree",[51,4],0,"A") and M("a1",51)==0)

print("\n"+("ALL PASS" if not F else f"{len(F)} FAILED: {F}"))
if not F:
    import os
    outp = os.path.join(os.path.dirname(__file__),"..","execnode","contracts","poker.json")
    if os.environ.get("WRITE"): json.dump(CODE, open(outp,"w")); print("WROTE", outp)
    else:
        committed=json.load(open(outp)) if os.path.exists(outp) else None
        assert committed==CODE, "execnode/contracts/poker.json is STALE — re-run with WRITE=1"
        print("committed poker.json matches")
sys.exit(1 if F else 0)
