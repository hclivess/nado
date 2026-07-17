"""
Merkle-UPDATE AIR (state-root binding, doc/zk-recursion.md §5b piece (a), in-circuit) — the O(1) core, ALGHASH2.

Proves that rewriting ONE leaf old_val → new_val at a shared position turns pre_root into post_root — i.e.
post_root is pre_root with exactly that slot rewritten. Over ALGHASH2 (wide sponge, ~128-bit) so the settled
state root it advances is forgery-resistant (the earlier width-2 alghash root was ~32-bit). It is the recursion
membership fold (recursion.py) run as TWO PARALLEL chains — one for old_val, one for new_val — over the SAME
sibling/direction columns, so the path is shared BY CONSTRUCTION (the soundness crux: without a shared path a
prover could relate pre_root and post_root by changing a DIFFERENT slot). One alghash2 permutation per tree level
(RATE 8 = both child digests fill the rate). old_val/new_val + pre_root/post_root + the POSITION (dirs) are the
public statement; the path (siblings) is private witness in the trace.
"""
from execnode.stark import field as F, alghash2 as A2, stark, backend as B
from execnode.stark.recursion import _permute_snapshots, _next_pow2, _W, _R, _RATE

CAP = A2.CAPACITY                                # digest width (4)
OS = 0                                           # old alghash2 state: lanes 0.._W-1
NS = _W                                          # new alghash2 state: lanes _W..2_W-1
SIB = 2 * _W                                     # shared sibling digest (CAP lanes)
DIR = SIB + CAP                                  # shared direction bit
W = DIR + 1                                      # 2·12 + 4 + 1 = 29 columns
BR = _R + 1                                      # rows per permutation block (level)
MAX_DEGREE = A2.ALPHA                            # 7

# periodic: RC(_W) | ACT_R (round active) | ACT_A (absorb/level-boundary active) — all STRUCTURAL (from T, D)
RC_lo = 0
ACT_R = _W
ACT_A = _W + 1
NPER = _W + 2


def _leaf_init(val):
    return [A2.DOM_LEAF, int(val) % F.P, 0, 0, 0, 0, 0, 0] + list(A2.IV)


def _ordered(cur_digest, sib, d):
    """Row-0 of a fold block: RATE lanes = ordered(child, sib) by dir, then CAP capacity IV lanes."""
    left = sib if d else cur_digest
    right = cur_digest if d else sib
    return [int(x) % F.P for x in left] + [int(x) % F.P for x in right] + list(A2.IV)


def build_trace(old_val, new_val, siblings, dirs):
    """Two parallel folds (old_val, new_val) sharing (siblings, dirs). Returns (trace, T, D, pre_root, post_root)."""
    D = len(siblings)
    o_blocks = [_permute_snapshots(_leaf_init(old_val))]
    n_blocks = [_permute_snapshots(_leaf_init(new_val))]
    oc = tuple(o_blocks[0][_R][:CAP]); nc = tuple(n_blocks[0][_R][:CAP])
    sibs, ds = [], []
    for lvl in range(D):
        sib = tuple(int(x) % F.P for x in siblings[lvl]); d = int(dirs[lvl]) & 1
        o_blocks.append(_permute_snapshots(_ordered(oc, sib, d))); oc = tuple(o_blocks[-1][_R][:CAP])
        n_blocks.append(_permute_snapshots(_ordered(nc, sib, d))); nc = tuple(n_blocks[-1][_R][:CAP])
        sibs.append(sib); ds.append(d)
    pre_root, post_root = oc, nc
    nblk = D + 1
    n_used = nblk * BR
    T = _next_pow2(n_used)
    trace = []
    for b in range(nblk):
        # sib/dir carried by THIS block are the ones its boundary absorbs (block b < D folds with sibs[b]);
        # the last block (b == D) carries zeros (no further fold).
        sib = list(sibs[b]) if b < D else [0] * CAP
        d = ds[b] if b < D else 0
        for r in range(BR):
            trace.append(list(o_blocks[b][r]) + list(n_blocks[b][r]) + sib + [d])
    while len(trace) < T:
        trace.append(list(trace[-1]))
    return trace, T, D, pre_root, post_root


def _periodic(T, D):
    """Structural selectors: RC[row%R] on round rows; ACT_R active on round rows; ACT_A active on each block's
    LAST row that feeds a next block (the absorb/level boundary). Rebuilt by the verifier from (T, D)."""
    nblk = D + 1
    n_used = nblk * BR
    per = [[0] * T for _ in range(NPER)]
    for i in range(T):
        blk, rib = i // BR, i % BR
        if i < n_used and rib < _R:
            for lane in range(_W):
                per[RC_lo + lane][i] = A2.RC[rib][lane]
            per[ACT_R][i] = 1
        if i < n_used and rib == _R and blk + 1 < nblk:
            per[ACT_A][i] = 1
    return per


def _round_c(base, i):
    def c(cur, nxt, per):
        t = [F.pw(F.add(cur[base + j], per[RC_lo + j]), A2.ALPHA) for j in range(_W)]
        mixed = 0
        for j in range(_W):
            mixed = F.add(mixed, F.mul(A2._MDS[i][j], t[j]))
        return F.mul(per[ACT_R], F.sub(nxt[base + i], mixed))
    return c


def _absorb_c(base, i, part):
    """On a boundary row (ACT_A): next block's row 0 = ordered(this digest, sib) by dir + IV. `part` ∈
    {'left','right','cap'} sets the RATE-lo / RATE-hi / capacity lanes."""
    def c(cur, nxt, per):
        d = cur[DIR]
        if part == "left":
            want = F.add(F.mul(F.sub(1, d), cur[base + i]), F.mul(d, cur[SIB + i]))
            return F.mul(per[ACT_A], F.sub(nxt[base + i], want))
        if part == "right":
            want = F.add(F.mul(F.sub(1, d), cur[SIB + i]), F.mul(d, cur[base + i]))
            return F.mul(per[ACT_A], F.sub(nxt[base + CAP + i], want))
        return F.mul(per[ACT_A], F.sub(nxt[base + _RATE + i], A2.IV[i]))     # cap
    return c


def _transitions():
    """Old chain rounds+absorb + new chain rounds+absorb (SHARED sib/dir columns) + path binding (dir a bit;
    sib/dir held within a level). The old & new folds READ THE SAME sib/dir ⇒ same position ⇒ post_root is a
    single-slot rewrite of pre_root."""
    cons = []
    for base in (OS, NS):
        for i in range(_W):
            cons.append(_round_c(base, i))
        for i in range(CAP):
            cons.append(_absorb_c(base, i, "left"))
            cons.append(_absorb_c(base, i, "right"))
            cons.append(_absorb_c(base, i, "cap"))
    cons.append(lambda c, n, p: F.mul(c[DIR], F.sub(1, c[DIR])))                       # dir is a bit
    cons.append(lambda c, n, p: F.mul(F.sub(1, p[ACT_A]), F.sub(n[SIB], c[SIB])))      # sib held within a level
    cons.append(lambda c, n, p: F.mul(F.sub(1, p[ACT_A]), F.sub(n[SIB + 1], c[SIB + 1])))
    cons.append(lambda c, n, p: F.mul(F.sub(1, p[ACT_A]), F.sub(n[SIB + 2], c[SIB + 2])))
    cons.append(lambda c, n, p: F.mul(F.sub(1, p[ACT_A]), F.sub(n[SIB + 3], c[SIB + 3])))
    cons.append(lambda c, n, p: F.mul(F.sub(1, p[ACT_A]), F.sub(n[DIR], c[DIR])))      # dir held within a level
    return cons


def _boundaries(old_val, new_val, pre_root, post_root, dirs, D):
    """Public boundaries: the two leaf inits (row 0), the two roots (final digest row), and the POSITION — DIR
    pinned to each level's key bit at that level-block's start row. Pinning the position binds the update to a
    SPECIFIC slot (without it a prover could prove old→pre_root / new→post_root at ANOTHER position)."""
    nblk = D + 1
    final_row = (nblk - 1) * BR + _R
    bnd = [(0, OS + 0, A2.DOM_LEAF), (0, OS + 1, int(old_val) % F.P),
           (0, NS + 0, A2.DOM_LEAF), (0, NS + 1, int(new_val) % F.P)]
    for lane in range(2, _RATE):
        bnd.append((0, OS + lane, 0)); bnd.append((0, NS + lane, 0))
    for lane in range(CAP):
        bnd.append((0, OS + _RATE + lane, A2.IV[lane])); bnd.append((0, NS + _RATE + lane, A2.IV[lane]))
    for lane in range(CAP):
        bnd.append((final_row, OS + lane, int(pre_root[lane]) % F.P))
        bnd.append((final_row, NS + lane, int(post_root[lane]) % F.P))
    for level in range(D):
        bnd.append((level * BR, DIR, int(dirs[level]) & 1))          # position: DIR held per level, pinned here
    return bnd


def prove_update(old_val, new_val, siblings, dirs, num_queries=stark.NUM_QUERIES, backend=None):
    """Prove old_val at PUBLIC position `dirs` (private path `siblings`) folds to pre_root AND new_val folds to
    post_root through the SAME path. Returns (proof, pre_root, post_root) (roots are CAPACITY-tuples);
    proof['D'] is the public depth."""
    b = backend or B.RECURSION
    trace, T, D, pre_root, post_root = build_trace(old_val, new_val, siblings, dirs)
    bnd = _boundaries(old_val, new_val, pre_root, post_root, dirs, D)
    proof = stark.prove(trace, _transitions(), bnd, periodic=_periodic(T, D), max_degree=MAX_DEGREE,
                        num_queries=num_queries, backend=b)
    proof["D"] = D
    return proof, pre_root, post_root


def verify_update(proof, old_val, new_val, pre_root, post_root, dirs, num_queries=stark.NUM_QUERIES, backend=None):
    """Verify against the PUBLIC (old_val, new_val, pre_root, post_root, dirs) — roots are CAPACITY-tuples. A
    valid proof means pre_root and post_root are the same tree with the leaf at POSITION `dirs` rewritten
    old_val → new_val. Returns (ok, reason)."""
    try:
        b = backend or B.RECURSION
        D = proof.get("D")
        if not isinstance(D, int) or D < 1 or proof.get("T") != _next_pow2((D + 1) * BR) or len(dirs) != D:
            return False, "bad depth / trace geometry / dirs length"
        bnd = _boundaries(old_val, new_val, pre_root, post_root, dirs, D)
        return stark.verify(proof, _transitions(), bnd, periodic=_periodic(proof["T"], D),
                            max_degree=MAX_DEGREE, num_queries=num_queries, backend=b)
    except Exception as e:
        return False, f"malformed proof: {e}"
