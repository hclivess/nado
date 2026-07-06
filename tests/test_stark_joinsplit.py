"""
Join-split arithmetisation (execnode/stark/joinsplit.py, doc/privacy.md): the sponge-hash gadget that
underlies every shielded check, proven in zero-knowledge. A correctly-formed note commitment / nullifier
verifies while its opening stays secret; a wrong output or a tampered public tag is rejected.

Run: python3 tests/test_stark_joinsplit.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import field as F, alghash, joinsplit

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def t1_note_commitment_zk():
    """Prove cm = commit(value, owner, rho) verifies with only the DOM_CM tag and cm public (opening stays secret)."""
    # prove cm = commit(value, owner, rho) WITHOUT revealing value/owner/rho (only the DOM_CM tag + cm public)
    value, owner, rho = 12345, 67890, 11111
    cm = alghash.commit(value, owner, rho)
    msgs = [alghash.DOM_CM, value, owner, rho]
    proof, out = joinsplit.prove_hash(msgs, public_positions=[0])
    assert out == cm, "gadget output must equal commit()"
    ok, why = joinsplit.verify_hash(proof, {0: alghash.DOM_CM}, cm)
    assert ok, f"a well-formed commitment must verify: {why}"

def t2_wrong_output_rejected():
    """Prove verify_hash rejects a claimed commitment the trace doesn't actually produce (cm+1)."""
    value, owner, rho = 12345, 67890, 11111
    cm = alghash.commit(value, owner, rho)
    proof, _ = joinsplit.prove_hash([alghash.DOM_CM, value, owner, rho], public_positions=[0])
    ok, _ = joinsplit.verify_hash(proof, {0: alghash.DOM_CM}, F.add(cm, 1))   # claim a different commitment
    assert not ok, "a commitment claim the trace doesn't produce must be rejected"

def t3_wrong_domain_tag_rejected():
    """Prove a commitment-domain proof is rejected when claimed under the nullifier domain tag (DOM_NF)."""
    value, owner, rho = 7, 8, 9
    cm = alghash.commit(value, owner, rho)
    proof, _ = joinsplit.prove_hash([alghash.DOM_CM, value, owner, rho], public_positions=[0])
    ok, _ = joinsplit.verify_hash(proof, {0: alghash.DOM_NF}, cm)   # claim it was a nullifier-domain hash
    assert not ok, "a mismatched public domain tag must be rejected"

def t4_nullifier_zk():
    """Prove nf = nullifier(nsk, rho) verifies in ZK with only the DOM_NF tag and nf public."""
    nsk, rho = 424242, 99
    nf = alghash.nullifier(nsk, rho)
    proof, out = joinsplit.prove_hash([alghash.DOM_NF, nsk, rho], public_positions=[0])
    assert out == nf
    ok, why = joinsplit.verify_hash(proof, {0: alghash.DOM_NF}, nf)
    assert ok, f"a well-formed nullifier must verify: {why}"

def t5_merkle_node_zk():
    """Prove a Merkle tree node hash (DOM_NODE over two children) verifies in ZK — the unit a membership path chains."""
    # a tree node hash (the unit a membership path chains) proven in ZK over its two children
    left, right = 111, 222
    node = alghash.merkle_node(left, right)
    proof, out = joinsplit.prove_hash([alghash.DOM_NODE, left, right], public_positions=[0])
    assert out == node
    ok, why = joinsplit.verify_hash(proof, {0: alghash.DOM_NODE}, node)
    assert ok, why

def t6_verify_transfer_stark_seam():
    """Prove a valid STARK output-wellformedness bundle passes the real shielded.verify_transfer seam."""
    # route a STARK bundle through the REAL verify_transfer seam (execnode/shielded.py)
    from execnode.stark import joinsplit_transfer
    from execnode import shielded
    outputs = [(60, 111, 7), (40, 222, 8)]          # (value, owner, rho) openings
    bundle, cms = joinsplit_transfer.prove_output_commitments(outputs)
    public = {"out_commitments": cms}
    ok, why = shielded.verify_transfer(public, {"stark": bundle}, lambda r: True)
    assert ok, f"verify_transfer must accept a valid STARK output-wellformedness bundle: {why}"

def t7_verify_transfer_stark_rejects_bad_commitment():
    """Prove verify_transfer rejects a STARK bundle whose claimed output commitment is wrong."""
    from execnode.stark import joinsplit_transfer
    from execnode import shielded
    bundle, cms = joinsplit_transfer.prove_output_commitments([(60, 111, 7)])
    public = {"out_commitments": [F.add(cms[0], 1)]}   # claim a commitment the proof doesn't produce
    ok, _ = shielded.verify_transfer(public, {"stark": bundle}, lambda r: True)
    assert not ok, "verify_transfer must reject a STARK bundle whose commitment is wrong"

for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
