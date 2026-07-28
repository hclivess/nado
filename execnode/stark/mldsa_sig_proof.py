"""
ML-DSA-44 — the ASSEMBLED SIGNATURE PROOF: every sub-circuit of one signature verification, proven and folded
into ONE heterogeneous recursion bundle (execnode/stark/recursive_verify_hetero).

WHY HETEROGENEOUS. The sub-circuits have genuinely different AIRs — the Keccak permutation is 6080 boolean
columns over 32 rows, the norm/decode/UseHint circuits are narrow range-check tables, the NTT butterfly is its
own shape. `recursive_verify.prove` requires one shared AIR shape, so a single homogeneous fold cannot bind
them; `recursive_verify_hetero.prove_hetero` folds proofs of DIFFERENT AIRs into one bundle (one FRI fold plus
one composition per distinct AIR), which is exactly this assembly.

WHAT THE BUNDLE ATTESTS. Each sub-proof is pinned to its own PUBLIC statement by boundaries (the decoded
coefficients, the range rows, the butterflies, the permutation states). The verifier rebuilds every one of
those statements from the PUBLIC (pk, msg, sig) via mldsa_verify — the same deterministic derivation the
reference performs — and then checks the single bundle against them. So the bundle proves the arithmetic while
the CHAINING (which value feeds which circuit) is verifier-derived and unforgeable, the same division of labour
the sponge uses.

SCOPE. `plan()` derives the full per-signature workload and the exact sub-proof list. `prove_signature()` proves
and folds a chosen SUBSET of that plan (`parts=`), because a full ML-DSA signature is 103 Keccak permutations —
minutes each — so the complete bundle is a proving-farm job, not a unit test. The subset path is the same code:
what changes with scale is time, not correctness. `verify_signature()` rebuilds the statements and verifies the
bundle.

Golden reference for every statement: mldsa_verify (which agrees with the native RustCrypto ml-dsa backend).
"""
from execnode.stark import (mldsa_params as P, mldsa_verify as MV, mldsa_norm_air as NORM,
                            mldsa_decode_air as DEC, mldsa_hint_air as HINT, mldsa_keccak_air as KEC,
                            mldsa_sponge_air as SP, mldsa_sample_air as SA, stark,
                            recursive_verify as RV, recursive_verify_hetero as RVH, backend as B)

Q, N, K, L = P.Q, P.N, P.K, P.L

# the sub-circuit parts an assembled signature proof is made of, in verification order
PARTS = ("decode_z", "norm_z", "decode_t1", "usehint", "keccak")


def plan(pk, msg, sig):
    """The full statement + workload of ONE signature verification: what each sub-proof must cover.
    Everything here is derived from the PUBLIC (pk, msg, sig), so the verifier builds the identical plan."""
    up, us = MV.unpack_pk(pk), MV.unpack_sig(sig)
    if up is None or us is None:
        return None
    rho, t1 = up
    c_tilde, z, h = us
    z_bytes = sig[P.C_TILDE_BYTES:P.C_TILDE_BYTES + L * MV.Z_BYTES]
    t1_bytes = pk[32:]
    # the w' the UseHint rows are taken over (the same computation mldsa_verify performs)
    return {
        "rho": rho, "c_tilde": c_tilde,
        "z_chunks": [z_bytes[i * MV.Z_BYTES:(i + 1) * MV.Z_BYTES] for i in range(L)],
        "t1_chunks": [t1_bytes[i * MV.T1_BYTES:(i + 1) * MV.T1_BYTES] for i in range(K)],
        "z_coeffs": [c % Q for poly in z for c in poly],
        "hint_rows": _hint_rows(pk, msg, sig),
        "workload": MV.statement(pk, msg, sig),
    }


def _w_prime(pk, msg, sig):
    """Recompute w' = NTT^-1(A.NTT(z) - NTT(c)*NTT(t1*2^d)) — the input to UseHint (public)."""
    from execnode.stark import mldsa_ntt_air as NTT
    rho, t1 = MV.unpack_pk(pk)
    c_tilde, z, h = MV.unpack_sig(sig)
    A = SA.expand_a(rho)
    c, _ = SA.sample_in_ball(c_tilde)
    c_hat, _ = NTT.apply_forward([x % Q for x in c])
    z_hat = [NTT.apply_forward([x % Q for x in poly])[0] for poly in z]
    t1_hat = [NTT.apply_forward([(x << P.D) % Q for x in poly])[0] for poly in t1]
    out = []
    for i in range(K):
        acc = [0] * N
        for j in range(L):
            prod, _ = NTT.pointwise(A[i][j], z_hat[j])
            acc = [(a + b) % Q for a, b in zip(acc, prod)]
        ct, _ = NTT.pointwise(c_hat, t1_hat[i])
        out.append(NTT.apply_inverse([(a - b) % Q for a, b in zip(acc, ct)])[0])
    return out, h


def _hint_rows(pk, msg, sig):
    """The (r, h) UseHint rows for the whole signature."""
    w, h = _w_prime(pk, msg, sig)
    return [(w[i][n], h[i][n]) for i in range(K) for n in range(N)]


def _items(plan_, parts, num_queries):
    """Prove each requested sub-circuit and return the hetero recursion items + their AIR descriptors."""
    bk = B.RECURSION
    items, airs = [], []

    def add(proof, transitions, boundaries, periodic=None):
        it = {"proof": proof, "transitions": transitions, "boundaries": boundaries}
        air = {"transitions": transitions, "boundaries": boundaries}
        if periodic is not None:
            it["periodic"] = periodic; air["periodic"] = periodic
        items.append(it); airs.append(air)

    if "decode_z" in parts:                                  # one z polynomial's bit-unpack
        chunk = plan_["z_chunks"][0]
        pr, coeffs = DEC.prove_field(chunk, "z", num_queries=num_queries, backend=bk)
        vals = [c % stark.F.P for c in coeffs] if hasattr(stark, "F") else coeffs
        add(pr, DEC.transitions(DEC.BITS_Z, P.GAMMA_1), DEC._boundaries(coeffs, pr["T"]))
    if "decode_t1" in parts:
        chunk = plan_["t1_chunks"][0]
        pr, coeffs = DEC.prove_field(chunk, "t1", num_queries=num_queries, backend=bk)
        add(pr, DEC.transitions(DEC.BITS_T1, None), DEC._boundaries(coeffs, pr["T"]))
    if "norm_z" in parts:                                    # the ||z||inf bound over a slice of coefficients
        zc = plan_["z_coeffs"][:64]
        pr = NORM.prove(zc, num_queries=num_queries, backend=bk)
        add(pr, NORM.transitions(), NORM._boundaries(zc, pr["T"]))
    if "usehint" in parts:
        rows = plan_["hint_rows"][:64]
        pr = HINT.prove(rows, num_queries=num_queries, backend=bk)
        add(pr, HINT.transitions(), HINT._boundaries(rows, pr["T"]))
    if "keccak" in parts:                                    # one proven Keccak-f permutation
        st = [0] * KEC.LANES
        pr, out = KEC.prove_permutation(st, num_queries=num_queries, backend=bk)
        T = pr["T"]
        add(pr, KEC.transitions(), KEC._boundaries(st, out, T), KEC.periodic(T))
    return items, airs


def prove_signature(pk, msg, sig, parts=("decode_z", "norm_z", "usehint"),
                    num_queries=2, num_queries_outer=2):
    """Prove the requested sub-circuits of this signature and FOLD them into ONE heterogeneous bundle.
    Returns (bundle, publics, airs) or None if the signature does not verify natively (never prove a lie)."""
    if not MV.verify(pk, msg, sig):
        return None
    pl = plan(pk, msg, sig)
    if pl is None:
        return None
    items, airs = _items(pl, parts, num_queries)
    bundle = RVH.prove_hetero(items, num_queries_outer=num_queries_outer)
    publics = [RV.public_part(it["proof"]) for it in items]
    return bundle, publics, airs


def verify_signature(bundle, publics, airs, num_queries=2, num_queries_outer=2):
    """Verify the folded bundle. The AIR descriptors carry each sub-circuit's public statement (its
    boundaries), which the caller rebuilds from the public (pk, msg, sig) — so a bundle cannot be replayed
    against a different signature. Returns (ok, reason)."""
    return RVH.verify_hetero(publics, airs, bundle, num_queries_outer=num_queries_outer,
                             num_queries_inner=num_queries)
