"""
STARK over an AIR — prove that an execution TRACE satisfies its constraints, in zero-added-trust and
post-quantum (doc/privacy.md). This is the layer between "a computation" and FRI.

An AIR (Algebraic Intermediate Representation) is:
  * a TRACE: T rows × W columns (T a power of two) — the registers of the computation over time;
  * TRANSITION constraints c(cur_row, next_row) = 0, required on every step;
  * BOUNDARY constraints (row, col, value) — pinned inputs/outputs.

The STARK, in one breath: interpolate each column to a degree-<T polynomial; evaluate on a larger coset (the
low-degree extension) and Merkle-commit it; form the COMPOSITION polynomial = a random linear combination of
every constraint DIVIDED by the polynomial that vanishes where it must hold — this quotient is low-degree
IFF every constraint holds; prove that with FRI; and spot-check, at FRI's own query points, that the committed
composition really equals the quotient recomputed from the committed trace. Cheating requires either a
non-low-degree quotient (FRI rejects) or a trace/composition mismatch (the spot-checks reject).

Soundness assumption: BLAKE2b collision-resistance. Nothing elliptic-curve, no trusted setup.
"""
from execnode.stark import field as F, merkle, fri
from execnode.stark.transcript import Transcript

OFF = F.GENERATOR                    # LDE coset shift (disjoint from the trace subgroup, so Z never divides by 0)
BLOWUP = 8                           # LDE size = BLOWUP · T


def _next_pow2(x):
    p = 1
    while p < x:
        p <<= 1
    return p


def _coset_evaluate(coeffs, N, offset):
    """Evaluate a coefficient polynomial (len ≤ N) on the size-N coset {offset·ω^i}."""
    c = list(coeffs) + [0] * (N - len(coeffs))
    g = [F.mul(c[j], F.pw(offset, j)) for j in range(N)]
    return F.evaluate(g)


def _build(trace, transitions, boundaries, max_degree):
    T = len(trace)
    W = len(trace[0])
    N = BLOWUP * T
    gT = F.primitive_root_of_unity(T)                 # trace-domain generator
    wN = F.primitive_root_of_unity(N)                 # LDE-domain generator
    col_polys = [F.interpolate([trace[i][c] for i in range(T)]) for c in range(W)]
    col_lde = [_coset_evaluate(col_polys[c], N, OFF) for c in range(W)]
    x_lde = F.domain(N, OFF)                            # x_j = OFF·wN^j
    deg_bound = _next_pow2(max_degree) * T             # composition degree bound (power of two)
    return T, W, N, gT, wN, col_polys, col_lde, x_lde, deg_bound


def _composition(T, W, N, gT, col_lde, x_lde, transitions, boundaries, alphas):
    """The quotient/composition evaluations over the LDE. CP[j] is low-degree over all j IFF every constraint
    holds on the trace domain."""
    last = F.pw(gT, T - 1)
    xT = [F.pw(x_lde[j], T) for j in range(N)]         # x_j^T
    cp = [0] * N
    ai = 0
    # transition constraints: vanish on the whole trace domain except the last row -> divide by
    # Z_trans(x) = (x^T - 1)/(x - g^{T-1})
    for k, con in enumerate(transitions):
        a = alphas[ai]; ai += 1
        for j in range(N):
            cur = [col_lde[c][j] for c in range(W)]
            nxt = [col_lde[c][(j + BLOWUP) % N] for c in range(W)]
            cval = con(cur, nxt)
            z = F.mul(F.sub(xT[j], 1), F.inv(F.sub(x_lde[j], last)))   # Z_trans(x_j)
            cp[j] = F.add(cp[j], F.mul(a, F.mul(cval, F.inv(z))))
    # boundary constraints: (col(x) - v) vanishes at x = g^row -> divide by (x - g^row)
    for (row, col, val) in boundaries:
        a = alphas[ai]; ai += 1
        pt = F.pw(gT, row)
        for j in range(N):
            b = F.sub(col_lde[col][j], val)
            cp[j] = F.add(cp[j], F.mul(a, F.mul(b, F.inv(F.sub(x_lde[j], pt)))))
    return cp


def prove(trace, transitions, boundaries, max_degree=2, num_queries=32):
    T, W, N, gT, wN, col_polys, col_lde, x_lde, deg_bound = _build(trace, transitions, boundaries, max_degree)
    t = Transcript("nado-stark")
    col_roots, col_mlayers = [], []
    for c in range(W):
        root, ml = merkle.commit(col_lde[c])
        col_roots.append(root); col_mlayers.append(ml); t.absorb(root)
    alphas = [t.challenge() for _ in range(len(transitions) + len(boundaries))]
    cp = _composition(T, W, N, gT, col_lde, x_lde, transitions, boundaries, alphas)

    fri_blowup = N // deg_bound                          # FRI proves deg(CP) < N/fri_blowup = deg_bound
    fri_proof = fri.prove(cp, OFF, fri_blowup, num_queries, transcript=t)

    # spot-check openings of the TRACE at FRI's own layer-0 query points (ties trace <-> composition)
    openings = []
    for q in fri_proof["queries"]:
        lo = q["idx"] % (N // 2)
        nxt = (lo + BLOWUP) % N
        cols = []
        for c in range(W):
            cols.append({
                "cur": col_lde[c][lo], "cur_path": merkle.open_at(col_mlayers[c], lo),
                "nxt": col_lde[c][nxt], "nxt_path": merkle.open_at(col_mlayers[c], nxt),
            })
        openings.append({"lo": lo, "cols": cols})

    return {"T": T, "W": W, "N": N, "deg_bound": deg_bound, "col_roots": col_roots,
            "boundaries": boundaries, "fri": fri_proof, "openings": openings}


def verify(proof, transitions, boundaries, max_degree=2):
    try:
        T, W, N = proof["T"], proof["W"], proof["N"]
        col_roots = proof["col_roots"]
        gT = F.primitive_root_of_unity(T)
        x_dom = F.domain(N, OFF)
        last = F.pw(gT, T - 1)

        t = Transcript("nado-stark")
        for r in col_roots:
            t.absorb(r)
        alphas = [t.challenge() for _ in range(len(transitions) + len(boundaries))]

        ok, why = fri.verify(proof["fri"], transcript=t)
        if not ok:
            return False, f"composition is not low-degree: {why}"

        # re-derive CP from the committed trace at each FRI query point and match FRI's committed CP value
        for q, op in zip(proof["fri"]["queries"], proof["openings"]):
            lo = q["idx"] % (N // 2)
            if lo != op["lo"]:
                return False, "opening index mismatch"
            nxt = (lo + BLOWUP) % N
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
            cp = 0; ai = 0
            for con in transitions:
                a = alphas[ai]; ai += 1
                z = F.mul(F.sub(xT, 1), F.inv(F.sub(x, last)))
                cp = F.add(cp, F.mul(a, F.mul(con(cur_row, nxt_row), F.inv(z))))
            for (row, col, val) in boundaries:
                a = alphas[ai]; ai += 1
                pt = F.pw(gT, row)
                cp = F.add(cp, F.mul(a, F.mul(F.sub(cur_row[col], val), F.inv(F.sub(x, pt)))))
            if cp != q["steps"][0]["lo"]:                 # FRI already Merkle-verified this CP value
                return False, "trace/composition mismatch (a constraint is violated)"
        return True, "ok"
    except Exception as e:
        return False, f"malformed proof: {e}"
