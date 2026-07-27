"""
ML-DSA-44 verify AIR — sub-circuit 3b: the FULL 256-point negacyclic NTT (forward + inverse + pointwise),
composed from the butterfly gadget (mldsa_butterfly_air). This is the arithmetic engine behind
w' = A·z − c·t1·2^d: every polynomial multiply in ML-DSA verification happens in the NTT domain.

STRUCTURE. dilithium's forward NTT is 8 stages (l = 128, 64, ..., 1), each stage applying 128
Cooley-Tukey butterflies with a per-group zeta from the bit-reversed twiddle table; the inverse is 8
Gentleman-Sande stages (l = 1 .. 128) followed by a scale by ntt_f = 256^-1 mod Q. Since ONE butterfly
is already a proven, self-contained row (mldsa_butterfly_air), a whole NTT is just 8·128 = 1024 butterfly
rows in the schedule's order — so this module PROVES a full NTT by emitting that row list and reusing the
butterfly AIR, with the routing (which coefficients feed which butterfly, and which zeta) rebuilt
IDENTICALLY by the verifier from the public schedule. The routing is data-independent (it depends only on
the stage/index structure, never on coefficient values), which is exactly what makes it safe to be public.

WHAT IS PROVEN. Given a PUBLIC input polynomial and a PUBLIC claimed output, the proof establishes that every
butterfly in the schedule was computed correctly over Q. Chaining is enforced natively by the verifier
re-deriving the same routing: it rebuilds each butterfly's (a, b) from the previous stage's proven outputs.
(Binding the intermediate wiring IN-circuit — so the verifier does no O(stages·N) work — is the succinctness
step that comes with the full-signature composition; here the routing is cheap public structure.)

Golden reference: dilithium_py.polynomials.polynomials (to_ntt / from_ntt / ntt_coefficient_multiplication).
"""
from execnode.stark import field as F, stark, backend as B
from execnode.stark import mldsa_params as P, mldsa_butterfly_air as BF

Q = P.Q
N = P.N                                   # 256


def zetas():
    """The Dilithium twiddle table: bit-reversed powers of the 512th root of unity 1753 mod Q."""
    def br(i, k):
        return int(bin(i & (2 ** k - 1))[2:].zfill(k)[::-1], 2)
    return [pow(1753, br(i, 8), Q) for i in range(N)]


ZETAS = zetas()
NTT_F = pow(N, -1, Q)                     # 256^-1 mod Q, the inverse-NTT scale factor


def forward_schedule():
    """The (stage, j, j+l, zeta_index) routing of dilithium's to_ntt, in execution order — 8 stages x 128
    butterflies. Data-INDEPENDENT: pure index structure the verifier rebuilds for free."""
    sched, k, l = [], 0, 128
    while l > 0:
        start = 0
        while start < N:
            k += 1
            j = start
            for j in range(start, start + l):
                sched.append((j, j + l, k))
            start = l + (j + 1)
        l >>= 1
    return sched


def inverse_schedule():
    """The routing of dilithium's from_ntt (Gentleman-Sande), in execution order — 8 stages x 128 steps,
    each (j, j+l, zeta_index) with the zeta NEGATED at use (see apply_inverse)."""
    sched, k, l = [], N, 1
    while l < N:
        start = 0
        while start < N:
            k -= 1
            j = start
            for j in range(start, start + l):
                sched.append((j, j + l, k))
            start = j + l + 1
        l <<= 1
    return sched


def apply_forward(coeffs):
    """Reference forward NTT (matches dilithium to_ntt) returning (out_coeffs, butterflies) where
    `butterflies` is the ordered (a, b, zeta) list the AIR proves."""
    c = [int(x) % Q for x in coeffs]
    bfs = []
    for (j, jl, k) in forward_schedule():
        a, b, z = c[j], c[jl], ZETAS[k] % Q
        t = z * b % Q
        bfs.append((a, b, z))
        c[j], c[jl] = (a + t) % Q, (a - t) % Q
    return c, bfs


def apply_inverse(coeffs):
    """Reference inverse NTT (matches dilithium from_ntt incl. the final 256^-1 scale). Returns
    (out_coeffs, butterflies) — the GS step is (a+b, zeta·(a−b)), expressed as butterfly rows over Q."""
    c = [int(x) % Q for x in coeffs]
    bfs = []
    for (j, jl, k) in inverse_schedule():
        a, b = c[j], c[jl]
        z = (-ZETAS[k]) % Q
        s, d = (a + b) % Q, (a - b) % Q
        c[j], c[jl] = s, z * d % Q
        bfs.append((d, 1, z))                  # prove the multiply zeta·(a−b) as a butterfly with b=1
    c = [x * NTT_F % Q for x in c]
    return c, bfs


def pointwise(f_coeffs, g_coeffs):
    """NTT-domain pointwise product (dilithium ntt_coefficient_multiplication) + the (a,b) pairs to prove
    via the mod-Q gadget."""
    pairs = [(int(a) % Q, int(b) % Q) for a, b in zip(f_coeffs, g_coeffs)]
    return [a * b % Q for a, b in pairs], pairs


def prove_forward(coeffs, num_queries=stark.NUM_QUERIES, backend=None):
    """Prove a full forward NTT of the PUBLIC `coeffs`. Returns (proof, out_coeffs, butterflies)."""
    out, bfs = apply_forward(coeffs)
    return BF.prove(bfs, num_queries=num_queries, backend=backend), out, bfs


def verify_forward(proof, coeffs, out_coeffs, num_queries=stark.NUM_QUERIES, backend=None):
    """Verify a forward-NTT proof against PUBLIC input and claimed output: the verifier REBUILDS the whole
    butterfly list from the input via the public (data-independent) schedule — so it checks the claimed output
    AND that the proof covers exactly those butterflies. Returns (ok, reason)."""
    try:
        want_out, want_bfs = apply_forward(coeffs)
        if [int(x) % Q for x in out_coeffs] != want_out:
            return False, "claimed NTT output does not match the schedule"
        return BF.verify(proof, want_bfs, num_queries=num_queries, backend=backend)
    except Exception as e:
        return False, f"malformed forward-NTT proof: {e}"


def prove_inverse(coeffs, num_queries=stark.NUM_QUERIES, backend=None):
    out, bfs = apply_inverse(coeffs)
    return BF.prove(bfs, num_queries=num_queries, backend=backend), out, bfs


def verify_inverse(proof, coeffs, out_coeffs, num_queries=stark.NUM_QUERIES, backend=None):
    try:
        want_out, want_bfs = apply_inverse(coeffs)
        if [int(x) % Q for x in out_coeffs] != want_out:
            return False, "claimed inverse-NTT output does not match the schedule"
        return BF.verify(proof, want_bfs, num_queries=num_queries, backend=backend)
    except Exception as e:
        return False, f"malformed inverse-NTT proof: {e}"
