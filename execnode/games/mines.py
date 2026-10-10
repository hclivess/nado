"""
Mines — zkVM port (doc/zk-execution-proofs.md). Banked provably-fair mines: a player bets on a machine that
hides `n` mines among 25 tiles, blind-picks tiles in rounds (each safe reveal multiplies the payout), then
`resolve` draws the mine layout from the epoch BEACON the round was bound to at pick time (_lib.beacon_bind /
seed_q; a round picked before that rule keeps the L1 BLOCKHASH rule) and checks the round's picks. Cash out any
time no round is pending; a game idle for 18,000 blocks is reaped TO THE BANK (the stake stays in the pot, nobody
is paid). Ported from the deleted stackvm contract with identical math (multiplier
uses a 1% edge: each of the `count` reveals multiplies by rem·99 / ((rem−n)·100), rem = tiles left).

Table: 1 ta 2 tk 3 tp 4 tc 6 tz 15 tn 16 tx.  Game: 7 gg 9 gs 10 ga 11 gh 12 gb(beacon epoch; 0 = legacy
  block-hash round) 14 gd(1 settled, 2 timed out to the bank) 17 gn(mines) 18 gv(value) 19 gp(picked)
  20 gc(round count) 21 gq(potential) 22 gx(hit) 23 ge(last activity).  Scratch field 30.
Index: slot0/field24 tables, slot1/25 games.
Methods: open(t)[bank] · bet(g,t,n)[stake] · pick(g,count) · resolve(g) · cashout(g) · reap(g) · fund/close.
"""
from execnode import zkvmasm
from execnode.games import _lib
from execnode.stark import alghash, field as F

TA, TK, TP, TC, TZ, TN, TX = 1, 2, 3, 4, 6, 15, 16
GG, GS, GA, GH, GD, GN, GV, GP, GC, GQ, GX, GE = 7, 9, 10, 11, 14, 17, 18, 19, 20, 21, 22, 23
# 12 gb (beacon epoch of the pending round): added at an unused field for the in-place upgrade. gb == 0 marks a
# round picked before the beacon rule, which keeps resolving from BHASH(gh) + BHASH(gh + 1) (_lib.seed_q). The
# hit index (field 22) was exposed as "gb" before; its view name is now "gx" so "gb" means the beacon epoch in every
# banked game (bankedgame.js reads it).
GB = 12
SC = 30
TLIST, GLIST = 24, 25


def carry_in_flight(storage):
    """Why this contract's storage cannot cross a reroll yet ([] = it can, as is): a table with open bets. Settle them
    on the old chain first (settle is permissionless); see _lib.banked_tables_in_flight."""
    return [f"table {t} has open bets" for t in _lib.banked_tables_in_flight(storage, TLIST)]


def multiplier(gv, gp, gn, count):
    """In-clear payout after revealing `count` more safe tiles (the reference the pick loop reproduces)."""
    nv = gv
    for i in range(count):
        rem = 25 - gp - i
        nv = nv * rem * 99 // ((rem - gn) * 100)
    return nv


def round_seed(g, beacon=None, bh0=None, bh1=None):
    """In-clear q for resolve_hit: BEACON(gb) + g for a beacon round, BHASH(gh) + BHASH(gh+1) + g for a round
    picked before the beacon rule (gb == 0) — what RESOLVE stores at scratch 2 via _lib.seed_q + `add r3 r0`."""
    base = beacon % F.P if beacon is not None else (bh0 % F.P + bh1 % F.P)
    return (base + g) % F.P


def resolve_hit(q, gp, gn, gc):
    """In-clear: b = the 1-based pick index that hit a mine among this round's gc picks, else 0 (stops at the
    first hit). Mine at pick i iff alghash([q + gp + i]) % (25 - gp - i) < gn. q = round_seed(...): the draws of
    one round are kept distinct by the pick index gp + i, exactly as before the beacon rule."""
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


# pick(g, count): lock `count` blind reveals and bind the round to its beacon epoch (_lib.beacon_bind: gb =
# epoch(cursor) + 2, gh = gb * EPOCH_LENGTH - 1). Every pick re-binds, so each round draws from its own epoch.
# INVARIANT: a round's layout is unknown when it is picked, because BEACON(gb) is revealed during epoch gb - 1, after
# the pick has landed in epoch gb - 2, and resolve's "cursor >= gh + 1" gate is exactly "epoch gb has begun".
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
    slot r4 3 r2
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
""" + _lib.beacon_bind(GH, GB) + """
    slot r4 23 r0
    ctx r5 cursor
    sstore r4 r5
    ret r0
"""

# resolve(g): q = seed_q (BEACON(gb), or BHASH(gh) + BHASH(gh + 1) for a round picked before the beacon rule) + g;
# draw i of the round is alghash(q + gp + i) % (25 - gp - i) < gn (reference: round_seed / resolve_hit).
# INVARIANT: a round picked before the upgrade still resolves on its old rule, because it carries gb == 0 and seed_q
# falls back to the block-hash seed exactly as the old code computed it.
RESOLVE = """
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
""" + _lib.seed_q(GH, GB) + f"""
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
    "open": _lib.open_table(TLIST),
    # bet(g, t, n)[stake]: n mines (1..24); game value starts at the stake
    "bet": """
        ctx r3 value
        movi r4 0
        lt r4 r0
        require r4
        movi r4 0
        lt r4 r3
        require r4
        mov r5 r3
        movi r6 1125899906842624
        lt r5 r6
        require r5
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
        slot r4 4 r1
        sload r6 r4
        add r6 r3
        sstore r4 r6
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
    # reap(g): TIMEOUT -> BANK. A game idle for 18,000 blocks (ge = its last bet/pick/resolve) resolves in favour of
    # the bank, exactly like a bust: the stake stays in the pot (tp, credited at bet time) and joins the bankroll
    # (tk += gs), the at-risk reservation is released (tc -= gq while a round is pending, gv otherwise), the game is
    # marked gd = 2 (timed out) with no hit, and nobody is paid. Permissionless and randomness-free, so tc can never
    # be pinned >0 forever (which would block close_table).
    # INVARIANT: a player is never timed out while they can still act, because reap requires ge + 18000 < cursor,
    # and cashout (no round pending) and resolve (permissionless, open from gh + 1 <= ge + 2 * EPOCH_LENGTH) stay
    # available for that whole window.
    # INVARIANT: the table balances after a reap, because bet/pick added gs to tp and the current exposure to tc,
    # and reap removes exactly that tc term and leaves tp alone — identical to the resolve `lost` path.
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
        movi r6 18000
        add r5 r6
        ctx r6 cursor
        lt r5 r6
        require r5
        slot r4 18 r0
        sload r5 r4
        slot r4 11 r0
        sload r6 r4
        nez r6
        slot r4 21 r0
        sload r3 r4
        sub r3 r5
        mul r3 r6
        add r5 r3
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
        movi r5 2
        sstore r4 r5
        ret r0
    """,
    "fund": _lib.fund_table(),
    "close": _lib.close_table(),
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
        "maps": {**_lib.view_table_maps("tables"),
                 "gg": {"field": GG, "index": "games"}, "gs": {"field": GS, "index": "games"},
                 "ga": {"field": GA, "index": "games"}, "gh": {"field": GH, "index": "games"},
                 "gd": {"field": GD, "index": "games"}, "gn": {"field": GN, "index": "games"},
                 "gv": {"field": GV, "index": "games"}, "gp": {"field": GP, "index": "games"},
                 "gc": {"field": GC, "index": "games"}, "gq": {"field": GQ, "index": "games"},
                 "gx": {"field": GX, "index": "games"}, "ge": {"field": GE, "index": "games"},
                 "gb": {"field": GB, "index": "games"}},
        "indexes": {"tables": {"cnt": 0, "list": TLIST}, "games": {"cnt": 1, "list": GLIST}},
        "addr": ["ta", "ga"],
    },
}


def build():
    # C2 (security review 2026-09-23): every id-taking method refuses an id >= 2^32 before touching a slot;
    # see _lib.id_guard. The ABI, the field layout and every honest call are unchanged.
    ID_GUARDS = {"bet": ["r0", "r1"], "pick": ["r0"], "resolve": ["r0"], "cashout": ["r0"], "reap": ["r0"]}
    return zkvmasm.assemble_contract(_lib.guard_ids(SRC, ID_GUARDS))
