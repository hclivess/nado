"""A reroll's genesis carries every account's coins AND identity, and leases only the identities that were live
(genesis.py make_genesis with genesis_alloc.dat + genesis_carry.dat; tools/alphanet6_carryforward.py writes them).

Carried since the betanet-8 reroll (2026-09-25): balances, bonded stake, the identity fields (CARRY_FIELDS), device
bindings, aliases and account-auth history. The first betanet-8 genesis leased EVERY registered identity — 79 open-lane
collectors against 46 live, the lapsed ones drawn for slots they never fill — and was replaced before block 1; the
carry now names the PRESENT set and genesis leases exactly it. Pins: coins and supply, the identity fields, device
bindings / aliases / auth history, leases only for the present set (a registered-but-lapsed identity keeps its
registration and device but is not in the open registry), and a carry file naming another generation is ignored.

Run: python3 tests/test_genesis_carries_identities.py
"""
import os, tempfile, json
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-carry-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import sys, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
H = os.environ["HOME"]
os.makedirs(os.path.join(H, "nado", "private"), exist_ok=True)
import protocol as P

LIVE, LAPSED, PLAIN = "a" * 46, "b" * 46, "c" * 46
alloc = [
    {"address": LIVE, "balance": 500, "bonded": 0, "registered": 1, "fidelity": 12, "devkey": "tpm:" + "1" * 64,
     "public_key": "pk-live"},
    {"address": LAPSED, "balance": 0, "bonded": 700, "registered": 1, "fidelity": 3, "devkey": "tpm:" + "2" * 64},
    {"address": PLAIN, "balance": 42, "bonded": 0},
]
MISMATCH = os.environ.get("NADO_TEST_CARRY_MISMATCH") == "1"      # the child run: a carry file for ANOTHER generation
carry = {"generation": int(P.CHAIN_GENERATION) + (1 if MISMATCH else 0), "present": [LIVE],
         "devbind": [["tpm:" + "1" * 64, LIVE, "perm"], ["tpm:" + "2" * 64, LAPSED, "perm"]],
         "aliases": [["zag", LIVE]], "auth_history": [[LIVE, 1, ["k1", "k2"]]]}
json.dump(alloc, open(os.path.join(H, "nado", "private", "genesis_alloc.dat"), "w"))
json.dump([], open(os.path.join(H, "nado", "private", "genesis_open.dat"), "w"))
cpath = os.path.join(H, "carry.json")
json.dump(carry, open(cpath, "w"))
os.environ["NADO_GENESIS_CARRY"] = cpath

from genesis import make_folders, make_genesis
from ops import kv_ops
from ops.account_ops import get_open_registry, get_account

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


make_folders()
make_genesis(address=P.GENESIS_ADDRESS, balance=P.TREASURY_GENESIS, ip="127.0.0.1", port=9173,
             timestamp=P.GENESIS_TIMESTAMP, logger=logging.getLogger("t"))
acc = lambda a: get_account(a, create_on_error=False) or {}
if MISMATCH:
    check("a carry file naming another generation is ignored: no device bindings", kv_ops.devbind_get("tpm:" + "1" * 64) is None)
    check("... no aliases", kv_ops.alias_get("zag") is None)
    check("... while the allocation's coins still carry", acc(LIVE).get("balance") == 500)
    print("ALL PASS" if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
check("balances and bonded stake are carried", (acc(LIVE).get("balance"), acc(LAPSED).get("bonded"), acc(PLAIN).get("balance")) == (500, 700, 42))
check("identity fields are carried", acc(LIVE).get("fidelity") == 12 and acc(LIVE).get("devkey") == "tpm:" + "1" * 64
      and acc(LIVE).get("public_key") == "pk-live" and str(acc(LAPSED).get("registered")) == "1")
check("device bindings are carried", kv_ops.devbind_get("tpm:" + "1" * 64) is not None and kv_ops.devbind_get("tpm:" + "2" * 64) is not None)
check("aliases are carried", kv_ops.alias_get("zag") == LIVE, kv_ops.alias_get("zag"))
check("account-auth history is carried", bool(kv_ops.auth_history(LIVE)))
reg = get_open_registry(0)
check("the live identity holds a lease at genesis", LIVE in reg, sorted(reg))
check("a lapsed identity keeps its registration but holds no lease (it rejoins by renewing)", LAPSED not in reg, sorted(reg))
check("an account that never registered holds none", PLAIN not in reg)
import subprocess
child = subprocess.run([sys.executable, os.path.abspath(__file__)], capture_output=True, text=True, timeout=600,
                       env={**os.environ, "NADO_TEST_CARRY_MISMATCH": "1", "HOME": tempfile.mkdtemp(prefix="nado-test-carry2-")})
for line in child.stdout.splitlines():
    if line.startswith(("PASS", "FAIL")):
        print(line)
check("(the other-generation run completed)", child.returncode == 0, child.stdout[-400:] + child.stderr[-400:])
print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
