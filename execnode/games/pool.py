"""
Pool (8-ball) — zkVM port (doc/zk-execution-proofs.md). A 1v1 game of 8-ball, WITH OR WITHOUT A STAKE.
The full rules engine — a deterministic FIXED-POINT INTEGER physics simulation plus the 8-ball ruleset —
lives in the browser (static/pool-engine.js); the CONTRACT is the stormhold/chess escrow: an ordered move
log + a mutual-agreement settle. Every shot is one log entry (aim angle, power, English, called pocket,
and the ball-in-hand placement), so both browsers re-run the identical simulation from the identical
inputs and land on the identical table. No floats ever cross the wire — the log is integers only.

WHY IT NEEDS NO ON-CHAIN RULES: pool has no hidden information and no randomness after the rack. The rack
itself is seeded by `kh` (the join-time future block height, exactly as stormhold seeds its kingdom), so
neither player can pre-grind a favourable break. From there the game is a pure function of the move log,
which is what makes the chess trust model sound here: an illegal or misattributed move marks the game
corrupt in every honest client, play stops and the move-clock refund settles it.

FREE PLAY: `open` does NOT require a stake — value 0 opens a friendly game (st = pt = 0). Every other
method is unchanged; a 0-value pot simply pays 0 to the winner, so the whole escrow/settle path stays
byte-identical between staked and unstaked games. This is the ONLY difference from the stormhold escrow,
and it is deliberate: the stake is an option on the game, not a precondition for it.

Game fields: 1 nn 2 st 3 pt 4 p1 5 p2 6 sd 7 wr 8 mc 9 dl 10 list 11 a1 12 a2 13 kh 14 cfg.
Move log: mv[mc] = enc at field MV_BASE+mc · seed/actor: mh[mc] = (cursor+GAP)*4+side at MH_BASE+mc,
both keyed by gameId (frontend reads mv[g*10000+i] / mh[g*10000+i], view stride 10000).
Methods: open(g,cfg)[stake] · join(g)[stake] · move(g,enc,ply) · agree(g,result) · resign(g) · abort(g) ·
cancel(g).
"""
from execnode import zkvmasm
from execnode.games import tictactoe as _t
from execnode.games import chess as _c
from execnode.games import stormhold as _s

NN, ST, PT, P1, P2, SD, WR, MC, DL, LIST, A1, A2, KH = 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13
CFG = 14               # creator's game-configuration word — reserved (0 = standard 8-ball)
MV_BASE, MH_BASE = _s.MV_BASE, _s.MH_BASE
MAXMOVES = 256         # a full rack is ~30 shots; 256 leaves room for the longest safety battle
GAP = _s.GAP           # seed height = cursor + GAP (a future block at signing time)
MOVE_CLOCK = _s.MOVE_CLOCK

# ---- open(g, cfg) [value] -------------------------------------------------------------------------
# tictactoe's open (escrow, seat, lobby index) with the `value > 0` require REMOVED so a game can be
# opened for nothing, prefixed with the creator's cfg word. cfg is stored FIRST because the base body
# clobbers r1 with `ctx value`; a failed require later reverts the whole call, so the early write is safe.
# With value 0 the st/pt sstores write 0, which the VM treats as "absent" — every later read returns 0,
# `join` matches 0 == 0, and the settle paths pay out 0. Nothing else in the escrow changes.
_OPEN_FREE = _t.SRC["open"].replace(
    """        ctx r1 value
        movi r2 0
        lt r2 r1
        require r2
""",
    """        ctx r1 value
""", 1)
assert _OPEN_FREE != _t.SRC["open"], "tictactoe open changed shape — update pool's stake-optional splice"
assert "lt r2 r0" in _OPEN_FREE, "the gameId > 0 guard must survive the splice"

OPEN = f"""
        slot r4 {CFG} r0
        sstore r4 r1
""" + _OPEN_FREE

# join = tictactoe's join (stake match, seat, pot, nn=2) + pin the RACK seed height kh = cursor + GAP
# and give the breaker a full move clock for the first shot. Identical to stormhold's splice, minus the
# hidden-hands commit (pool has no hidden information).
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
assert JOIN != _t.SRC["join"], "tictactoe join changed shape — update pool's JOIN splice"

# move(g, enc, ply): stormhold's free-actor recorder verbatim, with pool's shorter log bound. The engine
# is the referee — it decides whose shot it is, so the contract only records (seed height, actor).
MOVE = _s.MOVE.replace(f"movi r6 {_s.MAXMOVES}", f"movi r6 {MAXMOVES}")
assert MOVE != _s.MOVE, "stormhold MOVE changed shape — update pool's MAXMOVES splice"

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
