"""
DEEP out-of-domain EVALUATION proof (doc/zk-recursion.md §5c, piece 2 — the fold-layer io binding).

To bind two proofs' io WITHOUT re-checking the whole log and WITHOUT a shared prover transcript, commit each
proof's io as a polynomial and, at a random point z drawn AFTER both commitments, prove P(z)=v for each and check
the v's equal: P_a(z)=P_b(z) at a random z ⟹ P_a=P_b (Schwartz–Zippel), in O(polylog). This is the standard DEEP
(Domain-Extending-for-Eliminating-Pretenders) / PLONK-evaluation technique.

prove_eval(values, z, N, offset): commit P (the length-T column) on the coset, then commit q(x)=(P(x)−v)/(x−z)
and FRI-prove deg(q) < T. verify_eval opens q + P at each FRI query point and checks q(x)·(x−z) = P(x)−v — a
low-degree q satisfying that relation everywhere forces P(z)=v (a wrong v makes q non-polynomial ⇒ FRI rejects).
The commitment P_root is returned/checked so a caller can TIE the evaluated polynomial to an already-committed
column (root equality: same values + same geometry ⇒ same root), which is how the io of an existing proof is
bound without re-opening it on its own coset.
"""
from execnode.stark import field as F, fri, merkle, backend as _backend
from execnode.stark.transcript import Transcript
from execnode.stark.stark import _coset_evaluate, OFF as DEFAULT_OFF


def _lde_and_commit(values, N, offset, backend):
    """Interpolate the length-T column, evaluate on the size-N coset, Merkle-commit. Returns (coeffs, lde, root, mlayers)."""
    T = len(values)
    if N % T or (N // T) < 2 or (N & (N - 1)) or (T & (T - 1)):
        raise ValueError("N must be a power-of-two multiple (blowup ≥ 2) of the power-of-two column length")
    coeffs = F.interpolate([int(v) % F.P for v in values])
    lde = _coset_evaluate(coeffs, N, offset)
    root, ml = merkle.commit(lde, backend)
    return coeffs, lde, root, ml


def commit_column(values, N, offset=DEFAULT_OFF, backend=None):
    """Just the commitment of a column on the size-N coset — the root a caller pins to tie an eval to it."""
    b = backend or _backend.DEFAULT
    _c, _l, root, _m = _lde_and_commit(values, N, offset, b)
    return root


def prove_eval(values, z, N, offset=DEFAULT_OFF, num_queries=fri.NUM_QUERIES, transcript=None, backend=None):
    """Prove P(z)=v for P = the interpolation of `values` (length T = power of two), committed on the size-N
    coset. Returns {v, P_root, T, N, offset, fri, P_open}. `transcript` (shared) binds z's context; z itself is
    the caller's OOD point (drawn from a transcript that already absorbed the committed roots)."""
    b = backend or _backend.DEFAULT
    t = transcript or Transcript("deep-eval", backend=b)
    T = len(values)
    coeffs, P_lde, P_root, P_ml = _lde_and_commit(values, N, offset, b)
    z = int(z) % F.P
    v = F.poly_eval(coeffs, z)
    x_lde = F.domain(N, offset)
    q_lde = [F.mul(F.sub(P_lde[i], v), F.inv(F.sub(x_lde[i], z))) for i in range(N)]   # (P-v)/(x-z) on the coset
    t.absorb("deep", v, z, P_root)                                       # bind the claim into the FRI transcript
    blowup = N // T                                                      # FRI proves deg(q) < N/blowup = T
    fri_proof = fri.prove(q_lde, offset, blowup, num_queries, transcript=t, backend=b)
    P_open = [{"idx": qr["idx"], "val": P_lde[qr["idx"]], "path": merkle.open_at(P_ml, qr["idx"])}
              for qr in fri_proof["queries"]]
    return {"v": v, "P_root": P_root, "T": T, "N": N, "offset": offset, "fri": fri_proof, "P_open": P_open}


def verify_eval(proof, z, num_queries=fri.NUM_QUERIES, transcript=None, backend=None, expect_P_root=None):
    """Verify a DEEP eval proof: q is low-degree (deg < T) AND q(x)·(x−z)=P(x)−v at every FRI query point, with P
    opened against P_root. If `expect_P_root` is given, P_root must equal it (the tie to a pre-committed column).
    Returns (ok, reason). On ok, the proven value is proof["v"] = P(z)."""
    try:
        b = backend or _backend.DEFAULT
        t = transcript or Transcript("deep-eval", backend=b)
        v, P_root, T, N, offset = proof["v"], proof["P_root"], proof["T"], proof["N"], proof["offset"]
        if not all(isinstance(x, int) for x in (T, N)) or N % T or (N // T) < 2 or (N & (N - 1)) or (T & (T - 1)):
            return False, "bad eval geometry"
        if expect_P_root is not None and P_root != expect_P_root:
            return False, "P_root does not match the pinned committed column"
        z = int(z) % F.P
        t.absorb("deep", v, z, P_root)
        blowup = N // T
        okf, whyf = fri.verify(proof["fri"], transcript=t, num_queries=num_queries, expected_blowup=blowup, backend=b)
        if not okf:
            return False, f"q not low-degree: {whyf}"
        qq = proof["fri"]["queries"]
        if len(proof["P_open"]) != len(qq):
            return False, "P-opening count mismatch"
        wN = F.primitive_root_of_unity(N)
        half = N // 2
        for qr, po in zip(qq, proof["P_open"]):
            idx = qr["idx"]
            if po["idx"] != idx:
                return False, "P-opening index mismatch"
            if not merkle.verify(P_root, idx, po["val"], po["path"], b):
                return False, "bad P opening"
            # q at the query point (fri verified steps[0] against its root): lo half → steps[0].lo, hi half → .hi
            q_at = qr["steps"][0]["lo"] if idx < half else qr["steps"][0]["hi"]
            x = F.mul(offset, F.pw(wN, idx))
            if F.mul(int(q_at) % F.P, F.sub(x, z)) != F.sub(int(po["val"]) % F.P, v):
                return False, "DEEP relation q·(x−z)=P−v violated"
        return True, "ok"
    except Exception as e:
        return False, f"malformed eval proof: {e}"
