"""
ML-DSA-44 verify, sub-circuit 1 of N: the coefficient INFINITY-NORM BOUND  ||z||_inf < GAMMA_1 - BETA
(FIPS 204 Algorithm 8, the "if ||z||_inf >= gamma_1 - beta: return False" gate). This is the smallest
self-contained, decode-agnostic piece of the ML-DSA verification AIR (doc/zk-signature-aggregation.md) and
establishes the mod-Q-over-Goldilocks + exact-range-check pattern the heavier sub-circuits (Decompose/UseHint,
the NTT, the eventual Keccak/SHAKE) reuse.

STATEMENT (verifier-authoritative). The verifier supplies the PUBLIC coefficient vector `z` (each z_i in
[0, Q), as produced by the signature decode — a later sub-circuit / dilithium_py in tests) and pins each row's
coefficient column to it via a boundary. The proof attests: for EVERY pinned coefficient c, the centered
representative v = c - s*Q (s the 1-bit sign hint) satisfies |v| < B := GAMMA_1 - BETA. Because c is pinned to a
canonical value in [0, Q), exactly one of s in {0,1} can place v in (-B, B) when the coefficient is in range,
and NEITHER can when c is in the forbidden middle band [B, Q-B] — so an out-of-bound coefficient is
unprovable, and the bound is EXACT (not a power-of-two over-approximation): u = v + (B-1) is pinned into
[0, 2B-2] by decomposing BOTH u and (2B-2 - u) into NBITS bits (both non-negative => u <= 2B-2).

All constraints are per-row (functions of the current row only), degree <= 2. Rows 0..M-1 carry the M
coefficients; rows M..T-2 are valid zero-coefficient padding (also constrained); the last row T-1 is
unconstrained pad. No periodic columns; boundaries pin the public coefficients.
"""
from execnode.stark import field as F, stark, backend as B
from execnode.stark import mldsa_params as P

Q = P.Q
BOUND = P.Z_BOUND               # B = GAMMA_1 - BETA = 130994
BM1 = BOUND - 1                 # 130993
TWOBM2 = 2 * BOUND - 2         # 261986  (max value of u)
NBITS = TWOBM2.bit_length()    # 18  (2^18 = 262144 > 261986)
POW2 = [1 << i for i in range(NBITS)]

# column layout
C = 0                           # the coefficient (pinned to public z_i)
S = 1                           # sign hint bit: v = c - s*Q is the centered representative
U0 = 2                          # u = v + (B-1) decomposed into NBITS bits, cols U0 .. U0+NBITS-1
T0 = U0 + NBITS                 # t = (2B-2) - u decomposed into NBITS bits
W = T0 + NBITS                  # total width = 2 + 2*NBITS = 38
MAX_DEGREE = 2


def _centered_sign(c):
    """s in {0,1} placing v = c - s*Q as the centered representative of c in (-Q/2, Q/2]."""
    return 0 if c <= (Q - 1) // 2 else 1


def _row(c):
    """Build one trace row for coefficient c (in [0, Q)); raises if |centered(c)| >= B (unprovable)."""
    c %= Q
    s = _centered_sign(c)
    v = c - s * Q                                  # signed integer in (-Q, Q)
    if not (-BOUND < v < BOUND):
        raise ValueError(f"coefficient {c} (centered {v}) violates ||.||_inf < {BOUND}")
    u = v + BM1                                    # in [0, 2B-2]
    t = TWOBM2 - u                                 # in [0, 2B-2]
    row = [0] * W
    row[C] = c % F.P
    row[S] = s
    for i in range(NBITS):
        row[U0 + i] = (u >> i) & 1
        row[T0 + i] = (t >> i) & 1
    return row


def _next_pow2(n):
    p = 1
    while p < n:
        p <<= 1
    return p


def build_trace(z_coeffs):
    """z_coeffs: flat list of the M coefficients of z (each in [0, Q)). Returns (rows, T, M)."""
    M = len(z_coeffs)
    rows = [_row(int(c)) for c in z_coeffs]
    T = _next_pow2(M + 1)                           # +1 so row M-1 is a constrained `cur` (transitions hit 0..T-2)
    pad = _row(0)                                   # zero coefficient is a valid, in-bound padding row
    while len(rows) < T:
        rows.append(list(pad))
    return rows, T, M


def _boolean(col):
    return lambda c, n, per, _k=col: F.sub(F.mul(c[_k], c[_k]), c[_k])


def transitions():
    """Per-row (cur-only) constraints, all degree <= 2:
       (1) s and every bit are boolean;
       (2) Σ u_bits·2^i == c - s·Q + (B-1)   [u decomposition + definition];
       (3) Σ t_bits·2^i == (B-1) - c + s·Q   [t = (2B-2) - u decomposition]."""
    cons = [_boolean(S)]
    cons += [_boolean(U0 + i) for i in range(NBITS)]
    cons += [_boolean(T0 + i) for i in range(NBITS)]

    def u_link(c, n, per):
        acc = 0
        for i in range(NBITS):
            acc = F.add(acc, F.mul(c[U0 + i], POW2[i]))
        rhs = F.add(F.sub(c[C], F.mul(c[S], Q)), BM1)   # c - s*Q + (B-1)
        return F.sub(acc, rhs)

    def t_link(c, n, per):
        acc = 0
        for i in range(NBITS):
            acc = F.add(acc, F.mul(c[T0 + i], POW2[i]))
        rhs = F.add(F.sub(BM1, c[C]), F.mul(c[S], Q))   # (B-1) - c + s*Q
        return F.sub(acc, rhs)

    cons.append(u_link)
    cons.append(t_link)
    return cons


def _boundaries(z_coeffs, T):
    """Pin each row's coefficient column to the PUBLIC z (verifier-authoritative). Pad rows are unpinned."""
    return [(i, C, int(c) % F.P) for i, c in enumerate(z_coeffs)]


def prove(z_coeffs, num_queries=stark.NUM_QUERIES, backend=None):
    """Prove ||z||_inf < GAMMA_1 - BETA for the public coefficient vector `z_coeffs`. Returns the proof."""
    bk = backend or B.RECURSION
    rows, T, _M = build_trace(z_coeffs)
    return stark.prove(rows, transitions(), _boundaries(z_coeffs, T),
                       max_degree=MAX_DEGREE, num_queries=num_queries, backend=bk)


def verify(proof, z_coeffs, num_queries=stark.NUM_QUERIES, backend=None):
    """Verify the norm bound for PUBLIC `z_coeffs`: rebuild the coefficient boundaries and check the STARK.
    A coefficient that does not match the proven trace fails its boundary. Returns (ok, reason)."""
    try:
        bk = backend or B.RECURSION
        T = proof["T"]
        return stark.verify(proof, transitions(), _boundaries(z_coeffs, T),
                            max_degree=MAX_DEGREE, num_queries=num_queries, backend=bk)
    except Exception as e:
        return False, f"malformed norm proof: {e}"
