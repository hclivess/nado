"""
Mines — zkVM port (doc/zk-execution-proofs.md). Banked provably-fair mines: a player bets on a machine that
hides `n` mines among 25 tiles, blind-picks tiles in rounds (each safe reveal multiplies the payout), then
`resolve` draws the mine layout from L1 BLOCKHASH and checks the round's picks. Cash out any time before a
resolve; a stalled game is reaped. Ported from the deleted stackvm contract with identical math (multiplier
uses a 1% edge: each of the `count` reveals multiplies by rem·99 / ((rem−n)·100), rem = tiles left).

Table: 1 ta 2 tk 3 tp 4 tc 6 tz 15 tn 16 tx.  Game: 7 gg 9 gs 10 ga 11 gh 14 gd 17 gn(mines) 18 gv(value)
  19 gp(picked) 20 gc(round count) 21 gq(potential) 22 gb(hit) 23 ge(last activity).  Scratch field 30.
Index: slot0/field24 tables, slot1/25 games.
Methods: open(t)[bank] · bet(g,t,n)[stake] · pick(g,count) · resolve(g) · cashout(g) · reap(g) · fund/close.
"""
from execnode import zkvmasm
from execnode.stark import alghash, field as F

TA, TK, TP, TC, TZ, TN, TX = 1, 2, 3, 4, 6, 15, 16
GG, GS, GA, GH, GD, GN, GV, GP, GC, GQ, GB, GE = 7, 9, 10, 11, 14, 17, 18, 19, 20, 21, 22, 23
SC = 30
TLIST, GLIST = 24, 25


def multiplier(gv, gp, gn, count):
    """In-clear payout after revealing `count` more safe tiles (the reference the pick loop reproduces)."""
    nv = gv
    for i in range(count):
        rem = 25 - gp - i
        nv = nv * rem * 99 // ((rem - gn) * 100)
    return nv


def resolve_hit(q, gp, gn, gc):
    """In-clear: b = the 1-based pick index that hit a mine among this round's gc picks, else 0 (stops at the
    first hit). Mine at pick i iff alghash([q + gp + i]) % (25 - gp - i) < gn."""
    b = 0
    for i in range(gc):
        if b:
            break
        d = (alghash.hashn([(q + gp + i) % F.P]) & 0xFFFFFFFF) % (25 - gp - i)   # lo32 window, matches the VM
        if d < gn:
            b = i + 1
    return b


def _sc(i):
    return (SC << 32) + i


PICK = f"""
    slot r4 7 r0
    sload r5 r4
    require r5
    slot r4 14 r0
    sload r5 r4
    nez r5
    notb r5
    require r5
    slot r4 11 r0
    sload r5 r4
    nez r5
    notb r5
    require r5
    ctx r6 caller
    slot r4 10 r0
    sload r5 r4
    eq r5 r6
    require r5
    mov r5 r1
    movi r6 1
    lt r5 r6
    notb r5
    require r5
    slot r4 19 r0
    sload r2 r4
    slot r4 17 r0
    sload r3 r4
    mov r5 r2
    add r5 r1
    movi r6 25
    sub r6 r3
    mov r4 r6
    lt r4 r5
    notb r4
    require r4
    slot r4 18 r0
    sload r5 r4
    movi r4 {_sc(0)}
    sstore r4 r5
    movi r4 {_sc(1)}
    movi r5 0
    sstore r4 r5
pk_loop:
    movi r4 {_sc(1)}
    sload r5 r4
    mov r6 r5
    lt r6 r1
    jnz r6 @pk_body
    jmp @pk_done
pk_body:
    movi r6 25
    sub r6 r2
    sub r6 r5
    movi r4 {_sc(0)}
    sload r4 r4
    mul r4 r6
    movi r7 99
    mul r4 r7
    sub r6 r3
    movi r7 100
    mul r6 r7
    divmod r4 r6
    movi r6 {_sc(0)}
    sstore r6 r4
    movi r4 {_sc(1)}
    sload r5 r4
    movi r6 1
    add r5 r6
    sstore r4 r5
    jmp @pk_loop
pk_done:
    movi r4 {_sc(0)}
    sload r5 r4
    slot r4 18 r0
    sload r6 r4
    sub r5 r6
    slot r4 7 r0
    sload r2 r4
    slot r4 4 r2
    sload r6 r4
    add r6 r5
    slot r4 2 r2
    sload r4 r4
    lt r4 r6
    notb r4
    require r4
    slot r4 4 r2
    sstore r4 r6
    movi r4 {_sc(0)}
    sload r5 r4
    slot r4 21 r0
    sstore r4 r5
    slot r4 20 r0
    sstore r4 r1
    slot r4 11 r0
    ctx r5 cursor
    movi r6 2
    add r5 r6
    sstore r4 r5
    slot r4 23 r0
    ctx r5 cursor
    sstore r4 r5
    ret r0
"""

RESOLVE = f"""
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
    require r5
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
    movi r4 {_sc(2)}
    sstore r4 r3
    movi r4 {_sc(3)}
    movi r5 0
    sstore r4 r5
    movi r4 {_sc(4)}
    movi r5 0
    sstore r4 r5
    slot r4 19 r0
    sload r2 r4
    slot r4 17 r0
    sload r3 r4
    slot r4 20 r0
    sload r1 r4
rs_loop:
    movi r4 {_sc(4)}
    sload r5 r4
    mov r6 r5
    lt r6 r1
    movi r4 {_sc(3)}
    sload r7 r4
    nez r7
    notb r7
    mul r6 r7
    jnz r6 @rs_body
    jmp @rs_done
rs_body:
    movi r4 {_sc(2)}
    sload r4 r4
    add r4 r2
    add r4 r5
    hash r4 <- r4
    lo32 r4
    movi r6 25
    sub r6 r2
    sub r6 r5
    divmod r4 r6
    mov r6 r7
    lt r6 r3
    jnz r6 @rs_hit
    jmp @rs_next
rs_hit:
    movi r4 {_sc(4)}
    sload r5 r4
    movi r6 1
    add r5 r6
    movi r4 {_sc(3)}
    sstore r4 r5
rs_next:
    movi r4 {_sc(4)}
    sload r5 r4
    movi r6 1
    add r5 r6
    sstore r4 r5
    jmp @rs_loop
rs_done:
    movi r4 {_sc(3)}
    sload r5 r4
    slot r4 22 r0
    sstore r4 r5
    nez r5
    jnz r5 @lost
    slot r4 20 r0
    sload r5 r4
    slot r4 19 r0
    sload r6 r4
    add r6 r5
    sstore r4 r6
    slot r4 21 r0
    sload r5 r4
    slot r4 18 r0
    sstore r4 r5
    slot r4 11 r0
    movi r5 0
    sstore r4 r5
    slot r4 23 r0
    ctx r5 cursor
    sstore r4 r5
    ret r0
lost:
    slot r4 7 r0
    sload r1 r4
    slot r4 21 r0
    sload r5 r4
    slot r4 9 r0
    sload r6 r4
    sub r5 r6
    slot r4 4 r1
    sload r6 r4
    sub r6 r5
    sstore r4 r6
    slot r4 9 r0
    sload r5 r4
    slot r4 2 r1
    sload r6 r4
    add r6 r5
    sstore r4 r6
    slot r4 14 r0
    movi r5 1
    sstore r4 r5
    ret r0
"""

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
        slot r6 24 r5
        sstore r6 r0
        movi r3 1
        add r5 r3
        sstore r4 r5
        ret r0
    """,
    # bet(g, t, n)[stake]: n mines (1..24); game value starts at the stake
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
        mov r5 r2
        movi r6 1
        lt r5 r6
        notb r5
        require r5
        movi r5 25
        mov r6 r2
        lt r6 r5
        require r6
        slot r4 9 r0
        sstore r4 r3
        slot r4 7 r0
        sstore r4 r1
        ctx r6 caller
        slot r4 10 r0
        sstore r4 r6
        slot r4 17 r0
        sstore r4 r2
        slot r4 18 r0
        sstore r4 r3
        slot r4 23 r0
        ctx r6 cursor
        sstore r4 r6
        slot r4 3 r1
        sload r5 r4
        add r5 r3
        sstore r4 r5
        movi r4 1
        sload r5 r4
        slot r6 25 r5
        sstore r6 r0
        movi r2 1
        add r5 r2
        sstore r4 r5
        ret r0
    """,
    "pick": PICK,
    "resolve": RESOLVE,
    # cashout(g): take the current value before a pending resolve (gh must be 0)
    "cashout": """
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
        nez r5
        notb r5
        require r5
        ctx r6 caller
        slot r4 10 r0
        sload r5 r4
        eq r5 r6
        require r5
        slot r4 18 r0
        sload r5 r4
        pay r6 r5
        slot r4 3 r1
        sload r6 r4
        sub r6 r5
        sstore r4 r6
        slot r4 4 r1
        sload r6 r4
        slot r4 18 r0
        sload r3 r4
        sub r6 r3
        slot r4 9 r0
        sload r3 r4
        add r6 r3
        slot r4 4 r1
        sstore r4 r6
        slot r4 2 r1
        sload r6 r4
        slot r4 9 r0
        sload r3 r4
        add r6 r3
        slot r4 18 r0
        sload r3 r4
        sub r6 r3
        slot r4 2 r1
        sstore r4 r6
        slot r4 14 r0
        movi r5 1
        sstore r4 r5
        ret r0
    """,
    # reap(g): a long-stalled game refunds the current value to the player
    "reap": """
        slot r4 7 r0
        sload r1 r4
        require r1
        slot r4 14 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 23 r0
        sload r5 r4
        movi r6 1200
        add r5 r6
        ctx r6 cursor
        lt r5 r6
        require r5
        slot r4 18 r0
        sload r5 r4
        slot r4 10 r0
        sload r6 r4
        pay r6 r5
        slot r4 3 r1
        sload r6 r4
        sub r6 r5
        sstore r4 r6
        slot r4 14 r0
        movi r5 1
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
}

ABI = {
    "open": {"args": ["tableId"], "value": True},
    "bet": {"args": ["gameId", "tableId", "mines"], "value": True},
    "pick": {"args": ["gameId", "count"]},
    "resolve": {"args": ["gameId"]},
    "cashout": {"args": ["gameId"]},
    "reap": {"args": ["gameId"]},
    "fund": {"args": ["tableId"], "value": True},
    "close": {"args": ["tableId"]},
    "_view": {
        "maps": {"ta": {"field": TA, "index": "tables"}, "tk": {"field": TK, "index": "tables"},
                 "tp": {"field": TP, "index": "tables"}, "tc": {"field": TC, "index": "tables"},
                 "tz": {"field": TZ, "index": "tables"},
                 "gg": {"field": GG, "index": "games"}, "gs": {"field": GS, "index": "games"},
                 "ga": {"field": GA, "index": "games"}, "gh": {"field": GH, "index": "games"},
                 "gd": {"field": GD, "index": "games"}, "gn": {"field": GN, "index": "games"},
                 "gv": {"field": GV, "index": "games"}, "gp": {"field": GP, "index": "games"},
                 "gc": {"field": GC, "index": "games"}, "gq": {"field": GQ, "index": "games"},
                 "gb": {"field": GB, "index": "games"}, "ge": {"field": GE, "index": "games"}},
        "indexes": {"tables": {"cnt": 0, "list": TLIST}, "games": {"cnt": 1, "list": GLIST}},
        "addr": ["ta", "ga"],
    },
}


def build():
    return zkvmasm.assemble_contract(SRC)
