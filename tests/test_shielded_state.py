"""
Shielded-contract private state (execnode/shielded_state.py) — soundness suite.

The pool this extends was built Phase-1-first for a reason: the state machine is where double-spends,
forged membership and unbacked value actually get stopped, and a circuit can only ever prove the statement
the state machine already insists on. So every check here is a check the eventual AIR must also enforce —
this file is the specification the Phase-2 circuit gets diffed against, not just a regression net.

Run:  python3 tests/test_shielded_state.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode import shielded_state as S
from execnode.stark import alghash

FAILS = []


def check(name, fn):
    try:
        fn()
        print("PASS  " + name)
    except AssertionError as e:
        print("FAIL  " + name + " — " + str(e))
        FAILS.append(name)
    except Exception as e:                                     # a crash is a failure, not an error report
        print(f"FAIL  {name} — {type(e).__name__}: {e}")
        FAILS.append(name)


CID = "d0be764f3da9c9cc6bb609280a887929"
OTHER_CID = "230860957a7c1db403434ffb4a3969b3"
NSK = 0xC0FFEE1234
NSK2 = 0xBEEF5678


def _note(cid, kind, fields, nsk, rho):
    """(commitment, nullifier) for a note owned by `nsk`."""
    cm = S.note_commitment(cid, kind, fields, S.owner_of(nsk), rho)
    return cm, S.note_nullifier(nsk, cm)


def _seed(pool, cid, fields, nsk, rho):
    """Put a note into the tree directly (the genesis of any private balance — an app's deposit path
    creates the first note; spending it is what the rest of the suite exercises)."""
    cm, nf = _note(cid, S.KIND_VALUE, fields, nsk, rho)
    pool.append(cid, cm)
    return cm, nf


def _spend(pool, cid, in_notes, out_notes, public_delta=0, kind=None):
    """Build (public, proof) for a transition spending `in_notes` [(fields, nsk, rho)] and creating
    `out_notes` [(fields, owner, rho)] — the shape a wallet would produce."""
    kind = S.KIND_VALUE if kind is None else kind
    ins, nfs = [], []
    for fields, nsk, rho in in_notes:
        cm = S.note_commitment(cid, kind, fields, S.owner_of(nsk), rho)
        pos = pool.position(cid, cm)
        sibs, dirs = S.tree_path(pool.trees.get(cid, []), pos if pos is not None else 0)
        ins.append({"nsk": nsk, "fields": fields, "rho": rho, "siblings": sibs, "dirs": dirs})
        nfs.append(S.note_nullifier(nsk, cm))
    outs, cms = [], []
    for fields, owner, rho in out_notes:
        outs.append({"fields": fields, "owner": owner, "rho": rho})
        cms.append(S.note_commitment(cid, kind, fields, owner, rho))
    public = {"cid": cid, "kind": kind, "root": pool.root(cid), "nullifiers": nfs,
              "out_commitments": cms, "public_delta": public_delta}
    return public, {"witness": {"inputs": ins, "outputs": outs}}


# ---- note algebra ------------------------------------------------------------------------------------
def t_commitment_is_deterministic_and_scoped():
    a = S.note_commitment(CID, S.KIND_VALUE, [100], S.owner_of(NSK), 7)
    assert a == S.note_commitment(CID, S.KIND_VALUE, [100], S.owner_of(NSK), 7), "not deterministic"
    assert a != S.note_commitment(OTHER_CID, S.KIND_VALUE, [100], S.owner_of(NSK), 7), "cid does not scope"
    assert a != S.note_commitment(CID, S.KIND_VALUE + 1, [100], S.owner_of(NSK), 7), "kind does not scope"
    assert a != S.note_commitment(CID, S.KIND_VALUE, [101], S.owner_of(NSK), 7), "fields not bound"
    assert a != S.note_commitment(CID, S.KIND_VALUE, [100], S.owner_of(NSK2), 7), "owner not bound"
    assert a != S.note_commitment(CID, S.KIND_VALUE, [100], S.owner_of(NSK), 8), "rho not bound"


def t_arity_is_bound():
    """Two notes whose flat absorption sequences would otherwise coincide must not share a commitment."""
    a = S.note_commitment(CID, S.KIND_VALUE, [1, 2], 3, 4)
    b = S.note_commitment(CID, S.KIND_VALUE, [1], 2, 3)          # one shorter, same trailing elements
    assert a != b, "arity is not bound into the commitment"


def t_domain_separated_from_pool_notes():
    """An app note and a value-pool note must never hash alike, or one pool's note could be replayed
    into the other's tree."""
    app = S.note_commitment(CID, S.KIND_VALUE, [100], S.owner_of(NSK), 7)
    pool = alghash.commit(100, alghash.owner_of(NSK), 7)
    assert app != pool, "app commitment collides with a value-pool commitment"


def t_nullifier_is_not_computable_by_the_sender():
    """The sender picks rho and knows the recipient's owner id, but not nsk. Deriving nf from cm means the
    best they can do with what they hold is not the nullifier."""
    owner = S.owner_of(NSK)
    cm = S.note_commitment(CID, S.KIND_VALUE, [100], owner, 7)
    real = S.note_nullifier(NSK, cm)
    from_sender_view = alghash.hashn([S.DOM_APPNF, owner, cm])   # owner id is all the sender has
    assert real != from_sender_view, "sender can derive the nullifier"


def t_path_folds_to_the_root():
    leaves = [S.note_commitment(CID, S.KIND_VALUE, [i], S.owner_of(NSK), i) for i in range(5)]
    root = S.tree_root(leaves)
    for pos in range(len(leaves)):
        sibs, dirs = S.tree_path(leaves, pos)
        assert S.fold_path(leaves[pos], sibs, dirs) == root, f"path at {pos} does not fold to the root"


def t_empty_tree_has_a_stable_root():
    p = S.ShieldedStatePool()
    assert p.root("anything") == S.EMPTY_ROOT, "a contract with no notes is not the empty root"


# ---- the consensus switch ----------------------------------------------------------------------------
def t_transparent_witness_is_refused_by_default():
    """Phase 1 reveals nsk. A chain that accepted it would publish spend keys, so the default must refuse."""
    assert S.CONSENSUS_ALLOW_TRANSPARENT is False, "transparent witnesses are enabled by default"
    p = S.ShieldedStatePool()
    _seed(p, CID, [100], NSK, 1)
    public, proof = _spend(p, CID, [([100], NSK, 1)], [([100], S.owner_of(NSK2), 2)])
    assert S.verify_transition(public, proof, p) == "transparent witness refused — a proof is required", \
        "a transparent witness was accepted with the switch off"


def t_stark_seam_is_honest_about_being_unbuilt():
    p = S.ShieldedStatePool()
    r = S.verify_transition({"cid": CID, "kind": S.KIND_VALUE, "nullifiers": [1], "out_commitments": []},
                            {"stark": {"anything": 1}}, p)
    assert "phase 2" in r, f"stark seam did not say it is unbuilt: {r}"


# ---- the transitions themselves (with the switch forced on, as dev/test) -----------------------------
class _Transparent:
    """Force the Phase-1 verifier on for the duration of a test, and put it back afterwards."""
    def __enter__(self):
        self.prev = S.CONSENSUS_ALLOW_TRANSPARENT
        S.CONSENSUS_ALLOW_TRANSPARENT = True

    def __exit__(self, *a):
        S.CONSENSUS_ALLOW_TRANSPARENT = self.prev


def t_a_valid_transition_applies():
    with _Transparent():
        p = S.ShieldedStatePool()
        _seed(p, CID, [100], NSK, 1)
        public, proof = _spend(p, CID, [([100], NSK, 1)], [([60], S.owner_of(NSK2), 2), ([40], S.owner_of(NSK), 3)])
        assert S.apply_transition(public, proof, p) is None, "a valid transition was rejected"
        assert p.has_nullifier(public["nullifiers"][0]), "the spent note was not nullified"
        assert len(p.trees[CID]) == 3, "the output notes were not appended"


def t_double_spend_is_rejected():
    with _Transparent():
        p = S.ShieldedStatePool()
        _seed(p, CID, [100], NSK, 1)
        public, proof = _spend(p, CID, [([100], NSK, 1)], [([100], S.owner_of(NSK2), 2)])
        assert S.apply_transition(public, proof, p) is None, "first spend rejected"
        # rebuild against the NEW root so only the nullifier is stale
        public2, proof2 = _spend(p, CID, [([100], NSK, 1)], [([100], S.owner_of(NSK2), 9)])
        assert S.apply_transition(public2, proof2, p) == "note already spent", "double spend accepted"


def t_value_must_be_conserved():
    with _Transparent():
        p = S.ShieldedStatePool()
        _seed(p, CID, [100], NSK, 1)
        public, proof = _spend(p, CID, [([100], NSK, 1)], [([140], S.owner_of(NSK2), 2)])
        r = S.apply_transition(public, proof, p)
        assert r and "not conserved" in r, f"value was minted from nothing: {r}"


def t_public_delta_moves_value_in_and_out():
    with _Transparent():
        p = S.ShieldedStatePool()
        _seed(p, CID, [100], NSK, 1)
        public, proof = _spend(p, CID, [([100], NSK, 1)], [([130], S.owner_of(NSK), 2)], public_delta=30)
        assert S.apply_transition(public, proof, p) is None, "a funded deposit was rejected"


def t_modp_wraparound_cannot_mint():
    """The attack the range bound exists for: an output near P balances mod P but is not an integer balance."""
    with _Transparent():
        from execnode.stark import field as Fld
        p = S.ShieldedStatePool()
        _seed(p, CID, [1], NSK, 1)
        huge = (1 - (1 << 61)) % Fld.P                      # ≈ P, and 1 + (-(2**61)) ≡ huge (mod P)
        public, proof = _spend(p, CID, [([1], NSK, 1)], [([huge], S.owner_of(NSK2), 2)],
                               public_delta=-(1 << 61))
        r = S.apply_transition(public, proof, p)
        assert r is not None, "a mod-P wraparound assignment was accepted"


def t_forged_membership_is_rejected():
    with _Transparent():
        p = S.ShieldedStatePool()
        _seed(p, CID, [100], NSK, 1)
        public, proof = _spend(p, CID, [([100], NSK, 1)], [([100], S.owner_of(NSK2), 2)])
        proof["witness"]["inputs"][0]["siblings"][0] ^= 1        # break one sibling
        r = S.apply_transition(public, proof, p)
        assert r and "not a member" in r, f"a forged path was accepted: {r}"


def t_a_note_that_was_never_in_the_tree_cannot_be_spent():
    with _Transparent():
        p = S.ShieldedStatePool()
        _seed(p, CID, [100], NSK, 1)                            # tree holds 100, we try to spend 500
        public, proof = _spend(p, CID, [([500], NSK, 9)], [([500], S.owner_of(NSK2), 2)])
        r = S.apply_transition(public, proof, p)
        assert r and "not a member" in r, f"an invented note was spent: {r}"


def t_nullifier_must_derive_from_the_spent_note():
    with _Transparent():
        p = S.ShieldedStatePool()
        _seed(p, CID, [100], NSK, 1)
        public, proof = _spend(p, CID, [([100], NSK, 1)], [([100], S.owner_of(NSK2), 2)])
        public["nullifiers"][0] = (public["nullifiers"][0] + 1)  # a nullifier of the spender's choosing
        r = S.apply_transition(public, proof, p)
        assert r and "not derived" in r, f"an unbound nullifier was accepted: {r}"


def t_output_commitment_must_derive_from_its_opening():
    with _Transparent():
        p = S.ShieldedStatePool()
        _seed(p, CID, [100], NSK, 1)
        public, proof = _spend(p, CID, [([100], NSK, 1)], [([100], S.owner_of(NSK2), 2)])
        public["out_commitments"][0] += 1
        r = S.apply_transition(public, proof, p)
        assert r and "not derived" in r, f"an output commitment was accepted unopened: {r}"


def t_a_note_cannot_move_between_contracts():
    """cid is inside the commitment, so the same opening under another contract is simply not in its tree."""
    with _Transparent():
        p = S.ShieldedStatePool()
        _seed(p, CID, [100], NSK, 1)
        public, proof = _spend(p, CID, [([100], NSK, 1)], [([100], S.owner_of(NSK2), 2)])
        public["cid"] = OTHER_CID                                 # replay it against a different app
        r = S.apply_transition(public, proof, p)
        assert r is not None, "a note was spent under a contract that never held it"


def t_duplicate_nullifier_within_one_transition():
    with _Transparent():
        p = S.ShieldedStatePool()
        _seed(p, CID, [100], NSK, 1)
        public, proof = _spend(p, CID, [([100], NSK, 1)], [([200], S.owner_of(NSK2), 2)])
        public["nullifiers"] = public["nullifiers"] * 2           # spend the same note twice, in one go
        proof["witness"]["inputs"] = proof["witness"]["inputs"] * 2
        r = S.apply_transition(public, proof, p)
        assert r == "duplicate nullifier within one transition", f"same-transition double spend: {r}"


def t_unknown_kind_is_rejected():
    p = S.ShieldedStatePool()
    r = S.verify_transition({"cid": CID, "kind": 999, "nullifiers": [], "out_commitments": [1]}, {}, p)
    assert r == "unknown note kind 999", f"an unpredicated note kind was accepted: {r}"


def t_stale_anchor_is_rejected():
    with _Transparent():
        p = S.ShieldedStatePool()
        _seed(p, CID, [100], NSK, 1)
        public, proof = _spend(p, CID, [([100], NSK, 1)], [([100], S.owner_of(NSK2), 2)])
        public["root"] = 12345                                    # a root this contract never held
        r = S.apply_transition(public, proof, p)
        assert r and "unknown anchor" in r, f"an unknown anchor was accepted: {r}"


def t_a_rejected_transition_mutates_nothing():
    """The ordering the pool's own unshield bug was fixed for: never nullify before the whole check passes."""
    with _Transparent():
        p = S.ShieldedStatePool()
        _seed(p, CID, [100], NSK, 1)
        before_notes = list(p.trees[CID])
        before_nfs = set(p.nullifiers)
        public, proof = _spend(p, CID, [([100], NSK, 1)], [([140], S.owner_of(NSK2), 2)])   # not conserved
        assert S.apply_transition(public, proof, p) is not None, "the invalid transition was accepted"
        assert p.trees[CID] == before_notes, "a rejected transition appended a commitment"
        assert p.nullifiers == before_nfs, "a rejected transition burned a nullifier"


def t_bounds_are_enforced():
    p = S.ShieldedStatePool()
    r = S.verify_transition({"cid": CID, "kind": S.KIND_VALUE,
                             "nullifiers": list(range(S.MAX_INPUTS + 1)), "out_commitments": []}, {}, p)
    assert r and "exceeds" in r, f"input bound not enforced: {r}"
    r = S.verify_transition({"cid": CID, "kind": S.KIND_VALUE, "nullifiers": [], "out_commitments": []}, {}, p)
    assert r == "transition spends and creates nothing", f"empty transition accepted: {r}"


def t_snapshot_round_trips():
    with _Transparent():
        p = S.ShieldedStatePool()
        _seed(p, CID, [100], NSK, 1)
        public, proof = _spend(p, CID, [([100], NSK, 1)], [([100], S.owner_of(NSK2), 2)])
        assert S.apply_transition(public, proof, p) is None
        q = S.ShieldedStatePool.from_dict(p.to_dict())
        assert q.root(CID) == p.root(CID), "root did not survive the snapshot"
        assert q.nullifiers == p.nullifiers, "nullifier set did not survive the snapshot"
        assert q.nullifier_digest() == p.nullifier_digest(), "digest did not survive the snapshot"


for name, fn in list(globals().items()):
    if name.startswith("t_"):
        check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "ALL SHIELDED-STATE CHECKS PASSED")
sys.exit(1 if FAILS else 0)
