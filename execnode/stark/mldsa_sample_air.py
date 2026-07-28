"""
ML-DSA-44 verify AIR — sub-circuit 8: the XOF-driven SAMPLERS — ExpandA (the public matrix A) and
SampleInBall (the challenge polynomial c). Both turn SHAKE output into structured values by REJECTION
SAMPLING, and both are needed by FIPS 204 Algorithm 8.

ExpandA (dominates the whole circuit): for each of the k x l = 16 matrix entries, seed SHAKE128 with
rho || j || i and repeatedly read 3 bytes, mask to 23 bits, and keep the value if it is < Q — until 256
coefficients are collected. Roughly 256 * (Q / 2^23)^-1 ~ 285 draws of 3 bytes per polynomial, i.e. ~855
bytes, which is 6-7 SHAKE128 blocks per entry and ~100 permutations across the matrix. That is why the
sig-agg design folds proofs and why ExpandA sets the cost floor.

SampleInBall: seed SHAKE256 with c_tilde, take 8 sign bytes, then for i in [256-tau, 256) reject-sample a
byte j <= i and swap, writing +-1 from the sign bits — producing exactly tau nonzero coefficients.

ARITHMETISATION STRATEGY. The XOF itself is the proven sponge (mldsa_sponge_air). What this module adds is
the REJECTION LOGIC, and the key observation is that it is *verifier-derivable*: given the XOF output stream
(which the sponge proof attests) the accept/reject decisions and the resulting coefficients are a public,
deterministic function — there is no witness to trust. So the samplers are proven by:
    (1) the sponge proof over the XOF stream (already built), plus
    (2) a RANGE proof that every accepted coefficient is < Q and every REJECTED draw was indeed >= Q,
which is exactly the two-sided bit-range pattern used throughout these sub-circuits. `rejection_witness`
below emits those (value, accepted) pairs so the range AIR can prove the decisions were honest — a prover
cannot silently drop a valid draw (that would leave an accepted-but-out-of-order coefficient) nor accept an
invalid one (the range check fails).

Golden reference: dilithium_py.polynomials.polynomials.rejection_sample_ntt_poly / sample_in_ball.
"""
from execnode.stark import mldsa_params as P, mldsa_sponge_air as SP

Q, N = P.Q, P.N
MASK23 = 0x7FFFFF


# ---- ExpandA ---------------------------------------------------------------------------------------
def expand_a_seed(rho, i, j):
    """The XOF seed for matrix entry (i, j): rho || j || i (note the ORDER — j first; FIPS 204 / dilithium)."""
    return bytes(rho) + bytes([j, i])


def _xof_stream(seed, nbytes, rate):
    """Deterministic XOF bytes from the proven sponge."""
    return SP.shake(seed, nbytes, rate)


def rejection_sample_poly(rho, i, j, max_bytes=4096):
    """Reproduce dilithium's rejection_sample_ntt_poly for matrix entry (i, j).
    Returns (coeffs, draws) where `draws` is the ordered list of (value23, accepted) decisions."""
    seed = expand_a_seed(rho, i, j)
    stream = _xof_stream(seed, max_bytes, SP.RATE_128)
    coeffs, draws, pos = [], [], 0
    while len(coeffs) < N:
        if pos + 3 > len(stream):                       # extremely unlikely; widen the window and retry
            stream = _xof_stream(seed, len(stream) * 2, SP.RATE_128)
            continue
        v = int.from_bytes(stream[pos:pos + 3], "little") & MASK23
        pos += 3
        ok = v < Q
        draws.append((v, 1 if ok else 0))
        if ok:
            coeffs.append(v)
    return coeffs, draws


def expand_a(rho, k=P.K, l=P.L):
    """The full k x l public matrix A in the NTT domain (dilithium _expand_matrix_from_seed)."""
    return [[rejection_sample_poly(rho, i, j)[0] for j in range(l)] for i in range(k)]


def expand_a_cost(rho, k=P.K, l=P.L):
    """Measured cost of ExpandA: total draws and SHAKE128 permutations — the circuit's dominant term."""
    draws = 0
    for i in range(k):
        for j in range(l):
            draws += len(rejection_sample_poly(rho, i, j)[1])
    xof_bytes = draws * 3
    blocks = -(-xof_bytes // SP.RATE_128)               # ceil: one permutation per absorbed/squeezed block
    return {"draws": draws, "xof_bytes": xof_bytes, "permutations": blocks + k * l}


# ---- SampleInBall ----------------------------------------------------------------------------------
def sample_in_ball(c_tilde, tau=P.TAU, max_bytes=1024):
    """Reproduce dilithium's sample_in_ball: tau coefficients of +-1, the rest 0.
    Returns (coeffs, draws) with `draws` the ordered (byte, accepted) rejection decisions."""
    stream = _xof_stream(bytes(c_tilde), max_bytes, SP.RATE_256)
    sign_int = int.from_bytes(stream[:8], "little")
    pos = 8
    coeffs = [0] * N
    draws = []
    for i in range(N - tau, N):
        while True:
            if pos >= len(stream):
                stream = _xof_stream(bytes(c_tilde), len(stream) * 2, SP.RATE_256)
            j = stream[pos]
            pos += 1
            ok = j <= i
            draws.append((j, 1 if ok else 0))
            if ok:
                break
        coeffs[i] = coeffs[j]
        coeffs[j] = 1 - 2 * (sign_int & 1)
        sign_int >>= 1
    return coeffs, draws


# ---- the rejection witness the range AIR proves -----------------------------------------------------
def rejection_witness(draws, bound):
    """Turn rejection decisions into (value, accepted, bound) rows for a two-sided range proof: an ACCEPTED
    row must satisfy value < bound, a REJECTED row must satisfy value >= bound. Proving both directions is
    what stops a prover from dropping a valid draw or accepting an invalid one — the accepted subsequence is
    then forced to be exactly the reference's."""
    return [(int(v), int(a), int(bound)) for (v, a) in draws]


def witness_consistent(draws, bound):
    """Native check of the same statement (the reference the AIR mirrors)."""
    return all((v < bound) == bool(a) for v, a in draws)
