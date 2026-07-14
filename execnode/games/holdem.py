"""
Hold'em — zkVM port (doc/zk-execution-proofs.md). MULTIPLAYER TEXAS HOLD'EM with proper table stakes:
buy-in stacks, all-in, layered SIDE POTS with exact splits, commit-reveal hole cards, beacon community
cards, deadline betting streets, and a FULL ON-CHAIN 7-CARD SHOWDOWN (straight flush … high card, kickers
included) — differentially verified against the python reference in this module. No house, no dealer, no
turn order.

THE DEAL (dealer-less; roll32(x) = LO32(alghash(x)) is the shared window):
    cards are ints 0..51: rank = c % 13 (0=deuce…12=ace), suit = c // 13
    draw(seed, slot, excl): a = 0,1,2,…  c = roll32(seed + slot*4096 + a) % 52, first c ∉ excl
    HOLE  hs = H(bh(d0)+bh(d0+1)+x)  -> h0 = draw(hs,0,{}), h1 = draw(hs,1,{h0})       x = your SECRET
    FLOP  e1 = H(bh(c1)+bh(c1+1)+t)  -> b0,b1,b2 · TURN e2(c2) -> b3 (∉ flop) · RIVER e3(c3) -> b4
    MULTI-DECK RULE: the board and each player's hand draw from INDEPENDENT decks — exact duplicates
    across groups are legal and counted naturally; the only sound dealer-less hidden-card model.
    Commit: gc = H(x) — verified at reveal.

HAND VALUE PACKING (base 14, ranks as rank+1 so 0 = unused; any revealed hand > 0):
    value = cat·14^5 + t1·14^4 + … + t5 · cat: 8 SF · 7 quads · 6 boat · 5 flush · 4 straight ·
    3 trips · 2 two pair · 1 pair · 0 high card

STREETS: b0 = d0 + F0 (the shuffle — cards visible before any bet), street k closes at its host-forced
height sc[k] or c_{k-1}+S; close_street only when nobody owes a call; raises blocked in the last GRACE
blocks; showdown window (c4, c4+R]; settle = layered side pots (uncovered single-contributor layer refunds
— the uncalled-bet rule; uncovered multi-way layer -> best revealed hand) + every unspent stack refunded.

Table fields (key = t): 1 ta 2 t0 3 td 4 ts(ante) 5 tp 6 tn 7 tx 8 tw 9 tb 10 tz · street price 20+k ·
  forced close 25+k · seat ids 40+i (join order, i 0..8). Seat fields (key = g): 11 gg 12 ga 13 gc 14 gk
  15 gd 16 gsc 17 gr · street contribution 30+k. Indexes: tables (cnt 0, list 70) · seats (cnt 2, list 71).
Scratch: reveal/eval 800..899 keyed g · timeline/settle 900..999 keyed t (scrubbed on success; a failed
  call reverts to a no-op). rank_of(c0..c6) is a read-only view of the evaluator for the frontend + fuzz.
Methods: open(t,g,commit,ante)[buyin] · join(t,g,commit)[buyin] · start(t) · leave(g) · bet(g,amt) ·
  close_street(t) · reveal(g,x) · settle(t) · reclaim(t) · cancel(t) · rank_of(c0..c6).
"""
from execnode import zkvmasm
from execnode.stark import alghash, field as F

F0, S, GRACE, R = 14, 20, 5, 60
MAXP = 9
B14 = 14

TA, T0, TD, TS, TP, TN, TX, TW, TB, TZ = 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
GG, GA, GC, GK, GD, GSC, GR = 11, 12, 13, 14, 15, 16, 17
MS_BASE, SCL_BASE, CS_BASE, TI_BASE = 20, 25, 30, 40
TLIST, SLIST = 70, 71
SCNT_SLOT = 2
_2_32 = 1 << 32

# ---- scratch layout ----------------------------------------------------------------------------------
# reveal/eval (fields 800+, keyed g): 800+i cards 0..6 · 810 seed · 820+r rc · 835+s sc · 840+r fcnt ·
#   855 fs · 856 sth · 857.. parked predicate values (see _eval7) · 880..884 flush top-5
EV = 800
EV_CARD, EV_SEED, EV_RC, EV_SC, EV_FC = 800, 810, 820, 835, 840
EV_FS, EV_STH, EV_SFH = 855, 856, 857
EV_QR, EV_TR, EV_P1, EV_P2, EV_FHP, EV_QK, EV_TK1, EV_TK2, EV_TPK, EV_PK1, EV_PK2, EV_PK3 = range(858, 870)
EV_HK, EV_F5, EV_DUMP = 870, 880, 899          # 870..874 kickers · 880..884 flush picks · 899 dump
EV_SCRUB = (list(range(800, 807)) + [810] + list(range(820, 833)) + list(range(835, 839))
            + list(range(840, 853)) + list(range(855, 875)) + list(range(880, 885)) + [899])
# timeline/settle (fields 900+, keyed t): 900 b0 · 901..904 c1..c4 · 905 k · 906 mk · 907 n · 908 i ·
#   909 tmp · 910+i C_i · 920+i V_i · 930+i pay_i · 940+i seat_i · 950 prev 951 act 952 L 953 cnt
#   954 best 955 wins 956 share 957 rem 958 rf 959 ob 960 fst 961 obv 962 obi 963 lc
TL_B0, TL_C1, TL_K, TL_MK, TL_N, TL_I, TL_TMP = 900, 901, 905, 906, 907, 908, 909
TL_C, TL_V, TL_PAY, TL_SID = 910, 920, 930, 940
TL_PREV, TL_ACT, TL_L, TL_CNT, TL_BEST, TL_WINS, TL_SHARE, TL_REM = 950, 951, 952, 953, 954, 955, 956, 957
TL_RF, TL_OB, TL_FST, TL_OBV, TL_OBI, TL_LC = 958, 959, 960, 961, 962, 963
TL_SCRUB = ([TL_B0] + list(range(901, 910)) + list(range(910, 949))
            + list(range(950, 964)))


# ---- python reference (mirrored by static/poker.js; the E2E differentially verifies the bytecode) ----
def roll32(x):
    return alghash.hashn([x % F.P]) & 0xFFFFFFFF


def draw(seed, slot, excl):
    a = 0
    while True:
        c = roll32(seed + slot * 4096 + a) % 52
        if c not in excl:
            return c
        a += 1


def hole_ref(bh0, bh1, x):
    hs = alghash.hashn([(bh0 % F.P + bh1 % F.P + x) % F.P])
    h0 = draw(hs, 0, ())
    return [h0, draw(hs, 1, (h0,))]


def board_ref(bhmap, c1, c2, c3, t):
    e1 = alghash.hashn([(bhmap[c1] % F.P + bhmap[c1 + 1] % F.P + t) % F.P])
    b0 = draw(e1, 0, ()); b1 = draw(e1, 1, (b0,)); b2 = draw(e1, 2, (b0, b1))
    e2 = alghash.hashn([(bhmap[c2] % F.P + bhmap[c2 + 1] % F.P + t) % F.P])
    b3 = draw(e2, 3, (b0, b1, b2))
    e3 = alghash.hashn([(bhmap[c3] % F.P + bhmap[c3 + 1] % F.P + t) % F.P])
    b4 = draw(e3, 4, (b0, b1, b2, b3))
    return [b0, b1, b2, b3, b4]


def _sth(pres):
    best = 0
    for hi in range(4, 13):
        if all(pres[hi - k] for k in range(5)):
            best = max(best, hi + 1)
    if pres[12] and pres[0] and pres[1] and pres[2] and pres[3]:
        best = max(best, 4)
    return best


def eval7_ref(cards):
    rc = [0] * 13; sc = [0] * 4
    for c in cards:
        rc[c % 13] += 1; sc[c // 13] += 1
    fs = 0
    for s in range(4):
        if sc[s] >= 5:
            fs = s + 1
    sth = _sth([1 if rc[r] > 0 else 0 for r in range(13)])
    fcnt = [0] * 13
    for c in cards:
        if fs and c // 13 == fs - 1:
            fcnt[c % 13] += 1
    sfh = _sth([1 if fcnt[r] > 0 else 0 for r in range(13)])

    def maxr(pred):
        best = 0
        for r in range(13):
            if pred(r):
                best = max(best, r + 1)
        return best
    qr = maxr(lambda r: rc[r] >= 4)
    tr = maxr(lambda r: rc[r] >= 3)
    p1 = maxr(lambda r: rc[r] >= 2)
    p2 = maxr(lambda r: rc[r] >= 2 and r + 1 != p1)
    fhp = maxr(lambda r: rc[r] >= 2 and r + 1 != tr)
    qk = maxr(lambda r: rc[r] >= 1 and r + 1 != qr)
    tk1 = maxr(lambda r: rc[r] >= 1 and r + 1 != tr)
    tk2 = maxr(lambda r: rc[r] >= 1 and r + 1 != tr and r + 1 != tk1)
    tpk = maxr(lambda r: rc[r] >= 1 and r + 1 != p1 and r + 1 != p2)
    pk1 = maxr(lambda r: rc[r] >= 1 and r + 1 != p1)
    pk2 = maxr(lambda r: rc[r] >= 1 and r + 1 != p1 and r + 1 != pk1)
    pk3 = maxr(lambda r: rc[r] >= 1 and r + 1 != p1 and r + 1 != pk1 and r + 1 != pk2)
    hk = []
    for _ in range(5):
        hk.append(maxr(lambda r: rc[r] >= 1 and r + 1 not in hk))
    f = []; wc = fcnt[:]
    for _ in range(5):
        b = 0
        for r in range(13):
            if wc[r] > 0:
                b = max(b, r + 1)
        f.append(b)
        if b:
            wc[b - 1] -= 1

    def pack(cat, t1=0, t2=0, t3=0, t4=0, t5=0):
        return ((((cat * B14 + t1) * B14 + t2) * B14 + t3) * B14 + t4) * B14 + t5
    if sfh:
        return pack(8, sfh)
    if qr:
        return pack(7, qr, qk)
    if tr and fhp:
        return pack(6, tr, fhp)
    if fs:
        return pack(5, f[0], f[1], f[2], f[3], f[4])
    if sth:
        return pack(4, sth)
    if tr:
        return pack(3, tr, tk1, tk2)
    if p2:
        return pack(2, p1, p2, tpk)
    if p1:
        return pack(1, p1, pk1, pk2, pk3)
    return pack(0, hk[0], hk[1], hk[2], hk[3], hk[4])


def closes_ref(td, sc_forced):
    b0 = td + F0
    cs = [b0]
    for k in range(1, 5):
        f = sc_forced.get(k, 0) if isinstance(sc_forced, dict) else 0
        cs.append(f if f else cs[-1] + S)
    return cs


CAT_NAMES = ["High card", "Pair", "Two pair", "Trips", "Straight", "Flush", "Full house", "Quads",
             "Straight flush"]


# ---- asm building blocks -------------------------------------------------------------------------------
def _sl(field, key="r0"):
    return [f"slot r4 {field} {key}"]


def _fx(field, key="r0"):
    """r4 = slot(compile-time field, key-reg) — same as _sl (kept for reading clarity in scratch code)."""
    return [f"slot r4 {field} {key}"]


def _fd(base, idx_reg, key="r0"):
    """r4 = slot(base + runtime idx, key): (base+idx)·2^32 + key. Clobbers r4/r5."""
    return [f"movi r4 {base}", f"add r4 {idx_reg}", f"movi r5 {_2_32}", "mul r4 r5", f"add r4 {key}"]


def _roll32(src, out):
    return [f"hash {out} <- {src}", f"lo32 {out}"]


def _max_into(best, val):
    """best = max(best, val) branchless (clobbers r4/r5... uses r6/r7)."""
    return [f"mov r6 {best}", f"lt r6 {val}", f"mov r7 {val}", f"sub r7 {best}",
            f"mul r7 r6", f"add {best} r7"]


def _park(sc_field, reg, key="r0"):
    return _fx(sc_field, key) + [f"sstore r4 {reg}"]


def _load(sc_field, reg, key="r0"):
    return _fx(sc_field, key) + [f"sload {reg} r4"]


def _scrub(fields, key="r0"):
    L = []
    for f_ in fields:
        L += _fx(f_, key) + ["movi r5 0", "sstore r4 r5"]
    return L


def _closes(t_reg="r0"):
    """Timeline into TL scratch keyed t: TL_B0 = td+F0, TL_C1..+3 = c1..c4 (forced or scheduled)."""
    L = _fx(TD, t_reg) + ["sload r3 r4", f"movi r5 {F0}", "add r3 r5"]
    L += _park(TL_B0, "r3", t_reg)
    for k in range(1, 5):
        L += _fx(SCL_BASE + k, t_reg) + ["sload r5 r4", "mov r6 r5", "nez r6",   # r6 = forced?
              "mul r5 r6",
              f"movi r7 {S}", "add r3 r7", "mov r7 r6", "notb r7", "mul r3 r7",
              "add r3 r5"]                                                       # r3 = c_k
        L += _park(TL_C1 + k - 1, "r3", t_reg)
    return L


def _cur_street(out, t_reg="r0"):
    """out = current street k = 1 + Σ(cursor >= c_j) for j=1..3 (timeline in scratch)."""
    L = [f"movi {out} 1"]
    for j in range(1, 4):
        L += _load(TL_C1 + j - 1, "r5", t_reg) + ["ctx r6 cursor", "lt r6 r5", "notb r6", f"add {out} r6"]
    return L


def _ck_select(out, k_reg, t_reg="r0"):
    """out = c_k for runtime k: Σ c_j·(k==j). Internals use r4/r5/r7 only, so out may be r6."""
    L = [f"movi {out} 0"]
    for j in range(1, 5):
        L += _load(TL_C1 + j - 1, "r5", t_reg) + [f"movi r4 {j}", f"mov r7 {k_reg}", "eq r7 r4",
                                                  "mul r5 r7", f"add {out} r5"]
    return L


# ---- methods -------------------------------------------------------------------------------------------
OPEN = "\n".join(
    # open(t, g, commit, ante)[buyin] — args: r0=t r1=g r2=commit r3=ante(arg 3)
    ["ctx r5 value", "movi r6 0", "lt r6 r5", "require r6",
     "movi r5 0", "lt r5 r0", "require r5",
     f"movi r5 {_2_32}", "mov r6 r0", "lt r6 r5", "require r6",
     "movi r5 0", "lt r5 r1", "require r5",
     f"movi r5 {_2_32}", "mov r6 r1", "lt r6 r5", "require r6",
     "mov r5 r2", "nez r5", "require r5"]
    + _sl(TA) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    + [f"slot r4 {GG} r1", "sload r5 r4", "nez r5", "notb r5", "require r5"]
    + ["movi r5 0", "lt r5 r3", "require r5",                                    # ante > 0
       "ctx r6 value", "mov r5 r6", "lt r5 r3", "notb r5", "require r5"]         # buyin >= ante
    + ["ctx r5 caller"] + _sl(TA) + ["sstore r4 r5"]
    + _sl(T0) + ["ctx r5 cursor", "sstore r4 r5"]
    + _sl(TS) + ["sstore r4 r3"] + _sl(TP) + ["sstore r4 r3"]
    + _sl(TN) + ["movi r5 1", "sstore r4 r5"]
    + [f"slot r4 {GG} r1", "sstore r4 r0",
       "ctx r5 caller", f"slot r4 {GA} r1", "sstore r4 r5",
       f"slot r4 {GC} r1", "sstore r4 r2",
       "ctx r5 value", "sub r5 r3", f"slot r4 {GK} r1", "sstore r4 r5"]
    + [f"slot r4 {TI_BASE} r0", "sstore r4 r1"]
    + ["movi r4 0", "sload r5 r4", f"slot r6 {TLIST} r5", "sstore r6 r0",
       "movi r3 1", "add r5 r3", "sstore r4 r5"]
    + [f"movi r4 {SCNT_SLOT}", "sload r5 r4", f"slot r6 {SLIST} r5", "sstore r6 r1",
       "movi r3 1", "add r5 r3", "sstore r4 r5", "ret r0"])


def _join():
    # join(t, g, commit)[buyin]
    L = ["ctx r3 value", "movi r5 0", "lt r5 r3", "require r5",
         "movi r5 0", "lt r5 r1", "require r5",
         f"movi r5 {_2_32}", "mov r6 r1", "lt r6 r5", "require r6",
         "mov r5 r2", "nez r5", "require r5"]
    L += [f"slot r4 {GG} r1", "sload r5 r4", "nez r5", "notb r5", "require r5"]
    L += _sl(TA) + ["sload r5 r4", "require r5"]
    L += _sl(TZ) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    L += _sl(TS) + ["sload r6 r4", "mov r5 r3", "lt r5 r6", "notb r5", "require r5"]     # buyin >= ante
    L += _sl(TD) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    L += _sl(TN) + ["sload r5 r4", f"movi r6 {MAXP}", "lt r5 r6", "require r5"]
    # ONE SEAT PER ADDRESS: scan join order (n <= 9, unrolled with an active gate)
    L += _sl(TN) + ["sload r3 r4"]
    for i in range(MAXP):
        L += [f"movi r5 {i}", "lt r5 r3", "jnz r5 @jchk{I}".replace("{I}", str(i)),
              "jmp @jskip{I}".replace("{I}", str(i)), f"jchk{i}:",
              f"slot r4 {TI_BASE + i} r0", "sload r5 r4",
              f"slot r4 {GA} r5", "sload r5 r4", "ctx r6 caller", "eq r5 r6", "notb r5", "require r5",
              f"jskip{i}:"]
    # pot += ante ; seat records ; ti[tn] = g ; tn++
    L += ["ctx r3 value"]
    L += _sl(TS) + ["sload r6 r4"]
    L += _sl(TP) + ["sload r5 r4", "add r5 r6", "sstore r4 r5"]
    L += [f"slot r4 {GG} r1", "sstore r4 r0",
          "ctx r5 caller", f"slot r4 {GA} r1", "sstore r4 r5",
          f"slot r4 {GC} r1", "sstore r4 r2",
          "mov r5 r3", "sub r5 r6", f"slot r4 {GK} r1", "sstore r4 r5"]
    L += _sl(TN) + ["sload r5 r4"] + _fd(TI_BASE, "r5") + ["sstore r4 r1"]
    L += _sl(TN) + ["sload r5 r4", "movi r6 1", "add r5 r6", "sstore r4 r5"]
    L += [f"movi r4 {SCNT_SLOT}", "sload r5 r4", f"slot r6 {SLIST} r5", "sstore r6 r1",
          "movi r3 1", "add r5 r3", "sstore r4 r5", "ret r0"]
    return L


START = "\n".join(
    ["ctx r5 caller"] + _sl(TA) + ["sload r6 r4", "eq r6 r5", "require r6"]
    + _sl(TZ) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    + _sl(TD) + ["sload r5 r4", "nez r5", "notb r5", "require r5",
                 "ctx r5 cursor", "movi r6 2", "add r5 r6", "sstore r4 r5", "ret r0"])


def _leave():
    # leave(g): full refund before the deal; the last seat fills the leaver's hole (join order compact)
    L = _sl(GG) + ["sload r1 r4", "require r1"]                                  # r1 = t
    L += ["ctx r5 caller"] + _sl(GA) + ["sload r6 r4", "eq r6 r5", "require r6"]
    L += _fx(TZ, "r1") + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    L += _fx(TD, "r1") + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    L += ["ctx r5 caller"] + _fx(TA, "r1") + ["sload r6 r4", "eq r6 r5", "notb r6", "require r6"]
    L += _fx(TN, "r1") + ["sload r3 r4"]                                         # r3 = n
    # ix -> r2 (branchless argmax of the match flag; unrolled over MAXP with active gate)
    L += ["movi r2 0"]
    for i in range(MAXP):
        L += [f"movi r5 {i}", "lt r5 r3", "jnz r5 @lchk{I}".replace("{I}", str(i)),
              "jmp @lskip{I}".replace("{I}", str(i)), f"lchk{i}:",
              f"slot r4 {TI_BASE + i} r1", "sload r5 r4", "eq r5 r0",
              f"movi r6 {i}", "mul r5 r6", "add r2 r5",
              f"lskip{i}:"]
    # ti[ix] = ti[n-1] ; tn-- ; tp -= ante ; refund ante + stack
    L += ["mov r5 r3", "movi r6 1", "sub r5 r6"] + _fd(TI_BASE, "r5", "r1") + ["sload r5 r4"]
    L += _fd(TI_BASE, "r2", "r1") + ["sstore r4 r5"]
    L += _fx(TN, "r1") + ["sload r5 r4", "movi r6 1", "sub r5 r6", "sstore r4 r5"]
    L += _fx(TS, "r1") + ["sload r6 r4"]
    L += _fx(TP, "r1") + ["sload r5 r4", "sub r5 r6", "sstore r4 r5"]
    L += _sl(GK) + ["sload r5 r4", "add r5 r6", "ctx r6 caller", "pay r6 r5"]
    L += _sl(GK) + ["movi r5 0", "sstore r4 r5"] + _sl(GG) + ["movi r5 0", "sstore r4 r5", "ret r0"]
    return L


def _bet():
    # bet(g, amt): stack -> current street. r0 = g, r1 = amt, r2 = t (loaded).
    L = ["ctx r5 value", "nez r5", "notb r5", "require r5",
         "movi r5 0", "lt r5 r1", "require r5"]
    L += _sl(GG) + ["sload r2 r4", "require r2"]
    L += ["ctx r5 caller"] + _sl(GA) + ["sload r6 r4", "eq r6 r5", "require r6"]
    L += _fx(TZ, "r2") + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    L += _sl(GK) + ["sload r5 r4", "mov r6 r5", "lt r6 r1", "notb r6", "require r6"]     # amt <= stack
    L += _fx(TD, "r2") + ["sload r5 r4", "require r5"]
    L += _closes("r2")
    L += _load(TL_B0, "r5", "r2") + ["ctx r6 cursor", "lt r6 r5", "notb r6", "require r6"]
    L += _load(TL_C1 + 3, "r5", "r2") + ["ctx r6 cursor", "lt r6 r5", "require r6"]
    L += _cur_street("r3", "r2")                                                 # r3 = k
    # closed streets j < k must be matched
    for j in range(1, 4):
        L += [f"slot r4 {CS_BASE + j} r0", "sload r5 r4",
              f"slot r4 {MS_BASE + j} r2", "sload r6 r4", "eq r5 r6",
              f"movi r6 {j}", "mov r7 r3", "lt r6 r7", "notb r6",                # j >= k
              "add r5 r6", "nez r5", "require r5"]
    # stack -= amt ; nc = cs[k] + amt ; pot += amt
    L += _sl(GK) + ["sload r5 r4", "sub r5 r1", "sstore r4 r5"]
    L += _fd(CS_BASE, "r3") + ["sload r5 r4", "add r5 r1", "sstore r4 r5"]
    L += _park(TL_TMP, "r5", "r2")                                               # nc parked
    L += _fx(TP, "r2") + ["sload r5 r4", "add r5 r1", "sstore r4 r5"]
    # isRaise = nc > ms[k] -> r1 (amt is dead)
    L += _fd(MS_BASE, "r3", "r2") + ["sload r6 r4"]
    L += _load(TL_TMP, "r5", "r2") + ["mov r1 r6", "lt r1 r5"]
    # raises blocked in the last GRACE blocks of THIS street: require !isRaise OR cursor <= ck-GRACE
    L += _ck_select("r6", "r3", "r2")
    L += [f"movi r5 {GRACE}", "sub r6 r5", "ctx r5 cursor", "lt r6 r5",          # late = cursor > ck-GRACE
          "mul r6 r1", "notb r6", "require r6"]
    # ms[k] = mk + isRaise·(nc - mk)   (address parked in r7 — _fd/_load clobber r4/r5)
    L += _fd(MS_BASE, "r3", "r2") + ["mov r7 r4"]
    L += _load(TL_TMP, "r5", "r2")
    L += ["sload r6 r7", "sub r5 r6", "mul r5 r1", "add r6 r5", "sstore r7 r6"]
    L += _scrub([TL_B0, TL_C1, TL_C1 + 1, TL_C1 + 2, TL_C1 + 3, TL_TMP], "r2") + ["ret r0"]
    return L


def _close_street():
    L = ["ctx r5 caller"] + _sl(TA) + ["sload r6 r4", "eq r6 r5", "require r6"]
    L += _sl(TZ) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    L += _sl(TD) + ["sload r5 r4", "require r5"]
    L += _closes("r0")
    L += _load(TL_B0, "r5") + ["ctx r6 cursor", "lt r6 r5", "notb r6", "require r6"]
    L += _load(TL_C1 + 3, "r5") + ["ctx r6 cursor", "lt r6 r5", "require r6"]
    L += _cur_street("r3")
    L += _fd(SCL_BASE, "r3") + ["sload r5 r4", "nez r5", "notb r5", "require r5"]        # not already forced
    L += _ck_select("r6", "r3") + ["ctx r5 cursor", "movi r7 2", "add r5 r7", "lt r5 r6", "require r5"]
    # every seat: matched ms[k] OR all-in OR folded earlier
    L += _fd(MS_BASE, "r3") + ["sload r5 r4"] + _park(TL_MK, "r5")
    L += _sl(TN) + ["sload r2 r4"]                                               # r2 = n
    for i in range(MAXP):
        L += [f"movi r5 {i}", "lt r5 r2", "jnz r5 @cchk{I}".replace("{I}", str(i)),
              "jmp @cskip{I}".replace("{I}", str(i)), f"cchk{i}:",
              f"slot r4 {TI_BASE + i} r0", "sload r1 r4"]                        # g -> r1
        L += _fd(CS_BASE, "r3", "r1") + ["sload r5 r4"]
        L += _load(TL_MK, "r6") + ["eq r5 r6"]                                   # matched
        L += [f"slot r4 {GK} r1", "sload r6 r4", "nez r6", "notb r6", "add r5 r6"]       # all-in
        for j in range(1, 4):
            L += [f"slot r4 {CS_BASE + j} r1", "sload r6 r4",
                  f"slot r4 {MS_BASE + j} r0", "sload r7 r4", "eq r6 r7", "notb r6",
                  f"movi r7 {j}", "mov r4 r3"]
            L = L[:-1]
            L += ["mov r6 r6"]  # keep list shape simple; recompute below
            L = L[:-1]
            L += [f"movi r7 {j}", "mov r4 r7"]
            L = L[:-2]
            # folded_j = unmatched_j AND (j < k): j compile-time, k in r3
            L += [f"movi r7 {j}", "lt r7 r3", "mul r6 r7", "add r5 r6"]
        L += ["nez r5", "require r5", f"cskip{i}:"]
    L += _fd(SCL_BASE, "r3") + ["ctx r5 cursor", "movi r6 2", "add r5 r6", "sstore r4 r5"]
    L += _scrub([TL_B0, TL_C1, TL_C1 + 1, TL_C1 + 2, TL_C1 + 3, TL_MK]) + ["ret r0"]
    return L


def _draw_card(idx, slot, excl_from, excl_n, tag):
    """Draw card #idx into EV scratch (keyed g): retry until ∉ {cards excl_from..excl_from+excl_n-1}."""
    L = ["movi r1 0", f"{tag}_retry:"]
    L += _load(EV_SEED, "r2") + [f"movi r5 {slot * 4096}", "add r2 r5", "add r2 r1"]
    L += _roll32("r2", "r2") + ["movi r5 52", "rem r2 r5"]
    L += ["movi r3 0"]
    for j in range(excl_from, excl_from + excl_n):
        L += _load(EV_CARD + j, "r5") + ["eq r5 r2", "add r3 r5"]
    L += ["movi r5 1", "add r1 r5", f"jnz r3 @{tag}_retry"]
    L += _park(EV_CARD + idx, "r2")
    return L


def _eval7():
    """Rank EV cards 0..6 -> packed value in r3 at the end. All scans unrolled; uses r1/r2/r3/r5/r6/r7."""
    L = []
    for i in list(range(EV_RC, EV_RC + 13)) + list(range(EV_SC, EV_SC + 4)) + list(range(EV_FC, EV_FC + 13)):
        L += _fx(i) + ["movi r5 0", "sstore r4 r5"]
    # counts
    for c in range(7):
        L += _load(EV_CARD + c, "r2") + ["movi r5 13", "divmod r2 r5"]           # r2 suit, r7 rank
        L += _fd(EV_RC, "r7") + ["sload r5 r4", "movi r6 1", "add r5 r6", "sstore r4 r5"]
        L += _fd(EV_SC, "r2") + ["sload r5 r4", "movi r6 1", "add r5 r6", "sstore r4 r5"]
    # flush suit
    L += ["movi r3 0"]
    for s in range(4):
        L += _load(EV_SC + s, "r5") + ["movi r6 5", "lt r5 r6", "notb r5",
                                       f"movi r6 {s + 1}", "mul r5 r6", "add r3 r5"]
    L += _park(EV_FS, "r3")
    # flush-suit rank counts (fs=0 -> nothing counts). The flag rides in r3 — _fd clobbers r5.
    for c in range(7):
        L += _load(EV_CARD + c, "r2") + ["movi r5 13", "divmod r2 r5",           # r2 suit, r7 rank
              "mov r3 r2", "movi r6 1", "add r3 r6"]
        L += _load(EV_FS, "r6") + ["eq r3 r6"]                                   # in the flush suit?
        L += _fd(EV_FC, "r7") + ["sload r6 r4", "add r6 r3", "sstore r4 r6"]

    def straight_scan(base, out):
        O = [f"movi {out} 0"]
        for hi in range(4, 13):
            O += ["movi r5 1"]
            for k in range(5):
                O += _load(base + hi - k, "r6") + ["nez r6", "mul r5 r6"]
            O += [f"movi r6 {hi + 1}", "mul r5 r6"] + _max_into(out, "r5")
        O += ["movi r5 1"]
        for rr in (12, 0, 1, 2, 3):
            O += _load(base + rr, "r6") + ["nez r6", "mul r5 r6"]
        O += ["movi r6 4", "mul r5 r6"] + _max_into(out, "r5")
        return O
    L += straight_scan(EV_RC, "r2") + _park(EV_STH, "r2")
    L += straight_scan(EV_FC, "r2") + _park(EV_SFH, "r2")

    def scan(dst, n, excl=()):
        """dst = max rank+1 with rc[r] >= n and r+1 != any parked value in excl."""
        O = ["movi r3 0"]
        for r in range(13):
            O += _load(EV_RC + r, "r5") + [f"movi r6 {n}", "lt r5 r6", "notb r5"]
            for x in excl:
                O += _load(x, "r6") + [f"movi r7 {r + 1}", "eq r6 r7", "notb r6", "mul r5 r6"]
            O += [f"movi r6 {r + 1}", "mul r5 r6"] + _max_into("r3", "r5")
        return O + _park(dst, "r3")
    L += scan(EV_QR, 4)
    L += scan(EV_TR, 3)
    L += scan(EV_P1, 2)
    L += scan(EV_P2, 2, (EV_P1,))
    L += scan(EV_FHP, 2, (EV_TR,))
    L += scan(EV_QK, 1, (EV_QR,))
    L += scan(EV_TK1, 1, (EV_TR,))
    L += scan(EV_TK2, 1, (EV_TR, EV_TK1))
    L += scan(EV_TPK, 1, (EV_P1, EV_P2))
    L += scan(EV_PK1, 1, (EV_P1,))
    L += scan(EV_PK2, 1, (EV_P1, EV_PK1))
    L += scan(EV_PK3, 1, (EV_P1, EV_PK1, EV_PK2))
    L += scan(EV_HK, 1)
    L += scan(EV_HK + 1, 1, (EV_HK,))
    L += scan(EV_HK + 2, 1, (EV_HK, EV_HK + 1))
    L += scan(EV_HK + 3, 1, (EV_HK, EV_HK + 1, EV_HK + 2))
    L += scan(EV_HK + 4, 1, (EV_HK, EV_HK + 1, EV_HK + 2, EV_HK + 3))
    # flush top-5 by rank WITH multiplicity: 5 passes over fcnt, decrementing the pick each pass
    for p in range(5):
        L += ["movi r3 0"]
        for r in range(13):
            L += _load(EV_FC + r, "r5") + ["nez r5", f"movi r6 {r + 1}", "mul r5 r6"]
            L += _max_into("r3", "r5")
        L += _park(EV_F5 + p, "r3")
        # fcnt[b-1] -= (b>0): address (EV_FC-1+b) — b=0 lands on the DUMP-adjacent pad (EV_FC-1 = 839, unused)
        L += ["mov r5 r3", "nez r5", "mov r6 r3", f"movi r7 {EV_FC - 1}", "add r6 r7"]
        L += ["movi r4 0"]
        L = L[:-1]
        L += [f"movi r4 {_2_32}", "mul r6 r4", "add r6 r0",
              "mov r4 r6", "sload r7 r4", "sub r7 r5", "sstore r4 r7"]
    # ---- category select + pack -> r3 --------------------------------------------------------------
    def pack_from(cat, parts):
        """r3 = ((((cat·14 + p1)·14 + p2)·14 + p3)·14 + p4)·14 + p5 from parked scratch fields."""
        O = [f"movi r3 {cat}"]
        for p_ in parts:
            O += [f"movi r6 {B14}", "mul r3 r6"]
            if p_ is not None:
                O += _load(p_, "r5") + ["add r3 r5"]
        return O
    Z = [None]
    L += _load(EV_SFH, "r5") + ["jnz r5 @cat_sf"]
    L += _load(EV_QR, "r5") + ["jnz r5 @cat_q"]
    L += _load(EV_TR, "r5") + _load(EV_FHP, "r6") + ["mul r5 r6", "jnz r5 @cat_fh"]
    L += _load(EV_FS, "r5") + ["jnz r5 @cat_fl"]
    L += _load(EV_STH, "r5") + ["jnz r5 @cat_st"]
    L += _load(EV_TR, "r5") + ["jnz r5 @cat_tr"]
    L += _load(EV_P2, "r5") + ["jnz r5 @cat_2p"]
    L += _load(EV_P1, "r5") + ["jnz r5 @cat_1p"]
    L += pack_from(0, [EV_HK, EV_HK + 1, EV_HK + 2, EV_HK + 3, EV_HK + 4]) + ["jmp @cat_done"]
    L += ["cat_sf:"] + pack_from(8, [EV_SFH] + Z * 4) + ["jmp @cat_done"]
    L += ["cat_q:"] + pack_from(7, [EV_QR, EV_QK] + Z * 3) + ["jmp @cat_done"]
    L += ["cat_fh:"] + pack_from(6, [EV_TR, EV_FHP] + Z * 3) + ["jmp @cat_done"]
    L += ["cat_fl:"] + pack_from(5, [EV_F5, EV_F5 + 1, EV_F5 + 2, EV_F5 + 3, EV_F5 + 4]) + ["jmp @cat_done"]
    L += ["cat_st:"] + pack_from(4, [EV_STH] + Z * 4) + ["jmp @cat_done"]
    L += ["cat_tr:"] + pack_from(3, [EV_TR, EV_TK1, EV_TK2] + Z * 2) + ["jmp @cat_done"]
    L += ["cat_2p:"] + pack_from(2, [EV_P1, EV_P2, EV_TPK] + Z * 2) + ["jmp @cat_done"]
    L += ["cat_1p:"] + pack_from(1, [EV_P1, EV_PK1, EV_PK2, EV_PK3] + Z) + ["jmp @cat_done"]
    L += ["cat_done:"]
    return L


def _rank_of():
    """rank_of(c0..c6): read-only evaluator — fuzz target + the frontend's showdown label source."""
    L = []
    # args 0..6 -> EV cards (validate < 52)
    for i in range(7):
        L += [f"movi r5 {i}", "arg r6 r5", "mov r7 r6", "movi r5 52", "lt r7 r5", "require r7"]
        L += _park(EV_CARD + i, "r6")
    L += _eval7()
    L += _scrub(EV_SCRUB) + ["ret r3"]
    return L


def _reveal():
    # reveal(g, x): r0 = g, r1 = x
    L = _sl(GG) + ["sload r2 r4", "require r2"]                                  # r2 = t
    L += _sl(GD) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    L += _fx(TZ, "r2") + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    L += _fx(TD, "r2") + ["sload r5 r4", "require r5"]
    L += _closes("r2")
    L += _load(TL_C1 + 3, "r5", "r2") + ["ctx r6 cursor", "lt r6 r5", "notb r6", "require r6"]
    L += _load(TL_C1 + 3, "r5", "r2") + [f"movi r6 {R}", "add r5 r6",
                                         "ctx r6 cursor", "lt r6 r5", "require r6"]
    # commit check: H(x) == gc
    L += ["hash r5 <- r1"] + _sl(GC) + ["sload r6 r4", "eq r5 r6", "require r5"]
    # table-stakes eligibility: every street matched OR all-in
    for j in range(1, 5):
        L += [f"slot r4 {CS_BASE + j} r0", "sload r5 r4",
              f"slot r4 {MS_BASE + j} r2", "sload r6 r4", "eq r5 r6",
              f"slot r4 {GK} r0", "sload r6 r4", "nez r6", "notb r6",
              "add r5 r6", "nez r5", "require r5"]
    # hole seed hs = H(bh(d0)+bh(d0+1)+x)
    L += _fx(TD, "r2") + ["sload r5 r4", "bhash r3 r5", "movi r6 1", "add r5 r6", "bhash r6 r5",
                          "add r3 r6", "add r3 r1", "hash r3 <- r3"]
    L += _park(EV_SEED, "r3")
    L += _draw_card(0, 0, 0, 0, "h0")
    L += _draw_card(1, 1, 0, 1, "h1")
    # board: e1 from c1 -> b0,b1,b2 · e2 from c2 -> b3 · e3 from c3 -> b4.
    # _draw_card clobbers r1/r2/r3, so t is RELOADED from gg before each street's seed.
    for street, (slots_, tag) in enumerate((((0, 1, 2), "f"), ((3,), "t"), ((4,), "rv"))):
        c_idx = TL_C1 + street
        L += _sl(GG) + ["sload r2 r4"]                                           # r2 = t (fresh)
        L += _load(c_idx, "r5", "r2") + ["bhash r3 r5", "movi r6 1", "add r5 r6", "bhash r6 r5",
                                         "add r3 r6", "add r3 r2", "hash r3 <- r3"]
        L += _park(EV_SEED, "r3")
        for sl_ in slots_:
            # board exclusions: all PRIOR board cards (EV cards 2..2+drawn-1)
            L += _draw_card(2 + sl_, sl_, 2, sl_, f"{tag}{sl_}")
    L += _eval7()                                                                # r3 = hand value (clobbers r2)
    L += _sl(GSC) + ["sstore r4 r3"]
    L += _sl(GR) + ["sstore r4 r1"]
    L += _sl(GD) + ["movi r5 1", "sstore r4 r5"]
    L += _sl(GG) + ["sload r2 r4"]                                               # reload r2 = t
    L += _fx(TX, "r2") + ["sload r5 r4", "movi r6 1", "add r5 r6", "sstore r4 r5"]
    # leaderboard: tw/tb update if better (strict)
    L += _fx(TW, "r2") + ["sload r5 r4", "mov r6 r5", "lt r6 r3"]                # r6 = better
    L += ["mov r7 r3", "sub r7 r5", "mul r7 r6", "add r5 r7", "sstore r4 r5"]
    L += _fx(TB, "r2") + ["sload r5 r4", "mov r7 r0", "sub r7 r5", "mul r7 r6", "add r5 r7", "sstore r4 r5"]
    L += _scrub(EV_SCRUB)
    L += _scrub([TL_B0, TL_C1, TL_C1 + 1, TL_C1 + 2, TL_C1 + 3], "r2") + ["ret r3"]
    return L


def _settle():
    # settle(t): side-pot distribution + stack refunds. r0 = t.
    L = _sl(TA) + ["sload r5 r4", "require r5"]
    L += _sl(TZ) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    L += _sl(TD) + ["sload r5 r4", "require r5"]
    L += _closes("r0")
    # window ended OR everyone revealed
    L += _load(TL_C1 + 3, "r5") + [f"movi r6 {R}", "add r5 r6",
                                   "ctx r6 cursor", "lt r6 r5", "notb r6"]       # cursor >= c4+R
    L += _sl(TX) + ["sload r5 r4"] + _sl(TN) + ["sload r7 r4", "eq r5 r7", "add r6 r5",
                                                "nez r6", "require r6"]
    L += _sl(TB) + ["sload r5 r4", "require r5"]                                 # someone showed
    L += _sl(TN) + ["sload r2 r4"] + _park(TL_N, "r2")
    # phase A: gather per seat i: sid, pay=stack (zeroed), C_i = ante + Σ cs, V_i = gd·gsc
    for i in range(MAXP):
        L += [f"movi r5 {i}", "lt r5 r2", "jnz r5 @ga{I}".replace("{I}", str(i)),
              "jmp @gs{I}".replace("{I}", str(i)), f"ga{i}:",
              f"slot r4 {TI_BASE + i} r0", "sload r1 r4"]                        # g
        L += _park(TL_SID + i, "r1")
        L += [f"slot r4 {GK} r1", "sload r5 r4"] + _park(TL_PAY + i, "r5")
        L += [f"slot r4 {GK} r1", "movi r5 0", "sstore r4 r5"]
        L += _sl(TS) + ["sload r5 r4"]
        for k in range(1, 5):
            L += [f"slot r4 {CS_BASE + k} r1", "sload r6 r4", "add r5 r6"]
        L += _park(TL_C + i, "r5")
        L += [f"slot r4 {GD} r1", "sload r5 r4", f"slot r4 {GSC} r1", "sload r6 r4", "mul r5 r6"]
        L += _park(TL_V + i, "r5", "r0") + [f"gs{i}:"]
    # overall best (first argmax in join order) — fallback for uncovered multi-way layers
    L += ["movi r5 0"] + _park(TL_OBV, "r5") + ["movi r5 0"] + _park(TL_OBI, "r5")
    for i in range(MAXP):
        L += [f"movi r5 {i}", "lt r5 r2", "jnz r5 @ob{I}".replace("{I}", str(i)),
              "jmp @os{I}".replace("{I}", str(i)), f"ob{i}:"]
        L += _load(TL_V + i, "r5") + _load(TL_OBV, "r6") + ["mov r7 r6", "lt r7 r5"]     # better?
        L += ["mov r1 r5", "sub r1 r6", "mul r1 r7"]
        L += _load(TL_OBV, "r6") + ["add r6 r1"] + _park(TL_OBV, "r6")
        L += [f"movi r5 {i}"] + _load(TL_OBI, "r6") + ["sub r5 r6", "mul r5 r7",
                                                       "add r6 r5"] + _park(TL_OBI, "r6")
        L += [f"os{i}:"]
    # phase B: MAXP+1 layer passes
    L += ["movi r5 0"] + _park(TL_PREV, "r5") + ["movi r5 1"] + _park(TL_ACT, "r5")
    L += [f"movi r5 {MAXP + 1}"] + _park(TL_LC, "r5")
    L += ["layer_loop:"]
    # L = min C_i > prev (0 if none)
    L += ["movi r5 0"] + _park(TL_L, "r5")
    for i in range(MAXP):
        L += [f"movi r5 {i}", "lt r5 r2", "jnz r5 @La{I}".replace("{I}", str(i)),
              "jmp @Ls{I}".replace("{I}", str(i)), f"La{i}:"]
        L += _load(TL_C + i, "r1")                                               # c
        L += _load(TL_PREV, "r6") + ["mov r5 r6", "lt r5 r1"]                    # c > prev
        L += _load(TL_L, "r6") + ["mov r7 r6", "nez r7", "notb r7",              # L == 0
              "mov r3 r1", "lt r3 r6", "add r7 r3", "nez r7", "mul r5 r7"]       # or c < L -> take
        L += _load(TL_L, "r6") + ["mov r7 r1", "sub r7 r6", "mul r7 r5", "add r6 r7"] + _park(TL_L, "r6")
        L += [f"Ls{i}:"]
    L += _load(TL_L, "r5") + ["nez r5"] + _load(TL_ACT, "r6") + ["mul r6 r5"] + _park(TL_ACT, "r6")
    # cnt + best among coverers
    L += ["movi r5 0"] + _park(TL_CNT, "r5") + ["movi r5 0"] + _park(TL_BEST, "r5")
    for i in range(MAXP):
        L += [f"movi r5 {i}", "lt r5 r2", "jnz r5 @Ca{I}".replace("{I}", str(i)),
              "jmp @Cs{I}".replace("{I}", str(i)), f"Ca{i}:"]
        L += _load(TL_C + i, "r5") + _load(TL_L, "r6") + ["lt r5 r6", "notb r5"]         # cov
        L += _load(TL_CNT, "r6") + ["add r6 r5"] + _park(TL_CNT, "r6")
        L += _load(TL_V + i, "r6") + ["mul r6 r5"]                               # cov·V
        L += _load(TL_BEST, "r7") + ["mov r5 r7", "lt r5 r6", "sub r6 r7", "mul r6 r5",
                                     "add r7 r6"] + _park(TL_BEST, "r7")
        L += [f"Cs{i}:"]
    # amt = act·(L-prev)·cnt
    L += _load(TL_L, "r5") + _load(TL_PREV, "r6") + ["sub r5 r6"]
    L += _load(TL_ACT, "r6") + ["mul r5 r6"] + _load(TL_CNT, "r6") + ["mul r5 r6"]
    L += _park(TL_TMP, "r5")                                                     # amt
    # wins = ties among covering winners
    L += ["movi r5 0"] + _park(TL_WINS, "r5")
    for i in range(MAXP):
        L += [f"movi r5 {i}", "lt r5 r2", "jnz r5 @Wa{I}".replace("{I}", str(i)),
              "jmp @Ws{I}".replace("{I}", str(i)), f"Wa{i}:"]
        L += _load(TL_C + i, "r5") + _load(TL_L, "r6") + ["lt r5 r6", "notb r5"]
        L += _load(TL_V + i, "r6") + _load(TL_BEST, "r7") + ["eq r6 r7", "mul r5 r6"]
        L += _load(TL_BEST, "r7") + ["nez r7", "mul r5 r7"]
        L += _load(TL_WINS, "r6") + ["add r6 r5"] + _park(TL_WINS, "r6")
        L += [f"Ws{i}:"]
    # share/rem (wmax dodges div-by-0)
    L += _load(TL_WINS, "r5") + ["mov r6 r5", "nez r6", "notb r6", "add r5 r6"]
    L += _load(TL_TMP, "r1") + ["mov r3 r1", "divmod r3 r5"]                     # r3 = share, r7 = rem
    L += _park(TL_SHARE, "r3") + ["mov r5 r7"] + _park(TL_REM, "r5")
    # uncovered flags
    L += _load(TL_BEST, "r5") + ["nez r5", "notb r5"]                            # no revealed coverer
    L += _load(TL_CNT, "r6") + ["movi r7 1", "eq r6 r7", "mul r6 r5"] + _park(TL_RF, "r6")
    L += _load(TL_CNT, "r6") + ["movi r7 1", "lt r7 r6", "mul r6 r5"]
    L = L[:-2]
    L += _load(TL_CNT, "r6") + ["movi r7 1", "mov r1 r7", "lt r1 r6", "mul r1 r5"] + _park(TL_OB, "r1")
    L += ["movi r5 1"] + _park(TL_FST, "r5")
    # payout accumulation per seat
    for i in range(MAXP):
        L += [f"movi r5 {i}", "lt r5 r2", "jnz r5 @Pa{I}".replace("{I}", str(i)),
              "jmp @Ps{I}".replace("{I}", str(i)), f"Pa{i}:"]
        # w = cov AND V==best AND best>0
        L += _load(TL_C + i, "r5") + _load(TL_L, "r6") + ["lt r5 r6", "notb r5"]
        L += _load(TL_V + i, "r6") + _load(TL_BEST, "r7") + ["eq r6 r7", "mul r5 r6"]
        L += _load(TL_BEST, "r7") + ["nez r7", "mul r5 r7"]                      # r5 = w
        L += ["mov r1 r5"]                                                       # r1 = w (kept)
        L += _load(TL_SHARE, "r6") + ["mul r6 r5"]                               # w·share -> r6
        L += _load(TL_FST, "r5") + ["mul r5 r1"] + _load(TL_REM, "r7") + ["mul r5 r7", "add r6 r5"]
        # + rf·cov·amt
        L += _load(TL_C + i, "r5") + _load(TL_L, "r7") + ["lt r5 r7", "notb r5"]
        L += _load(TL_RF, "r7") + ["mul r5 r7"] + _load(TL_TMP, "r7") + ["mul r5 r7", "add r6 r5"]
        # + ob·(i==obi)·amt
        L += _load(TL_OBI, "r5") + [f"movi r7 {i}", "eq r5 r7"]
        L += _load(TL_OB, "r7") + ["mul r5 r7"] + _load(TL_TMP, "r7") + ["mul r5 r7", "add r6 r5"]
        L += _load(TL_PAY + i, "r5") + ["add r5 r6"] + _park(TL_PAY + i, "r5")
        # fst &= !w
        L += ["mov r5 r1", "notb r5"] + _load(TL_FST, "r6") + ["mul r6 r5"] + _park(TL_FST, "r6")
        L += [f"Ps{i}:"]
    # prev += act·(L-prev)
    L += _load(TL_L, "r5") + _load(TL_PREV, "r6") + ["sub r5 r6"]
    L += _load(TL_ACT, "r7") + ["mul r5 r7", "add r6 r5"] + _park(TL_PREV, "r6")
    # loop control
    L += _load(TL_LC, "r5") + ["movi r6 1", "sub r5 r6"] + _park(TL_LC, "r5") + ["jnz r5 @layer_loop"]
    # phase C: one PAY per seat (0 is a no-op amount-wise but PAY(0) still logs — skip zero payouts)
    for i in range(MAXP):
        L += [f"movi r5 {i}", "lt r5 r2", "jnz r5 @Ya{I}".replace("{I}", str(i)),
              "jmp @Yz{I}".replace("{I}", str(i)), f"Ya{i}:"]
        L += _load(TL_PAY + i, "r5") + [f"jnz r5 @Yp{i}", f"jmp @Yz{i}", f"Yp{i}:"]
        L += _load(TL_SID + i, "r6") + [f"slot r4 {GA} r6", "sload r6 r4"]
        L += _load(TL_PAY + i, "r5") + ["pay r6 r5"]
        L += [f"Yz{i}:"]
    L += _sl(TZ) + ["movi r5 1", "sstore r4 r5"] + _sl(TP) + ["movi r5 0", "sstore r4 r5"]
    L += _scrub(TL_SCRUB) + ["ret r0"]
    return L


def _reclaim():
    # reclaim(t): NOBODY revealed — stacks back, the dead pot to the host
    L = ["ctx r5 caller"] + _sl(TA) + ["sload r6 r4", "eq r6 r5", "require r6"]
    L += _sl(TZ) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    L += _sl(TD) + ["sload r5 r4", "require r5"]
    L += _closes("r0")
    L += _load(TL_C1 + 3, "r5") + [f"movi r6 {R}", "add r5 r6",
                                   "ctx r6 cursor", "lt r6 r5", "notb r6", "require r6"]
    L += _sl(TB) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    L += _sl(TN) + ["sload r2 r4"]
    for i in range(MAXP):
        L += [f"movi r5 {i}", "lt r5 r2", "jnz r5 @ra{I}".replace("{I}", str(i)),
              "jmp @rs{I}".replace("{I}", str(i)), f"ra{i}:",
              f"slot r4 {TI_BASE + i} r0", "sload r1 r4",
              f"slot r4 {GK} r1", "sload r5 r4", f"jnz r5 @rp{i}", f"jmp @rz{i}", f"rp{i}:",
              f"slot r4 {GA} r1", "sload r6 r4", "pay r6 r5",
              f"rz{i}:",
              f"slot r4 {GK} r1", "movi r5 0", "sstore r4 r5",
              f"rs{i}:"]
    L += _sl(TA) + ["sload r5 r4"] + _sl(TP) + ["sload r6 r4", "pay r5 r6"]
    L += _sl(TZ) + ["movi r5 1", "sstore r4 r5"] + _sl(TP) + ["movi r5 0", "sstore r4 r5"]
    L += _scrub([TL_B0, TL_C1, TL_C1 + 1, TL_C1 + 2, TL_C1 + 3]) + ["ret r0"]
    return L


CANCEL = "\n".join(
    ["ctx r5 caller"] + _sl(TA) + ["sload r6 r4", "eq r6 r5", "require r6"]
    + _sl(TZ) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    + _sl(TN) + ["sload r5 r4", "movi r6 1", "eq r5 r6", "require r5"]
    + [f"slot r4 {TI_BASE} r0", "sload r1 r4"]
    + [f"slot r4 {GK} r1", "sload r5 r4"] + _sl(TP) + ["sload r6 r4", "add r5 r6",
       "ctx r6 caller", "pay r6 r5"]
    + [f"slot r4 {GK} r1", "movi r5 0", "sstore r4 r5"]
    + _sl(TZ) + ["movi r5 1", "sstore r4 r5"] + _sl(TP) + ["movi r5 0", "sstore r4 r5", "ret r0"])


ABI = {
    "open": {"args": ["tableId", "seatId", "commit", "ante"], "value": True},
    "join": {"args": ["tableId", "seatId", "commit"], "value": True},
    "start": {"args": ["tableId"]},
    "leave": {"args": ["seatId"]},
    "bet": {"args": ["seatId", "amount"]},
    "close_street": {"args": ["tableId"]},
    "reveal": {"args": ["seatId", "secret"]},
    "settle": {"args": ["tableId"]},
    "reclaim": {"args": ["tableId"]},
    "cancel": {"args": ["tableId"]},
    "rank_of": {"args": ["c0", "c1", "c2", "c3", "c4", "c5", "c6"]},
    "_view": {
        "maps": {"ta": {"field": TA, "index": "tables"}, "t0": {"field": T0, "index": "tables"},
                 "td": {"field": TD, "index": "tables"}, "ts": {"field": TS, "index": "tables"},
                 "tp": {"field": TP, "index": "tables"}, "tn": {"field": TN, "index": "tables"},
                 "tx": {"field": TX, "index": "tables"}, "tw": {"field": TW, "index": "tables"},
                 "tb": {"field": TB, "index": "tables"}, "tz": {"field": TZ, "index": "tables"},
                 "gg": {"field": GG, "index": "seats"}, "ga": {"field": GA, "index": "seats"},
                 "gc": {"field": GC, "index": "seats"}, "gk": {"field": GK, "index": "seats"},
                 "gd": {"field": GD, "index": "seats"}, "gsc": {"field": GSC, "index": "seats"},
                 "gr": {"field": GR, "index": "seats"}},
        "indexes": {"tables": {"cnt": 0, "list": TLIST}, "seats": {"cnt": SCNT_SLOT, "list": SLIST}},
        "addr": ["ta", "ga"],
        "board": {"name": "ms", "base": MS_BASE, "cells": 5, "stride": 8, "index": "tables"},
    },
}
# street maps present as <key>*8 + k with k = 1..4 exactly like the old contract (cell 0 is never set, so
# base = the k=0 field keeps the keys aligned); seat ids as ti[t*16+i].
ABI["_view"]["board2"] = {"name": "sc", "base": SCL_BASE, "cells": 5, "stride": 8, "index": "tables"}
ABI["_view"]["board3"] = {"name": "cs", "base": CS_BASE, "cells": 5, "stride": 8, "index": "seats"}
ABI["_view"]["board4"] = {"name": "ti", "base": TI_BASE, "cells": MAXP, "stride": 16, "index": "tables"}


def build():
    src = {
        "open": OPEN,
        "join": "\n".join(_join()),
        "start": START,
        "leave": "\n".join(_leave()),
        "bet": "\n".join(_bet()),
        "close_street": "\n".join(_close_street()),
        "reveal": "\n".join(_reveal()),
        "settle": "\n".join(_settle()),
        "reclaim": "\n".join(_reclaim()),
        "cancel": CANCEL,
        "rank_of": "\n".join(_rank_of()),
    }
    return zkvmasm.assemble_contract(src)
