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
from execnode.games import _lib
from execnode.games import tictactoe as _t
from execnode.games import chess as _c

NN, ST, PT, P1, P2, SD, WR, MC, DL, LIST, A1, A2, KH = 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13
CFG = 14               # creator's game configuration word: 26-bit kingdom-card mask (0 = random kingdom)
C1, C2 = 15, 16        # hidden-hands commits H(secret) per seat (0 = classic open-hand game)
# revealed secrets, stored SPLIT into 32-bit halves (hi/lo): the JSON view coerces slot values to JS
# numbers, and a field-sized secret would lose precision past 2^53 — split halves survive exactly.
R1H, R2H, R1L, R2L = 17, 18, 19, 20
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
# join(g, commit): the joiner's hidden-hands commit rides as arg 2 (r1), stored before the base body
# (which clobbers r1 with `ctx value`). A hidden game needs BOTH commits nonzero; clients enforce the
# pairing (an opener who set c1 shows the game as hidden; an old client simply can't join it correctly —
# its join leaves c2 = 0 and every client then treats the game as OPEN-HAND, which both can still play).
JOIN = f"""
        slot r4 {C2} r0
        sstore r4 r1
""" + JOIN

# reveal(g, x): post the pre-committed secret once the game is decided — every client re-derives the whole
# hidden game and verifies every claim (engine verifyHidden). Requires: both seats filled, caller seated,
# caller committed (hidden game), and alghash(x) == commit. Storing into R1/R2 by seat; idempotent
# re-reveals just overwrite with the same value (a DIFFERENT x can't hash to the same commit).
REVEAL = f"""
    slot r4 {NN} r0
    sload r5 r4
    movi r6 2
    eq r5 r6
    require r5              ; both seats filled
    ctx r6 caller
    slot r4 {P1} r0
    sload r5 r4
    eq r5 r6                ; r5 = caller==p1
    slot r4 {P2} r0
    sload r7 r4
    eq r7 r6                ; r7 = caller==p2
    mov r2 r5
    add r2 r7
    require r2              ; caller seated
    movi r2 {C1 << 32}
    mul r2 r5
    movi r4 {C2 << 32}
    mul r4 r7
    add r2 r4
    add r2 r0               ; r2 = my commit's storage key
    sload r3 r2
    mov r6 r3
    nez r6
    require r6              ; this seat committed (hidden game)
    hash r4 <- r1
    eq r4 r3
    require r4              ; alghash(x) == commit
    movi r2 {R1H << 32}
    mul r2 r5
    movi r4 {R2H << 32}
    mul r4 r7
    add r2 r4
    add r2 r0               ; r2 = my hi-half slot key
    movi r3 {R1L << 32}
    mul r3 r5
    movi r4 {R2L << 32}
    mul r4 r7
    add r3 r4
    add r3 r0               ; r3 = my lo-half slot key (r5/r7 free from here)
    mov r6 r1
    lo32 r6                 ; r6 = x & 0xffffffff (canonical low half)
    mov r5 r1
    sub r5 r6               ; r5 = hi·2^32 (an exact multiple)
    movi r7 18446744065119617026
    mul r5 r7               ; r5 = hi — the field inverse of 2^32 undoes the exact factor
    sstore r2 r5            ; hi half
    sstore r3 r6            ; lo half
    ret r0
"""

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

# open(g, cfg, commit): tictactoe's open (stake escrow, seat, lobby index) prefixed with TWO stores — the
# creator's cfg word (26-bit kingdom mask, 0 = random) and their hidden-hands commit H(secret) (0 = classic
# open-hand play). Stored FIRST because the base body clobbers r1 with `ctx value`; a failed require later
# reverts the whole call, so the early writes are safe. Missing args pad to 0 → fully back-compatible.
OPEN = f"""
        slot r4 {CFG} r0
        sstore r4 r1
        slot r4 {C1} r0
        sstore r4 r2
""" + _t.SRC["open"]

SRC = {"open": OPEN, "join": JOIN, "move": MOVE, "agree": _c.AGREE, "reveal": REVEAL,
       "resign": _t.SRC["resign"], "abort": _t.ABORT_REFUND, "cancel": _t.SRC["cancel"]}

ABI = {
    "open": {"args": ["gameId", "cfg", "commit"], "value": True},
    "join": {"args": ["gameId", "commit"], "value": True},
    "move": {"args": ["gameId", "enc", "ply"]},
    "agree": {"args": ["gameId", "result"]},
    "reveal": {"args": ["gameId", "x"]},
    "resign": {"args": ["gameId"]},
    "abort": {"args": ["gameId"]},
    "cancel": {"args": ["gameId"]},
    "_view": {
        "maps": {"nn": NN, "st": ST, "pt": PT, "p1": P1, "p2": P2, "sd": SD, "wr": WR, "mc": MC, "dl": DL,
                 "a1": A1, "a2": A2, "kh": KH, "cfg": CFG, "c1": C1, "c2": C2,
                 "r1h": R1H, "r2h": R2H, "r1l": R1L, "r2l": R2L},
        "index": {"cnt": 0, "list": LIST},
        "board": {"name": "mv", "base": MV_BASE, "cells": MAXMOVES, "stride": 10000},
        "board2": {"name": "mh", "base": MH_BASE, "cells": MAXMOVES, "stride": 10000},
        "addr": ["p1", "p2"],
    },
}


# methods whose SOURCE differs between the ISAs on purpose (tests/test_every_contract_assembles_unchanged_for_the_old_vm):
# reveal splits the secret into browser halves with the field inverse of 2^32 on v1, a divide on v2 (_lib.port_inv32)
ISA_DIVERGENT_METHODS = ("reveal",)


def build(isa=None):
    # C2 (security review 2026-09-23): every id-taking method refuses an id >= 2^32 before touching a slot;
    # see _lib.id_guard. The ABI, the field layout and every honest call are unchanged.
    ID_GUARDS = {m: ["r0"] for m in ("open", "join", "move", "agree", "reveal", "resign", "abort", "cancel")}
    src = SRC
    if (isa or zkvmasm.default_isa()) == "v2":
        src = dict(SRC, reveal=_lib.port_inv32(SRC["reveal"]))      # no inverse of 2^32 on the 256-bit word
    return zkvmasm.assemble_contract(_lib.guard_ids(src, ID_GUARDS), isa)


# ---- the gen-29 carry (tools/carry.py, doc/stwo/g5-carry.md) ----------------------------------------------------------
# Values >= 2^32 kept verbatim (_lib.CARRY_WORDS note): the stakes (raw NADO), the creator's cfg word and every move
# word (both stored exactly as passed, so any field value), and a game's hidden-hands commitments. A revealed secret is
# stored as two 32-bit halves, so it is never large. The move log's seed heights mh/kh stay old-chain heights: they are
# read only by the browser replaying a finished game (G6 replays pre-reroll history with the old chain's hashes).
CARRY_WORDS = {("field", ST): "a game's stake (raw NADO)", ("field", PT): "a game's pot (raw NADO)",
               ("field", CFG): "the creator's cfg word (stored as passed)",
               ("field", C1): "p1's hidden-hands commitment H(secret)", ("field", C2): "p2's hidden-hands commitment H(secret)",
               **{("field", MV_BASE + i): "a recorded move word (stored as passed)" for i in range(MAXMOVES)}}


def carry_in_flight(storage):
    """Why this contract cannot cross a reroll yet ([] = it can):
      * an open game (_lib.pvp_games_in_flight) — its move clock is an old-chain height and its shuffles pin old-chain
        block hashes: the opener's cancel(g) in the lobby; agree / resign, or abort(g) once the move clock lapses
        (permissionless, refunds both stakes) after the join;
    A SETTLED game's unrevealed hidden-hands commitment does NOT block (the rule hexholm and scrapline share): reveal()
    after settlement is a client-side audit and moves no value, and blocking on it would let anyone hold the reroll
    forever — open a hidden game between two of their own addresses, settle it, never reveal. The commitment carries
    verbatim; a reveal of it on gen 29 reverts (the new hash cannot match it), and that is all that is lost.
    Reached through the game index only (slot 0 count, field LIST)."""
    slots = (storage or {}).get("slots") or {}
    g = lambda f, k: int(slots.get(str((f << 32) + k), 0))
    out = []
    for gid in _lib.pvp_games_in_flight(storage, NN, SD, LIST):
        if g(NN, gid) == 1:
            out.append(f"game {gid} awaits a joiner - cancel({gid}) (opener)")
        else:
            out.append(f"game {gid} is in play - agree/resign, or abort({gid}) past block {g(DL, gid)} (permissionless)")
    return out
