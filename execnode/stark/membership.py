"""
Merkle-membership AIR (doc/privacy.md) — prove, in zero-knowledge, that a PRIVATE note commitment (leaf) sits
in the pool's tree at the PUBLIC root, via a PRIVATE authentication path. This is the sound sub-statement the
transparent verifier does with a visible path; here the leaf, the siblings, and the left/right directions all
stay secret, so a spend reveals nothing about WHICH note it is.

The path is a chain of 2-to-1 compressions node' = hashn([DOM_NODE, left, right]) where (left,right) is
(node,sibling) or (sibling,node) per a secret direction bit. Each compression is the sponge gadget; between
levels the sponge RESETS and the previous output is carried in via a `carry` column. Columns:
  s0,s1  sponge state · ab  absorbed message · carry  incoming node (const within a level) · sib,dir  the
  level's sibling + direction bit (const within a level).
Periodic public columns rc0/rc1 (round constants), b (absorb boundary inside a level), lend (level-end reset).
"""
from execnode.stark import field as F, alghash, stark

R = alghash.ROUNDS
S0, S1, AB, CARRY, SIB, DIR = range(6)
RPL = 3 * R                                # rows per level (3 messages: DOM_NODE, left, right)
MAX_DEGREE = alghash.ALPHA                 # 7


def _next_pow2(x):
    p = 1
    while p < x:
        p <<= 1
    return p


def merkle_root_from_path(leaf, siblings, dirs):
    """Direct (in-clear) computation the AIR must reproduce."""
    node = leaf % F.P
    for sib, d in zip(siblings, dirs):
        left, right = (node, sib % F.P) if d == 0 else (sib % F.P, node)
        node = alghash.merkle_node(left, right)
    return node


def _round(s0, s1, r):
    t0 = alghash.sbox(F.add(s0, alghash.RC[r % R][0]))
    t1 = alghash.sbox(F.add(s1, alghash.RC[r % R][1]))
    return F.add(F.mul(2, t0), t1), F.add(t0, F.mul(3, t1))


def build_trace(leaf, siblings, dirs):
    D = len(siblings)
    T = _next_pow2(D * RPL + 1)
    trace = []
    carry = leaf % F.P
    sib = siblings[0] % F.P
    dr = dirs[0] % F.P
    s0, s1, ab = alghash.DOM_NODE, alghash.IV, alghash.DOM_NODE      # level 0: [DOM_NODE, IV]
    lvl = 0
    for r in range(T):
        trace.append([s0, s1, ab, carry, sib, dr])
        r0, r1 = _round(s0, s1, r)
        pos = r % RPL
        block, last = pos // R, (pos % R == R - 1)
        if last and block == 0:                                      # absorb left = carry + dir·(sib-carry)
            left = F.add(carry, F.mul(dr, F.sub(sib, carry)))
            s0, s1, ab = F.add(r0, left), r1, left
        elif last and block == 1:                                    # absorb right = sib + dir·(carry-sib)
            right = F.add(sib, F.mul(dr, F.sub(carry, sib)))
            s0, s1, ab = F.add(r0, right), r1, right
        elif last and block == 2:                                    # level end: r0 = node hash
            lvl += 1
            if lvl < D:                                              # reset the sponge, carry the output in
                carry, sib, dr = r0, siblings[lvl] % F.P, dirs[lvl] % F.P
                s0, s1, ab = alghash.DOM_NODE, alghash.IV, alghash.DOM_NODE
            else:
                s0, s1 = r0, r1                                      # final: s0 holds the root
        else:
            s0, s1 = r0, r1
    return trace, T, D, trace[D * RPL][S0]


def _periodic(T, D):
    rc0 = [alghash.RC[r % R][0] for r in range(T)]
    rc1 = [alghash.RC[r % R][1] for r in range(T)]
    b0 = [1 if (r % RPL == R - 1) else 0 for r in range(T)]          # absorb-left boundary (block 0 end)
    b1 = [1 if (r % RPL == 2 * R - 1) else 0 for r in range(T)]      # absorb-right boundary (block 1 end)
    lend = [1 if (r % RPL == RPL - 1 and 0 <= r // RPL < D - 1) else 0 for r in range(T)]  # level end w/ next
    return [rc0, rc1, b0, b1, lend]


def _transitions():
    def rnd(cur, per):
        t0 = F.pw(F.add(cur[S0], per[0]), alghash.ALPHA)
        t1 = F.pw(F.add(cur[S1], per[1]), alghash.ALPHA)
        return F.add(F.mul(2, t0), t1), F.add(t0, F.mul(3, t1))
    RC = per_idx = None
    def c_s1(cur, nxt, per):                                          # s1 always follows the round unless a reset
        _, r1 = rnd(cur, per)
        # on a level-end reset, s1 -> IV; else s1 -> r1
        return F.sub(nxt[S1], F.add(F.mul(per[4], alghash.IV), F.mul(F.sub(1, per[4]), r1)))
    def c_s0(cur, nxt, per):
        r0, _ = rnd(cur, per)
        b0, b1, lend = per[2], per[3], per[4]
        left = F.add(cur[CARRY], F.mul(cur[DIR], F.sub(cur[SIB], cur[CARRY])))
        right = F.add(cur[SIB], F.mul(cur[DIR], F.sub(cur[CARRY], cur[SIB])))
        # next s0 = r0 + (absorbed message), except on a level end where it RESETS to DOM_NODE
        absorbed = F.add(F.mul(b0, left), F.mul(b1, right))
        normal = F.add(r0, absorbed)
        return F.sub(nxt[S0], F.add(F.mul(lend, alghash.DOM_NODE), F.mul(F.sub(1, lend), normal)))
    def c_ab(cur, nxt, per):                                          # ab: DOM_NODE on reset, left/right on absorb, else held
        b0, b1, lend = per[2], per[3], per[4]
        left = F.add(cur[CARRY], F.mul(cur[DIR], F.sub(cur[SIB], cur[CARRY])))
        right = F.add(cur[SIB], F.mul(cur[DIR], F.sub(cur[CARRY], cur[SIB])))
        hold = F.sub(nxt[AB], cur[AB])
        setv = lambda v: F.sub(nxt[AB], v)
        # priority: lend -> DOM_NODE ; b0 -> left ; b1 -> right ; else hold
        sel_other = F.sub(1, F.add(F.add(b0, b1), lend))
        return F.add(F.add(F.mul(lend, setv(alghash.DOM_NODE)), F.mul(b0, setv(left))),
                     F.add(F.mul(b1, setv(right)), F.mul(sel_other, hold)))
    def c_carry(cur, nxt, per):                                       # carry: -> r0 (the node hash) on level end, else held
        r0, _ = rnd(cur, per)
        lend = per[4]
        return F.add(F.mul(lend, F.sub(nxt[CARRY], r0)), F.mul(F.sub(1, lend), F.sub(nxt[CARRY], cur[CARRY])))
    def c_dirbit(cur, nxt, per):                                      # dir must be a bit: dir*(1-dir)=0
        return F.mul(cur[DIR], F.sub(1, cur[DIR]))
    # SOUNDNESS: sib/dir must be HELD constant within a level (load only at a level-end), else a prover could
    # feed inconsistent siblings for left vs right and fold a non-member leaf to any root.
    def c_sib(cur, nxt, per): return F.mul(F.sub(1, per[4]), F.sub(nxt[SIB], cur[SIB]))   # per[4] = lend
    def c_dir(cur, nxt, per): return F.mul(F.sub(1, per[4]), F.sub(nxt[DIR], cur[DIR]))
    return [c_s1, c_s0, c_ab, c_carry, c_dirbit, c_sib, c_dir]


def prove_membership(leaf, siblings, dirs, num_queries=stark.NUM_QUERIES):
    trace, T, D, root = build_trace(leaf, siblings, dirs)
    periodic = _periodic(T, D)
    bnd = [(0, S1, alghash.IV), (0, S0, alghash.DOM_NODE), (0, AB, alghash.DOM_NODE), (D * RPL, S0, root)]
    proof = stark.prove(trace, _transitions(), bnd, periodic=periodic, max_degree=MAX_DEGREE, num_queries=num_queries)
    proof["D"] = D
    return proof, root


def verify_membership(proof, root, root_is_known):
    if not root_is_known(root):
        return False, "unknown anchor root"
    D, T = proof["D"], proof["T"]
    # H1: pin the trace length to the exact value implied by D so proof geometry can't be manipulated to
    # skip constraints (mirrors the join-split verifiers).
    if not isinstance(D, int) or not isinstance(T, int) or D < 1 or T != _next_pow2(D * RPL + 1):
        return False, "bad trace geometry"
    periodic = _periodic(T, D)
    bnd = [(0, S1, alghash.IV), (0, S0, alghash.DOM_NODE), (0, AB, alghash.DOM_NODE), (D * RPL, S0, root % F.P)]
    return stark.verify(proof, _transitions(), bnd, periodic=periodic, max_degree=MAX_DEGREE)
