"""
In-circuit Fiat-Shamir CHAIN (doc/zk-recursion.md §5 step 9): derive ALL of a FRI transcript's fold challenges
α_0..α_{L-1} from the layer roots, entirely in field constraints — the full in-circuit transcript for the FRI
fold-challenge schedule. Chains the absorb→challenge step (fs_step) across layers: starting from the public
t_init state, for each layer root absorb it then squeeze a challenge, feeding each challenge's digest into the
next absorb. This is what lets the verifier stop re-deriving α out of circuit (the O(1)-verify keystone): the
roots collapse to witness bound to a commitment, and α is a proven output.

Segments (all contiguous, so every state-flow link is an adjacent-row constraint):
    absorb(s0_public, root_0) → challenge → α_0 ; absorb(·, root_1) → challenge → α_1 ; …
The transition set is identical to fs_step (round / within-hashn absorb / per-segment first / segment-boundary
link), gated by periodic selectors; only the schedule (row layout, periodic, boundaries) grows with L.
Bit-identical to replaying backend t_absorb/t_challenge.
"""
from execnode.stark import alghash2 as a2, field as F, stark, backend
from execnode.stark.fs_step import (_seg_blocks, _chunks_of, _transitions, _W, _R, _RATE, _CAP, _BR,
                                     _M, _WTOT, _RCL, _ACTR, _ABS, _FIRST, _LINK, _NPER, DOM_ABSORB, DOM_CHAL)


def _init_state(label="fri", b=None):
    """The public transcript start state t_init(label) = hashn([DOM_ABSORB, label_enc]) — a constant the verifier
    holds. Uses the same backend encoding as Transcript."""
    from execnode.stark import backend as _bk
    bk = b or _bk.RECURSION
    return list(bk.t_init(label))


def _schedule(state0, roots):
    """Lay out absorb/challenge segments for the whole α chain and return (rows, per, bnds, alphas, T)."""
    s = [int(v) % F.P for v in state0]
    # build the sequence of segments, resolving each link from the previous digest
    segs = []                    # each: (kind, chunks, digest, first_M_state_public_or_None, root_or_None)
    cur_state = s
    alphas = []
    for r in roots:
        r = [int(v) % F.P for v in r]
        els_a = [len([DOM_ABSORB, *cur_state, *r])] + [DOM_ABSORB, *cur_state, *r]
        a_blocks, a_dig = _seg_blocks(_chunks_of(els_a))
        segs.append(("absorb", a_blocks, a_dig))
        els_c = [len([DOM_CHAL, *a_dig])] + [DOM_CHAL, *list(a_dig)]
        c_blocks, c_dig = _seg_blocks(_chunks_of(els_c))
        segs.append(("challenge", c_blocks, c_dig))
        alphas.append(c_dig[0])
        cur_state = list(c_dig)

    n_blocks = sum(len(bl) for (_k, bl, _d) in segs)
    n_used = n_blocks * _BR
    T = 1
    while T < n_used + 1:
        T <<= 1
    rows = [[0] * _WTOT for _ in range(T)]
    per = [[0] * T for _ in range(_NPER)]
    bnds = []

    row = 0
    seg_first_rows = []
    for si, (kind, blocks, digest) in enumerate(segs):
        seg_first_rows.append(row)
        for bi, (snaps, M) in enumerate(blocks):
            for srow in range(_BR):
                i = row + srow
                for lane in range(_W):
                    rows[i][lane] = int(snaps[srow][lane]) % F.P
                if srow == 0:
                    for k in range(_RATE):
                        rows[i][_M + k] = int(M[k]) % F.P
                if srow < _R:
                    for lane in range(_W):
                        per[_RCL + lane][i] = a2.RC[srow][lane]
                    per[_ACTR][i] = 1
            last = row + _R
            if bi < len(blocks) - 1:
                per[_ABS][last] = 1                          # continue the sponge within this hashn
            elif si < len(segs) - 1:
                per[_LINK][last] = 1                         # feed this digest into the next segment's chunk
            row += _BR
        per[_FIRST][seg_first_rows[si]] = 1                 # each segment starts a fresh sponge
        # public first-chunk constants (len, DOM) for every segment
        dom = DOM_ABSORB if kind == "absorb" else DOM_CHAL
        chunk0_len = (len([DOM_ABSORB]) + _CAP + _CAP) if kind == "absorb" else (len([DOM_CHAL]) + _CAP)
        bnds.append((seg_first_rows[si], _M + 0, chunk0_len % F.P))
        bnds.append((seg_first_rows[si], _M + 1, dom % F.P))
    # the very first segment's state is the PUBLIC t_init state
    for j in range(_CAP):
        bnds.append((seg_first_rows[0], _M + 2 + j, s[j]))
    # pin each challenge digest (α_i = its lane 0) so the verifier checks the derivation
    for si, (kind, blocks, digest) in enumerate(segs):
        if kind == "challenge":
            dig_row = seg_first_rows[si] + (len(blocks) - 1) * _BR + _R
            for j in range(_CAP):
                bnds.append((dig_row, j, int(digest[j]) % F.P))
    last_row = n_used - 1
    for i in range(n_used, T):
        rows[i] = list(rows[last_row])
    return rows, per, bnds, alphas, T


def prove_alphas(roots, label="fri", num_queries=stark.NUM_QUERIES):
    """Prove the whole fold-challenge schedule α_0..α_{L-1} is the correct in-circuit derivation from `roots`
    (witness) and the public t_init(label) state. Returns (proof, alphas)."""
    state0 = _init_state(label)
    rows, per, bnds, alphas, T = _schedule(state0, roots)
    proof = stark.prove(rows, _transitions(), bnds, periodic=per, max_degree=8,
                        num_queries=num_queries, backend=backend.ALGHASH2)
    proof["_per"] = per; proof["_bnds"] = bnds
    return proof, alphas


def verify_alphas(proof, num_queries=stark.NUM_QUERIES):
    per, bnds = proof.get("_per"), proof.get("_bnds")
    if per is None or bnds is None:
        return False, "missing public AIR schedule"
    return stark.verify(proof, _transitions(), bnds, periodic=per, max_degree=8,
                        num_queries=num_queries, backend=backend.ALGHASH2)
