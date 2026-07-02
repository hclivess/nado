"""
Full AUTHORISED-SPEND circuit (doc/privacy.md) — one zero-knowledge proof of the complete input side of a
shielded spend, revealing only the public root + nullifier:

  owner = hashn([DOM_OWNER, nsk])                      (spend-key binding)
  cm    = hashn([DOM_CM, value, owner, rho])           (note commitment)
  nf    = hashn([DOM_NF, nsk, rho])                    (nullifier — revealed)
  membership(cm, path, dirs) = root                    (the note is in the tree)

The shared secrets nsk (owner + nullifier) and rho (commitment + nullifier) live in PERSISTENT register
columns held across the whole trace, so the four regions are bound to the SAME witness without revealing it —
that binding is what makes revealing nf an AUTHORISED spend (only the key holder can produce it) and stops a
double-spend from a note whose opening you know but whose key you don't.

Four sponge regions run back-to-back (OWNER, COMMIT, NULLIFIER, MEMBERSHIP); each region-end HANDOFF captures
that region's output into a register and resets the sponge with the next domain tag. Periodic public columns
select, per row, which register (or free value / Merkle child) is absorbed and which reset/capture fires.
"""
from execnode.stark import field as F, alghash, membership as MB, stark

R = alghash.ROUNDS
# columns
S0, S1, AB, CARRY, SIB, DIR, NSK, RHO, OWN, NFREG = range(10)
RPL = 3 * R
OWN_END, COM_END, NUL_END = 2 * R, 6 * R, 9 * R          # region-end rows (exclusive block counts: 2,4,3)
MERK = NUL_END                                           # membership starts here
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


def full_spend(nsk, value, rho, siblings, dirs):
    owner = alghash.owner_of(nsk)
    cm = alghash.commit(value, owner, rho)
    nf = alghash.nullifier(nsk, rho)
    root = MB.merkle_root_from_path(cm, siblings, dirs)
    return owner, cm, nf, root


def build_trace(nsk, value, rho, siblings, dirs):
    nsk, value, rho = nsk % F.P, value % F.P, rho % F.P
    D = len(siblings)
    total = MERK + D * RPL
    T = _next_pow2(total + 1)
    tr = []
    s0, s1, ab = alghash.DOM_OWNER, alghash.IV, alghash.DOM_OWNER      # OWNER start
    carry = sib = dr = own = nfreg = 0
    lvl = 0
    for r in range(T):
        tr.append([s0, s1, ab, carry, sib, dr, nsk, rho, own, nfreg])
        r0, r1 = _round(s0, s1, r)
        last = (r % R == R - 1)
        if r < OWN_END:                                   # OWNER: [DOM_OWNER, nsk]
            if r == OWN_END - 1:                          # handoff -> COMMIT: capture owner, reset DOM_CM
                own = r0; s0, s1, ab = alghash.DOM_CM, alghash.IV, alghash.DOM_CM
            elif last:                                    # absorb nsk (block 1)
                s0, s1, ab = F.add(r0, nsk), r1, nsk
            else:
                s0, s1 = r0, r1
        elif r < COM_END:                                 # COMMIT: [DOM_CM, value, owner, rho]
            if r == COM_END - 1:                          # handoff -> NULLIFIER: capture cm into carry, reset DOM_NF
                carry = r0; s0, s1, ab = alghash.DOM_NF, alghash.IV, alghash.DOM_NF
            elif last:
                blk = (r - 2 * R) // R                    # 0 -> just after value block? blocks: value@3R-1, owner@4R-1, rho@5R-1
                msg = value if r == 3 * R - 1 else (own if r == 4 * R - 1 else rho)
                s0, s1, ab = F.add(r0, msg), r1, msg
            else:
                s0, s1 = r0, r1
        elif r < NUL_END:                                 # NULLIFIER: [DOM_NF, nsk, rho]
            if r == NUL_END - 1:                          # handoff -> MEMBERSHIP: capture nf, reset DOM_NODE, seed sib/dir
                nfreg = r0; sib, dr = siblings[0] % F.P, dirs[0] % F.P
                s0, s1, ab = alghash.DOM_NODE, alghash.IV, alghash.DOM_NODE
            elif last:
                msg = nsk if r == 7 * R - 1 else rho
                s0, s1, ab = F.add(r0, msg), r1, msg
            else:
                s0, s1 = r0, r1
        else:                                             # MEMBERSHIP
            pos = (r - MERK) % RPL
            block = pos // R
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
                else:
                    s0, s1 = r0, r1
            else:
                s0, s1 = r0, r1
    return tr, T, D, tr[MERK + D * RPL][S0], tr[MERK + D * RPL][NFREG]


# periodic-column indices
RC0, RC1, ANSK, ARHO, AOWN, AFREE, B0, B1, RCM, RNF, RNODE, CAPOWN, CAPCARRY, CAPNF, INMERK = range(15)


def _periodic(T, D):
    def col(fn): return [1 if fn(r) else 0 for r in range(T)]
    lvl_end = lambda r, upto: r >= MERK and (r - MERK) % RPL == RPL - 1 and 0 <= (r - MERK) // RPL < upto
    p = [None] * 15
    p[RC0] = [alghash.RC[r % R][0] for r in range(T)]
    p[RC1] = [alghash.RC[r % R][1] for r in range(T)]
    p[ANSK] = col(lambda r: r == R - 1 or r == 7 * R - 1)                 # absorb nsk (OWNER, NULLIFIER)
    p[ARHO] = col(lambda r: r == 5 * R - 1 or r == 8 * R - 1)             # absorb rho (COMMIT, NULLIFIER)
    p[AOWN] = col(lambda r: r == 4 * R - 1)                               # absorb owner (COMMIT)
    p[AFREE] = col(lambda r: r == 3 * R - 1)                              # absorb value (COMMIT, free)
    p[B0] = col(lambda r: r >= MERK and (r - MERK) % RPL == R - 1)        # merkle left
    p[B1] = col(lambda r: r >= MERK and (r - MERK) % RPL == 2 * R - 1)    # merkle right
    p[RCM] = col(lambda r: r == OWN_END - 1)                             # reset -> DOM_CM
    p[RNF] = col(lambda r: r == COM_END - 1)                             # reset -> DOM_NF
    p[RNODE] = col(lambda r: r == NUL_END - 1 or lvl_end(r, D - 1))      # reset -> DOM_NODE (also sib/dir load)
    p[CAPOWN] = col(lambda r: r == OWN_END - 1)                          # own <- r0
    p[CAPCARRY] = col(lambda r: r == COM_END - 1 or lvl_end(r, D - 1))   # carry <- r0 (cm / node hash)
    p[CAPNF] = col(lambda r: r == NUL_END - 1)                           # nfreg <- r0 (nf)
    p[INMERK] = col(lambda r: r >= MERK)
    return p


def _transitions():
    def rnd(cur, per):
        t0 = F.pw(F.add(cur[S0], per[RC0]), alghash.ALPHA)
        t1 = F.pw(F.add(cur[S1], per[RC1]), alghash.ALPHA)
        return F.add(F.mul(2, t0), t1), F.add(t0, F.mul(3, t1))
    def parts(cur, per):
        left = F.add(cur[CARRY], F.mul(cur[DIR], F.sub(cur[SIB], cur[CARRY])))
        right = F.add(cur[SIB], F.mul(cur[DIR], F.sub(cur[CARRY], cur[SIB])))
        reset = F.add(F.add(per[RCM], per[RNF]), per[RNODE])
        reset_dom = F.add(F.add(F.mul(per[RCM], alghash.DOM_CM), F.mul(per[RNF], alghash.DOM_NF)),
                          F.mul(per[RNODE], alghash.DOM_NODE))
        return left, right, reset, reset_dom
    def c_s1(cur, nxt, per):
        _, r1 = rnd(cur, per); _, _, reset, _ = parts(cur, per)
        return F.sub(nxt[S1], F.add(F.mul(reset, alghash.IV), F.mul(F.sub(1, reset), r1)))
    def c_s0(cur, nxt, per):
        r0, _ = rnd(cur, per); left, right, reset, reset_dom = parts(cur, per)
        absorbed = F.add(F.add(F.add(F.mul(per[ANSK], cur[NSK]), F.mul(per[ARHO], cur[RHO])),
                               F.add(F.mul(per[AOWN], cur[OWN]), F.mul(per[AFREE], nxt[AB]))),
                         F.add(F.mul(per[B0], left), F.mul(per[B1], right)))
        return F.sub(nxt[S0], F.add(reset_dom, F.mul(F.sub(1, reset), F.add(r0, absorbed))))
    def c_ab(cur, nxt, per):
        left, right, _, _ = parts(cur, per)
        setm = F.add(F.add(F.add(per[RCM], per[RNF]), F.add(per[RNODE], per[ANSK])),
                     F.add(F.add(per[ARHO], per[AOWN]), F.add(per[B0], per[B1])))
        hold = F.sub(F.sub(1, setm), per[AFREE])                        # a_free leaves ab unconstrained (free)
        return F.add(F.add(F.add(F.mul(per[RCM], F.sub(nxt[AB], alghash.DOM_CM)),
                                 F.mul(per[RNF], F.sub(nxt[AB], alghash.DOM_NF))),
                           F.add(F.mul(per[RNODE], F.sub(nxt[AB], alghash.DOM_NODE)),
                                 F.mul(per[ANSK], F.sub(nxt[AB], cur[NSK])))),
                     F.add(F.add(F.mul(per[ARHO], F.sub(nxt[AB], cur[RHO])),
                                 F.mul(per[AOWN], F.sub(nxt[AB], cur[OWN]))),
                           F.add(F.add(F.mul(per[B0], F.sub(nxt[AB], left)), F.mul(per[B1], F.sub(nxt[AB], right))),
                                 F.mul(hold, F.sub(nxt[AB], cur[AB])))))
    def _cap(cur, nxt, per, reg, sel):
        r0, _ = rnd(cur, per)
        return F.sub(nxt[reg], F.add(F.mul(per[sel], r0), F.mul(F.sub(1, per[sel]), cur[reg])))
    def c_carry(cur, nxt, per): return _cap(cur, nxt, per, CARRY, CAPCARRY)
    def c_own(cur, nxt, per): return _cap(cur, nxt, per, OWN, CAPOWN)
    def c_nf(cur, nxt, per): return _cap(cur, nxt, per, NFREG, CAPNF)
    def c_nsk(cur, nxt, per): return F.sub(nxt[NSK], cur[NSK])
    def c_rho(cur, nxt, per): return F.sub(nxt[RHO], cur[RHO])
    def c_sib(cur, nxt, per): return F.mul(F.sub(1, per[RNODE]), F.sub(nxt[SIB], cur[SIB]))   # held except on load
    def c_dir(cur, nxt, per): return F.mul(F.sub(1, per[RNODE]), F.sub(nxt[DIR], cur[DIR]))
    def c_dirbit(cur, nxt, per): return F.mul(per[INMERK], F.mul(cur[DIR], F.sub(1, cur[DIR])))
    return [c_s1, c_s0, c_ab, c_carry, c_own, c_nf, c_nsk, c_rho, c_sib, c_dir, c_dirbit]


def prove_spend(nsk, value, rho, siblings, dirs, num_queries=40):
    tr, T, D, root, nf = build_trace(nsk, value, rho, siblings, dirs)
    per = _periodic(T, D)
    end = MERK + D * RPL
    bnd = [(0, S0, alghash.DOM_OWNER), (0, S1, alghash.IV), (0, AB, alghash.DOM_OWNER),
           (end, S0, root), (end, NFREG, nf)]
    proof = stark.prove(tr, _transitions(), bnd, periodic=per, max_degree=MAX_DEGREE, num_queries=num_queries)
    proof["D"] = D
    return proof, root, nf


def verify_spend(proof, root, nf, root_is_known):
    if not root_is_known(root):
        return False, "unknown anchor root"
    D, T = proof["D"], proof["T"]
    per = _periodic(T, D)
    end = MERK + D * RPL
    bnd = [(0, S0, alghash.DOM_OWNER), (0, S1, alghash.IV), (0, AB, alghash.DOM_OWNER),
           (end, S0, root % F.P), (end, NFREG, nf % F.P)]
    return stark.verify(proof, _transitions(), bnd, periodic=per, max_degree=MAX_DEGREE)
