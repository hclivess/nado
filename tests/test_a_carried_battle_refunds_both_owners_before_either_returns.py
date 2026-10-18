"""A carried pets battle refunds BOTH stored owners on the new chain before either of them has made a call there
(execnode/exec_genesis.apply carries the digest -> address registry, `zk_addrs`).

Found 2026-10-11 (review): carried storage names its players by field DIGEST, and a PAY to a digest the registry cannot
resolve reverts (runtimes.split_io). The registry is learned from call boundaries and was not carried, so a fresh layer
knew nobody: refund_battle on a carried battle — permissionless, and paying both owners — reverted until BOTH had made
some exec call on the new chain. One owner who never came back locked the other's stake.

Pins, on the REAL pets contract (throwaway HOME, the carry's own exec_genesis_doc and exec_genesis.apply):
  1. the carry writes the registry into the exec genesis, and apply loads it (the genesis root is unchanged by it);
  2. a third party refunds the carried battle on the new chain, paying each owner their own stake;
  3. without the registry the same refund reverts (the failure this closes).

Run: python3 tests/test_a_carried_battle_refunds_both_owners_before_either_returns.py
"""
import os, sys, json, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-carry-zkaddrs-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
H = os.environ["HOME"]
GEN_FILE = os.path.join(H, "exec_genesis.json")
os.environ["NADO_EXEC_GENESIS"] = GEN_FILE
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from execnode.state import ExecState
from execnode.games import pets as P
from execnode.stark import alghash, field as _F
from execnode import exec_genesis as EG
import protocol
import tools.alphanet6_carryforward as C

import _harness
_report = _harness.Report()
check = _report.check


A, B, X = "ndoA" + "a" * 44, "ndoB" + "b" * 44, "ndoX" + "x" * 44
_n = [0]


def call(st, cid, who, method, args, value=None):
    _n[0] += 1
    p = {"op": "call", "contract": cid, "method": method, "args": args}
    if value:
        p["value"] = value
    return st.apply_blob(p, who, f"{method}-{_n[0]}")


old = ExecState(os.path.join(H, "old.json"))
old.cursor, old.block_ts = 150_000, int(time.time())
old.block_hashes = {h: (h * 1_000_003 + 7) for h in range(140_000, 160_000)}
code = P.build()
old.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": P.ABI, "nonce": "n"}, A, "d")
cid = old.contract_id(A, code, "n")
rd = lambda st, f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str((f << 32) + k), 0))
for who in (A, B):
    old.credit_deposit(who, 20 * P.MINT_FEE)
call(old, cid, A, "mint", [1000], P.MINT_FEE)
call(old, cid, B, "mint", [2000], P.MINT_FEE)
old.cursor += 3
call(old, cid, A, "hatch", [1000])
call(old, cid, B, "hatch", [2000])
old.cursor = max(rd(old, P.EX, 1000), rd(old, P.EX, 2000), old.cursor) + 1
STAKE = 10 ** 9
Hc = lambda x: alghash.hashn([x % _F.P])
r_ch = call(old, cid, A, "challenge", [70, 1000, 2000, Hc(11)], STAKE)
r_ac = call(old, cid, B, "accept", [70, Hc(22)], STAKE)
check("setup: an accepted commit-reveal battle, nobody revealed", "ok" in r_ch and "ok" in r_ac and rd(old, P.WN, 70) == 2,
      (r_ch, r_ac))
TIP = old.cursor
check("setup: the old layer's registry knows both owners", A in old.zk_addrs.values() and B in old.zk_addrs.values())

# the carry, exactly as build() assembles the exec genesis (contracts, pots, assets, registry)
C.CARRY_BLOCKERS.clear()
gen, kept = C.exec_genesis_doc({cid: old.contracts[cid]}, {cid: int(old.bridge.get(cid, 0))}, tip=TIP)
snap = json.loads(json.dumps({"assets": old.assets, "abal": old.abal, "allow": old.allow, "zk_addrs": old.zk_addrs}))
doc = {"generation": int(protocol.CHAIN_GENERATION), "contracts": gen,
       "bridge": {c: str(v) for c, v in kept.items()}, **C.exec_assets_doc(snap),
       "zk_addrs": {str(k): str(v) for k, v in sorted(snap["zk_addrs"].items())}}
with open(GEN_FILE, "w") as f:
    json.dump(doc, f, indent=0, sort_keys=True)
check("1. the carried genesis holds the registry", doc["zk_addrs"] and A in doc["zk_addrs"].values())


def new_layer(registry=True):
    EG._CACHE.clear()
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=H), "new.json"))
    EG.apply(st)
    if not registry:
        st.zk_addrs = {}
    st.cursor, st.block_ts = 0, int(time.time())
    st.block_hashes = {h: (h * 7 + 99) for h in range(0, 5000)}
    return st


new = new_layer()
check("...apply loads it, and the genesis root does not depend on it",
      new.zk_addrs == doc["zk_addrs"] and new_layer(registry=False).state_root() == new.state_root())
new.cursor = rd(new, P.WRD, 70) + 1                               # the reveal window lapsed, neither side revealed
a0, b0 = int(new.bridge.get(A, 0)), int(new.bridge.get(B, 0))
r = call(new, cid, X, "refund_battle", [70])                       # a third party: neither owner has called here
check("2. a third party refunds the carried battle on the new chain before either owner returns",
      "ok" in r and int(new.bridge.get(A, 0)) - a0 == STAKE and int(new.bridge.get(B, 0)) - b0 == STAKE, r)

bare = new_layer(registry=False)
bare.cursor = rd(bare, P.WRD, 70) + 1
r2 = call(bare, cid, X, "refund_battle", [70])
check("3. without the carried registry the same refund reverts (the stake stays locked)",
      "ok" not in r2 and int(bare.bridge.get(A, 0)) == 0, r2)
print("ALL PASS — a carried battle refunds both owners before either returns" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
