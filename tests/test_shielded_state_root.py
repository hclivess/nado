"""
Shielded-contract state binding (execnode/exec_root.py tags 11/12) — the compatibility invariant.

THE RISK THIS FILE EXISTS FOR. The settled state root must be a pure function of the applied blocks, and
every node must compute the same one. A new record that appears unconditionally would move every node's
root the moment the code shipped, and a fleet that upgrades over minutes rather than atomically splits —
which is not hypothetical here: a `sort_keys` change to the codec once altered the genesis root and wedged
the fleet, and a prune watermark leaking into the root split it at h10047.

So the rule for this feature is: a chain with no private state must project BYTE-IDENTICALLY to one that
has never heard of it. Empty is absent. That makes it an ordinary update — no activation height, no reroll
— and it is what the first three checks pin down.

Run:  python3 tests/test_shielded_state_root.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode import exec_root as ER
from execnode import shielded_state as S

FAILS = []


def check(name, fn):
    try:
        fn()
        print("PASS  " + name)
    except AssertionError as e:
        print("FAIL  " + name + " — " + str(e))
        FAILS.append(name)
    except Exception as e:
        print(f"FAIL  {name} — {type(e).__name__}: {e}")
        FAILS.append(name)


CID = "d0be764f3da9c9cc6bb609280a887929"
OTHER_CID = "230860957a7c1db403434ffb4a3969b3"
NSK = 0xC0FFEE1234


class _Pool:
    """The two existing pools, reduced to what records_projection reads from them."""
    def __init__(self):
        self.nullifiers = set()

    def root(self):
        return 0

    def nullifier_digest(self):
        return "0" * 64


class _State:
    """A duck-typed ExecState carrying a little of every OTHER record family, so a regression that
    disturbed tags 1-10 would show up here rather than only in the app records."""
    def __init__(self, app_state=None):
        self.bridge = {"addr1": 1234}
        self.dividend = {"addr2": 99}
        self.withdrawals = {"7": {"addr": "addr1", "amount": 5}}
        self.dividend_withdrawals = {}
        self.unshield_withdrawals = {}
        self.shielded = _Pool()
        self.field_pool = _Pool()
        self.outbox = {}
        self.inbox = []
        if app_state is not None:
            self.app_state = app_state


def _populated():
    p = S.ShieldedStatePool()
    cm = S.note_commitment(CID, S.KIND_VALUE, [100], S.owner_of(NSK), 1)
    p.append(CID, cm)
    p.spend(S.note_nullifier(NSK, cm))
    return p


def t_a_chain_without_private_state_is_unchanged():
    """The attribute is absent on every exec state built before this feature."""
    proj = ER.records_projection(_State())
    app_keys = [k for k in proj if k in (ER.record_key(ER.T_APP_NULL, "0" * 64),)]
    assert not app_keys, "an app record appeared on a state that has no pool"
    assert all(v is not None for v in proj.values()), "projection produced a null value"


def t_an_empty_pool_projects_identically():
    """Shipping the code must not move the root. This is the check that makes it an ordinary update."""
    without = ER.records_projection(_State())
    with_empty = ER.records_projection(_State(S.ShieldedStatePool()))
    assert without == with_empty, (
        f"an empty pool changed the projection by {set(with_empty) ^ set(without)} — "
        "shipping this would fork the fleet")


def t_a_contract_with_no_notes_contributes_nothing():
    p = S.ShieldedStatePool()
    p.trees[CID] = []                                        # touched, but holds nothing
    assert ER.records_projection(_State(p)) == ER.records_projection(_State()), \
        "an empty tree emitted a record"


def t_private_state_appears_once_it_exists():
    base = ER.records_projection(_State())
    full = ER.records_projection(_State(_populated()))
    added = set(full) - set(base)
    assert len(added) == 2, f"expected exactly a root record and a nullifier record, got {len(added)}"
    assert not (set(base) - set(full)), "adding private state removed an existing record"
    for k in added:
        assert full[k] == 1, "app records commit in the position, so the value must be 1"


def t_the_root_record_is_the_contracts_own():
    p = _populated()
    proj = ER.records_projection(_State(p))
    from execnode.stark import field as F
    expect = ER.record_key(ER.T_APP_ROOT, CID, str(int(p.root(CID)) % F.P))
    assert proj.get(expect) == 1, "the contract's note root is not committed at its own position"
    wrong = ER.record_key(ER.T_APP_ROOT, OTHER_CID, str(int(p.root(CID)) % F.P))
    assert wrong not in proj, "another contract's position carries this contract's root"


def t_appending_a_note_moves_that_contracts_record():
    p = _populated()
    before = set(ER.records_projection(_State(p)))
    p.append(CID, S.note_commitment(CID, S.KIND_VALUE, [7], S.owner_of(NSK), 42))
    after = set(ER.records_projection(_State(p)))
    assert before != after, "appending a note did not move the committed root"
    assert len(after) == len(before), "appending a note changed the record COUNT, not the root"


def t_spending_moves_the_nullifier_record():
    p = _populated()
    before = set(ER.records_projection(_State(p)))
    p.spend(12345)
    after = set(ER.records_projection(_State(p)))
    assert before != after, "a new nullifier did not move the committed set digest"
    assert len(after) == len(before), "a new nullifier changed the record COUNT"


def t_two_contracts_get_two_records():
    p = _populated()
    p.append(OTHER_CID, S.note_commitment(OTHER_CID, S.KIND_VALUE, [5], S.owner_of(NSK), 3))
    proj = ER.records_projection(_State(p))
    base = ER.records_projection(_State())
    assert len(set(proj) - set(base)) == 3, "two contracts and one spent set should be three records"


def t_projection_is_deterministic():
    """Same pool, rebuilt from its own snapshot, must project to the same positions — a root that depended
    on insertion order or on dict iteration would be a non-block-derived value entering consensus."""
    p = _populated()
    p.append(OTHER_CID, S.note_commitment(OTHER_CID, S.KIND_VALUE, [5], S.owner_of(NSK), 3))
    a = ER.records_projection(_State(p))
    b = ER.records_projection(_State(S.ShieldedStatePool.from_dict(p.to_dict())))
    assert a == b, "the projection did not survive a snapshot round-trip"


def t_tags_do_not_collide_with_the_existing_ten():
    assert ER.T_APP_ROOT == 11 and ER.T_APP_NULL == 12, "app tags moved off 11/12"
    used = {ER.T_BRIDGE_BAL, ER.T_DIV_BAL, ER.T_BRIDGE_WD, ER.T_DIV_WD, ER.T_UNSHIELD_WD,
            ER.T_DIGEST, ER.T_KVX, ER.T_ASSET_BAL, ER.T_ASSET_META, ER.T_ASSET_ALLOW}
    assert ER.T_APP_ROOT not in used and ER.T_APP_NULL not in used, "an app tag reuses a frozen tag number"


for name, fn in list(globals().items()):
    if name.startswith("t_"):
        check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "ALL STATE-BINDING CHECKS PASSED")
sys.exit(1 if FAILS else 0)
