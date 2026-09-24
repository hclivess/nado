"""
WIDE 2-output JOIN-SPLIT circuit (security review 2026-09-23, Z3; SHIELD_WIDE_HEIGHT) — joinsplit2's
statement over alghash2 (256-bit digests) instead of alghash (one 64-bit element):

  owner = H(nsk) · cm_in = commit(v_in, owner, rho_in) · fold(cm_in, path) = root · nf = H(nsk, rho_in) ·
  cm_out1 = commit(v_out1, o1, r1) · cm_out2 = commit(v_out2, o2, r2) ·
  v_in + public_value == v_out1 + v_out2 + fee ·  0 <= v_in, v_out1, v_out2 < 2^61   (the C-3 range proof)

Public: root, nf, cm_out1, cm_out2 (each 4 lanes), public_value, fee. Every hash is ONE alghash2 permutation
(znote.py: the frames fit the rate), so the trace is a sequence of 5+D PERMUTATION BLOCKS of BR = ROUNDS+1
rows — the shape merkle_update / recursion already prove — followed by the three 17-row range blocks:

    block 0        OWNER       row 0 = [5, DOM_ZOWNER, nsk(4), 0×2 | IV]         nsk is FOUR lanes (review 2026-09-24)
    block 1        COMMIT      row 0 = [7, DOM_ZCM, v_in, owner(4), rho_in | IV]   owner = block 0's output lanes
    blocks 2..D+1  MEMBERSHIP  row 0 = [ordered(prev output, sib) by dir | IV]      one level per block
    block D+2      NULLIFIER   row 0 = [6, DOM_ZNF, nsk(4), rho_in, 0 | IV]
    block D+3      OUTPUT1     row 0 = [7, DOM_ZCM, v_out1, o1(4), r1 | IV]       o1, r1 free witness
    block D+4      OUTPUT2     row 0 = [7, DOM_ZCM, v_out2, o2(4), r2 | IV]
    range region   3 × (16 nibble rows + 1 bind row)                                 as joinsplit2

A block's LAST row is its output, so every handoff reads the digest straight from the sponge lanes of that
row and pins the next block's row 0 with an absorb constraint gated by a structural selector: no capture
registers, no reset muxes. root / nf / cm_out1 / cm_out2 are boundary constraints on the four output lanes of
their block's last row. What crosses blocks as witness is only the five registers (nsk, rho, the three values,
held constant) and the path (SIB lanes + DIR, held within a level, free at each level's absorb row).

Degree: the round constraint is the x^7 S-box, so max_degree = ALPHA = 7 (blowup 16). At the pool's depth 12 the
real trace is 17 blocks × 55 + 51 = 986 rows, W = 28 witness columns.

ZERO KNOWLEDGE (security review 2026-09-23, Z1). joinsplit2 was not zero-knowledge: nsk, rho and every amount sat
in a CONSTANT column, a constant column's LDE is the constant, and every FRI query opens all columns — one
4-query transfer showed nsk eight times. Three things close it, all inside this circuit's own format (it has no
live proofs before SHIELD_WIDE_HEIGHT):
  * RANDOM_ROWS uniform rows follow the real ones (T = next_pow2(total + RANDOM_ROWS) = 2048 at depth 12) and
    every constraint that would reach into them — the register holds, the path holds, the conservation row
    check — is gated by the ACTIVE selector (1 while both rows of a transition are real). With more random rows
    than opened evaluations (2·NUM_QUERIES), what an opening shows of a witness column is independent of the
    secret it carries on the real rows;
  * ZK_RANDOMIZERS = next_pow2(ALPHA) = 8 uniform columns close the trace (unconstrained, appended by
    build_trace); stark.prove(zk=8) folds them into a uniformly random polynomial that masks the FRI input, so
    the layer roots, the fold openings and the final polynomial carry nothing of the witness;
  * every column leaf is salted (backend.leaf_salted), so the UNOPENED leaves of a commitment cannot be
    inverted by a 2^64 search of the value space.

RANGE PROOF (C-3, unchanged from joinsplit2): conservation is only mod P and P ≈ 2^64 barely exceeds the coin
range, so every note value is bit-decomposed into [0, 2^61) and, with the state-side |public_value|, fee ≤ 2^61
bound (state.MAX_EXIT_VALUE), the mod-P conservation equals INTEGER conservation. 2^61 is load-bearing (C-3b).
"""
from execnode.stark import field as F, alghash2 as A2, stark, znote as Z
from execnode.stark.recursion import _permute_snapshots

W_ST = A2.WIDTH                                   # 12 sponge lanes: columns 0..11
NSK = 12                                          # NSK..NSK+3: the spend key, four lanes (review 2026-09-24)
RHO, VIN, VOUT1, VOUT2, CONS = 16, 17, 18, 19, 20
SIB = 21                                          # SIB..SIB+3: the current level's sibling digest
DIR = 25
ACC, RB0, RB1, RB2, RB3 = 26, 27, 28, 29, 30
NCOLS = 31                                        # witness columns the AIR reads
ZK_RANDOMIZERS = 8                                # = next_pow2(MAX_DEGREE): stark.prove(zk=) requires that many
NCOLS_TOTAL = NCOLS + ZK_RANDOMIZERS              # the trace width a proof declares
RANDOM_ROWS = 2 * stark.NUM_QUERIES + 16          # more random rows than opened evaluations per column
CAP = A2.CAPACITY
RATE = A2.RATE
R = A2.ROUNDS
BR = R + 1                                        # rows per permutation block
MAX_DEGREE = A2.ALPHA

RNG_NIBBLES = 16
RNG_BLOCK = RNG_NIBBLES + 1
RNG_VALUES = 3

# periodic column indices: RC lanes, then the structural selectors
(RC0, ACT_R, A_COMMIT, A_MERK, A_NF, A_OUT1, A_OUT2, ROW0,
 RNG_ACC, RNG_START, RBIND_VIN, RBIND_VOUT1, RBIND_VOUT2, ACTIVE) = (0, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24)
NPER = 25

LEN_OWNER, LEN_CM, LEN_NF = 5, 7, 6               # hashn's length prefix for each frame (znote.py)


def _next_pow2(x):
    p = 1
    while p < x:
        p <<= 1
    return p


def _blocks(D):
    """Block indices: (OWNER, COMMIT, first MEMBERSHIP, NULLIFIER, OUTPUT1, OUTPUT2, count)."""
    return 0, 1, 2, D + 2, D + 3, D + 4, D + 5


def _last_row(b):
    return b * BR + R


def _rows(D):
    """(root_row, nf_row, cm1_row, sponge_end, range_start, total): the output rows the boundaries pin, the
    first range row and the last meaningful row (exclusive)."""
    _o, _c, _m, nfb, o1b, o2b, nb = _blocks(D)
    return (_last_row(nfb - 1), _last_row(nfb), _last_row(o1b), _last_row(o2b),
            nb * BR, nb * BR + RNG_VALUES * RNG_BLOCK)


def _total(D):
    return _rows(D)[5]


def _T(D):
    return _next_pow2(_total(D) + RANDOM_ROWS)


def _rand_field():
    import secrets
    return secrets.randbelow(F.P)


def _ordered(cur, sib, d):
    left = sib if d else cur
    right = cur if d else sib
    return [int(x) % F.P for x in left] + [int(x) % F.P for x in right] + list(A2.IV)


def _nibbles(v):
    return [(v >> (4 * (15 - k))) & 0xF for k in range(RNG_NIBBLES)]


def _range_fill(start, values):
    """row -> (acc, b0, b1, b2, b3) for the range region (acc = the accumulator BEFORE this row's nibble)."""
    fill = {}
    for b, val in enumerate(values):
        nibs = _nibbles(val)
        acc = 0
        base = start + b * RNG_BLOCK
        for i in range(RNG_NIBBLES):
            nib = nibs[i]
            fill[base + i] = (acc, (nib >> 3) & 1, (nib >> 2) & 1, (nib >> 1) & 1, nib & 1)
            acc = 16 * acc + nib
        fill[base + RNG_NIBBLES] = (acc, 0, 0, 0, 0)
    return fill


def transfer(nsk, v_in, rho_in, siblings, dirs, v1, o1, r1, v2, o2, r2):
    """Reference (non-ZK) evaluation of the statement: (owner, cm_in, nf, root, cm_out1, cm_out2) as digests."""
    owner = Z.owner_of(nsk)
    cm_in = Z.commit(v_in, owner, rho_in)
    return (owner, cm_in, Z.nullifier(nsk, rho_in), Z.fold_path(cm_in, siblings, dirs),
            Z.commit(v1, o1, r1), Z.commit(v2, o2, r2))


def build_trace(nsk, v_in, rho_in, siblings, dirs, v1, o1, r1, v2, o2, r2):
    """The honest witness trace. Returns (trace, T, D, root, nf, cm_out1, cm_out2) with the four outputs as
    CAPACITY-tuples — exactly the lanes the boundary constraints pin."""
    m = lambda x: int(x) % F.P
    nsk = list(Z.nsk_lanes(nsk))
    v_in, rho_in, v1, r1, v2, r2 = m(v_in), m(rho_in), m(v1), m(r1), m(v2), m(r2)
    o1, o2 = Z._d(o1), Z._d(o2)
    sibs = [Z._d(s) for s in siblings]
    ds = [int(d) & 1 for d in dirs]
    D = len(sibs)
    if D < 1 or len(ds) != D:
        raise ValueError("a membership path needs at least one level, one direction per sibling")
    blocks = []
    b = _permute_snapshots([LEN_OWNER, Z.DOM_ZOWNER, *nsk, 0, 0] + list(A2.IV)); blocks.append(b)
    owner = tuple(b[R][:CAP])
    b = _permute_snapshots([LEN_CM, Z.DOM_ZCM, v_in, *owner, rho_in] + list(A2.IV)); blocks.append(b)
    cur = tuple(b[R][:CAP])
    for k in range(D):
        b = _permute_snapshots(_ordered(cur, sibs[k], ds[k])); blocks.append(b)
        cur = tuple(b[R][:CAP])
    root = cur
    b = _permute_snapshots([LEN_NF, Z.DOM_ZNF, *nsk, rho_in, 0] + list(A2.IV)); blocks.append(b)
    nf = tuple(b[R][:CAP])
    b = _permute_snapshots([LEN_CM, Z.DOM_ZCM, v1, *o1, r1] + list(A2.IV)); blocks.append(b)
    cm1 = tuple(b[R][:CAP])
    b = _permute_snapshots([LEN_CM, Z.DOM_ZCM, v2, *o2, r2] + list(A2.IV)); blocks.append(b)
    cm2 = tuple(b[R][:CAP])
    _o, _c, mb, nfb, _1, _2, nb = _blocks(D)
    assert len(blocks) == nb
    cons = F.sub(F.sub(v_in, v1), v2)                 # = fee - public_value
    root_row, nf_row, cm1_row, sponge_end, rs, total = _rows(D)
    T = _T(D)                                         # real rows + RANDOM_ROWS, padded (Z1)
    rfill = _range_fill(rs, (v_in, v1, v2))
    # the path registers LEAD by one block: block b's boundary row absorbs block b+1's fold with the sibling
    # held during block b (see _periodic: A_MERK marks those rows). Blocks 0..1 hold level 0's; membership
    # block k holds level k+1's; nothing after the last level needs one.
    def path_for(bi):
        k = 0 if bi < mb else bi - mb + 1
        return (list(sibs[k]), ds[k]) if k < D else ([0] * CAP, 0)
    tr = []
    rnd = lambda n: [_rand_field() for _ in range(n)]
    for bi, blk in enumerate(blocks):
        sib, d = path_for(bi)
        for rr in range(BR):
            row = bi * BR + rr
            acc, b0, b1, b2, b3 = rfill.get(row, (0, 0, 0, 0, 0))
            tr.append([int(x) % F.P for x in blk[rr]] + nsk + [rho_in, v_in, v1, v2, cons] + sib
                      + [d, acc, b0, b1, b2, b3] + rnd(ZK_RANDOMIZERS))
    last_lanes = list(tr[-1][:W_ST])
    while len(tr) < total:                            # the range region: the sponge idles, registers hold
        row = len(tr)
        acc, b0, b1, b2, b3 = rfill.get(row, (0, 0, 0, 0, 0))
        tr.append(last_lanes + nsk + [rho_in, v_in, v1, v2, cons] + [0] * CAP + [0, acc, b0, b1, b2, b3]
                  + rnd(ZK_RANDOMIZERS))
    while len(tr) < T:                                # Z1: uniformly random rows, every column, no constraint reaches them
        tr.append(rnd(NCOLS_TOTAL))
    assert tr[root_row][:CAP] == list(root) and tr[nf_row][:CAP] == list(nf)
    assert tr[cm1_row][:CAP] == list(cm1) and tr[sponge_end][:CAP] == list(cm2)
    return tr, T, D, root, nf, cm1, cm2


def _periodic(T, D):
    """Public periodic columns, fully determined by (T, D): the round constants on round rows, the round
    selector, the five absorb selectors (one per handoff kind), the row-0 selector and the range selectors.
    Prover and verifier derive them from the geometry alone, so a prover cannot relocate a block, an absorb
    or a range-bind row."""
    _o, _c, mb, nfb, o1b, o2b, nb = _blocks(D)
    root_row, nf_row, cm1_row, sponge_end, rs, total = _rows(D)
    p = [[0] * T for _ in range(NPER)]
    for row in range(min(T, nb * BR)):
        bi, rr = divmod(row, BR)
        if rr < R:
            for lane in range(W_ST):
                p[RC0 + lane][row] = A2.RC[rr][lane]
            p[ACT_R][row] = 1
        else:                                         # a block's last row: the handoff into the next block
            if bi == 0:
                p[A_COMMIT][row] = 1
            elif 1 <= bi <= D:
                p[A_MERK][row] = 1                    # feeds membership block bi+1 (levels 0..D-1)
            elif bi == D + 1:
                p[A_NF][row] = 1
            elif bi == o1b - 1:
                p[A_OUT1][row] = 1
            elif bi == o2b - 1:
                p[A_OUT2][row] = 1
    p[ROW0][0] = 1
    for row in range(min(T, total - 1)):              # Z1: a transition is constrained only between two REAL rows
        p[ACTIVE][row] = 1
    for row in range(rs, min(T, total)):
        off = (row - rs) % RNG_BLOCK
        if off < RNG_NIBBLES:
            p[RNG_ACC][row] = 1
        if off == 0:
            p[RNG_START][row] = 1
    for sel, b in ((RBIND_VIN, 0), (RBIND_VOUT1, 1), (RBIND_VOUT2, 2)):
        row = rs + b * RNG_BLOCK + RNG_NIBBLES
        if row < T:
            p[sel][row] = 1
    return p


# ONE S-BOX VECTOR PER ROW, SHARED BY THE TWELVE LANE CONSTRAINTS. The composition calls every constraint
# with the same `cur` object at a point, so the twelve round constraints would each recompute the same
# twelve x^7 terms — 144 per point instead of 12. Keyed on the VALUES (a tuple of the lanes and their round
# constants), never on id(): the verifier builds its rows one query at a time and an address is reused.
_SBOX_MEMO = [None, None]


def _sboxes(cur, per):
    key = (tuple(cur[:W_ST]), tuple(per[RC0:RC0 + W_ST]))
    if _SBOX_MEMO[0] != key:
        _SBOX_MEMO[0] = key
        _SBOX_MEMO[1] = [F.pw(F.add(cur[j], per[RC0 + j]), A2.ALPHA) for j in range(W_ST)]
    return _SBOX_MEMO[1]


def _transitions():
    """The wide join-split AIR. Every constraint is gated to its rows by a structural selector, so one list
    covers the whole heterogeneous trace; max degree = ALPHA (the S-box)."""
    IV = list(A2.IV)
    cons = []

    def round_c(i):
        def c(cur, nxt, per):
            t = _sboxes(cur, per)
            mixed = 0
            for j in range(W_ST):
                mixed = F.add(mixed, F.mul(A2._MDS[i][j], t[j]))
            return F.mul(per[ACT_R], F.sub(nxt[i], mixed))
        return c
    for i in range(W_ST):
        cons.append(round_c(i))

    def pin(sel, lane, want):
        """nxt[lane] == want(cur) on rows where per[sel] = 1 — the absorb of one lane of the next block."""
        def c(cur, nxt, per):
            return F.mul(per[sel], F.sub(nxt[lane], want(cur)))
        return c
    const = lambda v: (lambda cur: v)
    reg = lambda col: (lambda cur: cur[col])
    lane = lambda k: (lambda cur: cur[k])
    # OWNER -> COMMIT: [7, DOM_ZCM, v_in, owner(4) = this block's output lanes, rho_in | IV]
    cons += [pin(A_COMMIT, 0, const(LEN_CM)), pin(A_COMMIT, 1, const(Z.DOM_ZCM)), pin(A_COMMIT, 2, reg(VIN)),
             pin(A_COMMIT, 7, reg(RHO))]
    cons += [pin(A_COMMIT, 3 + i, lane(i)) for i in range(CAP)]
    cons += [pin(A_COMMIT, RATE + i, const(IV[i])) for i in range(CAP)]
    # COMMIT -> level 0, level k -> level k+1: [ordered(output, sib) by dir | IV]; the path is witness
    def left(i):
        return lambda cur: F.add(F.mul(F.sub(1, cur[DIR]), cur[i]), F.mul(cur[DIR], cur[SIB + i]))
    def right(i):
        return lambda cur: F.add(F.mul(F.sub(1, cur[DIR]), cur[SIB + i]), F.mul(cur[DIR], cur[i]))
    cons += [pin(A_MERK, i, left(i)) for i in range(CAP)]
    cons += [pin(A_MERK, CAP + i, right(i)) for i in range(CAP)]
    cons += [pin(A_MERK, RATE + i, const(IV[i])) for i in range(CAP)]
    # last level -> NULLIFIER: [6, DOM_ZNF, nsk(4), rho_in, 0 | IV]
    cons += [pin(A_NF, 0, const(LEN_NF)), pin(A_NF, 1, const(Z.DOM_ZNF))]
    cons += [pin(A_NF, 2 + i, reg(NSK + i)) for i in range(CAP)]
    cons += [pin(A_NF, 6, reg(RHO)), pin(A_NF, 7, const(0))]
    cons += [pin(A_NF, RATE + i, const(IV[i])) for i in range(CAP)]
    # NULLIFIER -> OUTPUT1, OUTPUT1 -> OUTPUT2: [7, DOM_ZCM, v_out, (owner, rho: free witness) | IV]
    for sel, vreg in ((A_OUT1, VOUT1), (A_OUT2, VOUT2)):
        cons += [pin(sel, 0, const(LEN_CM)), pin(sel, 1, const(Z.DOM_ZCM)), pin(sel, 2, reg(vreg))]
        cons += [pin(sel, RATE + i, const(IV[i])) for i in range(CAP)]
    # row 0: the OWNER frame absorbs the four nsk lanes in lanes 2..5 (its other lanes are boundary constraints)
    for i in range(CAP):
        cons.append((lambda i_: (lambda cur, nxt, per: F.mul(per[ROW0], F.sub(cur[2 + i_], cur[NSK + i_]))))(i))
    # the witness registers are constant over the REAL rows (ACTIVE), so every block reads the SAME secret
    # value; past the last real row they are random (Z1), and no constraint may reach there
    for col in (NSK, NSK + 1, NSK + 2, NSK + 3, RHO, VIN, VOUT1, VOUT2):
        cons.append((lambda c_: (lambda cur, nxt, per: F.mul(per[ACTIVE], F.sub(nxt[c_], cur[c_]))))(col))
    # the path: SIB/DIR may change only right after a membership absorb row; DIR is a bit where it is used
    for i in range(CAP):
        cons.append((lambda c_: (lambda cur, nxt, per: F.mul(per[ACTIVE], F.mul(F.sub(1, per[A_MERK]), F.sub(nxt[c_], cur[c_])))))(SIB + i))
    cons.append(lambda cur, nxt, per: F.mul(per[ACTIVE], F.mul(F.sub(1, per[A_MERK]), F.sub(nxt[DIR], cur[DIR]))))
    cons.append(lambda cur, nxt, per: F.mul(per[A_MERK], F.mul(cur[DIR], F.sub(1, cur[DIR]))))
    # 2-output value conservation, pinned by the boundary to fee - public_value (on the real rows)
    cons.append(lambda cur, nxt, per: F.mul(per[ACTIVE], F.sub(cur[CONS], F.sub(F.sub(cur[VIN], cur[VOUT1]), cur[VOUT2]))))
    # C-3 range gadget (joinsplit2's, verbatim)
    def nib(cur):
        return F.add(F.add(F.mul(8, cur[RB0]), F.mul(4, cur[RB1])), F.add(F.mul(2, cur[RB2]), cur[RB3]))
    cons.append(lambda cur, nxt, per: F.mul(per[RNG_ACC], F.sub(nxt[ACC], F.add(F.mul(16, cur[ACC]), nib(cur)))))
    cons.append(lambda cur, nxt, per: F.mul(per[RNG_START], cur[ACC]))
    cons.append(lambda cur, nxt, per: F.mul(per[RNG_START], F.add(F.add(cur[RB0], cur[RB1]), cur[RB2])))
    for col in (RB0, RB1, RB2, RB3):
        cons.append((lambda c_: (lambda cur, nxt, per: F.mul(per[RNG_ACC], F.mul(cur[c_], F.sub(1, cur[c_])))))(col))
    for sel, vreg in ((RBIND_VIN, VIN), (RBIND_VOUT1, VOUT1), (RBIND_VOUT2, VOUT2)):
        cons.append((lambda s_, v_: (lambda cur, nxt, per: F.mul(per[s_], F.sub(cur[ACC], cur[v_]))))(sel, vreg))
    return cons


def _boundaries(D, root, nf, cm1, cm2, public_value, fee):
    root_row, nf_row, cm1_row, sponge_end, _rs, _t = _rows(D)
    cons_pub = F.sub(int(fee) % F.P, int(public_value) % F.P)
    bnd = [(0, 0, LEN_OWNER), (0, 1, Z.DOM_ZOWNER)] + [(0, k, 0) for k in range(2 + CAP, RATE)]
    bnd += [(0, RATE + i, A2.IV[i]) for i in range(CAP)]
    bnd.append((0, CONS, cons_pub))
    for row, dig in ((root_row, root), (nf_row, nf), (cm1_row, cm1), (sponge_end, cm2)):
        d = Z._d(dig)
        bnd += [(row, i, d[i]) for i in range(CAP)]
    return bnd


def bind_aux(aux, public_value, fee):
    """The transcript's extra public input for a wide join-split: the unshield destination AND the public value AND
    the fee (review 2026-09-24, reproduced on the legacy circuit). The only boundary on them is CONS = fee - pv and the
    AIR identity absorbs that DIFFERENCE, so (pv + k, fee + k) verified with the same proof: anyone could take a
    victim's unshield from DA, rewrite it to pv = 0, fee = 100, land it first, and burn the exit into pool fees.
    Binding both values here makes any rewrite a different transcript. The wallet's joinsplit3.js bindAux is the same
    string, byte for byte."""
    return f"j3|{aux or ''}|{int(public_value)}|{int(fee)}"


def prove_transfer(nsk, v_in, rho_in, siblings, dirs, v1, o1, r1, v2, o2, r2, public_value, fee,
                   num_queries=stark.NUM_QUERIES, aux=None):
    """Prove the wide join-split; returns (proof, root, nf, cm_out1, cm_out2) with digests as CAPACITY-tuples.
    proof["D"] carries the tree depth the verifier rebuilds the geometry from; `aux` binds extra public data
    (the unshield destination) into the transcript."""
    tr, T, D, root, nf, cm1, cm2 = build_trace(nsk, v_in, rho_in, siblings, dirs, v1, o1, r1, v2, o2, r2)
    bnd = _boundaries(D, root, nf, cm1, cm2, public_value, fee)
    proof = stark.prove(tr, _transitions(), bnd, periodic=_periodic(T, D), max_degree=MAX_DEGREE,
                        num_queries=num_queries, aux=bind_aux(aux, public_value, fee), zk=ZK_RANDOMIZERS)
    proof["D"] = D
    return proof, root, nf, cm1, cm2


def verify_transfer(proof, root, nf, cm1, cm2, public_value, fee, root_is_known, aux=None):
    """Verify against the public (root, nf, cm_out1, cm_out2, public_value, fee) — digests as tuples or 64-hex.
    Pins the whole geometry (D, T, W) to the honest values before rebuilding the AIR. Returns (ok, reason)."""
    try:
        root, nf, cm1, cm2 = Z._d(root), Z._d(nf), Z._d(cm1), Z._d(cm2)
    except Exception as e:
        return False, f"bad public digest: {e}"
    if not root_is_known(root):
        return False, "unknown anchor root"
    D, T, Wc = proof.get("D"), proof.get("T"), proof.get("W")
    # H1: T and D determine every block and range-bind row; an under-declared T pushes the range binds past
    # the trace and makes the range proof vacuous. W is pinned so no unconstrained column rides along.
    if not isinstance(D, int) or not isinstance(T, int) or D < 1 or T != _T(D) or Wc != NCOLS_TOTAL:
        return False, "bad trace geometry"
    bnd = _boundaries(D, root, nf, cm1, cm2, public_value, fee)
    try:
        _aux = bind_aux(aux, public_value, fee)
    except Exception:
        return False, "bad public value / fee"
    return stark.verify(proof, _transitions(), bnd, periodic=_periodic(T, D), max_degree=MAX_DEGREE, aux=_aux,
                        zk=ZK_RANDOMIZERS)
