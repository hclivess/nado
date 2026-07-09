# tests/test_chess_contract.py — build + exercise the CHESS WAGER contract (stackvm).
#
# Chess is skill, not chance, and a stack VM can't referee legal moves — so this contract is a SAFE wager
# ESCROW only (the board + legality live in the browser). Design goal: nobody can ever be ROBBED.
#   * Both players stake equally (open + join -> pot = 2*stake).
#   * Normal finish is by AGREEMENT or RESIGNATION:
#       - resign(g): you concede; the opponent takes the pot (always safe, unilateral).
#       - agree(g, r): each player submits the result (1=white wins, 2=black wins, 3=draw). When BOTH submit
#         the SAME r it settles: winner takes the pot, or a draw refunds each stake.
#   * A stall can never steal: abort(g) after the deadline REFUNDS both (so refusing to resign/agree only
#     voids the wager, it never wins). cancel(g) reclaims an un-joined game.
# Because the only outcomes are concede / mutual-agree / refund, an illegal or disputed move can at worst
# force a refund — never a theft. (A future version could add a validity-proof to enforce a contested loss.)
import sys, json, tempfile, hashlib
sys.path.insert(0, "/root/nado")
from execnode.state import ExecState

def P(v): return ["PUSH", v]
def A(i): return ["ARG", i]
def LD(m): return ["MLOAD", m]
def ST(m): return ["MSTORE", m]
def OP(o): return [o]
CALLER=OP("CALLER"); VALUE=OP("VALUE"); CURSOR=OP("CURSOR")
ADD=OP("ADD"); SUB=OP("SUB"); MUL=OP("MUL"); MOD=OP("MOD"); EQ=OP("EQ"); GT=OP("GT"); NOT=OP("NOT"); OR=OP("OR"); AND=OP("AND")
REQ=OP("REQUIRE"); PAY=OP("PAY"); HALT=OP("HALT")
WINDOW = 14400        # ~1 day at 6s: after this, an unresolved game can be aborted (refunded)

# maps: p1/p2=white/black  st=stake pt=pot  nn=count(0/1/2)  sd=settled  dl=deadline  a1/a2=asserted result(1/2/3)
open_m = [
  VALUE, P(0), GT, REQ,
  A(0), LD("nn"), P(0), EQ, REQ,
  A(0), VALUE, ST("st"),
  A(0), VALUE, ST("pt"),
  A(0), CALLER, ST("p1"),
  A(0), P(1), ST("nn"),
  HALT ]
join_m = [
  A(0), LD("nn"), P(1), EQ, REQ,
  VALUE, A(0), LD("st"), EQ, REQ,              # equal stake
  CALLER, A(0), LD("p1"), EQ, NOT, REQ,        # not yourself
  A(0), A(0), LD("pt"), VALUE, ADD, ST("pt"),
  A(0), CALLER, ST("p2"),
  A(0), P(2), ST("nn"),
  A(0), CURSOR, P(WINDOW), ADD, ST("dl"),
  HALT ]
# resign(g): caller concedes -> the OTHER player takes the pot
resign_m = [
  A(0), LD("nn"), P(2), EQ, REQ,
  A(0), LD("sd"), NOT, REQ,
  CALLER, A(0), LD("p1"), EQ, CALLER, A(0), LD("p2"), EQ, OR, REQ,   # caller is a player
  # winner = (caller==p1) ? p2 : p1 ; PAY winner pot  (branchless via two guarded PAYs)
  A(0), LD("p2"), A(0), LD("pt"), CALLER, A(0), LD("p1"), EQ, MUL, PAY,   # if caller==p1 -> pay p2
  A(0), LD("p1"), A(0), LD("pt"), CALLER, A(0), LD("p2"), EQ, MUL, PAY,   # if caller==p2 -> pay p1
  A(0), P(1), ST("sd"),
  A(0), P(0), ST("pt"),
  HALT ]
# agree(g, r): record the caller's asserted result; when BOTH players asserted the SAME r, settle it.
# Branchless: a1[g] = a1*(caller!=p1) + r*(caller==p1) (ditto a2); agreed = (a1==a2)*(a1>0); payouts *= agreed.
agree_m = [
  A(0), LD("nn"), P(2), EQ, REQ,
  A(0), LD("sd"), NOT, REQ,
  # validate r in {1,2,3}: (r>=1) and (r<=3)
  A(1), P(0), GT, REQ,
  A(1), P(4), GT, NOT, REQ,
  # a1[g] = caller==p1 ? r : a1[g]   (branchless: a1 = a1*(caller!=p1) + r*(caller==p1))
  A(0),
      A(0), LD("a1"), CALLER, A(0), LD("p1"), EQ, NOT, MUL,
      A(1), CALLER, A(0), LD("p1"), EQ, MUL, ADD,
  ST("a1"),
  A(0),
      A(0), LD("a2"), CALLER, A(0), LD("p2"), EQ, NOT, MUL,
      A(1), CALLER, A(0), LD("p2"), EQ, MUL, ADD,
  ST("a2"),
  # agreed = (a1 == a2) and (a1 != 0)
  # a = a1 (agreed value)
  # payP1 = agreed * ( pt*(a==1) + st*(a==3) )
  # payP2 = agreed * ( pt*(a==2) + st*(a==3) )
  # to reuse "agreed", compute it inline each place.
  A(0), LD("p1"),
      A(0), LD("pt"), A(0), LD("a1"), P(1), EQ, MUL,
      A(0), LD("st"), A(0), LD("a1"), P(3), EQ, MUL, ADD,
      A(0), LD("a1"), A(0), LD("a2"), EQ, A(0), LD("a1"), P(0), GT, MUL, MUL,   # * agreed
  PAY,
  A(0), LD("p2"),
      A(0), LD("pt"), A(0), LD("a1"), P(2), EQ, MUL,
      A(0), LD("st"), A(0), LD("a1"), P(3), EQ, MUL, ADD,
      A(0), LD("a1"), A(0), LD("a2"), EQ, A(0), LD("a1"), P(0), GT, MUL, MUL,
  PAY,
  # sd = agreed ; pt = pt*(1-agreed)
  A(0), A(0), LD("a1"), A(0), LD("a2"), EQ, A(0), LD("a1"), P(0), GT, MUL, ST("sd"),
  A(0), A(0), LD("pt"), P(1), A(0), LD("a1"), A(0), LD("a2"), EQ, A(0), LD("a1"), P(0), GT, MUL, SUB, MUL, ST("pt"),
  HALT ]
# abort(g): after the deadline, refund both (a stall can never steal — only void)
abort_m = [
  A(0), LD("nn"), P(2), EQ, REQ,
  A(0), LD("sd"), NOT, REQ,
  CURSOR, A(0), LD("dl"), GT, REQ,
  A(0), LD("p1"), A(0), LD("st"), PAY,
  A(0), LD("p2"), A(0), LD("st"), PAY,
  A(0), P(1), ST("sd"),
  A(0), P(0), ST("pt"),
  HALT ]
# cancel(g): opener reclaims an un-joined game
cancel_m = [
  A(0), LD("nn"), P(1), EQ, REQ,
  CALLER, A(0), LD("p1"), EQ, REQ,
  A(0), LD("sd"), NOT, REQ,
  A(0), LD("p1"), A(0), LD("pt"), PAY,
  A(0), P(1), ST("sd"),
  A(0), P(0), ST("pt"),
  HALT ]

# move(g, enc): record a move on-chain (a trustless, ordered game log + a move clock). enc packs the move
# (from + to*64 + promo*4096). Enforces TURN ORDER (white on even ply, black on odd) and resets the clock;
# it does NOT referee legality (the browser engine does that) — but since the only settlements are resign /
# mutual-agree / refund-on-timeout, an illegal or disputed move can at worst force a refund, never a theft.
move_m = [
  A(0), LD("nn"), P(2), EQ, REQ,
  A(0), LD("sd"), NOT, REQ,
  A(1), P(0), GT, REQ,                          # enc > 0
  # turn: white(p1) on even ply, black(p2) on odd ply
  CALLER, A(0), LD("p1"), EQ, A(0), LD("mc"), P(2), MOD, P(0), EQ, AND,
  CALLER, A(0), LD("p2"), EQ, A(0), LD("mc"), P(2), MOD, P(1), EQ, AND,
  OR, REQ,
  A(0), P(10000), MUL, A(0), LD("mc"), ADD, A(1), ST("mv"),   # mv[g*10000+ply] = enc
  A(0), A(0), LD("mc"), P(1), ADD, ST("mc"),                  # ply++
  A(0), CURSOR, P(WINDOW), ADD, ST("dl"),                     # reset the move clock
  HALT ]
CODE = {"open":open_m, "join":join_m, "move":move_m, "resign":resign_m, "agree":agree_m, "abort":abort_m, "cancel":cancel_m}

F=[]
def ck(n,c): print(("  ok  " if c else " FAIL ")+n); (F.append(n) if not c else None)
st=ExecState(tempfile.mktemp()); st.cursor=100
for a in ("W","B","C"): st.credit_deposit(a, 1000000)
st.apply_blob({"op":"deploy","code":CODE,"runtime":"stackvm","nonce":"chess"},"W","d0")
CID=list(st.contracts)[0]
def bal(a): return st.bridge.get(a,0)
def M(m,g): return st.contracts[CID]["storage"].get(m,{}).get(str(g),0)
def call(m,args,val,who): return st.apply_blob({"op":"call","contract":CID,"method":m,"args":args,"value":val},who,m+str(args))

STAKE=10000
# --- resign path: white resigns -> black takes the pot ---
call("open",[1,],STAKE,"W") if False else call("open",[1],STAKE,"W")
ck("open escrows stake", bal("W")==1000000-STAKE and bal(CID)==STAKE)
call("join",[1],STAKE,"B")
ck("join -> pot 2*stake", bal(CID)==2*STAKE and M("pt",1)==2*STAKE)
bB=bal("B"); call("resign",[1],0,"W")
ck("white resigns -> black takes pot", bal("B")==bB+2*STAKE and bal(CID)==0 and M("sd",1)==1)

# --- agreement path: both agree white wins ---
call("open",[2],STAKE,"W"); call("join",[2],STAKE,"B")
call("agree",[2,1],0,"W")            # white asserts white wins
ck("one-sided agree does not settle", M("sd",2)==0 and bal(CID)==2*STAKE)
bW=bal("W"); call("agree",[2,1],0,"B")   # black agrees white wins
ck("both agree white -> white takes pot", bal("W")==bW+2*STAKE and M("sd",2)==1)

# --- agreement path: draw refunds both ---
call("open",[3],STAKE,"W"); call("join",[3],STAKE,"B")
bW,bB=bal("W"),bal("B")
call("agree",[3,3],0,"W"); call("agree",[3,3],0,"B")
ck("both agree draw -> refund each", bal("W")==bW+STAKE and bal("B")==bB+STAKE and M("sd",3)==1)

# --- disagreement never settles; abort after deadline refunds both ---
call("open",[4],STAKE,"W"); call("join",[4],STAKE,"B")
call("agree",[4,1],0,"W"); call("agree",[4,2],0,"B")   # they disagree
ck("disagreement does not settle", M("sd",4)==0 and bal(CID)==2*STAKE)
ck("abort before deadline blocked", "revert" in call("abort",[4],0,"C"))
st.cursor = 100 + WINDOW + 1
bW,bB=bal("W"),bal("B")
call("abort",[4],0,"C")
ck("abort after deadline refunds both (no theft)", bal("W")==bW+STAKE and bal("B")==bB+STAKE and M("sd",4)==1)

# --- black wins by agreement ---
st.cursor=100; call("open",[5],STAKE,"W"); call("join",[5],STAKE,"B")
bB=bal("B"); call("agree",[5,2],0,"B"); call("agree",[5,2],0,"W")
ck("both agree black -> black takes pot", bal("B")==bB+2*STAKE and M("sd",5)==1)

# --- cancel an un-joined game ---
call("open",[6],STAKE,"W"); bW=bal("W")
ck("non-opener cannot cancel", "revert" in call("cancel",[6],0,"B"))
call("cancel",[6],0,"W")
ck("opener cancels -> refunded", bal("W")==bW+STAKE and M("sd",6)==1)

# --- guards ---
call("open",[7],STAKE,"W"); call("join",[7],STAKE,"B")
ck("non-player cannot resign", "revert" in call("resign",[7],0,"C"))
ck("bad result rejected", "revert" in call("agree",[7,5],0,"W") and M("a1",7)==0)

# move: on-chain move log with strict turn order
call("open",[8],STAKE,"W"); call("join",[8],STAKE,"B")
ck("black cannot move first", "revert" in call("move",[8,1804],0,"B") and M("mc",8)==0)
ck("non-player cannot move", "revert" in call("move",[8,1804],0,"C"))
call("move",[8,1804],0,"W")                       # white e2e4 (enc)
ck("white move recorded at ply 0", M("mc",8)==1 and M("mv",80000)==1804)
ck("white cannot move again", "revert" in call("move",[8,777],0,"W") and M("mc",8)==1)
call("move",[8,2000],0,"B")                       # black replies at ply 1
ck("black move recorded at ply 1", M("mc",8)==2 and M("mv",80001)==2000)
# after moves, resign still resolves (loser concedes)
bW=bal("W"); call("resign",[8],0,"B")             # black resigns -> white takes pot
ck("resign after moves pays the winner", bal("W")==bW+2*STAKE and M("sd",8)==1)

print("\n"+("ALL PASS" if not F else f"{len(F)} FAILED: {F}"))
if not F:
    import os
    outp = os.path.join(os.path.dirname(__file__),"..","execnode","contracts","chess.json")
    if os.environ.get("WRITE"): json.dump(CODE, open(outp,"w")); print("WROTE", outp)
    else:
        committed=json.load(open(outp)) if os.path.exists(outp) else None
        assert committed==CODE, "execnode/contracts/chess.json is STALE — re-run with WRITE=1"
        print("committed chess.json matches")
sys.exit(1 if F else 0)
