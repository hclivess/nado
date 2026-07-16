"""
Recursion DEPTH — AUTHORITATIVE (doc/zk-recursion.md §5b): a recursion bundle re-verified INSIDE a recursion
bundle. This is the component that collapses the fold/comp CRYPTO of a settlement bundle to a fixed-size root.

The LOW-DEGREE fold tree (recursion_depth) re-verifies EVERY node — a plain fold only attests its own trace is
low-degree, NOT that the children it folded VERIFIED. The AUTHORITATIVE level closes that: it binds BOTH halves
of a recursion bundle — the FRI fold AND the COMPOSITION — by RE-VERIFYING the bundle's fold_0 and comp_0 proofs
inside a NEW recursion bundle (recursive_verify). The resulting root {rv_fold, rv_comps} attests "the level-below
bundle VERIFIES," and checking the root's two constant-size recursion proofs is INDEPENDENT of K.

INPUT: a bundle from recursive_verify.prove(K segments, out_backend=backend.RECURSION) — {fold_0, comp_0} both
rleaf/rnode-committed (hence themselves recursively verifiable). prove_level produces the authoritative root;
verify_level checks it against the SAME statement, reconstructed verifier-authoritatively (fri_verify.fold_air /
comp_verify.comp_air / rowcomp_verify.comp_air rebuild EXACTLY the schedules verify_fold / verify_comp build —
never the prover's word). Soundness is inherited (§6): a forged root ⇒ a forged fold/comp proof = a broken
alghash2 collision or FRI.

⚠️ SCOPE — this is O(1) for the fold/comp CRYPTO, NOT yet O(1) settlement verify. verify_level still calls _prep,
which reconstructs the K-segment schedule (fold_air runs _canonical_public per segment; comp_air rebuilds the
K·queries point schedule) — that is O(K), and it is the SAME statement-rebuild verify_settlement_o1 already does.
So this level replaces the (smaller) K-dependent fold/comp proof verification with a constant-size root, but the
DOMINANT settlement costs — the io-replay to the state root and the per-segment statement rebuild — remain O(K).
TRUE O(1) settlement additionally needs, all IN-CIRCUIT (doc/zk-recursion.md §5b, the remaining frontier):
  (a) state-root BINDING — bind the segment traces to pre/post roots inside the proof (no io replay at verify);
  (b) the statement rebuild proven in-circuit against a COMMITMENT to the epoch's calls (no O(K) schedule rebuild);
  (c) the calls commitment as the single O(1) public input.
This module is the fold/comp-aggregation building block those compose with (and the cross-epoch aggregator).
"""
from execnode.stark import fri_verify, comp_verify, rowcomp_verify, recursive_verify as RV, air_ir, backend as B


def _prep(bundle, stark_publics, transitions, boundaries, W, num_queries_inner,
          periodic, num_challenges, num_aux, periodic_list):
    """Reconstruct — verifier-authoritatively, from the bundle's PUBLIC parts + the inner AIR — the fold proof's
    AIR and each comp proof's AIR (the same schedules verify_fold / verify_comp build). Returns
    (row_mode, (fold_proof, fold_air), [(comp_proof, comp_air), ...]) where each *_air is (transitions,
    boundaries, periodic). Shared by prove_level and verify_level so both bind the IDENTICAL statement."""
    row_mode = bundle["row_mode"]
    pubs, bnds_list = RV._as_lists(stark_publics, boundaries)
    pubs = [p if "fri_public" in p else RV.public_part(p) for p in pubs]
    nt = len(transitions)
    # the inner FRI transcript factories the fold used — one per segment, rebuilt exactly as recursive_verify does
    mks = [RV._fs(pub, num_challenges, nt + len(bl), B.RECURSION)[0] for pub, bl in zip(pubs, bnds_list)]
    ft, fb, fp = fri_verify.fold_air(bundle["fold_public"], mks, num_queries_inner)
    fold_item = (bundle["fold"], (ft, fb, fp))

    nper0 = len(RV._per_of(periodic, periodic_list, 0))
    prog = air_ir.build_program(transitions, W, nper0, num_challenges)
    comps = bundle["comp"] if isinstance(bundle["comp"], list) else [bundle["comp"]]
    comp_pubs = bundle["comp_public"] if isinstance(bundle["comp_public"], list) else [bundle["comp_public"]]
    comp_items = []
    for c, cpub in zip(comps, comp_pubs):
        if row_mode:
            ct, cb, cp, _ = rowcomp_verify.comp_air(prog, W, num_aux, bnds_list[0], cpub)
        else:
            ct, cb, cp, _ = comp_verify.comp_air(prog, W, bnds_list[0], cpub)
        comp_items.append((c, (ct, cb, cp)))
    return row_mode, fold_item, comp_items


def prove_level(bundle, stark_publics, transitions, boundaries, W, num_queries_inner,
                num_queries_level=fri_verify.NUM_QUERIES, periodic=None, num_challenges=0, num_aux=0,
                periodic_list=None):
    """ONE authoritative depth level over a RECURSION-committed `bundle` (recursive_verify.prove with
    out_backend=backend.RECURSION). Recursively RE-VERIFIES the bundle's fold + comp proofs. Returns the root
    {rv_fold, rv_comps, row_mode}. `num_queries_inner` = the segments' query count (the fold's inner strength);
    `num_queries_level` = this level's own outer query count."""
    row_mode, (fold_proof, (ft, fb, fp)), comp_items = _prep(
        bundle, stark_publics, transitions, boundaries, W, num_queries_inner,
        periodic, num_challenges, num_aux, periodic_list)
    rv_fold = RV.prove([fold_proof], ft, fb, periodic=fp, num_queries_outer=num_queries_level)
    rv_comps = [RV.prove([c], ct, cb, periodic=cp, num_queries_outer=num_queries_level)
                for (c, (ct, cb, cp)) in comp_items]
    return {"rv_fold": rv_fold, "rv_comps": rv_comps, "row_mode": row_mode}


def verify_level(root, bundle, stark_publics, transitions, boundaries, W, num_queries_inner,
                 num_queries_level=fri_verify.NUM_QUERIES, periodic=None, num_challenges=0, num_aux=0,
                 periodic_list=None):
    """O(1) verification of an authoritative depth root: checks that `root` attests the bundle's fold + comp
    proofs verify — each via one recursive_verify against a verifier-BUILT schedule (the same _prep the prover
    used). All passing ⇒ the bundle verifies (= every segment STARK verifies), established by a fixed-size root
    whose cost is INDEPENDENT of K. Returns (ok, reason). The fold/comp proofs' OWN query count (the depth
    level's inner strength) is the bundle's num_queries_outer, pinned here so a weaker inner proof is rejected."""
    try:
        row_mode, (fold_proof, (ft, fb, fp)), comp_items = _prep(
            bundle, stark_publics, transitions, boundaries, W, num_queries_inner,
            periodic, num_challenges, num_aux, periodic_list)
        fold_nqi = bundle["fold_public"]["num_queries_outer"]
        okf, whyf = RV.verify([RV.public_part(fold_proof)], ft, fb, root["rv_fold"],
                              num_queries_outer=num_queries_level, num_queries_inner=fold_nqi)
        if not okf:
            return False, f"authoritative fold level failed: {whyf}"
        if len(root["rv_comps"]) != len(comp_items):
            return False, "comp level count mismatch"
        for rv_c, (c, (ct, cb, cp)) in zip(root["rv_comps"], comp_items):
            comp_nqi = len(RV.public_part(c)["layer0"])
            okc, whyc = RV.verify([RV.public_part(c)], ct, cb, rv_c,
                                  num_queries_outer=num_queries_level, num_queries_inner=comp_nqi)
            if not okc:
                return False, f"authoritative comp level failed: {whyc}"
        return True, "authoritative depth root verified (bundle re-verified in O(1): fold + comp)"
    except Exception as e:
        return False, f"malformed authoritative depth root: {e}"
