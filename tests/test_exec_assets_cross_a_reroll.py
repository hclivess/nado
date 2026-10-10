"""Exec assets cross a reroll: records, holdings and allowances (execnode/exec_genesis.py, the carry's exec_assets_doc).

An exec asset has no L1 form to fold into, so the carry used to drop every held token with the generation (and since
2026-10-10, refused to run while one was held). It now carries them verbatim in the exec genesis.

Pins, on the real exec layer (throwaway HOME): a token issued and moved on the old chain is held by the same holders
in the same amounts on the new one, its record (supply, mintable, symbol) is unchanged, an allowance still spends,
and a holder can transfer it on the new chain; the genesis root covers the assets (it differs from a genesis without
them).

Run: python3 tests/test_exec_assets_cross_a_reroll.py
"""
import os, sys, json, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-assets-carry-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
H = os.environ["HOME"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
GEN = os.path.join(H, "exec_genesis.json")
os.environ["NADO_EXEC_GENESIS"] = GEN
import protocol as P
from execnode.state import ExecState
from execnode import exec_genesis as EG
import tools.alphanet6_carryforward as C

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


ISS, HOL, SPN, OUT = "ndoI" + "i" * 44, "ndoH" + "h" * 44, "ndoS" + "s" * 44, "ndoO" + "o" * 44
old = ExecState(os.path.join(H, "old.json"))
old.cursor = 150_000
r = old.apply_blob({"op": "asset_create", "seed": 7, "name": "Carried", "sym": "CRY", "dec": 2, "supply": 1000}, ISS, "c")
aid = next(iter(old.assets))
old.apply_blob({"op": "asset_transfer", "asset": aid, "to": HOL, "amount": 300}, ISS, "t")
old.apply_blob({"op": "asset_approve", "asset": aid, "spender": SPN, "amount": 50}, HOL, "a")
check("setup: a token issued, moved and approved on the old chain",
      old.abal[aid].get(HOL) == 300 and old.abal[aid].get(ISS) == 700, (r, old.abal))

snap = json.loads(json.dumps({"assets": old.assets, "abal": old.abal, "allow": old.allow}))
json.dump({"generation": P.CHAIN_GENERATION, "contracts": {}, "bridge": {}, **C.exec_assets_doc(snap)}, open(GEN, "w"))
EG._CACHE.clear()
new = ExecState(os.path.join(H, "new.json"))
EG.apply(new)
check("holders keep the same amounts on the new chain", new.abal.get(aid) == {ISS: 700, HOL: 300}, new.abal)
check("the asset record is unchanged", new.assets.get(aid) == old.assets[aid], new.assets.get(aid))
check("the genesis root covers the assets", new.state_root() == EG.genesis_root() and new.state_root() != P.EXEC_GENESIS_ROOT)
new.cursor = 5
new.apply_blob({"op": "asset_transfer", "asset": aid, "to": OUT, "amount": 100}, HOL, "t2")
check("a holder transfers on the new chain", new.abal[aid].get(OUT) == 100 and new.abal[aid].get(HOL) == 200, new.abal[aid])
new.apply_blob({"op": "asset_transfer_from", "asset": aid, "from": HOL, "to": SPN, "amount": 50}, SPN, "tf")
check("an allowance granted on the old chain still spends on the new one", new.abal[aid].get(SPN) == 50, new.abal[aid])

print("ALL PASS — exec assets cross a reroll" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
