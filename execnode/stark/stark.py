"""
STARK over an AIR — prove that an execution TRACE satisfies its constraints, post-quantum, no trusted setup
(doc/privacy.md). This is the layer between "a computation" and FRI.

An AIR here is:
  * a TRACE: T rows × W columns (T a power of two) — the registers of the computation over time;
  * optional PERIODIC columns: fixed PUBLIC per-row values (round constants, selector flags) the verifier can
    recompute itself — this is what lets one uniform constraint behave differently on different rows (e.g. a
    hash round vs a "inject the next Merkle sibling" step), which the shielded-pool circuit needs;
  * TRANSITION constraints c(cur_row, next_row, periodic_row) = 0, required on every step;
  * BOUNDARY constraints (row, col, value) — pinned inputs/outputs.

The STARK: interpolate each column to degree<T, evaluate on a BLOWUP·T coset and Merkle-commit it; form the
COMPOSITION polynomial = a Fiat-Shamir-random combination of every constraint DIVIDED by the polynomial that
vanishes where it must hold — low-degree IFF every constraint holds — prove that with FRI, and spot-check at
FRI's own query points that the committed composition equals the quotient recomputed from the committed trace.
Cheating requires a non-low-degree quotient (FRI rejects) or a trace/composition mismatch (spot-checks reject).
Soundness assumption: BLAKE2b collision-resistance.
"""
import os
from execnode.stark import field as F, merkle, fri, backend as _backend
from execnode.stark.transcript import Transcript
from execnode.stark.fri import NUM_QUERIES

OFF = F.GENERATOR                    # LDE coset shift (disjoint from the trace subgroup)

# H-7: a hard ceiling on the trace length a proof may claim. N (= blowup·T) is read from the proof and fed to
# F.domain(N) BEFORE any FRI/query check, so an unbounded N is an unauthenticated single-request OOM
# (N = 2^32 builds a ~34 GB list). Real shielded circuits use T ≈ 1024, so 2^17 is ~128× headroom and caps the
# LDE at ~2^21 elements — generous for legit proofs, fatal to the OOM.
MAX_TRACE_ROWS = 1 << 17
MAX_COLUMNS = 256


def _next_pow2(x):
    """Smallest power of two ≥ x."""
    p = 1
    while p < x:
        p <<= 1
    return p


def _blowup(max_degree):
    """LDE blowup for constraints of degree ≤ max_degree: 2·next_pow2(max_degree), so the composition
    (degree ≤ max_degree·T) still sits at Reed–Solomon rate 1/2 for FRI."""
    # LDE must leave FRI room: composition degree ≤ max_degree·T, and FRI needs blowup ≥ 2 over that bound.
    return 2 * _next_pow2(max_degree)


def _coset_evaluate(coeffs, N, offset):
    """Evaluate a coefficient polynomial on the size-N coset {offset·ω^i}: substitute x → offset·y (scale
    coeff j by offset^j), then NTT on the subgroup. Uses the native Rust path when built."""
    from execnode.stark import goldilocks_native as _gn
    if _gn.available() and N <= _gn.NMAX:
        return _gn.coset_evaluate(coeffs, N, offset)
    c = list(coeffs) + [0] * (N - len(coeffs))
    g = [0] * N
    s = 1                                    # incremental offset^j (not a fresh pw per point)
    for j in range(N):
        g[j] = F.mul(c[j], s)
        s = F.mul(s, offset)
    return F.evaluate(g)


def _per_expand(pc, T):
    """Materialize one public periodic column to its full length-T list. A plain length-T sequence passes
    through (legacy dense form). The STRUCTURED form {"period": p, "base": [p values], "sparse": [(row, val)]}
    means base[i % p] everywhere except the listed rows, which take their absolute value verbatim — the compact
    way to say "a fixed p-row pattern plus a few instance-specific rows". Proving with either form of the same
    column yields byte-identical proofs (this expansion IS the definition)."""
    if isinstance(pc, dict):
        p, base = pc.get("period", 1), pc.get("base", [0])
        if not isinstance(p, int) or p < 1 or (p & (p - 1)) or T % p or len(base) != p:
            raise ValueError("structured periodic: period must be a power of two dividing T, len(base)=period")
        full = [base[i % p] % F.P for i in range(T)]
        for (r, v) in pc.get("sparse", ()):
            if not isinstance(r, int) or r < 0 or r >= T:
                raise ValueError("structured periodic: sparse row out of range")
            full[r] = v % F.P
        return full
    if len(pc) != T:
        raise ValueError("dense periodic column must have length T")
    return list(pc)


def _per_evaluator(pc, T, gT):
    """Return ev(x, xT) evaluating this public periodic column's degree<T interpolation at an arbitrary point x
    (xT = x^T precomputed by the caller). Dense form: one O(T) interpolation, then Horner — the legacy cost.
    STRUCTURED form: O(period + #sparse) per point, INDEPENDENT of T — the succinct-verifier path. Why it is the
    same polynomial: a p-periodic column's interpolation is h(x^(T/p)) where h interpolates the base over the
    size-p subgroup (g_p = g_T^(T/p) exactly, since both are GENERATOR^((P-1)/n)); overriding row r adds
    (v - base[r%p])·L_r(x) with the closed-form Lagrange basis L_r(x) = g^r·(x^T - 1)/(T·(x - g^r))."""
    if isinstance(pc, dict):
        p, base = pc.get("period", 1), pc.get("base", [0])
        if not isinstance(p, int) or p < 1 or (p & (p - 1)) or T % p or len(base) != p:
            raise ValueError("structured periodic: period must be a power of two dividing T, len(base)=period")
        h = F.interpolate([v % F.P for v in base])
        step = T // p
        invT = F.inv(T)
        over = {}
        for (r, v) in pc.get("sparse", ()):
            if not isinstance(r, int) or r < 0 or r >= T:
                raise ValueError("structured periodic: sparse row out of range")
            over[r] = v % F.P                    # later entries win, matching _per_expand's sequential writes
        ent = [(F.pw(gT, r), F.sub(v, base[r % p] % F.P)) for r, v in over.items()]

        def ev(x, xT):
            out = F.poly_eval(h, F.pw(x, step))
            zT = F.mul(F.sub(xT, 1), invT)
            for (gr, dv) in ent:
                if dv:
                    out = F.add(out, F.mul(dv, F.mul(F.mul(gr, zT), F.inv(F.sub(x, gr)))))
            return out
        return ev
    coeffs = F.interpolate(list(pc))
    return lambda x, xT: F.poly_eval(coeffs, x)


def _composition(T, W, N, blowup, gT, col_lde, per_lde, x_lde, transitions, boundaries, alphas,
                 challenges=None):
    """Evaluate the composition polynomial on the LDE coset: the α-random linear combination of every
    transition constraint divided by its vanishing polynomial (x^T - 1)/(x - last) — zero on every step but
    the wrap-around — plus every boundary column minus its pinned value divided by (x - point). Each quotient
    is a polynomial (hence the sum low-degree) IFF the corresponding constraint actually holds; any violation
    leaves a non-polynomial term that FRI's low-degree test rejects. `next row` on the LDE is index j+blowup
    (one trace step = blowup coset steps). With `challenges` (two-phase aux protocol) every constraint is
    called as con(cur, nxt, per, challenges)."""
    last = F.pw(gT, T - 1)
    # Transition vanishing is the same for every constraint: invZ[j] = (x-last)/(x^T - 1). One batch inversion
    # for the whole vector instead of an inv() per (constraint, point).
    inv_xTm1 = F.batch_inverse([F.sub(F.pw(x_lde[j], T), 1) for j in range(N)])
    invZ = [F.mul(F.sub(x_lde[j], last), inv_xTm1[j]) for j in range(N)]
    # per-boundary 1/(x - g^row) vectors (one batch inversion each) — shared by both the native and Python
    # paths. DEDUP by row: the denominator depends only on `row`, and the recursion AIRs carry MANY boundaries
    # at the SAME rows (a leaf frame pins ~6 lanes at one row; column roots repeat), so computing the size-N
    # batch inverse once per UNIQUE row instead of per boundary saves the bulk of the setup (bit-identical —
    # boundaries sharing a row map to the same vector).
    _den_by_row = {}
    for (row, _col, _val) in boundaries:
        if row not in _den_by_row:
            _den_by_row[row] = F.batch_inverse([F.sub(x_lde[j], F.pw(gT, row)) for j in range(N)])
    bnd_inv_dens = [_den_by_row[row] for (row, _col, _val) in boundaries]

    # NATIVE-FIELD PATH: trace the constraints into the shared IR (air_ir) and evaluate the whole composition in
    # Rust — bit-identical to the Python loop below (verified in tests), an order of magnitude faster on the
    # execution AIR. Falls back to Python if the lib is unbuilt or rejects the program (returns None).
    from execnode.stark import air_ir
    prog = air_ir.build_program(transitions, W, len(per_lde), 0 if challenges is None else len(challenges))
    cp = air_ir.compose_native(prog, N, blowup, col_lde, per_lde, list(challenges or []), alphas, invZ,
                               boundaries, bnd_inv_dens)
    if cp is not None:
        return cp

    # PYTHON FALLBACK (reference): the same arithmetic, per point.
    cur_rows = [[col_lde[c][j] for c in range(W)] for j in range(N)]
    nxt_rows = [[col_lde[c][(j + blowup) % N] for c in range(W)] for j in range(N)]
    per_rows = [[pc[j] for pc in per_lde] for j in range(N)]
    cp = [0] * N
    ai = 0
    for con in transitions:
        a = alphas[ai]; ai += 1
        if challenges is None:
            for j in range(N):
                cp[j] = F.add(cp[j], F.mul(a, F.mul(con(cur_rows[j], nxt_rows[j], per_rows[j]), invZ[j])))
        else:
            for j in range(N):
                cp[j] = F.add(cp[j], F.mul(a, F.mul(con(cur_rows[j], nxt_rows[j], per_rows[j], challenges),
                                                    invZ[j])))
    for bi, (row, col, val) in enumerate(boundaries):
        a = alphas[ai]; ai += 1
        inv_den = bnd_inv_dens[bi]
        for j in range(N):
            cp[j] = F.add(cp[j], F.mul(a, F.mul(F.sub(col_lde[col][j], val), inv_den[j])))
    return cp


def _row_tree(col_lde_group, N):
    """Row-commitment tree: ONE recursion-Merkle tree whose leaf j = alghash2.rrow of LDE row j across the
    given column group. An in-circuit verifier authenticates a whole opened row with ONE path instead of one
    per column — the enabler for recursing wide (execution-AIR) traces."""
    from execnode.stark import alghash2 as _a2
    leaves = [_a2.rrow([col[j] for col in col_lde_group]) for j in range(N)]
    return merkle.commit_digests(leaves, _backend.RECURSION)


def prove(trace, transitions, boundaries, periodic=None, max_degree=2, num_queries=NUM_QUERIES, aux=None,
          aux_spec=None, backend=None, row_commit=False):
    """Prove `trace` satisfies the AIR (transitions + boundaries [+ public periodic columns]). Interpolates
    and Merkle-commits each column's LDE, draws the constraint-combination challenges α from the committed
    roots (Fiat–Shamir), FRI-proves the composition is low-degree, and opens the cur/next trace rows at every
    FRI query point so the verifier can recompute the composition there. `aux` binds an extra public input
    (e.g. an unshield withdraw address, H-4) into the transcript. Returns the proof dict.

    `aux_spec` enables the TWO-PHASE protocol that lookup/permutation arguments (LogUp — the memory-checking
    machinery the VM execution circuit needs) require: {"num_challenges": k, "num_aux": n, "build": fn}.
    Phase 1 commits the MAIN trace columns; only THEN are k challenges drawn from the transcript (so the
    prover cannot pick witness values that suit them); `build(trace, challenges)` returns n extra aux columns
    (running sums / helper inverses) which are committed in phase 2 before the constraint αs are drawn.
    With aux_spec, every transition constraint is called as con(cur, nxt, per, challenges) and cur/nxt span
    main+aux columns. Without aux_spec the transcript and proof are byte-identical to the one-phase protocol
    (live shielded-pool proofs are untouched).

    `row_commit=True` (RECURSION backend only) commits LDE ROWS instead of columns: ONE recursion-Merkle tree
    per phase (main / aux) whose leaf j = alghash2.rrow(row j). The transcript absorbs one root per phase and
    each FRI query opens whole rows with ONE path per tree — 2 (or 4, two-phase) paths per query instead of
    2W, which is what makes recursing a wide (W=106) trace feasible. A DIFFERENT proof format ("row_roots" /
    row openings), verified by the matching verify(row_commit=True); column-mode proofs are untouched."""
    # HOLISTIC NATIVE PROVER (native/starkprove): for the RECURSION backend, run the whole pipeline
    # (LDE → Merkle → composition → FRI → openings) in a PERSISTENT Rust arena instead of materializing every
    # LDE column as a Python int list — the recursion/settlement memory wall. Byte-identical to the Python path
    # below (tests/test_starkprove.py gates the whole proof dict + verify, all modes); falls back to Python on
    # ANY error, and NADO_NO_HOLISTIC=1 forces the Python path (used to cross-check byte-identity).
    _b = backend or _backend.DEFAULT
    if getattr(_b, "name", "") in ("recursion", "alghash2") and not os.environ.get("NADO_NO_HOLISTIC"):
        try:
            from execnode.stark import stark_native
            if stark_native.available():
                return stark_native.prove(trace, transitions, boundaries, periodic=periodic,
                                          max_degree=max_degree, num_queries=num_queries, aux=aux,
                                          aux_spec=aux_spec, row_commit=row_commit, backend=_b)
        except Exception:
            pass                                          # correctness-preserving fallback to pure Python
    periodic = periodic or []
    T = len(trace); W = len(trace[0])
    blowup = _blowup(max_degree); N = blowup * T
    gT = F.primitive_root_of_unity(T)
    col_polys = [F.interpolate([trace[i][c] for i in range(T)]) for c in range(W)]
    col_lde = [_coset_evaluate(p, N, OFF) for p in col_polys]
    per_lde = [_coset_evaluate(F.interpolate(_per_expand(pc, T)), N, OFF) for pc in periodic]
    x_lde = F.domain(N, OFF)
    deg_bound = _next_pow2(max_degree) * T

    b = backend or _backend.DEFAULT
    if row_commit and getattr(b, "name", "") != "recursion":
        raise ValueError("row_commit requires the RECURSION backend")
    t = Transcript("nado-stark", backend=b)
    if aux is not None:                      # H-4: bind an extra public input (e.g. an unshield withdraw_addr)
        t.absorb("aux", str(aux))            # into the transcript so the proof only verifies for THAT value
    col_roots, col_mlayers = [], []
    row_roots, row_layers = [], []
    if row_commit:
        root, ml = _row_tree(col_lde, N)
        row_roots.append(root); row_layers.append(ml); t.absorb(root)
    else:
        for c in range(W):
            root, ml = merkle.commit(col_lde[c], b)
            col_roots.append(root); col_mlayers.append(ml); t.absorb(root)
    challenges = None
    if aux_spec is not None:                 # phase 2: challenges AFTER the main commitment, then aux columns
        challenges = [t.challenge() for _ in range(aux_spec["num_challenges"])]
        aux_cols = aux_spec["build"](trace, challenges)
        if len(aux_cols) != aux_spec["num_aux"] or any(len(c) != T for c in aux_cols):
            raise ValueError("aux builder returned wrong geometry")
        aux_lde = [_coset_evaluate(F.interpolate([v % F.P for v in col]), N, OFF) for col in aux_cols]
        col_lde.extend(aux_lde)
        if row_commit:
            root, ml = _row_tree(aux_lde, N)
            row_roots.append(root); row_layers.append(ml); t.absorb(root)
        else:
            for lde in aux_lde:
                root, ml = merkle.commit(lde, b)
                col_roots.append(root); col_mlayers.append(ml); t.absorb(root)
        W += aux_spec["num_aux"]
    alphas = [t.challenge() for _ in range(len(transitions) + len(boundaries))]
    cp = _composition(T, W, N, blowup, gT, col_lde, per_lde, x_lde, transitions, boundaries, alphas,
                      challenges)

    fri_blowup = N // deg_bound
    fri_proof = fri.prove(cp, OFF, fri_blowup, num_queries, transcript=t, backend=b)

    openings = []
    for q in fri_proof["queries"]:
        lo = q["idx"] % (N // 2)
        nxt = (lo + blowup) % N
        if row_commit:
            openings.append({"lo": lo,
                             "cur": [col_lde[c][lo] for c in range(W)],
                             "nxt": [col_lde[c][nxt] for c in range(W)],
                             "cur_paths": [merkle.open_at(ml, lo) for ml in row_layers],
                             "nxt_paths": [merkle.open_at(ml, nxt) for ml in row_layers]})
        else:
            cols = [{
                "cur": col_lde[c][lo], "cur_path": merkle.open_at(col_mlayers[c], lo),
                "nxt": col_lde[c][nxt], "nxt_path": merkle.open_at(col_mlayers[c], nxt),
            } for c in range(W)]
            openings.append({"lo": lo, "cols": cols})

    out = {"T": T, "W": W, "N": N, "blowup": blowup, "deg_bound": deg_bound,
           "boundaries": boundaries, "fri": fri_proof, "openings": openings}
    if row_commit:
        out["row_roots"] = row_roots
    else:
        out["col_roots"] = col_roots
    return out


def verify(proof, transitions, boundaries, periodic=None, max_degree=2, num_queries=NUM_QUERIES, aux=None,
           aux_spec=None, backend=None, row_commit=False):
    """Verify a STARK proof. Returns (ok, reason). The AIR itself (transitions, boundaries, periodic,
    max_degree) comes from the CALLER, never from the proof; the proof only supplies commitments and openings.
    Order of checks: LDE geometry pinned to max_degree·T before any allocation (H-7); transcript replayed to
    re-derive the same α challenges; FRI verified with the protocol-fixed blowup=2 and query count (C-1); then
    at every query point the composition is recomputed from the Merkle-opened trace rows + the verifier's own
    periodic values and must equal the committed FRI layer-0 value — this spot-check is what binds the
    low-degree polynomial FRI accepted to the committed trace actually satisfying the constraints."""
    try:
        periodic = periodic or []
        T, W, N, blowup = proof["T"], proof["W"], proof["N"], proof["blowup"]
        # H-7: validate the LDE geometry — which is fully determined by max_degree and T — BEFORE allocating
        # F.domain(N). Otherwise an oversized N (verbatim from the proof) OOMs the process ahead of every check.
        if not all(isinstance(v, int) for v in (T, W, N, blowup)):
            return False, "bad proof dimensions"
        if T < 1 or (T & (T - 1)) != 0 or T > MAX_TRACE_ROWS:
            return False, "bad trace length"
        if W < 1 or W > MAX_COLUMNS:
            return False, "bad column count"
        if blowup != _blowup(max_degree) or N != blowup * T:
            return False, "bad LDE geometry"
        gT = F.primitive_root_of_unity(T)
        wN = F.primitive_root_of_unity(N)        # query points computed as OFF·ω^lo — no O(N) domain allocation
        last = F.pw(gT, T - 1)
        per_evals = [_per_evaluator(pc, T, gT) for pc in periodic]    # public periodic polynomials
        # (structured {period, base, sparse} columns evaluate in O(period + entries) per query — T-independent)

        b = backend or _backend.DEFAULT
        if row_commit and getattr(b, "name", "") != "recursion":
            return False, "row_commit requires the RECURSION backend"
        n_aux = aux_spec["num_aux"] if aux_spec is not None else 0
        w_main = W - n_aux
        if aux_spec is not None and W <= n_aux:
            return False, "bad aux geometry"
        col_roots = row_roots = None
        if row_commit:
            row_roots = proof["row_roots"]
            if len(row_roots) != (2 if aux_spec is not None else 1):
                return False, "bad row-root count"
        else:
            col_roots = proof["col_roots"]
            if aux_spec is not None and len(col_roots) != W:
                return False, "bad aux geometry"
        t = Transcript("nado-stark", backend=b)
        if aux is not None:                  # H-4: same extra public input the prover bound (unshield addr)
            t.absorb("aux", str(aux))        # a tampered value here diverges the transcript -> proof rejected
        challenges = None
        if aux_spec is not None:
            # Two-phase replay: the aux geometry comes from the CALLER's protocol (aux_spec), never the proof.
            # Main roots are absorbed first, the k challenges drawn, THEN the aux roots — same order as prove,
            # so a prover that built aux columns before its main commitment gets different challenges and fails.
            for r in (row_roots[:1] if row_commit else col_roots[:w_main]):
                t.absorb(r)
            challenges = [t.challenge() for _ in range(aux_spec["num_challenges"])]
            for r in (row_roots[1:] if row_commit else col_roots[w_main:]):
                t.absorb(r)
        else:
            for r in (row_roots if row_commit else col_roots):
                t.absorb(r)
        alphas = [t.challenge() for _ in range(len(transitions) + len(boundaries))]

        # fri_blowup is ALWAYS 2 for a STARK proof (N = 2·next_pow2(max_degree)·T, deg_bound = N/2), so pin it —
        # that forces the full FRI geometry and, with the fixed query count, closes the C-1 empty-proof bypass.
        ok, why = fri.verify(proof["fri"], transcript=t, num_queries=num_queries, expected_blowup=2, backend=b)
        if not ok:
            return False, f"composition is not low-degree: {why}"

        # C-1: the trace/composition spot-checks live in the loop below; enforce that there is exactly one
        # opening per required FRI query, so an empty/short `openings` (or `queries`) can't skip them via zip().
        if len(proof["openings"]) != num_queries or len(proof["fri"]["queries"]) != num_queries:
            return False, "wrong opening/query count"

        for q, op in zip(proof["fri"]["queries"], proof["openings"]):
            lo = q["idx"] % (N // 2)
            if lo != op["lo"]:
                return False, "opening index mismatch"
            nxt = (lo + blowup) % N
            cur_row, nxt_row = [], []
            if row_commit:
                from execnode.stark import alghash2 as _a2
                cur_row = [int(v) % F.P for v in op["cur"]]
                nxt_row = [int(v) % F.P for v in op["nxt"]]
                if len(cur_row) != W or len(nxt_row) != W:
                    return False, "bad row opening width"
                groups = [(0, w_main, 0)] + ([(w_main, W, 1)] if aux_spec is not None else [])
                for (s, e, ti) in groups:
                    if not merkle.verify_digest(row_roots[ti], lo, _a2.rrow(cur_row[s:e]),
                                                op["cur_paths"][ti], b):
                        return False, f"bad row opening (cur) tree {ti}"
                    if not merkle.verify_digest(row_roots[ti], nxt, _a2.rrow(nxt_row[s:e]),
                                                op["nxt_paths"][ti], b):
                        return False, f"bad row opening (nxt) tree {ti}"
            else:
                for c in range(W):
                    col = op["cols"][c]
                    if not merkle.verify(col_roots[c], lo, col["cur"], col["cur_path"], b):
                        return False, f"bad trace opening (cur) col {c}"
                    if not merkle.verify(col_roots[c], nxt, col["nxt"], col["nxt_path"], b):
                        return False, f"bad trace opening (nxt) col {c}"
                    cur_row.append(col["cur"]); nxt_row.append(col["nxt"])
            x = F.mul(OFF, F.pw(wN, lo))
            xT = F.pw(x, T)
            per = [pe(x, xT) for pe in per_evals]                    # verifier recomputes periodic values
            cp = 0; ai = 0
            for con in transitions:
                a = alphas[ai]; ai += 1
                z = F.mul(F.sub(xT, 1), F.inv(F.sub(x, last)))
                cval = con(cur_row, nxt_row, per) if challenges is None else con(cur_row, nxt_row, per, challenges)
                cp = F.add(cp, F.mul(a, F.mul(cval, F.inv(z))))
            for (row, col, val) in boundaries:
                a = alphas[ai]; ai += 1
                pt = F.pw(gT, row)
                cp = F.add(cp, F.mul(a, F.mul(F.sub(cur_row[col], val), F.inv(F.sub(x, pt)))))
            if cp != q["steps"][0]["lo"]:
                return False, "trace/composition mismatch (a constraint is violated)"
        return True, "ok"
    except Exception as e:
        return False, f"malformed proof: {e}"
