#!/usr/bin/env python3
# tests/farkle_onchain.py — a CORRECT on-chain Farkle auto-play scorer as stack-VM bytecode, proven EXACT
# against a Python reference by an exhaustive differential test. This decides who wins real money, so the
# only bar is byte-for-byte agreement between the contract's stored banked score and farkle_ref().
#
# ────────────────────────────────────────────────────────────────────────────────────────────────────────
# THE GAME (auto-play Farkle, "greed threshold" strategy)
#   A player has a seed (big int) and a threshold `thr`. They play ONE turn:
#     remaining=6, total=0, k=0 (GLOBAL running die index across the whole turn).
#     Roll `remaining` dice: die #k = (HASH(seed + k) mod 6) + 1, k advancing 0,1,2,... over the turn.
#     Score the roll -> (score, scoring-dice-count, allScore=did every die THIS roll score).
#       score==0        -> BUST: banked = 0, turn ends.
#       total+=score; total>=thr -> BANK: banked = total, turn ends.
#       remaining = allScore ? 6 : remaining - scoringDiceCount ; repeat.
#     Cap at 40 rolls (unrolled). If the turn never ends in 40 rolls, banked stays 0.
#
#   SCORING one roll of up to 6 dice (faces 1..6), take the MAXIMUM:
#     straight 1-2-3-4-5-6 (needs all six) = 1500, allScore=true.
#     otherwise per face F, c=count: three-of-a-kind base = (F==1?1000:F*100), four=2x, five=4x, six=8x
#       (i.e. base * 2^(c-3) when c>=3); then each leftover single 1 = 100, single 5 = 50 (2,3,4,6 singles
#       score nothing). A face's dice are "scoring dice" when they contribute: ones & fives ALWAYS (as
#       singles when c<3, as the n-of-a-kind when c>=3); 2,3,4,6 only when c>=3 (the whole n-of-a-kind).
#
# ────────────────────────────────────────────────────────────────────────────────────────────────────────
# DIE FORMULA vs the VM's HASH — the contract and any JS client MUST agree on every die. The VM's HASH pops v
# and pushes int.from_bytes(blake2b(json.dumps(v, sort_keys=True), digest_size=32), 'big'). So for an integer
# argument v = seed + k:
#     die = ( int.from_bytes(blake2b(json.dumps(seed+k).encode(), digest_size=32).digest(), 'big') % 6 ) + 1
# This file DEPLOYS a 1-instruction HASH contract and checks vm_hash(x) == the VM's HASH(x) for many x, so
# the reference's dice are provably the VM's dice (see verify_hash_matches_vm()).
#
# ────────────────────────────────────────────────────────────────────────────────────────────────────────
# ARG / STORAGE LAYOUT that score_ops (and the scoreP method) expects
#   Method scoreP is called with args = [gid, seed, thr]:
#       ARG 0 = gid   (game id — the storage KEY the banked score is written under)
#       ARG 1 = seed  (the player's seed; may be a large int)
#       ARG 2 = thr   (greed threshold)
#   Output: the banked score is written to storage map `out_prefix` (default "res") at key = gid, i.e.
#       storage[out_prefix][str(gid)] = banked_score   (0 banks as absence — MSTORE 0 deletes the key).
#   Scratch: one storage map "S" holds the unrolled machine's registers. Carried turn state uses fixed keys
#       d=done  t=total  r=remaining  k=global-die-index  b=banked ; each scoreP call re-initialises them, so
#       leftovers from a prior call never leak (the result depends only on this call's args). Per-roll temps
#       (e0..e5 masked dice, c1..c6 face counts, st straight, fs finalScore, fc finalCount, nt newTotal, act,
#       bust, be bank-event, allsc, bnow bank-now, cont continue) are fully rewritten every roll before use.
import sys, os, json, tempfile, hashlib, random
sys.path.insert(0, "/root/nado")
from execnode.state import ExecState
from execnode.vm import GAS_LIMIT

# ── the shared HASH (byte-identical to execnode.vm._hash_value) ─────────────────────────────────────────
def vm_hash(v):
    return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")

def die(seed, k):
    return (vm_hash(seed + k) % 6) + 1

# ── PYTHON REFERENCE ────────────────────────────────────────────────────────────────────────────────────
def score_roll(dice):
    """Score one roll (list of faces 1..6). Returns (score, scoring_dice_count, all_score)."""
    n = len(dice)
    counts = {f: 0 for f in range(1, 7)}
    for d in dice:
        counts[d] += 1
    # straight (needs all six faces exactly once)
    if n == 6 and all(counts[f] == 1 for f in range(1, 7)):
        return 1500, 6, True
    base = {1: 1000, 2: 200, 3: 300, 4: 400, 5: 500, 6: 600}
    score = 0
    scnt = 0
    for f in range(1, 7):
        c = counts[f]
        if c >= 3:
            score += base[f] * (2 ** (c - 3))
            scnt += c
        else:
            if f == 1:
                score += c * 100
                scnt += c
            elif f == 5:
                score += c * 50
                scnt += c
    return score, scnt, (scnt == n)

def farkle_ref(seed, thr):
    """Reference banked score for a whole auto-play turn (greed threshold `thr`), capped at 40 rolls."""
    remaining, total, k, banked = 6, 0, 0, 0
    for _ in range(40):
        dice = [die(seed, k + i) for i in range(remaining)]
        k += remaining
        score, scnt, allsc = score_roll(dice)
        if score == 0:                 # BUST
            banked = 0
            break
        total += score
        if total >= thr:               # BANK
            banked = total
            break
        remaining = 6 if allsc else (remaining - scnt)
    return banked

# ── VM ASSEMBLER (all helpers return LISTS-OF-INSTRUCTIONS so `+` composes programs) ─────────────────────
MAP = "S"
def P(v):    return [["PUSH", v]]
def LD(m):   return [["MLOAD", m]]
def STm(m):  return [["MSTORE", m]]
def A(i):    return [["ARG", i]]
def LDR(k):  return P(k) + LD(MAP)            # load scratch register `k`
def STR(k, val): return P(k) + val + STm(MAP)  # store `val` (a value-producing op list) into register `k`
ADD=[["ADD"]]; SUB=[["SUB"]]; MUL=[["MUL"]]; MOD=[["MOD"]]
EQ=[["EQ"]]; LT=[["LT"]]; GT=[["GT"]]; GTE=[["GTE"]]
AND=[["AND"]]; OR=[["OR"]]; NOT=[["NOT"]]; HASH=[["HASH"]]

def score_ops(seed_expr, thr_expr, out_prefix, gid_expr=None):
    """Return the fully-unrolled, branchless VM instruction list that plays ONE Farkle turn for a player
    whose seed/threshold are produced by `seed_expr`/`thr_expr` (value-producing op lists), writing the
    banked score to storage map `out_prefix` at key `gid_expr` (default ARG 0). 40 rolls unrolled."""
    if gid_expr is None:
        gid_expr = A(0)
    BASE = {1: 1000, 2: 200, 3: 300, 4: 400, 5: 500, 6: 600}

    def die_ops(p):
        # masked die at roll-position p = (p < remaining) ? ((HASH(seed + k + p) % 6) + 1) : 0
        raw = seed_expr + LDR("k") + ADD + P(p) + ADD + HASH + P(6) + MOD + P(1) + ADD
        mask = P(p) + LDR("r") + LT
        return raw + mask + MUL

    def count_ops(F):
        # count of face F among the six masked dice e0..e5
        ops = LDR("e0") + P(F) + EQ
        for p in range(1, 6):
            ops += LDR("e%d" % p) + P(F) + EQ + ADD
        return ops

    def straight_ops():
        # 1 iff every face count == 1 (implies remaining==6, a genuine 1-2-3-4-5-6)
        ops = LDR("c1") + P(1) + EQ
        for F in range(2, 7):
            ops += LDR("c%d" % F) + P(1) + EQ + AND
        return ops

    def face_score_ops(F):
        cF = "c%d" % F
        # multiplier m = 2^(c-3) for c>=3 else 0  ==  (c==3)*1 + (c==4)*2 + (c==5)*4 + (c==6)*8
        m = (LDR(cF) + P(3) + EQ
             + LDR(cF) + P(4) + EQ + P(2) + MUL + ADD
             + LDR(cF) + P(5) + EQ + P(4) + MUL + ADD
             + LDR(cF) + P(6) + EQ + P(8) + MUL + ADD)
        nkind = P(BASE[F]) + m + MUL
        if F == 1:
            single = LDR(cF) + P(3) + LT + LDR(cF) + MUL + P(100) + MUL   # (c<3)*c*100
            return nkind + single + ADD
        if F == 5:
            single = LDR(cF) + P(3) + LT + LDR(cF) + MUL + P(50) + MUL    # (c<3)*c*50
            return nkind + single + ADD
        return nkind

    def face_cnt_ops(F):
        cF = "c%d" % F
        if F in (1, 5):
            return LDR(cF)                          # ones & fives always score all c dice
        return LDR(cF) + P(3) + GTE + LDR(cF) + MUL # 2,3,4,6 score c dice only when c>=3

    def sum_ops(fn):
        ops = fn(1)
        for F in range(2, 7):
            ops += fn(F) + ADD
        return ops

    def roll_ops():
        ops = []
        for p in range(6):
            ops += STR("e%d" % p, die_ops(p))
        for F in range(1, 7):
            ops += STR("c%d" % F, count_ops(F))
        ops += STR("st", straight_ops())
        sumScore = sum_ops(face_score_ops)
        sumCnt = sum_ops(face_cnt_ops)
        # finalScore = straight ? 1500 : sumScore ; finalCount = straight ? 6 : sumCnt
        ops += STR("fs", LDR("st") + P(1500) + MUL + LDR("st") + NOT + sumScore + MUL + ADD)
        ops += STR("fc", LDR("st") + P(6) + MUL + LDR("st") + NOT + sumCnt + MUL + ADD)
        # turn-logic temporaries
        ops += STR("nt", LDR("t") + LDR("fs") + ADD)                       # newTotal
        ops += STR("act", LDR("d") + NOT)                                  # active = not done
        ops += STR("bust", LDR("fs") + NOT)                                # busted = finalScore==0
        ops += STR("be", LDR("nt") + thr_expr + GTE + LDR("fs") + AND)     # bank-event = nt>=thr and !bust
        ops += STR("allsc", LDR("fc") + LDR("r") + EQ)                     # allScore = finalCount==remaining
        ops += STR("bnow", LDR("act") + LDR("be") + AND)                   # bank happens on THIS roll
        ops += STR("cont", LDR("act") + (LDR("bust") + LDR("be") + OR) + NOT + AND)  # continue rolling
        # state updates — k uses OLD remaining, so store k before r; r stored last.
        ops += STR("k", LDR("k") + LDR("act") + LDR("r") + MUL + ADD)      # k += active*remaining
        ops += STR("t", LDR("t") + LDR("act") + LDR("fs") + MUL + ADD)     # total += active*finalScore
        # banked = bnow ? newTotal : banked
        ops += STR("b", LDR("b") + LDR("bnow") + NOT + MUL + LDR("nt") + LDR("bnow") + MUL + ADD)
        # done = done or (active and (bust or bank))
        ops += STR("d", LDR("d") + LDR("act") + (LDR("bust") + LDR("be") + OR) + AND + OR)
        # remaining = cont ? (allScore ? 6 : remaining-finalCount) : remaining
        newRem = (LDR("allsc") + P(6) + MUL
                  + LDR("allsc") + NOT + (LDR("r") + LDR("fc") + SUB) + MUL + ADD)
        ops += STR("r", LDR("r") + LDR("cont") + NOT + MUL + newRem + LDR("cont") + MUL + ADD)
        return ops

    prog = []
    # initialise carried turn state (fixed keys) — MSTORE 0 deletes -> reads back as 0
    prog += STR("d", P(0)) + STR("t", P(0)) + STR("k", P(0)) + STR("b", P(0)) + STR("r", P(6))
    for _ in range(40):
        prog += roll_ops()
    # write banked score to out_prefix[gid]
    prog += gid_expr + LDR("b") + STm(out_prefix)
    return prog

# ── DIFFERENTIAL TEST ───────────────────────────────────────────────────────────────────────────────────
def verify_hash_matches_vm(st):
    """Prove the reference's die HASH == the VM's HASH by deploying a 1-instruction HASH method."""
    code = {"h": [["ARG", 0], ["HASH"], ["RETURN"]]}
    st.apply_blob({"op": "deploy", "code": code, "runtime": "stackvm", "nonce": "hchk"}, "HASHER", "hchk")
    cid = [c for c, v in st.contracts.items() if v["code"] == code][0]
    sample = [0, 1, 2, 5, 6, 41, 99, 123456789, 2 ** 63, 2 ** 200 + 7, 10 ** 40]
    for x in sample:
        got = st.view(cid, "h", [x])
        assert got == vm_hash(x), f"VM HASH != reference for {x}: {got} vs {vm_hash(x)}"
    return len(sample)

def main():
    OUT = "res"
    CODE = {"scoreP": score_ops(A(1), A(2), OUT)}
    gas = len(CODE["scoreP"])
    print(f"scoreP program length = {gas} instructions (gas per call, every instruction executes; "
          f"limit {GAS_LIMIT})")
    assert gas < GAS_LIMIT, f"scoreP exceeds gas limit ({gas} >= {GAS_LIMIT})"

    st = ExecState(tempfile.mktemp())
    st.cursor = 100
    nsamp = verify_hash_matches_vm(st)
    print(f"die HASH formula verified against the VM's HASH on {nsamp} inputs")

    st.apply_blob({"op": "deploy", "code": CODE, "runtime": "stackvm", "nonce": "farkle"}, "DEP", "d0")
    CID = [c for c, v in st.contracts.items() if v["code"] == CODE][0]

    def stored(gid):
        return st.contracts[CID]["storage"].get(OUT, {}).get(str(gid), 0)

    THRS = [300, 400, 500, 600, 750, 1000, 1250, 1500, 2000, 3000]
    N = 20000
    rng = random.Random(0xFA5C1E)
    mismatches = []
    for i in range(1, N + 1):
        seed = rng.randrange(0, 2 ** 64)
        thr = rng.choice(THRS)
        gid = i
        res = st.apply_blob({"op": "call", "contract": CID, "method": "scoreP", "args": [gid, seed, thr]},
                            "PLAYER", f"call{i}")
        if "revert" in res or "skip" in res:
            mismatches.append((seed, thr, f"CALL-FAILED:{res}", "-"))
            if len(mismatches) <= 5:
                print(f"  mismatch #{len(mismatches)}: seed={seed} thr={thr} -> {res}")
            continue
        onchain = stored(gid)
        ref = farkle_ref(seed, thr)
        if onchain != ref:
            mismatches.append((seed, thr, onchain, ref))
            if len(mismatches) <= 5:
                print(f"  mismatch #{len(mismatches)}: seed={seed} thr={thr} contract={onchain} ref={ref}")
        if i % 2000 == 0:
            print(f"  progress {i}/{N} — {len(mismatches)} mismatch(es) so far")

    if not mismatches:
        print(f"\nDIFF TEST PASS: {N}/{N}")
        print(f"gas cost of one scoreP call = {gas} instructions (< {GAS_LIMIT} limit)")
        return 0
    print(f"\nDIFF TEST FAIL: {N - len(mismatches)}/{N} (first mismatches above)")
    return 1

if __name__ == "__main__":
    sys.exit(main())
