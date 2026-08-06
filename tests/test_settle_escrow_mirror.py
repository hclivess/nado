"""The PROVER's call-value escrow must mirror the LIVE chain's, or "provable" stops meaning "what happened".

WHY THIS EXISTS. execnode/state.py skips a call whose sender cannot cover the escrow: it checks
`bridge[sender] >= value`, debits the sender, credits the cid, and if the sender is short the VM NEVER RUNS
and no state moves. settlement_proofs._run_call used to only do the credit — no sender debit, no
affordability check — so the prover was strictly MORE PERMISSIVE than the chain and would happily prove
storage from a call the chain had skipped.

That is not cosmetic. L1 never recomputes the exec root (verifying the proof is what replaces
re-execution), so its only root check is `assert post_full == root` where `root` is the settle
transaction's OWN CLAIM. A proof over the wrong state satisfies that self-consistently, and the settle
would commit a root every honest exec node disagrees with. What masks it today is the records gate
refusing any block with a value>0 call — and that gate is meant to be relaxed
(doc/settle-proof-transport.md §7a), which would open the hole it was incidentally closing.

So this pins the invariant the settlement argument rests on: PROVABLE => WHAT THE CHAIN ACTUALLY DID.

Run: python3 tests/test_settle_escrow_mirror.py
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode import settlement_proofs as SP

fails = 0


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


# A contract whose method stores its call value, so a proven run is observable in storage.
CID = "c" * 32
SENDER = "s" * 40
# zkvm bytecode: [op, dst, src, imm]. Keep it to a single provable store of an immediate.
CODE = {"take": [["PUSH", 0, 0, 1], ["SSTORE", 0, 0, 7], ["RET", 0, 0, 0]]}


def _contracts():
    return {CID: {"code": CODE, "runtime": "zkvm", "storage": {"slots": {}}}}


def _call(value):
    return {"cid": CID, "method": "take", "args": [], "caller": SENDER, "value": value,
            "cursor": 1, "timestamp": 0}


def _run(bridge, value):
    """Drive _run_call directly with a native-value call. Returns None on success, else the error text."""
    try:
        SP._run_call(_contracts(), dict(bridge), {}, {}, {}, _call(value), 0, 1, 0, {}, {},
                     want_rows=False)
        return None
    except Exception as e:
        return f"{type(e).__name__}: {e}"


# ---- the invariant -----------------------------------------------------------------------------------
def t_unaffordable_call_is_refused():
    """The whole point: sender short => the chain SKIPPED it => the span must be unprovable."""
    why = _run({SENDER: 5}, 100)
    assert why is not None, "an unaffordable call must NOT be provable — the chain never ran it"
    assert "cover" in why or "unprovable" in why, f"refused, but for the wrong reason: {why}"


def t_exactly_affordable_is_allowed():
    """Boundary: sender holds exactly the value. The live rule is `< value` => skip, so == must pass."""
    why = _run({SENDER: 100}, 100)
    assert why is None or "cover" not in why, f"an exactly-affordable call must not be refused: {why}"


def t_zero_value_needs_no_balance():
    """A value=0 call escrows nothing, so a broke sender is irrelevant to it."""
    why = _run({}, 0)
    assert why is None or "cover" not in why, f"a zero-value call must not be gated on balance: {why}"


def t_sender_is_debited_and_cid_credited():
    """Mirror state.py: the escrow MOVES units, it does not mint them."""
    bridge = {SENDER: 100}
    try:
        SP._run_call(_contracts(), bridge, {}, {}, {}, _call(30), 0, 1, 0, {}, {}, want_rows=False)
    except Exception:
        pass                                    # the VM half may still fail; the escrow half is what we assert
    assert bridge.get(SENDER, 0) == 70, f"sender must be debited 30, got {bridge.get(SENDER, 0)}"
    assert bridge.get(CID, 0) == 30, f"cid must be credited 30, got {bridge.get(CID, 0)}"


def t_zero_balance_row_is_pruned():
    """state.py deletes a zeroed row (`if self.bridge[sender] == 0: del ...`). An explicit 0 is NOT the
    same as absence in a shadow that gets hashed downstream, so the prover must prune identically."""
    bridge = {SENDER: 40}
    try:
        SP._run_call(_contracts(), bridge, {}, {}, {}, _call(40), 0, 1, 0, {}, {}, want_rows=False)
    except Exception:
        pass
    assert SENDER not in bridge, "a fully-spent sender row must be ABSENT, not a stored zero"


# ---- the source-level guarantee ----------------------------------------------------------------------
def t_prover_mirrors_the_live_rule():
    """Both halves of the escrow must be present in the prover, not just the credit."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "execnode", "settlement_proofs.py")).read()
    assert "bridge[caller] = bridge.get(caller, 0) - value" in src, "native sender debit missing"
    assert "bridge[cid] = bridge.get(cid, 0) + value" in src, "native cid credit missing"
    assert "asset_credit_dict(abal, in_asset, caller, -value)" in src, "asset sender debit missing"


def t_asset_rows_read_with_string_keys():
    """asset_credit_dict stores rows under str(aid); reading with an int key silently returns {} and would
    reject every asset-denominated call. This bit me once already."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "execnode", "settlement_proofs.py")).read()
    assert "abal.get(str(in_asset))" in src, "asset affordability must read the str(aid)-keyed row"


for nm, fn in [("an UNAFFORDABLE call is refused (chain skipped it)", t_unaffordable_call_is_refused),
               ("an exactly-affordable call is allowed", t_exactly_affordable_is_allowed),
               ("a zero-value call is not gated on balance", t_zero_value_needs_no_balance),
               ("the sender is debited and the cid credited", t_sender_is_debited_and_cid_credited),
               ("a fully-spent sender row is pruned, not stored as 0", t_zero_balance_row_is_pruned),
               ("the prover mirrors the live rule, both halves", t_prover_mirrors_the_live_rule),
               ("asset rows are read with str(aid) keys", t_asset_rows_read_with_string_keys)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
