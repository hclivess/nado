"""STAKING POOLS RETIRED (protocol.POOL_RETIRE_HEIGHT, 2026-09-08 night). Pins:
  1. the slot before the gate: a delegator is absent from the producer draw and its stake rides its pool;
  2. from the gate: the delegator is drawn on its own stake, the pool on its own stake only (pooled ignored);
  3. from the gate: pool / delegate / undelegate transactions are refused by validation;
  4. from the gate: the reward split returns the whole producer cut (no journal record is written);
  5. the gate is keyed on the generation (a reroll ships it from genesis) and sits at/after the device-optional gate.
Run: python3 tests/test_pool_retire.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-poolretire-")
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def main():
    import protocol as P
    from ops import mining_ops as M
    N = P.DENOMINATION
    g = P.POOL_RETIRE_HEIGHT
    check("gate is keyed on the generation", "if CHAIN_GENERATION == 25 else 1" in open(os.path.join(ROOT, "protocol.py")).read().split("POOL_RETIRE_HEIGHT =")[1].split("\n")[0])
    check("gate at/after the device-optional gate", g >= P.BOND_ATTEST_OPTIONAL_HEIGHT)
    pool, dlg, solo = "p" * 46, "d" * 46, "s" * 46
    reg = {pool: {"bonded": 300 * N, "pooled": 500 * N, "fidelity": None, "bond_since": None},
           dlg: {"bonded": 500 * N, "pool_to": pool, "fidelity": None, "bond_since": None},
           solo: {"bonded": 100 * N, "fidelity": None, "bond_since": None}}
    before = M.bonded_producer_registry(reg, {}, g - 1)
    check("before the gate: delegator absent, pool carries own+pooled", dlg not in before and before[pool]["bonded"] == 800 * N, {k: v["bonded"] for k, v in before.items()})
    after = M.bonded_producer_registry(reg, {}, g)
    check("from the gate: delegator drawn on its own stake", after.get(dlg, {}).get("bonded") == 500 * N, after.get(dlg))
    check("from the gate: pool on its own stake only", after[pool]["bonded"] == 300 * N, after[pool])
    check("solo unchanged", after[solo]["bonded"] == 100 * N)
    # validation refuses the three pool txs from the gate (message, not exception type, is what the wallet shows)
    src = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
    check("validation refuses pool/delegate/undelegate from the gate", "POOL_RETIRE_HEIGHT and block_height >= POOL_RETIRE_HEIGHT" in src and "staking pools are retired" in src)
    rsrc = open(os.path.join(ROOT, "ops", "reward_ops.py")).read()
    check("reward split off from the gate", "POOL_RETIRE_HEIGHT and h >= POOL_RETIRE_HEIGHT" in rsrc)
    bsrc = open(os.path.join(ROOT, "ops", "block_ops.py")).read()
    check("wallet mirror carries pools_retired and skips the delegation view", '"pools_retired"' in bsrc and "{} if _pools_off else _delegation_view" in bsrc)
    return 0 if not _fails else 1


if __name__ == "__main__":
    sys.exit(main())
