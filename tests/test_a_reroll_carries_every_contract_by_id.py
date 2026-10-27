"""A reroll carries every contract by its id, and a carry-safe contract with its storage and pot (execnode/exec_genesis.py).

Before: a reroll started the exec layer EMPTY — every contract vanished, its pot was refunded, its game state was lost,
and every frontend pointed at a dead contract until execnode.games.redeploy ran (forgotten more than once; it fails
silently). Now the carry writes genesis_data/exec_genesis.json and every exec node starts from it.

Pins, driving the real carry builder, the real exec layer and the real L1 genesis (throwaway HOME):
  1. without a carried genesis nothing changes: the genesis root is EXEC_GENESIS_ROOT;
  2. the carry keeps EVERY contract under its id WITH its storage and its pot (operator rule 2026-10-20: no reset, no
     refund) — the faucet and a dice table at rest alike; a dice table with an open bet REFUSES the carry instead;
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
# THIS TEST'S OWN GENESIS ONLY: genesis.py seeds genesis_data/genesis_carry.dat when it names the live generation — the
# REAL chain's carried identities and open invites, whose INVITE_ESCROW a test alloc does not hold (the gen-29 rehearsal
# refused every genesis here, 2026-10-25). A path that does not exist = no carry file.
os.environ["NADO_GENESIS_CARRY"] = os.path.join(H, "no_genesis_carry.dat")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
GEN_FILE = os.environ.get("NADO_EXEC_GENESIS") or os.path.join(H, "exec_genesis.json")   # the L1 child inherits it
os.environ["NADO_EXEC_GENESIS"] = GEN_FILE
import protocol as P

import _harness
_report = _harness.Report()
check = _report.check


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
from tools.carry import Refused

# the empty exec state's root in this generation's format: the BLAKE2s one (BLAKE_EXEC_HEIGHT inlined in G9)
GENESIS_ROOT = P.EXEC_GENESIS_ROOT_B2
check("1. without a carried genesis the genesis root is EXEC_GENESIS_ROOT", EG.genesis_root() == GENESIS_ROOT)

OP = FIXED_CIDS["faucet"]
FAUCET_POT, DICE_POT = 9_000_000, 77
dice_code = json.loads(json.dumps(dice.build()))
contracts = {
    "faucet": {"code": json.loads(json.dumps(faucet.build())), "abi": faucet.ABI, "deployer": OP, "runtime": "zkvm",
               "upgradable": True, "storage": {"slots": {"7": str(FAUCET_POT), "8": "0"}}},
    "d" * 32: {"code": dice_code, "abi": {}, "deployer": OP, "runtime": "zkvm", "upgradable": True,
               # a table with an open bet (index count 1, table 5 at dice.TLIST, committed liability tc != 0): in flight
               "storage": {"slots": {"0": "1", str((dice.TLIST << 32) + 0): "5", str((4 << 32) + 5): "100"}}},
}
check("the faucet is carry-safe by its code; a dice table with an open bet is not", carry_policy("faucet", contracts["faucet"]) == "keep"
      and carry_policy("d" * 32, contracts["d" * 32]) == "blocked")
try:
    exec_genesis_doc(contracts, {"faucet": FAUCET_POT, "d" * 32: DICE_POT})
    refused = None
except Refused as e:
    refused = str(e)
check("2. the open bet refuses the whole carry (no reset, no refund), naming it", refused is not None
      and "table 5 has open bets" in refused, refused)
contracts["d" * 32]["storage"]["slots"][str((4 << 32) + 5)] = "0"            # settled on the old chain
gen_contracts, kept = exec_genesis_doc(contracts, {"faucet": FAUCET_POT, "d" * 32: DICE_POT})
check("2. every contract is carried under its id", sorted(gen_contracts) == sorted(contracts), sorted(gen_contracts))
# the fixture writes its slots as strings; the carried genesis holds them as INTS (alphanet6_carryforward.int_slots — a
# string slot is a KVX record in the root, not a slot leaf, and no settle proof could extend that root)
check("...the faucet with its storage, every slot an int", gen_contracts["faucet"]["storage"] == {"slots": {"7": FAUCET_POT, "8": 0}},
      gen_contracts["faucet"]["storage"])
check("...and EVERY pot kept in escrow", kept == {"faucet": FAUCET_POT, "d" * 32: DICE_POT}, kept)
check("...the settled dice table carries its storage too",
      gen_contracts["d" * 32]["storage"]["slots"] == {k: int(v) for k, v in contracts["d" * 32]["storage"]["slots"].items()}
      and gen_contracts["d" * 32]["code"] == dice_code, gen_contracts["d" * 32]["storage"])
json.dump({"generation": P.CHAIN_GENERATION, "contracts": gen_contracts, "bridge": {c: str(v) for c, v in kept.items()}},
          open(GEN_FILE, "w"))
EG._CACHE.clear()

st = ExecState(os.path.join(H, "s.json"))
check("3. a fresh exec layer loads the carried contracts", EG.apply(st) and sorted(st.contracts) == sorted(contracts))
check("...the faucet's pot is on its exec balance", int(st.bridge.get("faucet", 0)) == FAUCET_POT, st.bridge)
check("...its root is genesis_root(), not the empty root",
      st.state_root() == EG.genesis_root() and st.state_root() != GENESIS_ROOT)
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
ok = l1(FAUCET_POT + DICE_POT)
check("5. L1 genesis seeds bridgeescrow:default with exactly the carried pots",
      ok.returncode == 0 and f"ESCROW_COUNTER {FAUCET_POT + DICE_POT}" in ok.stdout, (ok.returncode, ok.stdout[-300:], ok.stderr[-300:]))
bad = l1(FAUCET_POT + DICE_POT - 1)
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
check("6. a genesis file for another generation is ignored", EG.load() is None and EG.genesis_root() == GENESIS_ROOT)

print("ALL PASS — a reroll carries every contract by its id" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
