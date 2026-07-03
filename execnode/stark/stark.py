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
from execnode.stark import field as F, merkle, fri
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
    p = 1
    while p < x:
        p <<= 1
    return p


def _blowup(max_degree):
    # LDE must leave FRI room: composition degree ≤ max_degree·T, and FRI needs blowup ≥ 2 over that bound.
    return 2 * _next_pow2(max_degree)


def _coset_evaluate(coeffs, N, offset):
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


def _composition(T, W, N, blowup, gT, col_lde, per_lde, x_lde, transitions, boundaries, alphas):
    last = F.pw(gT, T - 1)
    # Transition vanishing is the same for every constraint: invZ[j] = (x-last)/(x^T - 1). One batch inversion
    # for the whole vector instead of an inv() per (constraint, point).
    inv_xTm1 = F.batch_inverse([F.sub(F.pw(x_lde[j], T), 1) for j in range(N)])
    invZ = [F.mul(F.sub(x_lde[j], last), inv_xTm1[j]) for j in range(N)]
    # per-row column + periodic slices, shared across all transitions (built once)
    cur_rows = [[col_lde[c][j] for c in range(W)] for j in range(N)]
    nxt_rows = [[col_lde[c][(j + blowup) % N] for c in range(W)] for j in range(N)]
    per_rows = [[pc[j] for pc in per_lde] for j in range(N)]
    cp = [0] * N
    ai = 0
    for con in transitions:
        a = alphas[ai]; ai += 1
        for j in range(N):
            cp[j] = F.add(cp[j], F.mul(a, F.mul(con(cur_rows[j], nxt_rows[j], per_rows[j]), invZ[j])))
    for (row, col, val) in boundaries:
        a = alphas[ai]; ai += 1
        pt = F.pw(gT, row)
        inv_den = F.batch_inverse([F.sub(x_lde[j], pt) for j in range(N)])
        for j in range(N):
            cp[j] = F.add(cp[j], F.mul(a, F.mul(F.sub(col_lde[col][j], val), inv_den[j])))
    return cp


def prove(trace, transitions, boundaries, periodic=None, max_degree=2, num_queries=NUM_QUERIES, aux=None):
    periodic = periodic or []
    T = len(trace); W = len(trace[0])
    blowup = _blowup(max_degree); N = blowup * T
    gT = F.primitive_root_of_unity(T)
    col_polys = [F.interpolate([trace[i][c] for i in range(T)]) for c in range(W)]
    col_lde = [_coset_evaluate(p, N, OFF) for p in col_polys]
    per_lde = [_coset_evaluate(F.interpolate(list(pc)), N, OFF) for pc in periodic]
    x_lde = F.domain(N, OFF)
    deg_bound = _next_pow2(max_degree) * T

    t = Transcript("nado-stark")
    if aux is not None:                      # H-4: bind an extra public input (e.g. an unshield withdraw_addr)
        t.absorb("aux", str(aux))            # into the transcript so the proof only verifies for THAT value
    col_roots, col_mlayers = [], []
    for c in range(W):
        root, ml = merkle.commit(col_lde[c])
        col_roots.append(root); col_mlayers.append(ml); t.absorb(root)
    alphas = [t.challenge() for _ in range(len(transitions) + len(boundaries))]
    cp = _composition(T, W, N, blowup, gT, col_lde, per_lde, x_lde, transitions, boundaries, alphas)

    fri_blowup = N // deg_bound
    fri_proof = fri.prove(cp, OFF, fri_blowup, num_queries, transcript=t)

    openings = []
    for q in fri_proof["queries"]:
        lo = q["idx"] % (N // 2)
        nxt = (lo + blowup) % N
        cols = [{
            "cur": col_lde[c][lo], "cur_path": merkle.open_at(col_mlayers[c], lo),
            "nxt": col_lde[c][nxt], "nxt_path": merkle.open_at(col_mlayers[c], nxt),
        } for c in range(W)]
        openings.append({"lo": lo, "cols": cols})

    return {"T": T, "W": W, "N": N, "blowup": blowup, "deg_bound": deg_bound, "col_roots": col_roots,
            "boundaries": boundaries, "fri": fri_proof, "openings": openings}


def verify(proof, transitions, boundaries, periodic=None, max_degree=2, num_queries=NUM_QUERIES, aux=None):
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
        col_roots = proof["col_roots"]
        gT = F.primitive_root_of_unity(T)
        x_dom = F.domain(N, OFF)
        last = F.pw(gT, T - 1)
        per_coeffs = [F.interpolate(list(pc)) for pc in periodic]     # public periodic polynomials

        t = Transcript("nado-stark")
        if aux is not None:                  # H-4: same extra public input the prover bound (unshield addr)
            t.absorb("aux", str(aux))        # a tampered value here diverges the transcript -> proof rejected
        for r in col_roots:
            t.absorb(r)
        alphas = [t.challenge() for _ in range(len(transitions) + len(boundaries))]

        # fri_blowup is ALWAYS 2 for a STARK proof (N = 2·next_pow2(max_degree)·T, deg_bound = N/2), so pin it —
        # that forces the full FRI geometry and, with the fixed query count, closes the C-1 empty-proof bypass.
        ok, why = fri.verify(proof["fri"], transcript=t, num_queries=num_queries, expected_blowup=2)
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
            for c in range(W):
                col = op["cols"][c]
                if not merkle.verify(col_roots[c], lo, col["cur"], col["cur_path"]):
                    return False, f"bad trace opening (cur) col {c}"
                if not merkle.verify(col_roots[c], nxt, col["nxt"], col["nxt_path"]):
                    return False, f"bad trace opening (nxt) col {c}"
                cur_row.append(col["cur"]); nxt_row.append(col["nxt"])
            x = x_dom[lo]
            xT = F.pw(x, T)
            per = [F.poly_eval(pco, x) for pco in per_coeffs]        # verifier recomputes periodic values
            cp = 0; ai = 0
            for con in transitions:
                a = alphas[ai]; ai += 1
                z = F.mul(F.sub(xT, 1), F.inv(F.sub(x, last)))
                cp = F.add(cp, F.mul(a, F.mul(con(cur_row, nxt_row, per), F.inv(z))))
            for (row, col, val) in boundaries:
                a = alphas[ai]; ai += 1
                pt = F.pw(gT, row)
                cp = F.add(cp, F.mul(a, F.mul(F.sub(cur_row[col], val), F.inv(F.sub(x, pt)))))
            if cp != q["steps"][0]["lo"]:
                return False, "trace/composition mismatch (a constraint is violated)"
        return True, "ok"
    except Exception as e:
        return False, f"malformed proof: {e}"
