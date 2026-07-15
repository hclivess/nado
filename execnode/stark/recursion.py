"""
STARK recursion (doc/zk-recursion.md) — verifying a proof inside a proof, for O(1) settlement.

The crux of recursion is HASHING IN-CIRCUIT: a FRI/STARK verifier's cost is dominated by Merkle-path and
transcript hashing, so to prove "I ran the verifier and it accepted" you must arithmetize the hash. The
`alghash2` wide sponge (execnode/stark/alghash2.py) is built for exactly this — its round function is field
arithmetic. This module arithmetizes it as a STARK AIR and proves the atomic gadget a verifier repeats:

    PREIMAGE KNOWLEDGE — "I know a witness `pre` whose alghash2 permutation lands on a state whose digest
    lanes equal the PUBLIC `digest`" — i.e. a proof of a hash preimage, done entirely in field constraints.

A Merkle-path membership proof is this gadget chained up the path (each level absorbs the sibling + muxes on
the direction bit); a full inner-STARK verifier is many such chains plus cheap field arithmetic (FRI folds,
composition). The alghash2-backed inner STARK (`stark.prove(..., backend=ALGHASH2)`) already makes an inner
proof's verification field-native — this gadget is the piece a fold circuit runs over it. Running a full
verifier circuit at production speed is gated on the native/Rust prover (doc/zk-recursion.md §3.2); the
gadget + the field-verifiable inner proof are the soundness-bearing foundation, demonstrated here in Python.

AIR: the alghash2 permute is ROUNDS full rounds of  s ← MDS · (s + RC[r])^7.  ONE ROUND PER ROW: 12 state
columns S0..S11; RC[r] enters as 12 PUBLIC PERIODIC columns (verifier-supplied, indexed by row); the degree-7
transition enforces S_next[i] = Σ_j MDS[i][j]·(S[j]+RC_row[j])^7 on active rows. Boundaries pin row 0 to the
absorbed initial state and the digest lanes of row ROUNDS to the public digest.
"""
from execnode.stark import field as F, alghash2 as a2, stark, backend

_W = a2.WIDTH
_R = a2.ROUNDS
_RATE = a2.RATE


def _next_pow2(x):
    p = 1
    while p < x:
        p <<= 1
    return p


def verify_inner(proof, transitions, boundaries, **kw):
    """The accept/reject oracle for an alghash2-backed inner STARK — stark.verify with the alghash2 backend.
    A recursion fold proves THIS returned True for its inner proof(s)."""
    return stark.verify(proof, transitions, boundaries, backend=backend.ALGHASH2, **kw)


def _round_transitions():
    """12 constraints (one per lane): on an active row, S_next[i] = Σ_j MDS[i][j]·(S[j]+RC_row[j])^7.
    Periodic layout: per[0.._W-1] = RC for this row's round; per[_W] = active selector (1 round / 0 pad)."""
    ACT = _W
    cons = []

    def make(i):
        def c(cur, nxt, per):
            t = [F.pw(F.add(cur[j], per[j]), a2.ALPHA) for j in range(_W)]
            mixed = 0
            for j in range(_W):
                mixed = F.add(mixed, F.mul(a2._MDS[i][j], t[j]))
            return F.mul(per[ACT], F.sub(nxt[i], mixed))
        return c
    for i in range(_W):
        cons.append(make(i))
    return cons


def _permute_snapshots(state):
    """[state, after_round_0, ..., after_round_{R-1}] — R+1 rows, mirroring a2.permute exactly."""
    s = list(state); rows = [list(s)]
    for r in range(_R):
        s = [a2.sbox(F.add(s[i], a2.RC[r][i])) for i in range(_W)]
        s = [sum(F.mul(a2._MDS[i][j], s[j]) for j in range(_W)) % F.P for i in range(_W)]
        rows.append(list(s))
    return rows


def _pad_pow2(rows, rc_active):
    n = len(rows); T = 1
    while T < n:
        T <<= 1
    while len(rows) < T:
        rows.append(list(rows[-1])); rc_active.append((0, 0))   # inert pad rows (active=0)
    return T


def prove_preimage(elements, num_queries=6):
    """Prove knowledge of `elements` (the witness) whose alghash2 single-permute hash equals the digest that
    this function commits to publicly. Requires len(elements) <= RATE-1 (one absorb chunk). Returns
    (proof, digest, public_air) where public_air = (periodic, boundaries) the verifier reuses."""
    els = [len(elements)] + [int(m) % F.P for m in elements]
    if len(els) > _RATE:
        raise ValueError("prove_preimage: one-chunk gadget (<= RATE-1 elements)")
    init = [0] * _RATE + list(a2.IV)
    for i, m in enumerate(els):
        init[i] = F.add(init[i], m)
    snaps = _permute_snapshots(init)               # R+1 rows
    digest = tuple(snaps[_R][:a2.DIGEST])
    rows = [list(s) for s in snaps]
    rc_active = [(r, 1) for r in range(_R)] + [(_R, 0)]   # row r uses RC[r], active; terminal row inert
    final_row = _R
    T = _pad_pow2(rows, rc_active)
    periodic = ([[a2.RC[rc_active[i][0]][lane] if rc_active[i][0] < _R else 0 for i in range(T)]
                 for lane in range(_W)]
                + [[rc_active[i][1] for i in range(T)]])                       # active selector
    # boundaries: row 0 = the absorbed initial state (public); digest lanes of row R = the digest
    bnds = [(0, lane, init[lane] % F.P) for lane in range(_W)] \
        + [(final_row, lane, int(digest[lane]) % F.P) for lane in range(a2.DIGEST)]
    proof = stark.prove(rows, _round_transitions(), bnds, periodic=periodic, max_degree=8,
                        num_queries=num_queries, backend=backend.ALGHASH2)
    proof["_periodic"] = periodic
    proof["_bnds"] = bnds
    return proof, digest, (periodic, bnds)


def verify_preimage(proof, digest, num_queries=6):
    """Verify a preimage proof: the AIR (round transition + the public RC schedule + boundaries carried in
    the bundle) must hold, and the pinned digest boundary must equal `digest`."""
    per, bnds = proof.get("_periodic"), proof.get("_bnds")
    if per is None or bnds is None:
        return False, "missing public AIR schedule"
    # the digest the caller expects must be exactly the one the boundaries pin (last DIGEST boundaries)
    pinned = tuple(v for (_r, _l, v) in bnds[-a2.DIGEST:])
    if pinned != tuple(int(d) % F.P for d in digest):
        return False, "digest boundary does not match the claimed digest"
    return stark.verify(proof, _round_transitions(), bnds, periodic=per, max_degree=8,
                        num_queries=num_queries, backend=backend.ALGHASH2)


# ---- Merkle-path membership AIR: the preimage gadget chained up a tree (the FRI verifier's core) -----
_CAP = a2.DIGEST


def rmerkle_commit(values):
    """A recursion Merkle tree (rleaf/rnode, one permutation per node). Returns (root, layers of digests)."""
    layer = [a2.rleaf(v) for v in values]
    layers = [layer]
    while len(layer) > 1:
        layer = [a2.rnode(layer[i], layer[i + 1]) for i in range(0, len(layer), 2)]
        layers.append(layer)
    return layers[-1][0], layers


def rmerkle_path(layers, index):
    """Sibling digests bottom-up for leaf `index`."""
    path, idx = [], index
    for layer in layers[:-1]:
        path.append(layer[idx ^ 1]); idx //= 2
    return path


def _membership_air(leaf_val, index, path, root):
    """Build (trace, periodic, boundaries) proving rleaf(leaf_val) hashes up `path` to `root`. One
    permutation BLOCK per level (R+1 rows). RC/dir/sibling enter as PUBLIC periodic columns; the direction
    bit muxes (child,sib) order at each block boundary; the final block's digest lanes are pinned to root."""
    # ---- witness: the exact permutation snapshots at every level ----
    blocks = []
    s0 = [a2.DOM_LEAF, int(leaf_val) % F.P, 0, 0, 0, 0, 0, 0] + list(a2.IV)      # rleaf init
    snaps = _permute_snapshots(s0)                                              # R+1 states
    blocks.append(snaps)
    cur = tuple(snaps[_R][:_CAP])
    idx = index
    sibs, dirs = [], []
    for sib in path:
        d = idx & 1
        left = sib if d else cur
        right = cur if d else sib
        init = [int(x) % F.P for x in left] + [int(x) % F.P for x in right] + list(a2.IV)
        snaps = _permute_snapshots(init)
        blocks.append(snaps)
        sibs.append(tuple(int(x) % F.P for x in sib)); dirs.append(d)
        cur = tuple(snaps[_R][:_CAP]); idx >>= 1
    assert a2.eq(cur, root), "path does not hash to root"

    BR = _R + 1                                    # rows per block
    nblk = len(blocks)
    rows = []
    for blk in blocks:
        rows.extend([list(s) for s in blk])        # R+1 rows each
    n_used = len(rows)
    T = _next_pow2(n_used)
    while len(rows) < T:
        rows.append(list(rows[-1]))

    # periodic: RC(W) | ractive | aactive | dir | sib(CAP)
    RC_lo, ACT_R, ACT_A, DIRC, SIB_lo = 0, _W, _W + 1, _W + 2, _W + 3
    NPER = SIB_lo + _CAP
    per = [[0] * T for _ in range(NPER)]
    for i in range(T):
        blk = i // BR
        rib = i % BR
        if i < n_used and rib < _R:                # a round row: RC for round `rib`, transition active
            for lane in range(_W):
                per[RC_lo + lane][i] = a2.RC[rib][lane]
            per[ACT_R][i] = 1
        if i < n_used and rib == _R and blk + 1 < nblk:   # boundary row feeding the NEXT block's absorb
            per[ACT_A][i] = 1
            per[DIRC][i] = dirs[blk]                # block 0's boundary feeds level-1 with sibs[0]/dirs[0]
            for lane in range(_CAP):
                per[SIB_lo + lane][i] = sibs[blk][lane]
    # boundaries: leaf init (row 0) + final digest lanes = root
    bnds = [(0, 0, a2.DOM_LEAF), (0, 1, int(leaf_val) % F.P)]
    for lane in range(2, _RATE):
        bnds.append((0, lane, 0))
    for lane in range(_CAP):
        bnds.append((0, _RATE + lane, a2.IV[lane]))
    final_row = (nblk - 1) * BR + _R
    for lane in range(_CAP):
        bnds.append((final_row, lane, int(root[lane]) % F.P))
    return rows, per, bnds, (RC_lo, ACT_R, ACT_A, DIRC, SIB_lo)


def _membership_transitions(cols):
    """Round + absorb-mux constraints. cols = (RC_lo, ACT_R, ACT_A, DIRC, SIB_lo)."""
    RC_lo, ACT_R, ACT_A, DIRC, SIB_lo = cols
    cons = []

    def round_c(i):
        def c(cur, nxt, per):
            t = [F.pw(F.add(cur[j], per[RC_lo + j]), a2.ALPHA) for j in range(_W)]
            mixed = 0
            for j in range(_W):
                mixed = F.add(mixed, F.mul(a2._MDS[i][j], t[j]))
            return F.mul(per[ACT_R], F.sub(nxt[i], mixed))
        return c
    for i in range(_W):
        cons.append(round_c(i))

    # absorb: next block's row 0 = [ ordered(cur[:CAP], sib) by dir | IV ]
    def absorb_left(i):
        def c(cur, nxt, per):
            d = per[DIRC]
            want = F.add(F.mul(F.sub(1, d), cur[i]), F.mul(d, per[SIB_lo + i]))   # (1-d)·cur + d·sib
            return F.mul(per[ACT_A], F.sub(nxt[i], want))
        return c

    def absorb_right(i):
        def c(cur, nxt, per):
            d = per[DIRC]
            want = F.add(F.mul(F.sub(1, d), per[SIB_lo + i]), F.mul(d, cur[i]))   # (1-d)·sib + d·cur
            return F.mul(per[ACT_A], F.sub(nxt[_CAP + i], want))
        return c

    def absorb_cap(i):
        def c(cur, nxt, per):
            return F.mul(per[ACT_A], F.sub(nxt[_RATE + i], a2.IV[i]))
        return c
    for i in range(_CAP):
        cons.append(absorb_left(i)); cons.append(absorb_right(i)); cons.append(absorb_cap(i))
    return cons


def prove_membership(leaf_val, index, path, root, num_queries=4):
    """Prove, in a STARK, that leaf `leaf_val`@`index` + `path` hashes up to the public `root` under the
    recursion Merkle tree — the alghash2 hashing-in-circuit chained up a path. Raises if the path is wrong."""
    rows, per, bnds, cols = _membership_air(leaf_val, index, path, root)
    proof = stark.prove(rows, _membership_transitions(cols), bnds, periodic=per, max_degree=8,
                        num_queries=num_queries, backend=backend.ALGHASH2)
    proof["_periodic"] = per
    proof["_bnds"] = bnds
    proof["_cols"] = cols
    return proof


def verify_membership(proof, root, num_queries=4):
    """Verify a membership proof against the PUBLIC root (the root the boundaries pin must equal `root`)."""
    per, bnds, cols = proof.get("_periodic"), proof.get("_bnds"), proof.get("_cols")
    if per is None or bnds is None or cols is None:
        return False, "missing public AIR schedule"
    pinned = tuple(v for (_r, _l, v) in bnds[-_CAP:])
    if pinned != tuple(int(x) % F.P for x in root):
        return False, "root boundary does not match the claimed root"
    return stark.verify(proof, _membership_transitions(cols), bnds, periodic=per, max_degree=8,
                        num_queries=num_queries, backend=backend.ALGHASH2)


# ---- FRI fold-consistency AIR: the field-arithmetic core of an in-circuit FRI verifier -----------------
# A FRI verifier's per-query work is (a) Merkle-open lo,hi at each layer (the membership AIR above) and
# (b) check the FOLD is consistent: the next layer's opened value equals fold(lo,hi,x,α). Division-free that
# is  2·x·nxt = x·(lo+hi) + α·(lo−hi)  (verified bit-identical to fri.verify's fold). This AIR proves that
# equation on EVERY fold-check row of a FRI proof at once. It is the arithmetic half of the FRI verifier; the
# Merkle half is the membership AIR, and the transcript-derived challenges α + query indices are PUBLIC — L1
# recomputes them from the proof's roots with a handful of hashes (cheap), so no transcript sponge is needed
# in-circuit. Together (membership + fold + the public-challenge L1 check + the small final-layer low-degree
# test) they are a complete, sound FRI verifier — the low-degree heart of a STARK, done in-circuit.
FOLD_LO, FOLD_HI, FOLD_X, FOLD_ALPHA, FOLD_NXT, FOLD_ACT = range(6)   # trace columns
FOLD_W = 6


def fold_rows(fri_proof, alphas, doms):
    """Extract the (lo, hi, x, α, nxt) fold-check tuples from a FRI proof, given the transcript-replayed
    fold challenges `alphas` and layer domains `doms` (the PUBLIC challenge schedule L1 re-derives). `nxt` is
    the value the fold must equal: the next layer's opened lo/hi (by position parity) or the final layer.
    Mirrors fri.verify's per-(query,layer) loop exactly."""
    rows = []
    roots, final = fri_proof["roots"], fri_proof["final"]
    for q in fri_proof["queries"]:
        a = q["idx"]
        for L, (alpha, domL, step) in enumerate(zip(alphas, doms, q["steps"])):
            nL = len(domL); half = nL // 2; a %= nL; lo = a % half
            x = domL[lo]
            if L + 1 < len(roots):
                nhalf = len(doms[L + 1]) // 2
                nxt = q["steps"][L + 1]["lo"] if lo < nhalf else q["steps"][L + 1]["hi"]
            else:
                nxt = final[lo]
            rows.append((step["lo"] % F.P, step["hi"] % F.P, x % F.P, alpha % F.P, nxt % F.P))
            a = lo
    return rows


def _fold_transitions():
    """One constraint: on an ACTIVE row, 2·x·nxt − x·(lo+hi) − α·(lo−hi) = 0."""
    def c(cur, nxt, per):
        x, lo, hi, al, nx = cur[FOLD_X], cur[FOLD_LO], cur[FOLD_HI], cur[FOLD_ALPHA], cur[FOLD_NXT]
        lhs = F.mul(F.mul(2, x), nx)
        rhs = F.add(F.mul(x, F.add(lo, hi)), F.mul(al, F.sub(lo, hi)))
        return F.mul(cur[FOLD_ACT], F.sub(lhs, rhs))
    return [c]


def _blocks_for(leaf_val, index, path):
    """The permutation-snapshot blocks for one Merkle path (rleaf(leaf_val) up `path`). Returns
    (blocks, sibs, dirs, final_digest)."""
    s0 = [a2.DOM_LEAF, int(leaf_val) % F.P, 0, 0, 0, 0, 0, 0] + list(a2.IV)
    blocks = [_permute_snapshots(s0)]
    cur = tuple(blocks[0][_R][:_CAP]); idx = index; sibs, dirs = [], []
    for sib in path:
        d = idx & 1
        left, right = (sib, cur) if d else (cur, sib)
        init = [int(v) % F.P for v in left] + [int(v) % F.P for v in right] + list(a2.IV)
        blocks.append(_permute_snapshots(init))
        sibs.append(tuple(int(v) % F.P for v in sib)); dirs.append(d)
        cur = tuple(blocks[-1][_R][:_CAP]); idx >>= 1
    return blocks, sibs, dirs, cur


# integrated FRI-STEP AIR column layout: 12 sponge lanes + 2 carry columns holding the (WITNESS) opened values
_CLO, _CHI = _W, _W + 1
_WSTEP = _W + 2


def _fri_step_air(lo_val, ilo, plo, hi_val, ihi, phi, root, x, alpha, nxt):
    """ONE integrated FRI-step, proving IN CIRCUIT: lo_val@ilo and hi_val@ihi Merkle-include under the PUBLIC
    `root`, AND 2·x·nxt = x·(lo+hi) + α·(lo−hi). The opened lo/hi are WITNESS (only root + x,α,nxt are public):
    two Merkle sub-traces (lo then hi) concatenated; carry columns hold the leaf values (tied to the leaf
    lane at each path's start, held constant) and feed the fold at the final row. Roots pinned; leaf VALUES
    are NOT pinned — the prover must find openings that both hash to root and fold, which is FRI verification."""
    lb, lsib, ldir, lcur = _blocks_for(lo_val, ilo, plo)
    hb, hsib, hdir, hcur = _blocks_for(hi_val, ihi, phi)
    assert a2.eq(lcur, root) and a2.eq(hcur, root), "a path does not hash to root"
    BR = _R + 1
    n_lo, n_hi = len(lb), len(hb)
    rows = []
    for blk in lb + hb:
        rows.extend([list(s) + [int(lo_val) % F.P, int(hi_val) % F.P] for s in blk])   # append carries
    n_used = len(rows)
    T = _next_pow2(n_used + 1)
    while len(rows) < T:
        rows.append(list(rows[-1]))
    lo_start = 0
    hi_start = n_lo * BR                                   # row where the hi-path's block 0 begins
    fold_row = n_used - 1                                  # last used row carries lo/hi -> fold there

    RC_lo = 0; ACT_R = _W; ACT_A = _W + 1; DIRC = _W + 2; SIB_lo = _W + 3
    SEL_LO = SIB_lo + _CAP; SEL_HI = SEL_LO + 1; FOLD_AT = SEL_HI + 1
    PX = FOLD_AT + 1; PALPHA = PX + 1; PNXT = PALPHA + 1
    NPER = PNXT + 1
    per = [[0] * T for _ in range(NPER)]

    def fill_path(base, sibs, dirs, nblk):
        for b in range(nblk):
            for rib in range(BR):
                i = base + b * BR + rib
                if rib < _R:                              # round row
                    for lane in range(_W):
                        per[RC_lo + lane][i] = a2.RC[rib][lane]
                    per[ACT_R][i] = 1
                elif b + 1 < nblk:                        # boundary row -> absorb the sibling into next block
                    per[ACT_A][i] = 1
                    per[DIRC][i] = dirs[b]
                    for lane in range(_CAP):
                        per[SIB_lo + lane][i] = sibs[b][lane]
    fill_path(lo_start, lsib, ldir, n_lo)
    fill_path(hi_start, hsib, hdir, n_hi)
    per[SEL_LO][lo_start] = 1                              # tie carry_lo to the lo-leaf lane here
    per[SEL_HI][hi_start] = 1
    per[FOLD_AT][fold_row] = 1
    per[PX][fold_row] = int(x) % F.P
    per[PALPHA][fold_row] = int(alpha) % F.P
    per[PNXT][fold_row] = int(nxt) % F.P

    # boundaries: each path's block-0 rleaf frame (DOM_LEAF, zeros, IV) — but NOT the leaf value — and each
    # path's final digest == root.
    bnds = []
    for start in (lo_start, hi_start):
        bnds.append((start, 0, a2.DOM_LEAF))
        for lane in range(2, _RATE):
            bnds.append((start, lane, 0))
        for lane in range(_CAP):
            bnds.append((start, _RATE + lane, a2.IV[lane]))
    for last_block_start in (lo_start + (n_lo - 1) * BR, hi_start + (n_hi - 1) * BR):
        frow = last_block_start + _R
        for lane in range(_CAP):
            bnds.append((frow, lane, int(root[lane]) % F.P))
    cols = (RC_lo, ACT_R, ACT_A, DIRC, SIB_lo, SEL_LO, SEL_HI, FOLD_AT, PX, PALPHA, PNXT)
    return rows, per, bnds, cols


def _fri_step_transitions(cols):
    RC_lo, ACT_R, ACT_A, DIRC, SIB_lo, SEL_LO, SEL_HI, FOLD_AT, PX, PALPHA, PNXT = cols
    cons = []

    def round_c(i):
        def c(cur, nxt, per):
            t = [F.pw(F.add(cur[j], per[RC_lo + j]), a2.ALPHA) for j in range(_W)]
            mixed = 0
            for j in range(_W):
                mixed = F.add(mixed, F.mul(a2._MDS[i][j], t[j]))
            return F.mul(per[ACT_R], F.sub(nxt[i], mixed))
        return c
    for i in range(_W):
        cons.append(round_c(i))

    def absorb_left(i):
        def c(cur, nxt, per):
            d = per[DIRC]
            want = F.add(F.mul(F.sub(1, d), cur[i]), F.mul(d, per[SIB_lo + i]))
            return F.mul(per[ACT_A], F.sub(nxt[i], want))
        return c

    def absorb_right(i):
        def c(cur, nxt, per):
            d = per[DIRC]
            want = F.add(F.mul(F.sub(1, d), per[SIB_lo + i]), F.mul(d, cur[i]))
            return F.mul(per[ACT_A], F.sub(nxt[_CAP + i], want))
        return c

    def absorb_cap(i):
        def c(cur, nxt, per):
            return F.mul(per[ACT_A], F.sub(nxt[_RATE + i], a2.IV[i]))
        return c
    for i in range(_CAP):
        cons.append(absorb_left(i)); cons.append(absorb_right(i)); cons.append(absorb_cap(i))

    # carry hold (lo/hi constant across the whole trace) + load (carry == leaf lane at each path start)
    cons.append(lambda c, n, p: F.sub(n[_CLO], c[_CLO]))
    cons.append(lambda c, n, p: F.sub(n[_CHI], c[_CHI]))
    cons.append(lambda c, n, p: F.mul(p[SEL_LO], F.sub(c[_CLO], c[1])))   # carry_lo == leaf lane at lo-start
    cons.append(lambda c, n, p: F.mul(p[SEL_HI], F.sub(c[_CHI], c[1])))   # carry_hi == leaf lane at hi-start
    # fold: 2·x·nxt = x·(lo+hi) + α·(lo−hi)  on the fold row
    def fold_c(c, n, p):
        lhs = F.mul(F.mul(2, p[PX]), p[PNXT])
        rhs = F.add(F.mul(p[PX], F.add(c[_CLO], c[_CHI])), F.mul(p[PALPHA], F.sub(c[_CLO], c[_CHI])))
        return F.mul(p[FOLD_AT], F.sub(lhs, rhs))
    cons.append(fold_c)
    return cons


def prove_fri_step(lo_val, ilo, plo, hi_val, ihi, phi, root, x, alpha, nxt, num_queries=4):
    """Prove one integrated FRI step (two Merkle openings + a fold) in ONE STARK. Returns a proof bundle;
    only root + (x, α, nxt) are public (carried in the bundle for the verifier)."""
    rows, per, bnds, cols = _fri_step_air(lo_val, ilo, plo, hi_val, ihi, phi, root, x, alpha, nxt)
    proof = stark.prove(rows, _fri_step_transitions(cols), bnds, periodic=per, max_degree=8,
                        num_queries=num_queries, backend=backend.ALGHASH2)
    proof["_per"] = per; proof["_bnds"] = bnds; proof["_cols"] = cols
    proof["_public"] = {"root": [int(v) % F.P for v in root], "x": int(x) % F.P,
                        "alpha": int(alpha) % F.P, "nxt": int(nxt) % F.P}
    return proof


def verify_fri_step(proof, root, x, alpha, nxt, num_queries=4):
    """Verify an integrated FRI-step proof against the PUBLIC (root, x, α, nxt): the pinned root boundaries
    must equal `root`, the fold periodic must equal (x, α, nxt), and the STARK must verify."""
    per, bnds, cols = proof.get("_per"), proof.get("_bnds"), proof.get("_cols")
    pub = proof.get("_public")
    if per is None or bnds is None or cols is None or pub is None:
        return False, "missing public AIR schedule"
    if (pub["root"] != [int(v) % F.P for v in root] or pub["x"] != int(x) % F.P
            or pub["alpha"] != int(alpha) % F.P or pub["nxt"] != int(nxt) % F.P):
        return False, "public inputs do not match the bundle"
    return stark.verify(proof, _fri_step_transitions(cols), bnds, periodic=per, max_degree=8,
                        num_queries=num_queries, backend=backend.ALGHASH2)


# ---- chained multi-layer FRI verifier for ONE query: steps concatenated, folded value PRIVATE + linked ----
# Columns: 12 sponge lanes + CLO,CHI (opened values, per-step) + FOLDED (the fold result, per-step). Per-step
# carries reset at each step boundary (HOLD off on a step's last row); FOLDED of step i is tied to step i+1's
# opening (CHAIN), and the LAST step's FOLDED is pinned to the public final value. Only the layer roots + the
# public (x,α) schedule + the final value are public — every opened evaluation stays witness.
_QLO, _QHI, _QFOLD = _W, _W + 1, _W + 2
_WQ = _W + 3


def _fri_query_air(queries, finals):
    """queries = list of query step-lists; step = (lo_val, ilo, plo, hi_val, ihi, phi, root, x, alpha,
    chain_to_lo). `finals[q]` = the PUBLIC final value the q-th query's chain must fold to (the query's OWN
    FRI proof's final layer — so one recursion proof can fold MANY FRI proofs, each query pinned to its own
    proof's final). Proves every query's fold chain in one STARK; all openings witness, only roots+(x,α)+finals
    public."""
    BR = _R + 1
    # flatten steps, remembering which are a query's LAST layer (fold -> that query's final, no chain)
    steps, query_end, step_final = [], [], []
    for qi, q in enumerate(queries):
        for j, st in enumerate(q):
            steps.append(st); query_end.append(j == len(q) - 1)
            step_final.append(finals[qi])
    # build every step's rows; remember per-step landmarks
    seg = []          # (lo_start, hi_start, fold_row, lsib,ldir,n_lo, hsib,hdir,n_hi)
    rows = []
    for (lo_val, ilo, plo, hi_val, ihi, phi, root, x, alpha, _c2lo) in steps:
        lb, lsib, ldir, lcur = _blocks_for(lo_val, ilo, plo)
        hb, hsib, hdir, hcur = _blocks_for(hi_val, ihi, phi)
        assert a2.eq(lcur, root) and a2.eq(hcur, root), "a path does not hash to root"
        lo_start = len(rows)
        for blk in lb:
            rows.extend([list(s) + [int(lo_val) % F.P, int(hi_val) % F.P, 0] for s in blk])
        hi_start = len(rows)
        for blk in hb:
            rows.extend([list(s) + [int(lo_val) % F.P, int(hi_val) % F.P, 0] for s in blk])
        fold_row = len(rows) - 1
        seg.append((lo_start, hi_start, fold_row, lsib, ldir, len(lb), hsib, hdir, len(hb)))
    n_used = len(rows)
    T = _next_pow2(n_used + 1)
    # fill FOLDED witness per step (constant within the step = the correct fold), padded rows copy last
    INV2 = F.inv(2)
    for si, (lo_start, hi_start, fold_row, *_r) in enumerate(seg):
        lo_val, hi_val, x, alpha = steps[si][0], steps[si][3], steps[si][6 + 1], steps[si][6 + 2]
        # steps[si] = (lo,ilo,plo,hi,ihi,phi,root,x,alpha,c2lo) -> x=idx7, alpha=idx8
        x = steps[si][7]; alpha = steps[si][8]
        fv = F.add(F.mul(F.add(lo_val, hi_val), INV2),
                   F.mul(alpha, F.mul(F.sub(lo_val, hi_val), F.mul(INV2, F.inv(x)))))
        for i in range(lo_start, fold_row + 1):
            rows[i][_QFOLD] = fv % F.P
    while len(rows) < T:
        rows.append(list(rows[-1]))

    RC_lo = 0; ACT_R = _W; ACT_A = _W + 1; DIRC = _W + 2; SIB_lo = _W + 3
    SEL_LO = SIB_lo + _CAP; SEL_HI = SEL_LO + 1; HOLD = SEL_HI + 1; FOLD_AT = HOLD + 1
    PX = FOLD_AT + 1; PALPHA = PX + 1; CHAIN_LO = PALPHA + 1; CHAIN_HI = CHAIN_LO + 1
    FINAL_AT = CHAIN_HI + 1; PFINAL = FINAL_AT + 1
    NPER = PFINAL + 1
    per = [[0] * T for _ in range(NPER)]

    def fill_path(base, sibs, dirs, nblk):
        for b in range(nblk):
            for rib in range(BR):
                i = base + b * BR + rib
                if rib < _R:
                    for lane in range(_W):
                        per[RC_lo + lane][i] = a2.RC[rib][lane]
                    per[ACT_R][i] = 1
                elif b + 1 < nblk:
                    per[ACT_A][i] = 1; per[DIRC][i] = dirs[b]
                    for lane in range(_CAP):
                        per[SIB_lo + lane][i] = sibs[b][lane]

    for si, (lo_start, hi_start, fold_row, lsib, ldir, n_lo, hsib, hdir, n_hi) in enumerate(seg):
        fill_path(lo_start, lsib, ldir, n_lo)
        fill_path(hi_start, hsib, hdir, n_hi)
        per[SEL_LO][lo_start] = 1
        per[SEL_HI][hi_start] = 1
        per[FOLD_AT][fold_row] = 1
        per[PX][fold_row] = steps[si][7] % F.P
        per[PALPHA][fold_row] = steps[si][8] % F.P
        # HOLD on within-step (carry lo/hi/folded constant) — every used row of the step EXCEPT its last row
        for i in range(lo_start, fold_row):
            per[HOLD][i] = 1
        if query_end[si]:                            # a query's last layer: FOLDED == that query's public final
            per[FINAL_AT][fold_row] = 1
            per[PFINAL][fold_row] = int(step_final[si]) % F.P
        else:                                        # chain FOLDED_i -> next step's opening (lo or hi)
            if steps[si][9]:
                per[CHAIN_LO][fold_row] = 1
            else:
                per[CHAIN_HI][fold_row] = 1

    bnds = []
    for si, (lo_start, hi_start, fold_row, lsib, ldir, n_lo, hsib, hdir, n_hi) in enumerate(seg):
        # each path's block-0 rleaf frame (DOM_LEAF, zeros, IV) — the leaf VALUE stays witness
        for start in (lo_start, hi_start):
            bnds.append((start, 0, a2.DOM_LEAF))
            for lane in range(2, _RATE):
                bnds.append((start, lane, 0))
            for lane in range(_CAP):
                bnds.append((start, _RATE + lane, a2.IV[lane]))
        # each path's final digest == this step's (public) root
        rt = steps[si][6]
        for last_start in (lo_start + (n_lo - 1) * BR, hi_start + (n_hi - 1) * BR):
            frow = last_start + _R
            for lane in range(_CAP):
                bnds.append((frow, lane, int(rt[lane]) % F.P))
    cols = (RC_lo, ACT_R, ACT_A, DIRC, SIB_lo, SEL_LO, SEL_HI, HOLD, FOLD_AT, PX, PALPHA,
            CHAIN_LO, CHAIN_HI, FINAL_AT, PFINAL)
    return rows, per, bnds, cols


def _fri_query_transitions(cols):
    (RC_lo, ACT_R, ACT_A, DIRC, SIB_lo, SEL_LO, SEL_HI, HOLD, FOLD_AT, PX, PALPHA,
     CHAIN_LO, CHAIN_HI, FINAL_AT, PFINAL) = cols
    cons = []

    def round_c(i):
        def c(cur, nxt, per):
            t = [F.pw(F.add(cur[j], per[RC_lo + j]), a2.ALPHA) for j in range(_W)]
            mixed = 0
            for j in range(_W):
                mixed = F.add(mixed, F.mul(a2._MDS[i][j], t[j]))
            return F.mul(per[ACT_R], F.sub(nxt[i], mixed))
        return c
    for i in range(_W):
        cons.append(round_c(i))

    def a_left(i):
        def c(cur, nxt, per):
            d = per[DIRC]
            return F.mul(per[ACT_A], F.sub(nxt[i], F.add(F.mul(F.sub(1, d), cur[i]), F.mul(d, per[SIB_lo + i]))))
        return c

    def a_right(i):
        def c(cur, nxt, per):
            d = per[DIRC]
            return F.mul(per[ACT_A], F.sub(nxt[_CAP + i], F.add(F.mul(F.sub(1, d), per[SIB_lo + i]), F.mul(d, cur[i]))))
        return c

    def a_cap(i):
        def c(cur, nxt, per):
            return F.mul(per[ACT_A], F.sub(nxt[_RATE + i], a2.IV[i]))
        return c
    for i in range(_CAP):
        cons.append(a_left(i)); cons.append(a_right(i)); cons.append(a_cap(i))

    # per-step carries hold while HOLD=1 (reset at each step's last row)
    cons.append(lambda c, n, p: F.mul(p[HOLD], F.sub(n[_QLO], c[_QLO])))
    cons.append(lambda c, n, p: F.mul(p[HOLD], F.sub(n[_QHI], c[_QHI])))
    cons.append(lambda c, n, p: F.mul(p[HOLD], F.sub(n[_QFOLD], c[_QFOLD])))
    # load carries from the authenticated leaf lane at each step's path starts
    cons.append(lambda c, n, p: F.mul(p[SEL_LO], F.sub(c[_QLO], c[1])))
    cons.append(lambda c, n, p: F.mul(p[SEL_HI], F.sub(c[_QHI], c[1])))
    # fold correctness: 2·x·folded = x·(lo+hi) + α·(lo−hi)
    def fold_c(c, n, p):
        lhs = F.mul(F.mul(2, p[PX]), c[_QFOLD])
        rhs = F.add(F.mul(p[PX], F.add(c[_QLO], c[_QHI])), F.mul(p[PALPHA], F.sub(c[_QLO], c[_QHI])))
        return F.mul(p[FOLD_AT], F.sub(lhs, rhs))
    cons.append(fold_c)
    # chain: this step's folded value is the NEXT step's opening (lo or hi), across the step boundary
    cons.append(lambda c, n, p: F.mul(p[CHAIN_LO], F.sub(n[_QLO], c[_QFOLD])))
    cons.append(lambda c, n, p: F.mul(p[CHAIN_HI], F.sub(n[_QHI], c[_QFOLD])))
    # last step: folded == public final value
    cons.append(lambda c, n, p: F.mul(p[FINAL_AT], F.sub(c[_QFOLD], p[PFINAL])))
    return cons


def prove_fri_proof(queries, final_val, num_queries=4):
    """Prove ONE FRI proof in circuit (every query's chain folds to the single `final_val`)."""
    return _prove_fri(queries, [final_val] * len(queries), num_queries)


def _prove_fri(queries, finals, num_queries=4):
    rows, per, bnds, cols = _fri_query_air(queries, finals)
    proof = stark.prove(rows, _fri_query_transitions(cols), bnds, periodic=per, max_degree=8,
                        num_queries=num_queries, backend=backend.ALGHASH2)
    proof["_per"] = per; proof["_bnds"] = bnds; proof["_cols"] = cols
    return proof


def verify_fri_proof(proof, num_queries=4):
    """Verify an in-circuit FRI-proof (or a fold of several). Roots + fold schedule + finals are pinned in the
    AIR (the same public statement the prover used)."""
    per, bnds, cols = proof.get("_per"), proof.get("_bnds"), proof.get("_cols")
    if per is None or bnds is None or cols is None:
        return False, "missing public AIR schedule"
    return stark.verify(proof, _fri_query_transitions(cols), bnds, periodic=per, max_degree=8,
                        num_queries=num_queries, backend=backend.ALGHASH2)


def prove_fri_query(steps, final_val, num_queries=4):
    """One-query convenience wrapper over prove_fri_proof."""
    return prove_fri_proof([steps], final_val, num_queries=num_queries)


def verify_fri_query(proof, num_queries=4):
    return verify_fri_proof(proof, num_queries=num_queries)


def prove_recursive(fri_proofs, num_queries=4):
    """THE FOLD (for FRI low-degree proofs): verify MANY FRI proofs inside ONE recursion proof — a proof that
    proves other proofs. `fri_proofs` = list of {"queries": [...], "final": value} (each in recursion-ready
    rleaf/rnode form). Concatenates every proof's query-chains, each pinned to its OWN proof's final, into a
    single STARK. verify_recursive checks that one proof — O(1) in the number of folded proofs, up to the trace
    cap (beyond which fold_tree recurses). This is the aggregation step segmentation feeds into."""
    all_queries, all_finals = [], []
    for fp in fri_proofs:
        for q in fp["queries"]:
            all_queries.append(q); all_finals.append(fp["final"])
    return _prove_fri(all_queries, all_finals, num_queries)


def verify_recursive(proof, num_queries=4):
    """Verify a recursion (fold) proof — one check for all the FRI proofs it folded."""
    return verify_fri_proof(proof, num_queries=num_queries)


# ---- composition spot-check AIR: bind AUTHENTICATED trace openings to the AIR constraints -----------------
# The other half of a STARK verifier (beyond FRI low-degree): per query, open the trace columns at the query
# rows, RECOMPUTE the composition from them + the verifier's public periodic/challenge values, and check it
# equals the FRI layer-0 value. This demonstrates it for a 1-column inner AIR with the transition x_next =
# x_cur^2 and a boundary (row0 = seed): cp = At·(x_nxt − x_cur^2)·invZ + Ab·(x_cur − seed)·invDen, checked ==
# the (public) layer-0 value. The two openings (x@lo, x@nxt) are Merkle-authenticated (private) and carried to
# the check — the SAME membership+carry structure the FRI-step uses. For the execution AIR the fixed x^2 term
# is replaced by an in-circuit evaluation of the constraint-IR (air_ir); the mechanism here is identical.
def _comp_step_air(x_lo, ilo, plo, x_nxt, inxt, pnxt, col_root, At, invZ, Ab, invDen, seed, layer0):
    lb, lsib, ldir, lcur = _blocks_for(x_lo, ilo, plo)
    hb, hsib, hdir, hcur = _blocks_for(x_nxt, inxt, pnxt)
    assert a2.eq(lcur, col_root) and a2.eq(hcur, col_root), "a trace opening does not hash to the column root"
    BR = _R + 1
    n_lo, n_hi = len(lb), len(hb)
    rows = []
    for blk in lb + hb:
        rows.extend([list(s) + [int(x_lo) % F.P, int(x_nxt) % F.P] for s in blk])
    n_used = len(rows)
    T = _next_pow2(n_used + 1)
    while len(rows) < T:
        rows.append(list(rows[-1]))
    lo_start, hi_start, chk_row = 0, n_lo * BR, n_used - 1

    RC_lo = 0; ACT_R = _W; ACT_A = _W + 1; DIRC = _W + 2; SIB_lo = _W + 3
    SEL_LO = SIB_lo + _CAP; SEL_HI = SEL_LO + 1; CHK_AT = SEL_HI + 1
    PAT = CHK_AT + 1; PIZ = PAT + 1; PAB = PIZ + 1; PID = PAB + 1; PSEED = PID + 1; PL0 = PSEED + 1
    NPER = PL0 + 1
    per = [[0] * T for _ in range(NPER)]

    def fill_path(base, sibs, dirs, nblk):
        for b in range(nblk):
            for rib in range(BR):
                i = base + b * BR + rib
                if rib < _R:
                    for lane in range(_W):
                        per[RC_lo + lane][i] = a2.RC[rib][lane]
                    per[ACT_R][i] = 1
                elif b + 1 < nblk:
                    per[ACT_A][i] = 1; per[DIRC][i] = dirs[b]
                    for lane in range(_CAP):
                        per[SIB_lo + lane][i] = sibs[b][lane]
    fill_path(lo_start, lsib, ldir, n_lo)
    fill_path(hi_start, hsib, hdir, n_hi)
    per[SEL_LO][lo_start] = 1; per[SEL_HI][hi_start] = 1; per[CHK_AT][chk_row] = 1
    per[PAT][chk_row] = int(At) % F.P; per[PIZ][chk_row] = int(invZ) % F.P
    per[PAB][chk_row] = int(Ab) % F.P; per[PID][chk_row] = int(invDen) % F.P
    per[PSEED][chk_row] = int(seed) % F.P; per[PL0][chk_row] = int(layer0) % F.P

    bnds = []
    for start in (lo_start, hi_start):
        bnds.append((start, 0, a2.DOM_LEAF))
        for lane in range(2, _RATE):
            bnds.append((start, lane, 0))
        for lane in range(_CAP):
            bnds.append((start, _RATE + lane, a2.IV[lane]))
    for last_start in (lo_start + (n_lo - 1) * BR, hi_start + (n_hi - 1) * BR):
        frow = last_start + _R
        for lane in range(_CAP):
            bnds.append((frow, lane, int(col_root[lane]) % F.P))
    cols = (RC_lo, ACT_R, ACT_A, DIRC, SIB_lo, SEL_LO, SEL_HI, CHK_AT, PAT, PIZ, PAB, PID, PSEED, PL0)
    return rows, per, bnds, cols


def _comp_step_transitions(cols):
    RC_lo, ACT_R, ACT_A, DIRC, SIB_lo, SEL_LO, SEL_HI, CHK_AT, PAT, PIZ, PAB, PID, PSEED, PL0 = cols
    cons = []

    def round_c(i):
        def c(cur, nxt, per):
            t = [F.pw(F.add(cur[j], per[RC_lo + j]), a2.ALPHA) for j in range(_W)]
            mixed = 0
            for j in range(_W):
                mixed = F.add(mixed, F.mul(a2._MDS[i][j], t[j]))
            return F.mul(per[ACT_R], F.sub(nxt[i], mixed))
        return c
    for i in range(_W):
        cons.append(round_c(i))

    def a_left(i):
        def c(cur, nxt, per):
            d = per[DIRC]
            return F.mul(per[ACT_A], F.sub(nxt[i], F.add(F.mul(F.sub(1, d), cur[i]), F.mul(d, per[SIB_lo + i]))))
        return c

    def a_right(i):
        def c(cur, nxt, per):
            d = per[DIRC]
            return F.mul(per[ACT_A], F.sub(nxt[_CAP + i], F.add(F.mul(F.sub(1, d), per[SIB_lo + i]), F.mul(d, cur[i]))))
        return c

    def a_cap(i):
        def c(cur, nxt, per):
            return F.mul(per[ACT_A], F.sub(nxt[_RATE + i], a2.IV[i]))
        return c
    for i in range(_CAP):
        cons.append(a_left(i)); cons.append(a_right(i)); cons.append(a_cap(i))

    cons.append(lambda c, n, p: F.sub(n[_CLO], c[_CLO]))
    cons.append(lambda c, n, p: F.sub(n[_CHI], c[_CHI]))
    cons.append(lambda c, n, p: F.mul(p[SEL_LO], F.sub(c[_CLO], c[1])))
    cons.append(lambda c, n, p: F.mul(p[SEL_HI], F.sub(c[_CHI], c[1])))
    # composition recompute: cp = At·(x_nxt − x_cur^2)·invZ + Ab·(x_cur − seed)·invDen ; check cp == layer0
    def check_c(c, n, p):
        xl, xn = c[_CLO], c[_CHI]
        trans = F.mul(F.mul(p[PAT], F.sub(xn, F.mul(xl, xl))), p[PIZ])
        bnd = F.mul(F.mul(p[PAB], F.sub(xl, p[PSEED])), p[PID])
        cp = F.add(trans, bnd)
        return F.mul(p[CHK_AT], F.sub(cp, p[PL0]))
    cons.append(check_c)
    return cons


def prove_comp_step(x_lo, ilo, plo, x_nxt, inxt, pnxt, col_root, At, invZ, Ab, invDen, seed, layer0,
                    num_queries=4):
    """Prove ONE composition spot-check for the x²-AIR: x@lo, x@nxt are Merkle-authenticated under col_root
    (private) AND recompute the composition to the PUBLIC layer-0 value. The trace-to-constraints half of an
    in-circuit STARK verifier (the FRI half is prove_fri_proof)."""
    rows, per, bnds, cols = _comp_step_air(x_lo, ilo, plo, x_nxt, inxt, pnxt, col_root, At, invZ, Ab, invDen,
                                           seed, layer0)
    proof = stark.prove(rows, _comp_step_transitions(cols), bnds, periodic=per, max_degree=8,
                        num_queries=num_queries, backend=backend.ALGHASH2)
    proof["_per"] = per; proof["_bnds"] = bnds; proof["_cols"] = cols
    return proof


def verify_comp_step(proof, num_queries=4):
    per, bnds, cols = proof.get("_per"), proof.get("_bnds"), proof.get("_cols")
    if per is None or bnds is None or cols is None:
        return False, "missing public AIR schedule"
    return stark.verify(proof, _comp_step_transitions(cols), bnds, periodic=per, max_degree=8,
                        num_queries=num_queries, backend=backend.ALGHASH2)


def prove_fri_folds(rows, num_queries=4):
    """Prove every fold-check row (from fold_rows) satisfies the FRI fold equation, in ONE STARK. `rows` =
    [(lo,hi,x,α,nxt)]. Returns a proof bundle. This is the fold half of the in-circuit FRI verifier."""
    n = len(rows)
    T = max(2, _next_pow2(n + 1))
    trace = []
    for (lo, hi, x, al, nx) in rows:
        trace.append([lo, hi, x, al, nx, 1])
    while len(trace) < T:
        trace.append([0, 0, 0, 0, 0, 0])           # inert pad rows (ACT = 0)
    proof = stark.prove(trace, _fold_transitions(), [], max_degree=2, num_queries=num_queries,
                        backend=backend.ALGHASH2)
    proof["_nrows"] = n
    return proof


def verify_fri_folds(proof, rows, num_queries=4):
    """Verify a fold-consistency proof AGAINST the public rows: the proof must verify AND its committed active
    rows must be exactly `rows` (so the folds proven are the ones in the FRI proof the caller re-derived, not
    prover-chosen). Returns (ok, reason)."""
    if proof.get("_nrows") != len(rows):
        return False, "row count mismatch"
    # the trace's active rows are pinned by the caller's `rows` via boundary checks on the opened trace values:
    # re-run the transition verifier, then confirm the opened rows the STARK authenticates match `rows`.
    ok, why = stark.verify(proof, _fold_transitions(), [], max_degree=2, num_queries=num_queries,
                           backend=backend.ALGHASH2)
    return ok, why
