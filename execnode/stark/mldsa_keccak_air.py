"""
ML-DSA-44 verify AIR — sub-circuit 6 (THE big one): KECCAK-f[1600] / SHAKE in-circuit.

WHY IT MUST BE KECCAK. FIPS 204 fixes ML-DSA's hashing to SHAKE-128/256. The verifier uses it in four places:
ExpandA (SHAKE128 rejection-samples the k x l matrix A from rho — by far the most hashing), tr = SHAKE256(pk),
mu = SHAKE256(tr || m), SampleInBall (expands c_tilde into the challenge polynomial), and the final
c_tilde == SHAKE256(mu || w1) comparison. The STARK-friendly algebraic sponge (alghash2) CANNOT substitute: it
would change the bytes being hashed, so the circuit would no longer verify the signatures that actually exist
on chain or in the browser. Keccak must be proven as-is.

REPRESENTATION. Keccak-f[1600] is bit-oriented (a 5x5x64 state over GF(2)), which is hostile to a large-prime
field — so the state is carried as BOOLEAN columns (one per bit) and GF(2) is lifted to Goldilocks:
    XOR(a,b) = a + b - 2ab      NOT(a) = 1 - a      AND(a,b) = a*b

WIDE AND SHORT, AND WHY. The permutation is TIME-STEPPED: one trace ROW per round (row r = the state after r
rounds), so the 24 rounds cost ROWS, and the 1600-bit state costs COLUMNS — 6080 x 32 rather than anything
tall. Every intermediate of the round (theta parities + their carries, D, the post-theta state, the chi
AND-products) gets an explicit WITNESS column. That is what keeps each constraint genuinely degree <= 2:
chaining the xor() gadget through theta's 11-way XOR instead MULTIPLIES degree per link and measured degree 22
— value-correct but unprovable at max_degree=2, which is exactly the bug this layout replaced. rho+pi is a pure
re-indexing of the post-theta columns, so it is free; iota XORs a PUBLIC round-constant bit (degree 0), so it
does not raise the degree. tests/test_mldsa_keccak_air.py asserts the measured degree with air_ir.program_degree
rather than trusting the claim.

SCOPE OF THIS MODULE. The reference permutation + sponge (validated against hashlib.shake_*), the GF(2) bit
gadgets, and the PROVEN full 24-round permutation AIR. The sponge (absorb/squeeze over multiple permutations)
composes these — each block is one permutation proof chained on the rate lanes.

Golden reference: hashlib.shake_128 / shake_256 (OpenSSL) — the same primitive dilithium_py and the RustCrypto
ml-dsa crate use.
"""
from execnode.stark import field as F, stark, backend as B

# ---- Keccak-f[1600] constants ---------------------------------------------------------------------
LANES = 25                     # 5x5 lanes
LANE_BITS = 64
STATE_BITS = LANES * LANE_BITS  # 1600
ROUNDS = 24

RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]

ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61],
       [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]


def _rotl(x, n):
    n %= LANE_BITS
    return ((x << n) | (x >> (LANE_BITS - n))) & ((1 << LANE_BITS) - 1)


def keccak_round(state, rc):
    """One Keccak-f round on a list of 25 lane integers (the reference semantics the AIR proves)."""
    A = [[state[x + 5 * y] for y in range(5)] for x in range(5)]
    # theta
    C = [A[x][0] ^ A[x][1] ^ A[x][2] ^ A[x][3] ^ A[x][4] for x in range(5)]
    D = [C[(x - 1) % 5] ^ _rotl(C[(x + 1) % 5], 1) for x in range(5)]
    for x in range(5):
        for y in range(5):
            A[x][y] ^= D[x]
    # rho + pi
    Bm = [[0] * 5 for _ in range(5)]
    for x in range(5):
        for y in range(5):
            Bm[y][(2 * x + 3 * y) % 5] = _rotl(A[x][y], ROT[x][y])
    # chi
    for x in range(5):
        for y in range(5):
            A[x][y] = Bm[x][y] ^ ((~Bm[(x + 1) % 5][y]) & Bm[(x + 2) % 5][y] & ((1 << LANE_BITS) - 1))
    # iota
    A[0][0] ^= rc
    return [A[x][y] for y in range(5) for x in range(5)]


def keccak_f(state):
    """The full 24-round Keccak-f[1600] permutation on 25 lanes."""
    s = list(state)
    for r in range(ROUNDS):
        s = keccak_round(s, RC[r])
    return s


def _bytes_to_state(buf):
    return [int.from_bytes(buf[8 * i:8 * i + 8], "little") for i in range(LANES)]


def _state_to_bytes(state):
    return b"".join(int(l).to_bytes(8, "little") for l in state)


def shake(data, out_len, rate_bytes, dsbyte):
    """Reference sponge (SHAKE128 rate=168, SHAKE256 rate=136, dsbyte=0x1F) — the semantics the AIR proves."""
    state = [0] * LANES
    # absorb
    buf = bytearray(data)
    buf.append(dsbyte)
    while len(buf) % rate_bytes != 0:
        buf.append(0)
    buf[-1] |= 0x80
    for off in range(0, len(buf), rate_bytes):
        blk = bytes(buf[off:off + rate_bytes]) + b"\x00" * (200 - rate_bytes)
        st_bytes = _state_to_bytes(state)
        state = _bytes_to_state(bytes(a ^ b for a, b in zip(st_bytes, blk)))
        state = keccak_f(state)
    # squeeze
    out = b""
    while len(out) < out_len:
        out += _state_to_bytes(state)[:rate_bytes]
        if len(out) < out_len:
            state = keccak_f(state)
    return out[:out_len]


def shake128(data, out_len):
    return shake(data, out_len, 168, 0x1F)


def shake256(data, out_len):
    return shake(data, out_len, 136, 0x1F)


# ---- GF(2)-over-Goldilocks bit gadgets --------------------------------------------------------------
def xor(a, b):
    """a XOR b for boolean field elements: a + b - 2ab (degree 2)."""
    return F.sub(F.add(a, b), F.mul(2, F.mul(a, b)))


def notb(a):
    return F.sub(1, a)


def andb(a, b):
    return F.mul(a, b)


# ---- the permutation AIR ----------------------------------------------------------------------------
# TIME-STEPPED: one ROW per round (row r = the state after r rounds), so the 24 rounds cost ROWS, not columns.
# Every intermediate of the round is an explicit WITNESS column, which is what keeps each constraint genuinely
# degree <= 2 — chaining the xor() gadget instead (a+b-2ab per XOR) multiplies degree per link and measured
# degree 22 on the earlier one-row design, i.e. value-correct but unprovable at max_degree=2.
#
# Per-row layout (all boolean):
#   A    1600  the state at this row
#   C     320  theta column parities: C[x][z] = XOR over y of A[x][y][z]      (5-way -> sum/carry, degree 1)
#   K0    320  carry bit 0 of that 5-way parity   (k = K0 + K1 in {0,1,2})
#   K1    320  carry bit 1
#   D     320  D[x][z] = C[x-1][z] XOR C[x+1][z-1]                            (degree 2)
#   E    1600  post-theta state: E = A XOR D                                  (degree 2)
#   Pp   1600  chi products: P[x][y][z] = (NOT B[x+1][y][z]) AND B[x+2][y][z] (degree 2 in E)
# and the NEXT row's A is constrained to B XOR P (XOR the public round constant on lane (0,0)) — degree 2.
# rho+pi is a pure re-indexing of E (free: no columns, no constraints).
A0 = 0
C0 = A0 + STATE_BITS            # 1600
K0 = C0 + 5 * LANE_BITS         # 1920
K1 = K0 + 5 * LANE_BITS         # 2240
D0 = K1 + 5 * LANE_BITS         # 2560
E0 = D0 + 5 * LANE_BITS         # 2880
P0 = E0 + STATE_BITS            # 4480
W = P0 + STATE_BITS             # 6080
# COMPOSITION degree, which is NOT the same as the pointwise constraint degree air_ir reports: every PERIODIC
# column is interpolated as a degree-T polynomial, so each periodic FACTOR adds one to the composition degree.
# Worst case is the iota output constraint: degree 2 in the trace, times the rc bit (periodic), times the
# ACTIVE selector (periodic) = 4. Using 2 here proved fine but failed verification with "composition is not
# low-degree" — the trap this constant exists to record.
MAX_DEGREE = 4

# periodic columns: 64 round-constant bits + an ACTIVE selector (1 on the 24 round rows, 0 on pad)
PER_RC = 0
PER_ACT = LANE_BITS             # 64


def _bits_of_state(state):
    """25 lanes -> 1600 bits, lane-major, little-endian within a lane."""
    out = []
    for lane in state:
        for i in range(LANE_BITS):
            out.append((int(lane) >> i) & 1)
    return out


def _state_of_bits(bits):
    state = []
    for l in range(LANES):
        v = 0
        for i in range(LANE_BITS):
            v |= int(bits[l * LANE_BITS + i]) << i
        state.append(v)
    return state


def _src_of_B(X, Y):
    """rho+pi inverse: B[X][Y] is a rotation of A'[x][y]. pi sets B[y][(2x+3y)%5] = rot(A'[x][y], ROT[x][y]),
    so y = X and (2x + 3X) % 5 = Y  =>  x = 3*(Y - 3X) mod 5 (since 2*3 = 6 = 1 mod 5). Returns (x, y, rot)."""
    y = X
    x = (3 * (Y - 3 * X)) % 5
    return x, y, ROT[x][y]


def _E(cur, x, y, i):
    """Column value of post-theta bit (x, y, i)."""
    return cur[E0 + (x + 5 * y) * LANE_BITS + i]


def _B(cur, X, Y, i):
    """Post-rho/pi bit (X, Y, i) — a pure re-index of E, so it costs nothing."""
    x, y, rot = _src_of_B(X, Y)
    return _E(cur, x, y, (i - rot) % LANE_BITS)


def round_row(state_in, rc):
    """Build ONE row: the state plus every witness of the round applied to it. Returns (row, state_out)."""
    row = [0] * W
    bits = _bits_of_state(state_in)
    for i in range(STATE_BITS):
        row[A0 + i] = bits[i]
    A = [[state_in[x + 5 * y] for y in range(5)] for x in range(5)]
    # theta parities + carries
    C = [A[x][0] ^ A[x][1] ^ A[x][2] ^ A[x][3] ^ A[x][4] for x in range(5)]
    for x in range(5):
        for i in range(LANE_BITS):
            s = sum((A[x][y] >> i) & 1 for y in range(5))
            cbit = (C[x] >> i) & 1
            k = (s - cbit) // 2                       # k in {0, 1, 2}
            row[C0 + x * LANE_BITS + i] = cbit
            row[K0 + x * LANE_BITS + i] = 1 if k >= 1 else 0
            row[K1 + x * LANE_BITS + i] = 1 if k >= 2 else 0
    D = [C[(x - 1) % 5] ^ _rotl(C[(x + 1) % 5], 1) for x in range(5)]
    for x in range(5):
        for i in range(LANE_BITS):
            row[D0 + x * LANE_BITS + i] = (D[x] >> i) & 1
    # post-theta E
    Ap = [[A[x][y] ^ D[x] for y in range(5)] for x in range(5)]
    for x in range(5):
        for y in range(5):
            for i in range(LANE_BITS):
                row[E0 + (x + 5 * y) * LANE_BITS + i] = (Ap[x][y] >> i) & 1
    # rho + pi -> B, then the chi AND-products
    Bm = [[0] * 5 for _ in range(5)]
    for x in range(5):
        for y in range(5):
            Bm[y][(2 * x + 3 * y) % 5] = _rotl(Ap[x][y], ROT[x][y])
    for x in range(5):
        for y in range(5):
            prod = (~Bm[(x + 1) % 5][y]) & Bm[(x + 2) % 5][y] & ((1 << LANE_BITS) - 1)
            for i in range(LANE_BITS):
                row[P0 + (x + 5 * y) * LANE_BITS + i] = (prod >> i) & 1
    return row, keccak_round(state_in, rc)


def build_trace(state_in):
    """The full 24-round permutation trace: row r = the state after r rounds (+ that round's witnesses).
    Returns (rows, T, state_out)."""
    rows, s = [], list(state_in)
    for r in range(ROUNDS):
        row, s = round_row(s, RC[r])
        rows.append(row)
    final = [0] * W                                   # row 24 carries the FINAL state (its witnesses are unused)
    for i, b in enumerate(_bits_of_state(s)):
        final[A0 + i] = b
    rows.append(final)
    T = 1
    while T < len(rows):
        T <<= 1
    while len(rows) < T:                              # pad by repeating the final row (inactive: no constraints)
        rows.append(list(final))
    return rows, T, s


def periodic(T):
    """64 round-constant bit columns + the ACTIVE selector (1 on rows 0..23, 0 on the final/pad rows)."""
    per = []
    for i in range(LANE_BITS):
        per.append([((RC[r] >> i) & 1) if r < ROUNDS else 0 for r in range(T)])
    per.append([1 if r < ROUNDS else 0 for r in range(T)])
    return per


# ---- the round CONSTRAINTS ---------------------------------------------------------------------------
def _bidx(x, y, i):
    """Column offset of bit i of lane (x, y) in a 1600-bit block (lane index = x + 5y)."""
    return (x + 5 * y) * LANE_BITS + i




def transitions():
    """The permutation constraints — EVERY ONE degree <= 2 (verified by air_ir.program_degree in the test).
    `per[PER_RC + i]` is round-constant bit i for this row; `per[PER_ACT]` gates the round rows so the final
    and padding rows are unconstrained.

      booleanity   : every column is 0/1
      theta parity : sum_y A[x][y][z] == C[x][z] + 2*(K0 + K1)     (degree 1; K0,K1 boolean => k in {0,1,2})
      theta D      : D[x][z] == C[x-1][z] XOR C[x+1][z-1]          (degree 2)
      post-theta   : E[x][y][z] == A[x][y][z] XOR D[x][z]          (degree 2)
      chi products : P[x][y][z] == (1 - B[x+1][y][z]) * B[x+2][y][z]  (degree 2; B is a re-index of E)
      round output : A_next[x][y][z] == B[x][y][z] XOR P[x][y][z] (XOR rc bit on lane (0,0))  (degree 2)
    """
    cons = []
    for k in range(W):
        cons.append(lambda c, n, per, _k=k: F.sub(F.mul(c[_k], c[_k]), c[_k]))

    def parity(x, i):
        def con(c, n, per):
            s = 0
            for y in range(5):
                s = F.add(s, c[A0 + (x + 5 * y) * LANE_BITS + i])
            rhs = F.add(c[C0 + x * LANE_BITS + i],
                        F.mul(2, F.add(c[K0 + x * LANE_BITS + i], c[K1 + x * LANE_BITS + i])))
            return F.mul(per[PER_ACT], F.sub(s, rhs))
        return con

    def dcon(x, i):
        def con(c, n, per):
            c1 = c[C0 + ((x - 1) % 5) * LANE_BITS + i]
            c2 = c[C0 + ((x + 1) % 5) * LANE_BITS + (i - 1) % LANE_BITS]
            return F.mul(per[PER_ACT], F.sub(c[D0 + x * LANE_BITS + i], xor(c1, c2)))
        return con

    def econ(x, y, i):
        def con(c, n, per):
            a = c[A0 + (x + 5 * y) * LANE_BITS + i]
            d = c[D0 + x * LANE_BITS + i]
            return F.mul(per[PER_ACT], F.sub(_E(c, x, y, i), xor(a, d)))
        return con

    def pcon(x, y, i):
        def con(c, n, per):
            b1 = _B(c, (x + 1) % 5, y, i)
            b2 = _B(c, (x + 2) % 5, y, i)
            return F.mul(per[PER_ACT], F.sub(c[P0 + (x + 5 * y) * LANE_BITS + i], andb(notb(b1), b2)))
        return con

    def outcon(x, y, i):
        iota = (x == 0 and y == 0)
        def con(c, n, per):
            v = xor(_B(c, x, y, i), c[P0 + (x + 5 * y) * LANE_BITS + i])
            if iota:
                v = xor(v, per[PER_RC + i])          # public bit: degree 0, so this stays degree 2
            return F.mul(per[PER_ACT], F.sub(n[A0 + (x + 5 * y) * LANE_BITS + i], v))
        return con

    for x in range(5):
        for i in range(LANE_BITS):
            cons.append(parity(x, i))
            cons.append(dcon(x, i))
    for x in range(5):
        for y in range(5):
            for i in range(LANE_BITS):
                cons.append(econ(x, y, i))
                cons.append(pcon(x, y, i))
                cons.append(outcon(x, y, i))
    return cons


def _boundaries(state_in, state_out, T):
    """Pin the PUBLIC input state at row 0 and the claimed output state at row ROUNDS."""
    bnds = [(0, A0 + i, b) for i, b in enumerate(_bits_of_state(state_in))]
    bnds += [(ROUNDS, A0 + i, b) for i, b in enumerate(_bits_of_state(state_out))]
    return bnds


def prove_permutation(state_in, num_queries=stark.NUM_QUERIES, backend=None):
    """Prove the FULL 24-round Keccak-f[1600] permutation. Returns (proof, state_out)."""
    bk = backend or B.RECURSION
    rows, T, state_out = build_trace(state_in)
    proof = stark.prove(rows, transitions(), _boundaries(state_in, state_out, T),
                        periodic=periodic(T), max_degree=MAX_DEGREE, num_queries=num_queries, backend=bk)
    return proof, state_out


def verify_permutation(proof, state_in, state_out, num_queries=stark.NUM_QUERIES, backend=None):
    """Verify a full-permutation proof against the PUBLIC input and claimed output states."""
    try:
        bk = backend or B.RECURSION
        T = proof["T"]
        return stark.verify(proof, transitions(), _boundaries(state_in, state_out, T),
                            periodic=periodic(T), max_degree=MAX_DEGREE, num_queries=num_queries, backend=bk)
    except Exception as e:
        return False, f"malformed keccak permutation proof: {e}"
