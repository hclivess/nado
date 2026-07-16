"""
Stormhold — zkVM port (doc/zk-execution-proofs.md). A 2-player staked DECK-BUILDER in the classic
Dominion-style genre (mechanics only — every name, card title and rules text is original; game mechanics
are not copyrightable, names/text/art are, so none were copied). The FULL rules engine (26 kingdom cards +
base cards, pending-decision stack, attacks/reactions) lives in the browser (static/stormhold-engine.js); the CONTRACT is an escrow + ordered move recorder + a
mutual-agreement settle — the chess model. What chess does NOT have is randomness: Dominion shuffles. Every
recorded move therefore pins a seed height rh = cursor + GAP (a FUTURE block nobody can predict when the
move is signed); any shuffle the engine performs while replaying move k draws Fisher-Yates randomness from
HASH(bh(rh_k) + bh(rh_k+1) + salt + i) — the shared cards.js chain-draw convention. `join` pins one more
height kh for the kingdom selection + both starting-deck shuffles. So the whole game — kingdom, every
shuffle, every draw — re-derives deterministically from the on-chain log + L1 block hashes, in any browser.

Unlike the strictly-alternating chess `move`, Stormhold turns are many moves long and attacks interpose the
OPPONENT's decisions (Militia discards, Moat reveals) mid-turn — so the contract records WHO moved instead
of enforcing whose turn it is: mh[mc] = (cursor+GAP)*4 + side (1=p1, 2=p2). The ENGINE is the referee: a
move by the wrong actor (or any illegal move) marks the game corrupt in every honest client, play stops,
and the move-clock refund path settles it — exactly chess's illegal-move trust model. The wager settles by
resignation / mutual `agree` on the result (1=p1, 2=p2, 3=draw: chess's agree, verbatim) / refund-timeout.

Game fields: 1 nn 2 st 3 pt 4 p1 5 p2 6 sd 7 wr 8 mc 9 dl 10 list 11 a1 12 a2 13 kh.
Move log: mv[mc] = enc at field MV_BASE+mc · seed/actor: mh[mc] = (cursor+GAP)*4+side at field MH_BASE+mc,
both keyed by gameId (frontend reads mv[g*10000+i] / mh[g*10000+i], view stride 10000). Scratch field 30.
Methods: open(g)[stake] · join(g)[stake] · move(g,enc,ply) · agree(g,result) · resign(g) · abort(g) · cancel(g).
"""
from execnode import zkvmasm
from execnode.games import tictactoe as _t
from execnode.games import chess as _c

NN, ST, PT, P1, P2, SD, WR, MC, DL, LIST, A1, A2, KH = 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13
CFG = 14               # creator's game configuration word: 26-bit kingdom-card mask (0 = random kingdom)
MV_BASE = 1000
MH_BASE = 2000
MAXMOVES = 768
GAP = 2                # seed height = cursor + GAP (a future block at signing time)
MOVE_CLOCK = 14400     # ~1 day at 6s blocks — correspondence pace, same as chess


# join = tictactoe's join (stake match, seat, pot, nn=2) + pin the kingdom seed height kh = cursor + GAP
# and give the opener a full move clock for the first turn.
JOIN = _t.SRC["join"].replace(
    """        slot r4 9 r0
        ctx r5 cursor
        movi r6 300
        add r5 r6
        sstore r4 r5
        ret r0""",
    f"""        slot r4 9 r0
        ctx r5 cursor
        movi r6 {MOVE_CLOCK}
        add r5 r6
        sstore r4 r5
        slot r4 {KH} r0
        ctx r5 cursor
        movi r6 {GAP}
        add r5 r6
        sstore r4 r5
        ret r0""")
assert JOIN != _t.SRC["join"], "tictactoe join changed shape — update dominion JOIN splice"

# move(g, enc, ply): r0=g r1=enc r2=ply. Caller may be EITHER player (the engine referees whose decision
# it is); the record keeps (seed height, actor) so replay is deterministic and misattribution impossible.
MOVE = f"""
    slot r4 {NN} r0
    sload r5 r4
    movi r6 2
    eq r5 r6
    require r5              ; both seats filled
    slot r4 {SD} r0
    sload r5 r4
    nez r5
    notb r5
    require r5              ; not settled
    movi r5 0
    lt r5 r1
    require r5              ; enc > 0 (0 is the storage-empty sentinel)
    slot r4 {MC} r0
    sload r3 r4             ; r3 = mc
    mov r5 r3
    eq r5 r2
    require r5              ; ply binding: this move plays at exactly mc
    mov r5 r3
    movi r6 {MAXMOVES}
    lt r5 r6
    require r5              ; log bounded
    ctx r6 caller
    slot r4 {P1} r0
    sload r5 r4
    eq r5 r6                ; r5 = caller==p1
    slot r4 {P2} r0
    sload r7 r4
    eq r7 r6                ; r7 = caller==p2
    mov r6 r5
    add r6 r7
    require r6              ; caller seated
    movi r6 2
    mul r7 r6
    add r5 r7               ; r5 = side (1 or 2)
    ctx r6 cursor
    movi r4 {GAP}
    add r6 r4
    movi r4 4
    mul r6 r4
    add r6 r5               ; r6 = (cursor+GAP)*4 + side  (never 0)
    movi r4 {MH_BASE << 32}
    movi r5 4294967296
    mul r5 r3
    add r4 r5
    add r4 r0
    sstore r4 r6            ; mh[mc]
    movi r4 {MV_BASE << 32}
    movi r5 4294967296
    mul r5 r3
    add r4 r5
    add r4 r0
    sstore r4 r1            ; mv[mc]
    slot r4 {MC} r0
    movi r5 1
    add r5 r3
    sstore r4 r5            ; mc++
    slot r4 {DL} r0
    ctx r5 cursor
    movi r6 {MOVE_CLOCK}
    add r5 r6
    sstore r4 r5            ; move clock rearmed
    ret r0
"""

# open(g, cfg): tictactoe's open (stake escrow, seat, lobby index) prefixed with ONE store — the creator's
# cfg word (26-bit kingdom mask, 0 = random). Stored FIRST because the base body clobbers r1 with `ctx
# value`; a failed require later reverts the whole call, so the early write is safe. Old games (and a
# cfg-less rematch) read slot 14 as 0 → random kingdom: fully back-compatible.
OPEN = """
        slot r4 14 r0
        sstore r4 r1
""" + _t.SRC["open"]

SRC = {"open": OPEN, "join": JOIN, "move": MOVE, "agree": _c.AGREE,
       "resign": _t.SRC["resign"], "abort": _t.SRC["abort"], "cancel": _t.SRC["cancel"]}

ABI = {
    "open": {"args": ["gameId", "cfg"], "value": True},
    "join": {"args": ["gameId"], "value": True},
    "move": {"args": ["gameId", "enc", "ply"]},
    "agree": {"args": ["gameId", "result"]},
    "resign": {"args": ["gameId"]},
    "abort": {"args": ["gameId"]},
    "cancel": {"args": ["gameId"]},
    "_view": {
        "maps": {"nn": NN, "st": ST, "pt": PT, "p1": P1, "p2": P2, "sd": SD, "wr": WR, "mc": MC, "dl": DL,
                 "a1": A1, "a2": A2, "kh": KH, "cfg": CFG},
        "index": {"cnt": 0, "list": LIST},
        "board": {"name": "mv", "base": MV_BASE, "cells": MAXMOVES, "stride": 10000},
        "board2": {"name": "mh", "base": MH_BASE, "cells": MAXMOVES, "stride": 10000},
        "addr": ["p1", "p2"],
    },
}


def build():
    return zkvmasm.assemble_contract(SRC)
