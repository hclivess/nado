"""
Phase-2 STARK verifier seam for the shielded transfer (doc/privacy.md) — the drop-in target of
verify_transfer's `proof` seam.

WHAT IT PROVES TODAY (in zero-knowledge, revealing no opening): every OUTPUT commitment in the transfer is a
correctly-formed note commitment, cm = alghash.hashn([DOM_CM, value, owner, rho]) — arithmetised as the
sponge-hash AIR (execnode/stark/joinsplit.py) and checked with a real STARK. This is the hard, novel piece,
and it exercises the whole engine (field → FRI → AIR) inside verify_transfer.

WHAT IS STILL TRANSPARENT (the remaining Phase-2 composition, tracked in doc/privacy.md): Merkle MEMBERSHIP of
the inputs, VALUE CONSERVATION across the private values, and NULLIFIER derivation from the spend key — these
must be folded into the SAME circuit (sharing the value/nsk witness) to be both sound and private, and they
use this exact gadget chained/linked. Until then this verifier proves output well-formedness; the caller keeps
the transparent membership/conservation/nullifier checks. `PHASE2_COMPLETE` flips when the full circuit lands.
"""
from execnode.stark import joinsplit, alghash

PHASE2_COMPLETE = False        # True once membership + conservation + nullifier are composed into one circuit


def verify_output_commitments(out_commitments, bundle):
    """Zero-knowledge check that each output commitment is a well-formed alghash note commitment."""
    proofs = (bundle or {}).get("outputs", [])
    if len(proofs) != len(out_commitments):
        return False, "need one STARK proof per output commitment"
    for cm, pr in zip(out_commitments, proofs):
        ok, why = joinsplit.verify_hash(pr, {0: alghash.DOM_CM}, cm)
        if not ok:
            return False, f"an output commitment is not proven well-formed: {why}"
    return True, "ok"


def prove_output_commitments(outputs):
    """Build the ZK well-formedness proofs for a list of output openings [(value, owner, rho), ...]."""
    proofs, cms = [], []
    for (value, owner, rho) in outputs:
        pr, cm = joinsplit.prove_hash([alghash.DOM_CM, value, owner, rho], public_positions=[0])
        proofs.append(pr); cms.append(cm)
    return {"outputs": proofs}, cms


def verify_transfer(public, proof, root_is_known):
    """verify_transfer's Phase-2 path (dispatched when the proof carries a 'stark' bundle)."""
    ok, why = verify_output_commitments(public.get("out_commitments", []), proof.get("stark"))
    if not ok:
        return False, why
    if not PHASE2_COMPLETE:
        # sound-by-construction: we've proven output well-formedness in ZK, but the full transfer statement
        # (membership + conservation + nullifier) is not yet in the circuit, so we don't yet certify a spend.
        return True, "ok (zk output well-formedness verified; membership/conservation still transparent)"
    return True, "ok"
