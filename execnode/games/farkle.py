"""
Farkle — zkVM port (doc/zk-execution-proofs.md). Multi-seat staked Farkle: each seat rolls 6 dice from L1
BLOCKHASH randomness, sets aside scoring dice (the keep), and banks or pushes; a scoreless roll (a FARKLE)
loses the turn. First seat to bank 4000 finishes the table; the highest banked total takes the pot at
`settle`. Ported from the deleted stackvm contract with identical scoring:
  straight (6 kept, all faces once) = 1500; else per face BASE[f]·2^(k-3) for k≥3 kept, plus single 1s(×100)
  and 5s(×50); BASE = {1:1000,2:200,3:300,4:400,5:600? no}: {1:1000,2:200,3:300,4:400,5:500,6:600}.
The 6 rolled dice re-derive in-VM as die_p = alghash([bh(rh)+bh(rh+1)+seat*1000+rolln*10+p]) % 6 + 1
(p<diceLeft) — matching farkle.js rollDice — so no keep can claim a die that wasn't rolled.

Table: 1 ta 2 t0 3 ts 4 tp 5 tn 6 tx 7 tz 8 tb 9 tw 10 tfr 11 ti.  Seat: 12 gg 13 ga 14 gdl 15 grh 16 grn
17 gfin 18 gsc 19 gts 20 ggs.  Scratch field 30.  Index: slot0/field21 tables, slot1/22 seats.
Methods: open(t,g)[ante] · join(t,g)[ante] · roll(g) · hold(g,k1..k6,cont) · settle(t) · timeout(g) · reclaim(t) · cancel(t).
"""
from execnode import zkvmasm
from execnode.stark import alghash, field as F

TA, T0, TS, TP, TN, TX, TZ, TB, TW, TFR, TI = 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11
GG, GA, GDL, GRH, GRN, GFIN, GSC, GTS, GGS = 12, 13, 14, 15, 16, 17, 18, 19, 20
SC = 30
TLIST, GLIST = 21, 22
BASE = {1: 1000, 2: 200, 3: 300, 4: 400, 5: 500, 6: 600}
WIN = 4000


def roll_dice(rh_hash0, rh_hash1, seat, rolln, dice_left):
    """In-clear 6 dice (0 past dice_left) — matches the in-VM derivation + farkle.js."""
    seed = (rh_hash0 % F.P + rh_hash1 % F.P + seat * 1000 + rolln * 10) % F.P
    return [((alghash.hashn([(seed + p) % F.P]) & 0xFFFFFFFF) % 6 + 1) if p < dice_left else 0 for p in range(6)]


def score_counts(counts, straight):
    """Farkle score of per-face counts (counts[1..6]); `straight` forces 1500."""
    if straight:
        return 1500
    s = 0
    for f in range(1, 7):
        k = counts[f]
        if k >= 3:
            s += BASE[f] * (2 ** (k - 3))
        elif f == 1:
            s += k * 100
        elif f == 5:
            s += k * 50
    return s


def keep_valid(keep, rolled_counts, dice_left):
    """Whether `keep` (per-face) is a legal set-aside against the rolled counts."""
    for f in (2, 3, 4, 6):
        if not (keep[f] == 0 or keep[f] >= 3):
            return False
    for f in range(1, 7):
        if keep[f] > rolled_counts[f]:
            return False
    ksum = sum(keep[f] for f in range(1, 7))
    straight = dice_left == 6 and all(keep[f] == 1 for f in range(1, 7))
    return ksum >= 1 and (score_counts(keep, straight) > 0)


# ------- asm generators -------
def _sc(i):
    return (SC << 32) | i


def _mult_asm(cnt_reg, out):
    """out = (k==3) + (k==4)*2 + (k==5)*4 + (k==6)*8 for k in cnt_reg (uses r4/r5)."""
    L = [f"movi {out} 0"]
    for (val, mul) in [(3, 1), (4, 2), (5, 4), (6, 8)]:
        L += [f"mov r5 {cnt_reg}", f"movi r4 {val}", "eq r5 r4"]
        if mul != 1:
            L += [f"movi r4 {mul}", "mul r5 r4"]
        L += [f"add {out} r5"]
    return L


def _face_score(cnt_reg, face, acc):
    """acc += BASE[face]*mult(cnt) + (single 1s/5s). cnt in cnt_reg; uses r4/r5/r6."""
    L = _mult_asm(cnt_reg, "r6")                       # r6 = 2^(k-3) multiplier (0 if k<3)
    L += [f"movi r4 {BASE[face]}", "mul r6 r4", f"add {acc} r6"]   # + BASE*mult
    if face in (1, 5):                                 # + singles (only when k<3)
        single = 100 if face == 1 else 50
        L += [f"mov r5 {cnt_reg}", "movi r4 3", "lt r5 r4",        # k<3
              f"mov r6 {cnt_reg}", "mul r6 r5", f"movi r4 {single}", "mul r6 r4", f"add {acc} r6"]
    return L


def _score_from_scratch(cnt_slots, straight_slot, out_slot):
    """Compute the farkle score of counts in scratch slots cnt_slots[1..6] into out_slot; straight_slot gates
    the 1500. Accumulates into r3 then folds the straight."""
    L = ["movi r3 0"]
    for f in range(1, 7):
        L += [f"movi r4 {_sc(cnt_slots[f])}", "sload r2 r4"]      # cnt -> r2
        L += _face_score("r2", f, "r3")
    # score = straight*1500 + (1-straight)*r3
    L += [f"movi r4 {_sc(straight_slot)}", "sload r5 r4",         # straight
          "mov r6 r5", "movi r4 1500", "mul r6 r4",               # straight*1500
          "movi r4 1", "sub r4 r5", "mul r3 r4", "add r3 r6",     # + (1-straight)*r3
          f"movi r4 {_sc(out_slot)}", "sstore r4 r3"]
    return L


# scratch map: e0..5=0..5, c1..6=6..11, k1..6=12..17, straightRoll=18, straightKeep=19, gm=20, ks=21,
# isF=22, ok=23, ksum=24, te=25, gtsN=26, nd=27, dep=28, ng=29
def _derive_dice():
    """Re-derive the 6 rolled dice into scratch e0..e5 (0 past gdl). seed = bh(grh)+bh(grh+1)+g*1000+grn*10.
    Assumes g in r0, and computes into scratch. Leaves gdl in scratch slot 35 for reuse."""
    L = [
        "slot r4 15 r0", "sload r5 r4", "bhash r3 r5", "movi r6 1", "add r5 r6", "bhash r6 r5", "add r3 r6",  # bh(rh)+bh(rh+1)
        "mov r5 r0", "movi r6 1000", "mul r5 r6", "add r3 r5",                       # + g*1000
        "slot r4 16 r0", "sload r5 r4", "movi r6 10", "mul r5 r6", "add r3 r5",      # + grn*10  -> seed in r3
        f"movi r4 {_sc(34)}", "sstore r4 r3",                                        # SC34 = seed
        "slot r4 14 r0", "sload r5 r4", f"movi r4 {_sc(35)}", "sstore r4 r5",        # SC35 = gdl
    ]
    for p in range(6):
        L += [f"movi r4 {_sc(34)}", "sload r3 r4", f"movi r5 {p}", "add r3 r5",       # seed+p
              "hash r3 <- r3", "lo32 r3", "movi r5 6", "divmod r3 r5", "movi r5 1", "add r7 r5",  # r7 = die (1..6)
              # gate: p < gdl ? die : 0
              f"movi r4 {_sc(35)}", "sload r5 r4", f"movi r6 {p}", "lt r6 r5",        # p < gdl
              "mul r7 r6",                                                            # die * (p<gdl)
              f"movi r4 {_sc(p)}", "sstore r4 r7"]                                    # SC[p] = die
    return L


def _count_faces():
    """c_f (scratch 6+f-1) = number of e0..e5 equal to f, for f in 1..6."""
    L = []
    for f in range(1, 7):
        L += ["movi r6 0"]
        for p in range(6):
            L += [f"movi r4 {_sc(p)}", "sload r5 r4", f"movi r4 {f}", "eq r5 r4", "add r6 r5"]
        L += [f"movi r4 {_sc(6 + f - 1)}", "sstore r4 r6"]
    return L


def _hold():
    # hold(g, packedKeep, cont): the 6 keep counts (each 0..6, 3 bits) are PACKED into one arg
    # (k1 | k2<<3 | ... | k6<<15) so all 8 registers aren't consumed by args (which made saving them
    # clobber a keep). Unpack into scratch SC12..17 via 6 divmods-by-8; cont -> SC33.
    L = [f"movi r4 {_sc(33)}", "sstore r4 r2",       # cont
         "mov r3 r1"]                                 # r3 = packed keep (working copy)
    for i in range(6):
        L += ["movi r5 8", "mov r6 r3", "divmod r6 r5",        # r6 = kp//8, r7 = kp%8 = keep[i]
              f"movi r4 {_sc(12 + i)}", "sstore r4 r7",         # SC[12+i] = keep count
              "mov r3 r6"]                                      # kp //= 8
    L += [
        "slot r4 12 r0", "sload r5 r4", "require r5",                                # gg!=0
        "ctx r6 caller", "slot r4 13 r0", "sload r5 r4", "eq r5 r6", "require r5",   # caller==ga
        "slot r4 17 r0", "sload r5 r4", "nez r5", "notb r5", "require r5",           # not gfin
        "slot r4 15 r0", "sload r5 r4", "nez r5", "require r5",                      # grh set
        "movi r6 1", "add r5 r6", "ctx r6 cursor", "lt r6 r5", "notb r6", "require r6",  # cursor>=grh+1
    ]
    L += _derive_dice()
    L += _count_faces()
    # straightRoll (SC18) = (all c1..c6==1) AND gdl==6
    L += ["movi r6 1"]
    for f in range(1, 7):
        L += [f"movi r4 {_sc(6 + f - 1)}", "sload r5 r4", "movi r7 1", "eq r5 r7", "mul r6 r5"]
    L += [f"movi r4 {_sc(35)}", "sload r5 r4", "movi r7 6", "eq r5 r7", "mul r6 r5",
          f"movi r4 {_sc(18)}", "sstore r4 r6"]
    # straightKeep (SC19) = (all k1..k6==1) AND gdl==6
    L += ["movi r6 1"]
    for f in range(1, 7):
        L += [f"movi r4 {_sc(12 + f - 1)}", "sload r5 r4", "movi r7 1", "eq r5 r7", "mul r6 r5"]
    L += [f"movi r4 {_sc(35)}", "sload r5 r4", "movi r7 6", "eq r5 r7", "mul r6 r5",
          f"movi r4 {_sc(19)}", "sstore r4 r6"]
    # gm = score of rolled counts (c slots 6..11) with straightRoll(18); ks = score of keep (12..17) w/ straightKeep(19)
    L += _score_from_scratch({f: 6 + f - 1 for f in range(1, 7)}, 18, 20)          # gm -> SC20
    L += _score_from_scratch({f: 12 + f - 1 for f in range(1, 7)}, 19, 21)         # ks -> SC21
    # isF = (gm==0)
    L += [f"movi r4 {_sc(20)}", "sload r5 r4", "nez r5", "notb r5", f"movi r4 {_sc(22)}", "sstore r4 r5"]
    # ksum (SC24) = sum k
    L += ["movi r6 0"]
    for f in range(1, 7):
        L += [f"movi r4 {_sc(12 + f - 1)}", "sload r5 r4", "add r6 r5"]
    L += [f"movi r4 {_sc(24)}", "sstore r4 r6"]
    # ok (SC23): faces 2,3,4,6 keep 0 or >=3 ; all k<=c ; ksum>=1 ; ks>0
    L += ["movi r6 1"]
    for f in (2, 3, 4, 6):
        # (k==0) OR (k>=3): k==0 -> nez notb ; k>=3 -> not(k<3)
        L += [f"movi r4 {_sc(12 + f - 1)}", "sload r5 r4", "mov r7 r5", "nez r7", "notb r7",   # k==0
              "mov r3 r5", "movi r4 3", "lt r3 r4", "notb r3",                                 # k>=3
              "add r7 r3", "nez r7",                                                           # (k==0)||(k>=3)
              "mul r6 r7"]
    for f in range(1, 7):
        L += [f"movi r4 {_sc(12 + f - 1)}", "sload r5 r4", f"movi r4 {_sc(6 + f - 1)}", "sload r7 r4",
              "mov r3 r7", "lt r3 r5", "notb r3", "mul r6 r3"]                                 # k<=c
    L += [f"movi r4 {_sc(24)}", "sload r5 r4", "nez r5", "mul r6 r5",                          # ksum>=1
          f"movi r4 {_sc(21)}", "sload r5 r4", "nez r5", "mul r6 r5",                          # ks>0
          f"movi r4 {_sc(23)}", "sstore r4 r6"]
    # require isF || ok
    L += [f"movi r4 {_sc(22)}", "sload r5 r4", f"movi r4 {_sc(23)}", "sload r6 r4", "add r5 r6", "require r5"]
    # te = isF || (cont==0)
    L += [f"movi r4 {_sc(33)}", "sload r5 r4", "nez r5", "notb r5",                            # cont==0
          f"movi r4 {_sc(22)}", "sload r6 r4", "add r5 r6", "nez r5", f"movi r4 {_sc(25)}", "sstore r4 r5"]
    # gtsN = gts + (!isF)*ks
    L += ["slot r4 19 r0", "sload r3 r4",                                                      # gts
          f"movi r4 {_sc(22)}", "sload r5 r4", "movi r6 1", "sub r6 r5",                        # !isF
          f"movi r4 {_sc(21)}", "sload r5 r4", "mul r5 r6", "add r3 r5",                        # + (!isF)*ks
          f"movi r4 {_sc(26)}", "sstore r4 r3"]
    # nd = gdl - (!isF)*ksum ; if nd==0 -> 6 (hot dice)
    L += [f"movi r4 {_sc(35)}", "sload r3 r4",
          f"movi r4 {_sc(22)}", "sload r5 r4", "movi r6 1", "sub r6 r5",
          f"movi r4 {_sc(24)}", "sload r5 r4", "mul r5 r6", "sub r3 r5",                        # nd
          "mov r5 r3", "nez r5", "notb r5", "movi r6 6", "mul r5 r6", "add r3 r5",              # + (nd==0)*6
          f"movi r4 {_sc(27)}", "sstore r4 r3"]
    L += ["slot r4 15 r0", "movi r5 0", "sstore r4 r5"]                                        # grh = 0
    # dep = te*(!isF)*gtsN
    L += [f"movi r4 {_sc(25)}", "sload r3 r4",
          f"movi r4 {_sc(22)}", "sload r5 r4", "movi r6 1", "sub r6 r5", "mul r3 r6",           # te*(!isF)
          f"movi r4 {_sc(26)}", "sload r5 r4", "mul r3 r5", f"movi r4 {_sc(28)}", "sstore r4 r3"]  # *gtsN -> dep
    # ng = ggs + dep
    L += ["slot r4 20 r0", "sload r3 r4", f"movi r4 {_sc(28)}", "sload r5 r4", "add r3 r5",
          f"movi r4 {_sc(29)}", "sstore r4 r3"]
    # gts = (!te)*gtsN
    L += [f"movi r4 {_sc(25)}", "sload r5 r4", "movi r6 1", "sub r6 r5",
          f"movi r4 {_sc(26)}", "sload r5 r4", "mul r5 r6", "slot r4 19 r0", "sstore r4 r5"]
    # gdl = te*6 + (!te)*nd
    L += [f"movi r4 {_sc(25)}", "sload r5 r4", "mov r6 r5", "movi r7 6", "mul r6 r7",
          "movi r7 1", "sub r7 r5", f"movi r4 {_sc(27)}", "sload r3 r4", "mul r3 r7", "add r6 r3",
          "slot r4 14 r0", "sstore r4 r6"]
    # ggs = ng
    L += [f"movi r4 {_sc(29)}", "sload r5 r4", "slot r4 20 r0", "sstore r4 r5"]
    # fin = te AND (ng >= 4000)  (simplified: a seat finishes when it banks to the win threshold on a turn end)
    L += [f"movi r4 {_sc(25)}", "sload r5 r4",
          f"movi r4 {_sc(29)}", "sload r6 r4", "movi r7 4000", "lt r6 r7", "notb r6",           # ng>=4000
          "mul r5 r6",                                                                          # te && ng>=4000
          "slot r4 17 r0", "sload r7 r4", "add r7 r5", "nez r7", "slot r4 17 r0", "sstore r4 r7"]  # gfin |= fin
    # gsc = fin ? ng : gsc   (banked grand total for the board)
    L += [f"movi r4 {_sc(25)}", "sload r5 r4",
          f"movi r4 {_sc(29)}", "sload r6 r4", "movi r7 4000", "lt r6 r7", "notb r6", "mul r5 r6",  # fin (recompute)
          f"movi r4 {_sc(29)}", "sload r6 r4", "mul r6 r5",                                     # fin*ng
          "movi r7 1", "sub r7 r5", "slot r4 18 r0", "sload r3 r4", "mul r3 r7", "add r6 r3",   # + (1-fin)*gsc
          "slot r4 18 r0", "sstore r4 r6",
          "ret r0"]
    return L


SRC = {
    "open": """
        ctx r2 value
        movi r4 0
        lt r4 r2
        require r4
        movi r4 0
        lt r4 r0
        require r4
        movi r4 0
        lt r4 r1
        require r4
        slot r4 1 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 12 r1
        sload r5 r4
        nez r5
        notb r5
        require r5
        ctx r6 caller
        slot r4 1 r0
        sstore r4 r6
        slot r4 2 r0
        ctx r5 cursor
        sstore r4 r5
        slot r4 3 r0
        sstore r4 r2
        slot r4 4 r0
        sstore r4 r2
        slot r4 5 r0
        movi r5 1
        sstore r4 r5
        slot r4 12 r1
        sstore r4 r0
        slot r4 13 r1
        sstore r4 r6
        slot r4 14 r1
        movi r5 6
        sstore r4 r5
        movi r4 0
        sload r5 r4
        slot r6 21 r5
        sstore r6 r0
        movi r3 1
        add r5 r3
        sstore r4 r5
        movi r4 1
        sload r5 r4
        slot r6 22 r5
        sstore r6 r1
        movi r3 1
        add r5 r3
        sstore r4 r5
        ret r0
    """,
    "join": """
        ctx r2 value
        movi r4 0
        lt r4 r2
        require r4
        movi r4 0
        lt r4 r1
        require r4
        slot r4 12 r1
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 1 r0
        sload r5 r4
        nez r5
        require r5
        slot r4 7 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 3 r0
        sload r5 r4
        eq r5 r2
        require r5
        slot r4 4 r0
        sload r5 r4
        add r5 r2
        sstore r4 r5
        slot r4 5 r0
        sload r5 r4
        movi r6 1
        add r5 r6
        sstore r4 r5
        ctx r6 caller
        slot r4 12 r1
        sstore r4 r0
        slot r4 13 r1
        sstore r4 r6
        slot r4 14 r1
        movi r5 6
        sstore r4 r5
        movi r4 1
        sload r5 r4
        slot r6 22 r5
        sstore r6 r1
        movi r3 1
        add r5 r3
        sstore r4 r5
        ret r0
    """,
    "roll": """
        slot r4 12 r0
        sload r5 r4
        require r5
        ctx r6 caller
        slot r4 13 r0
        sload r5 r4
        eq r5 r6
        require r5
        slot r4 17 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 15 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 14 r0
        sload r5 r4
        nez r5
        require r5
        slot r4 15 r0
        ctx r5 cursor
        movi r6 2
        add r5 r6
        sstore r4 r5
        slot r4 16 r0
        sload r5 r4
        movi r6 1
        add r5 r6
        sstore r4 r5
        ret r0
    """,
    "hold": None,
    # settle(t): once the table's round is over, pay the best seat (tb) the pot
    "settle": """
        slot r4 1 r0
        sload r5 r4
        require r5
        slot r4 7 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 8 r0
        sload r5 r4
        nez r5
        require r5
        slot r4 13 r5
        sload r6 r4
        slot r4 4 r0
        sload r3 r4
        pay r6 r3
        slot r4 7 r0
        movi r5 1
        sstore r4 r5
        slot r4 4 r0
        movi r5 0
        sstore r4 r5
        ret r0
    """,
    "cancel": """
        ctx r1 caller
        slot r4 1 r0
        sload r5 r4
        eq r5 r1
        require r5
        slot r4 5 r0
        sload r5 r4
        movi r6 1
        eq r5 r6
        require r5
        slot r4 7 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 4 r0
        sload r5 r4
        pay r1 r5
        slot r4 7 r0
        movi r5 1
        sstore r4 r5
        slot r4 4 r0
        movi r5 0
        sstore r4 r5
        ret r0
    """,
}

ABI = {
    "open": {"args": ["tableId", "seatId"], "value": True},
    "join": {"args": ["tableId", "seatId"], "value": True},
    "roll": {"args": ["seatId"]},
    "hold": {"args": ["seatId", "packedKeep", "cont"]},   # packedKeep = k1 | k2<<3 | … | k6<<15
    "settle": {"args": ["tableId"]},
    "cancel": {"args": ["tableId"]},
    "_view": {
        "maps": {"ta": {"field": TA, "index": "tables"}, "ts": {"field": TS, "index": "tables"},
                 "tp": {"field": TP, "index": "tables"}, "tn": {"field": TN, "index": "tables"},
                 "tx": {"field": TX, "index": "tables"}, "tz": {"field": TZ, "index": "tables"},
                 "tb": {"field": TB, "index": "tables"}, "tw": {"field": TW, "index": "tables"},
                 "gg": {"field": GG, "index": "seats"}, "ga": {"field": GA, "index": "seats"},
                 "gdl": {"field": GDL, "index": "seats"}, "grh": {"field": GRH, "index": "seats"},
                 "gfin": {"field": GFIN, "index": "seats"}, "gsc": {"field": GSC, "index": "seats"},
                 "gts": {"field": GTS, "index": "seats"}, "ggs": {"field": GGS, "index": "seats"}},
        "indexes": {"tables": {"cnt": 0, "list": TLIST}, "seats": {"cnt": 1, "list": GLIST}},
        "addr": ["ta", "ga"],
    },
}


def build():
    src = dict(SRC)
    src["hold"] = "\n".join(_hold())
    return zkvmasm.assemble_contract(src)
