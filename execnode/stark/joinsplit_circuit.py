"""
Full 1-in/1-out JOIN-SPLIT circuit (doc/privacy.md) — the complete shielded transfer statement in ONE
zero-knowledge proof, revealing only the public root, nullifier, output commitment, public_value and fee:

  owner   = hashn([DOM_OWNER, nsk])
  cm_in   = hashn([DOM_CM, v_in, owner, rho_in])          membership(cm_in, path) = root
  nf      = hashn([DOM_NF, nsk, rho_in])                  (revealed)
  cm_out  = hashn([DOM_CM, v_out, owner_out, rho_out])    (revealed)
  v_in + public_value = v_out + fee                        (value conservation, over the SECRET values)
  0 <= v_in, v_out < 2^62                                  (C-3 in-circuit range proof — see below)

Extends the authorised-spend circuit (execnode/stark/spend_full) with an OUTPUT region and value conservation.
v_in and v_out live in persistent register columns so conservation is a linear check over the SECRET values;
the CONS register (= v_in - v_out) is pinned to (fee - public_value). Regions run back-to-back
(OWNER, COMMIT, NULLIFIER, MEMBERSHIP, OUTPUT); handoffs capture each region's output into a register.

C-3 RANGE PROOF. Conservation is only enforced modulo P, and Goldilocks P ≈ 2^64 is barely above the coin
range, so without bounding the values a crafted "change" value could WRAP past P: e.g. spend a 1-coin note
with public_value = -X, letting the output value be (1 - X) mod P ≈ P, and the mod-P equation still balances —
recording an unshield of X ≫ 1 and draining the shared escrow. We therefore bit-decompose every note value in
the trace and force it into [0, 2^62): 64 bits, 4 per row, with the top 2 bits pinned to 0. With the state-side
bound |public_value|, fee ≤ 2^62, the mod-P conservation then coincides with INTEGER conservation, so no
wraparound assignment exists. One 17-row block per value (16 nibble-accumulation rows + 1 bind row) is appended
after the sponge regions; for the production depth this leaves the trace length unchanged.
"""
from execnode.stark import field as F, alghash, membership as MB, stark

R = alghash.ROUNDS
# columns  (…, ACC + 4 nibble-bit columns for the C-3 range proof)
(S0, S1, AB, CARRY, SIB, DIR, NSK, RHO, OWN, NFREG, VIN, VOUT, CONS, ROOTREG,
 ACC, RB0, RB1, RB2, RB3) = range(19)
RPL = 3 * R
OWN_END, COM_END, NUL_END = 2 * R, 6 * R, 9 * R
MERK = NUL_END
MAX_DEGREE = alghash.ALPHA

# C-3 range gadget geometry
RNG_NIBBLES = 16                 # 16 nibbles × 4 bits = 64-bit decomposition
RNG_BLOCK = RNG_NIBBLES + 1      # 16 accumulation rows + 1 bind row, per value
RNG_VALUES = 2                   # VIN, VOUT


def _next_pow2(x):
    """Smallest power of two >= x (trace/FRI evaluation domains are power-of-two sized)."""
    p = 1
    while p < x:
        p <<= 1
    return p


def _out_end(D):
    """End of the sponge (OUTPUT region end) — where root/nf/cm_out are captured; the range region follows."""
    return MERK + D * RPL + 4 * R


def _total(D):
    """Last meaningful trace row for depth D: sponge end + the two 17-row C-3 range blocks (VIN, VOUT)."""
    return _out_end(D) + RNG_VALUES * RNG_BLOCK


def _round(s0, s1, r):
    """One prover-side sponge round (round constants → x^ALPHA S-box → MDS) — the same map the transition
    constraints recompute in-circuit, so the honest trace satisfies them by construction."""
    t0 = alghash.sbox(F.add(s0, alghash.RC[r % R][0]))
    t1 = alghash.sbox(F.add(s1, alghash.RC[r % R][1]))
    return F.add(F.mul(2, t0), t1), F.add(t0, F.mul(3, t1))


def transfer(nsk, v_in, rho_in, siblings, dirs, v_out, owner_out, rho_out):
    """Reference (non-ZK) evaluation of the join-split statement: (owner, cm_in, nf, root, cm_out) from the
    full witness. This is the ground truth the trace + boundary constraints must reproduce; callers/tests use
    it to derive the public values a proof will be checked against."""
    owner = alghash.owner_of(nsk)
    cm_in = alghash.commit(v_in, owner, rho_in)
    nf = alghash.nullifier(nsk, rho_in)
    root = MB.merkle_root_from_path(cm_in, siblings, dirs)
    cm_out = alghash.commit(v_out, owner_out, rho_out)
    return owner, cm_in, nf, root, cm_out


def _nibbles(v):
    """The 16 nibbles of v, MOST significant first (nibble k = bits [4·(15-k) .. +3])."""
    return [(v >> (4 * (15 - k))) & 0xF for k in range(RNG_NIBBLES)]


def _range_fill(out_end, values):
    """row -> (acc, b0, b1, b2, b3) for the range region. acc is the accumulator BEFORE this row's nibble;
    the recurrence acc' = 16·acc + nibble reconstructs the value by the block's bind row."""
    fill = {}
    for b, val in enumerate(values):
        nibs = _nibbles(val)
        acc = 0
        base = out_end + b * RNG_BLOCK
        for i in range(RNG_NIBBLES):
            nib = nibs[i]
            fill[base + i] = (acc, (nib >> 3) & 1, (nib >> 2) & 1, (nib >> 1) & 1, nib & 1)
            acc = 16 * acc + nib
        fill[base + RNG_NIBBLES] = (acc, 0, 0, 0, 0)     # bind row: acc == val (val < 2^64)
    return fill


def build_trace(nsk, v_in, rho_in, siblings, dirs, v_out, owner_out, rho_out):
    """Build the honest witness trace: the five sponge regions back-to-back (OWNER, COMMIT, NULLIFIER,
    MEMBERSHIP, OUTPUT) with the register columns held/captured per the handoff schedule, then the C-3 range
    blocks, padded to a power of two (the sponge idles through padding). Returns (trace, T, D, root, nf,
    cm_out); the captured registers at out_end (and the final sponge s0 = cm_out) are exactly what the
    boundary constraints pin to the public values."""
    nsk, v_in, rho_in = nsk % F.P, v_in % F.P, rho_in % F.P
    v_out, owner_out, rho_out = v_out % F.P, owner_out % F.P, rho_out % F.P
    D = len(siblings)
    out_start = MERK + D * RPL                          # OUTPUT region start (after membership)
    out_end = _out_end(D)                               # OUTPUT region end (= old total); range region follows
    total = _total(D)
    T = _next_pow2(total + 1)
    cons = F.sub(v_in, v_out)                           # = fee - public_value (checked by boundary)
    rfill = _range_fill(out_end, (v_in, v_out))
    tr = []
    s0, s1, ab = alghash.DOM_OWNER, alghash.IV, alghash.DOM_OWNER
    carry = sib = dr = own = nfreg = rootreg = 0
    lvl = 0
    for r in range(T):
        acc, rb0, rb1, rb2, rb3 = rfill.get(r, (0, 0, 0, 0, 0))
        tr.append([s0, s1, ab, carry, sib, dr, nsk, rho_in, own, nfreg, v_in, v_out, cons, rootreg,
                   acc, rb0, rb1, rb2, rb3])
        r0, r1 = _round(s0, s1, r)
        last = (r % R == R - 1)
        if r < OWN_END:                                 # OWNER [DOM_OWNER, nsk]
            if r == OWN_END - 1:
                own = r0; s0, s1, ab = alghash.DOM_CM, alghash.IV, alghash.DOM_CM
            elif last:
                s0, s1, ab = F.add(r0, nsk), r1, nsk
            else:
                s0, s1 = r0, r1
        elif r < COM_END:                               # COMMIT [DOM_CM, v_in, owner, rho_in]
            if r == COM_END - 1:
                carry = r0; s0, s1, ab = alghash.DOM_NF, alghash.IV, alghash.DOM_NF
            elif last:
                msg = v_in if r == 3 * R - 1 else (own if r == 4 * R - 1 else rho_in)
                s0, s1, ab = F.add(r0, msg), r1, msg
            else:
                s0, s1 = r0, r1
        elif r < NUL_END:                               # NULLIFIER [DOM_NF, nsk, rho_in]
            if r == NUL_END - 1:
                nfreg = r0; sib, dr = siblings[0] % F.P, dirs[0] % F.P
                s0, s1, ab = alghash.DOM_NODE, alghash.IV, alghash.DOM_NODE
            elif last:
                msg = nsk if r == 7 * R - 1 else rho_in
                s0, s1, ab = F.add(r0, msg), r1, msg
            else:
                s0, s1 = r0, r1
        elif r < out_start:                             # MEMBERSHIP
            pos = (r - MERK) % RPL; block = pos // R
            if last and block == 0:
                left = F.add(carry, F.mul(dr, F.sub(sib, carry)))
                s0, s1, ab = F.add(r0, left), r1, left
            elif last and block == 1:
                right = F.add(sib, F.mul(dr, F.sub(carry, sib)))
                s0, s1, ab = F.add(r0, right), r1, right
            elif last and block == 2:
                lvl += 1
                if lvl < D:
                    carry, sib, dr = r0, siblings[lvl] % F.P, dirs[lvl] % F.P
                    s0, s1, ab = alghash.DOM_NODE, alghash.IV, alghash.DOM_NODE
                else:                                   # last level: capture root, reset for OUTPUT
                    rootreg = r0; s0, s1, ab = alghash.DOM_CM, alghash.IV, alghash.DOM_CM
            else:
                s0, s1 = r0, r1
        elif r < out_end:                               # OUTPUT [DOM_CM, v_out, owner_out, rho_out]
            if last and r < out_end - 1:
                oi = (r - out_start) // R
                msg = v_out if oi == 0 else (owner_out if oi == 1 else rho_out)
                s0, s1, ab = F.add(r0, msg), r1, msg
            else:
                s0, s1 = r0, r1
        else:                                           # range region + padding: the sponge idles
            s0, s1 = r0, r1
    return tr, T, D, rootreg, nfreg, tr[out_end][S0]     # root, nf, cm_out


(RC0, RC1, ANSK, ARHO, AOWN, AVIN, AVOUT, AFREE, B0, B1, RCM, RNF, RNODE, ROUT,
 CAPOWN, CAPCARRY, CAPNF, CAPROOT, INMERK, RNG_ACC, RNG_START, RBIND_VIN, RBIND_VOUT) = range(23)


def _periodic(T, D):
    """Public periodic selector columns, fully determined by (T, D): round constants, the absorb schedule for
    each witness register, region reset/capture rows, Merkle block markers, and the C-3 range-region selectors.
    Because both prover and verifier derive these from the protocol geometry alone, a prover cannot relocate a
    region, an absorb slot, or a range-bind row."""
    out_start = MERK + D * RPL
    out_end = _out_end(D)
    total = _total(D)
    def col(fn):
        """0/1 selector column: fn(row) over all T rows."""
        return [1 if fn(r) else 0 for r in range(T)]
    lvl_end = lambda r, upto: r >= MERK and r < out_start and (r - MERK) % RPL == RPL - 1 and 0 <= (r - MERK) // RPL < upto
    rng = lambda r: out_end <= r < total
    p = [None] * 23
    p[RC0] = [alghash.RC[r % R][0] for r in range(T)]
    p[RC1] = [alghash.RC[r % R][1] for r in range(T)]
    p[ANSK] = col(lambda r: r in (R - 1, 7 * R - 1))
    p[ARHO] = col(lambda r: r in (5 * R - 1, 8 * R - 1))
    p[AOWN] = col(lambda r: r == 4 * R - 1)
    p[AVIN] = col(lambda r: r == 3 * R - 1)
    p[AVOUT] = col(lambda r: r == out_start + R - 1)
    p[AFREE] = col(lambda r: r in (out_start + 2 * R - 1, out_start + 3 * R - 1))
    p[B0] = col(lambda r: MERK <= r < out_start and (r - MERK) % RPL == R - 1)
    p[B1] = col(lambda r: MERK <= r < out_start and (r - MERK) % RPL == 2 * R - 1)
    p[RCM] = col(lambda r: r == OWN_END - 1)
    p[RNF] = col(lambda r: r == COM_END - 1)
    p[RNODE] = col(lambda r: r == NUL_END - 1 or lvl_end(r, D - 1))
    p[ROUT] = col(lambda r: r == out_start - 1)
    p[CAPOWN] = col(lambda r: r == OWN_END - 1)
    p[CAPCARRY] = col(lambda r: r == COM_END - 1 or lvl_end(r, D - 1))
    p[CAPNF] = col(lambda r: r == NUL_END - 1)
    p[CAPROOT] = col(lambda r: r == out_start - 1)
    p[INMERK] = col(lambda r: MERK <= r < out_start)
    # C-3 range region selectors
    p[RNG_ACC] = col(lambda r: rng(r) and (r - out_end) % RNG_BLOCK < RNG_NIBBLES)     # accumulation rows
    p[RNG_START] = col(lambda r: rng(r) and (r - out_end) % RNG_BLOCK == 0)             # block start (reset + top-bits)
    p[RBIND_VIN] = col(lambda r: r == out_end + 0 * RNG_BLOCK + RNG_NIBBLES)            # VIN bind row
    p[RBIND_VOUT] = col(lambda r: r == out_end + 1 * RNG_BLOCK + RNG_NIBBLES)           # VOUT bind row
    return p


def _transitions():
    """The join-split AIR: one list of transition polynomials, each gated to its region by the periodic
    selectors so a single constraint set covers the whole heterogeneous trace. Groups: sponge lanes + absorb
    (c_s1/c_s0/c_ab), region-output capture registers, constant witness registers, Merkle path handling, value
    conservation, and the C-3 range gadget. Max constraint degree = ALPHA (the S-box)."""
    A = alghash
    def rnd(cur, per):
        """The sponge round recomputed in-constraint (degree-ALPHA S-box + MDS) — every state transition and
        every capture must equal this evaluation of the current row."""
        t0 = F.pw(F.add(cur[S0], per[RC0]), A.ALPHA)
        t1 = F.pw(F.add(cur[S1], per[RC1]), A.ALPHA)
        return F.add(F.mul(2, t0), t1), F.add(t0, F.mul(3, t1))
    def parts(cur, per):
        """Shared subterms: the Merkle (left, right) child pair selected by DIR (linear interpolation, sound
        because c_dirbit forces DIR boolean), the combined region-reset selector, and reset_dom — the domain
        tag injected at the reset row (at most one reset selector is 1, so this is that region's separator)."""
        left = F.add(cur[CARRY], F.mul(cur[DIR], F.sub(cur[SIB], cur[CARRY])))
        right = F.add(cur[SIB], F.mul(cur[DIR], F.sub(cur[CARRY], cur[SIB])))
        reset = F.add(F.add(per[RCM], per[RNF]), F.add(per[RNODE], per[ROUT]))
        reset_dom = F.add(F.add(F.mul(per[RCM], A.DOM_CM), F.mul(per[RNF], A.DOM_NF)),
                          F.add(F.mul(per[RNODE], A.DOM_NODE), F.mul(per[ROUT], A.DOM_CM)))
        return left, right, reset, reset_dom
    def c_s1(cur, nxt, per):
        """Capacity lane: s1 follows the permutation, except at a region reset where it restarts from IV."""
        _, r1 = rnd(cur, per); _, _, reset, _ = parts(cur, per)
        return F.sub(nxt[S1], F.add(F.mul(reset, A.IV), F.mul(F.sub(1, reset), r1)))
    def c_s0(cur, nxt, per):
        """Rate lane: s0 follows the permutation plus whichever message the absorb schedule injects this row
        (a register value, free witness via nxt[AB], or the selected Merkle child); at a region reset it
        restarts from that region's domain tag. This single constraint binds every absorbed message — the
        whole hash-chain structure of the statement — to the intended source column."""
        r0, _ = rnd(cur, per); left, right, reset, reset_dom = parts(cur, per)
        absorbed = F.add(
            F.add(F.add(F.mul(per[ANSK], cur[NSK]), F.mul(per[ARHO], cur[RHO])),
                  F.add(F.mul(per[AOWN], cur[OWN]), F.mul(per[AVIN], cur[VIN]))),
            F.add(F.add(F.mul(per[AVOUT], cur[VOUT]), F.mul(per[AFREE], nxt[AB])),
                  F.add(F.mul(per[B0], left), F.mul(per[B1], right))))
        return F.sub(nxt[S0], F.add(reset_dom, F.mul(F.sub(1, reset), F.add(r0, absorbed))))
    def c_ab(cur, nxt, per):
        """AB register discipline: at each scheduled set-row AB' must equal the scheduled message (domain tag,
        register value, or Merkle child); on AFREE rows it is free witness (the secret output opening — the
        zero-knowledge part); everywhere else it holds. Keeps c_s0's absorbed values well-defined per block."""
        left, right, _, _ = parts(cur, per)
        setm = F.add(F.add(F.add(per[RCM], per[RNF]), F.add(per[RNODE], per[ROUT])),
                     F.add(F.add(per[ANSK], per[ARHO]), F.add(F.add(per[AOWN], per[AVIN]),
                           F.add(per[AVOUT], F.add(per[B0], per[B1])))))
        hold = F.sub(F.sub(1, setm), per[AFREE])
        terms = [
            F.mul(per[RCM], F.sub(nxt[AB], A.DOM_CM)), F.mul(per[RNF], F.sub(nxt[AB], A.DOM_NF)),
            F.mul(per[RNODE], F.sub(nxt[AB], A.DOM_NODE)), F.mul(per[ROUT], F.sub(nxt[AB], A.DOM_CM)),
            F.mul(per[ANSK], F.sub(nxt[AB], cur[NSK])), F.mul(per[ARHO], F.sub(nxt[AB], cur[RHO])),
            F.mul(per[AOWN], F.sub(nxt[AB], cur[OWN])), F.mul(per[AVIN], F.sub(nxt[AB], cur[VIN])),
            F.mul(per[AVOUT], F.sub(nxt[AB], cur[VOUT])),
            F.mul(per[B0], F.sub(nxt[AB], left)), F.mul(per[B1], F.sub(nxt[AB], right)),
            F.mul(hold, F.sub(nxt[AB], cur[AB])),
        ]
        acc = 0
        for t in terms:
            acc = F.add(acc, t)
        return acc
    def _cap(cur, nxt, per, reg, sel):
        """Generic capture register: latch the round output r0 where sel=1 (a region's final permutation),
        hold everywhere else — how a region's hash output becomes a boundary-checkable register."""
        r0, _ = rnd(cur, per)
        return F.sub(nxt[reg], F.add(F.mul(per[sel], r0), F.mul(F.sub(1, per[sel]), cur[reg])))
    def c_carry(cur, nxt, per):
        """CARRY capture: cm_in at COMMIT's end, then each intermediate Merkle node — the running child hash
        fed into the next tree level."""
        return _cap(cur, nxt, per, CARRY, CAPCARRY)
    def c_own(cur, nxt, per):
        """OWN capture: owner at OWNER's end; its later absorption into COMMIT ties cm_in to the same nsk."""
        return _cap(cur, nxt, per, OWN, CAPOWN)
    def c_nf(cur, nxt, per):
        """NFREG capture: the nullifier, pinned to the public nf by the out_end boundary."""
        return _cap(cur, nxt, per, NFREG, CAPNF)
    def c_root(cur, nxt, per):
        """ROOTREG capture: the Merkle root, pinned to the public anchor root by the out_end boundary."""
        return _cap(cur, nxt, per, ROOTREG, CAPROOT)
    def c_hold(reg):
        """Constraint factory: reg is constant over the whole trace (the witness registers nsk/rho/v_in/v_out),
        so every region reads the SAME secret value."""
        return lambda cur, nxt, per: F.sub(nxt[reg], cur[reg])
    def c_sib(cur, nxt, per):
        """SIB may change only at a Merkle level reset (RNODE row), fixing one sibling per level."""
        return F.mul(F.sub(1, per[RNODE]), F.sub(nxt[SIB], cur[SIB]))
    def c_dir(cur, nxt, per):
        """DIR may change only at a Merkle level reset, fixing one direction per level."""
        return F.mul(F.sub(1, per[RNODE]), F.sub(nxt[DIR], cur[DIR]))
    def c_dirbit(cur, nxt, per):
        """DIR is boolean inside the membership region — parts()'s child-selection interpolation is only a
        left/right swap for DIR ∈ {0,1}."""
        return F.mul(per[INMERK], F.mul(cur[DIR], F.sub(1, cur[DIR])))
    def c_cons(cur, nxt, per):
        """Value conservation: CONS = v_in - v_out on every row; the boundary pins CONS to fee - public_value
        (mod P — integer-exact only together with the C-3 range proof)."""
        return F.sub(cur[CONS], F.sub(cur[VIN], cur[VOUT]))
    # --- C-3 range constraints ---
    def _nib(cur):
        """The row's 4-bit nibble recomposed from its bit columns (degree 1; sound given c_bit)."""
        return F.add(F.add(F.mul(8, cur[RB0]), F.mul(4, cur[RB1])), F.add(F.mul(2, cur[RB2]), cur[RB3]))
    def c_rng_acc(cur, nxt, per):    # ACC recurrence on accumulation rows: acc' = 16·acc + nibble
        """Range accumulator recurrence: with boolean bits and a zeroed start, 16 steps make ACC at the bind
        row EXACTLY the 64-bit integer the bit columns spell — no mod-P alias fits."""
        return F.mul(per[RNG_ACC], F.sub(nxt[ACC], F.add(F.mul(16, cur[ACC]), _nib(cur))))
    def c_rng_reset(cur, nxt, per):  # ACC starts at 0 at each block start
        """ACC = 0 at each block start, so no value leaks between the per-value range blocks."""
        return F.mul(per[RNG_START], cur[ACC])
    def c_rng_top(cur, nxt, per):    # top 3 bits (of the MSB nibble at block start) = 0  ->  value < 2^61
        """Pins the MSB nibble's top 3 bits to 0 — each bound value < 2^61, the margin that makes the mod-P
        conservation equation coincide with integer conservation (module docstring, C-3)."""
        return F.mul(per[RNG_START], F.add(F.add(cur[RB0], cur[RB1]), cur[RB2]))
    def c_bit(reg):                  # each nibble bit is boolean on accumulation rows
        """Constraint factory: bit column is boolean on accumulation rows — the soundness hinge of the whole
        decomposition (non-bit values would let ACC reach any field element)."""
        return lambda cur, nxt, per: F.mul(per[RNG_ACC], F.mul(cur[reg], F.sub(1, cur[reg])))
    def c_bind(sel, val):            # at the bind row the accumulator equals the value column
        """Constraint factory: at the block's bind row ACC equals the value register — connecting the range
        decomposition to the very value conservation is computed over."""
        return lambda cur, nxt, per: F.mul(per[sel], F.sub(cur[ACC], cur[val]))
    return [c_s1, c_s0, c_ab, c_carry, c_own, c_nf, c_root,
            c_hold(NSK), c_hold(RHO), c_hold(VIN), c_hold(VOUT),
            c_sib, c_dir, c_dirbit, c_cons,
            c_rng_acc, c_rng_reset, c_rng_top,
            c_bit(RB0), c_bit(RB1), c_bit(RB2), c_bit(RB3),
            c_bind(RBIND_VIN, VIN), c_bind(RBIND_VOUT, VOUT)]


def prove_transfer(nsk, v_in, rho_in, siblings, dirs, v_out, owner_out, rho_out, public_value, fee, num_queries=stark.NUM_QUERIES, aux=None):
    """Prove the full join-split for the given witness; returns (proof, root, nf, cm_out). Boundaries pin the
    initial sponge state (domain tag + IV), CONS = fee - public_value, and the captured root/nf/cm_out at
    out_end. proof["D"] carries the tree depth from which the verifier rebuilds the whole geometry; `aux` binds
    extra public data (e.g. a withdraw address) into the Fiat–Shamir transcript."""
    tr, T, D, root, nf, cm_out = build_trace(nsk, v_in, rho_in, siblings, dirs, v_out, owner_out, rho_out)
    per = _periodic(T, D)
    out_end = _out_end(D)
    cons_pub = F.sub(fee % F.P, public_value % F.P)                 # v_in - v_out must equal fee - public_value
    bnd = [(0, S0, alghash.DOM_OWNER), (0, S1, alghash.IV), (0, AB, alghash.DOM_OWNER),
           (0, CONS, cons_pub),
           (out_end, ROOTREG, root), (out_end, NFREG, nf), (out_end, S0, cm_out)]
    proof = stark.prove(tr, _transitions(), bnd, periodic=per, max_degree=MAX_DEGREE, num_queries=num_queries, aux=aux)
    proof["D"] = D
    return proof, root, nf, cm_out


def verify_transfer(proof, root, nf, cm_out, public_value, fee, root_is_known, aux=None):
    """Verify a join-split proof against the public (root, nf, cm_out, public_value, fee). Checks the anchor
    root is known, pins the trace geometry (H1: T must be exactly the honest value for D), rebuilds the same
    periodic columns and boundary set as the prover, and runs the STARK verifier. Returns (ok, reason)."""
    if not root_is_known(root):
        return False, "unknown anchor root"
    D, T = proof["D"], proof["T"]
    # H1: pin T to the exact value the honest prover derives from D, so a truncated T can't push the C-3
    # range-bind rows past the trace end and make the range proof vacuous (see joinsplit2.verify_transfer).
    if not isinstance(D, int) or not isinstance(T, int) or D < 1 or T != _next_pow2(_total(D) + 1):
        return False, "bad trace geometry"
    per = _periodic(T, D)
    out_end = _out_end(D)
    cons_pub = F.sub(fee % F.P, public_value % F.P)
    bnd = [(0, S0, alghash.DOM_OWNER), (0, S1, alghash.IV), (0, AB, alghash.DOM_OWNER),
           (0, CONS, cons_pub),
           (out_end, ROOTREG, root % F.P), (out_end, NFREG, nf % F.P), (out_end, S0, cm_out % F.P)]
    return stark.verify(proof, _transitions(), bnd, periodic=per, max_degree=MAX_DEGREE, aux=aux)
