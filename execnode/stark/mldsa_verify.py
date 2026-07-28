"""
ML-DSA-44 verify — the ASSEMBLED verification (FIPS 204 Algorithm 8), built from the sub-circuits:

    mldsa_decode_air   unpack t1 (10-bit), z (18-bit, gamma_1 - x), h (omega+k hint encoding)
    mldsa_norm_air     ||z||_inf < gamma_1 - beta
    mldsa_hint_air     hint weight <= omega, decompose + UseHint
    mldsa_sample_air   ExpandA (SHAKE128 rejection sampling) and SampleInBall (c from c_tilde)
    mldsa_ntt_air      the 256-point negacyclic NTT and pointwise multiplication
    mldsa_modq_air     mod-Q multiply-reduce
    mldsa_sponge_air   SHAKE (tr, mu, and the final c_tilde comparison), over
    mldsa_keccak_air   the proven Keccak-f[1600] permutation

The verification equation:
    (1) decode the signature and public key
    (2) reject unless ||z||_inf < gamma_1 - beta and the hint weight <= omega
    (3) A_hat  = ExpandA(rho)
        tr     = SHAKE256(pk, 64)
        mu     = SHAKE256(tr || m, 64)
        c      = SampleInBall(c_tilde)
    (4) w'     = NTT^-1( A_hat . NTT(z)  -  NTT(c) * NTT(t1 * 2^d) )
    (5) w1'    = UseHint(h, w')
    (6) accept iff c_tilde == SHAKE256(mu || bit_pack_w(w1'), 32)

THIS MODULE runs that equation over the SAME code paths the AIRs prove, so it is the reference the assembled
circuit is checked against: `verify()` here must agree with the native RustCrypto backend on every input
(tests/test_mldsa_verify.py asserts that on real signatures, valid and tampered). `statement()` emits the
per-sub-circuit workload — the exact list of range rows, NTT butterflies, mod-Q products, UseHint items and
Keccak permutations a full proof must cover — which is what the block-level prover batches and folds.

NOTE ON WHAT IS AND IS NOT PROVEN YET. Every sub-circuit is individually built and validated, and this module
composes them into the true verification equation with a measured workload. What is NOT yet built is the single
assembled AIR that binds all of them together in one proof (each piece currently proves independently); that
binding — plus the block-level batching in doc/zk-signature-aggregation.md — is the remaining work.
"""
from execnode.stark import (mldsa_params as P, mldsa_decode_air as DEC, mldsa_ntt_air as NTT,
                            mldsa_hint_air as HINT, mldsa_sample_air as SA, mldsa_sponge_air as SP)

Q, N, K, L, D = P.Q, P.N, P.K, P.L, P.D
Z_BYTES = 576                     # packed bytes per z polynomial (18 bits * 256 / 8)
T1_BYTES = 320                    # packed bytes per t1 polynomial (10 bits * 256 / 8)
W1_BYTES = 192                    # packed bytes per w1 polynomial (6 bits * 256 / 8)


def unpack_pk(pk):
    """rho || t1 (k polynomials, 10-bit packed)."""
    if len(pk) != P.PK_BYTES:
        return None
    rho, rest = pk[:32], pk[32:]
    t1 = [DEC.unpack_t1(rest[i * T1_BYTES:(i + 1) * T1_BYTES]) for i in range(K)]
    return rho, t1


def unpack_sig(sig):
    """c_tilde || z (l polynomials, 18-bit packed) || h (omega+k hint encoding)."""
    if len(sig) != P.SIG_BYTES:
        return None
    c_tilde = sig[:P.C_TILDE_BYTES]
    zb = sig[P.C_TILDE_BYTES:P.C_TILDE_BYTES + L * Z_BYTES]
    z = [DEC.unpack_z(zb[i * Z_BYTES:(i + 1) * Z_BYTES]) for i in range(L)]
    h = DEC.unpack_h(sig[P.C_TILDE_BYTES + L * Z_BYTES:])
    if h is None:
        return None                                   # non-canonical hint encoding (malleability)
    return c_tilde, z, h


def _centered(c):
    return c - Q if c > (Q - 1) // 2 else c


def norm_ok(z):
    """||z||_inf < gamma_1 - beta over the centred representatives (mldsa_norm_air's statement)."""
    return all(abs(_centered(c % Q)) < P.Z_BOUND for poly in z for c in poly)


def hint_weight_ok(h):
    return sum(sum(poly) for poly in h) <= P.OMEGA


def bit_pack_w1(w1):
    """Pack w1 at 6 bits/coefficient (the level-2 gamma_2 width) — the bytes fed to the final SHAKE."""
    out = bytearray()
    for poly in w1:
        acc = bits = 0
        for c in poly:
            acc |= (int(c) & 0x3F) << bits
            bits += 6
            while bits >= 8:
                out.append(acc & 0xFF)
                acc >>= 8
                bits -= 8
        if bits:
            out.append(acc & 0xFF)
    return bytes(out)


def verify(pk, msg, sig):
    """The full FIPS 204 Alg 8 verification, over the sub-circuits' own code paths. Returns True/False."""
    try:
        up = unpack_pk(pk)
        us = unpack_sig(sig)
        if up is None or us is None:
            return False
        rho, t1 = up
        c_tilde, z, h = us
        if not norm_ok(z) or not hint_weight_ok(h):
            return False
        A = SA.expand_a(rho)                                        # ExpandA (NTT domain)
        tr = SP.shake256(bytes(pk), 64)
        mu = SP.shake256(tr + bytes(msg), 64)
        c, _draws = SA.sample_in_ball(c_tilde)                      # challenge polynomial
        c_hat, _ = NTT.apply_forward([x % Q for x in c])
        z_hat = [NTT.apply_forward([x % Q for x in poly])[0] for poly in z]
        t1_hat = [NTT.apply_forward([(x << D) % Q for x in poly])[0] for poly in t1]
        w = []
        for i in range(K):
            acc = [0] * N
            for j in range(L):
                prod, _pairs = NTT.pointwise(A[i][j], z_hat[j])
                acc = [(a + b) % Q for a, b in zip(acc, prod)]
            ct, _pairs = NTT.pointwise(c_hat, t1_hat[i])
            diff = [(a - b) % Q for a, b in zip(acc, ct)]
            w.append(NTT.apply_inverse(diff)[0])
        w1 = [[HINT.use_hint(h[i][n], w[i][n]) for n in range(N)] for i in range(K)]
        return bytes(c_tilde) == SP.shake256(mu + bit_pack_w1(w1), P.C_TILDE_BYTES)
    except Exception:
        return False


def statement(pk, msg, sig):
    """The per-sub-circuit WORKLOAD a full proof of this verification must cover — measured, not estimated.
    This is what the block-level prover batches and folds (doc/zk-signature-aggregation.md)."""
    rho, t1 = unpack_pk(pk)
    c_tilde, z, h = unpack_sig(sig)
    draws = 0
    for i in range(K):
        for j in range(L):
            draws += len(SA.rejection_sample_poly(rho, i, j)[1])
    sib_draws = len(SA.sample_in_ball(c_tilde)[1])
    tr_steps = len(SP.schedule(bytes(pk), 64, SP.RATE_256)[0])
    mu_steps = len(SP.schedule(SP.shake256(bytes(pk), 64) + bytes(msg), 64, SP.RATE_256)[0])
    expand_perms = SA.expand_a_cost(rho)["permutations"]
    ntts = L + K + 1 + K                    # NTT(z_j), NTT(t1_i * 2^d), NTT(c), and K inverse NTTs
    return {
        "decode_coeffs": L * N + K * N,                 # z + t1 coefficients bit-unpacked
        "norm_rows": L * N,                             # ||z||_inf range rows
        "usehint_rows": K * N,                          # UseHint per w' coefficient
        "ntt_transforms": ntts,
        "ntt_butterflies": ntts * 1024,                 # 8 stages x 128 butterflies each
        "modq_products": (K * L + K) * N,               # A.z pointwise + c*t1
        "expand_a_draws": draws,
        "sample_in_ball_draws": sib_draws,
        "keccak_permutations": expand_perms + tr_steps + mu_steps + 2,   # +final compare, +SampleInBall XOF
    }
