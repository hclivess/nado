"""A carried exec genesis commits every slot where the settle proof looks for it: the KV half of the genesis root holds
every carried slot as the 256-bit integer leaf the Stwo span settlement opens (tools/alphanet6_carryforward.int_slots).

Found 2026-10-11 (review): the reroll hooks re-pinned heights by writing STRING slot values (pets / autogame put(),
_lib.rebase_daily_anchors). The exec root's kv_projection commits a slot at its slot position only when the value is an
int — anything else becomes a KVX digest record — while the settle proof reads every slot as an integer. So the carried
genesis root was one no settle proof could extend until every rebased contract had been called again, and forever for
one nobody calls. In G9 the Goldilocks settle proof (settlement_sparse.sparse_projection, which int()ed every slot) was
deleted; on gen 29 the settle proof is the Stwo span settlement (execnode/settle_b2.py), which opens a slot as a 256-bit
integer leaf and REFUSES (Unprovable) a slot that is not one — so a string slot is still a contract no settle can touch.

Pins, on the REAL autogame contract (a parked run and a pinned day anchor, both re-pinned by the carry) and a contract
whose fixture slots are strings:
  1. the detector works: a string slot makes the exec root commit a KVX record where the settle proof opens a slot,
     and the settle proof refuses it;
  2. every slot of every carried contract is an int;
  3. the exec root's KV projection == the leaves the settle proof opens, over the carried contracts, so the genesis
     root's KV half is one a settle proof can extend;
  4. a slot value that is not an integer refuses the carry rather than being guessed.

Run: python3 tests/test_a_carried_genesis_root_is_the_root_a_settle_proof_pins.py
"""
import os, sys, json, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-carry-int-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
H = os.environ["HOME"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from execnode.state import ExecState
from execnode.games import autogame as G, faucet
from execnode import exec_root_b2 as ER
from execnode import settle_b2 as SB
import tools.alphanet6_carryforward as C

import _harness
_report = _harness.Report()
check = _report.check


def settle_projection(contracts):
    """{leaf key: leaf} for the KV half as the Stwo span settlement opens it: each contract's meta and code leaves and
    each storage slot through settle_b2's own slot rule (a 256-bit integer leaf, or Unprovable). Only `slots` is a
    family the settlement opens; any other storage map is a KVX record it cannot prove."""
    out = {}
    for cid in sorted(contracts):
        c = contracts[cid]
        out.update(SB._contract_leaves((cid,), c))
        for m, kv in (c.get("storage") or {}).items():
            if m != "slots":
                raise SB.Unprovable(f"storage map {m!r} of {cid} is a KVX record")
            for k, v in kv.items():
                out.update(SB._slot_leaves((cid, k), v))
    return out


def unprovable(contracts):
    try:
        settle_projection(contracts)
        return False
    except SB.Unprovable:
        return True


A = "ndoA" + "a" * 44
_n = [0]


def call(st, cid, who, m, args, value=None):
    _n[0] += 1
    p = {"op": "call", "contract": cid, "method": m, "args": args}
    if value:
        p["value"] = value
    return st.apply_blob(p, who, f"{m}-{_n[0]}")


old = ExecState(os.path.join(H, "old.json"))
old.cursor, old.block_ts = 150_000, int(time.time())
old.block_hashes = {h: (h * 2_654_435_761 + 3) % (1 << 61) for h in range(140_000, 160_000)}
code = G.build()
old.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": G.ABI, "nonce": "n"}, A, "d")
cid = old.contract_id(A, code, "n")
rd = lambda f, k: int((old.contracts[cid]["storage"].get("slots") or {}).get(str((f << 32) + k), 0))
r = call(old, cid, A, "begin", [7])                       # a run whose first terrain is pinned in the future
day = old.block_ts // 86400
r2 = call(old, cid, A, "anchor", [day])                    # a day anchor pinned, not yet resolved
TIP = old.cursor
check("setup: a live run with a future terrain and an unresolved day anchor",
      rd(G.RLH, 7) > TIP and rd(G.A_H, day) > TIP and not rd(G.A_V, day), (r, r2, rd(G.RLH, 7), rd(G.A_H, day)))

contracts = {
    cid: json.loads(json.dumps(old.contracts[cid])),
    "faucet": {"code": json.loads(json.dumps(faucet.build())), "abi": faucet.ABI, "deployer": A, "runtime": "zkvm",
               "upgradable": True, "storage": {"slots": {"7": "5000", "8": "0"}}},     # string slots, as a fixture
}

# 1. the detector: one string slot moves the KV projection away from the sparse one
probe = {"faucet": json.loads(json.dumps(contracts["faucet"]))}
check("1. a string slot is a KVX record in the exec root, not the slot leaf the settle proof opens",
      ER.slot_key("faucet", 7) not in ER.kv_projection(probe)
      and ER.kvx_key("faucet", "slots", "7", "5000") in ER.kv_projection(probe))
check("...and the settle proof refuses it (Unprovable), so no settle could extend that root", unprovable(probe))

C.CARRY_BLOCKERS.clear()
gen, _kept = C.exec_genesis_doc(contracts, {}, tip=TIP)
check("setup: both contracts carry with their storage", C.CARRY_BLOCKERS == {} and gen[cid]["storage"]["slots"], C.CARRY_BLOCKERS)
check("...the run's terrain and the day anchor were re-pinned onto the new chain",
      int(gen[cid]["storage"]["slots"][str((G.RLH << 32) + 7)]) < 100
      and int(gen[cid]["storage"]["slots"][str((G.A_H << 32) + day)]) < 100)
bad = [(c, k, v) for c, rec in gen.items() for k, v in (rec["storage"].get("slots") or {}).items() if type(v) is not int]
check("2. every slot of every carried contract is an int", bad == [], bad[:5])
check("3. the carried KV projection IS the leaf set a settle proof opens (genesis root provable)",
      not unprovable(gen) and ER.kv_projection(gen) == settle_projection(gen))
rt = json.loads(json.dumps(gen))
check("...and the same holds after the genesis file's JSON round trip",
      not unprovable(rt) and ER.kv_projection(rt) == settle_projection(rt))

try:
    C.int_slots({"slots": {"1": "not-a-number"}})
    refused = False
except ValueError:
    refused = True
check("4. a slot value that is not an integer refuses the carry", refused)
print("ALL PASS — a carried genesis root is the root a settle proof pins" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
