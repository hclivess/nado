"""
Hexholm — zkVM port (doc/zk-execution-proofs.md). A 2-4 player STAKED island-settlement duel in the
classic hex-resource genre (mechanics only — every name, card title, rules text and artwork is original;
game mechanics are not copyrightable, names/text/art are, so none were copied). The FULL rules engine
(board production, the Marauder, trading, scrolls, badges) lives in the browser
(static/hexholm-engine.js); the CONTRACT is an escrow + N-SEAT lobby + ordered move recorder + an
all-alive-agree settle — the stormhold/chess model widened from 2 seats to 4.

Randomness: every recorded move pins a seed height rh = cursor + GAP (a FUTURE block nobody can predict
when the move signs); the engine derives dice, steals and scroll draws from HASH(bh(rh)+bh(rh+1)+…).
`join` by the LAST seat pins one more height KH for the whole board layout. HIDDEN scrolls use the
battleship/hold'em commit-reveal model: every seat commits H(secret) at open/join, a seat's draws are
salted with its secret (the multi-deck rule), and reveal(x) at game end lets every client verify every
claim — a false claim marks the game corrupt in honest clients and the settle paths take over.

The engine is the referee (free-actor log): the contract records WHO moved — mh[mc] = (cursor+GAP)*8 +
side (1..4) — and any illegal move marks the game corrupt client-side; the wager settles by resignation
(last seat standing takes the pot), unanimous agree(w) among unresigned seats, or the move-clock abort
(equal refund among alive seats, remainder to the caller).

Game fields: 1 nn 2 st 3 pt 4-7 p1..p4 8 sd 9 wr 10 mc 11 dl 12 cap 13 kh 14-17 c1..c4 18-21 a1..a4
22 rc 23-26 rs1..rs4 27-34 r1h r1l r2h r2l r3h r3l r4h r4l · lobby index: cnt at raw key 0, list 35.
Move log: mv[mc] at field 1000+mc · seed/actor mh[mc] at field 2000+mc, keyed by gameId (frontend reads
mv[g*10000+i] / mh[g*10000+i], stride 10000). Methods: open(g,cap,commit)[stake] · join(g,commit)[stake]
· move(g,enc,ply) · agree(g,w) · resign(g) · reveal(g,x) · leave(g) · cancel(g) · abort(g).
"""
from execnode import zkvmasm

NN, ST, PT = 1, 2, 3
P_BASE = 3                  # P_i at field 3+i (4..7)
SD, WR, MC, DL, CAP, KH = 8, 9, 10, 11, 12, 13
C_BASE = 13                 # C_i at field 13+i (14..17)
A_BASE = 17                 # A_i at field 17+i (18..21)
RC = 22
RS_BASE = 22                # RS_i at field 22+i (23..26)
RH_BASE, RL_BASE = 25, 26   # R_i hi at 25+2i (27,29,31,33), lo at 26+2i (28,30,32,34)
LIST = 35
MV_BASE, MH_BASE, MAXMOVES = 1000, 2000, 999
GAP, MOVE_CLOCK = 2, 14400
_W = 1 << 32
INV32 = 18446744065119617026    # field inverse of 2^32 (exact hi-half extraction, from stormhold)


def _f(field):              # constant field key base
    return field * _W


# caller's seat -> r2 (1..4, 0 = not seated); clobbers r4,r5,r6. `require_seated` adds the gate.
def _side(require_seated=True):
    body = "    ctx r6 caller\n"
    for i in (1, 2, 3, 4):
        body += f"""    slot r4 {P_BASE + i} r0
    sload r5 r4
    eq r5 r6
"""
        body += ("    mov r2 r5\n" if i == 1 else f"    movi r4 {i}\n    mul r5 r4\n    add r2 r5\n")
    if require_seated:
        body += "    movi r5 0\n    lt r5 r2\n    require r5\n"
    return body


_FULL = f"""    slot r4 {NN} r0
    sload r5 r4
    slot r4 {CAP} r0
    sload r6 r4
    eq r5 r6
    require r5
    movi r4 1
    lt r4 r6
    require r4
"""
_UNSETTLED = f"""    slot r4 {SD} r0
    sload r5 r4
    nez r5
    notb r5
    require r5
"""

# alive_i = (i <= CAP) * (1 - RS_i) -> r4 ; expects nothing, clobbers r4,r5,r6
def _alive(i):
    return f"""    slot r4 {CAP} r0
    sload r5 r4
    movi r6 {i}
    mov r4 r6
    lt r4 r5
    eq r6 r5
    add r4 r6
    slot r6 {RS_BASE + i} r0
    sload r5 r6
    movi r6 1
    sub r6 r5
    mul r4 r6
"""


OPEN = f"""    ctx r3 value
    movi r4 0
    lt r4 r3
    require r4
    movi r4 0
    lt r4 r0
    require r4
    slot r4 {NN} r0
    sload r5 r4
    nez r5
    notb r5
    require r5
    movi r4 1
    lt r4 r1
    require r4
    movi r4 5
    mov r5 r1
    lt r5 r4
    require r5
    slot r4 {CAP} r0
    sstore r4 r1
    slot r4 {C_BASE + 1} r0
    sstore r4 r2
    slot r4 {ST} r0
    sstore r4 r3
    slot r4 {PT} r0
    sstore r4 r3
    ctx r6 caller
    slot r4 {P_BASE + 1} r0
    sstore r4 r6
    slot r4 {NN} r0
    movi r5 1
    sstore r4 r5
    movi r4 0
    sload r5 r4
    slot r6 {LIST} r5
    sstore r6 r0
    movi r3 1
    add r5 r3
    sstore r4 r5
    ret r0
"""

JOIN = f"""    slot r4 {NN} r0
    sload r3 r4
    movi r5 0
    lt r5 r3
    require r5
    slot r4 {CAP} r0
    sload r6 r4
    mov r5 r3
    lt r5 r6
    require r5
{_UNSETTLED}    ctx r5 value
    slot r4 {ST} r0
    sload r6 r4
    eq r6 r5
    require r6
    ctx r6 caller
    slot r4 {P_BASE + 1} r0
    sload r5 r4
    eq r5 r6
    mov r2 r5
    slot r4 {P_BASE + 2} r0
    sload r5 r4
    eq r5 r6
    add r2 r5
    slot r4 {P_BASE + 3} r0
    sload r5 r4
    eq r5 r6
    add r2 r5
    slot r4 {P_BASE + 4} r0
    sload r5 r4
    eq r5 r6
    add r2 r5
    notb r2
    require r2
    movi r4 {_W}
    mul r4 r3
    movi r5 {_f(P_BASE + 1)}
    add r5 r4
    add r5 r0
    sstore r5 r6
    movi r5 {_f(C_BASE + 1)}
    add r5 r4
    add r5 r0
    sstore r5 r1
    ctx r5 value
    slot r4 {PT} r0
    sload r6 r4
    add r6 r5
    sstore r4 r6
    movi r5 1
    add r5 r3
    slot r4 {NN} r0
    sstore r4 r5
    slot r4 {CAP} r0
    sload r6 r4
    eq r6 r5
    notb r6
    jnz r6 @jdone
    slot r4 {KH} r0
    ctx r5 cursor
    movi r6 {GAP}
    add r5 r6
    sstore r4 r5
    slot r4 {DL} r0
    ctx r5 cursor
    movi r6 {MOVE_CLOCK}
    add r5 r6
    sstore r4 r5
jdone:
    ret r0
"""

MOVE = f"""{_FULL}{_UNSETTLED}    movi r5 0
    lt r5 r1
    require r5
    slot r4 {MC} r0
    sload r3 r4
    mov r5 r3
    eq r5 r2
    require r5
    mov r5 r3
    movi r6 {MAXMOVES}
    lt r5 r6
    require r5
{_side()}    movi r4 {_W}
    mul r4 r2
    movi r5 {_f(RS_BASE + 1) - _W}
    add r5 r4
    add r5 r0
    sload r6 r5
    nez r6
    notb r6
    require r6
    ctx r6 cursor
    movi r4 {GAP}
    add r6 r4
    movi r4 8
    mul r6 r4
    add r6 r2
    movi r4 {_W}
    mul r4 r3
    movi r5 {_f(MH_BASE)}
    add r5 r4
    add r5 r0
    sstore r5 r6
    movi r5 {_f(MV_BASE)}
    add r5 r4
    add r5 r0
    sstore r5 r1
    slot r4 {MC} r0
    movi r5 1
    add r5 r3
    sstore r4 r5
    slot r4 {DL} r0
    ctx r5 cursor
    movi r6 {MOVE_CLOCK}
    add r5 r6
    sstore r4 r5
    ret r0
"""

# agree(g, w): record the caller's vote; when every ALIVE seat's vote equals w, pay seat w the pot.
_AGREE_TERMS = ""
for i in (1, 2, 3, 4):
    _AGREE_TERMS += f"""    slot r4 {CAP} r0
    sload r6 r4
    movi r5 {i}
    mov r2 r5
    lt r2 r6
    eq r5 r6
    add r2 r5
    slot r4 {RS_BASE + i} r0
    sload r5 r4
    movi r4 1
    sub r4 r5
    mul r2 r4
    slot r4 {A_BASE + i} r0
    sload r5 r4
    eq r5 r1
    movi r4 1
    sub r4 r5
    mul r2 r4
    movi r4 1
    sub r4 r2
    mul r3 r4
"""
AGREE = f"""{_FULL}{_UNSETTLED}    movi r5 0
    lt r5 r1
    require r5
    slot r4 {CAP} r0
    sload r6 r4
    mov r5 r1
    lt r5 r6
    mov r3 r1
    eq r3 r6
    add r5 r3
    require r5
    movi r4 {_W}
    mul r4 r1
    movi r5 {_f(RS_BASE + 1) - _W}
    add r5 r4
    add r5 r0
    sload r6 r5
    nez r6
    notb r6
    require r6
{_side()}    movi r4 {_W}
    mul r4 r2
    movi r5 {_f(RS_BASE + 1) - _W}
    add r5 r4
    add r5 r0
    sload r6 r5
    nez r6
    notb r6
    require r6
    movi r5 {_f(A_BASE + 1) - _W}
    add r5 r4
    add r5 r0
    sstore r5 r1
    movi r3 1
{_AGREE_TERMS}    notb r3
    jnz r3 @adone
    movi r4 {_W}
    mul r4 r1
    movi r5 {_f(P_BASE + 1) - _W}
    add r5 r4
    add r5 r0
    sload r6 r5
    slot r4 {PT} r0
    sload r5 r4
    pay r6 r5
    movi r5 0
    sstore r4 r5
    slot r4 {WR} r0
    sstore r4 r1
    slot r4 {SD} r0
    movi r5 1
    sstore r4 r5
adone:
    ret r0
"""

# resign(g): set the caller's resigned flag; when only ONE seat remains alive it takes the whole pot.
_LAST_ALIVE = ""
for i in (1, 2, 3, 4):
    _LAST_ALIVE += _alive(i) + f"""    movi r5 {i}
    mul r5 r4
    add r3 r5
"""
RESIGN = f"""{_FULL}{_UNSETTLED}{_side()}    movi r4 {_W}
    mul r4 r2
    movi r5 {_f(RS_BASE + 1) - _W}
    add r5 r4
    add r5 r0
    sload r6 r5
    nez r6
    notb r6
    require r6
    movi r6 1
    sstore r5 r6
    movi r5 {_f(A_BASE + 1) - _W}
    add r5 r4
    add r5 r0
    movi r6 0
    sstore r5 r6
    slot r4 {RC} r0
    sload r5 r4
    movi r6 1
    add r5 r6
    sstore r4 r5
    slot r4 {CAP} r0
    sload r6 r4
    movi r3 1
    sub r6 r3
    eq r5 r6
    notb r5
    jnz r5 @rdone
    movi r3 0
{_LAST_ALIVE}    movi r4 {_W}
    mul r4 r3
    movi r5 {_f(P_BASE + 1) - _W}
    add r5 r4
    add r5 r0
    sload r6 r5
    slot r4 {PT} r0
    sload r5 r4
    pay r6 r5
    movi r5 0
    sstore r4 r5
    slot r4 {WR} r0
    sstore r4 r3
    slot r4 {SD} r0
    movi r5 1
    sstore r4 r5
rdone:
    ret r0
"""

# reveal(g, x): post the pre-committed secret once the game is decided; clients verify every hidden claim.
REVEAL = f"""{_FULL}{_side()}    movi r4 {_W}
    mul r4 r2
    movi r5 {_f(C_BASE + 1) - _W}
    add r5 r4
    add r5 r0
    sload r3 r5
    mov r6 r3
    nez r6
    require r6
    hash r5 <- r1
    eq r5 r3
    require r5
    mov r6 r1
    lo32 r6
    mov r5 r1
    sub r5 r6
    movi r3 {INV32}
    mul r5 r3
    movi r3 {_f(RH_BASE)}
    movi r4 {2 * _W}
    mul r4 r2
    add r3 r4
    add r3 r0
    sstore r3 r5
    movi r3 {_f(RL_BASE)}
    add r3 r4
    add r3 r0
    sstore r3 r6
    ret r0
"""

# leave(g): the LAST joiner steps out of a not-yet-full table and takes their stake back.
LEAVE = f"""    slot r4 {NN} r0
    sload r3 r4
    movi r5 1
    lt r5 r3
    require r5
    slot r4 {CAP} r0
    sload r6 r4
    mov r5 r3
    lt r5 r6
    require r5
{_UNSETTLED}    movi r4 {_W}
    mul r4 r3
    movi r5 {_f(P_BASE)}
    add r5 r4
    add r5 r0
    sload r6 r5
    ctx r2 caller
    eq r6 r2
    require r6
    slot r4 {ST} r0
    sload r6 r4
    pay r2 r6
    movi r2 0
    sstore r5 r2
    movi r5 {_f(C_BASE)}
    add r5 r4
    add r5 r0
    movi r2 0
    sstore r5 r2
    slot r4 {PT} r0
    sload r5 r4
    sub r5 r6
    sstore r4 r5
    slot r4 {NN} r0
    movi r5 1
    mov r6 r3
    sub r6 r5
    sstore r4 r6
    ret r0
"""

# cancel(g): the CREATOR dissolves a not-yet-full table; every seated stake refunds.
_CANCEL_REFUNDS = ""
for i in (1, 2, 3, 4):
    _CANCEL_REFUNDS += f"""    slot r4 {NN} r0
    sload r5 r4
    movi r6 {i}
    mov r4 r6
    lt r4 r5
    eq r6 r5
    add r4 r6
    notb r4
    jnz r4 @cskip{i}
    slot r4 {P_BASE + i} r0
    sload r6 r4
    slot r4 {ST} r0
    sload r5 r4
    pay r6 r5
cskip{i}:
"""
CANCEL = f"""    slot r4 {NN} r0
    sload r5 r4
    movi r6 0
    lt r6 r5
    require r6
    slot r4 {CAP} r0
    sload r6 r4
    lt r5 r6
    require r5
{_UNSETTLED}    ctx r6 caller
    slot r4 {P_BASE + 1} r0
    sload r5 r4
    eq r5 r6
    require r5
{_CANCEL_REFUNDS}    slot r4 {SD} r0
    movi r5 1
    sstore r4 r5
    slot r4 {WR} r0
    movi r5 5
    sstore r4 r5
    slot r4 {PT} r0
    movi r5 0
    sstore r4 r5
    ret r0
"""

# abort(g): after the move clock lapses, any seated caller dissolves the table — the pot splits equally
# among the ALIVE seats (resigners forfeited already), division remainder to the caller.
_ABORT_PAYS = ""
for i in (1, 2, 3, 4):
    _ABORT_PAYS += _alive(i) + f"""    notb r4
    jnz r4 @xskip{i}
    slot r4 {P_BASE + i} r0
    sload r6 r4
    pay r6 r3
xskip{i}:
"""
ABORT = f"""{_FULL}{_UNSETTLED}    slot r4 {DL} r0
    sload r5 r4
    ctx r6 cursor
    lt r5 r6
    require r5
{_side()}    slot r4 {CAP} r0
    sload r5 r4
    slot r4 {RC} r0
    sload r6 r4
    sub r5 r6
    slot r4 {PT} r0
    sload r3 r4
    divmod r3 r5
    ctx r6 caller
    pay r6 r7
{_ABORT_PAYS}    slot r4 {SD} r0
    movi r5 1
    sstore r4 r5
    slot r4 {WR} r0
    movi r5 5
    sstore r4 r5
    slot r4 {PT} r0
    movi r5 0
    sstore r4 r5
    ret r0
"""

# PROVABLE DAILY BOARD (static/provable.js + the _lib generator): the free 12-turn solo gauntlet posts
# its claim (the player's packed move list) here; every browser and the faucet distributor replay it
# (static/hexholm-bot.js verifyClaim) and drop entries that don't reproduce their score.
from execnode.games import _lib
ECNT_SLOT = 4
E_DAY, E_ADDR, E_SCORE, E_N, ELIST, EW_BASE = 50, 51, 52, 53, 60, 100
CLAIM_WORDS, MAX_MY = 150, 100                              # MUST match static/hexholm-bot.js
POST = _lib.daily_post(ECNT_SLOT, E_DAY, E_ADDR, E_SCORE, E_N, ELIST, EW_BASE, CLAIM_WORDS, MAX_MY)

SRC = {"open": OPEN, "join": JOIN, "move": MOVE, "agree": AGREE, "resign": RESIGN,
       "reveal": REVEAL, "leave": LEAVE, "cancel": CANCEL, "abort": ABORT, "post": POST}

_G = lambda f: {"field": f, "index": "games"}
_E = lambda f: {"field": f, "index": "entries"}
ABI = {
    "open": {"args": ["gameId", "cap", "commit"], "value": True},
    "join": {"args": ["gameId", "commit"], "value": True},
    "move": {"args": ["gameId", "enc", "ply"]},
    "agree": {"args": ["gameId", "w"]},
    "resign": {"args": ["gameId"]},
    "reveal": {"args": ["gameId", "x"]},
    "leave": {"args": ["gameId"]},
    "cancel": {"args": ["gameId"]},
    "abort": {"args": ["gameId"]},
    "post": {"args": _lib.daily_post_abi(CLAIM_WORDS)},
    "_view": {
        "maps": {"nn": _G(NN), "st": _G(ST), "pt": _G(PT), "p1": _G(4), "p2": _G(5), "p3": _G(6),
                 "p4": _G(7), "sd": _G(SD), "wr": _G(WR), "mc": _G(MC), "dl": _G(DL), "cap": _G(CAP),
                 "kh": _G(KH), "c1": _G(14), "c2": _G(15), "c3": _G(16), "c4": _G(17), "a1": _G(18),
                 "a2": _G(19), "a3": _G(20), "a4": _G(21), "rc": _G(RC), "rs1": _G(23), "rs2": _G(24),
                 "rs3": _G(25), "rs4": _G(26), "r1h": _G(27), "r1l": _G(28), "r2h": _G(29), "r2l": _G(30),
                 "r3h": _G(31), "r3l": _G(32), "r4h": _G(33), "r4l": _G(34),
                 "eday": _E(E_DAY), "eaddr": _E(E_ADDR), "escore": _E(E_SCORE), "en": _E(E_N)},
        "indexes": {"games": {"cnt": 0, "list": LIST}, "entries": {"cnt": ECNT_SLOT, "list": ELIST}},
        "board": {"name": "mv", "base": MV_BASE, "cells": MAXMOVES, "stride": 10000, "index": "games"},
        "board2": {"name": "mh", "base": MH_BASE, "cells": MAXMOVES, "stride": 10000, "index": "games"},
        "board3": {"name": "ew", "base": EW_BASE, "cells": CLAIM_WORDS, "stride": 10000, "index": "entries"},
        "addr": ["p1", "p2", "p3", "p4", "eaddr"],
    },
}


def build():
    return zkvmasm.assemble_contract(SRC)
