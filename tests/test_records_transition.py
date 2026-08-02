"""RECORDS-HALF TRANSITION (execnode/stark/records_transition.py) — the missing half of full-state settlement.

The settled root is rnode(kv_root, rec_root). Settle-with-proof covers only the KV half and pins the SAME
rec_hex into both the pre and post root, so a proven span REQUIRES records to be unchanged — enforced
on-chain by block_records_inert. That means any epoch with a bridge deposit, dividend accrual, asset transfer
or shielded transfer cannot settle by proof at all.

This checks the records half can be proven with the SAME machinery as the KV half, and — the part that
matters — that a full transition is only accepted when BOTH halves are proven and compose to the claimed
settled roots.

Run: python3 tests/test_records_transition.py
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.stark import records_transition as RT, state_transition as SX, storage_tree as ST, field as F
from execnode import exec_root as ER

NQ = 2
# THE PRODUCTION DEPTH, deliberately. Record keys are HASHES over the full slot space, so a toy depth is not
# a smaller version of this tree -- it is a different one, where distinct records collide under the
# `key & ((1<<depth)-1)` mask and the update list stops matching the store. That is not a bug to work around
# in the module (it diffs through the store precisely so it stays correct at any depth); it just makes
# small-depth assertions about "how many records changed" meaningless. Proving is slower here and that is
# the right trade for testing the configuration that actually ships.
DEPTH = ER.DEPTH
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


class FakeState:
    """Duck-typed exec state. records_projection reads bridge/dividend/assets/withdrawals AND commits the
    shielded + field pool ROOTS, so those need real (empty) pools rather than None — an empty pool still has
    a root, and committing it is the point."""

    def __init__(self, bridge=None, dividend=None):
        from execnode.shielded import ShieldedPool
        from execnode.shielded_field import FieldShieldedPool
        self.bridge = dict(bridge or {})
        self.dividend = dict(dividend or {})
        self.abal = {}
        self.assets = {}
        self.allowances = {}
        self.withdrawals = {}
        self.dividend_withdrawals = {}
        self.unshield_withdrawals = {}
        self.shielded = ShieldedPool()
        self.field_pool = FieldShieldedPool()
        self.outbox = {}
        self.inbox = {}


def _states():
    pre = FakeState(bridge={"alice": 100, "bob": 50})
    post = FakeState(bridge={"alice": 70, "bob": 50, "carol": 30})   # alice pays carol
    return pre, post


def t_updates_are_net_and_sorted():
    pre, post = _states()
    ups = RT.records_updates(pre, post, DEPTH)
    keys = [k for k, _v in ups]
    assert keys == sorted(keys), "updates must be sorted — the proof must be a pure function of the states"
    assert len(ups) == 2, f"alice changed and carol appeared; bob did not — expected 2 updates, got {len(ups)}"


def t_unchanged_state_yields_no_updates():
    pre, _ = _states()
    same = FakeState(bridge=dict(pre.bridge))
    assert RT.records_updates(pre, same, DEPTH) == [], "an unchanged half must produce an empty update list"


def t_deletion_is_a_write_of_zero():
    pre = FakeState(bridge={"alice": 100})
    post = FakeState(bridge={})
    ups = RT.records_updates(pre, post, DEPTH)
    assert len(ups) == 1 and ups[0][1] == 0, f"a removed record must be a write of 0, got {ups}"


def t_records_transition_proves_and_verifies():
    pre, post = _states()
    store = RT.records_store(pre, DEPTH)
    pre_root = tuple(store.root())
    tr = RT.prove_records_transition(pre, post, num_queries=NQ, depth=DEPTH)
    post_root = tuple(tr["roots"][-1])
    ok, why = RT.verify_records_transition(tr, pre_root, post_root, num_queries=NQ)
    assert ok, why
    # and the proven post-root is the one an honest node computes from post_st directly
    assert post_root == tuple(RT.records_store(post, DEPTH).root()), \
        "proven records root != the root of the claimed post-state"


def t_full_transition_requires_both_halves():
    """The composition check: both halves must be proven AND compose to the claimed settled roots."""
    pre, post = _states()
    rec_tr = RT.prove_records_transition(pre, post, num_queries=NQ, depth=DEPTH)
    # KV half: an ordinary transition over contract storage
    kv_store = ST.SparseStore(DEPTH, {1: 11})
    kv_pre = tuple(kv_store.root())
    kv_tr = SX.prove_transition(kv_store, [(1, 111)], num_queries=NQ)
    kv_post = tuple(kv_tr["roots"][-1])
    rec_pre, rec_post = tuple(rec_tr["roots"][0]), tuple(rec_tr["roots"][-1])

    pre_full = RT.compose_full_root(kv_pre, rec_pre)
    post_full = RT.compose_full_root(kv_post, rec_post)
    ok, why = RT.verify_full_transition(kv_tr, rec_tr, pre_full, post_full, num_queries=NQ)
    assert ok, why

    # a WRONG claimed post-root must be refused
    wrong = RT.compose_full_root(kv_post, rec_pre)          # records pretended unchanged
    ok2, why2 = RT.verify_full_transition(kv_tr, rec_tr, pre_full, wrong, num_queries=NQ)
    assert not ok2, "a settled root that freezes the records half must be REJECTED"
    assert "post-root" in why2, why2


def t_frozen_records_cannot_masquerade():
    """THE bug the records-inertness allowlist exists to prevent: a span that really moved records, settled
    with records frozen, omits those payouts from the settled root forever."""
    pre, post = _states()
    rec_tr = RT.prove_records_transition(pre, post, num_queries=NQ, depth=DEPTH)
    rec_pre = tuple(rec_tr["roots"][0])
    rec_post = tuple(rec_tr["roots"][-1])
    assert rec_pre != rec_post, "control: the records half really did change"
    kv_store = ST.SparseStore(DEPTH, {1: 11})
    kv_pre = tuple(kv_store.root())
    kv_tr = SX.prove_transition(kv_store, [(1, 111)], num_queries=NQ)
    kv_post = tuple(kv_tr["roots"][-1])
    # the frozen-records composition — what today's KV-only proof would settle
    frozen_post = RT.compose_full_root(kv_post, rec_pre)
    honest_post = RT.compose_full_root(kv_post, rec_post)
    assert frozen_post != honest_post, "freezing records must change the settled root — else nothing is at stake"
    ok, _ = RT.verify_full_transition(kv_tr, rec_tr, RT.compose_full_root(kv_pre, rec_pre),
                                      frozen_post, num_queries=NQ)
    assert not ok, "the frozen-records root must not verify against a records half that moved"


if __name__ == "__main__":
    check("records updates are net and sorted", t_updates_are_net_and_sorted)
    check("unchanged half yields no updates", t_unchanged_state_yields_no_updates)
    check("a removed record is a write of zero", t_deletion_is_a_write_of_zero)
    check("records transition proves and verifies", t_records_transition_proves_and_verifies)
    check("full transition requires BOTH halves and the right composition", t_full_transition_requires_both_halves)
    check("frozen-records root cannot masquerade as a full transition", t_frozen_records_cannot_masquerade)
    print()
    print("ALL PASS — both halves of the settled root are provable" if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
