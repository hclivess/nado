# tests/test_reversi_contract.py — build + exercise the REVERSI (Othello) wager contract (stackvm).
#
# The deepest fully-on-chain referee yet: move() validates a reversi move ENTIRELY in the VM — it walks
# all 8 directions with JUMP loops, requires at least one flip (the legality rule), flips every bracketed
# run, and alternates turns. A PASS (pos=64) is always allowed; TWO passes in a row end the game and the
# contract counts the discs and pays the pot (majority wins, equal split refunds) — which covers the
# full-board and wiped-out endings, and lets both players agree to score early. Resign/abort/cancel come
# from the shared pvp skeleton (vmasm.pvp_methods).
#
# BOARD ADDRESSING: cell (c,r) at bd[g*512 + (c+1)*16 + (r+1)], c,r 0..7. The 16-stride padding means a
# walk that leaves the board reads a never-written slot (rows 0/9+, cols 0/9+; the ±offsets that bleed
# into a neighbour game's 512-block only touch its padding) — so direction walks need NO bounds checks.
# The four centre discs are placed by open(). Opener (p1) plays BLACK (1) and moves first.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vmasm import (P, A, LD, ST, SETR, R, IF, WHILE, CALLER, CURSOR, VALUE,
                   ADD, SUB, MUL, DIV, MOD, EQ, GT, GTE, LT, LTE, NOT, AND, OR, REQ, PAY, HALT,
                   pvp_methods, Harness)

WINDOW = 300          # ~30 min move clock
PASS = 64

CODE = dict(pvp_methods(WINDOW))

# open() additionally places the 4 centre discs: (3,3)=W (4,4)=W (3,4)=B (4,3)=B
_centre = []
for (c, r, k) in ((3, 3, 2), (4, 4, 2), (3, 4, 1), (4, 3, 1)):
    _centre = _centre + A(0) + P(512) + MUL + P((c + 1) * 16 + (r + 1)) + ADD + P(k) + ST("bd")
CODE["open"] = CODE["open"][:-1] + _centre + HALT   # splice before the trailing HALT

def _cell(base_reg, off_ops):
    """push bd[ R(base_reg) + off ]"""
    return R(base_reg) + off_ops + ADD + LD("bd")

def _dir_ops(dx, dy):
    """walk one direction from scratch 'base': count the opponent run, flip it if bracketed by mine.
    Uses scratch: base k opp n i fl (fl accumulates total flips)."""
    d = dx * 16 + dy
    return (
        SETR("n", P(0))
        # count consecutive opponent discs
        + WHILE(_cell("base", R("n") + P(1) + ADD + P(d) + MUL) + R("opp") + EQ,
                SETR("n", R("n") + P(1) + ADD))
        # bracketed by my own disc? then flip the run
        + IF(R("n") + P(0) + GT + _cell("base", R("n") + P(1) + ADD + P(d) + MUL) + R("k") + EQ + AND,
             SETR("i", P(1))
             + WHILE(R("i") + R("n") + LTE,
                     R("base") + R("i") + P(d) + MUL + ADD + R("k") + ST("bd")
                     + SETR("i", R("i") + P(1) + ADD))
             + SETR("fl", R("fl") + R("n") + ADD)))

_turn_checks = (
    A(0) + LD("nn") + P(2) + EQ + REQ
    + A(0) + LD("sd") + NOT + REQ
    + A(2) + A(0) + LD("mc") + EQ + REQ                     # PLY BINDING
    + CALLER + A(0) + LD("p1") + EQ + A(0) + LD("mc") + P(2) + MOD + P(0) + EQ + AND
    + CALLER + A(0) + LD("p2") + EQ + A(0) + LD("mc") + P(2) + MOD + P(1) + EQ + AND
    + OR + REQ
    + SETR("k", P(1) + A(0) + LD("mc") + P(2) + MOD + ADD)
    + SETR("opp", P(3) + R("k") + SUB))

_advance = (
    A(0) + A(0) + LD("mc") + P(1) + ADD + ST("mc")
    + A(0) + CURSOR + P(WINDOW) + ADD + ST("dl"))

# the two-pass game end: count discs, majority takes the pot, equal counts refund both
_score_and_pay = (
    SETR("n1", P(0)) + SETR("n2", P(0)) + SETR("ci", P(0))
    + WHILE(R("ci") + P(64) + LT,
            SETR("v", A(0) + P(512) + MUL
                 + R("ci") + P(8) + DIV + P(1) + ADD + P(16) + MUL + ADD
                 + R("ci") + P(8) + MOD + P(1) + ADD + ADD + LD("bd"))
            + SETR("n1", R("n1") + R("v") + P(1) + EQ + ADD)
            + SETR("n2", R("n2") + R("v") + P(2) + EQ + ADD)
            + SETR("ci", R("ci") + P(1) + ADD))
    + SETR("w1", R("n1") + R("n2") + GT)
    + SETR("w2", R("n2") + R("n1") + GT)
    + SETR("dr", P(1) + R("w1") + SUB + R("w2") + SUB)
    + A(0) + LD("p1") + A(0) + LD("pt") + R("w1") + MUL + PAY
    + A(0) + LD("p2") + A(0) + LD("pt") + R("w2") + MUL + PAY
    + A(0) + LD("p1") + A(0) + LD("st") + R("dr") + MUL + PAY
    + A(0) + LD("p2") + A(0) + LD("st") + R("dr") + MUL + PAY
    + A(0) + R("w1") + P(2) + R("w2") + MUL + ADD + P(3) + R("dr") + MUL + ADD + ST("wr")
    + A(0) + P(1) + ST("sd")
    + A(0) + P(0) + ST("pt"))

# move(g, pos, ply): pos 0..63 places (must flip >= 1), pos 64 = PASS (two in a row end the game)
CODE["move"] = (
    _turn_checks
    + A(1) + P(0) + GTE + REQ + A(1) + P(PASS) + LTE + REQ
    + IF(A(1) + P(PASS) + EQ,
         # PASS
         IF(A(0) + LD("lp"),
            _score_and_pay,
            A(0) + P(1) + ST("lp") + _advance),
         # PLACE: cell must be empty and flip at least one disc
         SETR("base", A(0) + P(512) + MUL
              + A(1) + P(8) + DIV + P(1) + ADD + P(16) + MUL + ADD
              + A(1) + P(8) + MOD + P(1) + ADD + ADD)
         + R("base") + LD("bd") + P(0) + EQ + REQ
         + SETR("fl", P(0))
         + _dir_ops(1, 0) + _dir_ops(-1, 0) + _dir_ops(0, 1) + _dir_ops(0, -1)
         + _dir_ops(1, 1) + _dir_ops(1, -1) + _dir_ops(-1, 1) + _dir_ops(-1, -1)
         + R("fl") + P(0) + GT + REQ
         + R("base") + R("k") + ST("bd")
         + A(0) + P(0) + ST("lp")
         + _advance)
    + HALT)


# ---------------- PYTHON REFERENCE ----------------
DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]

def ref_new():
    b = {}
    b[(3, 3)] = 2; b[(4, 4)] = 2; b[(3, 4)] = 1; b[(4, 3)] = 1
    return b

def ref_flips(b, c, r, k):
    if (c, r) in b: return []
    opp = 3 - k; out = []
    for dx, dy in DIRS:
        run = []; s = 1
        while b.get((c + s * dx, r + s * dy)) == opp:
            run.append((c + s * dx, r + s * dy)); s += 1
        if run and b.get((c + s * dx, r + s * dy)) == k:
            out += run
    return out

def ref_move(b, c, r, k):
    fl = ref_flips(b, c, r, k)
    if not fl: return False
    for cell in fl: b[cell] = k
    b[(c, r)] = k
    return True

def ref_legal(b, k):
    return [(c, r) for c in range(8) for r in range(8) if (c, r) not in b and ref_flips(b, c, r, k)]


# ---------------- TESTS ----------------
H = Harness(CODE, accounts=("B", "W", "EVE"), cursor=100, nonce="reversi")
ck, call, bal, M, rv = H.ck, H.call, H.bal, H.M, H.rv
STAKE = 10**9

def cell(g, c, r): return M("bd", g * 512 + (c + 1) * 16 + (r + 1))
def pos(c, r): return c * 8 + r

call("open", [1], STAKE, "B"); call("join", [1], STAKE, "W")
ck("open places the four centre discs", cell(1, 3, 3) == 2 and cell(1, 4, 4) == 2 and cell(1, 3, 4) == 1 and cell(1, 4, 3) == 1)
ck("W cannot move first", rv(call("move", [1, pos(2, 3), 0], 0, "W")))
ck("a move that flips nothing reverts", rv(call("move", [1, pos(0, 0), 0], 0, "B")))
ck("an occupied cell reverts", rv(call("move", [1, pos(3, 3), 0], 0, "B")))
call("move", [1, pos(2, 3), 0], 0, "B")                      # classic c4 opening: flips (3,3)
ck("the bracketed disc flips", cell(1, 3, 3) == 1 and cell(1, 2, 3) == 1 and M("mc", 1) == 1)
ck("stale ply retry reverts", rv(call("move", [1, pos(2, 3), 0], 0, "B")))
call("move", [1, pos(2, 2), 1], 0, "W")                      # flips (3,3)
ck("W's reply flips back", cell(1, 3, 3) == 2)
# pass is free; two passes end the game with a disc count
call("move", [1, PASS, 2], 0, "B")
ck("a single pass just alternates the turn", M("sd", 1) == 0 and M("mc", 1) == 3 and M("lp", 1) == 1)
b_ref = ref_new(); ref_move(b_ref, 2, 3, 1); ref_move(b_ref, 2, 2, 2)
n1 = sum(1 for v in b_ref.values() if v == 1); n2 = sum(1 for v in b_ref.values() if v == 2)
bB, bW = bal("B"), bal("W")
call("move", [1, PASS, 3], 0, "W")
want_wr = 1 if n1 > n2 else 2 if n2 > n1 else 3
ck(f"two passes end the game and count discs (B {n1} vs W {n2})", M("sd", 1) == 1 and M("wr", 1) == want_wr)
if want_wr == 1: ck("majority takes the pot", bal("B") == bB + 2 * STAKE)
elif want_wr == 2: ck("majority takes the pot", bal("W") == bW + 2 * STAKE)
else: ck("equal counts refund both", bal("B") == bB + STAKE and bal("W") == bW + STAKE)

# resign / abort / cancel (shared skeleton)
call("open", [2], STAKE, "B"); call("join", [2], STAKE, "W")
bW = bal("W"); call("resign", [2], 0, "B")
ck("resign concedes the pot", bal("W") == bW + 2 * STAKE and M("wr", 2) == 2)
call("open", [3], STAKE, "B"); bB = bal("B")
call("cancel", [3], 0, "B")
ck("cancel reclaims an un-joined stake", bal("B") == bB + STAKE)

# ---------------- DIFFERENTIAL: random legal games vs the python referee ----------------
import random as _r
rng = _r.Random(0x0E110)
mism = 0; wins = [0, 0, 0]; total_moves = 0
for kk in range(60):
    g = 1000 + kk
    call("open", [g], STAKE, "B"); call("join", [g], STAKE, "W")
    b = ref_new(); ply = 0; passes = 0
    bB, bW = bal("B"), bal("W")
    while True:
        k = 1 + ply % 2; who = "B" if k == 1 else "W"
        legal = ref_legal(b, k)
        if legal and rng.random() < 0.97:
            c, r = rng.choice(legal)
            rr = call("move", [g, pos(c, r), ply], 0, who)
            if H.rv(rr): mism += 1; break
            ref_move(b, c, r, k); passes = 0; total_moves += 1
            if cell(g, c, r) != k: mism += 1
        else:
            rr = call("move", [g, PASS, ply], 0, who)
            if H.rv(rr): mism += 1; break
            passes += 1
        ply += 1
        if passes == 2: break
        if M("sd", g) != 0: mism += 1; break
    # spot-check the FULL board against the reference at game end
    for c in range(8):
        for r in range(8):
            if cell(g, c, r) != b.get((c, r), 0): mism += 1
    n1 = sum(1 for v in b.values() if v == 1); n2 = sum(1 for v in b.values() if v == 2)
    want = 1 if n1 > n2 else 2 if n2 > n1 else 3
    if M("wr", g) != want or M("sd", g) != 1: mism += 1
    dB, dW = bal("B") - bB, bal("W") - bW
    if want == 1 and dB != 2 * STAKE: mism += 1
    if want == 2 and dW != 2 * STAKE: mism += 1
    if want == 3 and (dB != STAKE or dW != STAKE): mism += 1
    wins[want - 1] += 1
ck(f"DIFFERENTIAL: 60 random games / {total_moves} moves bytecode==python referee (mism={mism}, B {wins[0]} / W {wins[1]} / draw {wins[2]})",
   mism == 0 and wins[0] + wins[1] + wins[2] == 60 and total_moves > 2000)
ck("contract drains to zero", bal(H.cid) == 0)

H.finish("reversi.json", extra=f"move = {len(CODE['move'])} instr")
