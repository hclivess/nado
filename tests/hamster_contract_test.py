"""Hamster Racing contract test — exercises open/bet/settle/claim/void through ExecState and checks the
parimutuel money math, the chain-picked winner, auto-void on an unbacked winner, the betting-window guards,
and global value conservation (no NADO minted or lost). Run: HOME=/root python tests/hamster_contract_test.py
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode.games import hamster as H

A, B, C = "ndoAAA", "ndoBBB", "ndoCCC"
UNIT = H.UNIT


def fresh(cursor=100):
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json")); st.cursor = cursor
    code = H.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": H.ABI, "nonce": "n"}, A, "d")
    cid = st.contract_id(A, code, "n")
    rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
    return st, cid, rd


def set_hashes(st, gh, lk, seed=0xABCDEF):
    st.block_hashes[gh] = seed ^ 0x1111
    for bi in range(1, H.RACE_LEN + 1):
        st.block_hashes[lk + bi] = (seed * (bi + 7) + 0x9E3779B9) & ((1 << 64) - 1)


def total_supply(st, extra):
    return sum(st.bridge.values()) + sum(extra)


passed = failed = 0
def ok(c, m):
    global passed, failed
    if c: passed += 1
    else: failed += 1; print("  FAIL:", m)


# ---- 1. full flow: uneven bets across lanes; verify winner, parimutuel/void payout, conservation ----
def test_full():
    st, cid, rd = fresh()
    for who, amt in ((A, 100 * UNIT), (B, 100 * UNIT), (C, 100 * UNIT)):
        st.credit_deposit(who, amt)
    start = total_supply(st, [])
    R = 777
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [R]}, A, "o")
    gh, lk, fh = rd(H.GH, R), rd(H.LK, R), rd(H.FH, R)
    ok(gh == 102 and lk == 122 and fh == 128, f"1 heights gh{gh} lk{lk} fh{fh}")
    set_hashes(st, gh, lk)
    st.cursor = gh                                             # genes locked, betting open
    # uneven book: A→lane0 (5u), B→lane0 (2u) + lane3 (4u), C→lane1 (3u); lanes 2,4,5 unbacked
    bets = [(A, 0, 5), (B, 0, 2), (B, 3, 4), (C, 1, 3)]
    for who, lane, u in bets:
        st.apply_blob({"op": "call", "contract": cid, "method": "bet", "args": [R, lane], "value": u * UNIT}, who, "b")
    tot = rd(H.TOT, R)
    ok(tot == 14, f"1 pot units {tot}")                       # 5+2+4+3
    ok(st.bridge.get(cid, 0) == 14 * UNIT, "1 escrow == pot raw")
    st.cursor = fh                                            # all race blocks exist
    st.apply_blob({"op": "call", "contract": cid, "method": "settle", "args": [R]}, C, "s")
    ok(rd(H.SD, R) == 1, "1 settled")
    di = [rd(H.DI_BASE + h, R) for h in range(H.NH)]
    w = rd(H.WN, R) - 1
    ok(w == max(range(H.NH), key=lambda h: (di[h], -h)), f"1 winner={w} argmax di={di}")
    poolw = rd(H.PL_BASE + w, R)
    voided = rd(H.VD, R) == 1
    ok(voided == (poolw == 0), f"1 auto-void iff winner unbacked (w pool {poolw}, vd {voided})")
    # everybody claims; tally payouts
    before = {x: st.bridge.get(x, 0) for x in (A, B, C)}
    for who in (A, B, C):
        st.apply_blob({"op": "call", "contract": cid, "method": "claim", "args": [R]}, who, "c" + who)
    if voided:
        exp = {A: 5 * UNIT, B: (2 + 4) * UNIT, C: 3 * UNIT}   # refund each bettor's whole stake 1:1
    else:
        staked_w = {A: 5 if w == 0 else 0, B: (2 if w == 0 else 0) + (4 if w == 3 else 0), C: 3 if w == 1 else 0}
        exp = {who: (staked_w[who] * tot // poolw) * UNIT for who in (A, B, C)}
    for who in (A, B, C):
        got = st.bridge.get(who, 0) - before[who]
        ok(got == exp[who], f"1 {who} payout got {got} exp {exp[who]} (voided={voided})")
    ok(st.bridge.get(cid, 0) >= 0, "1 contract never negative")
    ok(total_supply(st, []) == start, "1 value conserved (nothing minted/lost)")
    # double-claim is a no-op (nothing left to pay -> revert)
    b = st.bridge.get(A, 0)
    st.apply_blob({"op": "call", "contract": cid, "method": "claim", "args": [R]}, A, "c2")
    ok(st.bridge.get(A, 0) == b, "1 double-claim no-op")


# ---- 2. sole-lane bettor always gets their stake back (covers the void-when-loser branch) ----
def test_single_lane():
    st, cid, rd = fresh()
    st.credit_deposit(A, 50 * UNIT)
    start = total_supply(st, [])
    R = 42
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [R]}, A, "o")
    gh, lk, fh = rd(H.GH, R), rd(H.LK, R), rd(H.FH, R)
    set_hashes(st, gh, lk, seed=0x5EED)
    st.cursor = gh
    st.apply_blob({"op": "call", "contract": cid, "method": "bet", "args": [R, 2], "value": 7 * UNIT}, A, "b")
    st.cursor = fh
    st.apply_blob({"op": "call", "contract": cid, "method": "settle", "args": [R]}, A, "s")
    b = st.bridge.get(A, 0)
    st.apply_blob({"op": "call", "contract": cid, "method": "claim", "args": [R]}, A, "c")
    ok(st.bridge.get(A, 0) - b == 7 * UNIT, "2 sole bettor recovers stake (win==pot or void refund)")
    ok(st.bridge.get(cid, 0) == 0, "2 contract fully drained")
    ok(total_supply(st, []) == start, "2 value conserved")


# ---- 3. betting-window + settle-timing guards ----
def test_guards():
    st, cid, rd = fresh()
    st.credit_deposit(A, 50 * UNIT)
    R = 9
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [R]}, A, "o")
    gh, lk, fh = rd(H.GH, R), rd(H.LK, R), rd(H.FH, R)
    set_hashes(st, gh, lk)
    # bet BEFORE genes lock (cursor < gh) -> revert (no pool)
    st.cursor = gh - 1
    st.apply_blob({"op": "call", "contract": cid, "method": "bet", "args": [R, 0], "value": 3 * UNIT}, A, "b0")
    ok(rd(H.PL_BASE + 0, R) == 0, "3 bet before gene lock reverts")
    # settle BEFORE finish -> revert
    st.cursor = fh - 1
    st.apply_blob({"op": "call", "contract": cid, "method": "settle", "args": [R]}, A, "s0")
    ok(rd(H.SD, R) == 0, "3 settle before finish reverts")
    # valid bet in-window
    st.cursor = gh
    st.apply_blob({"op": "call", "contract": cid, "method": "bet", "args": [R, 0], "value": 3 * UNIT}, A, "b1")
    ok(rd(H.PL_BASE + 0, R) == 3, "3 in-window bet lands")
    # bet AFTER lock -> revert
    st.cursor = lk
    st.apply_blob({"op": "call", "contract": cid, "method": "bet", "args": [R, 0], "value": 3 * UNIT}, A, "b2")
    ok(rd(H.PL_BASE + 0, R) == 3, "3 bet after lock reverts")
    # non-UNIT stake -> revert
    st.cursor = gh
    st.apply_blob({"op": "call", "contract": cid, "method": "bet", "args": [R, 1], "value": UNIT + 1}, A, "b3")
    ok(rd(H.PL_BASE + 1, R) == 0, "3 non-UNIT stake reverts")
    # lane out of range -> revert
    st.apply_blob({"op": "call", "contract": cid, "method": "bet", "args": [R, H.NH], "value": 2 * UNIT}, A, "b4")
    ok(rd(H.TOT, R) == 3, "3 out-of-range lane reverts")


# ---- 4. Daily Derby: anchor (two-phase) + provable post readable via the view ----
def test_daily():
    st, cid, rd = fresh(cursor=200)
    st.credit_deposit(A, UNIT)
    import time as _t
    day = int(_t.time()) // 86400
    st.block_ts = day * 86400 + 100                      # contract TIME -> this UTC day
    # anchor phase 1: pins a future height (ah), no value
    st.apply_blob({"op": "call", "contract": cid, "method": "anchor", "args": [day]}, A, "a1")
    ah = rd(H.A_H, day)
    ok(ah > 0, f"4 anchor pinned a future height ({ah})")
    # anchor phase 2: once the pinned block exists, resolve its hash into av[day]
    st.block_hashes[ah] = 0xC0FFEE
    st.cursor = ah + 1
    st.apply_blob({"op": "call", "contract": cid, "method": "anchor", "args": [day]}, A, "a2")
    ok(rd(H.A_V, day) != 0, "4 anchor resolved av[day]")
    # post a claim: day, score, n=8, w0=packed picks
    st.apply_blob({"op": "call", "contract": cid, "method": "post", "args": [day, 4200, 8, 12345]}, A, "p")
    v = st.decode_view(st.contracts[cid])
    ent = [e for e in v.get("eday", {}) if v["eday"][e] == day]
    ok(len(ent) == 1, "4 one daily entry recorded")
    e = ent[0]
    ok(v["escore"][e] == 4200 and v["en"][e] == 8 and v["ew0"][e] == 12345, "4 entry score/n/word stored")
    ok(v["eaddr"][e] == A, "4 entry bound to poster address")
    # a wrong-day post is rejected (day too far from chain TIME)
    st.apply_blob({"op": "call", "contract": cid, "method": "post", "args": [day + 5, 9999, 8, 1]}, A, "p2")
    ok(len([e for e in st.decode_view(st.contracts[cid]).get("eday", {}).values() if e == day + 5]) == 0, "4 wrong-day post rejected")


for t in (test_full, test_single_lane, test_guards, test_daily):
    t()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
