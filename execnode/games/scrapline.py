"""
Scrapline — zkVM port (doc/zk-execution-proofs.md). A 2-player staked AUTO-BATTLER with inventory
management, an ORIGINAL game in the roguelike auto-battler genre (inspired by LokiStriker's "From Rust To
Ash", which is all-rights-reserved and sold commercially — so NOTHING was ported: every item, name, number
and line of code here is original; game mechanics themselves are not copyrightable). The FULL rules engine
(draft offers, merges, the deterministic combat simulation) lives in the browser
(static/scrapline-engine.js); the CONTRACT is the exact Stormhold escrow: move log + seed heights +
mutual-agreement settle. See execnode/games/stormhold.py for the full design notes — this module reuses
its method sources verbatim (they are game-agnostic).

Why it fits: drafting is CONCURRENT (both players pick from their own seeded offer streams in any order —
the free-actor move log), each pick's offer derives from the seed height pinned by the player's PREVIOUS
move (kh for round 1), and once both finish drafting the combat resolves as a pure deterministic function
of the two builds — no more moves, both browsers compute the same winner, and the wager settles by
concede / mutual agree / refund-timeout.

Game fields: 1 nn 2 st 3 pt 4 p1 5 p2 6 sd 7 wr 8 mc 9 dl 10 list 11 a1 12 a2 13 kh.
Move log: mv[mc] at MV_BASE+mc · mh[mc]=(cursor+GAP)*4+side at MH_BASE+mc (stride 10000).

SOLO DAILY HIGHSCORES (`post`): the free solo gauntlet runs entirely client-side, but its DAILY runs are
deterministic from the shared date seed — so a score CLAIM = the packed list of draft choices, and any
browser can verify it by replaying the run through the engine. `post(day, score, n, a0..a7)` appends an
entry (caller, day, claimed score, n attempts, 8 words of 10 five-bit choices each = up to 80 attempts;
words stay < 2^50 so they survive JSON number decoding). The CONTRACT only checks the day against chain
time (±1) and bounds — VERIFICATION IS CLIENT-SIDE: every browser replays each claim and silently drops
entries whose replay doesn't reproduce the score (the chess-model trust shape: invalid data simply doesn't
render; posting costs a tx fee, which caps spam). Entries: global append log — cnt slot 4, elist field 60,
fields keyed by entry id e: 50 eday 51 eaddr 52 escore 53 en 54..58 ea0..ea4 62..64 ea5..ea7.
Methods: open(g)[stake] · join(g)[stake] · move(g,enc,ply) · agree(g,result) · resign(g) · abort(g) ·
cancel(g) · post(day,score,n,a0..a7).
"""
from execnode import zkvmasm
from execnode.games import stormhold as _s

NN, ST, PT, P1, P2, SD, WR, MC, DL, LIST, A1, A2, KH = 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13
MV_BASE, MH_BASE = _s.MV_BASE, _s.MH_BASE
MAXMOVES = 128            # 9 draft rounds x 2 players + slack — far below stormhold's 768
GAP = _s.GAP
MOVE_CLOCK = _s.MOVE_CLOCK

MOVE = _s.MOVE.replace(f"movi r6 {_s.MAXMOVES}", f"movi r6 {MAXMOVES}")
assert MOVE != _s.MOVE

ECNT_SLOT = 4
E_DAY, E_ADDR, E_SCORE, E_N, E_A = 50, 51, 52, 53, 54     # E_A..E_A+4 = packed words a0..a4
E_A2 = 62                                                 # E_A2..E_A2+2 = packed words a5..a7
ELIST = 60
MAX_ATT = 80                                              # 8 words x 10 five-bit attempts

# post(day, score, n, a0..a7): args preload r0..r7 = day, score, n, a0..a4; a5..a7 ride the ARG bus.
# Packed words are RE-FETCHED via ARG when stored (r3..r7 double as scratch).
POST = f"""
    movi r5 0
    lt r5 r0
    require r5              ; day > 0
    movi r5 4096
    mov r6 r1
    lt r6 r5
    require r6              ; claimed score sane (real check is the client replay)
    movi r5 0
    lt r5 r2
    require r5              ; n > 0
    movi r5 {MAX_ATT + 1}
    mov r6 r2
    lt r6 r5
    require r6              ; n <= {MAX_ATT}
    ctx r5 time
    movi r6 86400
    divmodw r5 r6           ; r5 = today (UTC day index)
    mov r6 r5
    movi r7 1
    add r6 r7
    mov r7 r0
    lt r6 r7
    notb r6
    require r6              ; !(today+1 < day)
    mov r6 r0
    movi r7 1
    add r6 r7
    mov r7 r5
    lt r6 r7
    notb r6
    require r6              ; !(day+1 < today)
    movi r4 {ECNT_SLOT}
    sload r3 r4             ; r3 = e (entry id)
    slot r4 {E_DAY} r3
    sstore r4 r0
    ctx r5 caller
    slot r4 {E_ADDR} r3
    sstore r4 r5
    slot r4 {E_SCORE} r3
    sstore r4 r1
    slot r4 {E_N} r3
    sstore r4 r2
    movi r5 3
    arg r6 r5
    slot r4 {E_A} r3
    sstore r4 r6
    movi r5 4
    arg r6 r5
    slot r4 {E_A + 1} r3
    sstore r4 r6
    movi r5 5
    arg r6 r5
    slot r4 {E_A + 2} r3
    sstore r4 r6
    movi r5 6
    arg r6 r5
    slot r4 {E_A + 3} r3
    sstore r4 r6
    movi r5 7
    arg r6 r5
    slot r4 {E_A + 4} r3
    sstore r4 r6
    movi r5 8
    arg r6 r5
    slot r4 {E_A2} r3
    sstore r4 r6
    movi r5 9
    arg r6 r5
    slot r4 {E_A2 + 1} r3
    sstore r4 r6
    movi r5 10
    arg r6 r5
    slot r4 {E_A2 + 2} r3
    sstore r4 r6
    slot r4 {ELIST} r3
    sstore r4 r3            ; elist[e] = e (enum key; raw value, 0 for the first entry is fine)
    movi r4 {ECNT_SLOT}
    mov r5 r3
    movi r6 1
    add r5 r6
    sstore r4 r5            ; cnt++
    ret r3
"""

SRC = dict(_s.SRC, move=MOVE, post=POST)

_G = lambda f: {"field": f, "index": "games"}
_E = lambda f: {"field": f, "index": "entries"}
ABI = {
    "open": {"args": ["gameId"], "value": True},
    "join": {"args": ["gameId"], "value": True},
    "move": {"args": ["gameId", "enc", "ply"]},
    "agree": {"args": ["gameId", "result"]},
    "resign": {"args": ["gameId"]},
    "abort": {"args": ["gameId"]},
    "cancel": {"args": ["gameId"]},
    "post": {"args": ["day", "score", "n", "a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7"]},
    "_view": {
        "maps": {"nn": _G(NN), "st": _G(ST), "pt": _G(PT), "p1": _G(P1), "p2": _G(P2), "sd": _G(SD),
                 "wr": _G(WR), "mc": _G(MC), "dl": _G(DL), "a1": _G(A1), "a2": _G(A2), "kh": _G(KH),
                 "eday": _E(E_DAY), "eaddr": _E(E_ADDR), "escore": _E(E_SCORE), "en": _E(E_N),
                 "ea0": _E(E_A), "ea1": _E(E_A + 1), "ea2": _E(E_A + 2), "ea3": _E(E_A + 3), "ea4": _E(E_A + 4),
                 "ea5": _E(E_A2), "ea6": _E(E_A2 + 1), "ea7": _E(E_A2 + 2)},
        "indexes": {"games": {"cnt": 0, "list": LIST}, "entries": {"cnt": ECNT_SLOT, "list": ELIST}},
        "board": {"name": "mv", "base": MV_BASE, "cells": MAXMOVES, "stride": 10000, "index": "games"},
        "board2": {"name": "mh", "base": MH_BASE, "cells": MAXMOVES, "stride": 10000, "index": "games"},
        "addr": ["p1", "p2", "eaddr"],
    },
}


def build():
    return zkvmasm.assemble_contract(SRC)
