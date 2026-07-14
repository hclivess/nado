# tests/test_connect4_contract.py — build + exercise the CONNECT FOUR wager contract (stackvm).
#
# Same fully-on-chain-refereed PvP pattern as tic-tac-toe (vmasm.pvp_methods skeleton): move() checks
# turn + gravity ON-CHAIN, drops the disc into the lowest free row of the column, detects four-in-a-row
# (horizontal / vertical / both diagonals) and pays the pot instantly; a full 7x6 board (42 plies) with
# no line refunds both stakes.
#
# BOARD ADDRESSING (the padding trick): cell (col, row) lives at bd[g*128 + (col+1)*10 + (row+1)] with
# col 0..6, row 0..5 (row 0 = bottom). Probes past the edge land on never-written padding addresses (the
# 10-stride leaves row slots 0 and 7..9 and column slots 0 and 8+ permanently empty, and the ±22-offset
# bleed into a neighbour game's 128-block only touches its own padding) — so the win scan needs NO
# bounds checks: an out-of-board probe just reads 0.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vmasm import (P, A, LD, ST, SETR, R, CALLER, CURSOR,
                   ADD, SUB, MUL, MOD, EQ, GT, GTE, LT, LTE, NOT, AND, OR, REQ, PAY, HALT,
                   pvp_methods, Harness)

WINDOW = 300          # ~30 min move clock
COLS, ROWS = 7, 6

CODE = dict(pvp_methods(WINDOW))

def _addr(dc, dr):
    """push bd-load of cell (col + dc, row + dr) — col from ARG 1, row from scratch 'row'."""
    return (A(0) + P(128) + MUL
            + A(1) + P(1 + dc) + ADD + P(10) + MUL + ADD
            + R("row") + P(1 + dr) + ADD + ADD + LD("bd"))

def _probe(dc, dr):
    """push 1 iff the cell at offset (dc, dr) holds my mark k."""
    return _addr(dc, dr) + R("k") + EQ

def _dir(dx, dy, w1, w2, w3, w4, w5, w6):
    """push 1 iff this direction (both ways) has >= 3 more of my mark in a row (scratch names given)."""
    return (SETR(w1, _probe(dx, dy))
            + SETR(w2, R(w1) + _probe(2 * dx, 2 * dy) + AND)
            + SETR(w3, R(w2) + _probe(3 * dx, 3 * dy) + AND)
            + SETR(w4, _probe(-dx, -dy))
            + SETR(w5, R(w4) + _probe(-2 * dx, -2 * dy) + AND)
            + SETR(w6, R(w5) + _probe(-3 * dx, -3 * dy) + AND)
            + R(w1) + R(w2) + ADD + R(w3) + ADD + R(w4) + ADD + R(w5) + ADD + R(w6) + ADD
            + P(3) + GTE)

def _cell_at_row(r):
    """push 1 iff cell (col, r) is occupied."""
    return (A(0) + P(128) + MUL
            + A(1) + P(1) + ADD + P(10) + MUL + ADD
            + P(r + 1) + ADD + LD("bd") + P(0) + EQ + NOT)

_gravity = _cell_at_row(0)
for _r in range(1, ROWS):
    _gravity = _gravity + _cell_at_row(_r) + ADD

CODE["move"] = (
    A(0) + LD("nn") + P(2) + EQ + REQ
    + A(0) + LD("sd") + NOT + REQ
    + A(1) + P(0) + GTE + REQ + A(1) + P(COLS - 1) + LTE + REQ
    + A(2) + A(0) + LD("mc") + EQ + REQ                     # PLY BINDING (the chess retry-race lesson)
    + CALLER + A(0) + LD("p1") + EQ + A(0) + LD("mc") + P(2) + MOD + P(0) + EQ + AND
    + CALLER + A(0) + LD("p2") + EQ + A(0) + LD("mc") + P(2) + MOD + P(1) + EQ + AND
    + OR + REQ
    + SETR("k", P(1) + A(0) + LD("mc") + P(2) + MOD + ADD)
    + SETR("row", _gravity)
    + R("row") + P(ROWS) + LT + REQ                          # column not full
    # place the disc
    + A(0) + P(128) + MUL + A(1) + P(1) + ADD + P(10) + MUL + ADD + R("row") + P(1) + ADD + ADD
        + R("k") + ST("bd")
    + A(0) + A(0) + LD("mc") + P(1) + ADD + ST("mc")
    + A(0) + CURSOR + P(WINDOW) + ADD + ST("dl")
    # w = four-in-a-row through the placed cell, any of the 4 directions
    + SETR("w", _dir(1, 0, "a", "b", "c", "d", "e", "f")
            + _dir(0, 1, "a", "b", "c", "d", "e", "f") + OR
            + _dir(1, 1, "a", "b", "c", "d", "e", "f") + OR
            + _dir(1, -1, "a", "b", "c", "d", "e", "f") + OR)
    # d = board full (42 plies) and no win
    + SETR("dr", A(0) + LD("mc") + P(COLS * ROWS) + EQ + P(1) + R("w") + SUB + MUL)
    # payouts: winner (the caller) takes the pot; a draw refunds each stake
    + CALLER + A(0) + LD("pt") + R("w") + MUL + PAY
    + A(0) + LD("p1") + A(0) + LD("st") + R("dr") + MUL + PAY
    + A(0) + LD("p2") + A(0) + LD("st") + R("dr") + MUL + PAY
    + A(0) + R("k") + R("w") + MUL + P(3) + R("dr") + MUL + ADD + ST("wr")
    + A(0) + R("w") + R("dr") + ADD + ST("sd")
    + A(0) + A(0) + LD("pt") + P(1) + R("w") + R("dr") + ADD + SUB + MUL + ST("pt")
    + HALT)


# ---------------- PYTHON REFERENCE ----------------
def ref_drop(board, col, k):
    """board: dict (col,row)->k. Returns row or None if full."""
    for r in range(ROWS):
        if (col, r) not in board:
            board[(col, r)] = k
            return r
    return None

def ref_win(board, col, row, k):
    for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
        n = 1
        for sgn in (1, -1):
            s = 1
            while board.get((col + sgn * s * dx, row + sgn * s * dy)) == k:
                n += 1; s += 1
        if n >= 4:
            return True
    return False


# ---------------- TESTS ----------------
H = Harness(CODE, accounts=("X", "O", "EVE"), cursor=100, nonce="c4")
ck, call, bal, M, rv = H.ck, H.call, H.bal, H.M, H.rv
STAKE = 10**9

def cell(g, c, r): return M("bd", g * 128 + (c + 1) * 10 + (r + 1))

# X wins with a vertical stack in column 3
call("open", [1], STAKE, "X"); call("join", [1], STAKE, "O")
ck("pot escrows both stakes", M("pt", 1) == 2 * STAKE and bal(H.cid) == 2 * STAKE)
ck("O cannot move first", rv(call("move", [1, 3, 0], 0, "O")))
ck("column out of range reverts", rv(call("move", [1, 7, 0], 0, "X")))
seq = [(3, "X"), (4, "O"), (3, "X"), (4, "O"), (3, "X"), (5, "O")]
for ply, (col, who) in enumerate(seq): call("move", [1, col, ply], 0, who)
ck("gravity stacks discs bottom-up", cell(1, 3, 0) == 1 and cell(1, 3, 1) == 1 and cell(1, 3, 2) == 1 and cell(1, 4, 1) == 2)
ck("stale ply retry reverts", rv(call("move", [1, 0, 3], 0, "O")))
bX = bal("X")
call("move", [1, 3, 6], 0, "X")                             # fourth in the column
ck("X's vertical four pays the pot INSTANTLY", bal("X") == bX + 2 * STAKE and M("wr", 1) == 1 and M("sd", 1) == 1 and M("pt", 1) == 0)
ck("moving after the win reverts", rv(call("move", [1, 0, 7], 0, "O")))

# O wins with a horizontal row
call("open", [2], STAKE, "X"); call("join", [2], STAKE, "O")
seq = [(0, "X"), (1, "O"), (0, "X"), (2, "O"), (1, "X"), (3, "O"), (5, "X")]
for ply, (col, who) in enumerate(seq): call("move", [2, col, ply], 0, who)
bO = bal("O")
call("move", [2, 4, 7], 0, "O")                             # O: 1,2,3,4 on the bottom row
ck("O's horizontal four pays O the pot", bal("O") == bO + 2 * STAKE and M("wr", 2) == 2)

# diagonal win (up-right): X at (0,0) (1,1) (2,2) (3,3)
call("open", [3], STAKE, "X"); call("join", [3], STAKE, "O")
seq = [(0, "X"), (1, "O"), (1, "X"), (2, "O"), (2, "X"), (3, "O"), (2, "X"), (3, "O"), (3, "X"), (6, "O")]
for ply, (col, who) in enumerate(seq): call("move", [3, col, ply], 0, who)
bX = bal("X")
call("move", [3, 3, 10], 0, "X")
ck("X's up-right diagonal pays the pot", bal("X") == bX + 2 * STAKE and M("wr", 3) == 1)

# full column rejected
call("open", [4], STAKE, "X"); call("join", [4], STAKE, "O")
for ply in range(6): call("move", [4, 0, ply], 0, "X" if ply % 2 == 0 else "O")
ck("a full column reverts", rv(call("move", [4, 0, 6], 0, "X")))

# edge probes never wrap: a piece at col 6 must not "see" col 0 discs (10-stride padding)
call("open", [5], STAKE, "X"); call("join", [5], STAKE, "O")
seq = [(6, "X"), (0, "O"), (6, "X"), (0, "O"), (6, "X"), (1, "O")]
for ply, (col, who) in enumerate(seq): call("move", [5, col, ply], 0, who)
ck("edge columns don't wrap around", M("sd", 5) == 0)

# resign / abort / cancel (the shared pvp skeleton)
bO = bal("O"); call("resign", [5], 0, "X")
ck("resign concedes the pot", bal("O") == bO + 2 * STAKE and M("wr", 5) == 2)
call("open", [6], STAKE, "X"); call("join", [6], STAKE, "O")
H.cursor += WINDOW + 1
bX, bO = bal("X"), bal("O")
call("abort", [6], 0, "EVE")
ck("abort after the deadline refunds both", bal("X") == bX + STAKE and bal("O") == bO + STAKE and M("wr", 6) == 3)
call("open", [7], STAKE, "X"); bX = bal("X")
call("cancel", [7], 0, "X")
ck("cancel reclaims an un-joined stake", bal("X") == bX + STAKE)

# ---------------- DIFFERENTIAL: random legal games vs the python referee ----------------
import random as _r
rng = _r.Random(0xC4C4)
mism = 0; wins = [0, 0, 0]
for k in range(200):
    g = 1000 + k
    call("open", [g], STAKE, "X"); call("join", [g], STAKE, "O")
    board = {}; ply = 0
    bX, bO = bal("X"), bal("O")
    while True:
        who = "X" if ply % 2 == 0 else "O"; mark = 1 + ply % 2
        options = [c for c in range(COLS) if (c, ROWS - 1) not in board]
        if not options: break
        col = rng.choice(options)
        r = call("move", [g, col, ply], 0, who)
        if H.rv(r): mism += 1; break
        row = ref_drop(board, col, mark); ply += 1
        if cell(g, col, row) != mark: mism += 1
        if ref_win(board, col, row, mark):
            if M("wr", g) != mark or M("sd", g) != 1: mism += 1
            wins[mark - 1] += 1; break
        if ply == COLS * ROWS:
            if M("wr", g) != 3 or M("sd", g) != 1: mism += 1
            wins[2] += 1; break
        if M("sd", g) != 0: mism += 1; break
    dX, dO = bal("X") - bX, bal("O") - bO
    if M("wr", g) == 1 and dX != 2 * STAKE: mism += 1
    if M("wr", g) == 2 and dO != 2 * STAKE: mism += 1
    if M("wr", g) == 3 and (dX != STAKE or dO != STAKE): mism += 1
ck(f"DIFFERENTIAL: 200 random games bytecode==python referee (mism={mism}, X {wins[0]} / O {wins[1]} / draw {wins[2]})",
   mism == 0 and wins[0] > 60 and wins[1] > 40)
call("resign", [4], 0, "O")                                  # the full-column fixture was left mid-game
ck("contract drains to zero", bal(H.cid) == 0)

H.finish("connect4.json", extra=f"move = {len(CODE['move'])} instr")
