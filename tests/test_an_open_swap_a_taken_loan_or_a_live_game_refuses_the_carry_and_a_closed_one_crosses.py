"""An open OTC order, a taken loan and a live 8-ball game each REFUSE the gen-29 carry, naming themselves; closed, they
cross with every slot accounted for (execnode/games/otc.py, lend.py, pool.py carry hooks; tools/carry.py;
doc/stwo/g5-carry.md). Operator rule: everything is carried, and what cannot be carried losslessly refuses — never reset.

Driving the REAL contracts on a gen-28 exec state:
  1. otc — an OPEN order and a FILLED-unsettled one are tied to a foreign HTLC with real money, expire at OLD-CHAIN
     heights, and settle against a FRESH VM hash whose layout changes at gen 29 (four alghash digests -> one BLAKE2s
     word): carry_in_flight names each, and carry_contract refuses. Once settled / cancelled / expired, the book carries:
     the maker and taker digests and every string-argument digest remapped, the closed orders' hashlocks and revealed
     limbs kept verbatim, an intra order wanting an asset id that names no asset kept as given. On gen 29 the carried
     book takes a NEW order under the v2 hashlock and settles it with the secret;
  2. lend — a TAKEN loan's deadline is in TIME, which restarts from the new generation's GENESIS_TIMESTAMP (a jump that
     could default it in the first block): it refuses, naming the loan. Repaid, the loan is pull balances only and
     carries; a long-term loan's due time past 2^32 is kept verbatim; on gen 29 the lender claims principal + interest
     and the borrower the collateral, exactly as on gen 28;
  3. pool (8-ball) — an open game races an old-chain move clock and its rack is BHASH(kh): it refuses; resigned, it
     carries, its stake, pot and a shot word past 2^32 kept verbatim.

Run: python3 tests/test_an_open_swap_a_taken_loan_or_a_live_game_refuses_the_carry_and_a_closed_one_crosses.py
"""
import _harness
HOME = _harness.isolate("nado-test-carry-otc-lend-pool-")
import copy
import json
import os
import time

import protocol as PR
from execnode.state import ExecState
from execnode.games import otc as O, lend as L, pool as PL
from execnode import exec_genesis as EG
from execnode.runtimes import zkvm_addr_digest
from tools import carry

T = _harness.Report()
MK, TK, LENDER, BORROWER, P1, P2 = "ndoMAKER", "ndoTAKER", "ndoLENDER", "ndoBORROWER", "ndoP1", "ndoP2"
NOW = int(time.time())
MADE_UP = 98_765_432_101_234_567
SECRET = "ab" * 32
_n = [0]


def fresh(path, cursor):
    st = ExecState(os.path.join(HOME, path))
    st.cursor, st.block_ts = cursor, NOW
    st.block_hashes = {h: h * 1_000_003 + 9 for h in range(max(0, cursor - 10), cursor + 20_000)}
    return st


def call(st, cid, who, m, args, value=0, asset=0):
    _n[0] += 1
    return st.apply_blob({"op": "call", "contract": cid, "method": m, "args": args, "value": value, "asset": asset},
                         who, f"{m}-{_n[0]}")


def deploy(st, mod, who, nonce):
    code = mod.build("v1")
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": mod.ABI, "nonce": nonce}, who, "d" + nonce)
    return st.contract_id(who, code, nonce)


def refused(fn):
    try:
        fn()
        return None
    except carry.Refused as e:
        return str(e)


nat = lambda st, w: int(st.bridge.get(w, 0))
cell = lambda st_or_rec, cid, f, k: int(((st_or_rec.contracts[cid] if cid else st_or_rec)["storage"].get("slots") or {})
                                        .get(str((f << 32) + k), 0))


def post_args(st, o, isa):
    expn = st.cursor + 5000                                  # 30,000 s of NADO window
    return [o, O.ASK, 10 ** 11, "btc", "0.01", "bc1qmaker", "sha:" + SECRET[:16], *O.vm_hashlock_parts(SECRET, isa),
            expn, st.block_ts + 10_000]                      # ASK: the foreign leg expires well inside expn


old = fresh("old.json", 100_000)
for w in (MK, TK, LENDER, BORROWER, P1, P2):
    old.bridge[w] = 10 ** 15

# ---- 1. otc ---------------------------------------------------------------------------------------------------------
oc = deploy(old, O, MK, "otc")
call(old, oc, MK, "post", post_args(old, 1, "v1"))
call(old, oc, MK, "post", post_args(old, 2, "v1"))
call(old, oc, MK, "post", post_args(old, 3, "v1"))
call(old, oc, TK, "boost", [2], 5 * 10 ** 9)
r = call(old, oc, TK, "fill", [2, "bc1qtaker", "txid:foreign"])
call(old, oc, MK, "post_intra", [4, 0, 3 * 10 ** 10, MADE_UP, 7, old.cursor + 100], 3 * 10 ** 10)
T.check("setup: three ASK orders posted, one filled and boosted, an intra order wanting a made-up asset, on gen 28",
        cell(old, oc, O.ST, 2) == O.FILLED and cell(old, oc, O.ST, 1) == O.OPEN and cell(old, oc, O.ST, 4) == O.OPEN, r)
why = O.carry_in_flight(old.contracts[oc]["storage"])
T.check("1. every open or filled order blocks, each named with what resolves it",
        len(why) == 4 and why[0].startswith("order 1 is open") and why[1].startswith("order 2 is filled and unsettled")
        and why[3].startswith("order 4 is open"), why)
dmap0, _ = carry.digest_map(old.zk_addrs)
msg = refused(lambda: carry.carry_contract(oc, old.contracts[oc], dmap0, old.cursor, src="v1", dst="v2"))
T.check("1. ...and carry_contract refuses the book, naming the in-flight orders", msg is not None and "in flight" in msg
        and "order 2 is filled" in msg, msg)

limbs = O.preimage_limbs(SECRET)
b4 = nat(old, TK)
call(old, oc, TK, "settle", [2, *limbs])                    # the taker (or a watchtower) settles with the secret
T.check("setup: the filled order settles and its bounty pays the settler", cell(old, oc, O.ST, 2) == O.SETTLED
        and nat(old, TK) - b4 == 5 * 10 ** 9)
call(old, oc, MK, "cancel", [1])
call(old, oc, MK, "cancel", [4])
old.cursor = cell(old, oc, O.EXPN, 3)
call(old, oc, TK, "expire", [3])
T.check("1. settled, cancelled and expired, the book is at rest", O.carry_in_flight(old.contracts[oc]["storage"]) == [],
        O.carry_in_flight(old.contracts[oc]["storage"]))

# ---- 2. lend --------------------------------------------------------------------------------------------------------
lc = deploy(old, L, LENDER, "lend")
LU = L.UNIT
call(old, lc, LENDER, "offer", [7, 10 ** 6, 2 * 10 ** 5, 15 * 10 ** 5, 86400], 10 ** 6 * LU)
call(old, lc, LENDER, "offer", [8, 1000, 10, 2000, (1 << 32) - 1], 1000 * LU)     # a very long term
call(old, lc, LENDER, "offer", [9, 1000, 10, 2000, 3600], 1000 * LU)              # never taken: an OPEN offer
call(old, lc, BORROWER, "take", [7], 15 * 10 ** 5 * LU)
r = call(old, lc, BORROWER, "take", [8], 2000 * LU)
why = L.carry_in_flight(old.contracts[lc]["storage"])
T.check("2. a taken loan blocks, named; an open offer does not", len(why) == 2 and why[0].startswith("loan 7 is taken")
        and why[1].startswith("loan 8 is taken"), (why, r))
msg = refused(lambda: carry.carry_contract(lc, old.contracts[lc], carry.digest_map(old.zk_addrs)[0], old.cursor))
T.check("2. ...and carry_contract refuses the contract, naming the loan", msg is not None and "loan 7 is taken" in msg, msg)
call(old, lc, BORROWER, "repay", [7], 12 * 10 ** 5 * LU)
call(old, lc, BORROWER, "repay", [8], 1010 * LU)
T.check("2. repaid, the loans are at rest; the long-term loan's due time is past 2^32",
        L.carry_in_flight(old.contracts[lc]["storage"]) == [] and cell(old, lc, L.DL, 8) >= 1 << 32,
        cell(old, lc, L.DL, 8))

# ---- 3. pool (8-ball) -----------------------------------------------------------------------------------------------
pc = deploy(old, PL, P1, "pool")
STAKE = 3 * 10 ** 10
call(old, pc, P1, "open", [11, 0], STAKE)
call(old, pc, P2, "join", [11], STAKE)
r = call(old, pc, P1, "move", [11, (1 << 50) + 1, 0])                         # a shot word past 2^32
T.check("3. a live game blocks the carry", PL.carry_in_flight(old.contracts[pc]["storage"]) == ["game 11 is open"]
        and cell(old, pc, PL.MV_BASE, 11) == (1 << 50) + 1, r)
msg = refused(lambda: carry.carry_contract(pc, old.contracts[pc], carry.digest_map(old.zk_addrs)[0], old.cursor))
T.check("3. ...and carry_contract refuses it", msg is not None and "game 11 is open" in msg, msg)
b4 = nat(old, P1)
call(old, pc, P2, "resign", [11])
T.check("3. resigned, the game is settled (the winner paid) and at rest",
        PL.carry_in_flight(old.contracts[pc]["storage"]) == [] and nat(old, P1) - b4 == 2 * STAKE)

# ---- the carry, at rest -----------------------------------------------------------------------------------------------
TIP = old.cursor
snap = copy.deepcopy({"contracts": old.contracts, "zk_addrs": old.zk_addrs, "bridge": old.bridge})
recs, reg, counts = carry.carry_contracts(snap["contracts"], snap["zk_addrs"], TIP, src="v1", dst="v2")
for cid, name in ((oc, "otc"), (lc, "lend"), (pc, "pool")):
    T.check(f"{name}: every slot is carried (none dropped, none merged)",
            counts[cid]["slots"] == len(snap["contracts"][cid]["storage"]["slots"]) == len(recs[cid]["storage"]["slots"]),
            counts[cid])
ro = recs[oc]
T.check("1. the maker/taker and every string-argument digest are remapped to their gen-29 digests",
        cell(ro, None, O.MAKER, 2) == zkvm_addr_digest(MK, True) and cell(ro, None, O.TAKER, 2) == zkvm_addr_digest(TK, True)
        and cell(ro, None, O.WADR, 2) == zkvm_addr_digest("bc1qmaker", True)
        and cell(ro, None, O.FREF, 2) == zkvm_addr_digest("txid:foreign", True))
T.check("1. the closed orders' hashlocks and revealed limbs are kept verbatim (history: nothing re-hashes them)",
        all(cell(ro, None, f, 2) == cell(old, oc, f, 2) != 0 for f in (O.HVM, O.HV1, O.HV2, O.HV3))
        and [cell(ro, None, O.S0 + i, 2) for i in range(5)] == limbs)
T.check("1. an intra order wanting an asset id that names no asset keeps it as given",
        cell(ro, None, O.WAST, 4) == MADE_UP)
T.check("2. the long-term loan's due time is kept verbatim, the parties remapped",
        cell(recs[lc], None, L.DL, 8) == cell(old, lc, L.DL, 8)
        and cell(recs[lc], None, L.BW, 7) == zkvm_addr_digest(BORROWER, True))
T.check("3. the game's stake, pot and shot word are kept verbatim, the players remapped",
        cell(recs[pc], None, PL.ST, 11) == STAKE and cell(recs[pc], None, PL.MV_BASE, 11) == (1 << 50) + 1
        and cell(recs[pc], None, PL.P2, 11) == zkvm_addr_digest(P2, True))

# what gen 28 pays the lend parties from here
pay28 = {}
for w in (LENDER, BORROWER):
    for i in (7, 8):
        b4 = nat(old, w)
        call(old, lc, w, "claim", [i])
        pay28[(w, i)] = nat(old, w) - b4
b4 = nat(old, LENDER)
call(old, lc, LENDER, "cancel", [9])
call(old, lc, LENDER, "claim", [9])
pay28["cancel9"] = nat(old, LENDER) - b4
T.check("setup: on gen 28 the lender is owed principal + interest and the borrower the collateral",
        pay28[(LENDER, 7)] == 12 * 10 ** 5 * LU and pay28[(BORROWER, 7)] == 15 * 10 ** 5 * LU
        and pay28["cancel9"] == 1000 * LU, pay28)

# ---- gen 29 -----------------------------------------------------------------------------------------------------------
gen_file = os.path.join(HOME, "exec_genesis.json")
pots = {cid: str(int(snap["bridge"].get(cid, 0))) for cid in recs if int(snap["bridge"].get(cid, 0))}
json.dump({"generation": PR.CHAIN_GENERATION, "contracts": recs, "bridge": pots, "zk_addrs": reg}, open(gen_file, "w"))
os.environ["NADO_EXEC_GENESIS"] = gen_file
EG._CACHE.clear()
PR.BLAKE_EXEC_HEIGHT = 1
try:
    new = fresh("new.json", -1)
    T.check("the carried genesis loads into a fresh gen-29 layer", EG.apply(new) and sorted(new.contracts) == sorted(recs))
    new.cursor = 10
    for w in (MK, TK, LENDER, BORROWER, P1, P2):
        new.bridge[w] = int(snap["bridge"][w])
    pay29 = {}
    for w in (LENDER, BORROWER):
        for i in (7, 8):
            b4 = nat(new, w)
            call(new, lc, w, "claim", [i])
            pay29[(w, i)] = nat(new, w) - b4
    b4 = nat(new, LENDER)
    call(new, lc, LENDER, "cancel", [9])
    call(new, lc, LENDER, "claim", [9])
    pay29["cancel9"] = nat(new, LENDER) - b4
    T.check("2. on gen 29 every lend claim pays exactly what it pays on gen 28 (and the open offer still cancels)",
            pay29 == pay28, (pay29, pay28))
    call(new, oc, MK, "post", post_args(new, 50, "v2"))
    call(new, oc, TK, "fill", [50, "bc1qtaker", "txid:foreign2"])
    r = call(new, oc, TK, "settle", [50, *limbs])
    T.check("1. on gen 29 the carried book takes a new order under the v2 hashlock and settles it with the secret",
            cell(new, oc, O.ST, 50) == O.SETTLED and cell(new, oc, O.ST, 2) == O.SETTLED, r)
    r = call(new, oc, TK, "settle", [2, *limbs])
    T.check("1. ...while a carried closed order can never be settled again", r.find("-> ok") < 0, r)
finally:
    PR.BLAKE_EXEC_HEIGHT = 1 << 62
T.done("ALL PASS — an open swap, a taken loan or a live game refuses the carry, and a closed one crosses")
