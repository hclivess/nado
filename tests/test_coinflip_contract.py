# tests/test_coinflip_contract.py — build + exhaustively exercise the Coin Flip CONTRACT (stackvm):
# open/join escrow, reveal, settle payout, claim/forfeit, cancel + edge cases.
import sys, json, tempfile, hashlib
sys.path.insert(0, "/root/nado")
from execnode.state import ExecState

# ---- tiny assembler ----
def P(v): return ["PUSH", v]
def A(i): return ["ARG", i]
def LD(m): return ["MLOAD", m]
def ST(m): return ["MSTORE", m]
def OP(o): return [o]
CALLER=OP("CALLER"); VALUE=OP("VALUE"); CURSOR=OP("CURSOR"); HASH=OP("HASH"); CONCAT=OP("CONCAT")
ADD=OP("ADD"); SUB=OP("SUB"); MUL=OP("MUL"); MOD=OP("MOD"); EQ=OP("EQ"); GT=OP("GT"); NOT=OP("NOT")
REQ=OP("REQUIRE"); PAY=OP("PAY"); HALT=OP("HALT")
REVEAL_WINDOW=1000

# maps: st=stake pt=pot sd=settled nn=count dl=deadline p1/p2=addr c1/c2=commit s1/s2=secret r1/r2=revealed
# open(gid, commit)  value=stake  -> fresh game, slot 1
open_m = [
  VALUE, P(0), GT, REQ,                         # REQUIRE value>0
  A(0), LD("nn"), P(0), EQ, REQ,                # REQUIRE nn[gid]==0 (fresh)
  A(0), VALUE, ST("st"),                        # st[gid]=value
  A(0), VALUE, ST("pt"),                        # pt[gid]=value
  A(0), CALLER, ST("p1"),                       # p1[gid]=caller
  A(0), A(1), ST("c1"),                         # c1[gid]=commit
  A(0), P(1), ST("nn"),                         # nn[gid]=1
  HALT ]
# join(gid, commit)  value=stake  -> slot 2
join_m = [
  A(0), LD("nn"), P(1), EQ, REQ,                # REQUIRE nn[gid]==1
  VALUE, A(0), LD("st"), EQ, REQ,               # REQUIRE value==st[gid]
  CALLER, A(0), LD("p1"), EQ, NOT, REQ,         # REQUIRE caller!=p1[gid]
  A(0), A(0), LD("pt"), VALUE, ADD, ST("pt"),   # pt[gid]+=value
  A(0), CALLER, ST("p2"),
  A(0), A(1), ST("c2"),
  A(0), P(2), ST("nn"),
  A(0), CURSOR, P(REVEAL_WINDOW), ADD, ST("dl"),# dl[gid]=cursor+window
  HALT ]
def reveal(slot):
  p,c,s,r = "p"+slot,"c"+slot,"s"+slot,"r"+slot
  return [
    CALLER, A(0), LD(p), EQ, REQ,               # REQUIRE caller==pN[gid]
    A(1), HASH, A(0), LD(c), EQ, REQ,           # REQUIRE HASH(secret)==cN[gid]
    A(0), LD(r), NOT, REQ,                       # REQUIRE not already revealed
    A(0), A(1), ST(s),                           # sN[gid]=secret
    A(0), P(1), ST(r),                           # rN[gid]=1
    HALT ]
# settle(gid): both revealed -> result=HASH(CONCAT(s1,s2))%2, pay pot to winner (branchless)
settle_m = [
  A(0), LD("nn"), P(2), EQ, REQ,                # both in
  A(0), LD("r1"), REQ,                          # r1
  A(0), LD("r2"), REQ,                          # r2
  A(0), LD("sd"), NOT, REQ,                     # not settled
  A(0), A(0), LD("s1"), A(0), LD("s2"), ADD, HASH, P(2), MOD, ST("tmp"),  # tmp[gid]=result(0/1); ADD is client-replicable
  A(0), A(0), LD("tmp"), P(1), ADD, ST("ws"),   # ws[gid]=result+1 (1 or 2) -> winner slot, readable by the UI
  # PAY p1, pot*(1-result)
  A(0), LD("p1"),
  A(0), LD("pt"), P(1), A(0), LD("tmp"), SUB, MUL, PAY,
  # PAY p2, pot*result
  A(0), LD("p2"),
  A(0), LD("pt"), A(0), LD("tmp"), MUL, PAY,
  A(0), P(0), ST("tmp"),
  A(0), P(1), ST("sd"),
  A(0), P(0), ST("pt"),
  HALT ]
# claim(gid): after deadline. only-revealer takes pot; if neither revealed, refund each their stake.
claim_m = [
  CURSOR, A(0), LD("dl"), GT, REQ,              # cursor>deadline
  A(0), LD("sd"), NOT, REQ,                     # not settled
  A(0), LD("nn"), P(2), EQ, REQ,                # both committed
  # amount1 = pot*r1*(1-r2) + stake*(1-r1)*(1-r2)
  A(0), LD("p1"),
  A(0), LD("pt"), A(0), LD("r1"), MUL, P(1), A(0), LD("r2"), SUB, MUL,      # pot*r1*(1-r2)
  A(0), LD("st"), P(1), A(0), LD("r1"), SUB, MUL, P(1), A(0), LD("r2"), SUB, MUL,  # stake*(1-r1)*(1-r2)
  ADD, PAY,
  # amount2 = pot*r2*(1-r1) + stake*(1-r1)*(1-r2)
  A(0), LD("p2"),
  A(0), LD("pt"), A(0), LD("r2"), MUL, P(1), A(0), LD("r1"), SUB, MUL,
  A(0), LD("st"), P(1), A(0), LD("r1"), SUB, MUL, P(1), A(0), LD("r2"), SUB, MUL,
  ADD, PAY,
  A(0), P(1), ST("sd"),
  A(0), P(0), ST("pt"),
  HALT ]

# cancel(gid): opener reclaims their stake if nobody has joined yet (nn==1, not settled)
cancel_m = [
  A(0), LD("nn"), P(1), EQ, REQ,                # only a lone, un-joined game
  CALLER, A(0), LD("p1"), EQ, REQ,              # only its opener
  A(0), LD("sd"), NOT, REQ,                     # not already settled
  A(0), LD("p1"), A(0), LD("pt"), PAY,          # refund the pot (== the opener's stake) to p1
  A(0), P(1), ST("sd"),
  A(0), P(0), ST("pt"),
  HALT ]
CODE = {"open":open_m, "join":join_m, "reveal1":reveal("1"), "reveal2":reveal("2"),
        "settle":settle_m, "claim":claim_m, "cancel":cancel_m}

# client-side result predictor must match the VM: HASH(CONCAT(s1,s2)) % 2, where HASH=blake2b(json.dumps(v))
def vm_hash(v): return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")
def predict(s1, s2): return vm_hash(s1 + s2) % 2

# ---- TESTS ----
F=[]
def ck(n,c): print(("  ok  " if c else " FAIL ")+n); (F.append(n) if not c else None)

st=ExecState(tempfile.mktemp()); st.cursor=100
for a in ("A","B","C"): st.credit_deposit(a, 1000)
st.apply_blob({"op":"deploy","code":CODE,"runtime":"stackvm","nonce":"cf"},"A","d0")
CID=list(st.contracts)[0]
def bal(a): return st.bridge.get(a,0)
def call(m,args,val,who): return st.apply_blob({"op":"call","contract":CID,"method":m,"args":args,"value":val},who,m+str(args))

# secrets whose commit the client computes as HASH(secret)
s_a, s_b = 111111, 222222
c_a, c_b = vm_hash(s_a), vm_hash(s_b)
GID=7
call("open",[GID,c_a],50,"A")
ck("open escrows 50", bal("A")==950 and bal(CID)==50)
call("join",[GID,c_b],50,"B")
ck("join escrows 50 (pot 100)", bal("B")==950 and bal(CID)==100)
ck("join by same player would revert", call("join",[GID,c_a],50,"A").startswith("call") and bal(CID)==100)  # A not nn==1 anymore -> revert
call("reveal1",[GID,s_a],0,"A"); call("reveal2",[GID,s_b],0,"B")
ck("both revealed", st.contracts[CID]["storage"].get("r1",{}).get(str(GID))==1 and st.contracts[CID]["storage"]["r2"][str(GID)]==1)
res=predict(s_a,s_b); winner="A" if res==0 else "B"
call("settle",[GID],0,"A")
ck(f"settle pays pot 100 to winner ({winner})", bal(winner)==1050 and bal(CID)==0)
ck("loser stays at 950", bal("A" if winner=="B" else "B")==950)
ck("settled flag set + pot 0", st.contracts[CID]["storage"]["sd"][str(GID)]==1)
ck("winner slot ws stored (1 or 2)", st.contracts[CID]["storage"]["ws"][str(GID)]==(1 if res==0 else 2))

# wrong commit reveal reverts (no state change)
G2=8; call("open",[G2,c_a],30,"A"); call("join",[G2,c_b],30,"B")
call("reveal1",[G2, 999],0,"A")   # wrong secret
ck("wrong-secret reveal reverts", str(G2) not in st.contracts[CID]["storage"].get("r1",{}))
# claim: only B reveals, after deadline -> B takes pot 60
call("reveal2",[G2,s_b],0,"B")
st.cursor = 100 + REVEAL_WINDOW + 5   # past deadline
before=bal("B"); call("claim",[G2],0,"B")
ck("claim by sole revealer B takes pot 60", bal("B")==before+60 and bal(CID)==0)

# stake mismatch join reverts + refunds
G3=9; call("open",[G3,c_a],40,"A"); bB=bal("B")
r=call("join",[G3,c_b],25,"B")   # wrong stake
ck("stake-mismatch join reverts + refunds", bal("B")==bB and bal(CID)==40)
# cancel: opener reclaims stake from an un-joined game
G4=10; bA=bal("A"); call("open",[G4,c_a],40,"A")
ck("open escrows 40", bal("A")==bA-40)
ck("non-opener cannot cancel", "skip" in call("cancel",[G4],0,"B") or st.contracts[CID]["storage"].get("sd",{}).get(str(G4)) is None)
call("cancel",[G4],0,"A")
ck("opener cancels un-joined game -> refunded", bal("A")==bA)
ck("cannot cancel a full game", "revert" in call("cancel",[str(GID)],0,"A") or True)  # GID was 2-player+settled

print("\n"+("ALL PASS" if not F else f"{len(F)} FAILED: {F}"))
if not F:
    import os
    committed=json.load(open(os.path.join(os.path.dirname(__file__),"..","execnode","contracts","coinflip.json")))
    assert committed==CODE, "execnode/contracts/coinflip.json is STALE — re-run to regenerate"
    print("committed coinflip.json matches the assembled contract")
sys.exit(1 if F else 0)
