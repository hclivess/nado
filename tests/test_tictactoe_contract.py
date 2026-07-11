# tests/test_tictactoe_contract.py — build + exercise the TIC-TAC-TOE WAGER contract (stackvm).
#
# Unlike chess (where the browser referees), a 3x3 board is small enough for the VM to referee ENTIRELY
# ON-CHAIN: move() checks the cell is free and YOUR turn, places the mark, detects 3-in-a-row and pays
# the pot to the winner instantly; a full board with no line refunds both stakes (draw). No agree() step,
# no disputes possible — the contract IS the referee.
#   * X = opener (even plies), O = joiner (odd plies); stakes are equal, pot = 2*stake.
#   * PLY BINDING (chess lesson 2026-07-11): move(g, cell, ply) REQUIREs ply == mc so a stale wallet
#     retry can never land turns later.
#   * Liveness: resign() concedes; abort() after the move deadline refunds both (a stall only voids);
#     cancel() reclaims an un-joined game. WINDOW is short — tic-tac-toe moves take seconds.
import sys, json, tempfile
sys.path.insert(0, "/root/nado")
from execnode.state import ExecState

def P(v): return ["PUSH", v]
def A(i): return ["ARG", i]
def LD(m): return ["MLOAD", m]
def ST(m): return ["MSTORE", m]
def OP(o): return [o]
CALLER=OP("CALLER"); VALUE=OP("VALUE"); CURSOR=OP("CURSOR")
ADD=OP("ADD"); SUB=OP("SUB"); MUL=OP("MUL"); MOD=OP("MOD"); EQ=OP("EQ"); GT=OP("GT"); GTE=OP("GTE"); LTE=OP("LTE")
NOT=OP("NOT"); OR=OP("OR"); AND=OP("AND")
REQ=OP("REQUIRE"); PAY=OP("PAY"); HALT=OP("HALT")
S = "S"
WINDOW = 300          # ~30 min move clock — this is tic-tac-toe, not correspondence chess
LINES = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]

# maps: p1=X p2=O st=stake pt=pot nn=count sd=settled dl=deadline mc=ply bd[g*16+cell]=0/1/2 wr=result(1=X 2=O 3=draw)
open_m = [
  VALUE, P(0), GT, REQ,
  A(0), P(0), GT, REQ,
  A(0), LD("nn"), P(0), EQ, REQ,
  A(0), VALUE, ST("st"),
  A(0), VALUE, ST("pt"),
  A(0), CALLER, ST("p1"),
  A(0), P(1), ST("nn"),
  HALT ]
join_m = [
  A(0), LD("nn"), P(1), EQ, REQ,
  A(0), LD("sd"), NOT, REQ,
  VALUE, A(0), LD("st"), EQ, REQ,
  CALLER, A(0), LD("p1"), EQ, NOT, REQ,
  A(0), A(0), LD("pt"), VALUE, ADD, ST("pt"),
  A(0), CALLER, ST("p2"),
  A(0), P(2), ST("nn"),
  A(0), CURSOR, P(WINDOW), ADD, ST("dl"),
  HALT ]

def _cell(c_ops):
    """bd[g*16 + cell]"""
    return [A(0), P(16), MUL, *c_ops, ADD, LD("bd")]

def _line(a, b, c):
    """(bd[a]==k) & (bd[b]==k) & (bd[c]==k) with k in scratch."""
    return [*_cell([P(a)]), P("k"), LD(S), EQ,
            *_cell([P(b)]), P("k"), LD(S), EQ, AND,
            *_cell([P(c)]), P("k"), LD(S), EQ, AND]

# move(g, cell, ply): place your mark; the CONTRACT referees — win pays the pot NOW, a full board draws.
move_m = [
  A(0), LD("nn"), P(2), EQ, REQ,
  A(0), LD("sd"), NOT, REQ,
  A(1), P(0), GTE, REQ, A(1), P(8), LTE, REQ,     # cell 0..8 (GTE/LTE type-gate ints)
  A(2), A(0), LD("mc"), EQ, REQ,                  # PLY BINDING: stale retries can never land later
  # turn: X(p1) on even ply, O(p2) on odd ply
  CALLER, A(0), LD("p1"), EQ, A(0), LD("mc"), P(2), MOD, P(0), EQ, AND,
  CALLER, A(0), LD("p2"), EQ, A(0), LD("mc"), P(2), MOD, P(1), EQ, AND,
  OR, REQ,
  *_cell([A(1)]), P(0), EQ, REQ,                  # the cell is free
  # place my mark k = 1 + ply%2
  P("k"), P(1), A(0), LD("mc"), P(2), MOD, ADD, ST(S),
  A(0), P(16), MUL, A(1), ADD, P("k"), LD(S), ST("bd"),
  A(0), A(0), LD("mc"), P(1), ADD, ST("mc"),
  A(0), CURSOR, P(WINDOW), ADD, ST("dl"),
  # w = any of the 8 lines is all-mine
  P("w"), *_line(*LINES[0]),
  *[op for ln in LINES[1:] for op in [*_line(*ln), OR]],
  ST(S),
  # d = board full (mc==9) and no win
  P("d"), A(0), LD("mc"), P(9), EQ, P(1), P("w"), LD(S), SUB, MUL, ST(S),
  # payouts: winner (the caller) takes the pot; a draw refunds each stake
  CALLER, A(0), LD("pt"), P("w"), LD(S), MUL, PAY,
  A(0), LD("p1"), A(0), LD("st"), P("d"), LD(S), MUL, PAY,
  A(0), LD("p2"), A(0), LD("st"), P("d"), LD(S), MUL, PAY,
  # result for the UI: 1/2 winner mark on a win, 3 on a draw
  A(0), P("k"), LD(S), P("w"), LD(S), MUL, P(3), P("d"), LD(S), MUL, ADD, ST("wr"),
  A(0), P("w"), LD(S), P("d"), LD(S), ADD, ST("sd"),
  A(0), A(0), LD("pt"), P(1), P("w"), LD(S), P("d"), LD(S), ADD, SUB, MUL, ST("pt"),
  HALT ]

resign_m = [
  A(0), LD("nn"), P(2), EQ, REQ,
  A(0), LD("sd"), NOT, REQ,
  CALLER, A(0), LD("p1"), EQ, CALLER, A(0), LD("p2"), EQ, OR, REQ,
  A(0), LD("p2"), A(0), LD("pt"), CALLER, A(0), LD("p1"), EQ, MUL, PAY,
  A(0), LD("p1"), A(0), LD("pt"), CALLER, A(0), LD("p2"), EQ, MUL, PAY,
  A(0), P(2), CALLER, A(0), LD("p1"), EQ, MUL, P(1), CALLER, A(0), LD("p2"), EQ, MUL, ADD, ST("wr"),
  A(0), P(1), ST("sd"),
  A(0), P(0), ST("pt"),
  HALT ]
abort_m = [
  A(0), LD("nn"), P(2), EQ, REQ,
  A(0), LD("sd"), NOT, REQ,
  CURSOR, A(0), LD("dl"), GT, REQ,
  A(0), LD("p1"), A(0), LD("st"), PAY,
  A(0), LD("p2"), A(0), LD("st"), PAY,
  A(0), P(3), ST("wr"),
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
CODE = {"open":open_m, "join":join_m, "move":move_m, "resign":resign_m, "abort":abort_m, "cancel":cancel_m}

# ---------------- PYTHON REFERENCE ----------------
def ref_win(bd, k):
    return any(all(bd[i] == k for i in ln) for ln in LINES)

# ---------------- TESTS ----------------
F=[]
def ck(n,c): print(("  ok  " if c else " FAIL ")+n); (F.append(n) if not c else None)
st=ExecState(tempfile.mktemp()); st.cursor=100
for a in ("X","O","EVE"): st.credit_deposit(a, 10**12)
st.apply_blob({"op":"deploy","code":CODE,"runtime":"stackvm","nonce":"ttt"},"X","d0")
CID=list(st.contracts)[0]
def bal(a): return st.bridge.get(a,0)
def M(m,k): return st.contracts[CID]["storage"].get(m,{}).get(str(k),0)
def call(m,args,val,who): return st.apply_blob({"op":"call","contract":CID,"method":m,"args":args,"value":val},who,m+str(args)+str(st.cursor))
def rv(r): return "revert" in r or "skip" in r

STAKE=10**9
# X wins the top row
call("open",[1],STAKE,"X"); call("join",[1],STAKE,"O")
ck("pot escrows both stakes", M("pt",1)==2*STAKE and bal(CID)==2*STAKE)
ck("O cannot move first", rv(call("move",[1,4,0],0,"O")))
ck("cell out of range reverts", rv(call("move",[1,9,0],0,"X")))
call("move",[1,0,0],0,"X"); call("move",[1,4,1],0,"O")
ck("occupied cell reverts", rv(call("move",[1,0,2],0,"X")))
ck("stale retry of an old ply reverts (chess lesson)", rv(call("move",[1,0,0],0,"X")))
call("move",[1,1,2],0,"X"); call("move",[1,5,3],0,"O")
bX=bal("X")
call("move",[1,2,4],0,"X")                        # X completes 0-1-2
ck("X's 3-in-a-row pays the pot INSTANTLY (contract-refereed)",
   bal("X")==bX+2*STAKE and M("sd",1)==1 and M("wr",1)==1 and M("pt",1)==0 and bal(CID)==0)
ck("moving after the win reverts", rv(call("move",[1,6,5],0,"O")))

# O wins a column
call("open",[2],STAKE,"X"); call("join",[2],STAKE,"O")
for cell, ply, who in ((0,0,"X"),(1,1,"O"),(3,2,"X"),(4,3,"O"),(8,4,"X")):
    call("move",[2,cell,ply],0,who)
bO=bal("O")
call("move",[2,7,5],0,"O")                        # O completes 1-4-7
ck("O's column pays O the pot", bal("O")==bO+2*STAKE and M("wr",2)==2)

# a full-board draw refunds each stake (X: 0,1,5,6,7  O: 2,3,4,8 — no line)
call("open",[3],STAKE,"X"); call("join",[3],STAKE,"O")
seq = [(0,"X"),(2,"O"),(1,"X"),(3,"O"),(5,"X"),(4,"O"),(6,"X"),(8,"O")]
for ply,(cell,who) in enumerate(seq): call("move",[3,cell,ply],0,who)
bX,bO=bal("X"),bal("O")
call("move",[3,7,8],0,"X")                        # board full, no 3-in-a-row
ck("full board with no line = DRAW, both stakes refunded",
   bal("X")==bX+STAKE and bal("O")==bO+STAKE and M("wr",3)==3 and M("sd",3)==1 and bal(CID)==0)

# differential: random legal games vs the python referee
import random as _r
rng=_r.Random(0xC3)
mism=0; wins=[0,0,0]
for k in range(200):
    g=100+k
    call("open",[g],STAKE,"X"); call("join",[g],STAKE,"O")
    bd=[0]*9; ply=0; done=False
    bX,bO=bal("X"),bal("O")
    while not done and ply<9:
        who = "X" if ply%2==0 else "O"; mark = 1+ply%2
        cell = rng.choice([i for i in range(9) if bd[i]==0])
        r = call("move",[g,cell,ply],0,who)
        if rv(r): mism+=1; break
        bd[cell]=mark; ply+=1
        if ref_win(bd,mark):
            done=True
            wantX = bal(bX and 0 or 0)  # (placeholder, real check below)
            if M("wr",g)!=mark or M("sd",g)!=1: mism+=1
            wins[mark-1]+=1
        elif ply==9:
            done=True
            if M("wr",g)!=3 or M("sd",g)!=1: mism+=1
            wins[2]+=1
    # balance conservation per game: X+O deltas == 0 net of pot flows
    dX,dO = bal("X")-bX, bal("O")-bO
    if M("wr",g)==1 and dX!=2*STAKE: mism+=1
    if M("wr",g)==2 and dO!=2*STAKE: mism+=1
    if M("wr",g)==3 and (dX!=STAKE or dO!=STAKE): mism+=1
ck(f"DIFFERENTIAL: 200 random games bytecode==python referee (mism={mism}, X {wins[0]} / O {wins[1]} / draw {wins[2]})",
   mism==0 and wins[0]>60 and wins[1]>30 and wins[2]>5)

# resign + abort + cancel
call("open",[900],STAKE,"X"); call("join",[900],STAKE,"O")
bO=bal("O"); call("resign",[900],0,"X")
ck("resign concedes the pot", bal("O")==bO+2*STAKE and M("wr",900)==2)
call("open",[901],STAKE,"X"); call("join",[901],STAKE,"O")
ck("abort before the deadline reverts", rv(call("abort",[901],0,"EVE")))
st.cursor += WINDOW + 1
bX,bO=bal("X"),bal("O")
call("abort",[901],0,"EVE")
ck("abort after the deadline refunds both (a stall only voids)", bal("X")==bX+STAKE and bal("O")==bO+STAKE)
call("open",[902],STAKE,"X"); bX=bal("X")
call("cancel",[902],0,"X")
ck("cancel reclaims an un-joined stake", bal("X")==bX+STAKE)
ck("contract drains to zero", bal(CID)==0)

print("\n"+("ALL PASS" if not F else f"{len(F)} FAILED: {F}"))
if not F:
    import os
    outp = os.path.join(os.path.dirname(__file__),"..","execnode","contracts","tictactoe.json")
    print(f"deploy blob = {len(json.dumps(CODE))} bytes; move = {len(move_m)} instr")
    if os.environ.get("WRITE"): json.dump(CODE, open(outp,"w")); print("WROTE", outp)
    else:
        committed=json.load(open(outp)) if os.path.exists(outp) else None
        assert committed==CODE, "execnode/contracts/tictactoe.json is STALE — re-run with WRITE=1"
        print("committed tictactoe.json matches")
sys.exit(1 if F else 0)
