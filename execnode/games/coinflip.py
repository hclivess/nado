"""
Coin Flip — zkVM port (doc/zk-execution-proofs.md). A fair 2-player flip settled from L1 BLOCKHASH
randomness: nobody spins, nobody reveals a secret, every node derives the same winner. Ported from the
deleted stackvm contract with IDENTICAL semantics, over the composite-integer slot model:

    slot(field, gameId) = field*2^32 + gameId          (the `slot` asm macro; frontend computes the same)

Fields:   1 nn(state 0/1/2)  2 st(stake)  3 pt(pot)  4 p1  5 p2  6 sd(settled)  7 sh(settle height)  8 ws(winner)
Index:    slot 0 = cnt (open-game count);  slot(9, i) = the i-th gameId   (so the frontend can enumerate)

Methods: open(g)[stake] · join(g)[stake] · settle(g) · cancel(g). gameId is a frontend int < 2^32.
"""
from execnode import zkvmasm

NN, ST, PT, P1, P2, SD, SH, WS, LIST = 1, 2, 3, 4, 5, 6, 7, 8, 9

SRC = {
    # open(g) with stake escrowed as call value: new game, record p1 + stake, append to the index
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
        slot r4 2 r0
        sstore r4 r1
        slot r4 3 r0
        sstore r4 r1
        ctx r6 caller
        slot r4 4 r0
        sstore r4 r6
        slot r4 1 r0
        movi r5 1
        sstore r4 r5
        movi r4 0
        sload r5 r4
        slot r6 9 r5
        sstore r6 r0
        movi r3 1
        add r5 r3
        sstore r4 r5
        ret r0
    """,
    # join(g): matching stake, different player; arm settlement two blocks out
    "join": """
        ctx r1 value
        slot r4 1 r0
        sload r5 r4
        movi r2 1
        eq r5 r2
        require r5
        slot r4 6 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 2 r0
        sload r5 r4
        eq r5 r1
        require r5
        ctx r6 caller
        slot r4 4 r0
        sload r5 r4
        eq r5 r6
        notb r5
        require r5
        slot r4 5 r0
        sstore r4 r6
        slot r4 3 r0
        sload r5 r4
        add r5 r1
        sstore r4 r5
        slot r4 1 r0
        movi r5 2
        sstore r4 r5
        slot r4 7 r0
        ctx r5 cursor
        movi r6 2
        add r5 r6
        sstore r4 r5
        ret r0
    """,
    # settle(g): once both settle-height blocks are final, derive the winner from BLOCKHASH and pay the pot
    "settle": """
        slot r4 1 r0
        sload r5 r4
        movi r2 2
        eq r5 r2
        require r5
        slot r4 6 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 7 r0
        sload r5 r4
        movi r6 1
        add r5 r6
        ctx r6 cursor
        lt r6 r5
        notb r6
        require r6
        slot r4 7 r0
        sload r2 r4
        bhash r3 r2
        movi r6 1
        add r2 r6
        bhash r5 r2
        add r3 r5
        add r3 r0
        hash r3 <- r3
        lo32 r3
        movi r6 2
        divmod r3 r6
        movi r6 1
        add r7 r6
        slot r4 8 r0
        sstore r4 r7
        slot r4 3 r0
        sload r1 r4
        movi r5 2
        sub r5 r7
        mov r6 r1
        mul r6 r5
        slot r4 4 r0
        sload r2 r4
        pay r2 r6
        movi r5 1
        sub r7 r5
        mov r6 r1
        mul r6 r7
        slot r4 5 r0
        sload r2 r4
        pay r2 r6
        slot r4 6 r0
        movi r5 1
        sstore r4 r5
        slot r4 3 r0
        movi r5 0
        sstore r4 r5
        ret r0
    """,
    # cancel(g): only the opener, only while still waiting for a joiner — refund the stake
    "cancel": """
        ctx r1 caller
        slot r4 4 r0
        sload r5 r4
        eq r5 r1
        require r5
        slot r4 1 r0
        sload r5 r4
        movi r2 1
        eq r5 r2
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
}

ABI = {
    "open": {"args": ["gameId"], "value": True},
    "join": {"args": ["gameId"], "value": True},
    "settle": {"args": ["gameId"]},
    "cancel": {"args": ["gameId"]},
    # _view: the exec node reconstructs these named maps from the flat slots, so coinflip.js reads them
    # exactly as it did under stackvm (only the cid changes). p1/p2 resolve digest -> L1 address.
    "_view": {"maps": {"nn": NN, "st": ST, "pt": PT, "p1": P1, "p2": P2, "sd": SD, "sh": SH, "ws": WS},
              "index": {"cnt": 0, "list": LIST}, "addr": ["p1", "p2"]},
}


def build():
    return zkvmasm.assemble_contract(SRC)
