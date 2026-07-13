# tests/test_battleship_contract.py — build + exercise the BATTLESHIP wager contract (stackvm).
#
# Trustless hidden-board battleship. Each player commits a MERKLE-SUM root over their 128-cell board (10x10
# grid = cells 0..99, cells 100..127 are always water so the tree is a full 2^7). A leaf is
#     leaf(cell, isShip, salt) = HASH(salt*256 + cell*2 + isShip)     (per-cell random 256-bit salt)
# and an internal node binds BOTH children AND its subtree ship-count into one hash (non-commutative slots so
# a cell's POSITION is fixed → it can't be duplicated):
#     node(L, R, sum) = HASH(L*2^264 + R*2^8 + sum)          sum = L.sum + R.sum
# Leaves sit at bit-reversed positions (pos = bitrev7(cell)) so the sibling subtree SUMS a proof reveals cover
# SCATTERED cells, not contiguous grid regions → the count-proof leaks nothing useful about ship locations.
#
# A shot is answered by revealing just that ONE cell (isShip, salt) + its 7 (siblingHash, siblingSum) path.
# The contract recomputes the leaf, walks the 7 levels to the committed root, and REQUIREs (a) it equals the
# committed root — so you can't lie about hit/miss — AND (b) the accumulated sum == 17 — so you can't hide
# ships to be unsinkable. 17 proven hits = all ships sunk = you win. No reveal-at-end, no oracle, no trust;
# only HASH/ADD (post-quantum, and byte-identical to the browser's blake2bHash).
#
# Flow: open(g,root)+stake · join(g,root)+stake · move(g, fireCell, isShip, salt, sib0,ss0..sib6,ss6) proves
# the OPPONENT's last shot at MY board then fires MY next shot · resign · timeout (a staller forfeits) · cancel.
import sys, json, tempfile, hashlib
sys.path.insert(0, "/root/nado")
from execnode.state import ExecState
from execnode.vm import _hash_value as VMHASH   # the exact HASH opcode: blake2b(json.dumps(v,sort_keys=True))

def P(v): return ["PUSH", v]
def A(i): return ["ARG", i]
def LD(m): return ["MLOAD", m]
def ST(m): return ["MSTORE", m]
def OP(o): return [o]
CALLER=OP("CALLER"); VALUE=OP("VALUE"); CURSOR=OP("CURSOR"); HASH=OP("HASH")
ADD=OP("ADD"); SUB=OP("SUB"); MUL=OP("MUL"); DIV=OP("DIV"); MOD=OP("MOD")
EQ=OP("EQ"); GT=OP("GT"); GTE=OP("GTE"); LT=OP("LT"); LTE=OP("LTE")
NOT=OP("NOT"); OR=OP("OR"); AND=OP("AND")
REQ=OP("REQUIRE"); PAY=OP("PAY"); HALT=OP("HALT"); DUP=OP("DUP"); POP=OP("POP")

LEVELS = 7
SHIPS  = 17
M1 = 2**8         # right-child hash slot   (bits 8..263)
M2 = 2**264       # left-child hash slot    (bits 264..519); sum sits in bits 0..7
WINDOW = 600      # ~1h move clock
S = "S"           # scratch map

# ---- python reference merkle (independent of the contract opcodes) -------------------------------
def _leaf(cell, isShip, salt): return VMHASH(salt * 256 + cell * 2 + isShip)
def _node(L, R, s):            return VMHASH(L * M2 + R * M1 + s)
def bitrev7(x):                return int(format(x, "07b")[::-1], 2)

def build_root(board, salts):
    """board[128] 0/1, salts[128] ints -> merkle-sum root. leaf(cell) lives at array index bitrev7(cell)."""
    lvl = [None] * 128
    for cell in range(128):
        lvl[bitrev7(cell)] = (_leaf(cell, board[cell], salts[cell]), board[cell])
    while len(lvl) > 1:
        lvl = [(_node(lvl[i][0], lvl[i+1][0], lvl[i][1] + lvl[i+1][1]), lvl[i][1] + lvl[i+1][1])
               for i in range(0, len(lvl), 2)]
    return lvl[0][0]

def make_proof(board, salts, cell):
    """-> (isShip, salt, [ (sibHash, sibSum) per level 0..6 ]). Sibling at each level as we climb from the leaf."""
    lvl = [None] * 128
    for c in range(128):
        lvl[bitrev7(c)] = (_leaf(c, board[c], salts[c]), board[c])
    pos = bitrev7(cell); sibs = []
    while len(lvl) > 1:
        i = pos ^ 1
        sibs.append((lvl[i][0], lvl[i][1]))
        lvl = [(_node(lvl[j][0], lvl[j+1][0], lvl[j][1] + lvl[j+1][1]), lvl[j][1] + lvl[j+1][1])
               for j in range(0, len(lvl), 2)]
        pos //= 2
    return board[cell], salts[cell], sibs

# ---- contract methods ----------------------------------------------------------------------------
# maps: p1 p2 (addrs) · r1 r2 (roots) · st(stake) pt(pot) nn(count) sd(settled) dl(deadline) · mc(move#/turn)
#       pc(pending shot cell) pex(pending exists) · h1 h2 (hit counts) · f1[g|cell] f2[g|cell] (fired) · wr(winner)
open_m = [
  VALUE, P(0), GT, REQ,
  A(0), P(0), GT, REQ,
  A(0), LD("nn"), P(0), EQ, REQ,
  A(0), VALUE, ST("st"),
  A(0), VALUE, ST("pt"),
  A(0), CALLER, ST("p1"),
  A(0), A(1), ST("r1"),                 # p1's board commitment
  A(0), P(1), ST("nn"),
  HALT ]
join_m = [
  A(0), LD("nn"), P(1), EQ, REQ,
  VALUE, A(0), LD("st"), EQ, REQ,
  CALLER, A(0), LD("p1"), EQ, NOT, REQ,
  A(0), A(0), LD("pt"), VALUE, ADD, ST("pt"),
  A(0), CALLER, ST("p2"),
  A(0), A(1), ST("r2"),                 # p2's board commitment
  A(0), P(2), ST("nn"),
  A(0), CURSOR, P(WINDOW), ADD, ST("dl"),
  HALT ]

# root-agnostic recompute of the merkle-sum for cell (cell_ops pushes the cell#), leaving the reconstructed
# hash in S["h"] and the accumulated ship-count in S["s"]. Uses ONLY [ ]-sequenced instructions (+ joins seqs).
def _merkle_recompute(cell_ops):
    ops  = [P("h"), A(3), P(256), MUL] + cell_ops + [P(2), MUL, ADD, A(2), ADD, HASH, ST(S)]   # leaf=HASH(salt*256+cell*2+isShip)
    ops += [P("s"), A(2), ST(S)]                                                                 # s = isShip
    for L in range(LEVELS):
        div = 2 ** (LEVELS - 1 - L)                 # dir bit = (cell // div) % 2  (bit-reversed leaf position)
        sibH = A(4 + 2*L); sibS = A(5 + 2*L)
        ops += [P("s"), P("s"), LD(S), sibS, ADD, ST(S)]                                          # s += sibSum
        ops += [P("d")] + cell_ops + [P(div), DIV, P(2), MOD, ST(S)]                              # d = direction
        ops += [P("a"), P("h"), LD(S), P(1), P("d"), LD(S), SUB, MUL, sibH, P("d"), LD(S), MUL, ADD, ST(S)]  # a = h*(1-d)+sib*d
        ops += [P("b"), P("h"), LD(S), P("d"), LD(S), MUL, sibH, P(1), P("d"), LD(S), SUB, MUL, ADD, ST(S)]  # b = h*d+sib*(1-d)
        ops += [P("h"), P("a"), LD(S), P(M2), MUL, P("b"), LD(S), P(M1), MUL, ADD, P("s"), LD(S), ADD, HASH, ST(S)]  # h=HASH(a*M2+b*M1+s)
    return ops

# move(g, fireCell, isShip, salt, sib0,ss0 .. sib6,ss6): prove the OPPONENT's pending shot at MY board
# (skipped on the very first move), credit the hit, settle if 17, then fire MY next shot. Branch-free: every
# guard is an algebraic 0/1 flag multiplied in, so there are no JUMPs.
def _mk_move():
    P1v   = [P("P1"), LD(S)]                 # push iAmP1 (0/1)
    NOTP1 = [P(1), P("P1"), LD(S), SUB]      # 1 - P1
    ops  = [A(0), LD("nn"), P(2), EQ, REQ]
    ops += [A(0), LD("sd"), NOT, REQ]
    ops += [CALLER, A(0), LD("p1"), EQ, A(0), LD("mc"), P(2), MOD, P(0), EQ, AND,        # my turn: p1 on even mc,
            CALLER, A(0), LD("p2"), EQ, A(0), LD("mc"), P(2), MOD, P(1), EQ, AND, OR, REQ]  #          p2 on odd mc
    ops += [P("P1"), CALLER, A(0), LD("p1"), EQ, ST(S)]                                   # P1 = caller==p1
    ops += _merkle_recompute([A(0), LD("pc")])                                            # recompute proof of pc
    MYROOT = [A(0), LD("r1")] + P1v + [MUL, A(0), LD("r2")] + NOTP1 + [MUL, ADD]           # myroot = P1?r1:r2
    ops += [A(0), LD("pex"), NOT, P("h"), LD(S)] + MYROOT + [EQ, OR, REQ]                  # pex ⇒ h==myroot
    ops += [A(0), LD("pex"), NOT, P("s"), LD(S), P(SHIPS), EQ, OR, REQ]                    # pex ⇒ sum==17
    HIT = [A(0), LD("pex"), A(2), P(1), EQ, AND]                                           # hit = pex && isShip==1
    ops += [A(0), A(0), LD("h2")] + HIT + P1v   + [MUL, ADD, ST("h2")]                     # opp(=p2 if I'm p1) hits += hit
    ops += [A(0), A(0), LD("h1")] + HIT + NOTP1 + [MUL, ADD, ST("h1")]
    # record the shot RESULT so the ATTACKER's UI can render it: res[g|attackerSlot|pc] = (isShip+1)*pex.
    # attackerSlot = the opponent of the caller = 1+P1 (I'm p1 → attacker is p2 → 2; I'm p2 → attacker p1 → 1).
    RESKEY = ([A(0), P("|"), OP("CONCAT")] + [P(1)] + P1v + [ADD, OP("CONCAT"), P("|"), OP("CONCAT"), A(0), LD("pc"), OP("CONCAT")])
    ops += RESKEY + [A(2), P(1), ADD, A(0), LD("pex"), MUL, ST("res")]
    P1WIN = [A(0), LD("h1"), P(SHIPS), EQ]; P2WIN = [A(0), LD("h2"), P(SHIPS), EQ]
    ANYWIN = P1WIN + P2WIN + [OR]
    ops += [A(0), LD("p1"), A(0), LD("pt")] + P1WIN + [MUL, PAY]                           # pay winner the pot
    ops += [A(0), LD("p2"), A(0), LD("pt")] + P2WIN + [MUL, PAY]
    ops += [A(0), P(1)] + P1WIN + [MUL, P(2)] + P2WIN + [MUL, ADD, ST("wr")]
    ops += [A(0)] + ANYWIN + [ST("sd")]
    ops += [A(0), A(0), LD("pt"), P(1)] + ANYWIN + [SUB, MUL, ST("pt")]
    NOTDONE = [A(0), LD("sd"), NOT]
    FKEY = [A(0), P("|"), OP("CONCAT"), A(1), OP("CONCAT")]                                # "g|cell"
    ops += [A(0), LD("sd"), A(1), P(0), GTE, A(1), P(99), LTE, AND, OR, REQ]               # playing ⇒ cell 0..99
    ALREADY = FKEY + [LD("f1")] + P1v + [MUL] + FKEY + [LD("f2")] + NOTP1 + [MUL, ADD]     # my prior shot here?
    ops += [A(0), LD("sd")] + ALREADY + [P(0), EQ, OR, REQ]                                # playing ⇒ not already fired
    ops += FKEY + P1v   + NOTDONE + [MUL, ST("f1")]                                        # record fire in my slot
    ops += FKEY + NOTP1 + NOTDONE + [MUL, ST("f2")]
    ops += [A(0), A(1)] + NOTDONE + [MUL, A(0), LD("pc"), A(0), LD("sd"), MUL, ADD, ST("pc")]  # pc = playing?fireCell:pc
    ops += [A(0)] + NOTDONE + [ST("pex")]
    ops += [A(0), A(0), LD("mc"), P(1)] + NOTDONE + [MUL, ADD, ST("mc")]                   # mc += playing
    ops += [A(0), CURSOR, P(WINDOW), ADD, ST("dl")]
    ops += [HALT]
    return ops

move_m = _mk_move()

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
# timeout(g): past the move deadline, the player whose turn it is NOT (the waiter) claims the win.
timeout_m = [
  A(0), LD("nn"), P(2), EQ, REQ,
  A(0), LD("sd"), NOT, REQ,
  CURSOR, A(0), LD("dl"), GT, REQ,
  # current mover = p1 if mc even else p2; caller must be the OTHER (the one being stalled on)
  CALLER, A(0), LD("p1"), EQ, A(0), LD("mc"), P(2), MOD, P(1), EQ, AND,     # p1 waits when it's p2's turn (mc odd)
  CALLER, A(0), LD("p2"), EQ, A(0), LD("mc"), P(2), MOD, P(0), EQ, AND,     # p2 waits when it's p1's turn (mc even)
  OR, REQ,
  CALLER, A(0), LD("pt"), PAY,                                     # the waiter (caller) WINS the pot
  A(0), P(1), CALLER, A(0), LD("p1"), EQ, MUL, P(2), CALLER, A(0), LD("p2"), EQ, MUL, ADD, ST("wr"),
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

CODE = {"open":open_m, "join":join_m, "move":move_m, "resign":resign_m, "timeout":timeout_m, "cancel":cancel_m}

# ================= TESTS =================
F=[]
def ck(n,c): print(("  ok  " if c else " FAIL ")+n); (F.append(n) if not c else None)
st=ExecState(tempfile.mktemp()); st.cursor=100
for a in ("A","B","EVE"): st.credit_deposit(a, 10**13)
st.apply_blob({"op":"deploy","code":CODE,"runtime":"stackvm","nonce":"battleship"},"A","d0")
CID=list(st.contracts)[0]
def bal(a): return st.bridge.get(a,0)
def M(m,k): return st.contracts[CID]["storage"].get(m,{}).get(str(k),0)
def call(m,args,val,who): return st.apply_blob({"op":"call","contract":CID,"method":m,"args":args,"value":val},who,m+str(args)+who+str(st.cursor))
def rv(r): return "revert" in r or "skip" in r

import random
random.seed(1)
def rand_board(ship_cells):
    board=[0]*128;
    for c in ship_cells: board[c]=1
    salts=[random.getrandbits(256) for _ in range(128)]
    return board, salts
def proof_args(board, salts, cell):
    isShip, salt, sibs = make_proof(board, salts, cell)
    a=[isShip, salt]
    for (h,s) in sibs: a += [h, s]
    return a   # -> [isShip, salt, sib0,ss0, ... sib6,ss6]

# two valid 17-cell fleets
FA = list(range(0,5))+list(range(10,14))+list(range(20,23))+list(range(30,33))+list(range(40,42))   # 5+4+3+3+2
FB = [c+5 for c in FA]
boardA, saltsA = rand_board(FA)
boardB, saltsB = rand_board(FB)
rootA = build_root(boardA, saltsA)
rootB = build_root(boardB, saltsB)

STAKE=10**9
call("open",[1, rootA], STAKE, "A")
call("join",[1, rootB], STAKE, "B")
ck("pot escrows both stakes", M("pt",1)==2*STAKE and bal(CID)==2*STAKE)
ck("commitments stored", M("r1",1)==rootA and M("r2",1)==rootB)

# A fires first (no proof yet). Fire at B's cell 5 (a ship in FB).
call("move",[1, 5, 0,0]+[0,0]*7, 0, "A")
ck("A's first shot recorded, turn -> B", M("pc",1)==5 and M("pex",1)==1 and M("mc",1)==1)
ck("B cannot move out of turn... A tries again", rv(call("move",[1, 6, 0,0]+[0,0]*7, 0, "A")))

def bad_miss(board, salts, cell):
    """A FALSE 'miss' proof: claim isShip=0 for a real ship, reusing its true salt+siblings (leaf won't match root)."""
    _, salt, sibs = make_proof(board, salts, cell)
    a=[0, salt]
    for (h,s) in sibs: a += [h,s]
    return a

# cell 5 ∈ FB (a ship in B), cell 0 ∈ FA (a ship in A). A fired at 5. B proves it against B's board -> HIT for A.
call("move",[1, 0]+proof_args(boardB,saltsB,5), 0, "B")   # B proves A's shot(5)=HIT, fires at A's cell 0
ck("B proved A's shot (cell 5 ∈ B) = HIT for A", M("h1",1)==1 and M("pc",1)==0 and M("mc",1)==2)
ck("shot RESULT recorded for the attacker's UI (res[g|1|5]=2=hit)", M("res","1|1|5")==2)

# A must now prove B's shot at cell 0 (∈ FA). A cannot claim a FALSE miss on it.
ck("A cannot prove a FALSE miss (isShip=0 on a real ship)", rv(call("move",[1, 6]+bad_miss(boardA,saltsA,0), 0, "A")))
call("move",[1, 6]+proof_args(boardA,saltsA,0), 0, "A")   # A proves B's shot(0)=HIT for B, fires at B's cell 6
ck("A proved B's shot (cell 0 ∈ A) = HIT for B", M("h2",1)==1)

# Full game to a win: A sinks all 17 of B's ships (FB). A fires FB cells; B proves each as a HIT (-> h1). Between,
# B fires at A's FA cells and A proves them. A wins when h1 reaches 17.
call("open",[2, rootA], STAKE, "A")
call("join",[2, rootB], STAKE, "B")
bA=bal("A")
call("move",[2, FB[0]]+[0,0]+[0,0]*7, 0, "A")             # A fires B-ship 0 (first move, proof ignored)
for i in range(1, 18):
    call("move",[2, FA[i-1]]+proof_args(boardB,saltsB,FB[i-1]), 0, "B")   # B proves A's shot FB[i-1]=HIT (h1++), fires FA[i-1]
    if M("sd",2)==1: break
    call("move",[2, FB[i]]+proof_args(boardA,saltsA,FA[i-1]), 0, "A")     # A proves B's shot FA[i-1], fires next B-ship FB[i]
ck("A sank all 17 of B's ships -> A wins the pot", M("wr",2)==1 and M("sd",2)==1 and M("h1",2)==17 and bal("A")>=bA+STAKE and M("pt",2)==0)

# timeout: fresh game, B never proves A's shot -> A (waiter) claims after the deadline
call("open",[3, rootA], STAKE, "A"); call("join",[3, rootB], STAKE, "B")
call("move",[3, FB[0]]+[0,0]+[0,0]*7, 0, "A")        # A fired, now it's B's turn (mc odd)
ck("timeout before deadline reverts", rv(call("timeout",[3], 0, "A")))
st.cursor += WINDOW+1
bA=bal("A")
call("timeout",[3], 0, "A")
ck("A claims the stalled pot after the deadline", M("wr",3)==1 and M("sd",3)==1 and bal("A")>=bA+2*STAKE)

# cancel: un-joined game refunds the opener
call("open",[4, rootA], STAKE, "A")
bA=bal("A")
call("cancel",[4], 0, "A")
ck("cancel refunds the opener", bal("A")==bA+STAKE and M("sd",4)==1)

# adversarial: a FEWER-SHIPS cheat can't even move — the sum inside the proof binds the count to exactly 17.
cheat=[0]*128
for c in range(16): cheat[c]=1                       # only 16 ships (one hidden)
csalts=[random.getrandbits(256) for _ in range(128)]
croot=build_root(cheat,csalts)
call("open",[5, rootA], STAKE, "A"); call("join",[5, croot], STAKE, "B")
call("move",[5, 0]+[0,0]+[0,0]*7, 0, "A")            # A fires cell 0
ck("a <17-ship board can't produce a valid proof (count is bound to 17)",
   rv(call("move",[5, 30]+proof_args(cheat,csalts,0), 0, "B")))

# adversarial: firing the same cell twice is rejected.
call("open",[6, rootA], STAKE, "A"); call("join",[6, rootB], STAKE, "B")
call("move",[6, FB[0]]+[0,0]+[0,0]*7, 0, "A")                       # A fires FB[0]
call("move",[6, FA[0]]+proof_args(boardB,saltsB,FB[0]), 0, "B")    # B proves, fires FA[0]
call("move",[6, FB[1]]+proof_args(boardA,saltsA,FA[0]), 0, "A")    # A proves, fires FB[1]
ck("re-firing a cell already shot reverts",
   rv(call("move",[6, FA[0]]+proof_args(boardB,saltsB,FB[1]), 0, "B")))   # B tries to fire FA[0] again

# ---- regenerate the committed contract artifact ----
import os
outp = os.path.join(os.path.dirname(__file__), "..", "execnode", "contracts", "battleship.json")
if os.environ.get("WRITE"):
    json.dump(CODE, open(outp,"w")); print("WROTE", outp)
elif os.path.exists(outp):
    committed = json.load(open(outp))
    ck("committed battleship.json matches the assembled contract", committed == CODE)

print(("\nALL PASS" if not F else "\nFAILED: " + ", ".join(F)))
sys.exit(1 if F else 0)
