"""EVERY GEN-25 CONSENSUS GATE TRANSFERS AT A REROLL (protocol.py "GATE LEDGER", 2026-09-09).

A gate written as a bare height (`POOL_HEIGHT = 6000`) silently survives a reroll: the fresh chain would leave the
rule off for its first 6,000 blocks. Every gate is therefore `<live height> if CHAIN_GENERATION == 25 else <x>`, and
this test pins BOTH halves:
  1. the gen-25 value still equals what the running chain uses (a reroll edit must never change live consensus);
  2. the reroll value is the one the ledger documents — 1 = live from block 1 / epoch 0, 0 = never (dead code to
     delete in the cleanup pass);
  3. no gate constant is left unkeyed (a new one added without a reroll branch fails here).
Run: python3 tests/test_gate_reroll_transfer.py
"""
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-gates-")
_fails = []

# gate -> value on a fresh chain. 1 = live from genesis, 0 = never (its code path is cleanup fodder).
REROLL = {
    "DEVICE_ATTEST_HEIGHT": 1, "DEVICE_BIND_HEIGHT": 1, "DEVICE_BIND_STRICT_HEIGHT": 1,
    "DEVICE_BIND_PERMANENT_HEIGHT": 1, "DEVICE_REBIND_INSTANT_HEIGHT": 1,
    "DEVICE_ATTEST_TPM_ANY_AAGUID_HEIGHT": 1, "DEVICE_ATTEST_EK_HEIGHT": 1,
    "DEVICE_ATTEST_EK_SHORT_HEIGHT": 1, "DEVICE_ATTEST_EK_ROOTS_V2_HEIGHT": 1,
    "DEVICE_ATTEST_EK_PROVEN_HEIGHT": 1, "DEVICE_ATTEST_EK_READY_HEIGHT": 1,
    "DEVICE_BIND_DEVKEY_ALL_EPOCH": 0,
    "BOND_ATTEST_OPTIONAL_HEIGHT": 1, "POOL_RETIRE_HEIGHT": 1, "BOND_CURVE_RETIRE_HEIGHT": 1,
    "OPEN_LANE_EXCLUDE_RETIRE_HEIGHT": 1,
    "BOND_DEVICE_CAP_HEIGHT": 0, "BOND_WEIGHT_CURVE_HEIGHT": 0, "POOL_HEIGHT": 0,
    "OPEN_LANE_EXCLUDE_BONDED_HEIGHT": 0,
    "DIVIDEND_ATTESTED_EPOCH": 0, "DIVIDEND_WEIGHT_CAP_V2_EPOCH": 0, "DIV_CARRY_METER_EPOCH": 0,
}


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def main():
    import protocol as P
    src = open(os.path.join(ROOT, "protocol.py")).read()
    check("this test tracks the live generation", P.CHAIN_GENERATION == 25, P.CHAIN_GENERATION)

    for name, want in sorted(REROLL.items()):
        m = re.search(r"^" + name + r" = ([^#\n]+)", src, re.M)
        if not m:
            check(f"{name}: found in protocol.py", False)
            continue
        expr = m.group(1).strip()
        live = eval(expr, {"CHAIN_GENERATION": 25})          # noqa: S307 - our own constant expression
        nxt = eval(expr, {"CHAIN_GENERATION": 26})
        check(f"{name}: live value unchanged", live == getattr(P, name), f"{live} != {getattr(P, name)}")
        check(f"{name}: reroll value {want}", nxt == want, f"got {nxt}")
        if live not in (0, 1):                                # a real gen-25 height MUST carry the branch
            check(f"{name}: keyed on CHAIN_GENERATION", "CHAIN_GENERATION == 25" in expr, expr)

    # 3. nothing new slipped in unkeyed: every *_HEIGHT / *_EPOCH gate is either in the ledger or a plain parameter
    declared = set(re.findall(r"^([A-Z][A-Z0-9_]*(?:HEIGHT|EPOCH)) = ", src, re.M))
    unkeyed = {n for n in declared - set(REROLL)
               if isinstance(getattr(P, n, None), int) and getattr(P, n) > 1}
    not_gates = {"GENESIS_TIMESTAMP",          # a timestamp, not a switch
                 "GC_MAX_PER_EPOCH",           # a per-boundary work bound
                 "OPEN_LANE_EXCLUDE_BONDED_EPOCH"}   # DERIVED from a keyed gate — checked below instead
    check("no gate constant is missing from the ledger", not (unkeyed - not_gates), sorted(unkeyed - not_gates))

    # a derived gate must follow its parent into the next generation (0 // 60 = 0), never freeze at its gen-25 value
    hexpr = re.search(r"^OPEN_LANE_EXCLUDE_BONDED_HEIGHT = ([^#\n]+)", src, re.M).group(1).strip()
    check("OPEN_LANE_EXCLUDE_BONDED_EPOCH follows its height at a reroll",
          eval(hexpr, {"CHAIN_GENERATION": 26}) // P.EPOCH_LENGTH == 0
          and P.OPEN_LANE_EXCLUDE_BONDED_EPOCH == P.OPEN_LANE_EXCLUDE_BONDED_HEIGHT // P.EPOCH_LENGTH)

    # 4. the ledger comment exists and names the cleanup
    check("protocol.py carries the GATE LEDGER", "GATE LEDGER" in src and "CLEANUP AT THE REROLL" in src)
    return 0 if not _fails else 1


if __name__ == "__main__":
    sys.exit(main())
