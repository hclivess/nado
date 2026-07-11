#!/usr/bin/env python3
# tests/holdem_onchain.py — the TEXAS HOLD'EM on-chain core: card derivation + a FULL 7-card hand evaluator
# (straight flush … high card, kickers included) as stack-VM bytecode, proven EXACT against a Python
# reference by differential test. This ranks showdowns for real money, so the only bar is byte-for-byte
# agreement between the contract's packed hand value and eval7_ref().
#
# ────────────────────────────────────────────────────────────────────────────────────────────────────────
# THE DEAL (dealer-less, commit-reveal — no house, no mental poker):
#   Cards are ints 0..51: rank = c % 13 (0=deuce … 12=ace), suit = c // 13.
#   draw(seed, slot, excl): candidate a=0,1,2,… c = HASH(seed + slot*4096 + a) % 52, first c not in excl.
#   HOLE  (per seat, secret x): hs = HASH(BH(d0) + BH(d0+1) + x)      -> h0=draw(hs,0,{}), h1=draw(hs,1,{h0})
#   FLOP  (public):            e1 = HASH(BH(d0+S) + BH(d0+S+1) + t)  -> b0,b1,b2 (slots 0,1,2, distinct)
#   TURN:                      e2 = HASH(BH(d0+2S) + BH(d0+2S+1) + t) -> b3 (slot 3, ∉ flop)
#   RIVER:                     e3 = HASH(BH(d0+3S) + BH(d0+3S+1) + t) -> b4 (slot 4, ∉ flop+turn)
#   MULTI-DECK RULE: the board and each player's hand draw from INDEPENDENT decks — exact duplicates across
#   groups are legal and counted naturally (two Kh = a pair of kings). This is the only sound way to keep
#   hole cards hidden without a dealer or mental poker; the odds shift identically for every player.
#
# ────────────────────────────────────────────────────────────────────────────────────────────────────────
# HAND VALUE PACKING (base 14, ranks stored as rank+1 so 0 always means "unused"):
#   value = cat*14^5 + t1*14^4 + t2*14^3 + t3*14^2 + t4*14 + t5
#   cat: 8=straight flush 7=quads 6=full house 5=flush 4=straight 3=trips 2=two pair 1=pair 0=high card
#   Any 7-card hand has value > 0 (high card still packs kickers), so storage 0 == "not revealed".
import sys, os, json, tempfile, hashlib, random
sys.path.insert(0, "/root/nado")

# ── the shared HASH (byte-identical to execnode.vm._hash_value) ─────────────────────────────────────────
def vm_hash(v):
    return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")

# ── PYTHON REFERENCE ────────────────────────────────────────────────────────────────────────────────────
def draw(seed, slot, excl):
    a = 0
    while True:
        c = vm_hash(seed + slot * 4096 + a) % 52
        if c not in excl:
            return c
        a += 1

def hole_ref(bh, d0, x):
    hs = vm_hash(bh[d0] + bh[d0 + 1] + x)
    h0 = draw(hs, 0, ())
    return [h0, draw(hs, 1, (h0,))]

def board_ref_h(bh, c1, c2, c3, t):
    """Board from EXPLICIT street-close heights (the v3 contract lets the host force-close streets, so
    the seeds are the actual close blocks, not a fixed d0+k*S schedule)."""
    e1 = vm_hash(bh[c1] + bh[c1 + 1] + t)
    b0 = draw(e1, 0, ()); b1 = draw(e1, 1, (b0,)); b2 = draw(e1, 2, (b0, b1))
    e2 = vm_hash(bh[c2] + bh[c2 + 1] + t)
    b3 = draw(e2, 3, (b0, b1, b2))
    e3 = vm_hash(bh[c3] + bh[c3 + 1] + t)
    b4 = draw(e3, 4, (b0, b1, b2, b3))
    return [b0, b1, b2, b3, b4]

def board_ref(bh, d0, S, t):
    e1 = vm_hash(bh[d0 + S] + bh[d0 + S + 1] + t)
    b0 = draw(e1, 0, ()); b1 = draw(e1, 1, (b0,)); b2 = draw(e1, 2, (b0, b1))
    e2 = vm_hash(bh[d0 + 2 * S] + bh[d0 + 2 * S + 1] + t)
    b3 = draw(e2, 3, (b0, b1, b2))
    e3 = vm_hash(bh[d0 + 3 * S] + bh[d0 + 3 * S + 1] + t)
    b4 = draw(e3, 4, (b0, b1, b2, b3))
    return [b0, b1, b2, b3, b4]

def _sth(pres):
    """straight high as rank+1 (0=none); MAX over all windows + the wheel, mirroring the bytecode's max-scan."""
    best = 0
    for hi in range(4, 13):
        if all(pres[hi - k] for k in range(5)):
            best = max(best, hi + 1)
    if pres[12] and pres[0] and pres[1] and pres[2] and pres[3]:
        best = max(best, 4)                      # wheel A-2-3-4-5, high card 5 (rank idx 3 -> 3+1)
    return best

def eval7_ref(cards):
    """Packed value of the best 5-of-7 (multi-deck: duplicates allowed, counted naturally)."""
    rc = [0] * 13; sc = [0] * 4
    for c in cards:
        rc[c % 13] += 1; sc[c // 13] += 1
    fs = 0                                       # flush suit + 1 (only one suit can reach 5 of 7)
    for s in range(4):
        if sc[s] >= 5:
            fs = s + 1
    pres = [1 if rc[r] > 0 else 0 for r in range(13)]
    sth = _sth(pres)
    fcnt = [0] * 13                              # per-rank count WITHIN the flush suit (multiplicity kept)
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
    qr  = maxr(lambda r: rc[r] >= 4)
    tr  = maxr(lambda r: rc[r] >= 3)
    p1  = maxr(lambda r: rc[r] >= 2)
    p2  = maxr(lambda r: rc[r] >= 2 and r + 1 != p1)
    fhp = maxr(lambda r: rc[r] >= 2 and r + 1 != tr)
    qk  = maxr(lambda r: rc[r] >= 1 and r + 1 != qr)
    tk1 = maxr(lambda r: rc[r] >= 1 and r + 1 != tr)
    tk2 = maxr(lambda r: rc[r] >= 1 and r + 1 != tr and r + 1 != tk1)
    tpk = maxr(lambda r: rc[r] >= 1 and r + 1 != p1 and r + 1 != p2)
    pk1 = maxr(lambda r: rc[r] >= 1 and r + 1 != p1)
    pk2 = maxr(lambda r: rc[r] >= 1 and r + 1 != p1 and r + 1 != pk1)
    pk3 = maxr(lambda r: rc[r] >= 1 and r + 1 != p1 and r + 1 != pk1 and r + 1 != pk2)
    hk = []
    for _ in range(5):
        hk.append(maxr(lambda r: rc[r] >= 1 and r + 1 not in hk))
    # flush top-5 by rank WITH multiplicity (two Kh both count)
    f = []; wc = fcnt[:]
    for _ in range(5):
        b = 0
        for r in range(13):
            if wc[r] > 0:
                b = max(b, r + 1)
        f.append(b)
        if b:
            wc[b - 1] -= 1
    B = 14
    def pack(cat, t1=0, t2=0, t3=0, t4=0, t5=0):
        return ((((cat * B + t1) * B + t2) * B + t3) * B + t4) * B + t5
    if sfh:            return pack(8, sfh)
    if qr:             return pack(7, qr, qk)
    if tr and fhp:     return pack(6, tr, fhp)
    if fs:             return pack(5, f[0], f[1], f[2], f[3], f[4])
    if sth:            return pack(4, sth)
    if tr:             return pack(3, tr, tk1, tk2)
    if p2:             return pack(2, p1, p2, tpk)
    if p1:             return pack(1, p1, pk1, pk2, pk3)
    return pack(0, hk[0], hk[1], hk[2], hk[3], hk[4])

CAT_NAMES = ["High card", "Pair", "Two pair", "Trips", "Straight", "Flush", "Full house", "Quads", "Straight flush"]

# ── VM ASSEMBLER (lists-of-instructions; `+` composes) ──────────────────────────────────────────────────
MAP = "S"
def P(v):    return [["PUSH", v]]
def LD(m):   return [["MLOAD", m]]
def STm(m):  return [["MSTORE", m]]
def A(i):    return [["ARG", i]]
def LDR(k):  return P(k) + LD(MAP)                 # load named scratch register
def STR(k, val): return P(k) + val + STm(MAP)      # store into named scratch register
def LDK(keyexpr): return keyexpr + LD(MAP)         # load scratch at a COMPUTED key
def STK(keyexpr, valexpr): return keyexpr + valexpr + STm(MAP)
ADD=[["ADD"]]; SUB=[["SUB"]]; MUL=[["MUL"]]; MOD=[["MOD"]]; DIV=[["DIV"]]
EQ=[["EQ"]]; LT=[["LT"]]; GT=[["GT"]]; GTE=[["GTE"]]
AND=[["AND"]]; OR=[["OR"]]; NOT=[["NOT"]]; HASH=[["HASH"]]
JUMPI=[["JUMPI"]]

# key spaces inside the scratch map "S" (re-written on every call before any read):
#   100+r rank counts · 200+s suit counts · 300+r flush-suit rank counts · 400+r flush working copy
RC, SC, FC, WC = 100, 200, 300, 400

def loop_range(lo, hi, body_fn, ctr="i"):
    """i = lo .. hi-1 (body may read LDR(ctr))."""
    ops = STR(ctr, P(lo))
    top = len(ops)
    ops = ops + body_fn() + STR(ctr, LDR(ctr) + P(1) + ADD)
    ops += LDR(ctr) + P(hi) + LT
    j_at = len(ops) + 1
    ops += P(top - j_at) + JUMPI
    return ops

def maxacc(out, cand_expr):
    """out = max(out, cand)  (branchless: out += (c>out)*(c-out))."""
    return (STR("_c", cand_expr)
            + STR(out, LDR(out) + (LDR("_c") + LDR(out) + GT) + (LDR("_c") + LDR(out) + SUB) + MUL + ADD))

def maxr(out, pred_fn):
    """out = max over r=0..12 of pred(r)*(r+1); pred_fn() leaves a bool using LDR('i')."""
    return STR(out, P(0)) + loop_range(0, 13, lambda: maxacc(out, pred_fn() + (LDR("i") + P(1) + ADD) + MUL))

def rc_ge(n):   return LDK(P(RC) + LDR("i") + ADD) + P(n) + GTE
def not_reg(k): return (LDR("i") + P(1) + ADD) + LDR(k) + EQ + NOT

def straight_scan(base, out):
    """out = straight high (rank+1, 0=none) from presence of counts at S[base+r]."""
    ops = STR(out, P(0))
    def body():
        ok = LDK(P(base) + LDR("i") + ADD) + P(1) + GTE
        for k in range(1, 5):
            ok += LDK(P(base) + LDR("i") + ADD + P(k) + SUB) + P(1) + GTE + AND
        return maxacc(out, ok + (LDR("i") + P(1) + ADD) + MUL)
    ops += loop_range(4, 13, body)
    okw = LDK(P(base + 12)) + P(1) + GTE
    for r in range(4):
        okw += LDK(P(base + r)) + P(1) + GTE + AND
    ops += maxacc(out, okw + P(4) + MUL)
    return ops

def draw_ops(seed_reg, slot, excl_regs, out_reg):
    """out = first HASH(seed + slot*4096 + a) % 52 not equal to any excl register, a = 0,1,2,…"""
    ops = STR("a", P(0))
    top = len(ops)
    body = STR(out_reg, LDR(seed_reg) + P(slot * 4096) + ADD + LDR("a") + ADD + HASH + P(52) + MOD)
    body += STR("a", LDR("a") + P(1) + ADD)
    if excl_regs:
        cond = LDR(out_reg) + LDR(excl_regs[0]) + EQ
        for e in excl_regs[1:]:
            cond += LDR(out_reg) + LDR(e) + EQ + OR
    else:
        cond = P(0)
    ops = ops + body + cond
    j_at = len(ops) + 1
    ops += P(top - j_at) + JUMPI
    return ops

CARDS = ["b0", "b1", "b2", "b3", "b4", "h0", "h1"]

def eval7_ops(out_reg="val"):
    """Rank the 7 cards in registers b0..b4,h0,h1 -> packed value in register `out_reg`.
    Every scratch key is written before it is read, so stale state from a prior call can't leak."""
    ops = []
    # rank counts S[100+r], suit counts S[200+s]
    def rc_body():
        val = LDR(CARDS[0]) + P(13) + MOD + LDR("i") + EQ
        for c in CARDS[1:]:
            val += LDR(c) + P(13) + MOD + LDR("i") + EQ + ADD
        return STK(P(RC) + LDR("i") + ADD, val)
    ops += loop_range(0, 13, rc_body)
    def sc_body():
        val = LDR(CARDS[0]) + P(13) + DIV + LDR("i") + EQ
        for c in CARDS[1:]:
            val += LDR(c) + P(13) + DIV + LDR("i") + EQ + ADD
        return STK(P(SC) + LDR("i") + ADD, val)
    ops += loop_range(0, 4, sc_body)
    # flush suit (+1): at most one suit can hold 5 of 7 cards
    fsv = LDK(P(SC)) + P(5) + GTE + P(1) + MUL
    for s in range(1, 4):
        fsv += (LDK(P(SC + s)) + P(5) + GTE) + P(s + 1) + MUL + ADD
    ops += STR("fs", fsv)
    # flush-suit per-rank counts S[300+r]  ((fs-1) never matches a real suit when fs==0)
    def fc_body():
        val = (LDR(CARDS[0]) + P(13) + DIV + (LDR("fs") + P(1) + SUB) + EQ) + (LDR(CARDS[0]) + P(13) + MOD + LDR("i") + EQ) + AND
        for c in CARDS[1:]:
            val += ((LDR(c) + P(13) + DIV + (LDR("fs") + P(1) + SUB) + EQ) + (LDR(c) + P(13) + MOD + LDR("i") + EQ) + AND) + ADD
        return STK(P(FC) + LDR("i") + ADD, val)
    ops += loop_range(0, 13, fc_body)
    # straights
    ops += straight_scan(RC, "sth")
    ops += straight_scan(FC, "sfh")
    # rank-structure scans
    ops += maxr("qr",  lambda: rc_ge(4))
    ops += maxr("tr",  lambda: rc_ge(3))
    ops += maxr("p1",  lambda: rc_ge(2))
    ops += maxr("p2",  lambda: rc_ge(2) + not_reg("p1") + AND)
    ops += maxr("fhp", lambda: rc_ge(2) + not_reg("tr") + AND)
    ops += maxr("qk",  lambda: rc_ge(1) + not_reg("qr") + AND)
    ops += maxr("tk1", lambda: rc_ge(1) + not_reg("tr") + AND)
    ops += maxr("tk2", lambda: rc_ge(1) + not_reg("tr") + AND + not_reg("tk1") + AND)
    ops += maxr("tpk", lambda: rc_ge(1) + not_reg("p1") + AND + not_reg("p2") + AND)
    ops += maxr("pk1", lambda: rc_ge(1) + not_reg("p1") + AND)
    ops += maxr("pk2", lambda: rc_ge(1) + not_reg("p1") + AND + not_reg("pk1") + AND)
    ops += maxr("pk3", lambda: rc_ge(1) + not_reg("p1") + AND + not_reg("pk1") + AND + not_reg("pk2") + AND)
    ops += maxr("hk1", lambda: rc_ge(1))
    ops += maxr("hk2", lambda: rc_ge(1) + not_reg("hk1") + AND)
    ops += maxr("hk3", lambda: rc_ge(1) + not_reg("hk1") + AND + not_reg("hk2") + AND)
    ops += maxr("hk4", lambda: rc_ge(1) + not_reg("hk1") + AND + not_reg("hk2") + AND + not_reg("hk3") + AND)
    ops += maxr("hk5", lambda: rc_ge(1) + not_reg("hk1") + AND + not_reg("hk2") + AND + not_reg("hk3") + AND + not_reg("hk4") + AND)
    # flush top-5 with multiplicity: working copy at S[400+r], 5 max-extractions into f1..f5
    ops += loop_range(0, 13, lambda: STK(P(WC) + LDR("i") + ADD, LDK(P(FC) + LDR("i") + ADD)))
    for n in range(1, 6):
        fn = "f%d" % n
        ops += maxr(fn, lambda: LDK(P(WC) + LDR("i") + ADD) + P(1) + GTE)
        idx = (LDR(fn) + P(0) + GT) + (LDR(fn) + P(1) + SUB) + MUL     # (f>0)*(f-1): 0 when no card left
        ops += STK(P(WC) + idx + ADD, LDK(P(WC) + idx + ADD) + (LDR(fn) + P(0) + GT) + SUB)
    # candidate packed values (base 14), then a priority cascade
    B = 14
    def pack(cat, ts):
        v = P(cat)
        for t in ts:
            v = v + P(B) + MUL + t + ADD
        while len(ts) < 5:
            v = v + P(B) + MUL
            ts = ts + [None]
        return v
    ops += STR("vv", pack(0, [LDR("hk1"), LDR("hk2"), LDR("hk3"), LDR("hk4"), LDR("hk5")]))
    def sel(flag_expr, val_ops):
        # vv = flag ? val : vv
        return (STR("_f", flag_expr) + STR("_v", val_ops)
                + STR("vv", LDR("vv") + LDR("_f") + (LDR("_v") + LDR("vv") + SUB) + MUL + ADD))
    ops += sel(LDR("p1") + P(0) + GT,                       pack(1, [LDR("p1"), LDR("pk1"), LDR("pk2"), LDR("pk3")]))
    ops += sel(LDR("p2") + P(0) + GT,                       pack(2, [LDR("p1"), LDR("p2"), LDR("tpk")]))
    ops += sel(LDR("tr") + P(0) + GT,                       pack(3, [LDR("tr"), LDR("tk1"), LDR("tk2")]))
    ops += sel(LDR("sth") + P(0) + GT,                      pack(4, [LDR("sth")]))
    ops += sel(LDR("fs") + P(0) + GT,                       pack(5, [LDR("f1"), LDR("f2"), LDR("f3"), LDR("f4"), LDR("f5")]))
    ops += sel((LDR("tr") + P(0) + GT) + (LDR("fhp") + P(0) + GT) + AND, pack(6, [LDR("tr"), LDR("fhp")]))
    ops += sel(LDR("qr") + P(0) + GT,                       pack(7, [LDR("qr"), LDR("qk")]))
    ops += sel(LDR("sfh") + P(0) + GT,                      pack(8, [LDR("sfh")]))
    ops += STR(out_reg, LDR("vv"))
    return ops

def deal_ops(hole_seed_ops, e1_ops, e2_ops, e3_ops):
    """Draw the 7 cards into registers: board b0..b4 from the street seeds, hole h0,h1 from the hole seed."""
    ops = STR("s1", e1_ops) + STR("s2", e2_ops) + STR("s3", e3_ops) + STR("hs", hole_seed_ops)
    ops += draw_ops("s1", 0, [], "b0")
    ops += draw_ops("s1", 1, ["b0"], "b1")
    ops += draw_ops("s1", 2, ["b0", "b1"], "b2")
    ops += draw_ops("s2", 3, ["b0", "b1", "b2"], "b3")
    ops += draw_ops("s3", 4, ["b0", "b1", "b2", "b3"], "b4")
    ops += draw_ops("hs", 0, [], "h0")
    ops += draw_ops("hs", 1, ["h0"], "h1")
    return ops

# ── DIFFERENTIAL TEST ───────────────────────────────────────────────────────────────────────────────────
def main():
    from execnode.state import ExecState
    from execnode.vm import GAS_LIMIT
    # method rank7(gid, c0..c6): store eval7 of the given cards at res[gid]
    body = []
    for j, reg in enumerate(CARDS):
        body += STR(reg, A(j + 1))
    body += eval7_ops("val")
    body += A(0) + LDR("val") + STm("res") + [["HALT"]]
    CODE = {"rank7": body}
    print(f"rank7 program length = {len(body)} instructions")

    st = ExecState(tempfile.mktemp())
    st.cursor = 100
    st.apply_blob({"op": "deploy", "code": CODE, "runtime": "stackvm", "nonce": "he"}, "DEP", "d0")
    CID = [c for c, v in st.contracts.items() if v["code"] == CODE][0]

    rng = random.Random(0x401D)
    N = 4000
    mism = 0
    # targeted structures so every category is hit many times, then uniform noise
    def rig(kind):
        if kind == "sf":   # 5+ same suit in sequence
            s = rng.randrange(4); lo = rng.randrange(9)
            cards = [s * 13 + lo + k for k in range(5)] + [rng.randrange(52) for _ in range(2)]
        elif kind == "wheelsf":
            s = rng.randrange(4)
            cards = [s * 13 + r for r in (12, 0, 1, 2, 3)] + [rng.randrange(52) for _ in range(2)]
        elif kind == "quads":
            r = rng.randrange(13)
            cards = [s * 13 + r for s in range(4)] + [rng.randrange(52) for _ in range(3)]
        elif kind == "fh":
            r1, r2 = rng.sample(range(13), 2)
            cards = [s * 13 + r1 for s in range(3)] + [s * 13 + r2 for s in range(2)] + [rng.randrange(52) for _ in range(2)]
        elif kind == "flush":
            s = rng.randrange(4)
            cards = [s * 13 + r for r in rng.sample(range(13), 5)] + [rng.randrange(52) for _ in range(2)]
        elif kind == "straight":
            lo = rng.randrange(9)
            cards = [rng.randrange(4) * 13 + lo + k for k in range(5)] + [rng.randrange(52) for _ in range(2)]
        elif kind == "dup":    # multi-deck duplicates on purpose
            c = rng.randrange(52)
            cards = [c, c] + [rng.randrange(52) for _ in range(5)]
        else:
            cards = [rng.randrange(52) for _ in range(7)]
        rng.shuffle(cards)
        return cards
    kinds = ["sf", "wheelsf", "quads", "fh", "flush", "straight", "dup"] + ["rand"] * 9
    for i in range(1, N + 1):
        cards = rig(kinds[i % len(kinds)])
        res = st.apply_blob({"op": "call", "contract": CID, "method": "rank7", "args": [i] + cards}, "P", f"c{i}")
        got = st.contracts[CID]["storage"].get("res", {}).get(str(i), 0)
        ref = eval7_ref(cards)
        if "revert" in str(res) or got != ref:
            mism += 1
            if mism <= 5:
                print(f"  MISMATCH {cards} -> contract={got} ref={ref} ({res})")
        if i % 500 == 0:
            print(f"  progress {i}/{N} — {mism} mismatch(es)")
    # draw formula differential: whole deal (board + hole) via a contract method vs the reference
    dealer = deal_ops(A(0) + HASH, A(1) + HASH, A(2) + HASH, A(3) + HASH)
    store = []
    for j, reg in enumerate(CARDS):
        store += P(1000 + j) + LDR(reg) + STm("deal")
    DCODE = {"deal": dealer + store + [["HALT"]]}
    st.apply_blob({"op": "deploy", "code": DCODE, "runtime": "stackvm", "nonce": "he2"}, "DEP", "d1")
    DCID = [c for c, v in st.contracts.items() if v["code"] == DCODE][0]
    dmism = 0
    for i in range(500):
        xs = [rng.randrange(2 ** 64) for _ in range(4)]
        st.apply_blob({"op": "call", "contract": DCID, "method": "deal", "args": xs}, "P", f"d{i}")
        got = [st.contracts[DCID]["storage"].get("deal", {}).get(str(1000 + j), 0) for j in range(7)]
        s1, s2, s3, hs = vm_hash(xs[1]), vm_hash(xs[2]), vm_hash(xs[3]), vm_hash(xs[0])
        b0 = draw(s1, 0, ()); b1 = draw(s1, 1, (b0,)); b2 = draw(s1, 2, (b0, b1))
        b3 = draw(s2, 3, (b0, b1, b2)); b4 = draw(s3, 4, (b0, b1, b2, b3))
        h0 = draw(hs, 0, ()); h1 = draw(hs, 1, (h0,))
        if got != [b0, b1, b2, b3, b4, h0, h1]:
            dmism += 1
            if dmism <= 3:
                print(f"  DEAL MISMATCH {xs}: {got} vs {[b0,b1,b2,b3,b4,h0,h1]}")
    ok = (mism == 0 and dmism == 0)
    print(f"\n{'DIFF TEST PASS' if ok else 'DIFF TEST FAIL'}: eval {N-mism}/{N} · deal {500-dmism}/500")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
