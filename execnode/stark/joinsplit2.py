"""
2-output JOIN-SPLIT circuit (doc/privacy.md) — 1 input, 2 outputs, so a shielded transfer sends any amount and
keeps the CHANGE (out1 = recipient, out2 = change), all in one zero-knowledge STARK. Extends
joinsplit_circuit with a second OUTPUT region and 2-output value conservation:

  owner=H(nsk) · cm_in=commit(v_in,owner,rho_in) · membership(cm_in,path)=root · nf=H(nsk,rho_in) ·
  cm_out1=commit(v_out1,owner1,rho1) · cm_out2=commit(v_out2,owner2,rho2) ·
  v_in + public_value == v_out1 + v_out2 + fee ·  0 <= v_in, v_out1, v_out2 < 2^62   (C-3 range proof)

Public: root, nf, cm_out1, cm_out2, public_value, fee. Six sponge regions run back-to-back
(OWNER, COMMIT, NULLIFIER, MEMBERSHIP, OUTPUT1, OUTPUT2); handoffs capture each region's output into a register.

C-3 RANGE PROOF: conservation is only mod P and P ≈ 2^64 barely exceeds the coin range, so without bounding the
values a crafted change value could wrap past P and record an exit far larger than the input (drain the shared
escrow). Every note value is bit-decomposed and forced into [0, 2^62) (64 bits, 4 per row, top 2 pinned to 0);
with the state-side |public_value|,fee ≤ 2^62 bound the mod-P conservation then equals INTEGER conservation, so
no wraparound assignment exists. One 17-row block per value (16 nibble rows + 1 bind row) follows OUTPUT2.
"""
from execnode.stark import field as F, alghash, membership as MB, stark

R = alghash.ROUNDS
(S0, S1, AB, CARRY, SIB, DIR, NSK, RHO, OWN, NFREG, VIN, VOUT1, VOUT2, CONS, ROOTREG, CMOUT1,
 ACC, RB0, RB1, RB2, RB3) = range(21)
RPL = 3 * R
OWN_END, COM_END, NUL_END = 2 * R, 6 * R, 9 * R
MERK = NUL_END
MAX_DEGREE = alghash.ALPHA

# C-3 range gadget geometry (see module docstring)
RNG_NIBBLES = 16
RNG_BLOCK = RNG_NIBBLES + 1      # 16 accumulation rows + 1 bind row, per value
RNG_VALUES = 3                   # VIN, VOUT1, VOUT2


def _next_pow2(x):
    """Smallest power of two >= x (trace/FRI evaluation domains are power-of-two sized)."""
    p = 1
    while p < x:
        p <<= 1
    return p


def _round(s0, s1, r):
    """One prover-side sponge round (round constants → x^ALPHA S-box → MDS) — the same map the transition
    constraints recompute in-circuit, so the honest trace satisfies them by construction."""
    t0 = alghash.sbox(F.add(s0, alghash.RC[r % R][0]))
    t1 = alghash.sbox(F.add(s1, alghash.RC[r % R][1]))
    return F.add(F.mul(2, t0), t1), F.add(t0, F.mul(3, t1))


def transfer(nsk, v_in, rho_in, siblings, dirs, v1, o1, r1, v2, o2, r2):
    """Reference (non-ZK) evaluation of the 2-output statement: (owner, cm_in, nf, root, cm_out1, cm_out2)
    from the full witness — the ground truth the trace + boundary constraints must reproduce."""
    owner = alghash.owner_of(nsk)
    cm_in = alghash.commit(v_in, owner, rho_in)
    nf = alghash.nullifier(nsk, rho_in)
    root = MB.merkle_root_from_path(cm_in, siblings, dirs)
    return owner, cm_in, nf, root, alghash.commit(v1, o1, r1), alghash.commit(v2, o2, r2)


def _bounds(D):
    """(OUTPUT1 start, OUTPUT2 start, sponge end). The range region follows the sponge end."""
    out1 = MERK + D * RPL
    out2 = out1 + 4 * R
    sponge_end = out2 + 4 * R
    return out1, out2, sponge_end


def _total(D):
    """Last meaningful trace row for depth D: sponge end + the three 17-row C-3 range blocks (VIN/VOUT1/VOUT2)."""
    _, _, sponge_end = _bounds(D)
    return sponge_end + RNG_VALUES * RNG_BLOCK


def _nibbles(v):
    """The 16 nibbles of v, MOST significant first (nibble k = bits [4·(15-k) .. +3])."""
    return [(v >> (4 * (15 - k))) & 0xF for k in range(RNG_NIBBLES)]


def _range_fill(sponge_end, values):
    """row -> (acc, b0, b1, b2, b3) witness for the range region. acc is the accumulator BEFORE this row's
    nibble; the recurrence acc' = 16·acc + nibble reconstructs each value by its block's bind row."""
    fill = {}
    for b, val in enumerate(values):
        nibs = _nibbles(val)
        acc = 0
        base = sponge_end + b * RNG_BLOCK
        for i in range(RNG_NIBBLES):
            nib = nibs[i]
            fill[base + i] = (acc, (nib >> 3) & 1, (nib >> 2) & 1, (nib >> 1) & 1, nib & 1)
            acc = 16 * acc + nib
        fill[base + RNG_NIBBLES] = (acc, 0, 0, 0, 0)     # bind row: acc == val
    return fill


def build_trace(nsk, v_in, rho_in, siblings, dirs, v1, o1, r1, v2, o2, r2):
    """Build the honest witness trace: the six sponge regions back-to-back (OWNER, COMMIT, NULLIFIER,
    MEMBERSHIP, OUTPUT1, OUTPUT2) with the register columns held/captured per the handoff schedule, then the
    three C-3 range blocks, padded to a power of two (the sponge idles through padding). Returns (trace, T, D,
    root, nf, cm_out1, cm_out2); the captured registers at sponge_end (and the final sponge s0 = cm_out2) are
    exactly what the boundary constraints pin to the public values."""
    m = lambda x: x % F.P
    nsk, v_in, rho_in = m(nsk), m(v_in), m(rho_in)
    v1, o1, r1, v2, o2, r2 = m(v1), m(o1), m(r1), m(v2), m(o2), m(r2)
    D = len(siblings)
    out1, out2, sponge_end = _bounds(D)
    total = _total(D)
    T = _next_pow2(total + 1)
    cons = F.sub(F.sub(v_in, v1), v2)                  # = fee - public_value
    rfill = _range_fill(sponge_end, (v_in, v1, v2))
    tr = []
    s0, s1, ab = alghash.DOM_OWNER, alghash.IV, alghash.DOM_OWNER
    carry = sib = dr = own = nfreg = rootreg = cmout1 = 0
    lvl = 0
    for r in range(T):
        acc, rb0, rb1, rb2, rb3 = rfill.get(r, (0, 0, 0, 0, 0))
        tr.append([s0, s1, ab, carry, sib, dr, nsk, rho_in, own, nfreg, v_in, v1, v2, cons, rootreg, cmout1,
                   acc, rb0, rb1, rb2, rb3])
        r0, r1r = _round(s0, s1, r)
        last = (r % R == R - 1)
        if r < OWN_END:                                 # OWNER [DOM_OWNER, nsk]
            if r == OWN_END - 1:
                own = r0; s0, s1, ab = alghash.DOM_CM, alghash.IV, alghash.DOM_CM
            elif last:
                s0, s1, ab = F.add(r0, nsk), r1r, nsk
            else:
                s0, s1 = r0, r1r
        elif r < COM_END:                               # COMMIT [DOM_CM, v_in, owner, rho_in]
            if r == COM_END - 1:
                carry = r0; s0, s1, ab = alghash.DOM_NF, alghash.IV, alghash.DOM_NF
            elif last:
                msg = v_in if r == 3 * R - 1 else (own if r == 4 * R - 1 else rho_in)
                s0, s1, ab = F.add(r0, msg), r1r, msg
            else:
                s0, s1 = r0, r1r
        elif r < NUL_END:                               # NULLIFIER [DOM_NF, nsk, rho_in]
            if r == NUL_END - 1:
                nfreg = r0; sib, dr = m(siblings[0]), m(dirs[0])
                s0, s1, ab = alghash.DOM_NODE, alghash.IV, alghash.DOM_NODE
            elif last:
                msg = nsk if r == 7 * R - 1 else rho_in
                s0, s1, ab = F.add(r0, msg), r1r, msg
            else:
                s0, s1 = r0, r1r
        elif r < out1:                                  # MEMBERSHIP
            pos = (r - MERK) % RPL; block = pos // R
            if last and block == 0:
                left = F.add(carry, F.mul(dr, F.sub(sib, carry)))
                s0, s1, ab = F.add(r0, left), r1r, left
            elif last and block == 1:
                right = F.add(sib, F.mul(dr, F.sub(carry, sib)))
                s0, s1, ab = F.add(r0, right), r1r, right
            elif last and block == 2:
                lvl += 1
                if lvl < D:
                    carry, sib, dr = r0, m(siblings[lvl]), m(dirs[lvl])
                    s0, s1, ab = alghash.DOM_NODE, alghash.IV, alghash.DOM_NODE
                else:                                   # capture root, reset for OUTPUT1
                    rootreg = r0; s0, s1, ab = alghash.DOM_CM, alghash.IV, alghash.DOM_CM
            else:
                s0, s1 = r0, r1r
        elif r < out2:                                  # OUTPUT1 [DOM_CM, v1, o1, r1]
            if r == out2 - 1:                           # capture cm_out1, reset for OUTPUT2
                cmout1 = r0; s0, s1, ab = alghash.DOM_CM, alghash.IV, alghash.DOM_CM
            elif last:
                oi = (r - out1) // R
                msg = v1 if oi == 0 else (o1 if oi == 1 else r1)
                s0, s1, ab = F.add(r0, msg), r1r, msg
            else:
                s0, s1 = r0, r1r
        elif r < sponge_end:                            # OUTPUT2 [DOM_CM, v2, o2, r2]
            if last and r < sponge_end - 1:
                oi = (r - out2) // R
                msg = v2 if oi == 0 else (o2 if oi == 1 else r2)
                s0, s1, ab = F.add(r0, msg), r1r, msg
            else:
                s0, s1 = r0, r1r
        else:                                           # range region + padding: the sponge idles
            s0, s1 = r0, r1r
    return tr, T, D, rootreg, nfreg, tr[out2][CMOUT1], tr[sponge_end][S0]   # root, nf, cm_out1, cm_out2


(RC0, RC1, ANSK, ARHO, AOWN, AVIN, AVOUT1, AVOUT2, AFREE, B0, B1, RCM, RNF, RNODE,
 ROUT1, ROUT2, CAPOWN, CAPCARRY, CAPNF, CAPROOT, CAPCM1, INMERK,
 RNG_ACC, RNG_START, RBIND_VIN, RBIND_VOUT1, RBIND_VOUT2) = range(27)


def _periodic(T, D):
    """Public periodic selector columns, fully determined by (T, D): round constants, the absorb schedule for
    each witness register (including the two output regions), region reset/capture rows, Merkle block markers,
    and the C-3 range-region selectors. Both prover and verifier derive these from the protocol geometry alone,
    so a prover cannot relocate a region, an absorb slot, or a range-bind row."""
    out1, out2, sponge_end = _bounds(D)
    total = _total(D)
    def col(fn):
        """0/1 selector column: fn(row) over all T rows."""
        return [1 if fn(r) else 0 for r in range(T)]
    lvl_end = lambda r, upto: MERK <= r < out1 and (r - MERK) % RPL == RPL - 1 and 0 <= (r - MERK) // RPL < upto
    rng = lambda r: sponge_end <= r < total
    p = [None] * 27
    p[RC0] = [alghash.RC[r % R][0] for r in range(T)]
    p[RC1] = [alghash.RC[r % R][1] for r in range(T)]
    p[ANSK] = col(lambda r: r in (R - 1, 7 * R - 1))
    p[ARHO] = col(lambda r: r in (5 * R - 1, 8 * R - 1))
    p[AOWN] = col(lambda r: r == 4 * R - 1)
    p[AVIN] = col(lambda r: r == 3 * R - 1)
    p[AVOUT1] = col(lambda r: r == out1 + R - 1)
    p[AVOUT2] = col(lambda r: r == out2 + R - 1)
    p[AFREE] = col(lambda r: r in (out1 + 2 * R - 1, out1 + 3 * R - 1, out2 + 2 * R - 1, out2 + 3 * R - 1))
    p[B0] = col(lambda r: MERK <= r < out1 and (r - MERK) % RPL == R - 1)
    p[B1] = col(lambda r: MERK <= r < out1 and (r - MERK) % RPL == 2 * R - 1)
    p[RCM] = col(lambda r: r == OWN_END - 1)
    p[RNF] = col(lambda r: r == COM_END - 1)
    p[RNODE] = col(lambda r: r == NUL_END - 1 or lvl_end(r, D - 1))
    p[ROUT1] = col(lambda r: r == out1 - 1)
    p[ROUT2] = col(lambda r: r == out2 - 1)
    p[CAPOWN] = col(lambda r: r == OWN_END - 1)
    p[CAPCARRY] = col(lambda r: r == COM_END - 1 or lvl_end(r, D - 1))
    p[CAPNF] = col(lambda r: r == NUL_END - 1)
    p[CAPROOT] = col(lambda r: r == out1 - 1)
    p[CAPCM1] = col(lambda r: r == out2 - 1)
    p[INMERK] = col(lambda r: MERK <= r < out1)
    # C-3 range region selectors
    p[RNG_ACC] = col(lambda r: rng(r) and (r - sponge_end) % RNG_BLOCK < RNG_NIBBLES)
    p[RNG_START] = col(lambda r: rng(r) and (r - sponge_end) % RNG_BLOCK == 0)
    p[RBIND_VIN] = col(lambda r: r == sponge_end + 0 * RNG_BLOCK + RNG_NIBBLES)
    p[RBIND_VOUT1] = col(lambda r: r == sponge_end + 1 * RNG_BLOCK + RNG_NIBBLES)
    p[RBIND_VOUT2] = col(lambda r: r == sponge_end + 2 * RNG_BLOCK + RNG_NIBBLES)
    return p


def _transitions():
    """The 2-output join-split AIR: one list of transition polynomials, each gated to its region by the
    periodic selectors so a single constraint set covers the whole heterogeneous trace. Same structure as
    joinsplit_circuit plus the CMOUT1 capture, the VOUT2 absorb, 2-output conservation, and a third range
    block. Max constraint degree = ALPHA (the S-box)."""
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
        tag injected at the reset row (at most one reset selector is 1, so this is that region's separator;
        both OUTPUT regions restart under DOM_CM)."""
        left = F.add(cur[CARRY], F.mul(cur[DIR], F.sub(cur[SIB], cur[CARRY])))
        right = F.add(cur[SIB], F.mul(cur[DIR], F.sub(cur[CARRY], cur[SIB])))
        reset = F.add(F.add(F.add(per[RCM], per[RNF]), per[RNODE]), F.add(per[ROUT1], per[ROUT2]))
        reset_dom = F.add(F.add(F.mul(per[RCM], A.DOM_CM), F.mul(per[RNF], A.DOM_NF)),
                          F.add(F.mul(per[RNODE], A.DOM_NODE),
                                F.add(F.mul(per[ROUT1], A.DOM_CM), F.mul(per[ROUT2], A.DOM_CM))))
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
        ab_srcs = [F.mul(per[ANSK], cur[NSK]), F.mul(per[ARHO], cur[RHO]), F.mul(per[AOWN], cur[OWN]),
                   F.mul(per[AVIN], cur[VIN]), F.mul(per[AVOUT1], cur[VOUT1]), F.mul(per[AVOUT2], cur[VOUT2]),
                   F.mul(per[AFREE], nxt[AB]), F.mul(per[B0], left), F.mul(per[B1], right)]
        absorbed = 0
        for t in ab_srcs:
            absorbed = F.add(absorbed, t)
        return F.sub(nxt[S0], F.add(reset_dom, F.mul(F.sub(1, reset), F.add(r0, absorbed))))
    def c_ab(cur, nxt, per):
        """AB register discipline: at each scheduled set-row AB' must equal the scheduled message (domain tag,
        register value, or Merkle child); on AFREE rows it is free witness (the secret output openings — the
        zero-knowledge part); everywhere else it holds. Keeps c_s0's absorbed values well-defined per block."""
        left, right, _, _ = parts(cur, per)
        setm = 0
        for s in (per[RCM], per[RNF], per[RNODE], per[ROUT1], per[ROUT2], per[ANSK], per[ARHO], per[AOWN],
                  per[AVIN], per[AVOUT1], per[AVOUT2], per[B0], per[B1]):
            setm = F.add(setm, s)
        hold = F.sub(F.sub(1, setm), per[AFREE])
        terms = [
            F.mul(per[RCM], F.sub(nxt[AB], A.DOM_CM)), F.mul(per[RNF], F.sub(nxt[AB], A.DOM_NF)),
            F.mul(per[RNODE], F.sub(nxt[AB], A.DOM_NODE)),
            F.mul(per[ROUT1], F.sub(nxt[AB], A.DOM_CM)), F.mul(per[ROUT2], F.sub(nxt[AB], A.DOM_CM)),
            F.mul(per[ANSK], F.sub(nxt[AB], cur[NSK])), F.mul(per[ARHO], F.sub(nxt[AB], cur[RHO])),
            F.mul(per[AOWN], F.sub(nxt[AB], cur[OWN])), F.mul(per[AVIN], F.sub(nxt[AB], cur[VIN])),
            F.mul(per[AVOUT1], F.sub(nxt[AB], cur[VOUT1])), F.mul(per[AVOUT2], F.sub(nxt[AB], cur[VOUT2])),
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
        """NFREG capture: the nullifier, pinned to the public nf by the sponge_end boundary."""
        return _cap(cur, nxt, per, NFREG, CAPNF)
    def c_root(cur, nxt, per):
        """ROOTREG capture: the Merkle root, pinned to the public anchor root by the sponge_end boundary."""
        return _cap(cur, nxt, per, ROOTREG, CAPROOT)
    def c_cm1(cur, nxt, per):
        """CMOUT1 capture: cm_out1 at OUTPUT1's end, so it survives OUTPUT2 and is boundary-checkable at
        sponge_end (cm_out2 needs no register — it is the final sponge s0 itself)."""
        return _cap(cur, nxt, per, CMOUT1, CAPCM1)
    def c_hold(reg):
        """Constraint factory: reg is constant over the whole trace (the witness registers
        nsk/rho/v_in/v_out1/v_out2), so every region reads the SAME secret value."""
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
        """2-output value conservation: CONS = v_in - v_out1 - v_out2 on every row; the boundary pins CONS to
        fee - public_value (mod P — integer-exact only together with the C-3 range proof)."""
        return F.sub(cur[CONS], F.sub(F.sub(cur[VIN], cur[VOUT1]), cur[VOUT2]))
    # --- C-3 range constraints ---
    def _nib(cur):
        """The row's 4-bit nibble recomposed from its bit columns (degree 1; sound given c_bit)."""
        return F.add(F.add(F.mul(8, cur[RB0]), F.mul(4, cur[RB1])), F.add(F.mul(2, cur[RB2]), cur[RB3]))
    def c_rng_acc(cur, nxt, per):
        """Range accumulator recurrence acc' = 16·acc + nibble on accumulation rows: with boolean bits and a
        zeroed start, 16 steps make ACC at the bind row EXACTLY the 64-bit integer the bit columns spell."""
        return F.mul(per[RNG_ACC], F.sub(nxt[ACC], F.add(F.mul(16, cur[ACC]), _nib(cur))))
    def c_rng_reset(cur, nxt, per):
        """ACC = 0 at each block start, so no value leaks between the per-value range blocks."""
        return F.mul(per[RNG_START], cur[ACC])
    def c_rng_top(cur, nxt, per):
        """Pins the MSB nibble's top 3 bits to 0 — each bound value < 2^61 (see the comment below for why the
        2-output conservation span demands the third bit too)."""
        # top 3 bits (of the MSB nibble at block start) = 0 -> each value < 2^61. With TWO outputs the
        # conservation span is v_in + |public_value| vs v_out1 + v_out2 + fee; bounding every note value AND
        # (state-side) fee/|public_value| to <=2^61 keeps the worst-case |LHS-RHS| = 2*2^61 + 2^61 + 2^61 = 2^63
        # < P, so mod-P conservation coincides with INTEGER conservation. At 2^62 (top-2-bits) the five ~2^62
        # terms summed past P and a -P wraparound let a 1-coin input record a 2^62-coin exit (C-3b).
        return F.mul(per[RNG_START], F.add(F.add(cur[RB0], cur[RB1]), cur[RB2]))
    def c_bit(reg):
        """Constraint factory: bit column is boolean on accumulation rows — the soundness hinge of the whole
        decomposition (non-bit values would let ACC reach any field element)."""
        return lambda cur, nxt, per: F.mul(per[RNG_ACC], F.mul(cur[reg], F.sub(1, cur[reg])))
    def c_bind(sel, val):
        """Constraint factory: at the block's bind row ACC equals the value register — connecting the range
        decomposition to the very value conservation is computed over."""
        return lambda cur, nxt, per: F.mul(per[sel], F.sub(cur[ACC], cur[val]))
    return [c_s1, c_s0, c_ab, c_carry, c_own, c_nf, c_root, c_cm1,
            c_hold(NSK), c_hold(RHO), c_hold(VIN), c_hold(VOUT1), c_hold(VOUT2),
            c_sib, c_dir, c_dirbit, c_cons,
            c_rng_acc, c_rng_reset, c_rng_top,
            c_bit(RB0), c_bit(RB1), c_bit(RB2), c_bit(RB3),
            c_bind(RBIND_VIN, VIN), c_bind(RBIND_VOUT1, VOUT1), c_bind(RBIND_VOUT2, VOUT2)]


def prove_transfer(nsk, v_in, rho_in, siblings, dirs, v1, o1, r1, v2, o2, r2, public_value, fee, num_queries=stark.NUM_QUERIES, aux=None):
    """Prove the 2-output join-split for the given witness; returns (proof, root, nf, cm_out1, cm_out2).
    Boundaries pin the initial sponge state (domain tag + IV), CONS = fee - public_value, and the captured
    root/nf/cm_out1 plus the final sponge s0 (= cm_out2) at sponge_end. proof["D"] carries the tree depth from
    which the verifier rebuilds the whole geometry; `aux` binds extra public data (e.g. a withdraw address)
    into the Fiat–Shamir transcript."""
    tr, T, D, root, nf, cm1, cm2 = build_trace(nsk, v_in, rho_in, siblings, dirs, v1, o1, r1, v2, o2, r2)
    per = _periodic(T, D)
    _, _, sponge_end = _bounds(D)
    cons_pub = F.sub(fee % F.P, public_value % F.P)
    bnd = [(0, S0, alghash.DOM_OWNER), (0, S1, alghash.IV), (0, AB, alghash.DOM_OWNER), (0, CONS, cons_pub),
           (sponge_end, ROOTREG, root), (sponge_end, NFREG, nf), (sponge_end, CMOUT1, cm1), (sponge_end, S0, cm2)]
    proof = stark.prove(tr, _transitions(), bnd, periodic=per, max_degree=MAX_DEGREE, num_queries=num_queries, aux=aux)
    proof["D"] = D
    return proof, root, nf, cm1, cm2


def verify_transfer(proof, root, nf, cm1, cm2, public_value, fee, root_is_known, aux=None):
    """Verify a 2-output join-split proof against the public (root, nf, cm_out1, cm_out2, public_value, fee).
    Checks the anchor root is known, pins the trace geometry (H1: T must be exactly the honest value for D),
    rebuilds the same periodic columns and boundary set as the prover, and runs the STARK verifier. Returns
    (ok, reason)."""
    if not root_is_known(root):
        return False, "unknown anchor root"
    D, T = proof["D"], proof["T"]
    # H1: T and D fully determine the trace layout (region boundaries + the C-3 range-block row positions). A
    # prover that under-declares T can push the RANGE-bind rows past row T so their selectors are all-zero and
    # the range proof becomes vacuous (out-of-range values then pass -> wraparound exit). Pin T to the exact
    # value the honest prover computes for this D, so the range block always lands inside the trace.
    if not isinstance(D, int) or not isinstance(T, int) or D < 1 or T != _next_pow2(_total(D) + 1):
        return False, "bad trace geometry"
    per = _periodic(T, D)
    _, _, sponge_end = _bounds(D)
    cons_pub = F.sub(fee % F.P, public_value % F.P)
    bnd = [(0, S0, alghash.DOM_OWNER), (0, S1, alghash.IV), (0, AB, alghash.DOM_OWNER), (0, CONS, cons_pub),
           (sponge_end, ROOTREG, root % F.P), (sponge_end, NFREG, nf % F.P),
           (sponge_end, CMOUT1, cm1 % F.P), (sponge_end, S0, cm2 % F.P)]
    return stark.verify(proof, _transitions(), bnd, periodic=per, max_degree=MAX_DEGREE, aux=aux)
