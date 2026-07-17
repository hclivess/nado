"""
HETEROGENEOUS recursion (doc/zk-recursion.md §5b/§5c) — fold proofs of DIFFERENT AIRs into ONE bundle.

recursive_verify folds K proofs that SHARE an AIR (the segment path). The O(1) settlement assembly and the
authoritative-depth tree both need to fold proofs of DIFFERENT AIRs together with a SHARED transcript — e.g. the
exec proof + the io-replay proofs + a binding proof, or a bundle's fold-AIR proof + its comp-AIR proof. This does
that: ONE FRI fold over every proof's FRI (the fold is AIR-agnostic — it only folds low-degree), and ONE
composition proof per DISTINCT AIR group (each group re-verified against its own program). A verifier checks the
single fold + the per-group comps — all from the proofs' public parts — so the whole heterogeneous set is
re-verified as one object, and the shared fold transcript is what a cross-proof (fingerprint/multiset) binding
rides on (fold-layer binding, §5c piece 2).

Handles BOTH commitment modes per group: single-phase COLUMN (membership/update/binding proofs, comp_verify) and
ROW-committed TWO-PHASE (the W=106 exec AIR + any LogUp AIR, rowcomp_verify with num_aux) — an item declares its
own {transitions, boundaries, periodic, num_challenges, num_aux}; items sharing an AIR (transitions identity)
form one group and must share the mode. Verifier-authoritative + succinct exactly as recursive_verify: nothing
constraint-shaped is read from a proof.
"""
from execnode.stark import (field as F, fri_verify, comp_verify, rowcomp_verify, air_ir,
                            recursive_verify as RV, backend as B)


def _is_row(pub):
    return "row_roots" in pub


def _points_of(item):
    """The comp spot-check points for ONE proof — row-mode (whole-row openings + row roots) or column-mode
    (per-column openings), the same construction recursive_verify does per proof. Two-phase AIRs pass
    num_challenges/num_aux; _fs replays the two-phase transcript (main root → challenges → aux root)."""
    from execnode.stark import stark
    proof = item["proof"]
    transitions, boundaries = item["transitions"], item["boundaries"]
    periodic = item.get("periodic")
    num_challenges = item.get("num_challenges", 0)
    b = B.RECURSION
    pub = RV.public_part(proof)
    row_mode = _is_row(pub)
    nt = len(transitions)
    _mk, chals, alphas = RV._fs(pub, num_challenges, nt + len(boundaries), b)
    N, blowup, T, wN, gT, last = RV._geometry(pub)
    gTp = F.primitive_root_of_unity(T)
    per_evals = [stark._per_evaluator(pc, T, gTp) for pc in (periodic or [])]
    W = pub["W"]
    pts = []
    for q, op in zip(proof["fri"]["queries"], proof["openings"]):
        lo = q["idx"] % (N // 2)
        nxt = (lo + blowup) % N
        vals = RV._point_values(pub, boundaries, alphas, chals, per_evals, lo, q["steps"][0]["lo"])
        if row_mode:
            pts.append({"cur": op["cur"], "nxt": op["nxt"],
                        "cur_paths": op["cur_paths"], "nxt_paths": op["nxt_paths"],
                        "cur_index": lo, "nxt_index": nxt, "roots": proof["row_roots"],
                        "path_lens": [len(pp) for pp in op["cur_paths"]],
                        "per": vals["per"], "chal": vals["chal"], "alphas": vals["alphas"],
                        "invZ": vals["invZ"], "bnd": vals["bnd"], "layer0": vals["layer0"]})
        else:
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
    """`items` = [{proof, transitions, boundaries[, periodic, num_challenges, num_aux]}], all RECURSION-committed
    and sharing the inner FRI query count. Each item may be single-phase column OR two-phase row (declared by its
    proof + num_aux). Returns {fold, fold_public, groups, num_queries_inner}: ONE fold over all FRIs + one comp
    per distinct-AIR group (row → rowcomp_verify with num_aux, column → comp_verify)."""
    b = B.RECURSION
    nqi = len(items[0]["proof"]["fri"]["queries"])
    fri_proofs, mks = [], []
    for it in items:
        pub = RV.public_part(it["proof"])
        if len(it["proof"]["fri"]["queries"]) != nqi:
            raise ValueError("hetero fold needs a shared inner query count")
        _mk, _c, _a = RV._fs(pub, it.get("num_challenges", 0), len(it["transitions"]) + len(it["boundaries"]), b)
        fri_proofs.append(it["proof"]["fri"]); mks.append(_mk)
    fold, fold_public = fri_verify.prove_fold(fri_proofs, num_queries_inner=nqi,
                                              num_queries_outer=num_queries_outer, mk_transcripts=mks,
                                              out_backend=out_backend)
    # group items by their AIR (transitions identity) — one comp per distinct AIR; items in a group share mode
    groups, order = {}, []
    for idx, it in enumerate(items):
        key = id(it["transitions"])
        if key not in groups:
            groups[key] = {"item": it, "idxs": [], "points": []}
            order.append(key)
        groups[key]["idxs"].append(idx)
        groups[key]["points"].extend(_points_of(it))
    out_groups = []
    for key in order:
        g = groups[key]
        it = g["item"]
        prog = _prog_of(it)
        W = RV.public_part(it["proof"])["W"]
        if _is_row(RV.public_part(it["proof"])):
            c, cp = rowcomp_verify.prove_comp(prog, W, it.get("num_aux", 0), it["boundaries"], g["points"],
                                              num_queries=num_queries_outer, out_backend=out_backend)
        else:
            c, cp = comp_verify.prove_comp(prog, W, it["boundaries"], g["points"], None,
                                           num_queries=num_queries_outer, out_backend=out_backend)
        out_groups.append({"idxs": g["idxs"], "comp": c})
    return {"fold": fold, "fold_public": fold_public, "groups": out_groups, "num_queries_inner": nqi}


def verify_hetero(publics, item_airs, bundle, num_queries_outer=fri_verify.NUM_QUERIES,
                  num_queries_inner=None, out_backend=None):
    """Verify a heterogeneous bundle. `publics[i]` = public_part(proof_i); `item_airs[i]` =
    {transitions, boundaries[, periodic, num_challenges, num_aux]} for proof i (same order as prove_hetero).
    Checks the ONE fold covers every proof's FRI (at the verifier's inner-query policy) and each per-AIR-group
    comp re-verifies its proofs (row → rowcomp, column → comp). Returns (ok, reason)."""
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
        from execnode.stark import stark
        for key, gb in zip(order, bundle["groups"]):
            g = groups[key]
            if g["idxs"] != gb["idxs"]:
                return False, "group membership mismatch"
            air = g["air"]
            row_mode = _is_row(pubs[g["idxs"][0]])
            W = pubs[g["idxs"][0]]["W"]
            prog = air_ir.build_program(air["transitions"], W, len(air.get("periodic") or []),
                                        air.get("num_challenges", 0))
            pts_public = []
            for idx in g["idxs"]:
                pub = pubs[idx]
                # per-ITEM boundaries + periodic (values differ across a group — e.g. each merkle-update pins its
                # own roots/DIRs, each slot_key its own inputs; only the boundary/periodic SHAPE is shared, which
                # is what the group's program/comp structure uses). Mirrors prove_hetero's _points_of(it).
                iair = item_airs[idx]
                if _is_row(pub) != row_mode or pub["W"] != W:
                    return False, "group members must share the AIR mode/shape"
                if len(iair["boundaries"]) != len(air["boundaries"]) \
                        or len(iair.get("periodic") or []) != len(air.get("periodic") or []):
                    return False, "group members must share the AIR shape (boundary/periodic count)"
                _mk, chals, alphas = RV._fs(pub, iair.get("num_challenges", 0),
                                            len(iair["transitions"]) + len(iair["boundaries"]), b)
                positions = RV._canon_positions(pub, nqi, _mk)
                T = pub["T"]; gTp = F.primitive_root_of_unity(T)
                per_evals = [stark._per_evaluator(pc, T, gTp) for pc in (iair.get("periodic") or [])]
                for lo, l0 in zip(positions, pub["layer0"]):
                    vals = RV._point_values(pub, iair["boundaries"], alphas, chals, per_evals, lo, l0)
                    if row_mode:
                        vals["roots"] = pub["row_roots"]
                        vals["path_lens"] = [pub["N"].bit_length() - 1] * len(pub["row_roots"])
                    else:
                        vals["roots"] = [[int(v) % F.P for v in r] for r in pub["col_roots"]]
                    pts_public.append(vals)
            if row_mode:
                auth_public = {"points_public": pts_public, "num_queries": num_queries_outer}
                okc, whyc = rowcomp_verify.verify_comp(gb["comp"], prog, W, air.get("num_aux", 0),
                                                       air["boundaries"], auth_public, out_backend=out_backend)
            else:
                auth_public = comp_verify.public_from_point_publics(pts_public, None, None, num_queries_outer)
                okc, whyc = comp_verify.verify_comp(gb["comp"], prog, W, air["boundaries"], auth_public,
                                                    out_backend=out_backend)
            if not okc:
                return False, f"group comp failed: {whyc}"
        return True, "heterogeneous set re-verified (one fold + per-AIR comps, row & column)"
    except Exception as e:
        return False, f"malformed hetero bundle: {e}"
