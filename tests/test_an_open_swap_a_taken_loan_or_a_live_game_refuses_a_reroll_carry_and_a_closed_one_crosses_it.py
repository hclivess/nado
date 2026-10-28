"""An open OTC order, a taken loan and a live 8-ball game each REFUSE the reroll carry, naming themselves; closed, they
cross with every slot and pay exactly what they would have paid on the old chain (execnode/games/otc.py, lend.py,
pool.py carry hooks; tools/carry.py; tools/alphanet6_carryforward.exec_genesis; execnode/exec_genesis.py). Operator
rule: everything is carried, and what cannot be carried losslessly refuses — never reset.

This is the v2 -> v2 carry every reroll from generation 29 on runs: the old chain is a live-shaped exec state (the zkvm2
VM, the BLAKE2s exec root) saved as the exec node saves it, the carry is tools/carry.py as the operator runs it (on a
COPY of exec_state.json) and the builder's exec_genesis, and the new chain is a fresh layer loaded by the real genesis
loader. (Replaces the gen-28 -> gen-29 test G9 slice 3a retired with the field VM; SCHEDULED_CLEANUPS.md 2026-10-27.)

  1. otc — an OPEN order and a FILLED-unsettled one are tied to a foreign HTLC with real money and expire at OLD-CHAIN
     heights: carry_in_flight names each, tools/carry.py exits refusing and names them, and exec_genesis refuses. Once
     settled / cancelled / expired the book carries with every slot unchanged; on the new chain it takes a NEW order and
     settles it with the secret, while a carried settled order can never be settled again;
  2. lend — a TAKEN loan's deadline is in TIME, which restarts with the new generation: it refuses, naming the loan.
     Repaid, the loans are pull balances only and carry; a long-term due time past 2^32 is kept verbatim; on the new
     chain every claim pays exactly what it pays on the old one, and an open offer still cancels;
  3. pool (8-ball) — an open game races an old-chain move clock: it refuses; resigned, it carries, its stake and a shot
     word past 2^32 kept verbatim;
  4. the carried genesis loads, its root is genesis_root(), and the pots are exactly the old chain's.

Run: python3 tests/test_an_open_swap_a_taken_loan_or_a_live_game_refuses_a_reroll_carry_and_a_closed_one_crosses_it.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-carry-otc-lend-pool-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
HOME = os.environ["HOME"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["NADO_EXEC_GENESIS"] = os.path.join(HOME, "exec_genesis.json")
import copy
import json
import subprocess
import time

import protocol as PR
from execnode.state import ExecState
from execnode.games import otc as O, lend as L, pool as PL
from execnode import exec_genesis as EG
from tools import carry
import tools.alphanet6_carryforward as C

import _harness
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
    code = mod.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": mod.ABI, "nonce": nonce}, who, "d" + nonce)
    return st.contract_id(who, code, nonce)


def refused(fn):
    try:
        fn()
        return None
    except carry.Refused as e:
        return str(e)


def carry_cli(st):
    """tools/carry.py exactly as the operator runs it: on a saved COPY of the exec node's state file. (exit, output)"""
    st.save()
    cp = os.path.join(HOME, "copy-" + os.path.basename(st.path))
    shutil.copyfile(st.path, cp)
    p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "carry.py"), cp, "--out", cp + ".out"],
                       capture_output=True, text=True, timeout=900)
    return p.returncode, p.stdout + p.stderr


nat = lambda st, w: int(st.bridge.get(w, 0))
cell = lambda st_or_rec, cid, f, k: int(((st_or_rec.contracts[cid] if cid else st_or_rec)["storage"].get("slots") or {})
                                        .get(str((f << 32) + k), 0))


def post_args(st, o):
    expn = st.cursor + 5000                                  # 30,000 s of NADO window
    return [o, O.ASK, 10 ** 11, "btc", "0.01", "bc1qmaker", "sha:" + SECRET[:16], *O.vm_hashlock_parts(SECRET),
            expn, st.block_ts + 10_000]                      # ASK: the foreign leg expires well inside expn


old = fresh("old.json", 100_000)
for w in (MK, TK, LENDER, BORROWER, P1, P2):
    old.bridge[w] = 10 ** 15

# ---- 1. otc ---------------------------------------------------------------------------------------------------------
oc = deploy(old, O, MK, "otc")
for o in (1, 2, 3):
    call(old, oc, MK, "post", post_args(old, o))
call(old, oc, TK, "boost", [2], 5 * 10 ** 9)
r = call(old, oc, TK, "fill", [2, "bc1qtaker", "txid:foreign"])
call(old, oc, MK, "post_intra", [4, 0, 3 * 10 ** 10, MADE_UP, 7, old.cursor + 100], 3 * 10 ** 10)
T.check("setup: three ASK orders posted, one filled and boosted, an intra order wanting a made-up asset",
        cell(old, oc, O.ST, 2) == O.FILLED and cell(old, oc, O.ST, 1) == O.OPEN and cell(old, oc, O.ST, 4) == O.OPEN, r)
why = O.carry_in_flight(old.contracts[oc]["storage"])
T.check("1. every open or filled order blocks, each named with what resolves it",
        len(why) == 4 and why[0].startswith("order 1 is open") and why[1].startswith("order 2 is filled and unsettled")
        and why[3].startswith("order 4 is open"), why)
msg = refused(lambda: carry.carry_contract(oc, old.contracts[oc], old.cursor))
T.check("1. ...and carry_contract refuses the book, naming the in-flight orders",
        msg is not None and "in flight" in msg and "order 2 is filled" in msg, msg)

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
msg = refused(lambda: carry.carry_contract(lc, old.contracts[lc], old.cursor))
T.check("2. ...and carry_contract refuses the contract, naming the loan", msg is not None and "loan 7 is taken" in msg, msg)

# ---- 3. pool (8-ball) -----------------------------------------------------------------------------------------------
pc = deploy(old, PL, P1, "pool")
STAKE = 3 * 10 ** 10
call(old, pc, P1, "open", [11, 0], STAKE)
call(old, pc, P2, "join", [11], STAKE)
r = call(old, pc, P1, "move", [11, (1 << 50) + 1, 0])                         # a shot word past 2^32
T.check("3. a live game blocks the carry", PL.carry_in_flight(old.contracts[pc]["storage"]) == ["game 11 is open"]
        and cell(old, pc, PL.MV_BASE, 11) == (1 << 50) + 1, r)
msg = refused(lambda: carry.carry_contract(pc, old.contracts[pc], old.cursor))
T.check("3. ...and carry_contract refuses it", msg is not None and "game 11 is open" in msg, msg)

# ---- the whole state refuses, through both entry points, naming every blocker at once ------------------------------
pots0 = {cid: nat(old, cid) for cid in old.contracts}
msg = refused(lambda: C.exec_genesis(old.contracts, pots0, old.zk_addrs, old.cursor))
T.check("1-3. the reroll builder's exec_genesis refuses the whole state, naming the order, the loan and the game",
        msg is not None and "order 2 is filled" in msg and "loan 7 is taken" in msg and "game 11 is open" in msg, msg)
rc, out = carry_cli(old)
T.check("1-3. tools/carry.py on a copy of the saved exec state exits refusing, naming each and writing nothing",
        rc != 0 and "order 1 is open" in out and "loan 8 is taken" in out and "game 11 is open" in out
        and not os.path.exists(os.path.join(HOME, "copy-old.json.out")), (rc, out[-800:]))

# ---- settle everything on the old chain ----------------------------------------------------------------------------
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
call(old, lc, BORROWER, "repay", [7], 12 * 10 ** 5 * LU)
call(old, lc, BORROWER, "repay", [8], 1010 * LU)
T.check("2. repaid, the loans are at rest; the long-term loan's due time is past 2^32",
        L.carry_in_flight(old.contracts[lc]["storage"]) == [] and cell(old, lc, L.DL, 8) >= 1 << 32,
        cell(old, lc, L.DL, 8))
b4 = nat(old, P1)
call(old, pc, P2, "resign", [11])
T.check("3. resigned, the game is settled (the winner paid) and at rest",
        PL.carry_in_flight(old.contracts[pc]["storage"]) == [] and nat(old, P1) - b4 == 2 * STAKE)

# ---- the carry, at rest ---------------------------------------------------------------------------------------------
TIP = old.cursor
rc, out = carry_cli(old)
T.check("tools/carry.py carries the settled state: every contract, nothing refused",
        rc == 0 and "contracts carried: 3 (every one)" in out, (rc, out[-800:]))
snap = copy.deepcopy({"contracts": old.contracts, "zk_addrs": old.zk_addrs, "bridge": old.bridge})
pots = {cid: int(snap["bridge"].get(cid, 0)) for cid in snap["contracts"]}
recs, kept, reg = C.exec_genesis(snap["contracts"], pots, snap["zk_addrs"], TIP)
for cid, name in ((oc, "otc"), (lc, "lend"), (pc, "pool")):
    T.check(f"{name}: every slot carried unchanged (none dropped, none re-keyed, none re-valued), the code its build",
            recs[cid]["storage"]["slots"] == {k: int(v) for k, v in snap["contracts"][cid]["storage"]["slots"].items()}
            and recs[cid]["code"] == json.loads(json.dumps(snap["contracts"][cid]["code"])))
T.check("the pots stay in escrow with their contracts, exactly", kept == {c: p for c, p in pots.items() if p}, kept)
T.check("the payee registry crosses as it is", reg == snap["zk_addrs"])
ro = recs[oc]
T.check("1. the closed orders' hashlock and revealed limbs are kept verbatim (history: nothing re-hashes them)",
        cell(ro, None, O.HVM, 2) == cell(old, oc, O.HVM, 2) != 0 and [cell(ro, None, O.S0 + i, 2) for i in range(5)] == limbs)
T.check("1. an intra order wanting an asset id that names no asset keeps it as given", cell(ro, None, O.WAST, 4) == MADE_UP)
T.check("2. the long-term loan's due time is kept verbatim", cell(recs[lc], None, L.DL, 8) == cell(old, lc, L.DL, 8) >= 1 << 32)
T.check("3. the game's stake and shot word are kept verbatim",
        cell(recs[pc], None, PL.ST, 11) == STAKE and cell(recs[pc], None, PL.MV_BASE, 11) == (1 << 50) + 1)


# ---- what the old chain pays the lend parties from here ------------------------------------------------------------
def lend_pays(st):
    pay = {}
    for w in (LENDER, BORROWER):
        for i in (7, 8):
            b = nat(st, w)
            call(st, lc, w, "claim", [i])
            pay[(w, i)] = nat(st, w) - b
    b = nat(st, LENDER)
    call(st, lc, LENDER, "cancel", [9])
    call(st, lc, LENDER, "claim", [9])
    pay["cancel9"] = nat(st, LENDER) - b
    return pay


pay_old = lend_pays(old)
T.check("setup: on the old chain the lender is owed principal + interest and the borrower the collateral",
        pay_old[(LENDER, 7)] == 12 * 10 ** 5 * LU and pay_old[(BORROWER, 7)] == 15 * 10 ** 5 * LU
        and pay_old["cancel9"] == 1000 * LU, pay_old)

# ---- the new chain --------------------------------------------------------------------------------------------------
json.dump({"generation": PR.CHAIN_GENERATION, "contracts": recs, "bridge": {c: str(v) for c, v in kept.items()},
           "zk_addrs": reg}, open(os.environ["NADO_EXEC_GENESIS"], "w"))
EG._CACHE.clear()
new = fresh("new.json", -1)
T.check("4. the carried genesis loads into a fresh layer", EG.apply(new) and sorted(new.contracts) == sorted(recs))
T.check("4. ...its root is genesis_root(), and the pots are the old chain's",
        new.state_root() == EG.genesis_root() and {c: nat(new, c) for c in recs} == pots)
new.cursor = 10
for w in (MK, TK, LENDER, BORROWER, P1, P2):
    new.bridge[w] = int(snap["bridge"][w])
pay_new = lend_pays(new)
T.check("2. on the new chain every lend claim pays exactly what it pays on the old one (and the open offer still cancels)",
        pay_new == pay_old, (pay_new, pay_old))
call(new, oc, MK, "post", post_args(new, 50))
call(new, oc, TK, "fill", [50, "bc1qtaker", "txid:foreign2"])
r = call(new, oc, TK, "settle", [50, *limbs])
T.check("1. on the new chain the carried book takes a new order and settles it with the secret",
        cell(new, oc, O.ST, 50) == O.SETTLED and cell(new, oc, O.ST, 2) == O.SETTLED, r)
r = call(new, oc, TK, "settle", [2, *limbs])
T.check("1. ...while a carried settled order can never be settled again", r.find("-> ok") < 0, r)
T.done("ALL PASS — an open swap, a taken loan or a live game refuses a reroll carry, and a closed one crosses it")
