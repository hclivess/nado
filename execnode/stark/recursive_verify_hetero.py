"""
HETEROGENEOUS recursion (doc/zk-recursion.md §5b/§5c) — fold proofs of DIFFERENT AIRs into ONE bundle.

recursive_verify folds K proofs that SHARE an AIR (the segment path). The O(1) settlement assembly and the
authoritative-depth tree both need to fold proofs of DIFFERENT AIRs together with a SHARED transcript — e.g. the
exec proof + the io-replay proofs + a binding proof, or a bundle's fold-AIR proof + its comp-AIR proof. This does
that: ONE FRI fold over every proof's FRI (the fold is AIR-agnostic — it only folds low-degree), and ONE
composition proof per DISTINCT AIR group (each group re-verified against its own program). A verifier checks the
single fold + the per-group comps — all from the proofs' public parts — so the whole heterogeneous set is
re-verified as one object, and the shared fold transcript is what a cross-proof (multiset-eq) binding rides on.

Single-phase COLUMN mode (what the recursion GADGETS + the membership/update/binding proofs use); all proofs must
share the inner FRI query count (the fold requires it). Verifier-authoritative + succinct exactly as
recursive_verify: nothing constraint-shaped is read from a proof.
"""
from execnode.stark import (field as F, fri_verify, comp_verify, air_ir, recursive_verify as RV, backend as B)


def _points_of(proof, transitions, boundaries, periodic, num_challenges):
    """The column-mode comp spot-check points for ONE proof (its trace openings + the verifier-built public
    values at each FS query position) — the same construction recursive_verify.prove does per proof."""
    from execnode.stark import stark
    pub = RV.public_part(proof)
    b = B.RECURSION
    nt = len(transitions)
    _mk, chals, alphas = RV._fs(pub, num_challenges, nt + len(boundaries), b)
    N, blowup, T, wN, gT, last = RV._geometry(pub)
    gTp = F.primitive_root_of_unity(T)
    per_evals = [stark._per_evaluator(pc, T, gTp) for pc in (periodic or [])]
    pts = []
    for q, op in zip(proof["fri"]["queries"], proof["openings"]):
        lo = q["idx"] % (N // 2)
        nxt = (lo + blowup) % N
        W = pub["W"]
        vals = RV._point_values(pub, boundaries, alphas, chals, per_evals, lo, q["steps"][0]["lo"])
        cols = op["cols"]
        pts.append({"cur": [(cols[c]["cur"], lo, cols[c]["cur_path"]) for c in range(W)],
                    "nxt": [(cols[c]["nxt"], nxt, cols[c]["nxt_path"]) for c in range(W)],
                    "per": vals["per"], "chal": vals["chal"], "alphas": vals["alphas"],
                    "invZ": vals["invZ"], "bnd": vals["bnd"], "layer0": vals["layer0"],
                    "roots": proof["col_roots"]})
    return pts


def _prog_of(item):
    W = RV.public_part(item["proof"])["W"]
    return air_ir.build_program(item["transitions"], W, len(item.get("periodic") or []),
                                item.get("num_challenges", 0))


def prove_hetero(items, num_queries_outer=fri_verify.NUM_QUERIES, out_backend=None):
    """`items` = [{proof, transitions, boundaries[, periodic]}], single-phase column, all RECURSION-committed and
    sharing the inner FRI query count. Returns {fold, fold_public, groups, num_queries_inner}: ONE fold over all
    FRIs + one comp per distinct-AIR group (keyed by the item's index list)."""
    b = B.RECURSION
    nqi = len(items[0]["proof"]["fri"]["queries"])
    fri_proofs, mks, seam = [], [], []
    for it in items:
        pub = RV.public_part(it["proof"])
        if len(it["proof"]["fri"]["queries"]) != nqi:
            raise ValueError("hetero fold needs a shared inner query count")
        _mk, _c, _a = RV._fs(pub, it.get("num_challenges", 0), len(it["transitions"]) + len(it["boundaries"]), b)
        fri_proofs.append(it["proof"]["fri"]); mks.append(_mk)
        seam.extend(int(q["steps"][0]["lo"]) % F.P for q in it["proof"]["fri"]["queries"])
    fold, fold_public = fri_verify.prove_fold(fri_proofs, num_queries_inner=nqi,
                                              num_queries_outer=num_queries_outer, mk_transcripts=mks,
                                              out_backend=out_backend)
    # group items by their AIR (transitions identity) — one comp per distinct AIR
    groups, order = {}, []
    for idx, it in enumerate(items):
        key = id(it["transitions"])
        if key not in groups:
            groups[key] = {"item": it, "idxs": [], "points": []}
            order.append(key)
        groups[key]["idxs"].append(idx)
        groups[key]["points"].extend(_points_of(it["proof"], it["transitions"], it["boundaries"],
                                                 it.get("periodic"), it.get("num_challenges", 0)))
    out_groups = []
    for key in order:
        g = groups[key]
        prog = _prog_of(g["item"])
        W = RV.public_part(g["item"]["proof"])["W"]
        c, cp = comp_verify.prove_comp(prog, W, g["item"]["boundaries"], g["points"], None,
                                       num_queries=num_queries_outer, out_backend=out_backend)
        out_groups.append({"idxs": g["idxs"], "comp": c})
    return {"fold": fold, "fold_public": fold_public, "groups": out_groups, "num_queries_inner": nqi}


def verify_hetero(publics, item_airs, bundle, num_queries_outer=fri_verify.NUM_QUERIES,
                  num_queries_inner=None, out_backend=None):
    """Verify a heterogeneous bundle. `publics[i]` = public_part(proof_i); `item_airs[i]` =
    {transitions, boundaries[, periodic]} for proof i (same order as prove_hetero). Checks the ONE fold covers
    every proof's FRI (at the verifier's inner-query policy) and each per-AIR-group comp re-verifies its proofs.
    Returns (ok, reason)."""
    try:
        b = B.RECURSION
        nqi = num_queries_inner if num_queries_inner is not None else fri_verify.NUM_QUERIES
        pubs = [p if "fri_public" in p else RV.public_part(p) for p in publics]
        if any(len(p["layer0"]) != nqi for p in pubs):
            return False, "inner query count != verifier policy"
        mks, seam = [], []
        for pub, air in zip(pubs, item_airs):
            _mk, _c, _a = RV._fs(pub, air.get("num_challenges", 0),
                                 len(air["transitions"]) + len(air["boundaries"]), b)
            pos = RV._canon_positions(pub, nqi, _mk)
            if pos is None:
                return False, "an inner FRI public statement failed native verification"
            mks.append(_mk)
            seam.extend(int(v) % F.P for v in pub["layer0"])
        fold_public = {"publics": [p["fri_public"] for p in pubs], "num_queries_inner": nqi,
                       "num_queries_outer": num_queries_outer, "seam_lo0": seam}
        okf, whyf = fri_verify.verify_fold(bundle["fold"], fold_public, mk_transcripts=mks,
                                           expect_inner=nqi, expect_outer=num_queries_outer, out_backend=out_backend)
        if not okf:
            return False, f"fold failed: {whyf}"
        # regroup by AIR (same identity grouping the prover used) and verify each group's comp
        groups, order = {}, []
        for idx, air in enumerate(item_airs):
            key = id(air["transitions"])
            if key not in groups:
                groups[key] = {"air": air, "idxs": []}
                order.append(key)
            groups[key]["idxs"].append(idx)
        if len(order) != len(bundle["groups"]):
            return False, "group count mismatch"
        for key, gb in zip(order, bundle["groups"]):
            g = groups[key]
            if g["idxs"] != gb["idxs"]:
                return False, "group membership mismatch"
            air = g["air"]
            W = pubs[g["idxs"][0]]["W"]
            prog = air_ir.build_program(air["transitions"], W, len(air.get("periodic") or []),
                                        air.get("num_challenges", 0))
            from execnode.stark import stark
            pts_public = []
            for idx in g["idxs"]:
                pub = pubs[idx]
                _mk, chals, alphas = RV._fs(pub, air.get("num_challenges", 0),
                                            len(air["transitions"]) + len(air["boundaries"]), b)
                positions = RV._canon_positions(pub, nqi, _mk)
                T = pub["T"]; gTp = F.primitive_root_of_unity(T)
                per_evals = [stark._per_evaluator(pc, T, gTp) for pc in (air.get("periodic") or [])]
                for lo, l0 in zip(positions, pub["layer0"]):
                    vals = RV._point_values(pub, air["boundaries"], alphas, chals, per_evals, lo, l0)
                    vals["roots"] = [[int(v) % F.P for v in r] for r in pub["col_roots"]]
                    pts_public.append(vals)
            auth_public = comp_verify.public_from_point_publics(pts_public, None, None, num_queries_outer)
            okc, whyc = comp_verify.verify_comp(gb["comp"], prog, W, air["boundaries"], auth_public,
                                                out_backend=out_backend)
            if not okc:
                return False, f"group comp failed: {whyc}"
        return True, "heterogeneous set re-verified (one fold + per-AIR comps)"
    except Exception as e:
        return False, f"malformed hetero bundle: {e}"
