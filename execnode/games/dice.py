"""
Dice — zkVM port (doc/zk-execution-proofs.md). A banked roll-under game: a banker opens a table with a
bankroll, players bet a stake on "roll under target" (2..98) for a 99/target payout (1% house edge), and
each bet settles from L1 BLOCKHASH randomness. Ported from the deleted stackvm contract with identical
economics, over the composite-integer slot model (slot = field*2^32 + id).

Table fields:  1 ta(banker)  2 tk(bankroll)  3 tp(pot=banker withdrawable)  4 tc(committed/at-risk)  6 tz(closed)
Game fields:   7 gg(table)  8 gm(target)  9 gs(stake)  10 ga(player)  11 gh(settle height)  12 gr(roll)
               13 gw(win)  14 gd(settled)
Index:  slot 0 = table count, field 15 = table list;  slot 1 = game count, field 16 = game list.

Methods: open(t)[bankroll] · bet(g,t,target)[stake] · settle(g) · close(t) · fund(t)[value].
"""
from execnode import zkvmasm

TA, TK, TP, TC, TZ = 1, 2, 3, 4, 6
GG, GM, GS, GA, GH, GR, GW, GD = 7, 8, 9, 10, 11, 12, 13, 14
TLIST, GLIST = 15, 16

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
        slot r6 15 r5
        sstore r6 r0
        movi r3 1
        add r5 r3
        sstore r4 r5
        ret r0
    """,
    "bet": """
        ctx r3 value
        movi r4 0
        lt r4 r0
        require r4
        movi r4 0
        lt r4 r3
        require r4
        mov r4 r2
        movi r5 2
        lt r4 r5
        notb r4
        require r4
        movi r5 99
        mov r4 r2
        lt r4 r5
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
        mov r5 r3
        movi r6 99
        mul r5 r6
        divmod r5 r2
        sub r5 r3
        slot r4 4 r1
        sload r6 r4
        add r6 r5
        slot r4 2 r1
        sload r4 r4
        lt r4 r6
        notb r4
        require r4
        slot r4 4 r1
        sstore r4 r6
        slot r4 3 r1
        sload r6 r4
        add r6 r3
        sstore r4 r6
        slot r4 8 r0
        sstore r4 r2
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
        slot r6 16 r5
        sstore r6 r0
        movi r2 1
        add r5 r2
        sstore r4 r5
        ret r0
    """,
    "settle": """
        slot r4 7 r0
        sload r1 r4
        nez r1
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
        movi r6 100
        divmod r3 r6
        movi r6 1
        add r7 r6
        slot r4 12 r0
        sstore r4 r7
        mov r2 r7
        movi r6 1
        sub r2 r6
        slot r4 8 r0
        sload r5 r4
        lt r2 r5
        slot r4 13 r0
        sstore r4 r2
        slot r4 9 r0
        sload r3 r4
        movi r6 99
        mul r3 r6
        slot r4 8 r0
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
        movi r6 99
        mov r5 r3
        mul r5 r6
        slot r4 8 r0
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
    "bet": {"args": ["gameId", "tableId", "target"], "value": True},
    "settle": {"args": ["gameId"]},
    "close": {"args": ["tableId"]},
    "fund": {"args": ["tableId"], "value": True},
    "_view": {
        "maps": {"ta": {"field": TA, "index": "tables"}, "tk": {"field": TK, "index": "tables"},
                 "tp": {"field": TP, "index": "tables"}, "tc": {"field": TC, "index": "tables"},
                 "tz": {"field": TZ, "index": "tables"},
                 "gg": {"field": GG, "index": "games"}, "gm": {"field": GM, "index": "games"},
                 "gs": {"field": GS, "index": "games"}, "ga": {"field": GA, "index": "games"},
                 "gh": {"field": GH, "index": "games"}, "gr": {"field": GR, "index": "games"},
                 "gw": {"field": GW, "index": "games"}, "gd": {"field": GD, "index": "games"}},
        "indexes": {"tables": {"cnt": 0, "list": TLIST}, "games": {"cnt": 1, "list": GLIST}},
        "addr": ["ta", "ga"],
    },
}


def build():
    return zkvmasm.assemble_contract(SRC)
