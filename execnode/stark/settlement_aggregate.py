"""
SETTLEMENT single-bundle AGGREGATION (doc/zk-recursion.md §5c) — collapse the O(#io) settlement crypto to O(1).

The bound-epoch chain leaves two O(#io) proof families: one merkle-update per storage write (io_replay) and one
slot_key derivation per storage entry (state_io_tie/slot_key_air). Both are single-phase RECURSION-committed
column proofs, so recursive_verify_hetero folds ALL of them — DIFFERENT AIRs, per-item boundaries/periodic — into
ONE bundle: one FRI fold + one composition per distinct AIR. A verifier then re-establishes every merkle-update
AND every position derivation by checking that single bundle from the proofs' public parts — the K→1 step that
makes the settlement crypto O(1). (The exec proof and the constant number of io_bind DEEP evals verify alongside;
they don't scale with #io.)
"""
from execnode.stark import (merkle_update as MU, slot_key_air as SK, recursive_verify_hetero as RVH,
                            recursive_verify as RV, fri_verify)


def _items(replay_steps, positions, depth):
    """The hetero items: every merkle-update (shared MU AIR, per-step boundaries/roots) + every slot_key
    derivation (shared SK AIR, per-entry inputs). One transitions object per family ⇒ two comp groups."""
    MU_T = MU._transitions()
    SK_T = SK._all_transitions()
    items = []
    for s in replay_steps:
        p = s["proof"]
        items.append({"proof": p, "transitions": MU_T,
                      "boundaries": MU._boundaries(s["old"], s["new"], s["pre_root"], s["post_root"], s["dirs"], depth),
                      "periodic": MU._periodic(p["T"], depth)})
    for pos in positions:
        p = pos["proof"]; T = p["T"]; els = SK.elements(pos["cid"], pos["slot"])
        items.append({"proof": p, "transitions": SK_T,
                      "boundaries": SK._boundaries(T, els, pos["digest"]),
                      "periodic": SK._full_periodic(els, T)})
    return items


def prove_settlement_bundle(replay_steps, positions, depth, num_queries_outer=fri_verify.NUM_QUERIES):
    """Fold every merkle-update + every slot_key derivation into ONE recursion bundle. All inner proofs must
    share the FRI query count + trace length (same depth ⇒ same MU trace length; slot_key is fixed). Returns
    (bundle, pubs, airs) — the bundle plus the public parts + per-item AIRs the verifier re-checks against."""
    items = _items(replay_steps, positions, depth)
    if not items:
        return None, [], []
    bundle = RVH.prove_hetero(items, num_queries_outer=num_queries_outer)
    pubs = [RV.public_part(it["proof"]) for it in items]
    airs = [{"transitions": it["transitions"], "boundaries": it["boundaries"], "periodic": it["periodic"]}
            for it in items]
    return bundle, pubs, airs


def verify_settlement_bundle(bundle, pubs, airs, num_queries_inner, num_queries_outer=fri_verify.NUM_QUERIES):
    """Verify the ONE bundle re-establishes all K merkle-updates + all K slot_key derivations. Returns
    (ok, reason). This is the O(1) crypto — one fold + two per-AIR comps, regardless of #io."""
    if bundle is None:
        return (not pubs), "empty settlement bundle"
    return RVH.verify_hetero(pubs, airs, bundle, num_queries_outer=num_queries_outer,
                             num_queries_inner=num_queries_inner)
