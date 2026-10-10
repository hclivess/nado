"""A reroll carries every contract by its id, and a carry-safe contract with its storage and pot (execnode/exec_genesis.py).

Before: a reroll started the exec layer EMPTY — every contract vanished, its pot was refunded, its game state was lost,
and every frontend pointed at a dead contract until execnode.games.redeploy ran (forgotten more than once; it fails
silently). Now the carry writes genesis_data/exec_genesis.json and every exec node starts from it.

Pins, driving the real carry builder, the real exec layer and the real L1 genesis (throwaway HOME):
  1. without a carried genesis nothing changes: the genesis root is EXEC_GENESIS_ROOT;
  2. the carry keeps EVERY contract under its id; a CARRY_STORAGE contract (the faucet) keeps storage and pot, any
     other contract starts from fresh-deploy storage (its constructor's output) and its pot is refunded by the carry;
  3. a fresh exec layer loads the carried contracts, its root equals genesis_root(), and loading twice is a no-op;
  4. the carried pot is SPENDABLE on the new chain: the faucet operator defunds from it;
  5. L1 genesis seeds the default namespace's escrow counter with exactly the carried pots, and refuses to build when
     BRIDGE_ESCROW does not hold them;
  6. redeploy only verifies references when contracts were carried (a deploy would orphan them);
  7. a genesis file for another generation is ignored.

Run: python3 tests/test_a_reroll_carries_every_contract_by_id.py
"""
import os, sys, json, tempfile, subprocess
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-exec-genesis-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
H = os.environ["HOME"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
GEN_FILE = os.environ.get("NADO_EXEC_GENESIS") or os.path.join(H, "exec_genesis.json")   # the L1 child inherits it
os.environ["NADO_EXEC_GENESIS"] = GEN_FILE
import protocol as P

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


PHASE = os.environ.get("NADO_TEST_PHASE", "main")
if PHASE == "l1":
    # 5) L1 genesis, in a child process with its own HOME (make_genesis writes the L1 database)
    import logging
    held = int(os.environ["NADO_TEST_ESCROW"])
    os.makedirs(os.path.join(H, "nado", "private"), exist_ok=True)
    json.dump([{"address": P.BRIDGE_ESCROW, "balance": held, "bonded": 0}],
              open(os.path.join(H, "nado", "private", "genesis_alloc.dat"), "w"))
    json.dump([], open(os.path.join(H, "nado", "private", "genesis_open.dat"), "w"))
    from genesis import make_folders, make_genesis
    from ops import kv_ops
    make_folders()
    try:
        make_genesis(address=P.GENESIS_ADDRESS, balance=P.TREASURY_GENESIS, ip="127.0.0.1", port=9173,
                     timestamp=P.GENESIS_TIMESTAMP, logger=logging.getLogger("t"))
    except SystemExit as e:
        print("REFUSED", e)
        sys.exit(3)
    print("ESCROW_COUNTER", kv_ops.bridge_escrow_ns("default"))
    sys.exit(0)

from execnode import exec_genesis as EG
from execnode.state import ExecState
from execnode.code_codec import FIXED_CIDS
from execnode.games import faucet, dice
from tools.alphanet6_carryforward import exec_genesis_doc, carry_policy

check("1. without a carried genesis the genesis root is EXEC_GENESIS_ROOT", EG.genesis_root() == P.EXEC_GENESIS_ROOT)

OP = FIXED_CIDS["faucet"]
FAUCET_POT, DICE_POT = 9_000_000, 77
dice_code = json.loads(json.dumps(dice.build()))
contracts = {
    "faucet": {"code": json.loads(json.dumps(faucet.build())), "abi": faucet.ABI, "deployer": OP, "runtime": "zkvm",
               "upgradable": True, "storage": {"slots": {"7": str(FAUCET_POT), "8": "0"}}},
    "d" * 32: {"code": dice_code, "abi": {}, "deployer": OP, "runtime": "zkvm", "upgradable": True,
               "storage": {"slots": {"11": "123", "17": "9"}}},             # a seat in flight: must NOT carry
}
check("the faucet is carry-safe by its code; dice is not", carry_policy("faucet", contracts["faucet"]) == "keep"
      and carry_policy("d" * 32, contracts["d" * 32]) == "reset")
gen_contracts, kept = exec_genesis_doc(contracts, {"faucet": FAUCET_POT, "d" * 32: DICE_POT})
check("2. every contract is carried under its id", sorted(gen_contracts) == sorted(contracts), sorted(gen_contracts))
check("...the faucet with its storage", gen_contracts["faucet"]["storage"] == contracts["faucet"]["storage"])
check("...and its pot kept in escrow; the reset contract's pot is left to the refund", kept == {"faucet": FAUCET_POT}, kept)
check("...the reset contract starts from fresh-deploy storage, its in-flight seat gone",
      gen_contracts["d" * 32]["storage"] != contracts["d" * 32]["storage"] and gen_contracts["d" * 32]["code"] == dice_code,
      gen_contracts["d" * 32]["storage"])
json.dump({"generation": P.CHAIN_GENERATION, "contracts": gen_contracts, "bridge": {c: str(v) for c, v in kept.items()}},
          open(GEN_FILE, "w"))
EG._CACHE.clear()

st = ExecState(os.path.join(H, "s.json"))
check("3. a fresh exec layer loads the carried contracts", EG.apply(st) and sorted(st.contracts) == sorted(contracts))
check("...the faucet's pot is on its exec balance", int(st.bridge.get("faucet", 0)) == FAUCET_POT, st.bridge)
check("...its root is genesis_root(), not the empty root",
      st.state_root() == EG.genesis_root() and st.state_root() != P.EXEC_GENESIS_ROOT)
check("...and loading again is a no-op", EG.apply(st) is False)

# 4) the carried pot pays: the operator defunds part of its own donation on the new chain
st.cursor = 5
r = st.apply_blob({"op": "call", "contract": "faucet", "method": "defund", "args": [1000], "value": 0}, OP, "t1")
check("4. the carried pot is spendable: the operator defunds from it",
      int(st.bridge.get("faucet", 0)) == FAUCET_POT - 1000, (r, st.bridge.get("faucet")))

# 5) L1 genesis seeds the escrow counter from the carried pots, and refuses a mismatch
def l1(escrow):
    env = dict(os.environ, NADO_TEST_PHASE="l1", NADO_TEST_ESCROW=str(escrow), HOME=tempfile.mkdtemp(dir=H))
    env["NADO_EXEC_STATE"] = os.path.join(env["HOME"], "exec_state.json")
    env["NADO_EXEC_DA"] = os.path.join(env["HOME"], "exec_da")
    return subprocess.run([sys.executable, os.path.abspath(__file__)], env=env, capture_output=True, text=True, timeout=600)
ok = l1(FAUCET_POT)
check("5. L1 genesis seeds bridgeescrow:default with exactly the carried pots",
      ok.returncode == 0 and f"ESCROW_COUNTER {FAUCET_POT}" in ok.stdout, (ok.returncode, ok.stdout[-300:], ok.stderr[-300:]))
bad = l1(FAUCET_POT - 1)
check("...and refuses to build genesis when BRIDGE_ESCROW does not hold them", bad.returncode == 3 and "REFUSED" in bad.stdout,
      (bad.returncode, bad.stdout[-300:]))

# redeploy never deploys over carried contracts (it would rewire the frontends away from them): a dead exec URL proves
# it stops at verification instead of reaching the deploy path
rd = subprocess.run([sys.executable, "-m", "execnode.games.redeploy", "--l1", "http://127.0.0.1:9", "--ex", "http://127.0.0.1:9"],
                    cwd=ROOT, env=dict(os.environ), capture_output=True, text=True, timeout=300)
check("redeploy with a carried genesis only verifies references and deploys nothing",
      "were CARRIED" in rd.stdout and "== deploy ==" not in rd.stdout, (rd.returncode, rd.stdout[-300:], rd.stderr[-300:]))

# 6) a file for another generation is ignored
json.dump({"generation": P.CHAIN_GENERATION + 1, "contracts": gen_contracts, "bridge": {}}, open(GEN_FILE, "w"))
EG._CACHE.clear()
check("6. a genesis file for another generation is ignored", EG.load() is None and EG.genesis_root() == P.EXEC_GENESIS_ROOT)

print("ALL PASS — a reroll carries every contract by its id" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
