"""
Phase-2 STARK verifier seam for the shielded transfer (doc/privacy.md) — the drop-in target of
verify_transfer's `proof` seam.

The complete 1-in/1-out join-split is now arithmetised (execnode/stark/joinsplit_circuit): owner binding,
input commitment, Merkle membership, nullifier, output commitment, AND value conservation, all in ONE
zero-knowledge STARK over field-hash (alghash) notes. A `stark` bundle carries {proof, root, nf, cm_out,
public_value, fee}; this verifies it against the public inputs, revealing nothing about the opening or which
leaf was spent.

PHASE2_COMPLETE means the circuit covers the full statement. It applies to FIELD-HASH (alghash) notes — the
representation the STARK proves. Migrating the live BLAKE2b pool + the browser client to the field hash (and
providing a client/delegated prover) is the remaining rollout; on a field-hash pool this is a complete,
sound, private verifier.
"""
from execnode.stark import joinsplit, alghash, joinsplit_circuit, joinsplit2

PHASE2_COMPLETE = True


def verify_output_commitments(out_commitments, bundle):
    """(Legacy partial path) zero-knowledge check that each output commitment is a well-formed note commitment."""
    proofs = (bundle or {}).get("outputs", [])
    if len(proofs) != len(out_commitments):
        return False, "need one STARK proof per output commitment"
    for cm, pr in zip(out_commitments, proofs):
        ok, why = joinsplit.verify_hash(pr, {0: alghash.DOM_CM}, cm)
        if not ok:
            return False, f"an output commitment is not proven well-formed: {why}"
    return True, "ok"


def prove_output_commitments(outputs):
    """(Legacy partial path) build the ZK well-formedness proofs for output openings [(value, owner, rho), ...]."""
    proofs, cms = [], []
    for (value, owner, rho) in outputs:
        pr, cm = joinsplit.prove_hash([alghash.DOM_CM, value, owner, rho], public_positions=[0])
        proofs.append(pr); cms.append(cm)
    return {"outputs": proofs}, cms


def verify_transfer(public, proof, root_is_known):
    """verify_transfer's Phase-2 path (dispatched when the proof carries a 'stark' bundle)."""
    bundle = proof.get("stark") or {}
    # 2-output join-split (send any amount + change).
    if "joinsplit2" in bundle:
        b = bundle["joinsplit2"]
        try:
            return joinsplit2.verify_transfer(b["proof"], b["root"], b["nf"], b["cm_out1"], b["cm_out2"],
                                              b["public_value"], b["fee"], root_is_known)
        except (KeyError, TypeError) as e:
            return False, f"malformed joinsplit2 bundle: {e}"
    # FULL 1-output join-split proof: the complete transfer statement in one STARK.
    if "joinsplit" in bundle:
        b = bundle["joinsplit"]
        try:
            return joinsplit_circuit.verify_transfer(
                b["proof"], b["root"], b["nf"], b["cm_out"], b["public_value"], b["fee"], root_is_known)
        except (KeyError, TypeError) as e:
            return False, f"malformed join-split bundle: {e}"
    # legacy partial path (output well-formedness only)
    ok, why = verify_output_commitments(public.get("out_commitments", []), bundle)
    if not ok:
        return False, why
    return True, "ok (zk output well-formedness only; use a 'joinsplit' bundle for the full statement)"
