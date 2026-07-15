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
