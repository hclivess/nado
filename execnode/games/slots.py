"""
Slots — zkVM port (doc/zk-execution-proofs.md). Player-owned 3-reel slot machines: a banker opens a machine
with a bankroll, a player spins a stake, and once its epoch beacon is final the reels stop from that randomness and
pay per a fixed paytable (up to 150×, RTP 95.796%). Ported from the deleted stackvm contract with the SAME
paytable, so `tests/test_slots.py`'s full enumeration matches.

Randomness (rule consistency with every banked game, _lib.beacon_bind / seed_q): `spin` binds the seat to the epoch
beacon — gb = epoch(cursor) + 2, gh = gb*60 - 1 — and `settle` draws from BEACON(gb). A spin placed before this
rule (gb == 0) keeps settling from BLOCKHASH(gh) + BLOCKHASH(gh+1). INVARIANT: the reels of a seat are a pure
function of (seed, g) because seed is BEACON(gb) or the two block hashes, both final before settle is allowed.

Reels: q = seed + g (seed = BEACON(gb), or BLOCKHASH(gh)+BLOCKHASH(gh+1) when gb == 0);
stop_i = LO32(alghash([q+i])) % 64 (0..63). symbol(stop) counts the
thresholds {16,30,42,52,58,62} → 0..6. 3-of-a-kind pays paytable[sym]; else partial pays for two/one 7s
(sym 6) or two cherries (sym 0). m2 = 2× the multiplier (so ×1.5 stays integer); pay = stake·m2/2.

Table: 1 ta 2 tk 3 tp 4 tc 6 tz 15 tn(spins).  Game: 7 gg 9 gs 10 ga 11 gh 12 gr(packed stops+1) 13 gw(m2) 14 gd
18 gb (beacon epoch; 0 = a spin placed under the block-hash rule).
Scratch (field 30, fixed slots 0..5 = r0,r1,r2,s0,s1,s2; cleared at end).  Index: slot0/field16 tables, slot1/17 games.
Methods: open(t)[bankroll] · spin(g,t)[stake] · settle(g) · claim(g) (timeout -> bank) · fund(t)[value] · close(t).
"""
from execnode import zkvmasm
from execnode.games import _lib

TA, TK, TP, TC, TZ, TN = 1, 2, 3, 4, 6, 15
GG, GS, GA, GH, GR, GW, GD = 7, 9, 10, 11, 12, 13, 14
GB = 18                 # beacon epoch of a spin (unused field before the beacon rule; 0 on every older spin)
HORIZON = 18000         # the settle window: after gh + HORIZON, claim() resolves an unsettled spin to the bank
SC = 30
TLIST, GLIST = 16, 17


def carry_in_flight(storage):
    """Why this contract's storage cannot cross a reroll yet ([] = it can, as is): a table with open bets. Settle them
    on the old chain first (settle is permissionless); see _lib.banked_tables_in_flight."""
    return [f"table {t} has open bets" for t in _lib.banked_tables_in_flight(storage, TLIST)]
THRESH = [16, 30, 42, 52, 58, 62]
# paytable[sym] = 2× multiplier for a 3-of-a-kind of `sym`: [16,20,24,30,60,100,300] -> ×[8,10,12,15,30,50,150]
PT2 = [16, 16 + 4, 16 + 4 + 4, 16 + 4 + 4 + 6, 16 + 4 + 4 + 6 + 30, 16 + 4 + 4 + 6 + 30 + 40,
       16 + 4 + 4 + 6 + 30 + 40 + 200]


def sym_of(stop):
    """The in-clear symbol (0..6) of a reel stop — mirrors the asm + slots.js symOf."""
    return sum(1 for t in THRESH if stop >= t)


def m2_of(stops):
    """The in-clear 2× multiplier for three stops — the reference the AIR settle must reproduce."""
    s = [sym_of(x) for x in stops]
    if s[0] == s[1] == s[2]:
        return PT2[s[0]]
    c7 = sum(1 for x in s if x == 6)
    ch = sum(1 for x in s if x == 0)
    return (10 if c7 == 2 else 0) + (3 if c7 == 1 else 0) + (6 if (c7 == 0 and ch == 2) else 0)


def stops_of(seed, g):
    """The in-clear reel stops the asm settle derives: q = seed + g (mod P), stop_i = LO32(alghash([q+i])) % 64.
    `seed` is BEACON(gb) for a beacon spin, BLOCKHASH(gh) + BLOCKHASH(gh+1) for a spin with gb == 0 (each value
    enters the VM reduced mod P). Mirrors slots.js spinResult (chainResultAlg with salt g + i)."""
    from execnode.stark import alghash, field as F
    q = (int(seed) + int(g)) % F.P
    return [(alghash.hashn([(q + i) % F.P]) & 0xFFFFFFFF) % 64 for i in range(3)]


def seed_of(gb, gh, beacon=None, bh0=None, bh1=None):
    """The randomness base _lib.seed_q loads: BEACON(gb) when gb != 0, else BLOCKHASH(gh) + BLOCKHASH(gh+1)."""
    from execnode.stark import field as F
    if gb:
        return int(beacon) % F.P
    return (int(bh0) % F.P + int(bh1) % F.P) % F.P



def _settle():
    L = []
    def sc(i): return [f"movi r4 {(SC << 32) + i}"]
    # header + q + draws
    L += ["slot r4 7 r0", "sload r1 r4", "require r1",
          "slot r4 14 r0", "sload r5 r4", "nez r5", "notb r5", "require r5",
          "slot r4 11 r0", "sload r5 r4", "movi r6 1", "add r5 r6", "ctx r6 cursor", "lt r6 r5", "notb r6", "require r6",
          ]
    # seed: BEACON(gb) for a beacon spin, BHASH(gh)+BHASH(gh+1) for a spin with gb == 0 (placed before the rule).
    # INVARIANT: the derivation below is unchanged for both — only the base is swapped, so the paytable and
    # salts are identical and a legacy spin settles exactly as it would have before the upgrade.
    L += _lib.seed_q(GH, GB, out="r3", key="r0", tag="sq").strip().splitlines()
    L += ["add r3 r0", "mov r1 r3"]
    for i in range(3):
        L += ["mov r2 r1", f"movi r3 {i}", "add r2 r3", "hash r2 <- r2", "lo32 r2", "movi r3 64", "divmod r2 r3"]
        L += [f"movi r4 {(SC << 32) + i}", "sstore r4 r7"]                    # SC[i] = stop
        L += ["movi r6 0"]
        for t in THRESH:
            L += ["mov r5 r7", f"movi r4 {t}", "lt r5 r4", "notb r5", "add r6 r5"]
        L += [f"movi r4 {(SC << 32) + 3 + i}", "sstore r4 r6"]               # SC[3+i] = symbol
    # now compute m2 from SC[3],SC[4],SC[5]. Put s0->r1, s1->r2, s2->r3
    L += [f"movi r4 {(SC << 32) + 3}", "sload r1 r4", f"movi r4 {(SC << 32) + 4}", "sload r2 r4", f"movi r4 {(SC << 32) + 5}", "sload r3 r4"]
    # tr = (s0==s1)*(s1==s2)  -> r5
    L += ["mov r5 r1", "eq r5 r2", "mov r6 r2", "eq r6 r3", "mul r5 r6"]     # r5 = tr
    L += [f"movi r4 {(SC << 32) + 6}", "sstore r4 r5"]                          # SC[6] = tr
    # t2 = paytable[s0]: 16 + (s0>=1)*4 + (s0>=2)*4 + (s0>=3)*6 + (s0>=4)*30 + (s0>=5)*40 + (s0>=6)*200
    incs = [(1, 4), (2, 4), (3, 6), (4, 30), (5, 40), (6, 200)]
    L += ["movi r6 16"]                                              # r6 = t2 accumulator
    for (thr, add) in incs:
        L += ["mov r5 r1", f"movi r4 {thr}", "lt r5 r4", "notb r5", f"movi r4 {add}", "mul r5 r4", "add r6 r5"]
    L += [f"movi r4 {(SC << 32) + 7}", "sstore r4 r6"]                          # SC[7] = t2
    # c7 = (s0==6)+(s1==6)+(s2==6) ; ch = (s0==0)+(s1==0)+(s2==0)
    L += ["movi r6 0"]
    for reg in ("r1", "r2", "r3"):
        L += [f"mov r5 {reg}", "movi r4 6", "eq r5 r4", "add r6 r5"]
    L += [f"movi r4 {(SC << 32) + 8}", "sstore r4 r6"]                          # SC[8] = c7
    L += ["movi r6 0"]
    for reg in ("r1", "r2", "r3"):
        L += [f"mov r5 {reg}", "nez r5", "notb r5", "add r6 r5"]      # s==0
    L += [f"movi r4 {(SC << 32) + 9}", "sstore r4 r6"]                          # SC[9] = ch
    # partial = (c7==2)*10 + (c7==1)*3 + ((c7==0)*(ch==2))*6
    L += [f"movi r4 {(SC << 32) + 8}", "sload r1 r4"]                           # r1 = c7
    L += ["movi r6 0"]
    L += ["mov r5 r1", "movi r4 2", "eq r5 r4", "movi r4 10", "mul r5 r4", "add r6 r5"]     # (c7==2)*10
    L += ["mov r5 r1", "movi r4 1", "eq r5 r4", "movi r4 3", "mul r5 r4", "add r6 r5"]      # (c7==1)*3
    L += ["mov r5 r1", "nez r5", "notb r5",                                                 # r5=(c7==0)
          f"movi r4 {(SC << 32) + 9}", "sload r4 r4", "movi r3 2", "eq r4 r3", "mul r5 r4",           # *(ch==2)
          "movi r4 6", "mul r5 r4", "add r6 r5"]                                            # *6
    # m2 = tr*t2 + (1-tr)*partial ; tr=SC[6], t2=SC[7]
    L += ["mov r2 r6"]                                               # r2 = partial
    L += [f"movi r4 {(SC << 32) + 6}", "sload r5 r4"]                          # r5 = tr
    L += [f"movi r4 {(SC << 32) + 7}", "sload r6 r4"]                          # r6 = t2
    L += ["mul r6 r5"]                                               # tr*t2
    L += ["movi r4 1", "sub r4 r5", "mul r2 r4", "add r6 r2"]        # + (1-tr)*partial ; r6 = m2
    L += ["slot r4 13 r0", "sstore r4 r6"]                          # gw[g] = m2
    L += [f"movi r4 {(SC << 32) + 10}", "sstore r4 r6"]                        # SC[10] = m2
    # pay = gs*m2/2
    L += ["slot r4 9 r0", "sload r5 r4"]                             # r5 = gs
    L += [f"movi r4 {(SC << 32) + 10}", "sload r6 r4"]                         # r6 = m2
    # pay = gs*m2/2 WITHOUT forming gs*m2: DIVMOD's quotient window is 2^48, so a winning spin above ~3,518
    # NADO could never settle (review 2026-09-23, medium). floor(gs*m2/2) = (gs//2)*m2 + (gs%2)*(m2//2).
    L += ["mov r3 r6", "movi r4 2", "divmod r3 r4"]                  # r3 = m2//2
    L += ["movi r4 2", "divmod r5 r4"]                               # r5 = gs//2, r7 = gs%2
    L += ["mul r5 r6", "mul r7 r3", "add r5 r7"]                     # r5 = pay
    L += [f"movi r4 {(SC << 32) + 11}", "sstore r4 r5"]                        # SC[11] = pay
    L += ["slot r4 10 r0", "sload r6 r4", "pay r6 r5"]              # pay player ga
    # gr = r0stop + r1stop*64 + r2stop*4096 + 1
    L += [f"movi r4 {(SC << 32) + 0}", "sload r1 r4", f"movi r4 {(SC << 32) + 1}", "sload r2 r4", f"movi r4 {(SC << 32) + 2}", "sload r3 r4"]
    L += ["movi r4 64", "mul r2 r4", "add r1 r2", "movi r4 4096", "mul r3 r4", "add r1 r3", "movi r4 1", "add r1 r4"]
    L += ["slot r4 12 r0", "sstore r4 r1"]                           # gr
    # bank accounting: t = gg[g] (reload) ; tp -= pay ; tc -= gs*149 ; tk += gs - pay
    L += ["slot r4 7 r0", "sload r1 r4"]                             # r1 = t
    L += [f"movi r4 {(SC << 32) + 11}", "sload r2 r4"]                         # r2 = pay
    L += ["slot r4 3 r1", "sload r5 r4", "sub r5 r2", "sstore r4 r5"]                       # tp -= pay
    L += ["slot r4 9 r0", "sload r3 r4"]                             # r3 = gs
    L += ["mov r5 r3", "movi r6 149", "mul r5 r6"]                   # gs*149
    L += ["slot r4 4 r1", "sload r6 r4", "sub r6 r5", "sstore r4 r6"]                       # tc -= gs*149
    L += ["mov r5 r3", "sub r5 r2"]                                  # gs - pay
    L += ["slot r4 2 r1", "sload r6 r4", "add r6 r5", "sstore r4 r6"]                       # tk += gs - pay
    L += ["slot r4 14 r0", "movi r5 1", "sstore r4 r5"]             # gd=1
    # clear scratch SC[0..11]
    for i in range(12):
        L += [f"movi r4 {(SC << 32) + i}", "movi r5 0", "sstore r4 r5"]
    L += ["ret r0"]
    return "\n".join(L)


SRC = {
    "open": _lib.open_table(TLIST),
    # spin(g, t)[stake]: reserve a 150x cover (tc += stake*149), like dice bet without a target
    # B2: the seat binds to the epoch beacon (gb, gh = gb*60 - 1) instead of cursor + 2 — every "settle at gh + 1"
    # gate and the HORIZON window keep their meaning. beacon_bind clobbers r4-r7; r0 (g), r1 (t) and r3 (stake)
    # survive it, and everything after reloads what it uses.
    "spin": """
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
        mov r5 r3
        movi r6 149
        mul r5 r6
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
""" + _lib.beacon_bind(GH, GB) + """
        slot r4 2 r1
        sload r5 r4
        movi r4 1
        sload r5 r4
        slot r6 17 r5
        sstore r6 r0
        movi r2 1
        add r5 r2
        sstore r4 r5
        ret r0
    """,
    "settle": None,          # filled by build()
    # claim(g): TIMEOUT -> BANK. A spin nobody settled within HORIZON blocks of gh resolves IN FAVOUR OF THE BANK,
    # exactly like a losing settle: the stake stays in the pot (tp unchanged), the 149x cover is released
    # (tc -= gs*149), the bankroll keeps the stake (tk += gs), the spin is marked settled with no win (gw = 0)
    # and nobody is paid. The method keeps its name so existing clients and the ABI stay valid.
    # INVARIANT: a timeout never pays the player because settle is permissionless and allowed for the whole
    # window — a winning spin is always collectable before claim opens; refunding instead gave every spinner a
    # free option to sit on a losing spin and take the stake back (game fairness, matches blackjack.reap).
    "claim": """
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
        mov r5 r3
        movi r6 149
        mul r5 r6
        slot r4 4 r1
        sload r6 r4
        sub r6 r5
        sstore r4 r6
        slot r4 2 r1
        sload r6 r4
        add r6 r3
        sstore r4 r6
        slot r4 14 r0
        movi r5 1
        sstore r4 r5
        ret r0
    """,
    "fund": _lib.fund_table(),
    "close": _lib.close_table(),
}

ABI = {
    "open": {"args": ["tableId"], "value": True},
    "spin": {"args": ["gameId", "tableId"], "value": True},
    "settle": {"args": ["gameId"]},
    "claim": {"args": ["gameId"]},
    "fund": {"args": ["tableId"], "value": True},
    "close": {"args": ["tableId"]},
    "_view": {
        "maps": {**_lib.view_table_maps("tables"),
                 "gg": {"field": GG, "index": "games"}, "gs": {"field": GS, "index": "games"},
                 "ga": {"field": GA, "index": "games"}, "gh": {"field": GH, "index": "games"},
                 "gr": {"field": GR, "index": "games"}, "gw": {"field": GW, "index": "games"},
                 "gd": {"field": GD, "index": "games"}, "gb": {"field": GB, "index": "games"}},
        "indexes": {"tables": {"cnt": 0, "list": TLIST}, "games": {"cnt": 1, "list": GLIST}},
        "addr": ["ta", "ga"],
    },
}


def build():
    src = dict(SRC)
    src["settle"] = _settle()
    # C2 (security review 2026-09-23): every id-taking method refuses an id >= 2^32 before touching a slot;
    # see _lib.id_guard. The ABI, the field layout and every honest call are unchanged.
    ID_GUARDS = {"spin": ["r0", "r1"], "settle": ["r0"], "claim": ["r0"]}
    return zkvmasm.assemble_contract(_lib.guard_ids(src, ID_GUARDS))
