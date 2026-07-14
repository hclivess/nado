"""
Chess — zkVM port (doc/zk-execution-proofs.md). Correspondence-style staked chess: the board + full legality
live in the browser (a perft-verified engine); the CONTRACT is an escrow + move recorder + a mutual-agreement
settle. Two players stake equally; each move records its encoding on-chain (from + to*64 + promo*4096) so the
whole game is auditable; the result settles when BOTH players `agree` on it (1 white, 2 black, 3 draw). A
stall/dispute refunds both. Ported from the deleted stackvm contract.

Game fields: 1 nn 2 st 3 pt 4 p1 5 p2 6 sd 7 wr 8 mc 9 dl 10 a1 11 a2 12 list.  Move history: field
MV_BASE(20)+mc keyed by gameId → the frontend reads mv[g*10000 + mc] (view stride 10000). Scratch field 30.
Methods: open(g)[stake] · join(g)[stake] · move(g,enc,ply) · agree(g,result) · resign(g) · abort(g) · cancel(g).
"""
from execnode import zkvmasm
from execnode.games import tictactoe as _t

NN, ST, PT, P1, P2, SD, WR, MC, DL, LIST, A1, A2 = 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12
MV_BASE = 20
SC = 30
MAXMOVES = 512


def _s(i):
    return (SC << 32) | i


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
    movi r5 0
    lt r5 r1
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
    movi r4 {MV_BASE << 32}
    movi r5 4294967296
    mul r5 r3
    add r4 r5
    add r4 r0
    sstore r4 r1
    slot r4 8 r0
    movi r5 1
    add r3 r5
    sstore r4 r3
    slot r4 9 r0
    ctx r5 cursor
    movi r6 14400
    add r5 r6
    sstore r4 r5
    ret r0
"""

# agree(g, result): record the caller's claimed result into a1 (p1) or a2 (p2); when a1==a2>0 the game
# settles — winner gets the pot (or a draw refunds each stake).
AGREE = f"""
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
    movi r5 0
    lt r5 r1
    require r5
    movi r6 3
    mov r5 r1
    lt r6 r5
    notb r6
    require r6
    ctx r2 caller
    slot r4 4 r0
    sload r5 r4
    mov r6 r2
    eq r6 r5
    slot r4 11 r0
    sload r7 r4
    movi r5 1
    sub r5 r6
    mul r7 r5
    mov r5 r1
    mul r5 r6
    add r7 r5
    slot r4 11 r0
    sstore r4 r7
    slot r4 5 r0
    sload r5 r4
    mov r6 r2
    eq r6 r5
    slot r4 12 r0
    sload r7 r4
    movi r5 1
    sub r5 r6
    mul r7 r5
    mov r5 r1
    mul r5 r6
    add r7 r5
    slot r4 12 r0
    sstore r4 r7
    slot r4 11 r0
    sload r5 r4
    slot r4 12 r0
    sload r6 r4
    mov r7 r5
    eq r7 r6
    mov r3 r5
    nez r3
    mul r7 r3
    movi r4 {_s(0)}
    sstore r4 r7
    movi r4 {_s(1)}
    sstore r4 r5
    slot r4 3 r0
    sload r2 r4
    slot r4 2 r0
    sload r3 r4
    mov r6 r5
    movi r4 1
    eq r6 r4
    mul r6 r2
    mov r4 r5
    movi r1 3
    eq r4 r1
    mul r4 r3
    add r6 r4
    mul r6 r7
    slot r4 4 r0
    sload r4 r4
    pay r4 r6
    movi r4 {_s(1)}
    sload r5 r4
    movi r4 {_s(0)}
    sload r7 r4
    mov r6 r5
    movi r4 2
    eq r6 r4
    mul r6 r2
    mov r4 r5
    movi r1 3
    eq r4 r1
    mul r4 r3
    add r6 r4
    mul r6 r7
    slot r4 5 r0
    sload r4 r4
    pay r4 r6
    movi r4 {_s(0)}
    sload r7 r4
    slot r4 6 r0
    sstore r4 r7
    movi r4 1
    sub r4 r7
    slot r5 3 r0
    sload r6 r5
    mul r6 r4
    sstore r5 r6
    slot r4 7 r0
    sload r6 r4
    movi r3 1
    sub r3 r7
    mul r6 r3
    movi r4 {_s(1)}
    sload r5 r4
    mul r5 r7
    add r6 r5
    slot r4 7 r0
    sstore r4 r6
    ret r0
"""

SRC = {"open": _t.SRC["open"], "join": _t.SRC["join"], "move": MOVE, "agree": AGREE,
       "resign": _t.SRC["resign"], "abort": _t.SRC["abort"], "cancel": _t.SRC["cancel"]}

ABI = {
    "open": {"args": ["gameId"], "value": True},
    "join": {"args": ["gameId"], "value": True},
    "move": {"args": ["gameId", "enc", "ply"]},
    "agree": {"args": ["gameId", "result"]},
    "resign": {"args": ["gameId"]},
    "abort": {"args": ["gameId"]},
    "cancel": {"args": ["gameId"]},
    "_view": {
        "maps": {"nn": NN, "st": ST, "pt": PT, "p1": P1, "p2": P2, "sd": SD, "wr": WR, "mc": MC, "dl": DL,
                 "a1": A1, "a2": A2},
        "index": {"cnt": 0, "list": LIST},
        "board": {"name": "mv", "base": MV_BASE, "cells": MAXMOVES, "stride": 10000},
        "addr": ["p1", "p2"],
    },
}


def build():
    return zkvmasm.assemble_contract(SRC)
