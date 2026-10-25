"""A contract carried from generation 28 to 29 plays on the new VM EXACTLY as it would have on the old one (tools/carry.py,
doc/stwo/g5-carry.md) — the carry is lossless where it matters: what a player is owed and what their pet produces.

Gen 29 changes every hash and digest a contract's storage is keyed by: owner digests become 256-bit BLAKE2s, hash-keyed
slots are re-derived under zkvm2.hash_words, and pets re-hash their gene for every trait. Driving the REAL bet and pets
contracts on a gen-28 exec state, carrying that state through the real genesis loader into a gen-29 state
(protocol.BLAKE_EXEC_HEIGHT = 1, as gen 29 runs), and playing the same calls on both:
  1. bet — tote stakes and book positions (hash keys over owner digests), a resolver row (a hash key over a STRING
     argument's digest) and the market's description digest: on gen 29 the views report the same stakes, the carried
     resolver can resolve, and each claim pays EXACTLY what the same claim pays on gen 28;
  2. pets — a farm staffed by a pet: its yield reads the worker's trade STAT (a roll of its gene), and the harvest lands
     in a hash-keyed resource row. After the carry, collect() after the same number of blocks produces EXACTLY the same
     harvest as on gen 28 — the roll table carries the gene's gen-28 rolls (without it the stat re-rolls under BLAKE2s);
  3. no slot key or value equal to a gen-28 digest remains, the registry is re-keyed by the new digests, and the
     carried code is each module's v2 build;
  4. the carried genesis loads into a fresh gen-29 layer and its root is genesis_root().

Run: python3 tests/test_a_carried_contract_plays_on_gen29_exactly_as_it_would_have_on_gen28.py
"""
import _harness
HOME = _harness.isolate("nado-test-carry-g29-")
import copy
import json
import os
import time

import protocol as PR
from execnode.state import ExecState
from execnode.games import bet as B, pets as P
from execnode import exec_genesis as EG
from tools import carry

T = _harness.Report()
BANK, A, C, R1, OWN = "ndoBANK", "ndoAAA", "ndoCCC", "ndoRES1", "ndoPETS"
UNIT, M, TIP = B.UNIT, 77, 5000


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


# ---- gen 28: a market with tote and book positions, and a working farm ------------------------------------------------
old = fresh("old.json")
for w in (BANK, A, C, OWN):
    old.credit_deposit(w, 10**13)
bcode = B.build("v1")
old.apply_blob({"op": "deploy", "runtime": "zkvm", "code": bcode, "abi": B.ABI, "nonce": "b"}, BANK, "db")
bc = old.contract_id(BANK, bcode, "b")
lock = old.block_ts + 3600
r = call(old, bc, BANK, "create_market", [M, 3, lock, lock + 7200, "Final?\nHome\nAway\nDraw", "src", "ev", 1, R1, 0, 0])
T.check("setup: a market is created on gen 28", r.endswith("-> ok"), r)
call(old, bc, A, "bet", [M, 0], 30 * UNIT)
call(old, bc, C, "bet", [M, 1], 10 * UNIT)
call(old, bc, BANK, "book", [M], 500 * UNIT)
call(old, bc, BANK, "quote", [M, 2, 250])
call(old, bc, C, "back", [M, 2], 40 * UNIT)

pcode = P.build("v1")
old.apply_blob({"op": "deploy", "runtime": "zkvm", "code": pcode, "abi": P.ABI, "nonce": "p"}, OWN, "dp")
pc = old.contract_id(OWN, pcode, "p")
prd = lambda st, f, k: int((st.contracts[pc]["storage"].get("slots") or {}).get(str((f << 32) + k), 0))
farmer = None
for pid in range(1000, 1400):
    call(old, pc, OWN, "mint", [pid], P.MINT_FEE)
    old.cursor += 3
    call(old, pc, OWN, "hatch", [pid])
    if prd(old, P.GN, pid) and prd(old, P.SI, pid) % P.NJOBS == 0:
        farmer = pid
        break
T.check("setup: a hatched pet of the farming trade", farmer is not None)
call(old, pc, OWN, "build", [1, 0, farmer], P.BUILD_FEE)
r = call(old, pc, OWN, "staff", [1, farmer])
T.check("setup: the farm is built and staffed on gen 28", prd(old, P.BP, 1) == farmer, r)
old.cursor = TIP
staffed_at = prd(old, P.BSI, 1)
snapshot = copy.deepcopy({"contracts": old.contracts, "zk_addrs": old.zk_addrs, "bridge": old.bridge})
VIEWS = (("stake_of", [M, 0, A]), ("stake_of", [M, 1, C]), ("total_of", [M, C]), ("bstake_of", [M, 2, C]),
         ("bpay_of", [M, 2, C]), ("claimed_of", [M, A]))
views28 = {(m, str(a)): old.view(bc, m, a) for m, a in VIEWS}

# what gen 28 pays and produces, played on through the old rules
ELAPSED = 900
g28 = old                                             # the snapshot above is what the carry moves
g28.cursor = staffed_at + ELAPSED
call(g28, pc, OWN, "collect", [1])
harvest28 = g28.view(pc, "res_of", [OWN, 0])
g28.block_ts = lock + 1
call(g28, bc, R1, "resolve", [M, 2])
pay28 = {}
for w, meth in ((A, "claim"), (C, "claim"), (C, "bclaim")):
    b4 = g28.bridge.get(w, 0)
    call(g28, bc, w, meth, [M])
    pay28[(w, meth)] = g28.bridge.get(w, 0) - b4
T.check("setup: on gen 28 the farm produced and the winner's book position paid",
        harvest28 > 0 and pay28[(C, "bclaim")] == 100 * UNIT, (harvest28, pay28))

# ---- the carry ------------------------------------------------------------------------------------------------------
pots = {cid: int(snapshot["bridge"].get(cid, 0)) for cid in snapshot["contracts"]}
recs, reg, counts = carry.carry_contracts(snapshot["contracts"], snapshot["zk_addrs"], staffed_at, src="v1", dst="v2")
old_digests = {int(k) for k in snapshot["zk_addrs"]}
left = [(cid, k, v) for cid, rec in recs.items() for k, v in rec["storage"]["slots"].items()
        if int(k) in old_digests or int(v) in old_digests]
T.check("3. no slot key or value equal to a gen-28 digest remains", not left, left[:3])
T.check("3. the hash keys were re-derived (bet's positions, pets' resource rows) and the digests remapped",
        counts[bc]["key_rehashed"] >= 5 and counts[bc]["value_remapped"] >= 3 and counts[pc]["value_remapped"] >= 2, counts)
T.check("3. the registry is re-keyed by every string's gen-29 digest",
        sorted(reg.values()) == sorted(snapshot["zk_addrs"].values()) and not (set(map(int, reg)) & old_digests))
gn = prd(old, P.GN, farmer)
rt = [recs[pc]["storage"]["slots"].get(str((P._rt(1000 + i) << 32) + farmer)) for i in range(10)]
from execnode.games import _lib
T.check("2. the roll table carries the worker's gen-28 stat rolls — which BLAKE2s would have re-rolled",
        rt == [_lib.vm_hash([gn + 1000 + i], "v1") & 0xFFFFFFFF for i in range(10)]
        and rt != [_lib.vm_hash([gn + 1000 + i], "v2") & 0xFFFFFFFF for i in range(10)], rt)
T.check("3. the carried code is each module's v2 build",
        recs[bc]["code"] == json.loads(json.dumps(B.build("v2"))) and recs[pc]["code"] == json.loads(json.dumps(P.build("v2"))))

# ---- gen 29: the carried genesis, through the real loader -----------------------------------------------------------
gen_file = os.path.join(HOME, "exec_genesis.json")
json.dump({"generation": PR.CHAIN_GENERATION, "contracts": recs, "bridge": {c: str(v) for c, v in pots.items() if v},
           "zk_addrs": reg}, open(gen_file, "w"))
os.environ["NADO_EXEC_GENESIS"] = gen_file
EG._CACHE.clear()
PR.BLAKE_EXEC_HEIGHT = 1
try:
    new = fresh("new.json")
    new.cursor = -1
    T.check("4. the carried genesis loads into a fresh gen-29 layer", EG.apply(new) and sorted(new.contracts) == sorted(recs))
    T.check("4. ...and its root is genesis_root()", new.state_root() == EG.genesis_root())
    new.cursor, new.block_ts = 10, old.block_ts
    v = lambda meth, args: new.view(bc, meth, args)
    views29 = {(m, str(a)): v(m, a) for m, a in VIEWS}
    T.check("1. the carried views report exactly the gen-28 positions", views29 == views28
            and views28[("stake_of", str([M, 0, A]))] == 30 * UNIT and views28[("bpay_of", str([M, 2, C]))] == 100 * UNIT,
            (views29, views28))
    new.cursor = ELAPSED                                  # the farm's clock was rebased to the new block 0
    call(new, pc, OWN, "collect", [1])
    harvest29 = new.view(pc, "res_of", [OWN, 0])
    T.check("2. the carried farm produces EXACTLY its gen-28 harvest after the same blocks (the worker keeps its stat)",
            harvest29 == harvest28, (harvest29, harvest28))
    new.block_ts = lock + 1
    r = call(new, bc, R1, "resolve", [M, 2])
    T.check("1. the carried resolver resolves on gen 29 (its row re-derived over the new digest)", r.endswith("-> ok"), r)
    pay29 = {}
    for w, meth in ((A, "claim"), (C, "claim"), (C, "bclaim")):
        b4 = new.bridge.get(w, 0)
        call(new, bc, w, meth, [M])
        pay29[(w, meth)] = new.bridge.get(w, 0) - b4
    T.check("1. every claim pays exactly what it pays on gen 28", pay29 == pay28, (pay29, pay28))
finally:
    PR.BLAKE_EXEC_HEIGHT = 1 << 62
T.done("ALL PASS — a carried contract plays on gen 29 exactly as it would have on gen 28")
