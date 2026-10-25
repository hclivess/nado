"""An AMM pool and a reserve vault cross the gen-29 carry and pay EXACTLY what they would have paid on gen 28
(execnode/games/dex.py and reserve.py carry hooks, tools/carry.py, doc/stwo/g5-carry.md).

Driving the REAL dex and reserve contracts on a gen-28 exec state, carrying them through tools/carry.carry_contracts (with
the asset map that re-derives every exec asset id under the new hash) into a gen-29 state loaded by the real genesis
loader (protocol.BLAKE_EXEC_HEIGHT = 1), and playing the same calls on both:
  1. dex — a seeded pool, an LP position, a staged-but-unjoined deposit and a pool on an asset id that names no asset
     (open() never checks it): every slot is accounted for, the owner digests and the real asset id are remapped, the
     made-up id is kept verbatim (refusing it would let one free open() veto the carry); on gen 29 a swap pays the same
     units, the LP's exit pays the same NADO and tokens, and the staged deposit refunds in full;
  2. reserve — a vault with an ANNOUNCED release: its unlock height `rdy` (an old-chain height) is rebased so the holders
     keep exactly the notice that was left; on gen 29 a redemption pays the same as on gen 28, a release one block
     early is refused, and at the rebased height it pays what gen 28 pays at the old one;
  3. both carry as at rest (no in-flight rule blocks them), and the carried code is each module's v2 build.

Run: python3 tests/test_amm_pools_and_reserve_vaults_carry_to_gen29_and_pay_exactly_as_on_gen28.py
"""
import _harness
HOME = _harness.isolate("nado-test-carry-dex-reserve-")
import copy
import json
import os
import time

import protocol as PR
from execnode.state import ExecState, asset_id
from execnode.games import dex as D, reserve as R
from execnode import exec_genesis as EG
from execnode.runtimes import zkvm_addr_digest
from tools import carry
import tools.alphanet6_carryforward as C

T = _harness.Report()
ISS, LP, LP2, TR, HOL = "ndoISS", "ndoLP", "ndoLP2", "ndoTRADER", "ndoHOLDER"
U = D.UNIT
MADE_UP = 12_345_678_901_234_567           # an asset id no asset_create ever produced (>= 2^32)
NOW = int(time.time())


def fresh(path, cursor):
    st = ExecState(os.path.join(HOME, path))
    st.cursor, st.block_ts = cursor, NOW
    return st


_n = [0]


def call(st, cid, who, m, args, value=0, asset=0):
    _n[0] += 1
    return st.apply_blob({"op": "call", "contract": cid, "method": m, "args": args, "value": value, "asset": asset},
                         who, f"{m}-{_n[0]}")


def deploy(st, mod, who, nonce):
    code = mod.build("v1")
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": mod.ABI, "nonce": nonce}, who, "d" + nonce)
    return st.contract_id(who, code, nonce)


nat = lambda st, w: int(st.bridge.get(w, 0))
tok = lambda st, a, w: int((st.abal.get(str(a)) or {}).get(w, 0))
cell = lambda rec, f, k: int(rec["storage"]["slots"].get(str((f << 32) + k), 0))

# ---- gen 28 -----------------------------------------------------------------------------------------------------------
old = fresh("old.json", 100_000)
for w in (ISS, LP, LP2, TR, HOL):
    old.bridge[w] = 10 ** 15
old.apply_blob({"op": "asset_create", "seed": 1, "name": "Pair", "sym": "PAIR", "dec": 0, "supply": 10 ** 15,
                "mintable": False}, ISS, "a1")
old.apply_blob({"op": "asset_create", "seed": 2, "name": "Backed", "sym": "BACK", "dec": 0, "supply": 10 ** 6,
                "mintable": False}, ISS, "a2")
A1, A2 = asset_id(ISS, 1, False), asset_id(ISS, 2, False)
for w, a, n in ((LP, A1, 10 ** 13), (TR, A1, 10 ** 13), (HOL, A2, 5000)):
    old.apply_blob({"op": "asset_transfer", "asset": str(a), "to": w, "amount": n}, ISS, f"t{w}{a}")

dc = deploy(old, D, ISS, "dex")
call(old, dc, ISS, "open", [1, A1])
call(old, dc, LP, "fundn", [10, 1, 5000], 5000 * U)
call(old, dc, LP, "fundt", [10, 1, 20000], 20000 * U, A1)
r = call(old, dc, LP, "join", [10, 1])
call(old, dc, TR, "swapn", [1, 100, 0, A1], 100 * U)
call(old, dc, LP2, "fundn", [11, 1, 300], 300 * U)            # staged, never joined: refundable at any time
call(old, dc, TR, "open", [2, MADE_UP])
shares = cell(old.contracts[dc], D.PSH, 10)
T.check("setup: a seeded pool, an LP position, a staged deposit and a pool on a made-up asset id, on gen 28",
        shares == 5000 and cell(old.contracts[dc], D.PPN, 11) == 300 and cell(old.contracts[dc], D.AST, 2) == MADE_UP, r)

rc = deploy(old, R, ISS, "reserve")
call(old, rc, ISS, "open", [5, A2, 5000, R.MIN_NOTICE, 1000], 1000 * U)
call(old, rc, ISS, "announce", [5, 400])
call(old, rc, HOL, "redeem", [5], 100, A2)
rdy_old = cell(old.contracts[rc], R.RDY, 5)
TIP = old.cursor + 5000
T.check("setup: a vault with an announced release and a redemption, on gen 28",
        rdy_old == 100_000 + R.MIN_NOTICE and cell(old.contracts[rc], R.OUT, 5) == 4900, rdy_old)
old.cursor = TIP

snap = copy.deepcopy({"contracts": old.contracts, "zk_addrs": old.zk_addrs, "bridge": old.bridge, "assets": old.assets,
                      "abal": old.abal, "allow": old.allow})

T.check("3. neither contract is in flight at rest (dex declares CARRY_STORAGE; reserve has no blocking rule)",
        D.CARRY_STORAGE is True and not hasattr(D, "carry_in_flight") and not hasattr(R, "carry_in_flight"))

# ---- what gen 28 pays from here --------------------------------------------------------------------------------------
def play(st, a1, a2, release_at, early):
    out = {}
    b = (nat(st, TR), tok(st, a1, TR))
    call(st, dc, TR, "swapt", [1, 50, 0], 50 * U, a1)
    out["swapt"] = (nat(st, TR) - b[0], b[1] - tok(st, a1, TR))
    b = (nat(st, LP), tok(st, a1, LP))
    call(st, dc, LP, "exit", [10, 1, shares, a1])
    out["exit"] = (nat(st, LP) - b[0], tok(st, a1, LP) - b[1])
    b = nat(st, LP2)
    call(st, dc, LP2, "refund", [11, 1, a1])
    out["refund"] = nat(st, LP2) - b
    b = nat(st, HOL)
    call(st, rc, HOL, "redeem", [5], 200, a2)
    out["redeem"] = nat(st, HOL) - b
    st.cursor = early
    b = nat(st, ISS)
    call(st, rc, ISS, "release", [5])
    out["early_release"] = nat(st, ISS) - b
    st.cursor = release_at
    b = nat(st, ISS)
    call(st, rc, ISS, "release", [5])
    out["release"] = nat(st, ISS) - b
    return out


g28 = play(old, A1, A2, rdy_old, rdy_old - 1)
T.check("setup: on gen 28 the swap, exit, refund, redemption and release all pay",
        all(g28[k] for k in ("swapt", "exit", "refund", "redeem", "release")) and g28["early_release"] == 0
        and g28["refund"] == 300 * U, g28)

# ---- the carry --------------------------------------------------------------------------------------------------------
amap = carry.asset_map(snap["assets"])
recs, reg, counts = carry.carry_contracts(snap["contracts"], snap["zk_addrs"], TIP, src="v1", dst="v2", amap=amap)
N1, N2 = amap[A1], amap[A2]
dold, dnew = zkvm_addr_digest(LP, False), zkvm_addr_digest(LP, True)
T.check("1. every dex slot is carried, the LP's digest and the real asset id remapped",
        counts[dc]["slots"] == len(snap["contracts"][dc]["storage"]["slots"]) == len(recs[dc]["storage"]["slots"])
        and cell(recs[dc], D.POW, 10) == dnew and cell(recs[dc], D.AST, 1) == N1 and N1 != A1, counts[dc])
T.check("1. a pool on an asset id that names no asset keeps it verbatim (one free open() cannot veto the carry)",
        cell(recs[dc], D.AST, 2) == MADE_UP and counts[dc]["value_kept_word"] == 1, counts[dc])
T.check("2. the announced release keeps exactly the notice it had left (rdy rebased to rdy - tip)",
        cell(recs[rc], R.RDY, 5) == rdy_old - TIP and cell(recs[rc], R.AST, 5) == N2 and cell(recs[rc], R.OWN, 5)
        == zkvm_addr_digest(ISS, True), cell(recs[rc], R.RDY, 5))
T.check("3. the carried code is each module's v2 build",
        recs[dc]["code"] == json.loads(json.dumps(D.build("v2"))) and recs[rc]["code"] == json.loads(json.dumps(R.build("v2"))))
T.check("1. the pre-carry storage really held the old digest (the remap is not vacuous)",
        cell(snap["contracts"][dc], D.POW, 10) == dold != dnew)

# ---- gen 29 -----------------------------------------------------------------------------------------------------------
gen_file = os.path.join(HOME, "exec_genesis.json")
pots = {cid: str(int(snap["bridge"].get(cid, 0))) for cid in recs if int(snap["bridge"].get(cid, 0))}
json.dump({"generation": PR.CHAIN_GENERATION, "contracts": recs, "bridge": pots, "zk_addrs": reg,
           **C.exec_assets_doc(snap, amap)}, open(gen_file, "w"))
os.environ["NADO_EXEC_GENESIS"] = gen_file
EG._CACHE.clear()
PR.BLAKE_EXEC_HEIGHT = 1
try:
    new = fresh("new.json", -1)
    T.check("3. the carried genesis loads into a fresh gen-29 layer", EG.apply(new) and sorted(new.contracts) == sorted(recs))
    new.cursor = 10
    for w in (ISS, LP, LP2, TR, HOL):
        new.bridge[w] = int(snap["bridge"][w])
    g29 = play(new, N1, N2, rdy_old - TIP, rdy_old - TIP - 1)
    T.check("1. on gen 29 the swap pays the same, the LP's exit takes the same slice of both sides, the staged "
            "deposit refunds in full", all(g29[k] == g28[k] for k in ("swapt", "exit", "refund")), (g29, g28))
    T.check("2. on gen 29 a redemption pays the same, a release one block early is refused, and at the rebased height "
            "it pays what gen 28 paid", all(g29[k] == g28[k] for k in ("redeem", "early_release", "release")), (g29, g28))
finally:
    PR.BLAKE_EXEC_HEIGHT = 1 << 62
T.done("ALL PASS — AMM pools and reserve vaults carry to gen 29 and pay exactly as on gen 28")
