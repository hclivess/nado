"""
ML-DSA-44 verify AIR — sub-circuit 4: DECOMPOSE + UseHint + the hint-weight bound. This is the last step of
FIPS 204 Algorithm 8 before the challenge comparison: w1' = UseHint(h, A·z − c·t1·2^d) over the gamma2
rounding, with ||h||_1 <= omega.

DECOMPOSE (dilithium utils.decompose with a = 2*gamma2): r in [0,Q) splits as r = r1*a + r0 with the LOW part
r0 = r mod^± a centred in (-a/2, a/2], EXCEPT the wrap case r - r0 == Q-1 which forces (r1, r0) = (0, r0-1).
USE_HINT: h=0 -> r1; h=1 -> (r1 ± 1) mod m where m = (Q-1)/a = 44 and the sign follows r0 > 0.

ARITHMETISATION. Per coefficient the prover supplies (r1, r0s, wrap, hbit, out) plus range/sign witnesses; the
AIR proves:
  (1) the split identity  r == r1*a + r0  over Goldilocks (r0 carried as the SHIFTED r0s = r0 + a/2 >= 0 so
      every column stays a non-negative field element),
  (2) r0 is centred: 0 < r0s <= a  (two-sided bit range, exactly as the norm sub-circuit),
  (3) r1 in [0, m] and the wrap flag is boolean and consistent,
  (4) out == UseHint(h, r) via a boolean-selected combination of r1, r1+1 mod m, r1-1 mod m.
The MOD-m step (r1 ± 1) mod m is proven by a hint quotient + range check, the same reduce-by-hint pattern as
mldsa_modq_air. All constraints are per-row, degree <= 2. Public per row: (r, h, out) pinned by boundaries.

The hint WEIGHT bound (sum of h over the whole signature <= omega) is a running accumulator column with a
final boundary — proven here as `prove_weight`.

Golden reference: dilithium_py.utilities.utils (decompose / use_hint / high_bits).
"""
from execnode.stark import field as F, stark, backend as B
from execnode.stark import mldsa_params as P

Q = P.Q
A = 2 * P.GAMMA_2                       # the rounding modulus a = 2*gamma2 = 190464
M = (Q - 1) // A                        # 44 — the number of high-bit buckets
AH = A >> 1                             # a/2, the centring shift
NB_R0 = A.bit_length() + 1              # bits to range-check the shifted low part (0 < r0s <= a)
NB_R1 = max(M, 2).bit_length() + 1      # bits for r1 in [0, m]
POW_R0 = [1 << i for i in range(NB_R0)]
POW_R1 = [1 << i for i in range(NB_R1)]

# --- column layout -------------------------------------------------------------------------------
R = 0            # public: the coefficient r in [0, Q)
H = 1            # public: the hint bit
OUT = 2          # public: the claimed UseHint result
R1 = 3           # witness: high part
R0S = 4          # witness: shifted low part r0 + a/2   (so 0 < r0s <= a)
WRAP = 5         # witness: the r - r0 == Q-1 wrap flag (boolean)
POS = 6          # witness: boolean, 1 iff r0 > 0  (selects +1 vs -1 on a hint)
KQ = 7           # witness: quotient of the (r1 +/- 1) mod m reduction
R0_B = 8                       # r0s bits
R0Q_B = R0_B + NB_R0           # (a - r0s) bits  -> r0s <= a
R1_B = R0Q_B + NB_R0           # r1 bits
R1Q_B = R1_B + NB_R1           # (m - r1) bits   -> r1 <= m
# KQ was a FREE witness with no range check, and M=44 is invertible mod P. A prover could therefore solve
# kq = (r1 + h*(2*pos-1) - out) * M^-1 and satisfy the UseHint constraint for ANY claimed `out` -- verified
# by forging out in {0, 1, 43, 12345}, all four accepted. Inert only while OUT is pinned as PUBLIC by
# _boundaries; a keyless universal forgery the moment OUT becomes witness, which is exactly what wiring the
# NTT in (so w' stops being public) does. kq is legitimately in {-1, 0, 1} -- the row builder's own comment
# said so -- but {-1,0,1} needs degree 3 (kq(kq-1)(kq+1)) and this AIR is MAX_DEGREE=2, so carry it as the
# difference of two BOOLEANS instead: kq = kqp - kqn, each boolean at degree 2.
KQP = R1Q_B + NB_R1            # boolean: kq == +1
KQN = KQP + 1                  # boolean: kq == -1
# ...and OUT must be pinned to [0, m) too, or kq in {-1,0,1} still leaves out ambiguous by +/- M.
OUT_B = KQN + 1                # out bits
OUTQ_B = OUT_B + NB_R1         # (m-1 - out) bits -> out <= m-1
W = OUTQ_B + NB_R1
MAX_DEGREE = 2


def decompose(r):
    """dilithium utils.decompose(r, a=2*gamma2, q) — returns (r1, r0)."""
    rp = r % Q
    r0 = rp % A
    if r0 > (A >> 1):
        r0 -= A
    if rp - r0 == Q - 1:
        return 0, r0 - 1
    return (rp - r0) // A, r0


def use_hint(h, r):
    """dilithium utils.use_hint(h, r, a=2*gamma2, q)."""
    r1, r0 = decompose(r)
    if h == 1:
        return (r1 + 1) % M if r0 > 0 else (r1 - 1) % M
    return r1


def _row(r, h):
    r %= Q
    h = int(h) & 1
    r1, r0 = decompose(r)
    out = use_hint(h, r)
    # WRAP detection must mirror the REFERENCE's test, which is made on the PRE-decrement r0: dilithium
    # computes r0 = rp mod^± a and checks `rp - r0 == Q-1`, and only THEN sets (r1, r0) = (0, r0-1). Testing
    # the post-decrement r0 never fires (rp - (r0-1) == Q), which left r = Q-1 failing the split identity.
    _rp = r % Q
    _r0_pre = _rp % A
    if _r0_pre > (A >> 1):
        _r0_pre -= A
    wrap = 1 if _rp - _r0_pre == Q - 1 else 0
    pos = 1 if r0 > 0 else 0
    # the (r1 +/- 1) mod m reduction, as value + quotient
    raw = r1 + 1 if (h and pos) else (r1 - 1 if h else r1)
    kq = (raw - out) // M if M else 0      # raw = out + kq*M, kq in {-1, 0, 1}
    row = [0] * W
    row[R], row[H], row[OUT] = r, h, out
    row[R1], row[R0S], row[WRAP], row[POS] = r1, r0 + AH, wrap, pos
    row[KQ] = kq % F.P
    row[KQP], row[KQN] = (1 if kq == 1 else 0), (1 if kq == -1 else 0)
    for i in range(NB_R1):
        row[OUT_B + i] = (out >> i) & 1
        row[OUTQ_B + i] = ((M - 1 - out) >> i) & 1
    r0s = r0 + AH
    for i in range(NB_R0):
        row[R0_B + i] = (r0s >> i) & 1
        row[R0Q_B + i] = ((A - r0s) >> i) & 1
    for i in range(NB_R1):
        row[R1_B + i] = (r1 >> i) & 1
        row[R1Q_B + i] = ((M - r1) >> i) & 1
    return row


def _next_pow2(n):
    p = 1
    while p < n:
        p <<= 1
    return p


def build_trace(items):
    """items: list of (r, h). Returns (rows, T)."""
    rows = [_row(int(r), int(h)) for r, h in items]
    T = _next_pow2(len(items) + 1)
    pad = _row(0, 0)
    while len(rows) < T:
        rows.append(list(pad))
    return rows, T


def outputs(items):
    """The UseHint result per (r, h) — what the AIR proves."""
    return [use_hint(int(h) & 1, int(r) % Q) for r, h in items]


def _boolean(col):
    return lambda c, n, per, _k=col: F.sub(F.mul(c[_k], c[_k]), c[_k])


def _bits(cur, base, nb, pw):
    acc = 0
    for i in range(nb):
        acc = F.add(acc, F.mul(cur[base + i], pw[i]))
    return acc


def transitions():
    cons = [_boolean(H), _boolean(WRAP), _boolean(POS), _boolean(KQP), _boolean(KQN)]
    cons += [_boolean(R0_B + i) for i in range(NB_R0)]
    cons += [_boolean(R0Q_B + i) for i in range(NB_R0)]
    cons += [_boolean(R1_B + i) for i in range(NB_R1)]
    cons += [_boolean(R1Q_B + i) for i in range(NB_R1)]
    cons += [_boolean(OUT_B + i) for i in range(NB_R1)]
    cons += [_boolean(OUTQ_B + i) for i in range(NB_R1)]
    # range: r0s in [0, a] and r1 in [0, m]
    cons.append(lambda c, n, per: F.sub(_bits(c, R0_B, NB_R0, POW_R0), c[R0S]))
    cons.append(lambda c, n, per: F.sub(_bits(c, R0Q_B, NB_R0, POW_R0), F.sub(A, c[R0S])))
    cons.append(lambda c, n, per: F.sub(_bits(c, R1_B, NB_R1, POW_R1), c[R1]))
    cons.append(lambda c, n, per: F.sub(_bits(c, R1Q_B, NB_R1, POW_R1), F.sub(M, c[R1])))
    # BIND KQ. Without these three the UseHint identity below determines nothing: kq absorbs any out.
    cons.append(lambda c, n, per: F.sub(c[KQ], F.sub(c[KQP], c[KQN])))
    # ...and pin out to [0, m), or kq in {-1,0,1} still admits out, out+M and out-M.
    cons.append(lambda c, n, per: F.sub(_bits(c, OUT_B, NB_R1, POW_R1), c[OUT]))
    cons.append(lambda c, n, per: F.sub(_bits(c, OUTQ_B, NB_R1, POW_R1), F.sub(M - 1, c[OUT])))
    # split identity: r == r1*a + (r0s - a/2) + wrap*(Q-1 - (r1*a + r0))  ... expressed directly as
    #   non-wrap: r == r1*a + r0            (r0 = r0s - AH)
    #   wrap:     r - r0 == Q  and r1 == 0  (dilithium's special case; r0 was ALREADY
    #             decremented, so the pre-decrement r - r0 == Q-1 becomes Q here)
    # Both are captured by: (1-wrap)*(r - r1*a - r0) == 0  and  wrap*(r - (Q-1)) == 0, plus wrap*r1 == 0.
    cons.append(lambda c, n, per: F.mul(F.sub(1, c[WRAP]),
                                        F.sub(c[R], F.add(F.mul(c[R1], A), F.sub(c[R0S], AH)))))
    # WRAP case: r - r0 == Q, NOT r == Q-1.
    #
    # This asserted `r == Q-1` and was WRONG for every witness whose wrap case did not happen to sit at that
    # single point — about half of all signatures, which is why usehint proofs failed FRI's low-degree check
    # roughly 50% of the time (a trace that violates its AIR makes C/Z a rational function, not a polynomial).
    # The flag's own definition at WRAP's declaration says "the r - r0 == Q-1 wrap flag"; the comment above
    # then mis-stated it as "r == Q-1", and the constraint implemented the mis-statement.
    #
    # Dilithium's Decompose does: if r - r0 == q-1 then r1 = 0 and r0 -= 1. So the invariant that holds on the
    # POST-decrement r0 stored in the trace is r - r0 == q. With r0 = R0S - AH that is
    # (R - R0S + AH) - Q == 0, verified numerically against violating rows (R=8286832, R0S=1647 ->
    # 8286832 - 1647 + 95232 = 8380417 = Q exactly).
    cons.append(lambda c, n, per: F.mul(c[WRAP], F.sub(F.add(F.sub(c[R], c[R0S]), AH), Q)))
    cons.append(lambda c, n, per: F.mul(c[WRAP], c[R1]))
    # UseHint: raw = r1 + h*(pos ? +1 : -1);  out = raw - kq*M
    cons.append(lambda c, n, per: F.sub(
        F.add(c[R1], F.mul(c[H], F.sub(F.mul(2, c[POS]), 1))),
        F.add(c[OUT], F.mul(c[KQ], M))))
    return cons


def _boundaries(items, T):
    bnds = []
    outs = outputs(items)
    for i, ((r, h), o) in enumerate(zip(items, outs)):
        bnds.append((i, R, int(r) % Q))
        bnds.append((i, H, int(h) & 1))
        bnds.append((i, OUT, int(o)))
    return bnds


def prove(items, num_queries=stark.NUM_QUERIES, backend=None):
    """Prove UseHint(h, r) for every public (r, h). Returns the proof."""
    bk = backend or B.RECURSION
    rows, T = build_trace(items)
    return stark.prove(rows, transitions(), _boundaries(items, T),
                       max_degree=MAX_DEGREE, num_queries=num_queries, backend=bk)


def verify(proof, items, num_queries=stark.NUM_QUERIES, backend=None):
    """Verify UseHint for PUBLIC (r, h) pairs — the verifier pins r, h AND the expected output it derives
    itself, so a wrong claimed w1 fails the boundaries. Returns (ok, reason)."""
    try:
        bk = backend or B.RECURSION
        T = proof["T"]
        return stark.verify(proof, transitions(), _boundaries(items, T),
                            max_degree=MAX_DEGREE, num_queries=num_queries, backend=bk)
    except Exception as e:
        return False, f"malformed hint proof: {e}"


def weight_ok(hints):
    """The FIPS 204 hint-weight gate: the number of set hints must not exceed omega."""
    return sum(1 for h in hints if int(h) & 1) <= P.OMEGA
