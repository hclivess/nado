"""A contract carried across a reroll plays on the new chain EXACTLY as it would have played on the old one (tools/carry.py,
tools/alphanet6_carryforward.exec_genesis, execnode/exec_genesis.py, doc/stwo/g5-carry.md) — the carry is lossless where
it matters: what a player is owed and what their pet produces.

This is the v2 -> v2 carry every reroll from generation 29 on runs: the old chain is a live-shaped exec state (the zkvm2
VM, the BLAKE2s exec root) saved as the exec node saves it; the carry is tools/carry.py on a copy of that file and the
builder's exec_genesis at the old chain's tip (its exec cursor — what build() passes); the new chain is a fresh layer
loaded by the real genesis loader. The same calls are played on both, the new chain `h` blocks past its block 0 standing
for the old chain `h` blocks past its tip (heights do not advance while the chain is down). (Replaces the gen-28 ->
gen-29 test G9 slice 3a retired with the field VM; SCHEDULED_CLEANUPS.md 2026-10-27.)
  1. bet — tote stakes and book positions (hash keys over owner digests), a resolver row (a hash key over a STRING
     argument's digest): on the new chain the views report the same stakes, the carried resolver resolves, and each
     claim pays EXACTLY what the same claim pays on the old chain;
  2. pets — a farm staffed by a pet BEFORE the tip, so production has accrued and is not yet banked when the carry is
     built: the carry banks it to the owner (pets._bank_at_tip, the contract's own _accrue at the tip), so the owner
     holds EXACTLY what the old chain gives them had anyone made the permissionless collect() at the tip — not one
     unit lost (a carry is that collect; plain equality with an uncollected chain cannot hold, because two collects
     floor and cap twice by the contract's own rule). A farm staffed AT the tip produces exactly the old chain's
     harvest (the worker keeps its trade stat: one VM hash on both sides);
  3. the carried records are the old ones (one VM: no slot re-keyed or re-valued, the code each module's build, the
     registry as it was) except the heights carry_rebase moves;
  4. the carried genesis loads into a fresh layer, its root is genesis_root(), and the pots are the old chain's.

Run: python3 tests/test_a_carried_contract_plays_exactly_as_it_would_have_without_the_carry.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-carry-plays-")
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
from execnode.games import bet as B, pets as P
from execnode import exec_genesis as EG
import tools.alphanet6_carryforward as C

import _harness
T = _harness.Report()
BANK, A, CC, R1, OWN = "ndoBANK", "ndoAAA", "ndoCCC", "ndoRES1", "ndoPETS"
UNIT, M, TIP = B.UNIT, 77, 5000
ELAPSED = 900                                         # blocks past the tip at which both chains collect


def fresh(path):
    st = ExecState(os.path.join(HOME, path))
    st.cursor, st.block_ts = TIP - 2000, int(time.time())
    st.block_hashes = {h: (h * 1_000_003 + 7) for h in range(0, TIP + 4000)}
    st.beacons = {e: (e * 7_919_993 + 11) for e in range(0, (TIP + 4000) // 60 + 10)}
    return st


def call(st, cid, who, method, args, value=None, tag=""):
    p = {"op": "call", "contract": cid, "method": method, "args": args}
    if value:
        p["value"] = value
    return st.apply_blob(p, who, f"{method}{tag}{who}{args}{st.cursor}")


# ---- the old chain: a market with tote and book positions, and two working farms ------------------------------------
old = fresh("old.json")
for w in (BANK, A, CC, OWN):
    old.credit_deposit(w, 10**13)
bcode = B.build()
old.apply_blob({"op": "deploy", "runtime": "zkvm", "code": bcode, "abi": B.ABI, "nonce": "b"}, BANK, "db")
bc = old.contract_id(BANK, bcode, "b")
lock = old.block_ts + 3600
r = call(old, bc, BANK, "create_market", [M, 3, lock, lock + 7200, "Final?\nHome\nAway\nDraw", "src", "ev", 1, R1, 0, 0])
T.check("setup: a market is created", r.endswith("-> ok"), r)
call(old, bc, A, "bet", [M, 0], 30 * UNIT)
call(old, bc, CC, "bet", [M, 1], 10 * UNIT)
call(old, bc, BANK, "book", [M], 500 * UNIT)
call(old, bc, BANK, "quote", [M, 2, 250])
call(old, bc, CC, "back", [M, 2], 40 * UNIT)

pcode = P.build()
old.apply_blob({"op": "deploy", "runtime": "zkvm", "code": pcode, "abi": P.ABI, "nonce": "p"}, OWN, "dp")
pc = old.contract_id(OWN, pcode, "p")
prd = lambda st, f, k: int((st.contracts[pc]["storage"].get("slots") or {}).get(str((f << 32) + k), 0))
farmers = []
for pid in range(1000, 1800):
    call(old, pc, OWN, "mint", [pid], P.MINT_FEE)
    old.cursor += 3
    call(old, pc, OWN, "hatch", [pid])
    if prd(old, P.GN, pid) and prd(old, P.SI, pid) % P.NJOBS == 0:
        farmers.append(pid)
        if len(farmers) == 2:
            break
T.check("setup: two hatched pets of the farming trade", len(farmers) == 2, farmers)
call(old, pc, OWN, "build", [1, 0, farmers[0]], P.BUILD_FEE)
r = call(old, pc, OWN, "staff", [1, farmers[0]])
early = prd(old, P.BSI, 1)
T.check("setup: farm 1 is built and staffed well before the tip", prd(old, P.BP, 1) == farmers[0] and early < TIP - 1000,
        (r, early))
old.cursor = TIP
call(old, pc, OWN, "build", [2, 0, farmers[1]], P.BUILD_FEE)
call(old, pc, OWN, "staff", [2, farmers[1]])
T.check("setup: farm 2 is built and staffed at the tip", prd(old, P.BP, 2) == farmers[1] and prd(old, P.BSI, 2) == TIP)
snapshot = copy.deepcopy({"contracts": old.contracts, "zk_addrs": old.zk_addrs, "bridge": old.bridge})
VIEWS = (("stake_of", [M, 0, A]), ("stake_of", [M, 1, CC]), ("total_of", [M, CC]), ("bstake_of", [M, 2, CC]),
         ("bpay_of", [M, 2, CC]), ("claimed_of", [M, A]))
views_old = {(m, str(a)): old.view(bc, m, a) for m, a in VIEWS}
old.save()
cp = os.path.join(HOME, "exec_state.copy.json")
shutil.copyfile(old.path, cp)
# the reachable old-chain history the carry stands for: somebody collects farm 1 AT the tip (collect is permissionless)
shutil.copyfile(old.path, os.path.join(HOME, "alt.json"))
alt = ExecState(os.path.join(HOME, "alt.json"))
alt.block_hashes, alt.beacons = dict(old.block_hashes), dict(old.beacons)
T.check("setup: the saved old chain reloads as itself", alt.state_root() == old.state_root() and alt.cursor == TIP)
fodder0 = alt.view(pc, "res_of", [OWN, 0])
call(alt, pc, BANK, "collect", [1], tag="tip")
tip_gain = alt.view(pc, "res_of", [OWN, 0]) - fodder0
T.check("setup: farm 1 holds unbanked production at the tip (a collect there pays its owner)", tip_gain > 0, tip_gain)
p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "carry.py"), cp], capture_output=True, text=True,
                   timeout=900)
T.check("tools/carry.py carries the saved state at its tip: both contracts", p.returncode == 0
        and "contracts carried: 2 (every one)" in p.stdout, (p.returncode, (p.stdout + p.stderr)[-600:]))


def play(st, at):
    """collect both farms and settle the market `at` blocks past the tip; (harvests, payouts)"""
    st.cursor = at
    call(st, pc, OWN, "collect", [1])
    h1 = st.view(pc, "res_of", [OWN, 0])
    call(st, pc, OWN, "collect", [2])
    h2 = st.view(pc, "res_of", [OWN, 0]) - h1
    st.block_ts = lock + 1
    rr = call(st, bc, R1, "resolve", [M, 2])
    pay = {"resolve": rr.endswith("-> ok")}
    for w, meth in ((A, "claim"), (CC, "claim"), (CC, "bclaim")):
        b4 = st.bridge.get(w, 0)
        call(st, bc, w, meth, [M])
        pay[(w, meth)] = st.bridge.get(w, 0) - b4
    return {"farm 1 (staffed before the tip)": h1, "farm 2 (staffed at the tip)": h2}, pay


harv_old, pay_old = play(old, TIP + ELAPSED)
harv_alt, _ = play(alt, TIP + ELAPSED)
T.check("setup: on the old chain both farms produce and the winner's book position pays",
        all(harv_old.values()) and pay_old[(CC, "bclaim")] == 100 * UNIT, (harv_old, pay_old))

# ---- the carry (the reroll builder's path, at the old chain's tip) --------------------------------------------------
pots = {cid: int(snapshot["bridge"].get(cid, 0)) for cid in snapshot["contracts"]}
recs, kept, reg = C.exec_genesis(snapshot["contracts"], pots, snapshot["zk_addrs"], TIP)
T.check("3. bet carries every slot unchanged (its storage holds no height), the code its build",
        recs[bc]["storage"]["slots"] == {k: int(v) for k, v in snapshot["contracts"][bc]["storage"]["slots"].items()}
        and recs[bc]["code"] == json.loads(json.dumps(B.build())))
ps_old = {k: int(v) for k, v in snapshot["contracts"][pc]["storage"]["slots"].items()}
moved = sorted(k for k, v in recs[pc]["storage"]["slots"].items() if ps_old.get(k) != v)
HEIGHTS = (P.BH, P.FU, P.EX, P.TH, P.BSI, P.BDP)
banked = {k: recs[pc]["storage"]["slots"][k] - ps_old.get(k, 0) for k in moved if (int(k) >> 32) not in HEIGHTS}
T.check("3. pets carries every slot, re-keying none; only stored heights (carry_rebase) and the owner's banked "
        "production (exactly the tip collect's) move",
        set(ps_old) <= set(recs[pc]["storage"]["slots"]) and list(banked.values()) == [tip_gain]
        and recs[pc]["code"] == json.loads(json.dumps(P.build())), (moved, banked, tip_gain))
T.check("3. the registry crosses as it is", reg == snapshot["zk_addrs"])

# ---- the new chain --------------------------------------------------------------------------------------------------
json.dump({"generation": PR.CHAIN_GENERATION, "contracts": recs, "bridge": {c: str(v) for c, v in kept.items()},
           "zk_addrs": reg}, open(os.environ["NADO_EXEC_GENESIS"], "w"))
EG._CACHE.clear()
new = fresh("new.json")
new.cursor = -1
T.check("4. the carried genesis loads into a fresh layer", EG.apply(new) and sorted(new.contracts) == sorted(recs))
T.check("4. ...its root is genesis_root(), and the pots are the old chain's",
        new.state_root() == EG.genesis_root() and {c: int(new.bridge.get(c, 0)) for c in recs} == pots)
new.cursor, new.block_ts = 10, old.block_ts
views_new = {(m, str(a)): new.view(bc, m, a) for m, a in VIEWS}
T.check("1. the carried views report exactly the old chain's positions", views_new == views_old
        and views_old[("stake_of", str([M, 0, A]))] == 30 * UNIT and views_old[("bpay_of", str([M, 2, CC]))] == 100 * UNIT,
        (views_new, views_old))
harv_new, pay_new = play(new, ELAPSED)
T.check("1. the carried resolver resolves, and every claim pays exactly what it pays on the old chain",
        pay_new == pay_old, (pay_new, pay_old))
T.check("2. a farm staffed AT the tip produces exactly the old chain's harvest the same blocks later",
        harv_new["farm 2 (staffed at the tip)"] == harv_old["farm 2 (staffed at the tip)"], (harv_new, harv_old))
# THE PROPERTY, stated whole: production a building accrued on the old chain and had not banked when the carry was
# built is the owner's, exactly as a pot or a stake is. Found 2026-10-28 (v2 -> v2 rewrite): pets.carry_rebase moved
# BSI (the since-block) to max(0, BSI - tip) = 0 with nothing banked, so the (tip - BSI) blocks the farm earned before
# the tip were dropped (4 fodder instead of 13 here). Fixed by pets._bank_at_tip.
T.check("2. a farm staffed BEFORE the tip leaves its owner exactly what the old chain pays with a collect at the tip "
        "(production accrued before the carry is not lost)",
        harv_new["farm 1 (staffed before the tip)"] == harv_alt["farm 1 (staffed before the tip)"]
        and harv_new["farm 1 (staffed before the tip)"] >= harv_old["farm 1 (staffed before the tip)"] - 1,
        (harv_new, harv_alt, harv_old))
T.done("ALL PASS — a carried contract plays exactly as it would have without the carry")
