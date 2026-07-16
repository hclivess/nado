"""
Merkle-UPDATE AIR (state-root binding, doc/zk-recursion.md §5b piece (a), in-circuit) — the O(1) core.

storage_tree.verify_transition checks a state transition with NATIVE folds (O(touched·depth) verifier work).
This AIR moves ONE such fold IN-CIRCUIT: it proves that changing a single leaf old_val → new_val at ONE shared
position turns pre_root into post_root — i.e. post_root is pre_root with exactly that slot rewritten. Folded
into the settlement recursion (with the touched slots batched + bound to the exec trace's SSTOREs), the whole
state transition becomes a proof the verifier checks in O(1) instead of replaying the epoch.

It is membership.py's leaf→root sponge-fold run as TWO PARALLEL chains — one for old_val, one for new_val —
over the SAME sibling/direction columns, so the path is shared BY CONSTRUCTION (the soundness crux: without a
shared path a prover could relate pre_root and post_root by changing a DIFFERENT slot). alghash (blake2b-free)
so it folds in the recursion layer. old_val/new_val + pre_root/post_root are the public statement; the path is
private witness (its POSITION is bound to the io slot at integration time).
"""
from execnode.stark import field as F, alghash, stark

R = alghash.ROUNDS
# old sponge (s0,s1,ab,carry) | new sponge (s0,s1,ab,carry) | shared (sib, dir)
OS0, OS1, OAB, OCARRY, NS0, NS1, NAB, NCARRY, SIB, DIR = range(10)
RPL = 3 * R                                # rows per level (3 messages: DOM_NODE, left, right)
MAX_DEGREE = alghash.ALPHA                 # 7


def _next_pow2(x):
    p = 1
    while p < x:
        p <<= 1
    return p


def _round(s0, s1, r):
    """One in-clear sponge round (add RC[r] → x^7 → 2×2 MDS), the trace-builder's copy of the AIR step."""
    t0 = alghash.sbox(F.add(s0, alghash.RC[r % R][0]))
    t1 = alghash.sbox(F.add(s1, alghash.RC[r % R][1]))
    return F.add(F.mul(2, t0), t1), F.add(t0, F.mul(3, t1))


def build_trace(old_leaf, new_leaf, siblings, dirs):
    """Two parallel leaf→root folds (old_leaf, new_leaf) sharing (siblings, dirs). Returns
    (trace, T, D, pre_root, post_root): pre_root = old chain's root cell (row D·RPL, OS0), post_root the new's."""
    D = len(siblings)
    T = _next_pow2(D * RPL + 1)
    trace = []
    ocarry, ncarry = old_leaf % F.P, new_leaf % F.P
    sib, dr = siblings[0] % F.P, dirs[0] % F.P
    os0, os1, oab = alghash.DOM_NODE, alghash.IV, alghash.DOM_NODE
    ns0, ns1, nab = alghash.DOM_NODE, alghash.IV, alghash.DOM_NODE
    lvl = 0
    for r in range(T):
        trace.append([os0, os1, oab, ocarry, ns0, ns1, nab, ncarry, sib, dr])
        or0, or1 = _round(os0, os1, r)
        nr0, nr1 = _round(ns0, ns1, r)
        pos = r % RPL
        block, last = pos // R, (pos % R == R - 1)
        if last and block == 0:                                  # absorb left = carry + dir·(sib − carry)
            oleft = F.add(ocarry, F.mul(dr, F.sub(sib, ocarry)))
            nleft = F.add(ncarry, F.mul(dr, F.sub(sib, ncarry)))
            os0, os1, oab = F.add(or0, oleft), or1, oleft
            ns0, ns1, nab = F.add(nr0, nleft), nr1, nleft
        elif last and block == 1:                                # absorb right = sib + dir·(carry − sib)
            oright = F.add(sib, F.mul(dr, F.sub(ocarry, sib)))
            nright = F.add(sib, F.mul(dr, F.sub(ncarry, sib)))
            os0, os1, oab = F.add(or0, oright), or1, oright
            ns0, ns1, nab = F.add(nr0, nright), nr1, nright
        elif last and block == 2:                                # level end: r0 = node hash
            lvl += 1
            if lvl < D:
                ocarry, ncarry = or0, nr0
                sib, dr = siblings[lvl] % F.P, dirs[lvl] % F.P
                os0, os1, oab = alghash.DOM_NODE, alghash.IV, alghash.DOM_NODE
                ns0, ns1, nab = alghash.DOM_NODE, alghash.IV, alghash.DOM_NODE
            else:
                os0, os1 = or0, or1
                ns0, ns1 = nr0, nr1
        else:
            os0, os1 = or0, or1
            ns0, ns1 = nr0, nr1
    return trace, T, D, trace[D * RPL][OS0], trace[D * RPL][NS0]


def _periodic(T, D):
    """Same 5 public periodic selectors as membership (round constants + absorb/level-end boundaries) — shared
    by both sponge chains; the verifier recomputes them from (T, D)."""
    rc0 = [alghash.RC[r % R][0] for r in range(T)]
    rc1 = [alghash.RC[r % R][1] for r in range(T)]
    b0 = [1 if (r % RPL == R - 1) else 0 for r in range(T)]
    b1 = [1 if (r % RPL == 2 * R - 1) else 0 for r in range(T)]
    lend = [1 if (r % RPL == RPL - 1 and 0 <= r // RPL < D - 1) else 0 for r in range(T)]
    return [rc0, rc1, b0, b1, lend]


def _sponge_constraints(s0i, s1i, abi, ci):
    """membership.py's 4 fold constraints for ONE sponge chain at column offsets (s0,s1,ab,carry), reading the
    SHARED sib/dir. Instantiated once for the old chain and once for the new — identical schedule, shared path."""
    def rnd(cur, per):
        t0 = F.pw(F.add(cur[s0i], per[0]), alghash.ALPHA)
        t1 = F.pw(F.add(cur[s1i], per[1]), alghash.ALPHA)
        return F.add(F.mul(2, t0), t1), F.add(t0, F.mul(3, t1))
    def c_s1(cur, nxt, per):
        _, r1 = rnd(cur, per)
        return F.sub(nxt[s1i], F.add(F.mul(per[4], alghash.IV), F.mul(F.sub(1, per[4]), r1)))
    def c_s0(cur, nxt, per):
        r0, _ = rnd(cur, per)
        b0, b1, lend = per[2], per[3], per[4]
        left = F.add(cur[ci], F.mul(cur[DIR], F.sub(cur[SIB], cur[ci])))
        right = F.add(cur[SIB], F.mul(cur[DIR], F.sub(cur[ci], cur[SIB])))
        normal = F.add(r0, F.add(F.mul(b0, left), F.mul(b1, right)))
        return F.sub(nxt[s0i], F.add(F.mul(lend, alghash.DOM_NODE), F.mul(F.sub(1, lend), normal)))
    def c_ab(cur, nxt, per):
        b0, b1, lend = per[2], per[3], per[4]
        left = F.add(cur[ci], F.mul(cur[DIR], F.sub(cur[SIB], cur[ci])))
        right = F.add(cur[SIB], F.mul(cur[DIR], F.sub(cur[ci], cur[SIB])))
        hold = F.sub(nxt[abi], cur[abi])
        setv = lambda v: F.sub(nxt[abi], v)
        sel_other = F.sub(1, F.add(F.add(b0, b1), lend))
        return F.add(F.add(F.mul(lend, setv(alghash.DOM_NODE)), F.mul(b0, setv(left))),
                     F.add(F.mul(b1, setv(right)), F.mul(sel_other, hold)))
    def c_carry(cur, nxt, per):
        r0, _ = rnd(cur, per)
        lend = per[4]
        return F.add(F.mul(lend, F.sub(nxt[ci], r0)), F.mul(F.sub(1, lend), F.sub(nxt[ci], cur[ci])))
    return [c_s1, c_s0, c_ab, c_carry]


def _transitions():
    """Old chain (4) + new chain (4) + shared path binding (dir is a bit; sib/dir held within a level). The
    old and new folds READ THE SAME sib/dir columns, so they authenticate the SAME position — that shared path
    is exactly what makes post_root a single-slot rewrite of pre_root."""
    def c_dirbit(cur, nxt, per):
        return F.mul(cur[DIR], F.sub(1, cur[DIR]))
    def c_sib(cur, nxt, per):
        return F.mul(F.sub(1, per[4]), F.sub(nxt[SIB], cur[SIB]))
    def c_dir(cur, nxt, per):
        return F.mul(F.sub(1, per[4]), F.sub(nxt[DIR], cur[DIR]))
    return (_sponge_constraints(OS0, OS1, OAB, OCARRY)
            + _sponge_constraints(NS0, NS1, NAB, NCARRY)
            + [c_dirbit, c_sib, c_dir])


def _boundaries(old_val, new_val, pre_root, post_root, dirs, D):
    """The public boundaries: the two sponge starts + the pinned leaves + the two roots, PLUS the POSITION —
    the DIR column pinned to each level's key bit at the level-start row. Pinning the position is what binds the
    update to a SPECIFIC slot (without it a prover could prove old→pre_root / new→post_root at ANOTHER position)."""
    bnd = [(0, OS1, alghash.IV), (0, OS0, alghash.DOM_NODE), (0, OAB, alghash.DOM_NODE), (0, OCARRY, old_val % F.P),
           (0, NS1, alghash.IV), (0, NS0, alghash.DOM_NODE), (0, NAB, alghash.DOM_NODE), (0, NCARRY, new_val % F.P),
           (D * RPL, OS0, pre_root % F.P), (D * RPL, NS0, post_root % F.P)]
    for level in range(D):
        bnd.append((level * RPL, DIR, int(dirs[level]) % F.P))       # position: DIR held per level, pinned here
    return bnd


def prove_update(old_val, new_val, siblings, dirs, num_queries=stark.NUM_QUERIES, backend=None):
    """Prove old_val at PUBLIC position `dirs` (private path `siblings`) folds to pre_root AND new_val folds to
    post_root through the SAME path. Public: old_val, new_val, pre_root, post_root, dirs (all pinned as
    boundaries). Returns (proof, pre_root, post_root); proof['D'] is the public depth."""
    trace, T, D, pre_root, post_root = build_trace(old_val, new_val, siblings, dirs)
    bnd = _boundaries(old_val, new_val, pre_root, post_root, dirs, D)
    proof = stark.prove(trace, _transitions(), bnd, periodic=_periodic(T, D), max_degree=MAX_DEGREE,
                        num_queries=num_queries, backend=backend)
    proof["D"] = D
    return proof, pre_root, post_root


def verify_update(proof, old_val, new_val, pre_root, post_root, dirs, num_queries=stark.NUM_QUERIES, backend=None):
    """Verify a Merkle-update proof against the PUBLIC (old_val, new_val, pre_root, post_root, dirs). Geometry is
    fixed by the public depth D; the periodic schedule + boundaries (incl. the position pins) are rebuilt locally.
    A valid proof means: pre_root and post_root are the same tree with the leaf at POSITION `dirs` rewritten
    old_val → new_val. Returns (ok, reason)."""
    try:
        D = proof.get("D")
        if not isinstance(D, int) or D < 1 or proof.get("T") != _next_pow2(D * RPL + 1) or len(dirs) != D:
            return False, "bad depth / trace geometry / dirs length"
        bnd = _boundaries(old_val, new_val, pre_root, post_root, dirs, D)
        return stark.verify(proof, _transitions(), bnd, periodic=_periodic(proof["T"], D),
                            max_degree=MAX_DEGREE, num_queries=num_queries, backend=backend)
    except Exception as e:
        return False, f"malformed proof: {e}"
