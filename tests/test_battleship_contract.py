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

# ---- reveal-at-claim: derive salts from ONE seed + validate a fleet is the standard 5 ships ----------
# Salts are now seed-derived (salt[c]=HASH(seed*128+c)) so a claim reveals just the seed, not 128 salts.
# The client uses the identical formula, so per-cell move proofs are unchanged; individual revealed salts
# don't leak the seed (one-way hash).
FLEET_LENS = [5, 4, 3, 3, 2]                       # ship lengths, in claim-arg order
def seed_salt(seed, c):    return VMHASH(seed * 128 + c)
def salts_from_seed(seed): return [seed_salt(seed, c) for c in range(128)]
def ship_cells(anchor, orient, length):
    step = 1 + orient * 9                          # 1 = horizontal, 10 = vertical
    return [anchor + k * step for k in range(length)]
def board_from_ships(ships):                       # ships = [(anchor,orient) x5] -> 128-cell board
    b = [0] * 128
    for (a, o), L in zip(ships, FLEET_LENS):
        for c in ship_cells(a, o, L): b[c] = 1
    return b
def valid_fleet(ships):
    occ = set()
    for (a, o), L in zip(ships, FLEET_LENS):
        if not (0 <= a <= 99) or o not in (0, 1): return False
        cells = ship_cells(a, o, L); last = cells[-1]
        if last > 99: return False
        if o == 0 and a // 10 != last // 10: return False     # a horizontal ship must stay in one row
        for c in cells:
            if c in occ: return False                          # no overlap
            occ.add(c)
    return len(occ) == 17
def root_from_ships(ships, seed): return build_root(board_from_ships(ships), salts_from_seed(seed))

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
  A(0), P(1), ST("tf"),                 # p1 fires first (tf = whose turn to FIRE)
  A(0), CURSOR, P(WINDOW), ADD, ST("dl"),
  HALT ]

# root-agnostic recompute of the merkle-sum for cell (cell_ops pushes the cell#), leaving the reconstructed
# hash in S["h"] and the accumulated ship-count in S["s"]. Uses ONLY [ ]-sequenced instructions (+ joins seqs).
def _merkle_recompute(cell_ops, base=2):
    isShip, salt = A(base), A(base + 1)             # base=2 for the old move layout; answer() uses base=1 (no fireCell arg)
    ops  = [P("h"), salt, P(256), MUL] + cell_ops + [P(2), MUL, ADD, isShip, ADD, HASH, ST(S)]  # leaf=HASH(salt*256+cell*2+isShip)
    ops += [P("s"), isShip, ST(S)]                                                               # s = isShip
    for L in range(LEVELS):
        div = 2 ** (LEVELS - 1 - L)                 # dir bit = (cell // div) % 2  (bit-reversed leaf position)
        sibH = A(base + 2 + 2*L); sibS = A(base + 3 + 2*L)
        ops += [P("s"), P("s"), LD(S), sibS, ADD, ST(S)]                                          # s += sibSum
        ops += [P("d")] + cell_ops + [P(div), DIV, P(2), MOD, ST(S)]                              # d = direction
        ops += [P("a"), P("h"), LD(S), P(1), P("d"), LD(S), SUB, MUL, sibH, P("d"), LD(S), MUL, ADD, ST(S)]  # a = h*(1-d)+sib*d
        ops += [P("b"), P("h"), LD(S), P("d"), LD(S), MUL, sibH, P(1), P("d"), LD(S), SUB, MUL, ADD, ST(S)]  # b = h*d+sib*(1-d)
        ops += [P("h"), P("a"), LD(S), P(M2), MUL, P("b"), LD(S), P(M1), MUL, ADD, P("s"), LD(S), ADD, HASH, ST(S)]  # h=HASH(a*M2+b*M1+s)
    return ops

# ---- turn model: FIRE then ANSWER, split so the defender's client can auto-reveal the result immediately ----
# tf = whose turn it is to FIRE (1/2) when nothing is pending. pex = a shot awaits an answer. pf = who fired that
# pending shot (the OTHER player must answer it). fd["g|slot|cell"] = that slot fired there. So you fire(); your
# opponent's client answer()s at once (proving hit/miss vs THEIR committed board) and you see the result in ~1
# block instead of waiting for their whole turn. Both branch-free.
def _mk_fire():
    ops  = [A(0), LD("nn"), P(2), EQ, REQ]
    ops += [A(0), LD("dc"), NOT, REQ]
    ops += [A(0), LD("pex"), NOT, REQ]                                        # nothing may be awaiting an answer
    ops += [P("P1"), CALLER, A(0), LD("p1"), EQ, ST(S)]                       # P1 = caller==p1
    MYSLOT = [P(1), P("P1"), LD(S), MUL, P(2), P(1), P("P1"), LD(S), SUB, MUL, ADD]   # 1 if p1 else 2
    ops += [CALLER, A(0), LD("p1"), EQ, CALLER, A(0), LD("p2"), EQ, OR, REQ]  # caller is a player
    ops += [A(0), LD("tf")] + MYSLOT + [EQ, REQ]                              # it's my turn to fire
    ops += [A(1), P(0), GTE, A(1), P(99), LTE, AND, REQ]                      # cell in 0..99
    FDK = [A(0), P("|"), OP("CONCAT")] + MYSLOT + [OP("CONCAT"), P("|"), OP("CONCAT"), A(1), OP("CONCAT")]   # "g|slot|cell"
    ops += FDK + [LD("fd"), P(0), EQ, REQ]                                    # not already fired here by me
    ops += FDK + [P(1), ST("fd")]                                            # record my shot
    ops += [A(0), A(1), ST("pc")]                                            # the cell now awaiting an answer
    ops += [A(0), P(1), ST("pex")]
    ops += [A(0)] + MYSLOT + [ST("pf")]                                      # I fired it -> the opponent answers
    ops += [A(0), CURSOR, P(WINDOW), ADD, ST("dl")]                          # answer clock
    ops += [HALT]
    return ops

# answer(g, isShip, salt, sib0,ss0 .. sib6,ss6): as the player fired upon, reveal that cell against MY committed
# board -> credit the shooter's hit, record the result, settle at 17 -> then it becomes MY turn to fire.
def _mk_answer():
    P1v = [P("P1"), LD(S)]; NOTP1 = [P(1), P("P1"), LD(S), SUB]
    ops  = [A(0), LD("nn"), P(2), EQ, REQ]
    ops += [A(0), LD("dc"), NOT, REQ]
    ops += [A(0), LD("pex"), REQ]                                            # a shot must be pending
    ops += [P("P1"), CALLER, A(0), LD("p1"), EQ, ST(S)]                      # P1 = caller==p1
    MYSLOT = [P(1)] + P1v + [MUL, P(2)] + NOTP1 + [MUL, ADD]                 # 1 if p1 else 2
    ops += MYSLOT + [A(0), LD("pf"), ADD, P(3), EQ, REQ]                     # I'm the answerer: myslot + pf == 3
    ops += _merkle_recompute([A(0), LD("pc")], base=1)                       # recompute pc's proof (isShip=A1, salt=A2)
    MYROOT = [A(0), LD("r1")] + P1v + [MUL, A(0), LD("r2")] + NOTP1 + [MUL, ADD]
    ops += [P("h"), LD(S)] + MYROOT + [EQ, REQ]                              # leaf hashes to MY committed root (no lying)
    ops += [P("s"), LD(S), P(SHIPS), EQ, REQ]                                # sum == 17 (can't hide ships)
    HIT = [A(1), P(1), EQ]                                                    # isShip == 1
    ops += [A(0), A(0), LD("h1")] + HIT + [A(0), LD("pf"), P(1), EQ, MUL, ADD, ST("h1")]   # firer(pf) hits += hit
    ops += [A(0), A(0), LD("h2")] + HIT + [A(0), LD("pf"), P(2), EQ, MUL, ADD, ST("h2")]
    RESKEY = [A(0), P("|"), OP("CONCAT"), A(0), LD("pf"), OP("CONCAT"), P("|"), OP("CONCAT"), A(0), LD("pc"), OP("CONCAT")]
    ops += RESKEY + [A(1), P(1), ADD, ST("res")]                             # res[g|firer|cell] = isShip+1 (1 miss,2 hit)
    P1WIN = [A(0), LD("h1"), P(SHIPS), EQ]; P2WIN = [A(0), LD("h2"), P(SHIPS), EQ]
    ANYWIN = P1WIN + P2WIN + [OR]
    ops += [A(0), P(1)] + P1WIN + [MUL, P(2)] + P2WIN + [MUL, ADD, ST("wr")]
    ops += [A(0)] + ANYWIN + [ST("dc")]                                      # 17 hits -> decided (winner claims the pot)
    ops += [A(0), CURSOR, P(WINDOW), ADD, ST("cd")]
    ops += [A(0), P(0), ST("pex")]                                          # answered -> nothing pending
    ops += [A(0)] + MYSLOT + [ST("tf")]                                      # I answered -> now it's MY turn to fire
    ops += [A(0), CURSOR, P(WINDOW), ADD, ST("dl")]                          # fire clock
    ops += [HALT]
    return ops
fire_m = _mk_fire()
answer_m = _mk_answer()

resign_m = [
  A(0), LD("nn"), P(2), EQ, REQ,
  A(0), LD("dc"), NOT, REQ,
  CALLER, A(0), LD("p1"), EQ, CALLER, A(0), LD("p2"), EQ, OR, REQ,
  # resigner forfeits → opponent is the winner; pot is released by the winner's claim() (valid-fleet reveal).
  A(0), P(2), CALLER, A(0), LD("p1"), EQ, MUL, P(1), CALLER, A(0), LD("p2"), EQ, MUL, ADD, ST("wr"),
  A(0), P(1), ST("dc"),
  A(0), CURSOR, P(WINDOW), ADD, ST("cd"),
  HALT ]
# timeout(g): past the deadline, the WAITER (the one being stalled on) wins, then claim()s. The staller is whoever
# owes the next action: if a shot is pending (pex) the answerer (3-pf) owes it → waiter = pf; else the firer (tf)
# owes it → waiter = 3-tf. So waiterSlot = pex ? pf : 3-tf.
_WAITER = [A(0), LD("pex"), A(0), LD("pf"), MUL,                          # pex*pf
           P(1), A(0), LD("pex"), SUB, P(3), A(0), LD("tf"), SUB, MUL, ADD]  # + (1-pex)*(3-tf)
timeout_m = [
  A(0), LD("nn"), P(2), EQ, REQ,
  A(0), LD("dc"), NOT, REQ,
  CURSOR, A(0), LD("dl"), GT, REQ,
  CALLER, A(0), LD("p1"), EQ] + _WAITER + [P(1), EQ, AND,                 # caller is the waiter (p1) ...
  CALLER, A(0), LD("p2"), EQ] + _WAITER + [P(2), EQ, AND, OR, REQ,        # ... or (p2)
  A(0), P(1), CALLER, A(0), LD("p1"), EQ, MUL, P(2), CALLER, A(0), LD("p2"), EQ, MUL, ADD, ST("wr"),
  A(0), P(1), ST("dc"),
  A(0), CURSOR, P(WINDOW), ADD, ST("cd"),
  HALT ]
# claim(g, a0,o0,a1,o1,a2,o2,a3,o3,a4,o4, seed): the WINNER of a decided game reveals their 5 ship placements
# + salt-seed to collect. The contract rebuilds the whole 128-leaf merkle-sum tree from those ships (salts
# derived as HASH(seed*128+c)), REQUIREs the rebuilt root == the winner's committed root AND the total ship
# count == 17 — so the committed board provably IS the 5 standard contiguous, in-bounds, non-overlapping ships.
# A shape-cheater's scattered commitment can't be reproduced from valid ships, so they can never claim.
KEY = lambda L, i: L * 256 + i            # unique (level,index) slot in the scratch tree maps TH/TS
def _mk_claim():
    a  = lambda i: A(1 + 2*i)             # anchor arg of ship i
    o  = lambda i: A(2 + 2*i)             # orientation arg of ship i (0 horiz, 1 vert)
    SEED = A(11)
    W1 = [A(0), LD("wr"), P(1), EQ]                                     # winner is p1?  (wr==1)
    # roots are integers so we can pick the winner's commitment arithmetically; ADDRESSES can't be (they're
    # strings) — so the caller-is-winner test and the payout use guard flags, never address arithmetic.
    WIN_ROOT  = [A(0), LD("r1")] + W1 + [MUL, A(0), LD("r2"), P(1)] + W1 + [SUB, MUL, ADD]
    ops  = [A(0), LD("nn"), P(2), EQ, REQ]
    ops += [A(0), LD("dc"), REQ]                                        # game must be DECIDED
    ops += [A(0), LD("sd"), NOT, REQ]                                   # not already settled/paid
    ops += [CALLER, A(0), LD("p1"), EQ, A(0), LD("wr"), P(1), EQ, AND,  # caller is the winner:
            CALLER, A(0), LD("p2"), EQ, A(0), LD("wr"), P(2), EQ, AND, OR, REQ]  #  (p1 & wr==1) or (p2 & wr==2)
    # per-ship shape validity: in-bounds, orientation boolean, last cell on-grid, horizontal ships stay in one row
    for i in range(5):
        L = FLEET_LENS[i]
        last = [a(i), P(L-1), ADD, P(9*(L-1)), o(i), MUL, ADD]         # a + (L-1) + 9*(L-1)*o  (= last cell)
        ops += [a(i), P(0), GTE, REQ]
        ops += [a(i), P(99), LTE, REQ]
        ops += [o(i), P(1), LTE, REQ, o(i), P(0), GTE, REQ]
        ops += last + [P(99), LTE, REQ]
        ops += [o(i)] + [a(i), P(10), DIV] + last + [P(10), DIV, EQ, OR, REQ]   # vertical OR same row
    # build the occupancy map O[cell]: clear all 128, then set the 17 ship cells (overlap => fewer than 17 ones)
    for c in range(128): ops += [P(c), P(0), ST("O")]
    for i in range(5):
        L = FLEET_LENS[i]
        for k in range(L):
            cell = [a(i)] if k == 0 else [a(i), P(k), ADD, P(9*k), o(i), MUL, ADD]   # a + k*(1+9o)
            ops += cell + [P(1), ST("O")]
    # rebuild the merkle-sum tree. level 0: leaf(c)=HASH(HASH(seed*128+c)*256 + 2c + O[c]) at pos bitrev7(c).
    for c in range(128):
        pos = bitrev7(c)
        salt = [SEED, P(128), MUL, P(c), ADD, HASH]
        leaf = salt + [P(256), MUL, P(2*c), ADD, P(c), LD("O"), ADD, HASH]
        ops += [P(KEY(0, pos))] + leaf + [ST("TH")]
        ops += [P(KEY(0, pos)), P(c), LD("O"), ST("TS")]
    for Lv in range(1, LEVELS + 1):                                    # 7 pairings: 128 -> 1
        for i in range(128 >> Lv):
            lh, rh = KEY(Lv-1, 2*i), KEY(Lv-1, 2*i+1)
            node = [P(lh), LD("TH"), P(M2), MUL, P(rh), LD("TH"), P(M1), MUL, ADD,
                    P(lh), LD("TS"), P(rh), LD("TS"), ADD, ADD, HASH]
            ops += [P(KEY(Lv, i))] + node + [ST("TH")]
            ops += [P(KEY(Lv, i)), P(lh), LD("TS"), P(rh), LD("TS"), ADD, ST("TS")]
    root = KEY(LEVELS, 0)
    ops += [P(root), LD("TS"), P(SHIPS), EQ, REQ]                       # exactly 17 ship cells (catches overlap)
    ops += [P(root), LD("TH")] + WIN_ROOT + [EQ, REQ]                   # rebuilt root == the winner's commitment
    ops += [A(0), LD("p1"), A(0), LD("pt"), A(0), LD("wr"), P(1), EQ, MUL, PAY]   # pay the winner (guarded amount)
    ops += [A(0), LD("p2"), A(0), LD("pt"), A(0), LD("wr"), P(2), EQ, MUL, PAY]
    ops += [A(0), P(1), ST("sd")]
    ops += [A(0), P(0), ST("pt")]
    ops += [HALT]
    return ops
claim_m = _mk_claim()
# forfeit(g): the winner never proved a valid fleet before the claim deadline → the LOSER takes the pot.
forfeit_m = [
  A(0), LD("nn"), P(2), EQ, REQ,
  A(0), LD("dc"), REQ,
  A(0), LD("sd"), NOT, REQ,
  CURSOR, A(0), LD("cd"), GT, REQ,
  CALLER, A(0), LD("p1"), EQ, A(0), LD("wr"), P(2), EQ, AND,              # caller is the LOSER:
  CALLER, A(0), LD("p2"), EQ, A(0), LD("wr"), P(1), EQ, AND, OR, REQ,     #  (p1 & wr==2) or (p2 & wr==1)
  A(0), LD("p1"), A(0), LD("pt"), A(0), LD("wr"), P(2), EQ, MUL, PAY,     # pay the loser the pot (guarded amount)
  A(0), LD("p2"), A(0), LD("pt"), A(0), LD("wr"), P(1), EQ, MUL, PAY,
  A(0), P(1), ST("sd"),
  A(0), P(0), ST("pt"),
  HALT ]
cancel_m = [
  A(0), LD("nn"), P(1), EQ, REQ,
  CALLER, A(0), LD("p1"), EQ, REQ,
  A(0), LD("sd"), NOT, REQ,
  A(0), LD("dc"), NOT, REQ,
  A(0), LD("p1"), A(0), LD("pt"), PAY,
  A(0), P(1), ST("sd"),
  A(0), P(0), ST("pt"),
  HALT ]

CODE = {"open":open_m, "join":join_m, "fire":fire_m, "answer":answer_m, "resign":resign_m, "timeout":timeout_m,
        "cancel":cancel_m, "claim":claim_m, "forfeit":forfeit_m}

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

# two valid 17-cell fleets, expressed as SHIP placements (anchor,orient); salts are seed-derived so a claim
# reveals just the seed. board_from_ships(shipsA) reproduces the old FA cell set exactly.
shipsA = [(0,0),(10,0),(20,0),(30,0),(40,0)]     # 5·4·3·3·2 across rows 0-4, all horizontal
shipsB = [(5,0),(15,0),(25,0),(35,0),(45,0)]     # same, shifted right by 5
seedA = 0xA1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1
seedB = 0xB2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2
FA = [c for (a,o),L in zip(shipsA,FLEET_LENS) for c in ship_cells(a,o,L)]
FB = [c for (a,o),L in zip(shipsB,FLEET_LENS) for c in ship_cells(a,o,L)]
boardA, saltsA = board_from_ships(shipsA), salts_from_seed(seedA)
boardB, saltsB = board_from_ships(shipsB), salts_from_seed(seedB)
rootA = build_root(boardA, saltsA)
rootB = build_root(boardB, saltsB)
def cl_args(g, ships, seed):
    r = [g]
    for (a, o) in ships: r += [a, o]
    return r + [seed]

STAKE=10**9
call("open",[1, rootA], STAKE, "A")
call("join",[1, rootB], STAKE, "B")
ck("pot escrows both stakes", M("pt",1)==2*STAKE and bal(CID)==2*STAKE)
ck("commitments stored", M("r1",1)==rootA and M("r2",1)==rootB)

def bad_miss(board, salts, cell):
    """A FALSE 'miss' proof: claim isShip=0 for a real ship, reusing its true salt+siblings (leaf won't match root)."""
    _, salt, sibs = make_proof(board, salts, cell)
    a=[0, salt]
    for (h,s) in sibs: a += [h,s]
    return a
def fire(g, cell, who):      return call("fire", [g, cell], 0, who)
def answer(g, board, salts, cell, who): return call("answer", [g]+proof_args(board, salts, cell), 0, who)

# A fires first at B's cell 5 (a ship in FB). No proof — the RESULT comes from B's answer().
fire(1, 5, "A")
ck("A's shot is pending B's answer (pex, pf=A)", M("pc",1)==5 and M("pex",1)==1 and M("pf",1)==1)
ck("A can't fire again while a shot awaits an answer", rv(fire(1, 6, "A")))
ck("A (the shooter) can't answer their own shot", rv(answer(1, boardB, saltsB, 5, "A")))
ck("B can't answer a FALSE miss on a real ship", rv(call("answer",[1]+bad_miss(boardB,saltsB,5), 0, "B")))
answer(1, boardB, saltsB, 5, "B")                    # B reveals cell 5 (∈ FB) = HIT for A; now B's turn to fire
ck("B answered A's shot(5∈B)=HIT for A → B fires next", M("h1",1)==1 and M("pex",1)==0 and M("tf",1)==2)
ck("shot RESULT recorded for the attacker's UI (res[g|1|5]=2=hit)", M("res","1|1|5")==2)
ck("A cannot fire out of turn (it's B's turn)", rv(fire(1, 7, "A")))
fire(1, 0, "B")                                      # B fires at A's cell 0 (∈ FA)
ck("A can't answer a FALSE miss", rv(call("answer",[1]+bad_miss(boardA,saltsA,0), 0, "A")))
answer(1, boardA, saltsA, 0, "A")                    # A reveals cell 0 = HIT for B
ck("A answered B's shot(0∈A)=HIT for B → A fires next", M("h2",1)==1 and M("tf",1)==1)

# reference sanity for the fleet validator the contract mirrors
ck("(ref) valid_fleet accepts the standard fleet", valid_fleet(shipsA) and valid_fleet(shipsB))
ck("(ref) valid_fleet rejects overlap / off-grid",
   (not valid_fleet([(0,0),(0,0),(20,0),(30,0),(40,0)])) and (not valid_fleet([(96,0),(10,0),(20,0),(30,0),(40,0)])))

# Full game to a win, then DECIDE→CLAIM settlement. A sinks all 17 of B's ships (FB): each round A fires FB[i],
# B answers it (h1++); between, B fires A's FA[i] and A answers. A is DECIDED the winner at h1==17.
call("open",[2, rootA], STAKE, "A")
call("join",[2, rootB], STAKE, "B")
bA=bal("A")
for i in range(17):
    fire(2, FB[i], "A"); answer(2, boardB, saltsB, FB[i], "B")   # A fires, B answers → h1++
    if M("dc",2)==1: break
    fire(2, FA[i], "B"); answer(2, boardA, saltsA, FA[i], "A")   # B fires, A answers
ck("A sank all 17 -> DECIDED for A, pot still ESCROWED (not auto-paid)",
   M("dc",2)==1 and M("wr",2)==1 and M("h1",2)==17 and M("sd",2)==0 and M("pt",2)==2*STAKE and bal("A")==bA)
ck("the loser B cannot claim A's win", rv(call("claim", cl_args(2, shipsB, seedB), 0, "B")))
ck("claim with the wrong seed (root mismatch) reverts", rv(call("claim", cl_args(2, shipsA, seedB), 0, "A")))
ck("claim with a mismatched fleet (root mismatch) reverts", rv(call("claim", cl_args(2, shipsB, seedA), 0, "A")))
call("claim", cl_args(2, shipsA, seedA), 0, "A")
ck("winner A reveals a VALID fleet -> pot released to A", M("sd",2)==1 and M("pt",2)==0 and bal("A")>=bA+STAKE)
ck("A cannot double-claim", rv(call("claim", cl_args(2, shipsA, seedA), 0, "A")))

# timeout #1 — the ANSWERER stalls: A fires, B never answers → A (the waiter=shooter) wins after the deadline.
call("open",[3, rootA], STAKE, "A"); call("join",[3, rootB], STAKE, "B")
fire(3, FB[0], "A")                                  # A fired, awaiting B's answer (pex, pf=A)
ck("timeout before deadline reverts", rv(call("timeout",[3], 0, "A")))
ck("the STALLER (B) can't timeout", rv(call("timeout",[3], 0, "B")))
st.cursor += WINDOW+1
call("timeout",[3], 0, "A")
ck("answerer stalled → waiter A wins; pot still escrowed", M("dc",3)==1 and M("wr",3)==1 and M("sd",3)==0 and M("pt",3)==2*STAKE)
bA=bal("A")
call("claim", cl_args(3, shipsA, seedA), 0, "A")
ck("A claims the stalled pot after revealing a valid fleet", M("sd",3)==1 and M("pt",3)==0 and bal("A")>=bA+2*STAKE)

# timeout #2 — the FIRER stalls: A fires, B answers (now B's turn to fire), B never fires → A (waiter=3-tf) wins.
call("open",[30, rootA], STAKE, "A"); call("join",[30, rootB], STAKE, "B")
fire(30, FB[0], "A"); answer(30, boardB, saltsB, FB[0], "B")    # now tf=2 (B must fire)
ck("firer-stall: waiter B can't timeout (B owes the fire)", rv(call("timeout",[30], 0, "B")))
st.cursor += WINDOW+1
call("timeout",[30], 0, "A")
ck("firer stalled → waiter A wins", M("dc",30)==1 and M("wr",30)==1)

# cancel: un-joined game refunds the opener
call("open",[4, rootA], STAKE, "A")
bA=bal("A")
call("cancel",[4], 0, "A")
ck("cancel refunds the opener", bal("A")==bA+STAKE and M("sd",4)==1)

# adversarial: a FEWER-SHIPS cheat can't ANSWER — the sum inside the proof binds the count to exactly 17.
cheat=[0]*128
for c in range(16): cheat[c]=1                       # only 16 ships (one hidden)
csalts=[random.getrandbits(256) for _ in range(128)]
croot=build_root(cheat,csalts)
call("open",[5, croot], STAKE, "A"); call("join",[5, rootB], STAKE, "B")   # A commits the cheat board
fire(5, 0, "B")                                      # B fires at A's cell 0; A (cheat board) must answer
ck("a <17-ship board can't produce a valid answer (count bound to 17)",
   rv(call("answer",[5]+proof_args(cheat,csalts,0), 0, "A")))

# adversarial: firing the same cell twice is rejected.
call("open",[6, rootA], STAKE, "A"); call("join",[6, rootB], STAKE, "B")
fire(6, FB[0], "A"); answer(6, boardB, saltsB, FB[0], "B")    # A fires FB[0], B answers (tf=2)
fire(6, FA[0], "B"); answer(6, boardA, saltsA, FA[0], "A")    # B fires FA[0], A answers (tf=1)
fire(6, FB[1], "A"); answer(6, boardB, saltsB, FB[1], "B")    # A fires FB[1], B answers (tf=2)
ck("re-firing a cell already shot reverts", rv(fire(6, FA[0], "B")))   # B tries to re-fire FA[0]

# adversarial: a SCATTERED-fleet committer can win (opponent resigns) but can NEVER claim — no set of valid
# ships reproduces a scattered root — so after the claim deadline the honest loser forfeits and recovers the pot.
scat = [0,2,4,6,8, 20,22,24,26, 40,42,44, 60,62,64, 80,82]          # 17 non-contiguous cells (illegal fleet)
seedS = 0xC3C3C3C3C3C3C3C3C3C3C3C3C3C3C3C3C3C3C3C3C3C3C3C3C3C3C3C3C3C3C3C3
scatBoard = [0]*128
for c in scat: scatBoard[c]=1
scatRoot = build_root(scatBoard, salts_from_seed(seedS))
call("open",[7, scatRoot], STAKE, "A")               # A commits a scattered (cheating) board
call("join",[7, rootB], STAKE, "B")
call("resign",[7], 0, "B")                           # B resigns -> A is DECIDED the winner
ck("cheat game decided for A, pot escrowed", M("dc",7)==1 and M("wr",7)==1 and M("sd",7)==0 and M("pt",7)==2*STAKE)
ck("cheater A cannot claim (no valid fleet reproduces a scattered root)", rv(call("claim", cl_args(7, shipsA, seedA), 0, "A")))
ck("forfeit before the claim deadline reverts", rv(call("forfeit",[7], 0, "B")))
st.cursor += WINDOW+1
bB=bal("B")
call("forfeit",[7], 0, "B")
ck("after the deadline the honest loser B recovers the pot; the cheater gets nothing",
   M("sd",7)==1 and M("pt",7)==0 and bal("B")>=bB+2*STAKE)

# adversarial: claim() rejects off-grid / overlapping fleets even from the legitimate winner; a valid one pays.
call("open",[8, rootA], STAKE, "A"); call("join",[8, rootB], STAKE, "B")
call("resign",[8], 0, "B")                           # A wins by B's resignation
ck("claim with an OFF-GRID ship reverts (in-bounds check)",
   rv(call("claim", cl_args(8, [(96,0),(10,0),(20,0),(30,0),(40,0)], seedA), 0, "A")))
ck("claim with OVERLAPPING ships reverts (sum/root mismatch)",
   rv(call("claim", cl_args(8, [(0,0),(0,0),(20,0),(30,0),(40,0)], seedA), 0, "A")))
bA=bal("A")
call("claim", cl_args(8, shipsA, seedA), 0, "A")
ck("winner A claims a resign-win with a valid fleet -> paid", M("sd",8)==1 and bal("A")>=bA+STAKE)

# forfeit guards: only the loser, only after the deadline; an honest winner is never time-barred from claiming.
call("open",[9, rootA], STAKE, "A"); call("join",[9, rootB], STAKE, "B")
call("resign",[9], 0, "B")                           # A wins
st.cursor += WINDOW+1
ck("the winner cannot forfeit-to-self", rv(call("forfeit",[9], 0, "A")))
ck("a third party cannot forfeit", rv(call("forfeit",[9], 0, "EVE")))
bA=bal("A")
call("claim", cl_args(9, shipsA, seedA), 0, "A")
ck("winner may still claim after the deadline (claim is not time-barred)", M("sd",9)==1 and bal("A")>=bA+STAKE)

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
