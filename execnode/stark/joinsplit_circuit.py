"""
Full 1-in/1-out JOIN-SPLIT circuit (doc/privacy.md) — the complete shielded transfer statement in ONE
zero-knowledge proof, revealing only the public root, nullifier, output commitment, public_value and fee:

  owner   = hashn([DOM_OWNER, nsk])
  cm_in   = hashn([DOM_CM, v_in, owner, rho_in])          membership(cm_in, path) = root
  nf      = hashn([DOM_NF, nsk, rho_in])                  (revealed)
  cm_out  = hashn([DOM_CM, v_out, owner_out, rho_out])    (revealed)
  v_in + public_value = v_out + fee                        (value conservation, over the SECRET values)

Extends the authorised-spend circuit (execnode/stark/spend_full) with an OUTPUT region and value conservation.
v_in and v_out live in persistent register columns so conservation is a linear check over the SECRET values;
the CONS register (= v_in - v_out) is pinned to (fee - public_value). Regions run back-to-back
(OWNER, COMMIT, NULLIFIER, MEMBERSHIP, OUTPUT); handoffs capture each region's output into a register.
"""
from execnode.stark import field as F, alghash, membership as MB, stark

R = alghash.ROUNDS
# columns
(S0, S1, AB, CARRY, SIB, DIR, NSK, RHO, OWN, NFREG, VIN, VOUT, CONS, ROOTREG) = range(14)
RPL = 3 * R
OWN_END, COM_END, NUL_END = 2 * R, 6 * R, 9 * R
MERK = NUL_END
MAX_DEGREE = alghash.ALPHA


def _next_pow2(x):
    p = 1
    while p < x:
        p <<= 1
    return p


def _round(s0, s1, r):
    t0 = alghash.sbox(F.add(s0, alghash.RC[r % R][0]))
    t1 = alghash.sbox(F.add(s1, alghash.RC[r % R][1]))
    return F.add(F.mul(2, t0), t1), F.add(t0, F.mul(3, t1))


def transfer(nsk, v_in, rho_in, siblings, dirs, v_out, owner_out, rho_out):
    owner = alghash.owner_of(nsk)
    cm_in = alghash.commit(v_in, owner, rho_in)
    nf = alghash.nullifier(nsk, rho_in)
    root = MB.merkle_root_from_path(cm_in, siblings, dirs)
    cm_out = alghash.commit(v_out, owner_out, rho_out)
    return owner, cm_in, nf, root, cm_out


def build_trace(nsk, v_in, rho_in, siblings, dirs, v_out, owner_out, rho_out):
    nsk, v_in, rho_in = nsk % F.P, v_in % F.P, rho_in % F.P
    v_out, owner_out, rho_out = v_out % F.P, owner_out % F.P, rho_out % F.P
    D = len(siblings)
    out_start = MERK + D * RPL                          # OUTPUT region start (after membership)
    total = out_start + 4 * R
    T = _next_pow2(total + 1)
    cons = F.sub(v_in, v_out)                           # = fee - public_value (checked by boundary)
    tr = []
    s0, s1, ab = alghash.DOM_OWNER, alghash.IV, alghash.DOM_OWNER
    carry = sib = dr = own = nfreg = rootreg = 0
    lvl = 0
    for r in range(T):
        tr.append([s0, s1, ab, carry, sib, dr, nsk, rho_in, own, nfreg, v_in, v_out, cons, rootreg])
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
        else:                                           # OUTPUT [DOM_CM, v_out, owner_out, rho_out]
            if last and r < total - 1:
                oi = (r - out_start) // R
                msg = v_out if oi == 0 else (owner_out if oi == 1 else rho_out)
                s0, s1, ab = F.add(r0, msg), r1, msg
            else:
                s0, s1 = r0, r1
    return tr, T, D, rootreg, nfreg, tr[total][S0]      # root, nf, cm_out


(RC0, RC1, ANSK, ARHO, AOWN, AVIN, AVOUT, AFREE, B0, B1, RCM, RNF, RNODE, ROUT,
 CAPOWN, CAPCARRY, CAPNF, CAPROOT, INMERK) = range(19)


def _periodic(T, D):
    out_start = MERK + D * RPL
    def col(fn): return [1 if fn(r) else 0 for r in range(T)]
    lvl_end = lambda r, upto: r >= MERK and r < out_start and (r - MERK) % RPL == RPL - 1 and 0 <= (r - MERK) // RPL < upto
    p = [None] * 19
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
    return p


def _transitions():
    A = alghash
    def rnd(cur, per):
        t0 = F.pw(F.add(cur[S0], per[RC0]), A.ALPHA)
        t1 = F.pw(F.add(cur[S1], per[RC1]), A.ALPHA)
        return F.add(F.mul(2, t0), t1), F.add(t0, F.mul(3, t1))
    def parts(cur, per):
        left = F.add(cur[CARRY], F.mul(cur[DIR], F.sub(cur[SIB], cur[CARRY])))
        right = F.add(cur[SIB], F.mul(cur[DIR], F.sub(cur[CARRY], cur[SIB])))
        reset = F.add(F.add(per[RCM], per[RNF]), F.add(per[RNODE], per[ROUT]))
        reset_dom = F.add(F.add(F.mul(per[RCM], A.DOM_CM), F.mul(per[RNF], A.DOM_NF)),
                          F.add(F.mul(per[RNODE], A.DOM_NODE), F.mul(per[ROUT], A.DOM_CM)))
        return left, right, reset, reset_dom
    def c_s1(cur, nxt, per):
        _, r1 = rnd(cur, per); _, _, reset, _ = parts(cur, per)
        return F.sub(nxt[S1], F.add(F.mul(reset, A.IV), F.mul(F.sub(1, reset), r1)))
    def c_s0(cur, nxt, per):
        r0, _ = rnd(cur, per); left, right, reset, reset_dom = parts(cur, per)
        absorbed = F.add(
            F.add(F.add(F.mul(per[ANSK], cur[NSK]), F.mul(per[ARHO], cur[RHO])),
                  F.add(F.mul(per[AOWN], cur[OWN]), F.mul(per[AVIN], cur[VIN]))),
            F.add(F.add(F.mul(per[AVOUT], cur[VOUT]), F.mul(per[AFREE], nxt[AB])),
                  F.add(F.mul(per[B0], left), F.mul(per[B1], right))))
        return F.sub(nxt[S0], F.add(reset_dom, F.mul(F.sub(1, reset), F.add(r0, absorbed))))
    def c_ab(cur, nxt, per):
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
        r0, _ = rnd(cur, per)
        return F.sub(nxt[reg], F.add(F.mul(per[sel], r0), F.mul(F.sub(1, per[sel]), cur[reg])))
    def c_carry(cur, nxt, per): return _cap(cur, nxt, per, CARRY, CAPCARRY)
    def c_own(cur, nxt, per): return _cap(cur, nxt, per, OWN, CAPOWN)
    def c_nf(cur, nxt, per): return _cap(cur, nxt, per, NFREG, CAPNF)
    def c_root(cur, nxt, per): return _cap(cur, nxt, per, ROOTREG, CAPROOT)
    def c_hold(reg):
        return lambda cur, nxt, per: F.sub(nxt[reg], cur[reg])
    def c_sib(cur, nxt, per): return F.mul(F.sub(1, per[RNODE]), F.sub(nxt[SIB], cur[SIB]))
    def c_dir(cur, nxt, per): return F.mul(F.sub(1, per[RNODE]), F.sub(nxt[DIR], cur[DIR]))
    def c_dirbit(cur, nxt, per): return F.mul(per[INMERK], F.mul(cur[DIR], F.sub(1, cur[DIR])))
    def c_cons(cur, nxt, per): return F.sub(cur[CONS], F.sub(cur[VIN], cur[VOUT]))
    return [c_s1, c_s0, c_ab, c_carry, c_own, c_nf, c_root,
            c_hold(NSK), c_hold(RHO), c_hold(VIN), c_hold(VOUT),
            c_sib, c_dir, c_dirbit, c_cons]


def prove_transfer(nsk, v_in, rho_in, siblings, dirs, v_out, owner_out, rho_out, public_value, fee, num_queries=stark.NUM_QUERIES, aux=None):
    tr, T, D, root, nf, cm_out = build_trace(nsk, v_in, rho_in, siblings, dirs, v_out, owner_out, rho_out)
    per = _periodic(T, D)
    total = MERK + D * RPL + 4 * R
    cons_pub = F.sub(fee % F.P, public_value % F.P)                 # v_in - v_out must equal fee - public_value
    bnd = [(0, S0, alghash.DOM_OWNER), (0, S1, alghash.IV), (0, AB, alghash.DOM_OWNER),
           (0, CONS, cons_pub),
           (total, ROOTREG, root), (total, NFREG, nf), (total, S0, cm_out)]
    proof = stark.prove(tr, _transitions(), bnd, periodic=per, max_degree=MAX_DEGREE, num_queries=num_queries, aux=aux)
    proof["D"] = D
    return proof, root, nf, cm_out


def verify_transfer(proof, root, nf, cm_out, public_value, fee, root_is_known, aux=None):
    if not root_is_known(root):
        return False, "unknown anchor root"
    D, T = proof["D"], proof["T"]
    per = _periodic(T, D)
    total = MERK + D * RPL + 4 * R
    cons_pub = F.sub(fee % F.P, public_value % F.P)
    bnd = [(0, S0, alghash.DOM_OWNER), (0, S1, alghash.IV), (0, AB, alghash.DOM_OWNER),
           (0, CONS, cons_pub),
           (total, ROOTREG, root % F.P), (total, NFREG, nf % F.P), (total, S0, cm_out % F.P)]
    return stark.verify(proof, _transitions(), bnd, periodic=per, max_degree=MAX_DEGREE, aux=aux)
