"""
Connect Four — zkVM port (doc/zk-execution-proofs.md). PvP staked board game on a 7-wide × 6-tall grid:
players drop into a column, the piece falls to the lowest empty row, and the contract detects any four in a
row (horizontal / vertical / both diagonals) and pays the pot; a full board refunds both. Same PvP skeleton
+ per-cell board fields as tictactoe (execnode/games/tictactoe.py); only the move (column-drop + 4-in-a-row)
differs. Board cell = row*7 + col; bottom row = 0.

Methods: open(g)[stake] · join(g)[stake] · move(g,col,ply) · resign(g) · abort(g) · cancel(g).
"""
from execnode import zkvmasm
from execnode.games import _lib
from execnode.games import tictactoe as _t   # reuse the identical open/join/resign/abort/cancel skeleton

NN, ST, PT, P1, P2, SD, WR, MC, DL, LIST = 1, 2, 3, 4, 5, 6, 7, 8, 9, 10

# ---- free DAILY CHALLENGE board (provable solo-vs-bot run, faucet-rewarded) ------------------------
# Fields sit at 1000+ so they can never collide with the game fields or the per-cell board fields, which
# are keyed by gameId. The board itself is the SHARED one every provable game uses (_lib.daily_post /
# daily_anchor); the run is replayed off-chain by static/board-daily.js against the day's anchor, so the
# chain only ever stores a claim — never the rules.
DCNT_SLOT, ECNT_SLOT = 1000, 1001
E_DAY, E_ADDR, E_SCORE, E_N = 1010, 1011, 1012, 1013
E_TS = 1014                               # UTC-seconds post-time (board shows day + time)
ELIST, EW_BASE = 1020, 1030
A_H, A_V, DLIST = 1050, 1051, 1052
DAILY_WORDS = 3                                    # ceil(42 moves / 16 per word) at 3 bits/move
DAILY_MAX_N = 42
BD_BASE = 20
W, H = 7, 6
CELLS = W * H                                          # 42
STRIDE = 64                                            # frontend key: bd[g*64 + cell]


def _quads():
    """Every four-in-a-row on the 7×6 grid (cell = row*W + col)."""
    q = []
    for r in range(H):
        for c in range(W):
            if c + 3 < W:
                q.append([r * W + c + i for i in range(4)])               # horizontal
            if r + 3 < H:
                q.append([(r + i) * W + c for i in range(4)])             # vertical
            if r + 3 < H and c + 3 < W:
                q.append([(r + i) * W + c + i for i in range(4)])         # diag up-right
            if r + 3 < H and c - 3 >= 0:
                q.append([(r + i) * W + c - i for i in range(4)])         # diag up-left
    return q


def _wincheck():
    """r6 = number of completed 4-in-a-row lines through the current mark (r2); g in r0. jnz r6 -> win."""
    out = ["movi r6 0"]
    for quad in _quads():
        parts = []
        for i, cell in enumerate(quad):
            reg = "r4" if i == 0 else "r5"
            parts += [f"movi {reg} {(BD_BASE + cell) << 32}", f"add {reg} r0", f"sload {reg} {reg}",
                      f"eq {reg} r2"]
            if i > 0:
                parts.append("mul r4 r5")
        parts.append("add r6 r4")
        out += parts
    return "\n".join(out)


def _drop():
    """Branchless column-drop: find the lowest empty row in col (r1), leaving the target cell in r7. found in
    r3. Per row, sel = empty·(1-found); target += sel·cell; found += sel — once found, later sels are 0."""
    out = ["movi r3 0", "movi r7 0"]
    for row in range(H):
        base = (BD_BASE + row * W) << 32
        out += [f"movi r4 {base}", "movi r5 4294967296", "mul r5 r1", "add r4 r5", "add r4 r0",
                "sload r5 r4", "nez r5", "notb r5",                       # r5 = (cell empty)
                "movi r6 1", "sub r6 r3", "mul r5 r6",                    # r5 = empty·(1-found) = sel
                f"movi r6 {row * W}", "add r6 r1", "mul r6 r5", "add r7 r6",   # target += sel·(row*W+col)
                "add r3 r5"]                                             # found += sel
    out.append("require r3")                                            # column not full
    return "\n".join(out)


MOVE = f"""
    slot r4 1 r0
    sload r5 r4
    movi r6 2
    eq r5 r6
    require r5
    slot r4 6 r0
    sload r5 r4
    nez r5
    notb r5
    require r5
    mov r5 r1
    movi r6 {W}
    lt r5 r6
    require r5
    slot r4 8 r0
    sload r3 r4
    mov r5 r3
    eq r5 r2
    require r5
    mov r5 r3
    movi r6 2
    divmod r5 r6
    ctx r6 caller
    movi r4 4
    add r4 r7
    movi r5 4294967296
    mul r4 r5
    add r4 r0
    sload r5 r4
    eq r5 r6
    require r5
    movi r5 1
    add r7 r5
    mov r2 r7
{_drop()}
    movi r4 {BD_BASE << 32}
    movi r5 4294967296
    mul r5 r7
    add r4 r5
    add r4 r0
    sstore r4 r2
    slot r4 8 r0
    sload r5 r4
    movi r6 1
    add r5 r6
    sstore r4 r5
{_wincheck()}
    jnz r6 @won
    slot r4 8 r0
    sload r5 r4
    movi r6 {CELLS}
    eq r5 r6
    jnz r5 @full
    jmp @done
won:
    slot r4 3 r0
    sload r5 r4
    ctx r6 caller
    pay r6 r5
    slot r4 7 r0
    sstore r4 r2
    slot r4 6 r0
    movi r5 1
    sstore r4 r5
    slot r4 3 r0
    movi r5 0
    sstore r4 r5
    jmp @done
full:
    slot r4 2 r0
    sload r5 r4
    slot r4 4 r0
    sload r6 r4
    pay r6 r5
    slot r4 5 r0
    sload r6 r4
    pay r6 r5
    slot r4 7 r0
    movi r5 3
    sstore r4 r5
    slot r4 6 r0
    movi r5 1
    sstore r4 r5
    slot r4 3 r0
    movi r5 0
    sstore r4 r5
done:
    ret r0
"""

POST = _lib.daily_post(ECNT_SLOT, E_DAY, E_ADDR, E_SCORE, E_N, ELIST, EW_BASE, DAILY_WORDS,
                       max_n=DAILY_MAX_N, max_score=2000, e_ts=E_TS)
ANCHOR = _lib.daily_anchor(A_H, A_V, DCNT_SLOT, DLIST)

SRC = {
    "post": POST, "anchor": ANCHOR,"open": _t.SRC["open"], "join": _t.SRC["join"], "move": MOVE,
       "resign": _t.SRC["resign"], "abort": _t.SRC["abort"], "cancel": _t.SRC["cancel"]}

ABI = {
    "post": {"args": _lib.daily_post_abi(DAILY_WORDS)},
    "anchor": {"args": ["day"]},
    "open": {"args": ["gameId"], "value": True},
    "join": {"args": ["gameId"], "value": True},
    "move": {"args": ["gameId", "col", "ply"]},
    "resign": {"args": ["gameId"]},
    "abort": {"args": ["gameId"]},
    "cancel": {"args": ["gameId"]},
    "_view": {
        "maps": {"nn": NN, "st": ST, "pt": PT, "p1": P1, "p2": P2, "sd": SD, "wr": WR, "mc": MC, "dl": DL,
                 "eday": {"field": E_DAY, "index": "entries"}, "eaddr": {"field": E_ADDR, "index": "entries"},
                 "escore": {"field": E_SCORE, "index": "entries"}, "en": {"field": E_N, "index": "entries"},
                 "ets": {"field": E_TS, "index": "entries"},
                 **{f"ew{k}": {"field": EW_BASE + k, "index": "entries"} for k in range(DAILY_WORDS)},
                 "ah": {"field": A_H, "index": "days"}, "av": {"field": A_V, "index": "days"},},
        "index": {"cnt": 0, "list": LIST},
        "indexes": {"entries": {"cnt": ECNT_SLOT, "list": ELIST},
                    "days": {"cnt": DCNT_SLOT, "list": DLIST}},
        "board": {"name": "bd", "base": BD_BASE, "cells": CELLS, "stride": STRIDE},
        "addr": ["p1", "p2", "eaddr"],
    },
}


def build():
    return zkvmasm.assemble_contract(SRC)
