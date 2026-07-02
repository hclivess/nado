"""
2-output JOIN-SPLIT circuit (doc/privacy.md) — 1 input, 2 outputs, so a shielded transfer sends any amount and
keeps the CHANGE (out1 = recipient, out2 = change), all in one zero-knowledge STARK. Extends
joinsplit_circuit with a second OUTPUT region and 2-output value conservation:

  owner=H(nsk) · cm_in=commit(v_in,owner,rho_in) · membership(cm_in,path)=root · nf=H(nsk,rho_in) ·
  cm_out1=commit(v_out1,owner1,rho1) · cm_out2=commit(v_out2,owner2,rho2) ·
  v_in + public_value == v_out1 + v_out2 + fee

Public: root, nf, cm_out1, cm_out2, public_value, fee. Six sponge regions run back-to-back
(OWNER, COMMIT, NULLIFIER, MEMBERSHIP, OUTPUT1, OUTPUT2); handoffs capture each region's output into a register.
"""
from execnode.stark import field as F, alghash, membership as MB, stark

R = alghash.ROUNDS
(S0, S1, AB, CARRY, SIB, DIR, NSK, RHO, OWN, NFREG, VIN, VOUT1, VOUT2, CONS, ROOTREG, CMOUT1) = range(16)
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


def transfer(nsk, v_in, rho_in, siblings, dirs, v1, o1, r1, v2, o2, r2):
    owner = alghash.owner_of(nsk)
    cm_in = alghash.commit(v_in, owner, rho_in)
    nf = alghash.nullifier(nsk, rho_in)
    root = MB.merkle_root_from_path(cm_in, siblings, dirs)
    return owner, cm_in, nf, root, alghash.commit(v1, o1, r1), alghash.commit(v2, o2, r2)


def _bounds(D):
    out1 = MERK + D * RPL
    out2 = out1 + 4 * R
    total = out2 + 4 * R
    return out1, out2, total


def build_trace(nsk, v_in, rho_in, siblings, dirs, v1, o1, r1, v2, o2, r2):
    m = lambda x: x % F.P
    nsk, v_in, rho_in = m(nsk), m(v_in), m(rho_in)
    v1, o1, r1, v2, o2, r2 = m(v1), m(o1), m(r1), m(v2), m(o2), m(r2)
    D = len(siblings)
    out1, out2, total = _bounds(D)
    T = _next_pow2(total + 1)
    cons = F.sub(F.sub(v_in, v1), v2)                  # = fee - public_value
    tr = []
    s0, s1, ab = alghash.DOM_OWNER, alghash.IV, alghash.DOM_OWNER
    carry = sib = dr = own = nfreg = rootreg = cmout1 = 0
    lvl = 0
    for r in range(T):
        tr.append([s0, s1, ab, carry, sib, dr, nsk, rho_in, own, nfreg, v_in, v1, v2, cons, rootreg, cmout1])
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
        else:                                           # OUTPUT2 [DOM_CM, v2, o2, r2]
            if last and r < total - 1:
                oi = (r - out2) // R
                msg = v2 if oi == 0 else (o2 if oi == 1 else r2)
                s0, s1, ab = F.add(r0, msg), r1r, msg
            else:
                s0, s1 = r0, r1r
    return tr, T, D, rootreg, nfreg, tr[out2][CMOUT1], tr[total][S0]   # root, nf, cm_out1, cm_out2


(RC0, RC1, ANSK, ARHO, AOWN, AVIN, AVOUT1, AVOUT2, AFREE, B0, B1, RCM, RNF, RNODE,
 ROUT1, ROUT2, CAPOWN, CAPCARRY, CAPNF, CAPROOT, CAPCM1, INMERK) = range(22)


def _periodic(T, D):
    out1, out2, total = _bounds(D)
    def col(fn): return [1 if fn(r) else 0 for r in range(T)]
    lvl_end = lambda r, upto: MERK <= r < out1 and (r - MERK) % RPL == RPL - 1 and 0 <= (r - MERK) // RPL < upto
    p = [None] * 22
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
        reset = F.add(F.add(F.add(per[RCM], per[RNF]), per[RNODE]), F.add(per[ROUT1], per[ROUT2]))
        reset_dom = F.add(F.add(F.mul(per[RCM], A.DOM_CM), F.mul(per[RNF], A.DOM_NF)),
                          F.add(F.mul(per[RNODE], A.DOM_NODE),
                                F.add(F.mul(per[ROUT1], A.DOM_CM), F.mul(per[ROUT2], A.DOM_CM))))
        return left, right, reset, reset_dom
    def c_s1(cur, nxt, per):
        _, r1 = rnd(cur, per); _, _, reset, _ = parts(cur, per)
        return F.sub(nxt[S1], F.add(F.mul(reset, A.IV), F.mul(F.sub(1, reset), r1)))
    def c_s0(cur, nxt, per):
        r0, _ = rnd(cur, per); left, right, reset, reset_dom = parts(cur, per)
        ab_srcs = [F.mul(per[ANSK], cur[NSK]), F.mul(per[ARHO], cur[RHO]), F.mul(per[AOWN], cur[OWN]),
                   F.mul(per[AVIN], cur[VIN]), F.mul(per[AVOUT1], cur[VOUT1]), F.mul(per[AVOUT2], cur[VOUT2]),
                   F.mul(per[AFREE], nxt[AB]), F.mul(per[B0], left), F.mul(per[B1], right)]
        absorbed = 0
        for t in ab_srcs:
            absorbed = F.add(absorbed, t)
        return F.sub(nxt[S0], F.add(reset_dom, F.mul(F.sub(1, reset), F.add(r0, absorbed))))
    def c_ab(cur, nxt, per):
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
        r0, _ = rnd(cur, per)
        return F.sub(nxt[reg], F.add(F.mul(per[sel], r0), F.mul(F.sub(1, per[sel]), cur[reg])))
    def c_carry(cur, nxt, per): return _cap(cur, nxt, per, CARRY, CAPCARRY)
    def c_own(cur, nxt, per): return _cap(cur, nxt, per, OWN, CAPOWN)
    def c_nf(cur, nxt, per): return _cap(cur, nxt, per, NFREG, CAPNF)
    def c_root(cur, nxt, per): return _cap(cur, nxt, per, ROOTREG, CAPROOT)
    def c_cm1(cur, nxt, per): return _cap(cur, nxt, per, CMOUT1, CAPCM1)
    def c_hold(reg): return lambda cur, nxt, per: F.sub(nxt[reg], cur[reg])
    def c_sib(cur, nxt, per): return F.mul(F.sub(1, per[RNODE]), F.sub(nxt[SIB], cur[SIB]))
    def c_dir(cur, nxt, per): return F.mul(F.sub(1, per[RNODE]), F.sub(nxt[DIR], cur[DIR]))
    def c_dirbit(cur, nxt, per): return F.mul(per[INMERK], F.mul(cur[DIR], F.sub(1, cur[DIR])))
    def c_cons(cur, nxt, per): return F.sub(cur[CONS], F.sub(F.sub(cur[VIN], cur[VOUT1]), cur[VOUT2]))
    return [c_s1, c_s0, c_ab, c_carry, c_own, c_nf, c_root, c_cm1,
            c_hold(NSK), c_hold(RHO), c_hold(VIN), c_hold(VOUT1), c_hold(VOUT2),
            c_sib, c_dir, c_dirbit, c_cons]


def prove_transfer(nsk, v_in, rho_in, siblings, dirs, v1, o1, r1, v2, o2, r2, public_value, fee, num_queries=32):
    tr, T, D, root, nf, cm1, cm2 = build_trace(nsk, v_in, rho_in, siblings, dirs, v1, o1, r1, v2, o2, r2)
    per = _periodic(T, D)
    out1, out2, total = _bounds(D)
    cons_pub = F.sub(fee % F.P, public_value % F.P)
    bnd = [(0, S0, alghash.DOM_OWNER), (0, S1, alghash.IV), (0, AB, alghash.DOM_OWNER), (0, CONS, cons_pub),
           (total, ROOTREG, root), (total, NFREG, nf), (total, CMOUT1, cm1), (total, S0, cm2)]
    proof = stark.prove(tr, _transitions(), bnd, periodic=per, max_degree=MAX_DEGREE, num_queries=num_queries)
    proof["D"] = D
    return proof, root, nf, cm1, cm2


def verify_transfer(proof, root, nf, cm1, cm2, public_value, fee, root_is_known):
    if not root_is_known(root):
        return False, "unknown anchor root"
    D, T = proof["D"], proof["T"]
    per = _periodic(T, D)
    out1, out2, total = _bounds(D)
    cons_pub = F.sub(fee % F.P, public_value % F.P)
    bnd = [(0, S0, alghash.DOM_OWNER), (0, S1, alghash.IV), (0, AB, alghash.DOM_OWNER), (0, CONS, cons_pub),
           (total, ROOTREG, root % F.P), (total, NFREG, nf % F.P), (total, CMOUT1, cm1 % F.P), (total, S0, cm2 % F.P)]
    return stark.verify(proof, _transitions(), bnd, periodic=per, max_degree=MAX_DEGREE)
