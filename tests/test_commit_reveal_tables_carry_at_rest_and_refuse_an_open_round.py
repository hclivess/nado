"""Coinflip, hold'em, farkle and stormhold cross the gen-29 reroll WITH all their storage once nothing is in flight, and
REFUSE the carry — naming the game and the action that resolves it — while a round is open (tools/carry.py,
doc/stwo/g5-carry.md 2c). Operator rule 2026-10-20: everything is carried, losslessly; a contract that cannot be carried
refuses, it is never reset.

Why an open round must refuse: these games commit HASH(secret) and check a later reveal against a FRESH hash. The gen-29
VM hashes with BLAKE2s, so a gen-28 commitment can never be revealed after the carry — and their deadlines and dice pins
are old-chain heights. Driving the REAL contracts on a gen-28 ExecState:
  1. coinflip: a joined, unrevealed game and a lobby game block (naming settle / cancel); settled and cancelled, the
     contract carries, every slot accounted for — and on gen 29 the carried contract plays a fresh commit-reveal round
     under the new hash while the finished game's record (winner, players) reads as before;
  2. hold'em: an undealt table and a dealt one block; a table voided by reclaim carries, its commitments, ante, street
     price and contributions (raw NADO, >= 2^32) kept verbatim;
  3. farkle: a table holding antes blocks; once every seat is reclaimed (tp == 0) it carries, and a free roll pending at
     a cancelled table is re-pinned onto the new chain (never blocking, never an old-chain height) and holds there;
  4. stormhold: a game in play blocks, and a SETTLED hidden-hands game still blocks until both secrets are revealed —
     reveal() checks the commitment after settlement too; revealed, it carries (move words and cfg kept verbatim).

Run: python3 tests/test_commit_reveal_tables_carry_at_rest_and_refuse_an_open_round.py
"""
import _harness
HOME = _harness.isolate("nado-test-carry-commit-reveal-")
import json
import os
import time

import protocol as PR
from execnode.state import ExecState
from execnode.games import coinflip as CF, holdem as HD, farkle as FK, stormhold as SH, _lib
from execnode import exec_genesis as EG
from tools import carry

T = _harness.Report()
A, B, C = "ndoAAAA" + "A" * 41, "ndoBBBB" + "B" * 41, "ndoCCCC" + "C" * 41
TIP0 = 150_000
BIG = 10 ** 11                          # 10 NADO raw: every amount slot here is >= 2^32, so CARRY_WORDS is exercised
_n = [0]


def fresh(path, cursor=TIP0, lo=0, hi=TIP0 + 30_000):
    st = ExecState(os.path.join(HOME, path))
    st.cursor, st.block_ts = cursor, int(time.time())
    st.block_hashes = {h: h * 1_000_003 + 7 for h in range(lo, hi)}
    st.beacons = {e: e * 7_919_993 + 11 for e in range(lo // 60, hi // 60 + 10)}
    for w in (A, B, C):
        st.credit_deposit(w, 10 ** 15)
    return st


def deploy(st, mod):
    code = mod.build("v1")
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": mod.ABI, "nonce": "n"}, A, "d" + mod.__name__)
    return st.contract_id(A, code, "n")


def call(st, cid, who, m, args, value=None):
    _n[0] += 1
    p = {"op": "call", "contract": cid, "method": m, "args": args}
    if value:
        p["value"] = value
    return st.apply_blob(p, who, f"{m}-{_n[0]}")


def rd(st, cid, f, k):
    return int((st.contracts[cid]["storage"].get("slots") or {}).get(str((f << 32) + k), 0))


def try_carry(st, cid):
    """(record, counts, None) or (None, None, the refusal) — the real carry, v1 -> v2, at the old chain's tip."""
    try:
        rec, n = carry.carry_contract(cid, st.contracts[cid], *carry.digest_map(st.zk_addrs)[:1], st.cursor,
                                      src="v1", dst="v2")
        return rec, n, None
    except carry.Refused as e:
        return None, None, str(e)


def carried_whole(st, cid, rec, n):
    """every gen-28 slot became exactly one gen-29 slot, and no gen-28 digest survives as a key or value"""
    old = st.contracts[cid]["storage"].get("slots") or {}
    digests = {int(k) for k in st.zk_addrs}
    left = [(k, v) for k, v in rec["storage"]["slots"].items() if int(k) in digests or int(v) in digests]
    return n["slots"] == len(old) == len(rec["storage"]["slots"]) and not left and n["value_remapped"] >= 1


v1h = lambda x: _lib.vm_hash([x], "v1")
v2h = lambda x: _lib.vm_hash([x], "v2")

# ---- 1. coinflip ------------------------------------------------------------------------------------------------------
st = st_cf = fresh("cf.json")
cf = deploy(st, CF)
s1, s2 = 0xABCDEF1234567, 0x7654321FEDCBA
call(st, cf, A, "open", [11, v1h(s1)], BIG)
call(st, cf, B, "join", [11, v1h(s2)], BIG)
call(st, cf, A, "open", [12, v1h(5)], BIG)
why = CF.carry_in_flight(st.contracts[cf]["storage"])
T.check("coinflip: a joined unrevealed game and a lobby game block, naming settle and the opener's cancel",
        len(why) == 2 and "game 11" in why[0] and "settle(11)" in why[0] and "cancel(12)" in why[1], why)
_r, _c, msg = try_carry(st, cf)
T.check("coinflip: the carry refuses while they are open", msg is not None and "in flight" in msg and "game 11" in msg, msg)
call(st, cf, A, "reveal", [11, s1])
call(st, cf, B, "reveal", [11, s2])
r = call(st, cf, C, "settle", [11])
call(st, cf, A, "cancel", [12])
ws = rd(st, cf, CF.WS, 11)
T.check("coinflip: settled and cancelled, nothing is in flight", ws in (1, 2) and CF.carry_in_flight(st.contracts[cf]["storage"]) == [], r)
cf_rec, n, msg = try_carry(st, cf)
T.check("coinflip: at rest the contract carries, every slot accounted for (stakes, commitments, secrets kept)",
        msg is None and carried_whole(st, cf, cf_rec, n) and n["value_kept_word"] >= 6
        and cf_rec["storage"]["slots"][str((CF.S1 << 32) + 11)] == s1, (msg, n))

# ---- 2. hold'em -------------------------------------------------------------------------------------------------------
st = fresh("hd.json")
hd = deploy(st, HD)
TB_, G1, G2 = 500, 501, 502
call(st, hd, A, "open", [TB_, G1, v1h(111), BIG], 3 * BIG)
call(st, hd, B, "join", [TB_, G2, v1h(222)], 3 * BIG)
why = HD.carry_in_flight(st.contracts[hd]["storage"])
T.check("hold'em: an undealt table blocks, naming start / leave + cancel", why and "start(500)" in why[0], why)
call(st, hd, A, "start", [TB_])
tg = rd(st, hd, HD.TG, TB_)
st.cursor = tg * HD.EPOCH_LENGTH + 1
call(st, hd, A, "bet", [G1, BIG])
r = call(st, hd, B, "bet", [G2, BIG])
why = HD.carry_in_flight(st.contracts[hd]["storage"])
_r, _c, msg = try_carry(st, hd)
T.check("hold'em: a dealt table blocks, naming settle / reclaim, and the carry refuses",
        why and "settle(500)" in why[0] and "reclaim(500)" in why[0] and msg is not None and "table 500" in msg, (why, msg, r))
_b0, cs, _o, _p = HD.timeline_ref(rd(st, hd, HD.TD, TB_), tg)
st.cursor = cs[3] + HD.R + 1
r = call(st, hd, C, "reclaim", [TB_])
T.check("hold'em: voided by reclaim (nobody revealed), the table is closed and at rest",
        rd(st, hd, HD.TZ, TB_) == 1 and HD.carry_in_flight(st.contracts[hd]["storage"]) == [], r)
hd_rec, n, msg = try_carry(st, hd)
hs = (hd_rec or {}).get("storage", {}).get("slots", {})
T.check("hold'em: at rest the contract carries; commitments, ante, street price and contributions kept verbatim",
        msg is None and carried_whole(st, hd, hd_rec, n)
        and hs.get(str((HD.GC << 32) + G2)) == v1h(222) and hs.get(str((HD.TS << 32) + TB_)) == BIG
        and hs.get(str(((HD.MS_BASE + 1) << 32) + TB_)) == BIG and hs.get(str(((HD.CS_BASE + 1) << 32) + G1)) == BIG,
        (msg, n))

# ---- 3. farkle --------------------------------------------------------------------------------------------------------
st = st_fk = fresh("fk.json")
fk = deploy(st, FK)
T1, S1, S2, T2, S3 = 5, 60, 61, 6, 70
call(st, fk, A, "open", [T1, S1], BIG)
call(st, fk, B, "join", [T1, S2], BIG)
call(st, fk, A, "roll", [S1])
grh = rd(st, fk, FK.GRH, S1)
st.cursor = grh + 2
dice = FK.roll_dice(st.block_hashes[grh], st.block_hashes[grh + 1], S1, rd(st, fk, FK.GRN, S1), 6)
keep = {f: sum(1 for d in dice if d == f) if f in (1, 5) else 0 for f in range(1, 7)}
r = call(st, fk, A, "hold", [S1, sum(keep[f] << (3 * (f - 1)) for f in range(1, 7)), 0])
why = FK.carry_in_flight(st.contracts[fk]["storage"])
_r, _c, msg = try_carry(st, fk)
T.check("farkle: a table holding antes blocks, naming settle / reclaim, and the carry refuses",
        why and "table 5" in why[0] and "reclaim" in why[0] and msg is not None and "in flight" in msg, (why, msg, r))
st.cursor += 18_001
call(st, fk, C, "reclaim", [S1])
call(st, fk, C, "reclaim", [S2])
call(st, fk, A, "open", [T2, S3], BIG)
call(st, fk, A, "cancel", [T2])
r = call(st, fk, A, "roll", [S3])                     # roll() never checks the table: a free roll at a cancelled table
pin = rd(st, fk, FK.GRH, S3)
T.check("farkle: every seat reclaimed (tp == 0) and the solo table cancelled, nothing is in flight — a free roll pending "
        "at the cancelled table does not block", rd(st, fk, FK.TP, T1) == 0 and pin > TIP0
        and FK.carry_in_flight(st.contracts[fk]["storage"]) == [], (r, FK.carry_in_flight(st.contracts[fk]["storage"])))
fk_rec, n, msg = try_carry(st, fk)
fs = (fk_rec or {}).get("storage", {}).get("slots", {})
newpin = fs.get(str((FK.GRH << 32) + S3))
T.check("farkle: at rest the contract carries, every slot accounted for; the pending roll is re-pinned to an INT "
        "new-chain block", msg is None and carried_whole(st, fk, fk_rec, n) and type(newpin) is int
        and _lib.CARRY_PIN_FLOOR <= newpin <= pin - st.cursor + _lib.CARRY_PIN_FLOOR, (msg, n, newpin))
T.check("farkle: hold()'s scratch seed (a large value) is kept as declared",
        any(int(k) >> 32 == FK.SC and v >= 1 << 32 for k, v in fs.items()), sorted(fs.items())[:3])
try:
    FK.carry_rebase({"slots": {"0": 1, str((FK.TLIST << 32)): T1, str((FK.TA << 32) + T1): 1,
                               str((FK.TP << 32) + T1): 5}}, 10)
    T.check("farkle: carry_rebase refuses a table in flight (a direct caller cannot re-roll it)", False)
except ValueError as e:
    T.check("farkle: carry_rebase refuses a table in flight (a direct caller cannot re-roll it)", "table 5" in str(e))

# ---- 4. stormhold -----------------------------------------------------------------------------------------------------
st = fresh("sh.json")
shc = deploy(st, SH)
G, x1, x2 = 77, 0x1234567890ABC, 0xCBA0987654321
CFGW, ENC = (1 << 40) + 5, (1 << 50) + 3
call(st, shc, A, "open", [G, CFGW, v1h(x1)], BIG)
call(st, shc, B, "join", [G, v1h(x2)], BIG)
call(st, shc, A, "move", [G, ENC, 0])
call(st, shc, B, "move", [G, 17, 1])
why = SH.carry_in_flight(st.contracts[shc]["storage"])
_r, _c, msg = try_carry(st, shc)
T.check("stormhold: a game in play blocks, naming agree/resign/abort, and the carry refuses",
        why and "abort(77)" in why[0] and msg is not None and "game 77" in msg, (why, msg))
call(st, shc, A, "agree", [G, 3])
r = call(st, shc, B, "agree", [G, 3])
why = SH.carry_in_flight(st.contracts[shc]["storage"])
_r, _c, msg = try_carry(st, shc)
T.check("stormhold: SETTLED with both hidden-hands commitments unrevealed, it still blocks (reveal checks them after "
        "settlement, and the gen-29 hash never could)", rd(st, shc, SH.SD, G) == 1 and len(why) == 2
        and all("unrevealed" in w and "reveal(77" in w for w in why) and msg is not None, (why, msg, r))
call(st, shc, A, "reveal", [G, x1])
call(st, shc, B, "reveal", [G, x2])
T.check("stormhold: both revealed, nothing is in flight", SH.carry_in_flight(st.contracts[shc]["storage"]) == [])
sh_rec, n, msg = try_carry(st, shc)
ss = (sh_rec or {}).get("storage", {}).get("slots", {})
T.check("stormhold: at rest the contract carries; the cfg word, move words and commitments kept verbatim",
        msg is None and carried_whole(st, shc, sh_rec, n) and ss.get(str((SH.CFG << 32) + G)) == CFGW
        and ss.get(str((SH.MV_BASE << 32) + G)) == ENC and ss.get(str((SH.C1 << 32) + G)) == v1h(x1), (msg, n))

# ---- gen 29: the carried coinflip and farkle play on, through the real genesis loader ---------------------------------
# one registry over every caller both carried contracts saw (the gen-29 genesis holds one registry)
reg_all = {**st_cf.zk_addrs, **st_fk.zk_addrs}
_dmap, reg = carry.digest_map(reg_all)
recs = {cf: cf_rec, fk: fk_rec}
gen_file = os.path.join(HOME, "exec_genesis.json")
json.dump({"generation": PR.CHAIN_GENERATION, "contracts": recs, "zk_addrs": reg}, open(gen_file, "w"))
os.environ["NADO_EXEC_GENESIS"] = gen_file
EG._CACHE.clear()
PR.BLAKE_EXEC_HEIGHT = 1
try:
    new = fresh("new.json", cursor=-1, lo=0, hi=5000)
    T.check("gen 29: the carried genesis loads", EG.apply(new) and sorted(new.contracts) == sorted(recs))
    new.cursor = 10
    view = new.decode_view(new.contracts[cf])
    T.check("gen 29: coinflip's finished game reads as before — the same players, the same winner",
            view["p1"][str(11)] == A and view["p2"][str(11)] == B and int(view["ws"][str(11)]) == ws, view.get("p1"))
    t1, t2 = 0x5151, 0x6262
    call(new, cf, A, "open", [21, v2h(t1)], BIG)
    call(new, cf, B, "join", [21, v2h(t2)], BIG)
    call(new, cf, A, "reveal", [21, t1])
    call(new, cf, B, "reveal", [21, t2])
    pa, pb = new.bridge.get(A, 0), new.bridge.get(B, 0)
    r = call(new, cf, C, "settle", [21])
    w = rd(new, cf, CF.WS, 21)
    expect = (v2h(t1 + t2 + 21) & 0xFFFFFFFF) % 2 + 1
    paid = (new.bridge.get(A, 0) - pa, new.bridge.get(B, 0) - pb)
    T.check("gen 29: the carried coinflip plays a fresh commit-reveal round under BLAKE2s and pays the winner the pot",
            w == expect and paid == ((2 * BIG, 0) if w == 1 else (0, 2 * BIG)), (r, w, expect, paid))
    newpin = rd(new, fk, FK.GRH, S3)
    new.cursor = newpin + 2
    seed = sum(new.block_hashes[h] for h in (newpin, newpin + 1)) + S3 * 1000 + rd(new, fk, FK.GRN, S3) * 10
    d2 = [(v2h(seed + p) & 0xFFFFFFFF) % 6 + 1 for p in range(6)]
    cnt = {f: d2.count(f) for f in range(1, 7)}
    k2 = {f: cnt[f] if (f in (1, 5) or cnt[f] >= 3) else 0 for f in range(1, 7)}
    r = call(new, fk, A, "hold", [S3, sum(k2[f] << (3 * (f - 1)) for f in range(1, 7)), 0])
    T.check("gen 29: the re-pinned farkle roll resolves from the new chain's own block hashes",
            r.endswith("-> ok") and rd(new, fk, FK.GRH, S3) == 0, r)
finally:
    PR.BLAKE_EXEC_HEIGHT = 1 << 62
T.done("ALL PASS — commit-reveal tables carry at rest and refuse an open round")
