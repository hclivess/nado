"""
Roulette — zkVM port (doc/zk-execution-proofs.md). A banked wheel: a banker opens a table with a bankroll,
players bet a stake covering a set of the 37 numbers (0..36), and each bet settles from L1 BLOCKHASH
randomness paying 36/coverage on a hit (single number = 36×). Ported from the deleted stackvm contract.

ARG-PACKING (the >8-arg rework): the old contract took up to 18 number slots as separate args, which
overflows the zkVM's 8-register arg limit. Here the coverage is a single 37-bit MASK arg (bit n = covering
number n). The contract counts the bits in-VM (popcount, a bounded loop) for the payout multiplier, and at
settle extracts bit `roll` of the mask with a bounded shift loop — no VM change, and fewer bytes on-chain.

Table fields:  1 ta  2 tk  3 tp  4 tc  6 tz          Game: 7 gg  8 gmask  9 gs  10 ga  11 gh  12 gr  13 gw
               14 gd  15 gc(coverage count).   Index: slot 0 = table count / field 16 list; slot 1 = game / 17.
Methods: open(t)[bankroll] · bet(g,t,mask)[stake] · settle(g) · close(t) · fund(t)[value].
"""
from execnode import zkvmasm

TA, TK, TP, TC, TZ = 1, 2, 3, 4, 6
GG, GMASK, GS, GA, GH, GR, GW, GD, GC = 7, 8, 9, 10, 11, 12, 13, 14, 15
TLIST, GLIST = 16, 17

SRC = {
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
        ctx r6 caller
        slot r4 1 r0
        sstore r4 r6
        slot r4 2 r0
        sstore r4 r1
        slot r4 3 r0
        sstore r4 r1
        movi r4 0
        sload r5 r4
        slot r6 16 r5
        sstore r6 r0
        movi r3 1
        add r5 r3
        sstore r4 r5
        ret r0
    """,
    # bet(g, t, mask)[stake]: mask is a 37-bit coverage set. popcount -> gc, then the dice-style bankroll check.
    "bet": """
        ctx r3 value
        movi r4 0
        lt r4 r0
        require r4
        movi r4 0
        lt r4 r3
        require r4
        slot r4 7 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 1 r1
        sload r5 r4
        nez r5
        require r5
        slot r4 6 r1
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 8 r0
        sstore r4 r2
        mov r6 r2
        movi r5 0
    pc_loop:
        mov r4 r6
        nez r4
        jnz r4 @pc_body
        jmp @pc_done
    pc_body:
        movi r4 2
        divmod r6 r4
        add r5 r7
        jmp @pc_loop
    pc_done:
        movi r4 0
        lt r4 r5
        require r4
        mov r4 r5
        movi r6 37
        lt r4 r6
        require r4
        slot r4 15 r0
        sstore r4 r5
        mov r6 r3
        movi r4 36
        mul r6 r4
        divmod r6 r5
        sub r6 r3
        slot r4 4 r1
        sload r5 r4
        add r5 r6
        slot r4 2 r1
        sload r4 r4
        lt r4 r5
        notb r4
        require r4
        slot r4 4 r1
        sstore r4 r5
        slot r4 3 r1
        sload r5 r4
        add r5 r3
        sstore r4 r5
        slot r4 9 r0
        sstore r4 r3
        slot r4 7 r0
        sstore r4 r1
        ctx r6 caller
        slot r4 10 r0
        sstore r4 r6
        slot r4 11 r0
        ctx r6 cursor
        movi r5 2
        add r6 r5
        sstore r4 r6
        movi r4 1
        sload r5 r4
        slot r6 17 r5
        sstore r6 r0
        movi r2 1
        add r5 r2
        sstore r4 r5
        ret r0
    """,
    "settle": """
        slot r4 7 r0
        sload r1 r4
        require r1
        slot r4 14 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 11 r0
        sload r5 r4
        movi r6 1
        add r5 r6
        ctx r6 cursor
        lt r6 r5
        notb r6
        require r6
        slot r4 11 r0
        sload r2 r4
        bhash r3 r2
        movi r6 1
        add r2 r6
        bhash r5 r2
        add r3 r5
        add r3 r0
        hash r3 <- r3
        lo32 r3
        movi r6 37
        divmod r3 r6
        mov r2 r7
        movi r6 1
        add r7 r6
        slot r4 12 r0
        sstore r4 r7
        slot r4 8 r0
        sload r3 r4
        movi r5 0
    sh_loop:
        mov r4 r5
        lt r4 r2
        jnz r4 @sh_body
        jmp @sh_done
    sh_body:
        movi r4 2
        divmod r3 r4
        movi r4 1
        add r5 r4
        jmp @sh_loop
    sh_done:
        movi r4 2
        divmod r3 r4
        slot r4 13 r0
        sstore r4 r7
        mov r2 r7
        slot r4 9 r0
        sload r3 r4
        movi r6 36
        mul r3 r6
        slot r4 15 r0
        sload r5 r4
        divmod r3 r5
        mul r3 r2
        slot r4 10 r0
        sload r6 r4
        pay r6 r3
        slot r4 3 r1
        sload r5 r4
        sub r5 r3
        sstore r4 r5
        slot r4 9 r0
        sload r3 r4
        movi r6 36
        mov r5 r3
        mul r5 r6
        slot r4 15 r0
        sload r6 r4
        divmod r5 r6
        sub r5 r3
        slot r4 4 r1
        sload r6 r4
        sub r6 r5
        sstore r4 r6
        slot r4 14 r0
        movi r5 1
        sstore r4 r5
        ret r0
    """,
    "close": """
        ctx r1 caller
        slot r4 1 r0
        sload r5 r4
        eq r5 r1
        require r5
        slot r4 6 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 3 r0
        sload r6 r4
        pay r1 r6
        slot r4 6 r0
        movi r5 1
        sstore r4 r5
        slot r4 3 r0
        movi r5 0
        sstore r4 r5
        ret r0
    """,
    "fund": """
        ctx r1 value
        ctx r2 caller
        slot r4 1 r0
        sload r5 r4
        eq r5 r2
        require r5
        slot r4 6 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        movi r5 0
        lt r5 r1
        require r5
        slot r4 2 r0
        sload r6 r4
        add r6 r1
        sstore r4 r6
        slot r4 3 r0
        sload r6 r4
        add r6 r1
        sstore r4 r6
        ret r0
    """,
}

ABI = {
    "open": {"args": ["tableId"], "value": True},
    "bet": {"args": ["gameId", "tableId", "mask"], "value": True},
    "settle": {"args": ["gameId"]},
    "close": {"args": ["tableId"]},
    "fund": {"args": ["tableId"], "value": True},
    "_view": {
        "maps": {"ta": {"field": TA, "index": "tables"}, "tk": {"field": TK, "index": "tables"},
                 "tp": {"field": TP, "index": "tables"}, "tc": {"field": TC, "index": "tables"},
                 "tz": {"field": TZ, "index": "tables"},
                 "gg": {"field": GG, "index": "games"}, "gmask": {"field": GMASK, "index": "games"},
                 "gs": {"field": GS, "index": "games"}, "ga": {"field": GA, "index": "games"},
                 "gh": {"field": GH, "index": "games"}, "gr": {"field": GR, "index": "games"},
                 "gw": {"field": GW, "index": "games"}, "gd": {"field": GD, "index": "games"},
                 "gc": {"field": GC, "index": "games"}},
        "indexes": {"tables": {"cnt": 0, "list": TLIST}, "games": {"cnt": 1, "list": GLIST}},
        "addr": ["ta", "ga"],
    },
}


def build():
    return zkvmasm.assemble_contract(SRC)
