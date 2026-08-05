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
from execnode.stark import extf
from execnode.stark import (field as F, fri_verify, comp_verify, rowcomp_verify, air_ir,
                            recursive_verify as RV, backend as B, recursion_depth as RD)


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


def _ext_now():
    """Which field this bundle's inner proofs drew their challenges and alphas from — the single authority,
    asked once. Not derived from the AIR: an AIR with no extension-valued constraint still gets extension
    ALPHAS when the proof was produced under an extension challenge field, and treating that program as
    base-valued makes the composition schedule read a tuple as an int."""
    from execnode.stark import stark as _st
    return _st.ext_challenges_active(B.RECURSION)


def _prog_of(item):
    W = RV.public_part(item["proof"])["W"]
    return air_ir.build_program(item["transitions"], W, len(item.get("periodic") or []),
                                item.get("num_challenges", 0), ext_chal=_ext_now())


def prove_hetero(items, num_queries_outer=fri_verify.NUM_QUERIES, out_backend=None, fan_in=None):
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
    # FOLD SHAPE. One prove_fold over ALL K inner FRIs builds a trace that is LINEAR IN K: measured
    # 2026-08-05, the recursion AIR spends ~65,536 rows per folded proof (96 segments x 1088 rows for K=2,
    # i.e. queries x FRI layers x two paths x path levels x 16-row sponge blocks), so
    #   K=2 -> T=131,072   K=4 -> T=262,144   K=8 -> T=524,288.
    # In production that is fatal: 48 exec calls put K in the dozens, T in the millions, and the settle
    # prove blew SETTLE_PROVE_TIMEOUT=1200s at 2.8 GB RSS and still climbing. The "O(1) settlement crypto"
    # in the design note is the VERIFIER's cost (one bundle instead of K proofs); the PROVER's trace was
    # never O(1).
    # `fan_in` folds through recursion_depth.fold_tree instead: each node folds at most `fan_in` proofs, so
    # the per-node trace is bounded by the fan-in rather than by K, memory stays bounded, and the nodes
    # within a level are independent. The root is still ONE proof, so the verifier stays O(1).
    if fan_in and len(fri_proofs) > fan_in:
        tree = RD.fold_tree(fri_proofs, inner_mks=mks, fan_in=int(fan_in), num_queries_inner=nqi,
                            num_queries_outer=num_queries_outer)
        fold, fold_public = None, None
    else:
        tree = None
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
    if tree is not None:
        # The tree carries the prover's `_inner_mks`; verify_hetero REBUILDS those (and every level-0 public)
        # from the inner proofs' public parts before checking it, so nothing prover-supplied is trusted.
        return {"tree": tree, "groups": out_groups, "num_queries_inner": nqi}
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
                return False, (f"an inner FRI public statement failed native verification: "
                               f"{fri_verify.LAST_REJECT}")
            mks.append(_mk)
            # layer0 values follow the CHALLENGE FIELD and may be extension elements; int(v) % P raises on
            # a tuple. The seam is pinned limb-by-limb downstream, so it must arrive unflattened.
            seam.extend(extf.canon(v) for v in pub["layer0"])
        if bundle.get("tree") is not None:
            # TREE FOLD. Same statement as the single fold — every inner FRI is low-degree — established by a
            # root proof plus one re-verification per node. VERIFIER-AUTHORITATIVE, which needs care because
            # recursion_depth.verify_tree reads two things off the tree that the PROVER wrote:
            #   * `_inner_mks`, the level-0 transcript factories, and
            #   * each node's `public` (its declared inner statement + seam).
            # Trusting either would be the forged-intermediate bug class again (eee54fe: verify_bound_epoch
            # trusted a prover-supplied cid_io). So rebuild both here from the inner proofs' PUBLIC parts —
            # the same values this function already derives for the single-fold path — and check the tree
            # against those. Level >= 1 needs no such rebuild: those children are fold proofs the tree itself
            # carries, each re-verified at its own level, and verify_tree cross-checks that a parent's
            # declared inner roots ARE its children's actual FRI roots, so the whole chain is pinned to the
            # level-0 anchor below.
            tree = bundle["tree"]
            levels = tree.get("levels") or []
            if not levels:
                return False, "fold tree has no levels"
            seam_by_item, _at = [], 0
            for p in pubs:
                n = len(p["layer0"])
                seam_by_item.append(seam[_at:_at + n]); _at += n
            lvl0 = []
            for node in levels[0]:
                ch = list(node.get("children") or [])
                if any(not isinstance(ci, int) or not (0 <= ci < len(pubs)) for ci in ch):
                    return False, "fold tree level 0 names an out-of-range inner proof"
                lvl0.append({**node, "public": {
                    "publics": [pubs[ci]["fri_public"] for ci in ch],
                    "num_queries_inner": nqi, "num_queries_outer": num_queries_outer,
                    "seam_lo0": [s for ci in ch for s in seam_by_item[ci]]}})
            tree_v = {**tree, "_inner_mks": mks, "levels": [lvl0] + list(levels[1:])}
            # Only `roots` is read off the level-0 children (the structure cross-check), and these are the
            # verifier's own copies of them.
            anchor = [{"roots": p["fri_public"]["roots"]} for p in pubs]
            okf, whyf = RD.verify_tree(tree_v, anchor, expect_inner=nqi, expect_outer=num_queries_outer)
            if not okf:
                return False, f"fold tree failed: {whyf}"
            # EVERY inner proof must actually be attested. verify_tree checks the nodes it is given; it does
            # not know that level 0 must COVER all K. Without this a prover could omit items from the tree.
            covered = sorted(ci for node in levels[0] for ci in (node.get("children") or []))
            if covered != list(range(len(pubs))):
                return False, "fold tree does not cover every inner proof exactly once"
        else:
            fold_public = {"publics": [p["fri_public"] for p in pubs], "num_queries_inner": nqi,
                           "num_queries_outer": num_queries_outer, "seam_lo0": seam}
            okf, whyf = fri_verify.verify_fold(bundle["fold"], fold_public, mk_transcripts=mks,
                                               expect_inner=nqi, expect_outer=num_queries_outer,
                                               out_backend=out_backend)
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
                                        air.get("num_challenges", 0), ext_chal=_ext_now())
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
        _trace_if_asked()
        return False, f"malformed hetero bundle: {e}"


def _trace_if_asked():
    """A verifier must never raise, so these modules wrap everything in `except Exception` and return a
    reason string. That is correct for consensus and hostile to debugging: the reason names the exception
    but throws away the frame that produced it, and a wiring bug then looks exactly like a corrupt proof.
    NADO_TRACE_RECURSION=1 prints the traceback WITHOUT changing the verdict."""
    import os as _os
    if _os.environ.get("NADO_TRACE_RECURSION"):
        import traceback as _tb
        _tb.print_exc()
