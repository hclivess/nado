"""EVERY CONSENSUS GATE TRANSFERS AT A REROLL (protocol.py "GATE LEDGER", 2026-09-09).

A gate written as a bare height (`POOL_HEIGHT = 6000`) silently survives a reroll: the fresh chain would leave the
rule off for its first 6,000 blocks. Every gate is therefore `<live height> if CHAIN_GENERATION == <gen> else <x>`,
and this test pins BOTH halves:
  1. the live value still equals what the running chain uses (a reroll edit must never change live consensus);
  2. the reroll value is the one the ledger documents — 1 = live from block 1 / epoch 0, 0 = never (dead code to
     delete in the cleanup pass);
  3. no gate constant is left unkeyed (a new one added without a reroll branch fails here);
  4. the gates already cleaned up after a reroll stay DELETED — every gen-25 gate, since the betanet-8 cleanup.
Run: python3 tests/test_gate_reroll_transfer.py
"""
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-gates-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)   # leave no /tmp home behind (9,600 leaked by 2026-09-22)
_fails = []

# gate -> value on a fresh chain. 1 = live from genesis, 0 = never (its code path is cleanup fodder).
REROLL = {
    # DEVICE_ATTEST_HEIGHT is a plain 1 (not generation-keyed); EK_ENROL_ROOTS_AT_HEIGHT is the gen-27 gate (1400).
    "DEVICE_ATTEST_HEIGHT": 1, "EK_ENROL_ROOTS_AT_HEIGHT": 1,
    # (every gen-25 gate is gone: slice 1 deleted the "never" gates with their code, slice 2 inlined the "from block 1"
    #  and "from epoch 0" gates as unconditional rules — see DELETED below)
}
# Gates cleaned up after the betanet-8 reroll (doc/reroll.md §"What the cleanup deletes"). They must stay gone: a
# re-added constant with the old name would read as a live switch for code that no longer branches on it.
DELETED = (
    # slice 1: reroll value 0 (never) and their retire twins — deleted with their code paths
    "BOND_DEVICE_CAP_HEIGHT", "BOND_WEIGHT_CURVE_HEIGHT", "POOL_HEIGHT", "OPEN_LANE_EXCLUDE_BONDED_HEIGHT",
    "OPEN_LANE_EXCLUDE_BONDED_EPOCH", "BOND_ATTEST_OPTIONAL_HEIGHT", "POOL_RETIRE_HEIGHT",
    "BOND_CURVE_RETIRE_HEIGHT", "OPEN_LANE_EXCLUDE_RETIRE_HEIGHT",
    # slice 2: reroll value 1 (from block 1) — the rule is unconditional (a `>= 1` survives only where height 0 reaches)
    "DEVICE_BIND_HEIGHT", "DEVICE_BIND_STRICT_HEIGHT", "DEVICE_BIND_PERMANENT_HEIGHT", "DEVICE_REBIND_INSTANT_HEIGHT",
    "DEVICE_BIND_PERMANENT_EK_HEIGHT", "DEVICE_ATTEST_TPM_ANY_AAGUID_HEIGHT", "DEVICE_ATTEST_TREZOR_SERIAL_OPTIONAL_HEIGHT",
    "DEVICE_ATTEST_EK_HEIGHT", "DEVICE_ATTEST_EK_SHORT_HEIGHT", "DEVICE_ATTEST_EK_ROOTS_V2_HEIGHT",
    "DEVICE_ATTEST_EK_PROVEN_HEIGHT", "DEVICE_ATTEST_EK_READY_HEIGHT", "TX_AT_MOST_ONCE_STRICT_HEIGHT",
    "PROOF_BIND_HEIGHT", "EXEC_RULES_V2_HEIGHT", "PROOF_BLOCK_SELECTOR_HEIGHT", "REVIEW_R2_HEIGHT",
    "PROOF_TRACE_LDT_HEIGHT", "PROOF_FIXED_CID_HEIGHT", "PRIVACY_PAUSE_HEIGHT", "PROOF_QUERY_FULL_HEIGHT",
    "ADDRESS_KEY_BIND_HEIGHT", "SETTLE_ANCHOR_HEIGHT", "SLASH_DEDUP_HEIGHT", "EXEC_CTX_CURRENT_HEIGHT",
    "EXEC_ROOT_V2_HEIGHT", "SHIELD_WIDE_HEIGHT",
    # slice 2: reroll value 0 on an epoch comparison (from epoch 0 = always)
    "LEASE_V2_EPOCH", "DIVIDEND_ATTESTED_EPOCH", "DIVIDEND_WEIGHT_CAP_V2_EPOCH", "DIV_CARRY_METER_EPOCH",
    "lease_v2_at",
)


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def main():
    import protocol as P
    src = open(os.path.join(ROOT, "protocol.py")).read()
    check("this test tracks the live generation (gen 27 since the betanet-8 reroll)", P.CHAIN_GENERATION == 27, P.CHAIN_GENERATION)

    for name, want in sorted(REROLL.items()):
        m = re.search(r"^" + name + r" = ([^#\n]+)", src, re.M)
        if not m:
            check(f"{name}: found in protocol.py", False)
            continue
        expr = m.group(1).strip()
        # evaluated at the LIVE generation and the next one: a gen-25 gate already runs its reroll value on gen 27
        # (its gen-25 branch is history), a gate added on gen 27 runs its live height now and `want` at the next reroll
        live = eval(expr, {"CHAIN_GENERATION": P.CHAIN_GENERATION})   # noqa: S307 - our own constant expression
        nxt = eval(expr, {"CHAIN_GENERATION": P.CHAIN_GENERATION + 1})
        check(f"{name}: live value unchanged", live == getattr(P, name), f"{live} != {getattr(P, name)}")
        check(f"{name}: reroll value {want}", nxt == want, f"got {nxt}")
        if live not in (0, 1):                                # a real live height MUST carry the branch
            check(f"{name}: keyed on CHAIN_GENERATION", f"CHAIN_GENERATION == {P.CHAIN_GENERATION}" in expr, expr)

    # 3. nothing new slipped in unkeyed: every *_HEIGHT / *_EPOCH gate is either in the ledger or a plain parameter
    declared = set(re.findall(r"^([A-Z][A-Z0-9_]*(?:HEIGHT|EPOCH)) = ", src, re.M))
    unkeyed = {n for n in declared - set(REROLL)
               if isinstance(getattr(P, n, None), int) and getattr(P, n) > 1}
    not_gates = {"GENESIS_TIMESTAMP",          # a timestamp, not a switch
                 "GC_MAX_PER_EPOCH"}           # a per-boundary work bound
    check("no gate constant is missing from the ledger", not (unkeyed - not_gates), sorted(unkeyed - not_gates))
    check("the cleaned-up gates stay deleted", not any(hasattr(P, n) or re.search(r"^" + n + r" = ", src, re.M) for n in DELETED),
          [n for n in DELETED if hasattr(P, n) or re.search(r"^" + n + r" = ", src, re.M)])
    check("no gen-25 branch is left in protocol.py", "CHAIN_GENERATION == 25" not in src)

    # 3a. the EXEC_ROOT_V2 layout stamps the prover's call context with the block being applied, which only holds
    #     once the F3 context (the cursor advanced BEFORE the block's blobs run) is in force — so the layout switch
    #     can never precede the context switch. Both gates are inlined as `>= 1` (genesis, h = 0, below both):
    #     pin that the two sites still switch at the same height. Read as SOURCE — importing execnode.execnode would
    #     open the exec state relative to the working directory (CLAUDE.md rule 4).
    esb = open(os.path.join(ROOT, "execnode", "stark", "exec_state_bind.py")).read()
    exn = open(os.path.join(ROOT, "execnode", "execnode.py")).read()
    rv = re.search(r"def root_v2\(height\):.*?return int\(height\) >= (\d+)", esb, re.S)
    cv = re.search(r"_st\._applying = h.*?if int\(h\) >= (\d+):\n\s+# F3", exn, re.S)
    check("the exec root v2 layout switches at height 1", bool(rv) and rv.group(1) == "1", rv and rv.group(1))
    check("the F3 call context switches at height 1", bool(cv) and cv.group(1) == "1", cv and cv.group(1))
    check("the root layout never precedes the call context", bool(rv and cv) and int(rv.group(1)) >= int(cv.group(1)))

    # 3b. the chain clock cadence is re-anchored at every reroll (C3, 2026-09-23): gen 25 ran 60 ds; the reroll set
    #     the measured 6.41 s, and the gen-25 branch was collapsed after the betanet-8 reroll
    check("CHAIN_CLOCK_CADENCE_DS: the measured 6.41 s (64 ds)", P.CHAIN_CLOCK_CADENCE_DS == 64)
    check("chain_clock runs at 6.4 s", all(P.chain_clock(h) == P.GENESIS_TIMESTAMP + h * 64 // 10 for h in (0, 1, 7, 209400, 2**40)))

    # 4. the ledger comment exists and names the cleanup
    check("protocol.py carries the GATE LEDGER", "GATE LEDGER" in src and "THE SAVINGS LANE IS PLAIN STAKE" in src)
    return 0 if not _fails else 1


if __name__ == "__main__":
    sys.exit(main())
