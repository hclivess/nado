"""
zk-STARK shielded pool — Phase-1 state-machine + soundness tests (execnode/shielded.py, doc/privacy.md).

These test the properties that must hold NOW and remain true after the Phase-2 STARK verifier replaces the
transparent one: hiding+binding commitments, unlinkable nullifiers, Merkle membership, value conservation,
double-spend prevention, anchor freshness, and the full shield -> transfer -> unshield flow.

Run: python3 tests/test_shielded.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.shielded import (ShieldedPool, note_commitment, note_nullifier, owner_id,
                               merkle_root, merkle_path, verify_path, apply_transfer, verify_transfer,
                               EMPTY_ROOT, SHIELD_DEPTH)

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

# --- a tiny "wallet" helper: notes are (value, spend_secret, rho) --------------------------------
def note(value, ss, rho): return {"value": value, "ss": ss, "rho": rho}
def cm_of(n): return note_commitment(n["value"], owner_id(n["ss"]), n["rho"])

def shield_tx(pool, out_notes, fee=0):
    pub_value = sum(n["value"] for n in out_notes) + fee            # coins entering the pool
    public = {"root": pool.root(), "nullifiers": [], "out_commitments": [cm_of(n) for n in out_notes],
              "public_value": pub_value, "fee": fee}
    proof = {"inputs": [], "outputs": [{"value": n["value"], "owner": owner_id(n["ss"]), "rho": n["rho"]} for n in out_notes]}
    return public, proof

def spend_tx(pool, in_specs, out_notes, public_value=0, fee=0):
    # in_specs: list of (note, pos). Builds nullifiers + membership witness against the CURRENT root.
    root = pool.root()
    ins, nfs = [], []
    for n, pos in in_specs:
        ins.append({"value": n["value"], "spend_secret": n["ss"], "rho": n["rho"],
                    "pos": pos, "path": merkle_path(pool.commitments, pos)})
        nfs.append(note_nullifier(n["ss"], n["rho"]))
    public = {"root": root, "nullifiers": nfs, "out_commitments": [cm_of(n) for n in out_notes],
              "public_value": public_value, "fee": fee}
    proof = {"inputs": ins, "outputs": [{"value": n["value"], "owner": owner_id(n["ss"]), "rho": n["rho"]} for n in out_notes]}
    return public, proof


def t1_commitment_hiding_and_binding():
    a = note_commitment(100, owner_id("alice"), "r1")
    b = note_commitment(100, owner_id("alice"), "r2")        # same value+owner, fresh rho
    assert a != b, "fresh rho -> unlinkable commitments (hiding)"
    assert note_commitment(100, owner_id("alice"), "r1") == a, "binding: same opening -> same commitment"
    assert note_commitment(101, owner_id("alice"), "r1") != a, "different value -> different commitment"

def t2_nullifier_is_deterministic_and_secret_bound():
    assert note_nullifier("alice", "r1") == note_nullifier("alice", "r1"), "deterministic"
    assert note_nullifier("alice", "r1") != note_nullifier("bob", "r1"), "bound to the spend secret"
    # a nullifier is in a different domain than the commitment -> not equal to it (unlinkable)
    assert note_nullifier("alice", "r1") != note_commitment(1, owner_id("alice"), "r1")

def t3_merkle_root_and_membership():
    leaves = [note_commitment(i, owner_id("x"), f"r{i}") for i in range(5)]
    root = merkle_root(leaves)
    assert merkle_root([]) == EMPTY_ROOT, "empty tree root is the all-empty root"
    for pos in range(5):
        assert verify_path(leaves[pos], pos, merkle_path(leaves, pos), root), f"leaf {pos} must verify"
    # tamper: a wrong leaf or wrong path fails
    assert not verify_path(leaves[0], 1, merkle_path(leaves, 0), root), "wrong position must fail"
    assert not verify_path("deadbeef", 0, merkle_path(leaves, 0), root), "wrong leaf must fail"

def t4_shield_then_private_transfer():
    pool = ShieldedPool()
    n0 = note(100, "alice", "r0")
    ok, why = apply_transfer(pool, *shield_tx(pool, [n0]), pool.knows_root)      # Alice shields 100
    assert ok, why
    assert pool.size() == 1 and pool.knows_root(pool.root())
    # Alice privately sends 60 to Bob + 40 change to herself (value conserved, public_value 0)
    to_bob = note(60, "bob", "rb"); change = note(40, "alice", "rc")
    ok, why = apply_transfer(pool, *spend_tx(pool, [(n0, 0)], [to_bob, change]), pool.knows_root)
    assert ok, why
    assert pool.size() == 3, "two new notes appended"
    assert pool.has_nullifier(note_nullifier("alice", "r0")), "input note is nullified"

def t5_double_spend_rejected():
    pool = ShieldedPool()
    n0 = note(50, "alice", "r0")
    apply_transfer(pool, *shield_tx(pool, [n0]), pool.knows_root)
    out1 = note(50, "bob", "rb1")
    ok, _ = apply_transfer(pool, *spend_tx(pool, [(n0, 0)], [out1]), pool.knows_root)
    assert ok, "first spend ok"
    # spend the SAME note again (same nullifier) -> rejected
    out2 = note(50, "carol", "rc")
    ok, why = apply_transfer(pool, *spend_tx(pool, [(n0, 0)], [out2]), pool.knows_root)
    assert not ok and "double-spend" in why, f"double-spend must be rejected, got {why}"

def t6_value_not_conserved_rejected():
    pool = ShieldedPool()
    n0 = note(100, "alice", "r0")
    apply_transfer(pool, *shield_tx(pool, [n0]), pool.knows_root)
    # try to spend 100 in -> 150 out (mint from nothing)
    bad = note(150, "bob", "rb")
    ok, why = apply_transfer(pool, *spend_tx(pool, [(n0, 0)], [bad]), pool.knows_root)
    assert not ok and "conserved" in why, f"value inflation must be rejected, got {why}"

def t7_forged_membership_and_wrong_nullifier_rejected():
    pool = ShieldedPool()
    n0 = note(100, "alice", "r0")
    apply_transfer(pool, *shield_tx(pool, [n0]), pool.knows_root)
    # a note that was never shielded -> its membership path can't verify
    ghost = note(100, "alice", "rGHOST")
    public, proof = spend_tx(pool, [(ghost, 0)], [note(100, "bob", "rb")])
    ok, why = apply_transfer(pool, public, proof, pool.knows_root)
    assert not ok and "not in the tree" in why, f"forged membership must fail, got {why}"
    # tamper the nullifier so it no longer matches the (real) note
    public, proof = spend_tx(pool, [(n0, 0)], [note(100, "bob", "rb")])
    public["nullifiers"] = [note_nullifier("mallory", "r0")]
    ok, why = apply_transfer(pool, public, proof, pool.knows_root)
    assert not ok and "nullifier does not match" in why, f"mismatched nullifier must fail, got {why}"

def t8_unshield_withdraws_with_change():
    pool = ShieldedPool()
    n0 = note(100, "alice", "r0")
    apply_transfer(pool, *shield_tx(pool, [n0]), pool.knows_root)
    # unshield 70 (public_value = -70 leaves the pool) + keep 30 as a change note, fee 0
    change = note(30, "alice", "rc")
    ok, why = apply_transfer(pool, *spend_tx(pool, [(n0, 0)], [change], public_value=-70), pool.knows_root)
    assert ok, why
    assert pool.has_nullifier(note_nullifier("alice", "r0")) and pool.size() == 2

def t9_unknown_anchor_rejected():
    pool = ShieldedPool()
    n0 = note(100, "alice", "r0")
    apply_transfer(pool, *shield_tx(pool, [n0]), pool.knows_root)
    public, proof = spend_tx(pool, [(n0, 0)], [note(100, "bob", "rb")])
    public["root"] = "0" * 64                                     # a root the pool never held
    ok, why = apply_transfer(pool, public, proof, pool.knows_root)
    assert not ok and "anchor" in why, f"unknown anchor must be rejected, got {why}"

def t10_fee_is_conserved():
    pool = ShieldedPool()
    n0 = note(100, "alice", "r0")
    apply_transfer(pool, *shield_tx(pool, [n0]), pool.knows_root)
    # spend 100 -> 90 out + 10 fee: conserves
    ok, why = apply_transfer(pool, *spend_tx(pool, [(n0, 0)], [note(90, "bob", "rb")], fee=10), pool.knows_root)
    assert ok, why

for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
