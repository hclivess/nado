"""
ML-DSA-44 verify AIR — sub-circuit 6 (THE big one): KECCAK-f[1600] / SHAKE in-circuit.

WHY IT MUST BE KECCAK. FIPS 204 fixes ML-DSA's hashing to SHAKE-128/256. The verifier uses it in four places:
ExpandA (SHAKE128 rejection-samples the k x l matrix A from rho — by far the most hashing), tr = SHAKE256(pk),
mu = SHAKE256(tr || m), SampleInBall (expands c_tilde into the challenge polynomial), and the final
c_tilde == SHAKE256(mu || w1) comparison. The STARK-friendly algebraic sponge (alghash2) CANNOT substitute: it
would change the bytes being hashed, so the circuit would no longer verify the signatures that actually exist
on chain or in the browser. Keccak must be proven as-is.

REPRESENTATION. Keccak-f[1600] is bit-oriented (a 5x5x64 state over GF(2)), which is hostile to a large-prime
field — so the state is carried as 1600 BOOLEAN columns (one per bit) and every step is expressed in GF(2)
arithmetic lifted to Goldilocks:
    XOR(a,b)      = a + b - 2ab                     (degree 2)
    NOT(a)        = 1 - a                           (degree 1)
    AND(a,b)      = a*b                             (degree 2)
    chi: A[x] = A[x] XOR ((NOT A[x+1]) AND A[x+2])  (degree 3 in one step -> split via an auxiliary product)
theta/rho/pi are linear/permutation-only (free: they are re-indexings and XOR chains), iota XORs a public round
constant (degree 1). One trace ROW per round-step keeps every constraint at degree <= 2 by carrying the chi
AND-products in auxiliary columns.

SCOPE OF THIS MODULE. It provides: the reference permutation + sponge (validated against hashlib.shake_*), the
bit-level GF(2) gadget helpers, and a PROVEN single-round AIR (the unit the full 24-round permutation and then
the sponge are composed from — same compose-the-atom strategy that took the butterfly to the full 256-point
NTT). The multi-round + absorb/squeeze composition builds on this.

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


# ---- single-round AIR (the composable unit) ---------------------------------------------------------
# Columns: 1600 input bits | 1600 output bits | 1600 chi AND-products (the degree-splitting auxiliaries).
IN0 = 0
OUT0 = STATE_BITS
AUX0 = 2 * STATE_BITS
W = 3 * STATE_BITS
MAX_DEGREE = 2


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


def round_trace_row(state_in, rc):
    """One row: input bits, output bits, and the chi AND-products that keep every constraint degree <= 2."""
    state_out = keccak_round(state_in, rc)
    row = [0] * W
    bin_ = _bits_of_state(state_in)
    bout = _bits_of_state(state_out)
    for i in range(STATE_BITS):
        row[IN0 + i] = bin_[i]
        row[OUT0 + i] = bout[i]
    # recompute the post-rho/pi B matrix to expose the chi AND terms as witnesses
    A = [[state_in[x + 5 * y] for y in range(5)] for x in range(5)]
    C = [A[x][0] ^ A[x][1] ^ A[x][2] ^ A[x][3] ^ A[x][4] for x in range(5)]
    D = [C[(x - 1) % 5] ^ _rotl(C[(x + 1) % 5], 1) for x in range(5)]
    for x in range(5):
        for y in range(5):
            A[x][y] ^= D[x]
    Bm = [[0] * 5 for _ in range(5)]
    for x in range(5):
        for y in range(5):
            Bm[y][(2 * x + 3 * y) % 5] = _rotl(A[x][y], ROT[x][y])
    for x in range(5):
        for y in range(5):
            prod = (~Bm[(x + 1) % 5][y]) & Bm[(x + 2) % 5][y] & ((1 << LANE_BITS) - 1)
            base = AUX0 + (x + 5 * y) * LANE_BITS
            for i in range(LANE_BITS):
                row[base + i] = (prod >> i) & 1
    return row, state_out


# ---- the round CONSTRAINTS ---------------------------------------------------------------------------
def _bidx(x, y, i):
    """Column offset of bit i of lane (x, y) in a 1600-bit block (lane index = x + 5y)."""
    return (x + 5 * y) * LANE_BITS + i


def _lin_theta_pi(cur, x, y, i):
    """The value of post-theta/rho/pi bit (x,y,i) as a LINEAR (XOR-only) expression over the INPUT bits.
    theta: A[x][y] ^= D[x] where D[x] = C[x-1] ^ rot(C[x+1],1) and C[x] = XOR over y of A[x][y];
    rho+pi: B[y][2x+3y] = rot(A[x][y], ROT[x][y]) — i.e. B lane (X,Y) is a rotation of a single A lane.
    Returns the field expression for B[x][y] bit i (built from `cur`, all XORs, degree 1)."""
    # invert pi: B[X][Y] comes from A[x0][y0] with X = y0, Y = (2*x0 + 3*y0) % 5
    for x0 in range(5):
        for y0 in range(5):
            if y0 == x and (2 * x0 + 3 * y0) % 5 == y:
                src_x, src_y, rot = x0, y0, ROT[x0][y0]
                break
        else:
            continue
        break
    j = (i - rot) % LANE_BITS                      # un-rotate: B bit i comes from A bit (i - rot)
    # A'[src] = A[src] ^ D[src_x] ; D[x] = C[x-1] ^ rot(C[x+1], 1)
    v = cur[_bidx(src_x, src_y, j)]
    for yy in range(5):                            # C[src_x - 1] bit j
        v = xor(v, cur[_bidx((src_x - 1) % 5, yy, j)])
    for yy in range(5):                            # rot(C[src_x + 1], 1) bit j  == C[src_x+1] bit (j-1)
        v = xor(v, cur[_bidx((src_x + 1) % 5, yy, (j - 1) % LANE_BITS)])
    return v


def round_transitions(rc):
    """Per-row constraints proving one Keccak-f round, all degree <= 2:
       (1) every input/output/aux column is boolean;
       (2) each aux column is the chi AND-product: aux = (NOT B[x+1]) AND B[x+2]  (degree 2 in the
           theta/pi-linear expressions, which are themselves degree 1 in the input bits);
       (3) each output bit = B[x][y] XOR aux, with iota's round-constant bit XORed into lane (0,0).
    `rc` is this round's public round constant."""
    cons = []
    for k in range(W):
        cons.append(lambda c, n, per, _k=k: F.sub(F.mul(c[_k], c[_k]), c[_k]))

    def make_aux(x, y, i):
        def con(c, n, per):
            b1 = _lin_theta_pi(c, (x + 1) % 5, y, i)
            b2 = _lin_theta_pi(c, (x + 2) % 5, y, i)
            return F.sub(c[AUX0 + _bidx(x, y, i)], andb(notb(b1), b2))
        return con

    def make_out(x, y, i, rc_bit):
        def con(c, n, per):
            b = _lin_theta_pi(c, x, y, i)
            v = xor(b, c[AUX0 + _bidx(x, y, i)])
            if rc_bit:
                v = xor(v, 1)
            return F.sub(c[OUT0 + _bidx(x, y, i)], v)
        return con

    for x in range(5):
        for y in range(5):
            for i in range(LANE_BITS):
                cons.append(make_aux(x, y, i))
                rc_bit = ((rc >> i) & 1) if (x == 0 and y == 0) else 0
                cons.append(make_out(x, y, i, rc_bit))
    return cons


def prove_round(state_in, rc, num_queries=stark.NUM_QUERIES, backend=None):
    """Prove ONE Keccak-f round. Returns (proof, state_out)."""
    bk = backend or B.RECURSION
    row, state_out = round_trace_row(state_in, rc)
    rows = [row, list(row)]                        # T must be a power of 2; the constraints are per-row
    bnds = [(0, IN0 + i, row[IN0 + i]) for i in range(STATE_BITS)]
    bnds += [(0, OUT0 + i, row[OUT0 + i]) for i in range(STATE_BITS)]
    proof = stark.prove(rows, round_transitions(rc), bnds, max_degree=MAX_DEGREE,
                        num_queries=num_queries, backend=bk)
    return proof, state_out


def verify_round(proof, state_in, state_out, rc, num_queries=stark.NUM_QUERIES, backend=None):
    """Verify a round proof against the PUBLIC input and claimed output states."""
    try:
        bk = backend or B.RECURSION
        bin_ = _bits_of_state(state_in)
        bout = _bits_of_state(state_out)
        bnds = [(0, IN0 + i, bin_[i]) for i in range(STATE_BITS)]
        bnds += [(0, OUT0 + i, bout[i]) for i in range(STATE_BITS)]
        return stark.verify(proof, round_transitions(rc), bnds, max_degree=MAX_DEGREE,
                            num_queries=num_queries, backend=bk)
    except Exception as e:
        return False, f"malformed keccak round proof: {e}"
