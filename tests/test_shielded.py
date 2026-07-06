"""
zk-STARK shielded pool — Phase-1 state-machine + soundness tests (execnode/shielded.py, doc/privacy.md).

These test the properties that must hold NOW and remain true after the Phase-2 STARK verifier replaces the
transparent one: hiding+binding commitments, unlinkable nullifiers, Merkle membership, value conservation,
double-spend prevention, anchor freshness, ML-DSA spend authorisation, and the full shield -> transfer ->
unshield flow.

Run: python3 tests/test_shielded.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.shielded import (ShieldedPool, note_commitment, note_nullifier, owner_id, transfer_sighash,
                               merkle_root, merkle_path, verify_path, apply_transfer, EMPTY_ROOT)
from Curve25519 import generate_keydict, sign, unhex

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

# ML-DSA keypairs (keygen is slow -> make them once)
ALICE, BOB, CAROL, MALLORY = (generate_keydict() for _ in range(4))

def note(value, kd, rho):
    """Build a test note dict {value, kd (owner keydict), rho}."""
    return {"value": value, "kd": kd, "rho": rho}
def cm_of(n):
    """Note commitment of test note n."""
    return note_commitment(n["value"], owner_id(n["kd"]["public_key"]), n["rho"])
def out_open(n):
    """Output-note opening {value, owner, rho} of test note n."""
    return {"value": n["value"], "owner": owner_id(n["kd"]["public_key"]), "rho": n["rho"]}

def shield_tx(pool, out_notes, fee=0):
    """Build a (public, proof) shield deposit creating out_notes, with public_value covering outputs + fee."""
    public = {"root": pool.root(), "nullifiers": [], "out_commitments": [cm_of(n) for n in out_notes],
              "public_value": sum(n["value"] for n in out_notes) + fee, "fee": fee}
    return public, {"inputs": [], "outputs": [out_open(n) for n in out_notes]}

def spend_tx(pool, in_specs, out_notes, public_value=0, fee=0, sign_with=None):
    """Build a (public, proof) spend of in_specs [(note, pos)] into out_notes, signed per input (sign_with forges with another key)."""
    # in_specs: [(note, pos)]. sign_with: optional keydict to forge the signature with (defaults to the note's own key)
    nfs = [note_nullifier(n["kd"]["public_key"], n["rho"]) for n, _ in in_specs]
    public = {"root": pool.root(), "nullifiers": nfs, "out_commitments": [cm_of(n) for n in out_notes],
              "public_value": public_value, "fee": fee}
    sh = transfer_sighash(public)
    ins = []
    for n, pos in in_specs:
        signer = sign_with or n["kd"]
        ins.append({"value": n["value"], "pubkey": n["kd"]["public_key"], "rho": n["rho"], "pos": pos,
                    "path": merkle_path(pool.commitments, pos), "sig": sign(signer["private_key"], unhex(sh))})
    return public, {"inputs": ins, "outputs": [out_open(n) for n in out_notes]}


def t1_commitment_hiding_and_binding():
    """Prove commitments are hiding (fresh rho -> unlinkable) and binding (same opening -> same, changed value -> different)."""
    o = owner_id(ALICE["public_key"])
    a = note_commitment(100, o, "r1"); b = note_commitment(100, o, "r2")
    assert a != b, "fresh rho -> unlinkable commitments (hiding)"
    assert note_commitment(100, o, "r1") == a and note_commitment(101, o, "r1") != a, "binding"

def t2_nullifier_domain():
    """Prove nullifiers are deterministic, key-bound, and domain-separated from commitments."""
    pk = ALICE["public_key"]
    assert note_nullifier(pk, "r1") == note_nullifier(pk, "r1")
    assert note_nullifier(pk, "r1") != note_nullifier(BOB["public_key"], "r1")
    assert note_nullifier(pk, "r1") != note_commitment(1, owner_id(pk), "r1")

def t3_merkle_membership():
    """Prove Merkle paths verify for every leaf at its own position and fail at a wrong position; empty tree hashes to EMPTY_ROOT."""
    leaves = [note_commitment(i, owner_id(ALICE["public_key"]), f"r{i}") for i in range(5)]
    root = merkle_root(leaves)
    assert merkle_root([]) == EMPTY_ROOT
    for pos in range(5):
        assert verify_path(leaves[pos], pos, merkle_path(leaves, pos), root)
    assert not verify_path(leaves[0], 1, merkle_path(leaves, 0), root)

def t4_shield_then_private_transfer():
    """Prove a shield followed by a private 2-output transfer applies, growing the tree and recording the spent nullifier."""
    pool = ShieldedPool()
    n0 = note(100, ALICE, "r0")
    ok, why = apply_transfer(pool, *shield_tx(pool, [n0]), pool.knows_root)
    assert ok, why
    ok, why = apply_transfer(pool, *spend_tx(pool, [(n0, 0)], [note(60, BOB, "rb"), note(40, ALICE, "rc")]), pool.knows_root)
    assert ok, why
    assert pool.size() == 3 and pool.has_nullifier(note_nullifier(ALICE["public_key"], "r0"))

def t5_double_spend_rejected():
    """Prove spending the same note a second time is rejected as a double-spend."""
    pool = ShieldedPool()
    n0 = note(50, ALICE, "r0")
    apply_transfer(pool, *shield_tx(pool, [n0]), pool.knows_root)
    assert apply_transfer(pool, *spend_tx(pool, [(n0, 0)], [note(50, BOB, "rb1")]), pool.knows_root)[0]
    ok, why = apply_transfer(pool, *spend_tx(pool, [(n0, 0)], [note(50, CAROL, "rc")]), pool.knows_root)
    assert not ok and "double-spend" in why, why

def t6_value_not_conserved_rejected():
    """Prove a transfer whose outputs exceed its inputs is rejected (value conservation)."""
    pool = ShieldedPool()
    n0 = note(100, ALICE, "r0")
    apply_transfer(pool, *shield_tx(pool, [n0]), pool.knows_root)
    ok, why = apply_transfer(pool, *spend_tx(pool, [(n0, 0)], [note(150, BOB, "rb")]), pool.knows_root)
    assert not ok and "conserved" in why, why

def t7_unauthorised_spend_rejected():
    """Prove knowing a note's opening is not enough: a spend signed with the wrong key fails authorisation."""
    # the CORE of ML-DSA auth: knowing the note opening is not enough — a wrong-key signature is rejected.
    pool = ShieldedPool()
    n0 = note(100, ALICE, "r0")
    apply_transfer(pool, *shield_tx(pool, [n0]), pool.knows_root)
    # Mallory knows Alice's note (value, pubkey, rho) but signs with HER OWN key -> auth fails
    ok, why = apply_transfer(pool, *spend_tx(pool, [(n0, 0)], [note(100, MALLORY, "rm")], sign_with=MALLORY), pool.knows_root)
    assert not ok and "authorisation" in why, f"forged-signature spend must be rejected, got {why}"

def t8_forged_membership_rejected():
    """Prove spending a note that was never shielded (not in the tree) is rejected."""
    pool = ShieldedPool()
    n0 = note(100, ALICE, "r0")
    apply_transfer(pool, *shield_tx(pool, [n0]), pool.knows_root)
    ghost = note(100, ALICE, "rGHOST")   # never shielded
    ok, why = apply_transfer(pool, *spend_tx(pool, [(ghost, 0)], [note(100, BOB, "rb")]), pool.knows_root)
    assert not ok and "not in the tree" in why, why

def t9_unshield_and_fee():
    """Prove a partial unshield (negative public_value) with change and a fee-paying spend both conserve value."""
    pool = ShieldedPool()
    n0 = note(100, ALICE, "r0")
    apply_transfer(pool, *shield_tx(pool, [n0]), pool.knows_root)
    # unshield 70 (public_value -70) + 30 change, fee 0
    ok, why = apply_transfer(pool, *spend_tx(pool, [(n0, 0)], [note(30, ALICE, "rc")], public_value=-70), pool.knows_root)
    assert ok, why
    n1 = note(50, BOB, "rb")
    apply_transfer(pool, *shield_tx(pool, [n1]), pool.knows_root)
    pos = pool.size() - 1
    ok, why = apply_transfer(pool, *spend_tx(pool, [(n1, pos)], [note(40, CAROL, "rk")], fee=10), pool.knows_root)
    assert ok, why  # 50 -> 40 out + 10 fee conserves

def t10_unknown_anchor_rejected():
    """Prove a transfer anchored to a root the pool never had is rejected (anchor freshness)."""
    pool = ShieldedPool()
    n0 = note(100, ALICE, "r0")
    apply_transfer(pool, *shield_tx(pool, [n0]), pool.knows_root)
    public, proof = spend_tx(pool, [(n0, 0)], [note(100, BOB, "rb")])
    public["root"] = "0" * 64
    ok, why = apply_transfer(pool, public, proof, pool.knows_root)
    assert not ok and "anchor" in why, why

for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
