"""
ML-DSA-44 verify AIR — sub-circuit 2: the mod-Q MULTIPLY-REDUCE gadget  c = (a * b) mod Q
(Q = 8380417), the arithmetic ATOM the 256-point negacyclic NTT and the w' = A·z - c·t1·2^d computation are
built from. See doc/zk-signature-aggregation.md.

EMULATING Q over Goldilocks (P = 2^64 - 2^32 + 1): a, b < Q < 2^23, so the product a*b < Q^2 < 2^46 < P fits ONE
Goldilocks element with NO wraparound. Reduce-by-HINT: the prover supplies the quotient K and remainder C with
a*b = K*Q + C, and the AIR checks that identity over Goldilocks (exact, no wrap) PLUS C in [0, Q) and K in
[0, Q) (both hold since a*b < Q^2 => K = a*b//Q < Q). The two range checks reuse the exact two-sided
bit-decomposition pattern from mldsa_norm_air (Q-1 < 2^23, so 23 bits each side).

STATEMENT (verifier-authoritative): the verifier PINS the public factor pair (a, b) per row via boundaries; the
AIR proves the unique canonical (C, K) with C = a*b mod Q. C is a WITNESS (an intermediate the full circuit
feeds onward), proven correct WITHOUT the verifier computing the product. All constraints are per-row, degree
<= 2. Rows 0..M-1 carry the M multiplies; rows M..T-2 are valid (0*0) padding; the last row is unconstrained pad.
"""
from execnode.stark import field as F, stark, backend as B
from execnode.stark import mldsa_params as P

Q = P.Q
NBITS = (Q - 1).bit_length()            # 23  (Q-1 = 8380416 < 2^23)
POW2 = [1 << i for i in range(NBITS)]

# column layout
A = 0                                   # public factor a (pinned)
Bc = 1                                  # public factor b (pinned)
C = 2                                   # witness product c = a*b mod Q
K = 3                                   # witness quotient k = a*b // Q
C0 = 4                                  # c decomposed into NBITS bits
CQ0 = C0 + NBITS                        # (Q-1 - c) bits  -> c <= Q-1
K0 = CQ0 + NBITS                        # k bits
KQ0 = K0 + NBITS                        # (Q-1 - k) bits  -> k <= Q-1
W = KQ0 + NBITS                         # total width = 4 + 4*NBITS = 96
MAX_DEGREE = 2


def _row(a, b):
    a %= Q; b %= Q
    prod = a * b
    k, c = divmod(prod, Q)              # a*b = k*Q + c, c in [0,Q), k in [0,Q)
    row = [0] * W
    row[A] = a; row[Bc] = b; row[C] = c; row[K] = k
    for i in range(NBITS):
        row[C0 + i] = (c >> i) & 1
        row[CQ0 + i] = ((Q - 1 - c) >> i) & 1
        row[K0 + i] = (k >> i) & 1
        row[KQ0 + i] = ((Q - 1 - k) >> i) & 1
    return row


def _next_pow2(n):
    p = 1
    while p < n:
        p <<= 1
    return p


def build_trace(pairs):
    """pairs: list of (a, b) factor pairs in [0, Q). Returns (rows, T, M)."""
    M = len(pairs)
    rows = [_row(int(a), int(b)) for a, b in pairs]
    T = _next_pow2(M + 1)                # +1 so row M-1 is a constrained `cur`
    pad = _row(0, 0)
    while len(rows) < T:
        rows.append(list(pad))
    return rows, T, M


def products(pairs):
    """The canonical c = a*b mod Q per pair — what the AIR proves (for callers/tests)."""
    return [(int(a) % Q) * (int(b) % Q) % Q for a, b in pairs]


def _boolean(col):
    return lambda c, n, per, _k=col: F.sub(F.mul(c[_k], c[_k]), c[_k])


def _bitsum(cur, base):
    acc = 0
    for i in range(NBITS):
        acc = F.add(acc, F.mul(cur[base + i], POW2[i]))
    return acc


def transitions():
    """Per-row (cur-only) constraints, all degree <= 2:
       (1) every bit boolean;
       (2) Σ c_bits·2^i == c ,  Σ (Q-1-c)_bits·2^i == Q-1-c   (c in [0, Q));
       (3) Σ k_bits·2^i == k ,  Σ (Q-1-k)_bits·2^i == Q-1-k   (k in [0, Q));
       (4) a·b - k·Q - c == 0                                 (the reduce identity, exact over Goldilocks)."""
    cons = []
    for base in (C0, CQ0, K0, KQ0):
        cons += [_boolean(base + i) for i in range(NBITS)]
    cons.append(lambda c, n, per: F.sub(_bitsum(c, C0), c[C]))
    cons.append(lambda c, n, per: F.sub(_bitsum(c, CQ0), F.sub(Q - 1, c[C])))
    cons.append(lambda c, n, per: F.sub(_bitsum(c, K0), c[K]))
    cons.append(lambda c, n, per: F.sub(_bitsum(c, KQ0), F.sub(Q - 1, c[K])))
    cons.append(lambda c, n, per: F.sub(F.mul(c[A], c[Bc]), F.add(F.mul(c[K], Q), c[C])))
    return cons


def _boundaries(pairs, T):
    """Pin each row's public factor pair (a, b) — verifier-authoritative."""
    bnds = []
    for i, (a, b) in enumerate(pairs):
        bnds.append((i, A, int(a) % Q))
        bnds.append((i, Bc, int(b) % Q))
    return bnds


def prove(pairs, num_queries=stark.NUM_QUERIES, backend=None):
    """Prove c = a*b mod Q for every public (a, b) in `pairs`. Returns the proof."""
    bk = backend or B.RECURSION
    rows, T, _M = build_trace(pairs)
    return stark.prove(rows, transitions(), _boundaries(pairs, T),
                       max_degree=MAX_DEGREE, num_queries=num_queries, backend=bk)


def verify(proof, pairs, num_queries=stark.NUM_QUERIES, backend=None):
    """Verify the mod-Q products for PUBLIC `pairs`: rebuild the factor boundaries + check the STARK.
    Returns (ok, reason)."""
    try:
        bk = backend or B.RECURSION
        T = proof["T"]
        return stark.verify(proof, transitions(), _boundaries(pairs, T),
                            max_degree=MAX_DEGREE, num_queries=num_queries, backend=bk)
    except Exception as e:
        return False, f"malformed modq proof: {e}"
