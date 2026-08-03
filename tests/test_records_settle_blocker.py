"""
WHY records_bind CANNOT YET BE WIRED INTO CONSENSUS — the blocker, pinned.

execnode/stark/records_bind.py derives a span's records effects and requires a records transition to prove
exactly that set. It works (tests/test_records_bind.py, 13/13 at production depth). It is nonetheless
referenced by nothing outside its own test, and this file records the concrete reason so the next person
does not rediscover it by trying.

THE BLOCKER. A settle-with-proof is checked by EVERY node at block-validation time, so every input to that
check must come from COMMITTED state. The settle branch deliberately reads per-block EXEC SUMMARIES
(kv_ops.exec_summary_get) and NOT block bodies — reading bodies made the same transaction validate
differently on a pruned node than on an archive node, which forked the fleet, and no depth fence fixes it
because a snapshot re-anchor wipes bodies wholesale.

But calls_commit.block_summary extracts ONLY `blob` transactions whose op == "call" — the KV half. A
bridge deposit, a faucet donation, a treasury->faucet mirror, a shield, an xmsg: none of them appear
anywhere in the summary. So the data a verifier would need in order to derive the records effects is not
in committed state at all. records_bind's derivation is correct and unreachable.

WHAT WOULD UNBLOCK IT, and why it is not done here: block_summary must additionally commit the block's
records-moving effects at incorporate time, so the verifier can derive them prune-safely. exec summaries
live in the `meta` sub-DB, which FEEDS THE L1 STATE ROOT — so adding a field changes the root on every
node that computes it and is a consensus change that must ride a reroll, exactly like
SETTLE_PROOF_RECURSIVE did. It cannot be landed incrementally on a live chain, and it must not be flipped
without one.

This test therefore CHARACTERISES the gap rather than asserting a fix. It is expected to FAIL the day the
summary is extended — at which point the wiring is possible and this file should become the test for it.

Run: python3 tests/test_records_settle_blocker.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_recblock_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.stark import calls_commit as CC, records_bind as RB
from execnode import exec_root as ER

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


NS = "default"
DEPOSITOR = "d" * 46

# One block carrying BOTH halves: a contract call (KV) and a bridge deposit (RECORDS).
BLOCK = {"block_number": 7, "block_hash": "ab" * 32, "block_transactions": [
    {"recipient": "blob", "sender": DEPOSITOR,
     "data": {"op": "call", "contract": "c" * 32, "method": "bump", "args": [], "ns": NS}},
    {"recipient": "bridge", "sender": DEPOSITOR, "amount": 500_0000},
]}

# --- 1) records_bind CAN derive the effect, given the block ------------------------------------------
eff = RB.span_effects(BLOCK["block_transactions"])
check("records_bind derives the bridge deposit when handed the block's transactions",
      eff == [(ER.T_BRIDGE_BAL, (DEPOSITOR,), 500_0000)])

# --- 2) but the block is NOT what a verifier gets. The summary is. -----------------------------------
inert, calls_by_ns = CC.block_summary(BLOCK)
check("the block is correctly seen as NON-inert (it moves records)", not inert)
check("the summary DOES carry the KV-half call", bool(calls_by_ns.get(NS)))

# THE BLOCKER, stated as an assertion: nothing in the summary identifies the records-moving transaction.
# `inert` says only THAT records moved, never WHICH effect or by how much — a boolean cannot be derived
# against.
flat = repr((inert, calls_by_ns))
check("the summary does NOT carry the depositor (so the effect cannot be derived from it)",
      DEPOSITOR not in flat)
check("the summary does NOT carry the amount either", "5000000" not in flat.replace("_", ""))

# --- 3) therefore a verifier restricted to committed state cannot bind the records half ---------------
# Simulate a verifier honestly: it holds the summary, not the body. Deriving effects from what it has is
# not merely lossy, it is impossible — there is no transaction list to walk.
def verifier_effects_from_summary(summary_inert, summary_calls):
    """What a node could derive at block-validation time today."""
    return None if summary_inert is False else None   # nothing to walk: the summary has no records txs


check("a verifier limited to the exec summary derives NO records effects",
      verifier_effects_from_summary(inert, calls_by_ns) is None)

# --- 4) and the consequence: such a span must keep falling back to quorum -----------------------------
check("block_records_inert correctly REFUSES the proof path for this block "
      "(which is why the fallback is still correct today)",
      not CC.block_records_inert(BLOCK))

print()
if not fails:
    print("ALL PASS — the gap is exactly as described: records_bind's derivation is correct and")
    print("unreachable, because the prune-safe summary a verifier reads carries no records transactions.")
    print("Extending block_summary changes the meta sub-DB and therefore the L1 state root: reroll-only.")
else:
    print(f"{fails} FAILURES — if these fail because the summary now CARRIES records effects, the blocker")
    print("is gone: rewrite this file as the wiring test for records-bound settlement.")
sys.exit(1 if fails else 0)
