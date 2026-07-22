"""
Reversi (Othello) — zkVM port (doc/zk-execution-proofs.md). Staked 8×8 PvP where the CONTRACT is the referee:
move() walks all 8 directions on-chain, requires ≥1 flip (the legality rule), flips every bracketed run, and
a consecutive double-pass ends the game and pays the disc majority (a draw refunds both). Ported from the
deleted stackvm contract with identical rules.

Board: a BORDERED 16-wide layout so edge detection is free — cell (c,r), c,r∈0..7 lives at
bidx = (c+1)*16 + (r+1); border cells stay 0, stopping every walk. Direction offsets are ±16,±1,±17,±15.
Each board cell is its own field (BD_BASE+bidx) keyed by gameId → slot = (BD_BASE+bidx)*2^32 + g (no 2^32
stride overflow). The frontend reads bd[g*512 + bidx], so the view uses stride 512 over 160 border cells.

Game fields: 1 nn 2 st 3 pt 4 p1 5 p2 6 sd 7 wr 8 mc 9 dl 10 list 11 lp(last-pass).  Board fields 20+bidx.
Scratch field 30 (0 base, 1 k, 2 opp, 3 fl/n1, 4 n2, 5 n, 6 i, 7 ci).  cell 0..63 = placement, 64 = PASS.
Methods: open(g)[stake] · join(g)[stake] · move(g,cell,ply) · resign(g) · abort(g) · cancel(g).
"""
from execnode import zkvmasm
from execnode.games import _lib
from execnode.games import tictactoe as _t
from execnode.stark.field import P as _P

NN, ST, PT, P1, P2, SD, WR, MC, DL, LIST, LP = 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11

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
DAILY_WORDS = 8                                    # ceil(60 moves / 8 per word) at 6 bits/move
DAILY_MAX_N = 60
BD_BASE = 20
SC = 30
DIRS = [16, -16, 1, -1, 17, 15, -15, -17]
PASS = 64
# standard Othello center: bidx 68/85 = white(2), 69/84 = black(1)
SEED = [(68, 2), (85, 2), (69, 1), (84, 1)]


def flips_for(board, cell, k):
    """In-clear reference (bordered dict {bidx: mark}) — the cells a placement at `cell` by `k` flips."""
    c, r = cell // 8, cell % 8
    base = (c + 1) * 16 + (r + 1)
    opp = 3 - k
    out = []
    for d in DIRS:
        run, p = [], base + d
        while board.get(p, 0) == opp:
            run.append(p); p += d
        if run and board.get(p, 0) == k:
            out += run
    return out


def _s(i):
    return (SC << 32) | i


def _bsl(bidx_reg, out):
    """Emit asm computing the board slot (BD_BASE+bidx)*2^32 + g into `out` (uses r7; g in r0; bidx_reg kept)."""
    return [f"movi {out} {BD_BASE << 32}", "movi r7 4294967296", f"mul r7 {bidx_reg}",
            f"add {out} r7", f"add {out} r0"]


def _dir_block(d):
    """One direction's count + conditional flip. base=SC0, k=SC1, opp=SC2, fl=SC3; n=SC5, i=SC6."""
    L = [f"movi r4 {_s(5)}", "movi r5 0", "sstore r4 r5"]            # n = 0
    # walk: while bd[base + (n+1)*d] == opp: n++
    L += [f"wk_{d}:",
          f"movi r4 {_s(5)}", "sload r5 r4", "movi r6 1", "add r5 r6",     # n+1
          f"movi r6 {d % _P}", "mul r5 r6",                                # (n+1)*d
          f"movi r4 {_s(0)}", "sload r4 r4", "add r4 r5"]                  # bidx = base + (n+1)*d  (r4)
    L += _bsl("r4", "r6") + ["sload r6 r6"]                               # bd[bidx] -> r6
    L += [f"movi r4 {_s(2)}", "sload r4 r4", "eq r6 r4",                   # == opp ?
          f"jnz r6 @wkb_{d}", f"jmp @wke_{d}",
          f"wkb_{d}:", f"movi r4 {_s(5)}", "sload r5 r4", "movi r6 1", "add r5 r6", "sstore r4 r5",   # n++
          f"jmp @wk_{d}", f"wke_{d}:"]
    # valid = (n>0) AND bd[base+(n+1)*d] == k
    L += [f"movi r4 {_s(5)}", "sload r5 r4", "nez r5",                     # r5 = (n>0)
          f"movi r4 {_s(5)}", "sload r6 r4", "movi r4 1", "add r6 r4",     # n+1
          f"movi r4 {d % _P}", "mul r6 r4",
          f"movi r4 {_s(0)}", "sload r4 r4", "add r4 r6"]                  # bidx (r4)
    L += _bsl("r4", "r6") + ["sload r6 r6"]
    L += [f"movi r4 {_s(1)}", "sload r4 r4", "eq r6 r4", "mul r5 r6",      # valid
          f"jnz r5 @flip_{d}", f"jmp @fdone_{d}", f"flip_{d}:"]
    # fl += n ; flip i=1..n: bd[base + i*d] = k
    L += [f"movi r4 {_s(5)}", "sload r5 r4", f"movi r4 {_s(3)}", "sload r6 r4", "add r6 r5", "sstore r4 r6",
          f"movi r4 {_s(6)}", "movi r5 1", "sstore r4 r5",                 # i = 1
          f"fl_{d}:",
          f"movi r4 {_s(6)}", "sload r5 r4", f"movi r4 {_s(5)}", "sload r6 r4",
          "movi r7 1", "add r6 r7", "lt r5 r6",                            # i < n+1
          f"jnz r5 @flb_{d}", f"jmp @fdone_{d}", f"flb_{d}:",
          f"movi r4 {_s(6)}", "sload r5 r4", f"movi r4 {d % _P}", "mul r5 r4",   # i*d
          f"movi r4 {_s(0)}", "sload r4 r4", "add r4 r5"]                  # bidx = base + i*d (r4)
    L += _bsl("r4", "r6")                                                 # slot -> r6
    L += [f"movi r5 {_s(1)}", "sload r5 r5", "sstore r6 r5",              # bd[bidx] = k
          f"movi r4 {_s(6)}", "sload r5 r4", "movi r6 1", "add r5 r6", "sstore r4 r5",   # i++
          f"jmp @fl_{d}", f"fdone_{d}:"]
    return L


def _move():
    L = ["slot r4 1 r0", "sload r5 r4", "movi r6 2", "eq r5 r6", "require r5",
         "slot r4 6 r0", "sload r5 r4", "nez r5", "notb r5", "require r5",
         "slot r4 8 r0", "sload r3 r4", "mov r5 r3", "eq r5 r2", "require r5",       # ply==mc (r3=mc)
         "mov r5 r3", "movi r6 2", "divmod r5 r6",                                   # r7=parity
         "ctx r6 caller", "movi r4 4", "add r4 r7", "movi r5 4294967296", "mul r4 r5", "add r4 r0",
         "sload r5 r4", "eq r5 r6", "require r5",
         "movi r5 1", "add r7 r5", "mov r2 r7",                                      # k
         f"movi r4 {_s(1)}", "sstore r4 r2", "movi r4 3", "sub r4 r2", f"movi r5 {_s(2)}", "sstore r5 r4",
         "mov r5 r1", f"movi r6 {PASS}", "eq r5 r6", "jnz r5 @pass", "jmp @place",
         "place:",
         "mov r5 r1", "movi r6 8", "divmod r5 r6",                                   # r5=c, r7=r
         "movi r6 1", "add r5 r6", "movi r6 16", "mul r5 r6", "movi r6 1", "add r7 r6", "add r5 r7",   # base
         f"movi r4 {_s(0)}", "sstore r4 r5"]
    L += _bsl("r5", "r6") + ["sload r6 r6", "nez r6", "notb r6", "require r6"]      # bd[base]==0
    L += [f"movi r4 {_s(3)}", "movi r5 0", "sstore r4 r5"]                          # fl=0
    for d in DIRS:
        L += _dir_block(d)
    L += [f"movi r4 {_s(3)}", "sload r5 r4", "require r5",                          # fl>0
          f"movi r4 {_s(0)}", "sload r5 r4"]
    L += _bsl("r5", "r6") + [f"movi r4 {_s(1)}", "sload r4 r4", "sstore r6 r4",     # bd[base]=k
          "slot r4 8 r0", "sload r5 r4", "movi r6 1", "add r5 r6", "sstore r4 r5",  # mc++
          "slot r4 11 r0", "movi r5 0", "sstore r4 r5", "ret r0",                   # lp=0
          "pass:",
          "slot r4 11 r0", "sload r5 r4", "nez r5", "jnz r5 @endgame",
          "slot r4 11 r0", "movi r5 1", "sstore r4 r5",
          "slot r4 8 r0", "sload r5 r4", "movi r6 1", "add r5 r6", "sstore r4 r5", "ret r0",
          "endgame:",
          f"movi r4 {_s(3)}", "movi r5 0", "sstore r4 r5",                          # n1=0
          f"movi r4 {_s(4)}", "movi r5 0", "sstore r4 r5",                          # n2=0
          f"movi r4 {_s(7)}", "movi r5 0", "sstore r4 r5",                          # ci=0
          "cnt_loop:",
          f"movi r4 {_s(7)}", "sload r5 r4", "movi r6 64", "mov r7 r5", "lt r7 r6",
          "jnz r7 @cnt_body", "jmp @cnt_done", "cnt_body:",
          f"movi r4 {_s(7)}", "sload r3 r4", "mov r6 r3", "movi r7 8", "divmod r6 r7",  # r6=ci//8 r7=ci%8
          "movi r5 1", "add r6 r5", "movi r5 16", "mul r6 r5", "movi r5 1", "add r7 r5", "add r6 r7"]  # bidx
    L += _bsl("r6", "r4") + ["sload r6 r4",                                         # v = bd[bidx]
          "mov r5 r6", "movi r7 1", "eq r5 r7", f"movi r4 {_s(3)}", "sload r7 r4", "add r7 r5", "sstore r4 r7",
          "mov r5 r6", "movi r7 2", "eq r5 r7", f"movi r4 {_s(4)}", "sload r7 r4", "add r7 r5", "sstore r4 r7",
          f"movi r4 {_s(7)}", "sload r5 r4", "movi r7 1", "add r5 r7", "sstore r4 r5", "jmp @cnt_loop",
          "cnt_done:",
          f"movi r4 {_s(3)}", "sload r1 r4", f"movi r4 {_s(4)}", "sload r2 r4",     # n1,n2
          "mov r5 r2", "lt r5 r1",                                                  # w1 = n2<n1
          "mov r6 r1", "lt r6 r2",                                                  # w2 = n1<n2
          "slot r4 3 r0", "sload r3 r4", "mov r7 r3", "mul r7 r5", "slot r4 4 r0", "sload r4 r4", "pay r4 r7",
          "slot r4 3 r0", "sload r3 r4", "mov r7 r3", "mul r7 r6", "slot r4 5 r0", "sload r4 r4", "pay r4 r7",
          "movi r7 1", "sub r7 r5", "sub r7 r6",                                    # dr
          "slot r4 2 r0", "sload r3 r4", "mov r4 r3", "mul r4 r7", "slot r3 4 r0", "sload r3 r3", "pay r3 r4",
          "slot r4 2 r0", "sload r3 r4", "mov r4 r3", "mul r4 r7", "slot r3 5 r0", "sload r3 r3", "pay r3 r4",
          "mov r3 r5", "movi r4 2", "mul r6 r4", "add r3 r6", "movi r4 3", "mul r7 r4", "add r3 r7",
          "slot r4 7 r0", "sstore r4 r3", "slot r4 6 r0", "movi r5 1", "sstore r4 r5",
          "slot r4 3 r0", "movi r5 0", "sstore r4 r5", "ret r0"]
    return L


def _open():
    L = ["ctx r1 value", "movi r2 0", "lt r2 r1", "require r2",
         "movi r2 0", "lt r2 r0", "require r2",
         "slot r4 1 r0", "sload r5 r4", "nez r5", "notb r5", "require r5",
         "slot r4 2 r0", "sstore r4 r1", "slot r4 3 r0", "sstore r4 r1",
         "ctx r6 caller", "slot r4 4 r0", "sstore r4 r6",
         "slot r4 1 r0", "movi r5 1", "sstore r4 r5"]
    for (bidx, mark) in SEED:
        L += [f"movi r4 {(BD_BASE + bidx) << 32}", "add r4 r0", f"movi r5 {mark}", "sstore r4 r5"]
    L += ["movi r4 0", "sload r5 r4", "slot r6 10 r5", "sstore r6 r0", "movi r3 1", "add r5 r3", "sstore r4 r5",
          "ret r0"]
    return L


POST = _lib.daily_post(ECNT_SLOT, E_DAY, E_ADDR, E_SCORE, E_N, ELIST, EW_BASE, DAILY_WORDS,
                       max_n=DAILY_MAX_N, max_score=2000, e_ts=E_TS)
ANCHOR = _lib.daily_anchor(A_H, A_V, DCNT_SLOT, DLIST)

SRC = {
    "post": POST, "anchor": ANCHOR,"open": None, "join": _t.SRC["join"], "move": None,
       "resign": _t.SRC["resign"], "abort": _t.SRC["abort"], "cancel": _t.SRC["cancel"]}

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
                 "lp": LP,
                 "eday": {"field": E_DAY, "index": "entries"}, "eaddr": {"field": E_ADDR, "index": "entries"},
                 "escore": {"field": E_SCORE, "index": "entries"}, "en": {"field": E_N, "index": "entries"},
                 "ets": {"field": E_TS, "index": "entries"},
                 **{f"ew{k}": {"field": EW_BASE + k, "index": "entries"} for k in range(DAILY_WORDS)},
                 "ah": {"field": A_H, "index": "days"}, "av": {"field": A_V, "index": "days"},},
        "index": {"cnt": 0, "list": LIST},
        "indexes": {"entries": {"cnt": ECNT_SLOT, "list": ELIST},
                    "days": {"cnt": DCNT_SLOT, "list": DLIST}},
        "board": {"name": "bd", "base": BD_BASE, "cells": 160, "stride": 512},
        "addr": ["p1", "p2", "eaddr"],
    },
}


def build():
    src = dict(SRC)
    src["open"] = "\n".join(_open())
    src["move"] = "\n".join(_move())
    return zkvmasm.assemble_contract(src)
