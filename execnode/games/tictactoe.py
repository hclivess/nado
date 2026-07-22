"""
Tic-Tac-Toe — zkVM port (doc/zk-execution-proofs.md). A PvP staked board game: two players stake, take
turns on-chain, the contract detects three-in-a-row and pays the pot instantly, and a full board refunds
both. Ported from the deleted stackvm contract. This is the PvP-board EXEMPLAR: connect4/reversi reuse the
same open/join/resign/abort/cancel skeleton + board scheme, differing only in board size + win detection.

2D board slots without stride overflow: each cell index is its OWN field (BD_BASE+cell), keyed by gameId —
slot = (BD_BASE+cell)*2^32 + g. So g stays a full 2^32 id and cells never collide. The exec node's view
decoder reconstructs the frontend's bd[g*16+cell] from these per-cell fields (a "board" view type).

Game fields: 1 nn(0/1/2) 2 st 3 pt 4 p1 5 p2 6 sd 7 wr(1/2/3) 8 mc(move count) 9 dl(deadline).
Board: fields 20..28 = cells 0..8 (mark 1=p1, 2=p2), keyed by gameId.  Index: slot 0 = count / field 10 list.
Methods: open(g)[stake] · join(g)[stake] · move(g,cell,ply) · resign(g) · abort(g) · cancel(g).
"""
from execnode import zkvmasm
from execnode.games import _lib

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
DAILY_WORDS = 1                                    # ceil(9 moves / 12 per word) at 4 bits/move
DAILY_MAX_N = 9
BD_BASE = 20
CELLS = 9
STRIDE = 16                                            # frontend key convention: bd[g*STRIDE + cell]
LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]
MOVE_CLOCK = 300


def _bconst(cell):
    """The compile-time constant (BD_BASE+cell)<<32 — the field base of a board cell (add gameId for the slot)."""
    return (BD_BASE + cell) << 32


def _wincheck():
    """Generate the asm that sets r6=1 iff the just-placed mark (r2) completes any line (g in r0)."""
    out = ["movi r6 0"]
    for (a, b, c) in LINES:
        # line = (bd[a]==mark) AND (bd[b]==mark) AND (bd[c]==mark)
        out += [f"movi r4 {_bconst(a)}", "add r4 r0", "sload r4 r4", "eq r4 r2",
                f"movi r5 {_bconst(b)}", "add r5 r0", "sload r5 r5", "eq r5 r2", "mul r4 r5",
                f"movi r5 {_bconst(c)}", "add r5 r0", "sload r5 r5", "eq r5 r2", "mul r4 r5",
                "add r6 r4"]
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
    movi r6 {CELLS}
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
    movi r4 {BD_BASE << 32}
    movi r5 4294967296
    mul r5 r1
    add r4 r5
    add r4 r0
    sload r5 r4
    nez r5
    notb r5
    require r5
    sstore r4 r2
    slot r4 8 r0
    mov r5 r3
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
    "post": POST, "anchor": ANCHOR,
    "open": """
        ctx r1 value
        movi r2 0
        lt r2 r1
        require r2
        movi r2 0
        lt r2 r0
        require r2
        slot r4 1 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 2 r0
        sstore r4 r1
        slot r4 3 r0
        sstore r4 r1
        ctx r6 caller
        slot r4 4 r0
        sstore r4 r6
        slot r4 1 r0
        movi r5 1
        sstore r4 r5
        movi r4 0
        sload r5 r4
        slot r6 10 r5
        sstore r6 r0
        movi r3 1
        add r5 r3
        sstore r4 r5
        ret r0
    """,
    "join": """
        ctx r1 value
        slot r4 1 r0
        sload r5 r4
        movi r6 1
        eq r5 r6
        require r5
        slot r4 6 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 2 r0
        sload r5 r4
        eq r5 r1
        require r5
        ctx r6 caller
        slot r4 4 r0
        sload r5 r4
        eq r5 r6
        notb r5
        require r5
        slot r4 5 r0
        sstore r4 r6
        slot r4 3 r0
        sload r5 r4
        add r5 r1
        sstore r4 r5
        slot r4 1 r0
        movi r5 2
        sstore r4 r5
        slot r4 9 r0
        ctx r5 cursor
        movi r6 300
        add r5 r6
        sstore r4 r5
        ret r0
    """,
    "move": MOVE,
    "resign": """
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
        ctx r1 caller
        slot r4 4 r0
        sload r2 r4
        slot r4 5 r0
        sload r3 r4
        mov r5 r1
        eq r5 r2
        mov r6 r1
        eq r6 r3
        add r5 r6
        require r5
        slot r4 3 r0
        sload r5 r4
        mov r6 r1
        eq r6 r2
        jnz r6 @p1res
        pay r2 r5
        movi r7 1
        jmp @rdone
    p1res:
        pay r3 r5
        movi r7 2
    rdone:
        slot r4 7 r0
        sstore r4 r7
        slot r4 6 r0
        movi r5 1
        sstore r4 r5
        slot r4 3 r0
        movi r5 0
        sstore r4 r5
        ret r0
    """,
    "abort": """
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
        slot r4 9 r0
        sload r5 r4
        ctx r6 cursor
        lt r5 r6
        require r5
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
        ret r0
    """,
    "cancel": """
        slot r4 1 r0
        sload r5 r4
        movi r6 1
        eq r5 r6
        require r5
        ctx r1 caller
        slot r4 4 r0
        sload r5 r4
        eq r5 r1
        require r5
        slot r4 6 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 3 r0
        sload r5 r4
        pay r1 r5
        slot r4 6 r0
        movi r5 1
        sstore r4 r5
        slot r4 3 r0
        movi r5 0
        sstore r4 r5
        ret r0
    """,
}

ABI = {
    "post": {"args": _lib.daily_post_abi(DAILY_WORDS)},
    "anchor": {"args": ["day"]},
    "open": {"args": ["gameId"], "value": True},
    "join": {"args": ["gameId"], "value": True},
    "move": {"args": ["gameId", "cell", "ply"]},
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
