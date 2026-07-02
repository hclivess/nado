"""
Goldilocks prime field  p = 2^64 - 2^32 + 1  — the arithmetic layer of NADO's zk-STARK (doc/privacy.md).

Why Goldilocks: it is a STARK-FRIENDLY field. p - 1 = 2^32 · (2^32 - 1), so it has 2-adicity 32 — there is a
primitive 2^k-th root of unity for every k ≤ 32, which is exactly what the NTT (and therefore FRI) needs to
build evaluation domains of size 2^k. Elements fit in 64 bits, so a full-node/phone verifier does only cheap
64-bit modular arithmetic, and it is hash-agnostic (post-quantum: the only assumption anywhere in the STARK is
a collision-resistant hash).

Everything here is pure integers in [0, p) — no classes, so it stays fast and trivially reproducible.
"""

P = 0xFFFFFFFF00000001                 # 2^64 - 2^32 + 1  = 18446744069414584321
GENERATOR = 7                          # a generator of the full multiplicative group F_p^*
TWO_ADICITY = 32                       # 2^32 | (p - 1)


def add(a, b): return (a + b) % P
def sub(a, b): return (a - b) % P
def neg(a): return (-a) % P
def mul(a, b): return (a * b) % P


def pw(a, e):
    """a**e mod p (e may be negative → uses the inverse)."""
    if e < 0:
        a = inv(a); e = -e
    return pow(a % P, e, P)


def inv(a):
    a %= P
    if a == 0:
        raise ZeroDivisionError("no inverse of 0 in F_p")
    return pow(a, P - 2, P)            # Fermat: a^(p-2) = a^-1


def div(a, b): return mul(a, inv(b))


# --- roots of unity + evaluation domains -----------------------------------------------------------
def primitive_root_of_unity(n):
    """A primitive n-th root of unity, n a power of two with n ≤ 2^TWO_ADICITY. ω = g^((p-1)/n) has order n."""
    if n <= 0 or (n & (n - 1)) != 0:
        raise ValueError("n must be a power of two")
    if n > (1 << TWO_ADICITY):
        raise ValueError(f"n exceeds the field's 2-adicity (max 2^{TWO_ADICITY})")
    return pow(GENERATOR, (P - 1) // n, P)


def domain(n, offset=1):
    """The size-n multiplicative coset {offset · ω^i}. offset=1 → the subgroup itself; a non-1 offset gives the
    'coset' evaluation domain a STARK uses so trace and quotient are evaluated on disjoint points."""
    w = primitive_root_of_unity(n)
    out = [offset % P] * n
    for i in range(1, n):
        out[i] = mul(out[i - 1], w)
    return out


# --- number-theoretic transform (evaluate/interpolate on the size-n subgroup) ----------------------
def _bitrev(a):
    n = len(a); j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit; bit >>= 1
        j ^= bit
        if i < j:
            a[i], a[j] = a[j], a[i]


def ntt(coeffs, inverse=False):
    """In/out size-n (power of two). Forward: coefficients → evaluations on the n-th-root subgroup. Inverse:
    evaluations → coefficients. Iterative radix-2 Cooley–Tukey."""
    a = [c % P for c in coeffs]
    n = len(a)
    if n & (n - 1):
        raise ValueError("length must be a power of two")
    _bitrev(a)
    w = inv(primitive_root_of_unity(n)) if inverse else primitive_root_of_unity(n)
    length = 2
    while length <= n:
        wlen = pow(w, n // length, P)
        for i in range(0, n, length):
            wn = 1
            for k in range(i, i + length // 2):
                u = a[k]; v = a[k + length // 2] * wn % P
                a[k] = (u + v) % P
                a[k + length // 2] = (u - v) % P
                wn = wn * wlen % P
        length <<= 1
    if inverse:
        n_inv = inv(n)
        a = [x * n_inv % P for x in a]
    return a


def interpolate(evals):
    """Coefficients of the polynomial that takes `evals` on the size-n root-of-unity subgroup."""
    return ntt(evals, inverse=True)


def evaluate(coeffs):
    """Evaluations of `coeffs` on the size-len(coeffs) subgroup."""
    return ntt(coeffs, inverse=False)


def poly_eval(coeffs, x):
    """Horner evaluation of a coefficient polynomial at an arbitrary point x."""
    acc = 0
    for c in reversed(coeffs):
        acc = (acc * x + c) % P
    return acc
