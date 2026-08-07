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


def _segment(old_val, new_val, siblings, dirs):
    """The UNPADDED rows for ONE update, plus its roots: (rows, D, pre_root, post_root).

    Split out of build_trace so a batch can concatenate K of these before padding once. build_trace pads to
    next_pow2 immediately, which is exactly what a batch must not do."""
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
    rows = []
    for b in range(nblk):
        # sib/dir carried by THIS block are the ones its boundary absorbs (block b < D folds with sibs[b]);
        # the last block (b == D) carries zeros (no further fold).
        sib = list(sibs[b]) if b < D else [0] * CAP
        d = ds[b] if b < D else 0
        for r in range(BR):
            rows.append(list(o_blocks[b][r]) + list(n_blocks[b][r]) + sib + [d])
    return rows, D, pre_root, post_root


def build_trace(old_val, new_val, siblings, dirs):
    """Two parallel folds (old_val, new_val) sharing (siblings, dirs). Returns (trace, T, D, pre_root, post_root)."""
    rows, D, pre_root, post_root = _segment(old_val, new_val, siblings, dirs)
    T = _next_pow2(len(rows))
    trace = list(rows)
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


# ---------------------------------------------------------------------------------------------------------
# BATCHED AIR: K updates in ONE trace.
#
# WHY. Proof size is LOGARITHMIC in trace length — measured, one update per depth:
#     T=512 6.24 MiB | T=2048 7.91 | T=4096 8.83 | T=8192 9.80 | T=16384 10.82
# i.e. ~1 MiB per doubling, because 88% of a proof is FRI queries and a query costs one Merkle path, which
# grows with log N. So K updates in ONE trace cost ~(10.82 + log2(K)) MiB instead of K x 10.82: eight updates
# are ~13.8 MiB instead of 86.6 MiB.
#
# THIS IS THE ONLY LEVER LEFT. The records half needs one update PER PRESENT MINER (20 and rising — it tracks
# fleet size), so K x 10.82 MiB passed the 191.94 MiB tx budget and keeps rising on its own. The K->1
# recursion bundle would also collapse the bytes, and it is not available: it OOM-killed at 27.5 GB resident
# for K=2. Dropping NUM_QUERIES would work and costs security bits, which is not a prover-side decision.
#
# WHAT CHANGES vs the single-update AIR — ONE constraint gate, nothing else. Transitions are evaluated on
# every row but the last (vanishing (x^T-1)/(x-last)), so the SEAM row — the last row of segment s, whose
# `nxt` is the first row of segment s+1 — is evaluated. There:
#     ACT_R = 0 (the seam is a block's last row, rib == _R)      -> round constraints vanish. Fine.
#     ACT_A = 0 (blk+1 == nblk within the segment)               -> absorb constraints vanish. Fine.
#     dir-is-a-bit reads only `cur`                              -> fine.
#     the sib/dir HOLD constraints are gated on (1 - ACT_A) = 1  -> they would force segment s's path to
#         carry into segment s+1, which has a DIFFERENT path. THAT is the whole defect, and the fix is to
#         gate those five on a periodic HOLD column that is 0 on seam rows.
#
# Kept as a SEPARATE AIR (_transitions_batch / _periodic_batch) rather than re-gating the existing one, so
# single-update proofs already in flight keep verifying bit-identically. No flag day.
HOLD = NPER                                      # periodic index: "sib carries into the next row"
DIRP = NPER + 1                                  # periodic index: the PUBLIC direction bit for this row
NPER_B = NPER + 2


def _periodic_batch(T, D, K, dirs_list):
    """Structural selectors for K segments, plus the PUBLIC position bits.

    Rebuilt by the verifier from PUBLIC data alone — (T, D, K) and the positions, which are part of the
    statement — so nothing here depends on witness values, which is what keeps the batching sound.

    THE POSITION LIVES HERE NOW, NOT IN 256 BOUNDARIES PER SEGMENT. It used to be pinned by one boundary per
    level (`(level*BR, DIR, dirs[level])`), which is 256 of each segment's ~288 boundaries. The composition
    allocates a size-N inverse-denominator vector PER BOUNDARY, so that choice cost ~9x more memory than the
    rest of the AIR put together and is what made K=9 OOM at 35.7 GB while K=2 fit in ~1 GB.

    `dirs` are PUBLIC, so a periodic column is the natural home: the verifier rebuilds it from the same
    statement it is checking, exactly as it rebuilds RC/ACT_R/ACT_A. The binding also gets STRONGER — the
    absorb constraint reads the position on EVERY row it matters on, instead of it being pinned once per
    level and merely carried by a hold constraint in between.
    """
    nblk = D + 1
    seg = nblk * BR                              # rows per update segment
    n_used = K * seg
    if len(dirs_list) != K:
        raise ValueError(f"periodic needs one position per segment: got {len(dirs_list)}, K={K}")
    per = [[0] * T for _ in range(NPER_B)]
    for i in range(T):
        if i >= n_used:
            continue                             # padding: every selector 0, so every constraint vanishes
        s = i // seg                             # which update this row belongs to
        rib = i % BR
        blk = (i % seg) // BR                    # block index WITHIN this segment, not globally
        if rib < _R:
            for lane in range(_W):
                per[RC_lo + lane][i] = A2.RC[rib][lane]
            per[ACT_R][i] = 1
        absorbing = (rib == _R and blk + 1 < nblk)
        if absorbing:
            per[ACT_A][i] = 1
        # The position bit for the level this row is in. The LAST block of a segment (blk == D) folds with
        # nothing, so it carries 0 — matching _segment(), which writes dir 0 there.
        if blk < D:
            per[DIRP][i] = int(dirs_list[s][blk]) & 1
        # HOLD: carry the sibling to the next row. Never on an absorb row (the next row starts a new level
        # and takes the NEXT sibling), never on the last row of a segment (the next row belongs to a
        # different update), and never on the last live row (the next row is padding).
        if not absorbing and (i + 1) < n_used and (i + 1) % seg != 0:
            per[HOLD][i] = 1
    return per


def _absorb_c_dirp(base, i, part):
    """The absorb constraint reading the position from the PUBLIC periodic column instead of the trace.

    Identical to _absorb_c except `d = per[DIRP]` rather than `cur[DIR]`. That single substitution is what
    lets the 256 per-level position boundaries go away: nothing needs the DIR trace column any more, so
    nothing needs to pin it."""
    def c(cur, nxt, per):
        d = per[DIRP]
        if part == "left":
            want = F.add(F.mul(F.sub(1, d), cur[base + i]), F.mul(d, cur[SIB + i]))
            return F.mul(per[ACT_A], F.sub(nxt[base + i], want))
        if part == "right":
            want = F.add(F.mul(F.sub(1, d), cur[SIB + i]), F.mul(d, cur[base + i]))
            return F.mul(per[ACT_A], F.sub(nxt[base + CAP + i], want))
        return F.mul(per[ACT_A], F.sub(nxt[base + _RATE + i], A2.IV[i]))     # cap
    return c


def _transitions_batch():
    """The batch AIR: rounds + absorb (reading the PUBLIC position), and the sibling held within a level.

    TWO DIFFERENCES FROM _transitions(), both consequences of moving the position into a periodic column:
      • absorb reads per[DIRP], not cur[DIR];
      • the "dir is a bit" and "dir held within a level" constraints are GONE. A periodic column is
        rebuilt by the verifier from the public statement, so it is a bit by construction and constant
        across a level by construction — there is nothing left for a constraint to enforce.
    The sibling stays private witness and keeps its HOLD constraints."""
    cons = []
    for base in (OS, NS):
        for i in range(_W):
            cons.append(_round_c(base, i))
        for i in range(CAP):
            cons.append(_absorb_c_dirp(base, i, "left"))
            cons.append(_absorb_c_dirp(base, i, "right"))
            cons.append(_absorb_c_dirp(base, i, "cap"))
    for lane in range(CAP):                                                       # sib held within a level
        cons.append((lambda L: (lambda c, n, p: F.mul(p[HOLD], F.sub(n[SIB + L], c[SIB + L]))))(lane))
    return cons


def build_trace_batch(items):
    """items = [(old_val, new_val, siblings, dirs), ...] -> (trace, T, D, K, roots).

    `roots` is the CHAIN [pre_0, post_0 == pre_1, post_1, ...]: every segment's roots are pinned as public
    boundaries, so the chain is public and a batch proves exactly what K separate proofs proved."""
    if not items:
        raise ValueError("empty batch")
    segs, roots, D = [], None, None
    for (old_val, new_val, sibs, dirs) in items:
        rows, d, pre_root, post_root = _segment(old_val, new_val, sibs, dirs)
        if D is None:
            D = d
            roots = [pre_root]
        elif d != D:
            raise ValueError("a batch must share one tree depth")
        elif roots[-1] != pre_root:
            raise ValueError("internal: batch segment pre_root breaks the chain")
        roots.append(post_root)
        segs.append(rows)
    K = len(items)
    flat = [r for rows in segs for r in rows]
    T = _next_pow2(len(flat))
    if T > stark.MAX_TRACE_ROWS:
        raise ValueError(f"batch of {K} needs T={T} beyond MAX_TRACE_ROWS={stark.MAX_TRACE_ROWS}")
    trace = flat
    while len(trace) < T:
        trace.append(list(trace[-1]))
    return trace, T, D, K, roots


def _boundaries_batch(items, roots, D):
    """Per-segment boundaries, each shifted to its segment's start row: the two leaf inits and the two roots.

    THE POSITION IS NOT HERE ANY MORE — it is the DIRP periodic column, which the verifier rebuilds from the
    same public statement. That drops 256 of each segment's ~288 boundaries, and boundaries are the
    expensive kind of constraint: the composition allocates a size-N inverse-denominator vector for EACH
    one, so at K=9 the position pins alone were ~21.5 GB against ~2.4 GB for everything else. It is also a
    STRONGER binding, checked on every absorb row rather than pinned once per level.

    What remains still leaves nothing about update k to the prover's choice: both values, both roots, and
    the position (via DIRP) are all public and all enforced."""
    seg = (D + 1) * BR
    bnd = []
    for s, (old_val, new_val, _sibs, dirs) in enumerate(items):
        off = s * seg
        for (row, col, val) in _boundaries(old_val, new_val, roots[s], roots[s + 1], dirs, D):
            if col == DIR:
                continue                 # position now lives in the DIRP periodic column
            bnd.append((off + row, col, val))
    return bnd


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


def prove_update(old_val, new_val, siblings, dirs, num_queries=stark.NUM_QUERIES, backend=None,
                 row_commit=None):
    """Prove old_val at PUBLIC position `dirs` (private path `siblings`) folds to pre_root AND new_val folds to
    post_root through the SAME path. Returns (proof, pre_root, post_root) (roots are CAPACITY-tuples);
    proof['D'] is the public depth.

    ROW-COMMITTED whenever the backend allows it. This call used to leave stark.prove's row_commit at its
    False default, and that ONE unset flag is what made records-bearing spans unprovable. Timing every arena
    entry point across a real update (D=256 → T=16384, W=29, N=131072):

        commit_col   29 calls   146.5 s   79.6% of the prove      lde_column  43 calls    5.3 s
        compose_ext   1 call     15.6 s    8.5%                   open_at  18560 calls    1.2 s
        fri_prove     1 call     14.7 s    8.0%                   PYTHON               0.5 s   0.3%

    Column mode builds W=29 SEPARATE Merkle trees over N=131072 leaves — ~2N alghash2 permutations each,
    7.6M per update. Row mode commits ONE tree whose leaves are whole rows: ~655k. Measured end to end,
    145.7 s → 35.3 s to prove, 45.7 s → 30.9 s to verify, and the proof shrinks 38.7 MiB → 11.4 MiB, which
    matters independently because the settle tx carries it.

    The KV settle half was ALREADY row-committed: settlement_sparse.py derives row_commit from the backend
    and proves a whole span in ~15 s. The records half ran the same arena, the same backend, and the same
    AIR an order of magnitude slower purely because the default was set in one file and not the other — so
    every live span logged `records half DECLINED … 18 updates exceeds SETTLE_RECORDS_MAX_UPDATES=6`.

    row_commit REQUIRES the RECURSION backend (stark.py:377), so derive it the same way settlement_sparse
    does rather than defaulting it True and breaking the ALGHASH2 callers."""
    b = backend or B.RECURSION
    if row_commit is None:
        row_commit = stark.row_commit_default(b)
    trace, T, D, pre_root, post_root = build_trace(old_val, new_val, siblings, dirs)
    bnd = _boundaries(old_val, new_val, pre_root, post_root, dirs, D)
    proof = stark.prove(trace, _transitions(), bnd, periodic=_periodic(T, D), max_degree=MAX_DEGREE,
                        num_queries=num_queries, backend=b, row_commit=row_commit)
    proof["D"] = D
    return proof, pre_root, post_root


def max_batch(D):
    """How many updates share one trace at depth D, from MAX_TRACE_ROWS alone. At D=256 that is 9
    (9 x 257 x 55 = 127215 rows, padding to 131072; ten would need 262144)."""
    seg = (D + 1) * BR
    k = 1
    while _next_pow2((k + 1) * seg) <= stark.MAX_TRACE_ROWS:
        k += 1
    return k


def prove_updates(items, num_queries=stark.NUM_QUERIES, backend=None, row_commit=None):
    """Prove K updates in ONE STARK. items = [(old_val, new_val, siblings, dirs), ...], applied IN ORDER, each
    starting from the previous one's post_root. Returns (proof, roots) where roots is the public chain
    [pre_0, ..., post_{K-1}]. proof['D'] and proof['K'] are public geometry."""
    b = backend or B.RECURSION
    if row_commit is None:
        row_commit = stark.row_commit_default(b)
    trace, T, D, K, roots = build_trace_batch(items)
    bnd = _boundaries_batch(items, roots, D)
    _dirs_list = [d for (_o, _n, _s, d) in items]
    proof = stark.prove(trace, _transitions_batch(), bnd, periodic=_periodic_batch(T, D, K, _dirs_list),
                        max_degree=MAX_DEGREE, num_queries=num_queries, backend=b, row_commit=row_commit)
    proof["D"] = D
    proof["K"] = K
    return proof, roots


def verify_updates(proof, items_public, roots, num_queries=stark.NUM_QUERIES, backend=None):
    """Verify a batched proof against the PUBLIC (per-update old/new values and positions, plus the root
    chain). items_public = [(old_val, new_val, dirs), ...] — NO siblings: the path stays private witness.
    Returns (ok, reason)."""
    try:
        b = backend or B.RECURSION
        D, K = proof.get("D"), proof.get("K")
        if not isinstance(D, int) or not isinstance(K, int) or D < 1 or K < 1:
            return False, "bad batch geometry"
        if len(items_public) != K or len(roots) != K + 1:
            return False, f"public statement covers {len(items_public)} updates but the proof declares K={K}"
        seg = (D + 1) * BR
        if proof.get("T") != _next_pow2(K * seg):
            return False, "trace length does not match the declared (D, K)"
        if any(len(dirs) != D for (_o, _n, dirs) in items_public):
            return False, "a position length does not match the declared depth"
        # Rebuild the boundaries from the PUBLIC statement only. _boundaries_batch takes the same tuples the
        # prover used, minus the siblings it never reads — passing None makes that structural rather than
        # a convention someone can quietly break.
        items = [(o, n, None, dirs) for (o, n, dirs) in items_public]
        bnd = _boundaries_batch(items, roots, D)
        return stark.verify(proof, _transitions_batch(), bnd,
                            periodic=_periodic_batch(proof["T"], D, K, [d for (_o, _n, d) in items_public]),
                            max_degree=MAX_DEGREE, num_queries=num_queries, backend=b,
                            row_commit=("row_roots" in proof))
    except Exception as e:
        import traceback as _tb
        _f = _tb.extract_tb(e.__traceback__)[-1]
        return False, (f"malformed batch proof: {type(e).__name__}: {e} "
                       f"[{_f.filename.rsplit('/', 1)[-1]}:{_f.lineno} in {_f.name}: {_f.line}]")


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
        # READ the commitment mode off the proof — the verifier is never TOLD it. This is the same detection
        # settlement_sparse.py already does (`row_commit = "row_roots" in bundle["proof"]`), and it is what
        # lets column-mode proofs (ALGHASH2, and anything already in flight) keep verifying unchanged while
        # RECURSION proofs move to row mode. It is not a security choice the prover gets to make: both modes
        # commit the same LDE under the same transcript, and every public input is still checked below.
        return stark.verify(proof, _transitions(), bnd, periodic=_periodic(proof["T"], D),
                            max_degree=MAX_DEGREE, num_queries=num_queries, backend=b,
                            row_commit=("row_roots" in proof))
    except Exception as e:
        # SAY WHERE. This returned only the exception's text, which for a TypeError deep in the verifier
        # ("int() argument must be ... not 'list'") names neither the file, the line, nor the value — and a
        # settle proof is ~118 MiB of nested structure, so "somewhere in there" is not a starting point.
        # Observed live 2026-08-04: the first settle proof ever to REACH verification (every earlier one was
        # refused for size before the verifier ran) failed with exactly that text and nothing else.
        import traceback as _tb
        _f = _tb.extract_tb(e.__traceback__)[-1]
        return False, (f"malformed proof: {type(e).__name__}: {e} "
                       f"[{_f.filename.rsplit('/', 1)[-1]}:{_f.lineno} in {_f.name}: {_f.line}]")
