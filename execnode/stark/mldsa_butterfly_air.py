"""
ML-DSA-44 verify AIR — sub-circuit 3a: the NTT BUTTERFLY gadget (the atom the 256-point negacyclic NTT is
composed from). One Cooley-Tukey butterfly over Q = 8380417:

    t    = zeta * b        (mod Q)          # b = coeffs[j+l], zeta = public twiddle
    out0 = a + t           (mod Q)          # coeffs[j]   <- a + t
    out1 = a - t           (mod Q)          # coeffs[j+l] <- a - t

dilithium_py.to_ntt runs the butterflies over UNREDUCED integers and reduces once at the end; reducing mod Q
per butterfly is equivalent (mod is a ring homomorphism) AND necessary for the AIR (values must stay < Q so the
Goldilocks emulation never overflows). See doc/zk-signature-aggregation.md.

Built on the mod-Q reduce-by-hint of mldsa_modq_air plus conditional add/sub-mod-Q: out0 = a+t-Q·carry0 (a+t in
[0,2Q) ⇒ one conditional subtract), out1 = a-t+Q·carry1 (a-t in (-Q,Q) ⇒ one conditional add), both range-checked
into [0,Q). Public (a, b, zeta) pinned per row (verifier-authoritative); t/out0/out1 are witnesses proven
correct. All constraints per-row, degree <= 2.
"""
from execnode.stark import field as F, stark, backend as B
from execnode.stark import mldsa_params as P

Q = P.Q
NB = (Q - 1).bit_length()               # 23
POW2 = [1 << i for i in range(NB)]

# value columns
A, Bc, Z = 0, 1, 2                       # public: a, b, zeta
T, KT = 3, 4                             # t = zeta*b mod Q ; quotient
O0, CA0 = 5, 6                           # out0 = a+t mod Q ; carry0 (0/1)
O1, CA1 = 7, 8                           # out1 = a-t mod Q ; carry1 (0/1)
# range-check bit blocks (each NB wide): value and (Q-1-value) for T, KT, O0, O1
_B = 9
T_B, TQ_B = _B, _B + NB
KT_B, KTQ_B = _B + 2 * NB, _B + 3 * NB
O0_B, O0Q_B = _B + 4 * NB, _B + 5 * NB
O1_B, O1Q_B = _B + 6 * NB, _B + 7 * NB
W = _B + 8 * NB                          # 9 + 8*23 = 193
MAX_DEGREE = 2


def _row(a, b, zeta):
    a %= Q; b %= Q; zeta %= Q
    prod = zeta * b
    kt, t = divmod(prod, Q)              # zeta*b = kt*Q + t
    s0 = a + t; ca0 = 1 if s0 >= Q else 0; o0 = s0 - Q * ca0        # (a+t) mod Q
    s1 = a - t; ca1 = 1 if s1 < 0 else 0; o1 = s1 + Q * ca1         # (a-t) mod Q
    row = [0] * W
    row[A], row[Bc], row[Z] = a, b, zeta
    row[T], row[KT] = t, kt
    row[O0], row[CA0] = o0, ca0
    row[O1], row[CA1] = o1, ca1
    for i in range(NB):
        row[T_B + i] = (t >> i) & 1;   row[TQ_B + i] = ((Q - 1 - t) >> i) & 1
        row[KT_B + i] = (kt >> i) & 1; row[KTQ_B + i] = ((Q - 1 - kt) >> i) & 1
        row[O0_B + i] = (o0 >> i) & 1; row[O0Q_B + i] = ((Q - 1 - o0) >> i) & 1
        row[O1_B + i] = (o1 >> i) & 1; row[O1Q_B + i] = ((Q - 1 - o1) >> i) & 1
    return row


def _next_pow2(n):
    p = 1
    while p < n:
        p <<= 1
    return p


def build_trace(bfs):
    """bfs: list of (a, b, zeta). Returns (rows, T)."""
    rows = [_row(int(a), int(b), int(z)) for a, b, z in bfs]
    Tn = _next_pow2(len(bfs) + 1)
    pad = _row(0, 0, 0)
    while len(rows) < Tn:
        rows.append(list(pad))
    return rows, Tn


def outputs(bfs):
    """(out0, out1) per butterfly — what the AIR proves (for callers/tests)."""
    out = []
    for a, b, z in bfs:
        a %= Q; b %= Q; t = (int(z) % Q) * b % Q
        out.append(((a + t) % Q, (a - t) % Q))
    return out


def _boolean(col):
    return lambda c, n, per, _k=col: F.sub(F.mul(c[_k], c[_k]), c[_k])


def _bitsum(cur, base):
    acc = 0
    for i in range(NB):
        acc = F.add(acc, F.mul(cur[base + i], POW2[i]))
    return acc


def transitions():
    cons = [_boolean(CA0), _boolean(CA1)]
    for base in (T_B, TQ_B, KT_B, KTQ_B, O0_B, O0Q_B, O1_B, O1Q_B):
        cons += [_boolean(base + i) for i in range(NB)]
    # reduce: zeta*b = kt*Q + t ; t,kt in [0,Q)
    cons.append(lambda c, n, per: F.sub(F.mul(c[Z], c[Bc]), F.add(F.mul(c[KT], Q), c[T])))
    cons.append(lambda c, n, per: F.sub(_bitsum(c, T_B), c[T]))
    cons.append(lambda c, n, per: F.sub(_bitsum(c, TQ_B), F.sub(Q - 1, c[T])))
    cons.append(lambda c, n, per: F.sub(_bitsum(c, KT_B), c[KT]))
    cons.append(lambda c, n, per: F.sub(_bitsum(c, KTQ_B), F.sub(Q - 1, c[KT])))
    # out0 = a + t - Q*carry0 ; out0 in [0,Q)
    cons.append(lambda c, n, per: F.sub(F.add(c[A], c[T]), F.add(F.mul(c[CA0], Q), c[O0])))
    cons.append(lambda c, n, per: F.sub(_bitsum(c, O0_B), c[O0]))
    cons.append(lambda c, n, per: F.sub(_bitsum(c, O0Q_B), F.sub(Q - 1, c[O0])))
    # out1 = a - t + Q*carry1 ; out1 in [0,Q)
    cons.append(lambda c, n, per: F.sub(F.add(F.sub(c[A], c[T]), F.mul(c[CA1], Q)), c[O1]))
    cons.append(lambda c, n, per: F.sub(_bitsum(c, O1_B), c[O1]))
    cons.append(lambda c, n, per: F.sub(_bitsum(c, O1Q_B), F.sub(Q - 1, c[O1])))
    return cons


def _boundaries(bfs, T):
    bnds = []
    for i, (a, b, z) in enumerate(bfs):
        bnds.append((i, A, int(a) % Q))
        bnds.append((i, Bc, int(b) % Q))
        bnds.append((i, Z, int(z) % Q))
    return bnds


def prove(bfs, num_queries=stark.NUM_QUERIES, backend=None):
    """Prove one butterfly per (a, b, zeta) in `bfs`. Returns the proof."""
    bk = backend or B.RECURSION
    rows, T = build_trace(bfs)
    return stark.prove(rows, transitions(), _boundaries(bfs, T),
                       max_degree=MAX_DEGREE, num_queries=num_queries, backend=bk)


def verify(proof, bfs, num_queries=stark.NUM_QUERIES, backend=None):
    try:
        bk = backend or B.RECURSION
        T = proof["T"]
        return stark.verify(proof, transitions(), _boundaries(bfs, T),
                            max_degree=MAX_DEGREE, num_queries=num_queries, backend=bk)
    except Exception as e:
        return False, f"malformed butterfly proof: {e}"
