"""
AUTHORITATIVE in-circuit STARK verification (doc/zk-recursion.md §5 step 7) — and the K→1 collapse. Combines
the two verifier-authoritative recursion halves so that verifying ONE recursion bundle is equivalent to running
`stark.verify` on K inner proofs: each committed trace satisfies its AIR AND its composition is low-degree —
with the heavy per-query work (Merkle membership + fold/composition arithmetic) inside the recursion proofs.

  * FRI low-degree half (`fri_verify.prove_fold`/`verify_fold`): every inner proof's composition FRI is
    low-degree, and each query's layer-0 opening is authenticated under the FRI roots.
  * Composition half: the trace values opened at each query row are authenticated under EACH inner proof's own
    commitments and recompute the AIR composition to that query's layer-0 value. COLUMN-committed proofs use
    `comp_verify` (one path per column); ROW-committed proofs (`stark.prove(..., row_commit=True)`) use
    `rowcomp_verify` (ONE path per row tree — the wide execution AIR's mode).
  * The seam that makes the pair authoritative: both halves must agree on the layer-0 composition value at the
    SAME Fiat-Shamir position. The verifier hands the SAME declared value to both — as comp's public target AND
    as a boundary pinning the fold's CLO carry, whose leaf-selector ties it to the Merkle-authenticated leaf.
    A declared value that is not the committed one cannot satisfy the fold's in-circuit membership; a committed
    composition that differs from the trace's cannot satisfy comp. Neither proof can move the seam value.

Verifier-authoritative AND succinct: the verifier re-derives every inner proof's Fiat-Shamir challenges + query
positions (positions come from the transcript, NEVER from the proof) and BUILDS both public statements itself,
reading only each inner proof's small public part — commitment roots, FRI roots/final/pow, geometry, and the
O(queries) declared layer-0 seam values (validated in-circuit as above). With the STRUCTURED periodic
(stark._per_evaluator) in both gadget AIRs, gadget verification cost is O(K · queries · layers) — independent
of both the inner and the recursion trace lengths. (An AIR with its own DENSE periodic columns — the execution
AIR's program/log/args tables — additionally costs their interpolation once per proof, amortized over all
query points.)

TWO-PHASE (LogUp) AIRs: pass `num_challenges`/`num_aux`/`periodic` — the transcript replay absorbs the main
commitment, draws the challenges, absorbs the aux commitment, then draws the constraint α's, mirroring
stark.prove(aux_spec=...). Two-phase requires row commitment (per-column trees would need 2·W paths per point).
"""
from execnode.stark import field as F, stark, backend as B, fri_verify, comp_verify, rowcomp_verify, air_ir
from execnode.stark.transcript import Transcript


def public_part(stark_proof):
    """The SMALL public part of an inner STARK proof — everything the recursive verifier reads. NO trace
    openings, NO Merkle paths: geometry + commitment roots + the FRI public part + the per-query declared
    layer-0 values (the seam; validated in-circuit, see module docstring)."""
    fp = stark_proof["fri"]
    out = {"T": stark_proof["T"], "W": stark_proof["W"], "N": stark_proof["N"],
           "blowup": stark_proof["blowup"],
           "fri_public": {"roots": fp["roots"], "N": fp["N"], "offset": fp["offset"],
                          "blowup": fp["blowup"], "final": fp["final"], "pow": fp.get("pow")},
           "layer0": [int(q["steps"][0]["lo"]) % F.P for q in fp["queries"]]}
    if "row_roots" in stark_proof:
        out["row_roots"] = stark_proof["row_roots"]
    else:
        out["col_roots"] = stark_proof["col_roots"]
    return out


def _fs(pub, n_chal, n_alphas, b):
    """Rebuild the inner STARK's transcript at the FRI start and return (factory, challenges, alphas).
    Single-phase column mode: absorb the W column roots, draw the α's. Row mode: absorb the main row root
    (+ two-phase: draw the LogUp challenges, absorb the aux row root), draw the α's. The factory is what
    fri_verify needs to re-derive the embedded FRI's challenges; challenges/alphas are what comp needs. All
    from the SAME replay, so they are mutually consistent and pinned to the roots."""
    if "row_roots" in pub:
        roots_main, roots_aux = pub["row_roots"][:1], pub["row_roots"][1:]
    else:
        roots_main, roots_aux = pub["col_roots"], []

    def replay(t):
        for r in roots_main:
            t.absorb(r)
        chals = [t.challenge() for _ in range(n_chal)]
        for r in roots_aux:
            t.absorb(r)
        alphas = [t.challenge() for _ in range(n_alphas)]
        return chals, alphas

    def mk():
        t = Transcript("nado-stark", backend=b)
        replay(t)
        return t
    t = Transcript("nado-stark", backend=b)
    chals, alphas = replay(t)
    return mk, chals, alphas


def _geometry(pub):
    N, blowup, T = pub["N"], pub["blowup"], pub["T"]
    wN = F.primitive_root_of_unity(N)            # points computed as OFF·ω^lo — no O(N) domain allocation
    gT = F.primitive_root_of_unity(T)
    last = F.pw(gT, T - 1)
    return N, blowup, T, wN, gT, last


def _point_values(pub, boundaries, alphas, chals, per_evals, lo, layer0):
    """The PUBLIC values of one comp spot-check point at FS-derived position `lo`."""
    N, blowup, T, wN, gT, last = _geometry(pub)
    x = F.mul(stark.OFF, F.pw(wN, lo))
    xT = F.pw(x, T)
    z = F.mul(F.sub(xT, 1), F.inv(F.sub(x, last)))
    bnd = [(int(val) % F.P, F.inv(F.sub(x, F.pw(gT, row)))) for (row, _c, val) in boundaries]
    return {"cur_index": lo, "nxt_index": (lo + blowup) % N,
            "per": [pe(x, xT) for pe in per_evals], "chal": [int(c) % F.P for c in chals],
            "alphas": [int(a) % F.P for a in alphas], "invZ": F.inv(z), "bnd": bnd,
            "layer0": int(layer0) % F.P, "path_len": N.bit_length() - 1}


def _canon_positions(pub, nqi, mk):
    """FS-derive the inner FRI's per-query layer-0 lo positions from the PUBLIC part alone (this also runs the
    native geometry/grind/final-low-degree checks). Returns list of positions or None."""
    canon = fri_verify._canonical_public(pub["fri_public"], nqi, mk)
    if canon is None:
        return None
    return [steps[0][0] for steps in canon["queries"]]


def _as_lists(stark_proofs, boundaries):
    """Normalize (proof | [proofs], boundaries | [boundaries]) to parallel lists."""
    if isinstance(stark_proofs, dict):
        return [stark_proofs], [boundaries]
    proofs = list(stark_proofs)
    if boundaries and isinstance(boundaries[0], (list,)) and boundaries[0] and isinstance(boundaries[0][0], tuple):
        bnds_list = [list(bl) for bl in boundaries]
    elif boundaries and isinstance(boundaries[0], tuple):
        bnds_list = [list(boundaries)] * len(proofs)
    else:
        bnds_list = [list(bl) for bl in boundaries]
    if len(bnds_list) != len(proofs):
        raise ValueError("need one boundary list per proof")
    return proofs, bnds_list


def _per_of(periodic, periodic_list, i):
    """The AIR's public periodic columns for proof i: the shared `periodic`, unless `periodic_list` supplies a
    per-proof list (chained execution segments each carry their own program/args/io tables)."""
    if periodic_list is not None:
        return periodic_list[i] or []
    return periodic or []


def prove(stark_proofs, transitions, boundaries, num_queries_outer=stark.NUM_QUERIES, periodic=None,
          num_challenges=0, num_aux=0, periodic_list=None, comp_points_per_proof=None):
    """Produce ONE recursion bundle {fold, fold_public, comp, comp_public, row_mode} that authoritatively
    re-verifies ALL of `stark_proofs` (each built with backend=RECURSION; column- or row-committed — detected
    from the proof; two-phase AIRs pass num_challenges/num_aux/periodic). `stark_proofs` may be one proof or a
    list of K; `boundaries` correspondingly one boundary list or a per-proof list (the AIR SHAPE — (row, col) —
    must match across proofs; the pinned VALUES may differ, e.g. chained segment seeds). `periodic_list`
    supplies per-proof periodic columns. `comp_points_per_proof` chunks the composition half into one proof per
    that many spot-check points (bounds the recursion trace when K·queries is large); comp/comp_public become
    lists — verification stays succinct per chunk."""
    proofs, bnds_list = _as_lists(stark_proofs, boundaries)
    b = B.RECURSION
    nt = len(transitions)
    W = proofs[0]["W"]
    row_mode = "row_roots" in proofs[0]
    if num_aux and not row_mode:
        raise ValueError("two-phase recursion requires row-committed inner proofs")
    nper0 = len(_per_of(periodic, periodic_list, 0))
    prog = air_ir.build_program(transitions, W, nper0, num_challenges)
    fri_proofs, mks, points = [], [], []
    for pi_, (p, bl) in enumerate(zip(proofs, bnds_list)):
        pub = public_part(p)
        mk, chals, alphas = _fs(pub, num_challenges, nt + len(bl), b)
        fri_proofs.append(p["fri"]); mks.append(mk)
        N, blowup, T, wN, gT, last = _geometry(pub)
        gTp = F.primitive_root_of_unity(T)
        per_evals = [stark._per_evaluator(pc, T, gTp) for pc in _per_of(periodic, periodic_list, pi_)]
        for q, op in zip(p["fri"]["queries"], p["openings"]):
            lo = q["idx"] % (N // 2)
            if lo != op["lo"]:
                raise ValueError("opening index mismatch")
            vals = _point_values(pub, bl, alphas, chals, per_evals, lo, q["steps"][0]["lo"])
            nxt = (lo + blowup) % N
            if row_mode:
                points.append({"cur": op["cur"], "nxt": op["nxt"],
                               "cur_paths": op["cur_paths"], "nxt_paths": op["nxt_paths"],
                               "cur_index": lo, "nxt_index": nxt, "roots": p["row_roots"],
                               "path_lens": [len(pp) for pp in op["cur_paths"]],
                               "per": vals["per"], "chal": vals["chal"], "alphas": vals["alphas"],
                               "invZ": vals["invZ"], "bnd": vals["bnd"], "layer0": vals["layer0"]})
            else:
                cols = op["cols"]
                points.append({"cur": [(cols[c]["cur"], lo, cols[c]["cur_path"]) for c in range(W)],
                               "nxt": [(cols[c]["nxt"], nxt, cols[c]["nxt_path"]) for c in range(W)],
                               "per": vals["per"], "chal": vals["chal"], "alphas": vals["alphas"],
                               "invZ": vals["invZ"], "bnd": vals["bnd"], "layer0": vals["layer0"],
                               "roots": p["col_roots"]})
    nqi = len(fri_proofs[0]["queries"])
    fold, fold_public = fri_verify.prove_fold(fri_proofs, num_queries_inner=nqi,
                                              num_queries_outer=num_queries_outer, mk_transcripts=mks)
    chunks = _chunk(points, comp_points_per_proof)
    comps, comp_pubs = [], []
    for ch in chunks:
        if row_mode:
            c, cp = rowcomp_verify.prove_comp(prog, W, num_aux, bnds_list[0], ch,
                                              num_queries=num_queries_outer)
        else:
            c, cp = comp_verify.prove_comp(prog, W, bnds_list[0], ch, None, num_queries=num_queries_outer)
        comps.append(c); comp_pubs.append(cp)
    one = comp_points_per_proof is None
    return {"fold": fold, "fold_public": fold_public, "comp": comps[0] if one else comps,
            "comp_public": comp_pubs[0] if one else comp_pubs, "row_mode": row_mode}


def _chunk(points, size):
    if size is None or size >= len(points):
        return [points]
    return [points[i:i + size] for i in range(0, len(points), size)]


def verify(stark_publics, transitions, boundaries, bundle, num_queries_outer=stark.NUM_QUERIES, periodic=None,
           num_challenges=0, num_aux=0, periodic_list=None, comp_points_per_proof=None,
           num_queries_inner=None):
    """AUTHORITATIVE verification of K inner proofs from their PUBLIC PARTS alone (`public_part(proof)` — full
    proofs are also accepted and reduced). Re-derives every proof's Fiat-Shamir challenges + query positions;
    verifies the FRI low-degree half against a verifier-built schedule (with the layer-0 seam values pinned as
    in-circuit-validated boundaries) at protocol query strength; builds comp's public statement itself and
    verifies the composition half against IT; cross-checks the fold covers exactly the K proofs' FRI roots.
    All passing ⇒ every committed trace satisfies the AIR and its composition is low-degree (= K× stark.verify),
    proven via ONE bundle. Returns (ok, reason)."""
    try:
        pubs_in, bnds_list = _as_lists(stark_publics, boundaries)
        pubs = [p if "fri_public" in p else public_part(p) for p in pubs_in]
        b = B.RECURSION
        nt = len(transitions)
        W = pubs[0]["W"]
        row_mode = "row_roots" in pubs[0]
        if num_aux and not row_mode:
            return False, "two-phase recursion requires row-committed inner proofs"
        nper0 = len(_per_of(periodic, periodic_list, 0))
        prog = air_ir.build_program(transitions, W, nper0, num_challenges)
        nqi = len(pubs[0]["layer0"])
        # the inner query count IS each proof's soundness — a caller with a protocol policy pins it here,
        # so a prover cannot present weaker (fewer-query) inner proofs than the protocol demands.
        if num_queries_inner is not None and nqi != num_queries_inner:
            return False, f"inner query count {nqi} != verifier policy {num_queries_inner}"
        mks, points_public, seam = [], [], []
        for pi_, (pub, bl) in enumerate(zip(pubs, bnds_list)):
            if pub["W"] != W:
                return False, "inner proofs must share the AIR shape"
            if len(pub["layer0"]) != nqi:
                return False, "inner proofs must share the query count"
            mk, chals, alphas = _fs(pub, num_challenges, nt + len(bl), b)
            mks.append(mk)
            # AUTHORITATIVE POSITIONS + native FRI checks: query positions are FS-derived from the public part,
            # never read from the proof — comp binds the trace at the SAME positions the fold authenticates.
            pos = _canon_positions(pub, nqi, mk)
            if pos is None:
                return False, "an inner FRI public statement failed native verification"
            T = pub["T"]
            gTp = F.primitive_root_of_unity(T)
            per_evals = [stark._per_evaluator(pc, T, gTp) for pc in _per_of(periodic, periodic_list, pi_)]
            for lo, l0 in zip(pos, pub["layer0"]):
                vals = _point_values(pub, bl, alphas, chals, per_evals, lo, l0)
                if row_mode:
                    vals["roots"] = pub["row_roots"]
                    vals["path_lens"] = [pub["N"].bit_length() - 1] * len(pub["row_roots"])
                else:
                    vals["roots"] = [[int(v) % F.P for v in r] for r in pub["col_roots"]]
                points_public.append(vals)
                seam.append(int(l0) % F.P)

        # (1) FRI low-degree half — the verifier rebuilds the schedule (challenges, positions, finals) and pins
        # the declared layer-0 seam values as CLO boundaries: in-circuit membership validates them.
        fold_public = {"publics": [pub["fri_public"] for pub in pubs], "num_queries_inner": nqi,
                       "num_queries_outer": num_queries_outer, "seam_lo0": seam}
        okf, whyf = fri_verify.verify_fold(bundle["fold"], fold_public, mk_transcripts=mks,
                                           expect_inner=nqi, expect_outer=num_queries_outer)
        if not okf:
            return False, f"FRI low-degree half failed: {whyf}"

        # (2) composition half — verifier BUILDS comp's public (positions, α/challenges, periodic values at the
        # point, invZ, boundary dens, per-point roots, layer-0 = the seam), so nothing in the composition
        # statement is taken on the prover's word. Chunked bundles verify chunk by chunk against the SAME
        # verifier-built point list, split identically.
        one = comp_points_per_proof is None
        comps = [bundle["comp"]] if one else list(bundle["comp"])
        chunks = _chunk(points_public, comp_points_per_proof)
        if len(comps) != len(chunks):
            return False, "composition chunk count mismatch"
        for c, ch in zip(comps, chunks):
            if row_mode:
                auth_public = {"points_public": ch, "num_queries": num_queries_outer}
                okc, whyc = rowcomp_verify.verify_comp(c, prog, W, num_aux, bnds_list[0], auth_public)
            else:
                auth_public = comp_verify.public_from_point_publics(ch, None, None, num_queries_outer)
                okc, whyc = comp_verify.verify_comp(c, prog, W, bnds_list[0], auth_public)
            if not okc:
                return False, f"composition half failed: {whyc}"
        return True, "authoritatively verified (K proofs: FRI low-degree + composition binding, verifier-built)"
    except Exception as e:
        return False, f"malformed recursion bundle: {e}"
