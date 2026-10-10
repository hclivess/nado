"""
Roulette — zkVM port (doc/zk-execution-proofs.md). A banked wheel: a banker opens a table with a bankroll,
players bet a stake covering a set of the 37 numbers (0..36), and each bet settles from the epoch BEACON its
seat was bound to at bet time (bets placed before that rule keep the L1 BLOCKHASH rule), paying 36/coverage on a
hit (single number = 36×). The spin is salted with the SEAT (game) id. A bet not settled within 18,000 blocks of
gh goes to the bank (reclaim). Ported from the deleted stackvm contract.

ARG-PACKING (the >8-arg rework): the old contract took up to 18 number slots as separate args, which
overflows the zkVM's 8-register arg limit. Here the coverage is a single 37-bit MASK arg (bit n = covering
number n). The contract counts the bits in-VM (popcount, a bounded loop) for the payout multiplier, and at
settle extracts bit `roll` of the mask with a bounded shift loop — no VM change, and fewer bytes on-chain.

Table fields:  1 ta  2 tk  3 tp  4 tc  6 tz          Game: 7 gg  8 gmask  9 gs  10 ga  11 gh  12 gr  13 gw
               14 gd  15 gc(coverage count)  18 gb(beacon epoch; 0 = legacy block-hash seat).
Index: slot 0 = table count / field 16 list; slot 1 = game / 17.
Methods: open(t)[bankroll] · bet(g,t,mask)[stake] · settle(g) · reclaim(g) · close(t) · fund(t)[value].
"""
from execnode import zkvmasm
from execnode.games import _lib

TA, TK, TP, TC, TZ = 1, 2, 3, 4, 6
GG, GMASK, GS, GA, GH, GR, GW, GD, GC = 7, 8, 9, 10, 11, 12, 13, 14, 15
TLIST, GLIST = 16, 17


def carry_in_flight(storage):
    """Why this contract's storage cannot cross a reroll yet ([] = it can, as is): a table with open bets. Settle them
    on the old chain first (settle is permissionless); see _lib.banked_tables_in_flight."""
    return [f"table {t} has open bets" for t in _lib.banked_tables_in_flight(storage, TLIST)]
# 18 gb (beacon epoch): added at an unused field for the in-place upgrade. gb == 0 marks a bet placed before the
# beacon rule, which keeps settling from BHASH(gh) + BHASH(gh + 1) (_lib.seed_q).
GB = 18

SRC = {
    "open": _lib.open_table(TLIST),
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
        slot r4 4 r1
        sload r5 r4
        add r5 r6
        slot r4 4 r1
        sstore r4 r5
        slot r4 3 r1
        sload r6 r4
        add r6 r3
        sstore r4 r6
        lt r6 r5
        notb r6
        require r6
        slot r4 9 r0
        sstore r4 r3
        slot r4 7 r0
        sstore r4 r1
        ctx r6 caller
        slot r4 10 r0
        sstore r4 r6
""" + _lib.beacon_bind(GH, GB) + """
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
""" + _lib.seed_q(GH, GB) + """
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
        slot r4 4 r1
        sload r6 r4
        sub r6 r5
        sstore r4 r6
        slot r4 14 r0
        movi r5 1
        sstore r4 r5
        ret r0
    """,
    # reclaim(g): TIMEOUT -> BANK. A bet nobody settled within its window resolves in favour of the bank: the
    # stake stays in the pot (tp), the at-risk reservation stake*36//gc is released from tc, the bet is marked
    # settled with no win and nobody is paid. Permissionless + randomness-free. Mirror of dice.reclaim; the
    # reservation divisor is gc (slot 15), not target.
    # INVARIANT: a winning bet is never timed out to the bank while it can still settle, because reclaim requires
    # gh + 18000 < cursor and settle (permissionless) is open from gh + 1 for the whole 18,000-block window.
    # INVARIANT: the table balances after a reclaim, because bet added stake to tp and stake*36//gc to tc, and
    # reclaim removes exactly that tc term and leaves tp alone — identical to a settled losing spin.
    "reclaim": """
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
        movi r6 18000
        add r5 r6
        ctx r6 cursor
        lt r5 r6
        require r5
        slot r4 9 r0
        sload r3 r4
        movi r6 36
        mul r3 r6
        slot r4 15 r0
        sload r5 r4
        divmod r3 r5
        slot r4 4 r1
        sload r6 r4
        sub r6 r3
        sstore r4 r6
        slot r4 14 r0
        movi r5 1
        sstore r4 r5
        ret r0
    """,
    "close": _lib.close_table(),
    "fund": _lib.fund_table(),
}

ABI = {
    "open": {"args": ["tableId"], "value": True},
    "bet": {"args": ["gameId", "tableId", "mask"], "value": True},
    "settle": {"args": ["gameId"]},
    "reclaim": {"args": ["gameId"]},
    "close": {"args": ["tableId"]},
    "fund": {"args": ["tableId"], "value": True},
    "_view": {
        "maps": {**_lib.view_table_maps("tables"),
                 "gg": {"field": GG, "index": "games"}, "gmask": {"field": GMASK, "index": "games"},
                 "gs": {"field": GS, "index": "games"}, "ga": {"field": GA, "index": "games"},
                 "gh": {"field": GH, "index": "games"}, "gr": {"field": GR, "index": "games"},
                 "gw": {"field": GW, "index": "games"}, "gd": {"field": GD, "index": "games"},
                 "gc": {"field": GC, "index": "games"}, "gb": {"field": GB, "index": "games"}},
        "indexes": {"tables": {"cnt": 0, "list": TLIST}, "games": {"cnt": 1, "list": GLIST}},
        "addr": ["ta", "ga"],
    },
}


def build():
    # C2 (security review 2026-09-23): every id-taking method refuses an id >= 2^32 before touching a slot;
    # see _lib.id_guard. The ABI, the field layout and every honest call are unchanged.
    ID_GUARDS = {"bet": ["r0", "r1"], "settle": ["r0"], "reclaim": ["r0"]}
    return zkvmasm.assemble_contract(_lib.guard_ids(SRC, ID_GUARDS))
