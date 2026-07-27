"""
ML-DSA-44 verify AIR — sub-circuit 5: the signature / public-key DECODER (bit-unpacking). FIPS 204 packs the
verification inputs as tightly-packed little-endian bit fields, and the verifier MUST decode them EXACTLY —
a decoder that accepts a non-canonical encoding is a signature-malleability hole.

WHAT IS DECODED (ML-DSA-44 widths, from dilithium_py.polynomials __bit_unpack + wrappers):
    t1  (public key) : 10 bits/coefficient, value as-is                       -> 320 bytes per poly, k=4
    z   (signature)  : 18 bits/coefficient, coefficient = gamma_1 - x         -> 576 bytes per poly, l=4
    w1  (recomputed) : 6  bits/coefficient, value as-is                       -> 192 bytes per poly, k=4
    h   (signature)  : the omega+k hint encoding (positions + per-poly cuts)

ARITHMETISATION. A packed field is a windowed sum of bits: coefficient i is bits [n*i, n*i+n) of the
little-endian bit stream. The AIR proves, per coefficient row: (a) every bit column is boolean, (b) the
coefficient equals the weighted bit sum, and (c) the value transform (identity for t1/w1, gamma_1 - x for z).
The BYTES themselves are pinned as the public statement (they are the signature the block commits to), and the
verifier reconstructs each row's bit window from them — so the decode is verifier-authoritative and canonical
by construction: there is exactly one bit assignment per byte string.

Golden reference: dilithium_py.polynomials.polynomials.__bit_unpack + bit_unpack_t1 / bit_unpack_z /
bit_unpack_w, and ml_dsa._unpack_pk / _unpack_sig / _unpack_h.
"""
from execnode.stark import field as F, stark, backend as B
from execnode.stark import mldsa_params as P

Q, N = P.Q, P.N
BITS_T1, BITS_Z, BITS_W1 = 10, 18, 6

# column layout is dynamic in the bit width: [value | bits...]
VAL = 0
BIT0 = 1
MAX_DEGREE = 2


def _width(n_bits):
    return 1 + n_bits


def bit_unpack(input_bytes, n_bits, n=N):
    """The reference primitive: little-endian bit windows (dilithium __bit_unpack)."""
    if (len(input_bytes) * 8) % n_bits != 0 and (len(input_bytes) * n_bits) % 8 != 0:
        raise ValueError("byte length incompatible with the bit width")
    r = int.from_bytes(input_bytes, "little")
    mask = (1 << n_bits) - 1
    return [(r >> (n_bits * i)) & mask for i in range(n)]


def unpack_t1(input_bytes):
    """10-bit, identity transform (dilithium bit_unpack_t1)."""
    return bit_unpack(input_bytes, BITS_T1)


def unpack_z(input_bytes, gamma_1=P.GAMMA_1):
    """18-bit, coefficient = gamma_1 - x (dilithium bit_unpack_z)."""
    return [gamma_1 - c for c in bit_unpack(input_bytes, BITS_Z)]


def unpack_w1(input_bytes):
    """6-bit, identity (dilithium bit_unpack_w for gamma_2 = 95232)."""
    return bit_unpack(input_bytes, BITS_W1)


def unpack_h(h_bytes, k=P.K, omega=P.OMEGA):
    """The hint decoding (dilithium ml_dsa._unpack_h): the first `omega` bytes are set-bit POSITIONS, the last
    `k` bytes are the cumulative per-polynomial cut points. Returns a list of k lists of 256 hint bits, or None
    if the encoding is non-canonical (positions must be strictly increasing within a polynomial and zero-padded
    after the final cut) — matching the reference's malleability rejection."""
    if len(h_bytes) != omega + k:
        return None
    hints, idx = [], 0
    for i in range(k):
        cut = h_bytes[omega + i]
        if cut < idx or cut > omega:
            return None                       # non-monotonic cut -> invalid encoding
        row = [0] * N
        prev = -1
        for j in range(idx, cut):
            pos = h_bytes[j]
            if pos <= prev:
                return None                   # positions must strictly increase
            row[pos] = 1
            prev = pos
        hints.append(row)
        idx = cut
    if any(h_bytes[j] != 0 for j in range(idx, omega)):
        return None                           # padding must be zero
    return hints


def _row(value, bits_val, n_bits):
    row = [0] * _width(n_bits)
    row[VAL] = int(value) % F.P
    for i in range(n_bits):
        row[BIT0 + i] = (bits_val >> i) & 1
    return row


def _next_pow2(n):
    p = 1
    while p < n:
        p <<= 1
    return p


def build_trace(raw_windows, n_bits, transform):
    """raw_windows: the packed bit windows (ints < 2^n_bits). transform maps a window to the coefficient."""
    rows = [_row(transform(w), w, n_bits) for w in raw_windows]
    T = _next_pow2(len(rows) + 1)
    pad = _row(transform(0), 0, n_bits)
    while len(rows) < T:
        rows.append(list(pad))
    return rows, T


def transitions(n_bits, gamma_1=None):
    """Per-row constraints: every bit boolean, and the value is the weighted bit sum (identity) or
    gamma_1 - (bit sum) when `gamma_1` is given (the z transform). Degree <= 2."""
    cons = [lambda c, n, per, _k=BIT0 + i: F.sub(F.mul(c[_k], c[_k]), c[_k]) for i in range(n_bits)]

    def link(c, n, per):
        acc = 0
        for i in range(n_bits):
            acc = F.add(acc, F.mul(c[BIT0 + i], 1 << i))
        want = F.sub(gamma_1, acc) if gamma_1 is not None else acc
        return F.sub(c[VAL], want)
    cons.append(link)
    return cons


def _boundaries(values, T):
    return [(i, VAL, int(v) % F.P) for i, v in enumerate(values)]


def prove_field(input_bytes, kind, num_queries=stark.NUM_QUERIES, backend=None):
    """Prove the decode of one packed polynomial. `kind` in {'t1','z','w1'}. Returns (proof, coefficients)."""
    bk = backend or B.RECURSION
    n_bits, gamma = {"t1": (BITS_T1, None), "z": (BITS_Z, P.GAMMA_1), "w1": (BITS_W1, None)}[kind]
    windows = bit_unpack(input_bytes, n_bits)
    transform = (lambda w: (gamma - w) % F.P) if gamma is not None else (lambda w: w)
    values = [transform(w) for w in windows]
    rows, T = build_trace(windows, n_bits, transform)
    proof = stark.prove(rows, transitions(n_bits, gamma), _boundaries(values, T),
                        max_degree=MAX_DEGREE, num_queries=num_queries, backend=bk)
    coeffs = [(gamma - w) if gamma is not None else w for w in windows]
    return proof, coeffs


def verify_field(proof, input_bytes, kind, coeffs, num_queries=stark.NUM_QUERIES, backend=None):
    """Verify a decode proof against the PUBLIC packed bytes + claimed coefficients: the verifier re-derives
    the windows from the bytes itself (canonical by construction) and pins the resulting values."""
    try:
        bk = backend or B.RECURSION
        n_bits, gamma = {"t1": (BITS_T1, None), "z": (BITS_Z, P.GAMMA_1), "w1": (BITS_W1, None)}[kind]
        windows = bit_unpack(input_bytes, n_bits)
        want = [(gamma - w) if gamma is not None else w for w in windows]
        if [int(c) for c in coeffs] != want:
            return False, "claimed coefficients do not match the packed bytes"
        vals = [v % F.P for v in want]
        T = proof["T"]
        return stark.verify(proof, transitions(n_bits, gamma), _boundaries(vals, T),
                            max_degree=MAX_DEGREE, num_queries=num_queries, backend=bk)
    except Exception as e:
        return False, f"malformed decode proof: {e}"
