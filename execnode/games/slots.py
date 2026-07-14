"""
Slots — zkVM port (doc/zk-execution-proofs.md). Player-owned 3-reel slot machines: a banker opens a machine
with a bankroll, a player spins a stake, and ~2 blocks later the reels stop from L1 BLOCKHASH randomness and
pay per a fixed paytable (up to 150×, RTP 95.796%). Ported from the deleted stackvm contract with the SAME
paytable, so `tests/test_slots.py`'s full enumeration matches.

Reels: q = BLOCKHASH(gh)+BLOCKHASH(gh+1)+g; stop_i = alghash([q+i]) % 64 (0..63). symbol(stop) counts the
thresholds {16,30,42,52,58,62} → 0..6. 3-of-a-kind pays paytable[sym]; else partial pays for two/one 7s
(sym 6) or two cherries (sym 0). m2 = 2× the multiplier (so ×1.5 stays integer); pay = stake·m2/2.

Table: 1 ta 2 tk 3 tp 4 tc 6 tz 15 tn(spins).  Game: 7 gg 9 gs 10 ga 11 gh 12 gr(packed stops+1) 13 gw(m2) 14 gd.
Scratch (field 30, fixed slots 0..5 = r0,r1,r2,s0,s1,s2; cleared at end).  Index: slot0/field16 tables, slot1/17 games.
Methods: open(t)[bankroll] · spin(g,t)[stake] · settle(g) · claim(g) · fund(t)[value] · close(t).
"""
from execnode import zkvmasm

TA, TK, TP, TC, TZ, TN = 1, 2, 3, 4, 6, 15
GG, GS, GA, GH, GR, GW, GD = 7, 9, 10, 11, 12, 13, 14
SC = 30
TLIST, GLIST = 16, 17
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



def _settle():
    L = []
    def sc(i): return [f"movi r4 {(SC << 32) + i}"]
    # header + q + draws
    L += ["slot r4 7 r0", "sload r1 r4", "require r1",
          "slot r4 14 r0", "sload r5 r4", "nez r5", "notb r5", "require r5",
          "slot r4 11 r0", "sload r5 r4", "movi r6 1", "add r5 r6", "ctx r6 cursor", "lt r6 r5", "notb r6", "require r6",
          "slot r4 11 r0", "sload r2 r4", "bhash r3 r2", "movi r6 1", "add r2 r6", "bhash r5 r2",
          "add r3 r5", "add r3 r0", "mov r1 r3"]
    for i in range(3):
        L += [f"mov r2 r1", f"movi r3 {i}", "add r2 r3", "hash r2 <- r2", "lo32 r2", "movi r3 64", "divmod r2 r3"]
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
    L += [f"slot r4 13 r0", "sstore r4 r6"]                          # gw[g] = m2
    L += [f"movi r4 {(SC << 32) + 10}", "sstore r4 r6"]                        # SC[10] = m2
    # pay = gs*m2/2
    L += ["slot r4 9 r0", "sload r5 r4"]                             # r5 = gs
    L += [f"movi r4 {(SC << 32) + 10}", "sload r6 r4"]                         # r6 = m2
    L += ["mul r5 r6", "movi r4 2", "divmod r5 r4"]                  # r5 = gs*m2/2 = pay
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
    # spin(g, t)[stake]: reserve a 150x cover (tc += stake*149), like dice bet without a target
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
        slot r4 11 r0
        ctx r6 cursor
        movi r5 2
        add r6 r5
        sstore r4 r6
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
    # claim(g): if a spin was never settled within a long window, the player reclaims their stake
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
        sload r5 r4
        slot r4 10 r0
        sload r6 r4
        pay r6 r5
        slot r4 3 r1
        sload r6 r4
        sub r6 r5
        sstore r4 r6
        slot r4 9 r0
        sload r3 r4
        mov r5 r3
        movi r6 149
        mul r5 r6
        slot r4 4 r1
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
    "spin": {"args": ["gameId", "tableId"], "value": True},
    "settle": {"args": ["gameId"]},
    "claim": {"args": ["gameId"]},
    "fund": {"args": ["tableId"], "value": True},
    "close": {"args": ["tableId"]},
    "_view": {
        "maps": {"ta": {"field": TA, "index": "tables"}, "tk": {"field": TK, "index": "tables"},
                 "tp": {"field": TP, "index": "tables"}, "tc": {"field": TC, "index": "tables"},
                 "tz": {"field": TZ, "index": "tables"},
                 "gg": {"field": GG, "index": "games"}, "gs": {"field": GS, "index": "games"},
                 "ga": {"field": GA, "index": "games"}, "gh": {"field": GH, "index": "games"},
                 "gr": {"field": GR, "index": "games"}, "gw": {"field": GW, "index": "games"},
                 "gd": {"field": GD, "index": "games"}},
        "indexes": {"tables": {"cnt": 0, "list": TLIST}, "games": {"cnt": 1, "list": GLIST}},
        "addr": ["ta", "ga"],
    },
}


def build():
    src = dict(SRC)
    src["settle"] = _settle()
    return zkvmasm.assemble_contract(src)
