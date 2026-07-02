"""
Composed SPEND circuit (doc/privacy.md) — one AIR that ties two gadgets so the witness stays shared + secret:
prove "I know an opening (value, owner, rho) whose note commitment cm = hashn([DOM_CM, value, owner, rho]) is a
leaf in the tree at the PUBLIC root", revealing NEITHER the opening NOR which leaf. This is the sound core of a
private spend (membership + commitment binding); nullifier + value conservation compose on the same pattern.

Layout: region A (COMMIT, 4 sponge blocks: DOM_CM, value, owner, rho) computes cm; the A→B handoff resets the
sponge for the tree and carries cm in as the leaf; region B (MEMBERSHIP, D levels of hashn([DOM_NODE,left,
right])) folds cm up to the root. A periodic selector `inB` switches the transition rules between the two
regions; the handoff row both resets (like a level end) and seeds the carry from region A's output.
"""
from execnode.stark import field as F, alghash, membership as MB, stark

R = alghash.ROUNDS
S0, S1, AB, CARRY, SIB, DIR = range(6)
RPL = 3 * R                                        # rows per membership level
ACOLS = 4 * R                                      # region A (commit) width: 4 message blocks
MAX_DEGREE = alghash.ALPHA                         # 7


def _next_pow2(x):
    p = 1
    while p < x:
        p <<= 1
    return p


def _round(s0, s1, r):
    t0 = alghash.sbox(F.add(s0, alghash.RC[r % R][0]))
    t1 = alghash.sbox(F.add(s1, alghash.RC[r % R][1]))
    return F.add(F.mul(2, t0), t1), F.add(t0, F.mul(3, t1))


def build_trace(value, owner, rho, siblings, dirs):
    D = len(siblings)
    total = ACOLS + D * RPL
    T = _next_pow2(total + 1)
    msgA = [alghash.DOM_CM, value % F.P, owner % F.P, rho % F.P]     # region-A absorbed messages
    trace = []
    s0, s1, ab = msgA[0], alghash.IV, msgA[0]        # region A start: absorb DOM_CM into [0,IV]
    carry = sib = dr = 0
    lvl = 0
    for r in range(T):
        trace.append([s0, s1, ab, carry, sib, dr])
        r0, r1 = _round(s0, s1, r)
        if r < ACOLS:                                # ---- region A (commit) ----
            blk_end = (r % R == R - 1)
            if blk_end and r == ACOLS - 1:           # A->B handoff: cm ready -> reset for the tree, carry it in
                carry = r0                            # cm = region A output
                sib, dr = siblings[0] % F.P, dirs[0] % F.P
                s0, s1, ab = alghash.DOM_NODE, alghash.IV, alghash.DOM_NODE
            elif blk_end:                            # absorb the next region-A message (value/owner/rho)
                mi = (r // R) + 1
                s0, s1, ab = F.add(r0, msgA[mi]), r1, msgA[mi]
            else:
                s0, s1 = r0, r1
        else:                                        # ---- region B (membership) ----
            pos = (r - ACOLS) % RPL
            block, last = pos // R, (pos % R == R - 1)
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
    return trace, T, D, trace[ACOLS + D * RPL][S0]


def spend_root(value, owner, rho, siblings, dirs):
    cm = alghash.commit(value, owner, rho)
    return cm, MB.merkle_root_from_path(cm, siblings, dirs)


def _periodic(T, D):
    rc0 = [alghash.RC[r % R][0] for r in range(T)]
    rc1 = [alghash.RC[r % R][1] for r in range(T)]
    inB = [1 if r >= ACOLS else 0 for r in range(T)]
    # region-A absorb boundaries (blocks 1..3 -> rows R-1, 2R-1, 3R-1), NOT the handoff row 4R-1
    aB = [1 if (r < ACOLS - 1 and r % R == R - 1) else 0 for r in range(T)]
    hand = [1 if r == ACOLS - 1 else 0 for r in range(T)]                       # A->B handoff
    b0 = [1 if (r >= ACOLS and (r - ACOLS) % RPL == R - 1) else 0 for r in range(T)]
    b1 = [1 if (r >= ACOLS and (r - ACOLS) % RPL == 2 * R - 1) else 0 for r in range(T)]
    lend = [1 if (r >= ACOLS and (r - ACOLS) % RPL == RPL - 1 and 0 <= (r - ACOLS) // RPL < D - 1) else 0 for r in range(T)]
    return [rc0, rc1, inB, aB, hand, b0, b1, lend]


def _transitions():
    RC0, RC1, INB, AB_, HAND, B0, B1, LEND = range(8)
    def rnd(cur, per):
        t0 = F.pw(F.add(cur[S0], per[RC0]), alghash.ALPHA)
        t1 = F.pw(F.add(cur[S1], per[RC1]), alghash.ALPHA)
        return F.add(F.mul(2, t0), t1), F.add(t0, F.mul(3, t1))
    def c_s1(cur, nxt, per):
        _, r1 = rnd(cur, per)
        reset = F.add(per[HAND], per[LEND])                     # s1 -> IV on handoff or level-end reset
        return F.sub(nxt[S1], F.add(F.mul(reset, alghash.IV), F.mul(F.sub(1, reset), r1)))
    def c_s0(cur, nxt, per):
        r0, _ = rnd(cur, per)
        left = F.add(cur[CARRY], F.mul(cur[DIR], F.sub(cur[SIB], cur[CARRY])))
        right = F.add(cur[SIB], F.mul(cur[DIR], F.sub(cur[CARRY], cur[SIB])))
        absorbB = F.add(F.mul(per[B0], left), F.mul(per[B1], right))
        absorbA = F.mul(per[AB_], nxt[AB])                      # region A absorbs the free next message
        reset = F.add(per[HAND], per[LEND])                    # -> DOM_NODE
        normal = F.add(r0, F.add(absorbA, absorbB))
        return F.sub(nxt[S0], F.add(F.mul(reset, alghash.DOM_NODE), F.mul(F.sub(1, reset), normal)))
    def c_carry(cur, nxt, per):                                # carry <- r0 (cm or node hash) on handoff/level-end
        r0, _ = rnd(cur, per)
        setc = F.add(per[HAND], per[LEND])
        return F.add(F.mul(setc, F.sub(nxt[CARRY], r0)), F.mul(F.sub(1, setc), F.sub(nxt[CARRY], cur[CARRY])))
    def c_ab(cur, nxt, per):
        left = F.add(cur[CARRY], F.mul(cur[DIR], F.sub(cur[SIB], cur[CARRY])))
        right = F.add(cur[SIB], F.mul(cur[DIR], F.sub(cur[CARRY], cur[SIB])))
        reset = F.add(per[HAND], per[LEND])
        # priority: reset -> DOM_NODE ; B0 -> left ; B1 -> right ; AB_ -> free(next ab) ; else hold
        setDOM = F.mul(reset, F.sub(nxt[AB], alghash.DOM_NODE))
        setL = F.mul(per[B0], F.sub(nxt[AB], left))
        setR = F.mul(per[B1], F.sub(nxt[AB], right))
        other = F.sub(1, F.add(F.add(reset, per[B0]), F.add(per[B1], per[AB_])))   # hold when nothing sets ab
        hold = F.mul(other, F.sub(nxt[AB], cur[AB]))
        return F.add(F.add(setDOM, setL), F.add(setR, hold))
    def c_dirbit(cur, nxt, per):
        return F.mul(F.mul(per[INB], cur[DIR]), F.sub(1, cur[DIR]))   # dir is a bit in region B
    return [c_s1, c_s0, c_carry, c_ab, c_dirbit]


def prove_spend(value, owner, rho, siblings, dirs, num_queries=40):
    trace, T, D, root = build_trace(value, owner, rho, siblings, dirs)
    periodic = _periodic(T, D)
    bnd = [(0, S1, alghash.IV), (0, S0, alghash.DOM_CM), (0, AB, alghash.DOM_CM),
           (ACOLS + D * RPL, S0, root)]
    proof = stark.prove(trace, _transitions(), bnd, periodic=periodic, max_degree=MAX_DEGREE, num_queries=num_queries)
    proof["D"] = D
    return proof, root


def verify_spend(proof, root, root_is_known):
    if not root_is_known(root):
        return False, "unknown anchor root"
    D, T = proof["D"], proof["T"]
    periodic = _periodic(T, D)
    bnd = [(0, S1, alghash.IV), (0, S0, alghash.DOM_CM), (0, AB, alghash.DOM_CM),
           (ACOLS + D * RPL, S0, root % F.P)]
    return stark.verify(proof, _transitions(), bnd, periodic=periodic, max_degree=MAX_DEGREE)
