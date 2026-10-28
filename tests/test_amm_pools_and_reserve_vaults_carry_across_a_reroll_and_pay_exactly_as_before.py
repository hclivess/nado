"""An AMM pool and a reserve vault cross the reroll carry and pay EXACTLY what they would have paid on the old chain
(execnode/games/dex.py and reserve.py carry hooks, tools/carry.py, tools/alphanet6_carryforward.exec_genesis and
exec_assets_doc, execnode/exec_genesis.py).

This is the v2 -> v2 carry every reroll from generation 29 on runs: the old chain is a live-shaped exec state (the zkvm2
VM, the BLAKE2s exec root, exec assets) saved as the exec node saves it, carried by tools/carry.py on a copy of that
file and by the builder's exec_genesis + exec_assets_doc (asset ids re-derived by carry.asset_map), then loaded into a
fresh layer by the real genesis loader; the same calls are played on both chains. (Replaces the gen-28 -> gen-29 test G9
slice 3a retired with the field VM; SCHEDULED_CLEANUPS.md 2026-10-27.)
  1. dex — a seeded pool, an LP position, a staged-but-unjoined deposit and a pool on an asset id that names no asset
     (open() never checks it): every slot is carried unchanged (one VM: nothing re-keyed), the made-up id kept verbatim
     (refusing it would let one free open() veto the carry); on the new chain a swap pays the same units, the LP's exit
     pays the same NADO and tokens, and the staged deposit refunds in full;
  2. reserve — a vault with an ANNOUNCED release: its unlock height `rdy` (an old-chain height) is rebased so the holders
     keep exactly the notice that was left; on the new chain a redemption pays the same, a release one block early is
     refused, and at the rebased height it pays what the old chain pays at the old one;
  3. both carry at rest (no in-flight rule blocks them); the asset records, balances and the carried genesis root load
     exactly (genesis_root()).

Run: python3 tests/test_amm_pools_and_reserve_vaults_carry_across_a_reroll_and_pay_exactly_as_before.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-carry-dex-reserve-")
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
from execnode.state import ExecState, asset_id
from execnode.games import dex as D, reserve as R
from execnode import exec_genesis as EG
from tools import carry
import tools.alphanet6_carryforward as C

import _harness
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
    code = mod.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": mod.ABI, "nonce": nonce}, who, "d" + nonce)
    return st.contract_id(who, code, nonce)


def carry_cli(st):
    """tools/carry.py exactly as the operator runs it: on a saved COPY of the exec node's state file. (exit, output)"""
    st.save()
    cp = os.path.join(HOME, "copy-" + os.path.basename(st.path))
    shutil.copyfile(st.path, cp)
    p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "carry.py"), cp], capture_output=True, text=True,
                       timeout=900)
    return p.returncode, p.stdout + p.stderr


nat = lambda st, w: int(st.bridge.get(w, 0))
tok = lambda st, a, w: int((st.abal.get(str(a)) or {}).get(w, 0))
cell = lambda rec, f, k: int(rec["storage"]["slots"].get(str((f << 32) + k), 0))

# ---- the old chain --------------------------------------------------------------------------------------------------
old = fresh("old.json", 100_000)
for w in (ISS, LP, LP2, TR, HOL):
    old.bridge[w] = 10 ** 15
old.apply_blob({"op": "asset_create", "seed": 1, "name": "Pair", "sym": "PAIR", "dec": 0, "supply": 10 ** 15,
                "mintable": False}, ISS, "a1")
old.apply_blob({"op": "asset_create", "seed": 2, "name": "Backed", "sym": "BACK", "dec": 0, "supply": 10 ** 6,
                "mintable": False}, ISS, "a2")
A1, A2 = asset_id(ISS, 1), asset_id(ISS, 2)
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
T.check("setup: a seeded pool, an LP position, a staged deposit and a pool on a made-up asset id",
        shares == 5000 and cell(old.contracts[dc], D.PPN, 11) == 300 and cell(old.contracts[dc], D.AST, 2) == MADE_UP, r)

rc = deploy(old, R, ISS, "reserve")
call(old, rc, ISS, "open", [5, A2, 5000, R.MIN_NOTICE, 1000], 1000 * U)
call(old, rc, ISS, "announce", [5, 400])
call(old, rc, HOL, "redeem", [5], 100, A2)
rdy_old = cell(old.contracts[rc], R.RDY, 5)
TIP = old.cursor + 5000
T.check("setup: a vault with an announced release and a redemption",
        rdy_old == 100_000 + R.MIN_NOTICE and cell(old.contracts[rc], R.OUT, 5) == 4900, rdy_old)
old.cursor = TIP
T.check("setup: the old state's asset ids are the one (BLAKE2s) id format the carry re-derives",
        carry.asset_map(old.assets) == {A1: A1, A2: A2})

snap = copy.deepcopy({"contracts": old.contracts, "zk_addrs": old.zk_addrs, "bridge": old.bridge, "assets": old.assets,
                      "abal": old.abal, "allow": old.allow})
T.check("3. neither contract is in flight at rest (dex declares CARRY_STORAGE; reserve has no blocking rule)",
        D.CARRY_STORAGE is True and not hasattr(D, "carry_in_flight") and not hasattr(R, "carry_in_flight"))
code, out = carry_cli(old)
T.check("3. tools/carry.py carries the saved state: both contracts and both assets",
        code == 0 and "contracts carried: 2 (every one)" in out and "assets: 2" in out, (code, out[-600:]))


# ---- what the old chain pays from here ------------------------------------------------------------------------------
def play(st, release_at, early):
    out = {}
    b = (nat(st, TR), tok(st, A1, TR))
    call(st, dc, TR, "swapt", [1, 50, 0], 50 * U, A1)
    out["swapt"] = (nat(st, TR) - b[0], b[1] - tok(st, A1, TR))
    b = (nat(st, LP), tok(st, A1, LP))
    call(st, dc, LP, "exit", [10, 1, shares, A1])
    out["exit"] = (nat(st, LP) - b[0], tok(st, A1, LP) - b[1])
    b = nat(st, LP2)
    call(st, dc, LP2, "refund", [11, 1, A1])
    out["refund"] = nat(st, LP2) - b
    b = nat(st, HOL)
    call(st, rc, HOL, "redeem", [5], 200, A2)
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


before = play(old, rdy_old, rdy_old - 1)
T.check("setup: on the old chain the swap, exit, refund, redemption and release all pay",
        all(before[k] for k in ("swapt", "exit", "refund", "redeem", "release")) and before["early_release"] == 0
        and before["refund"] == 300 * U, before)

# ---- the carry (the reroll builder's path) --------------------------------------------------------------------------
amap = carry.asset_map(snap["assets"])
pots = {cid: int(snap["bridge"].get(cid, 0)) for cid in snap["contracts"]}
recs, kept, reg = C.exec_genesis(snap["contracts"], pots, snap["zk_addrs"], TIP)
adoc = C.exec_assets_doc(snap, amap)
T.check("1. every dex slot is carried unchanged — the LP's owner digest and the asset id as they were",
        recs[dc]["storage"]["slots"] == {k: int(v) for k, v in snap["contracts"][dc]["storage"]["slots"].items()}
        and cell(recs[dc], D.AST, 1) == A1)
T.check("1. a pool on an asset id that names no asset keeps it verbatim (one free open() cannot veto the carry)",
        cell(recs[dc], D.AST, 2) == MADE_UP)
rs_old = {k: int(v) for k, v in snap["contracts"][rc]["storage"]["slots"].items()}
rs_new = recs[rc]["storage"]["slots"]
k_rdy = str((R.RDY << 32) + 5)
T.check("2. the announced release keeps exactly the notice it had left (rdy rebased to rdy - tip), nothing else moves",
        rs_new[k_rdy] == rdy_old - TIP and {k: v for k, v in rs_new.items() if k != k_rdy}
        == {k: v for k, v in rs_old.items() if k != k_rdy}, rs_new.get(k_rdy))
T.check("3. the carried code is each module's build", recs[dc]["code"] == json.loads(json.dumps(D.build()))
        and recs[rc]["code"] == json.loads(json.dumps(R.build())))
T.check("3. the asset records and every non-zero holding cross under their own ids",
        adoc["assets"] == snap["assets"]
        and adoc["abal"] == {a: {h: str(n) for h, n in sorted(hs.items()) if n} for a, hs in sorted(snap["abal"].items())})

# ---- the new chain --------------------------------------------------------------------------------------------------
json.dump({"generation": PR.CHAIN_GENERATION, "contracts": recs, "bridge": {c: str(v) for c, v in kept.items()},
           "zk_addrs": reg, **adoc}, open(os.environ["NADO_EXEC_GENESIS"], "w"))
EG._CACHE.clear()
new = fresh("new.json", -1)
T.check("3. the carried genesis loads into a fresh layer", EG.apply(new) and sorted(new.contracts) == sorted(recs))
T.check("3. ...its root is genesis_root(), the pots and the contracts' token holdings are the old chain's",
        new.state_root() == EG.genesis_root() and {c: nat(new, c) for c in recs} == pots
        and all(tok(new, a, c) == int(snap["abal"].get(str(a), {}).get(c, 0)) for a in (A1, A2) for c in recs))
new.cursor = 10
for w in (ISS, LP, LP2, TR, HOL):
    new.bridge[w] = int(snap["bridge"][w])
after = play(new, rdy_old - TIP, rdy_old - TIP - 1)
T.check("1. on the new chain the swap pays the same, the LP's exit takes the same slice of both sides, the staged "
        "deposit refunds in full", all(after[k] == before[k] for k in ("swapt", "exit", "refund")), (after, before))
T.check("2. on the new chain a redemption pays the same, a release one block early is refused, and at the rebased "
        "height it pays what the old chain paid", all(after[k] == before[k] for k in ("redeem", "early_release", "release")),
        (after, before))
T.done("ALL PASS — AMM pools and reserve vaults carry across a reroll and pay exactly as before")
