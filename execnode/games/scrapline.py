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
Methods: open(g)[stake] · join(g)[stake] · move(g,enc,ply) · agree(g,result) · resign(g) · abort(g) · cancel(g).
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

SRC = dict(_s.SRC, move=MOVE)

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
                 "a1": A1, "a2": A2, "kh": KH},
        "index": {"cnt": 0, "list": LIST},
        "board": {"name": "mv", "base": MV_BASE, "cells": MAXMOVES, "stride": 10000},
        "board2": {"name": "mh", "base": MH_BASE, "cells": MAXMOVES, "stride": 10000},
        "addr": ["p1", "p2"],
    },
}


def build():
    return zkvmasm.assemble_contract(SRC)
