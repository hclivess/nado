"""
In-circuit Fiat-Shamir STEP (doc/zk-recursion.md §5 step 9): derive one fold challenge α from a transcript
state and a root, entirely in field constraints — α = challenge(absorb(state, root)). This is the unit the FRI
in-circuit transcript chains (absorb root_i → challenge → α_i, for each layer), which is what lets the verifier's
Fiat-Shamir work move inside a proof (the O(1)-verify keystone). Built on the in-circuit hashn sponge
(fs_incircuit): two hashn calls placed contiguously so the state-flow link between them is an adjacent-row
constraint.

  absorb(state, root) = hashn([DOM_ABSORB, *state, *root])         (9 elements → els=10 → 2 blocks)
  challenge(s')       = hashn([DOM_CHAL, *s'])                      (5 elements → els=6  → 1 block)
  α = challenge_digest[0]

`state` is PUBLIC (the transcript state before this step — a constant the verifier holds); `root` is WITNESS; the
derived challenge digest (hence α) is pinned public so a verifier checks the derivation binds α to (state, root).
Bit-identical to backend `t_absorb`/`t_challenge` by construction.
"""
from execnode.stark import alghash2 as a2, field as F, stark, backend
from execnode.stark.recursion import _permute_snapshots

_W, _R, _RATE, _CAP = a2.WIDTH, a2.ROUNDS, a2.RATE, a2.DIGEST
_BR = _R + 1
_M = _W                                   # absorb-chunk witness columns 12..19
_WTOT = _W + _RATE                         # 20
_RCL = 0; _ACTR = _W; _ABS = _W + 1; _FIRST = _W + 2; _LINK = _W + 3
_NPER = _W + 4

DOM_ABSORB, DOM_CHAL = a2.DOM_ABSORB, a2.DOM_CHAL


def _chunks_of(els):
    return [els[o:o + _RATE] for o in range(0, len(els), _RATE)]


def _seg_blocks(chunks):
    """Sponge snapshots for a hashn whose successive RATE-chunks are `chunks` (each already the raw values added
    into the rate). Returns (list-of-block-snapshots, digest)."""
    state = [0] * _RATE + list(a2.IV)
    blocks = []
    for ch in chunks:
        M = [0] * _RATE
        for i, m in enumerate(ch):
            M[i] = int(m) % F.P
        for i in range(_RATE):
            state[i] = F.add(state[i], M[i])
        snaps = _permute_snapshots(state)
        blocks.append((snaps, M))
        state = list(snaps[_R])
    return blocks, tuple(state[:_CAP])


def _schedule(state_in, root):
    s = [int(v) % F.P for v in state_in]
    r = [int(v) % F.P for v in root]
    els_a = [len([DOM_ABSORB, *s, *r])] + [DOM_ABSORB, *s, *r]        # absorb input, length-prefixed
    a_blocks, a_dig = _seg_blocks(_chunks_of(els_a))
    els_c = [len([DOM_CHAL, *a_dig])] + [DOM_CHAL, *a_dig]            # challenge input
    c_blocks, c_dig = _seg_blocks(_chunks_of(els_c))
    seg = [a_blocks, c_blocks]                                        # two segments (contiguous)
    n_blocks = len(a_blocks) + len(c_blocks)
    n_used = n_blocks * _BR
    T = 1
    while T < n_used + 1:
        T <<= 1
    rows = [[0] * _WTOT for _ in range(T)]
    per = [[0] * T for _ in range(_NPER)]

    block_starts = []                                                # (start_row, is_segment_first)
    row = 0
    for si, blocks in enumerate(seg):
        for bi, (snaps, M) in enumerate(blocks):
            block_starts.append((row, si, bi))
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
            # transition out of this block's last row (row+_R):
            last = row + _R
            if bi < len(blocks) - 1:
                per[_ABS][last] = 1                                   # continue the sponge into the next block
            elif si < len(seg) - 1:
                per[_LINK][last] = 1                                  # segment boundary: next chunk carries this digest
            row += _BR
    per[_FIRST][0] = 1                                               # absorb segment fresh state
    c_start = len(a_blocks) * _BR
    per[_FIRST][c_start] = 1                                         # challenge segment fresh state

    # boundaries: public constants of each segment's first chunk + the pinned challenge digest (hence α).
    bnds = [(0, _M + 0, els_a[0] % F.P), (0, _M + 1, DOM_ABSORB % F.P)]
    for j in range(_CAP):
        bnds.append((0, _M + 2 + j, s[j]))                           # state_in is public
    bnds += [(c_start, _M + 0, els_c[0] % F.P), (c_start, _M + 1, DOM_CHAL % F.P)]
    last_row = n_used - 1
    for j in range(_CAP):
        bnds.append((last_row, j, int(c_dig[j]) % F.P))              # challenge digest (α = lane 0)
    for i in range(n_used, T):
        rows[i] = list(rows[last_row])
    return rows, per, bnds, c_dig, T, last_row


def _transitions():
    cons = []

    def round_c(i):
        def c(cur, nxt, per):
            t = [F.pw(F.add(cur[j], per[_RCL + j]), a2.ALPHA) for j in range(_W)]
            mixed = 0
            for j in range(_W):
                mixed = F.add(mixed, F.mul(a2._MDS[i][j], t[j]))
            return F.mul(per[_ACTR], F.sub(nxt[i], mixed))
        return c
    for i in range(_W):
        cons.append(round_c(i))

    def abs_rate(i):
        return lambda c, n, p: F.mul(p[_ABS], F.sub(n[i], F.add(c[i], n[_M + i])))

    def abs_cap(i):
        return lambda c, n, p: F.mul(p[_ABS], F.sub(n[_RATE + i], c[_RATE + i]))
    for i in range(_RATE):
        cons.append(abs_rate(i))
    for i in range(_CAP):
        cons.append(abs_cap(i))

    def first_rate(i):
        return lambda c, n, p: F.mul(p[_FIRST], F.sub(c[i], c[_M + i]))

    def first_cap(i):
        return lambda c, n, p: F.mul(p[_FIRST], F.sub(c[_RATE + i], a2.IV[i]))
    for i in range(_RATE):
        cons.append(first_rate(i))
    for i in range(_CAP):
        cons.append(first_cap(i))

    # LINK: at a segment boundary, the next segment's chunk carries THIS segment's digest at positions 2..2+CAP
    # (right after [len, DOM]) — an adjacent-row tie (cur = digest row, nxt = next segment's first row).
    def link_c(j):
        return lambda c, n, p: F.mul(p[_LINK], F.sub(n[_M + 2 + j], c[j]))
    for j in range(_CAP):
        cons.append(link_c(j))
    return cons


def prove_step(state_in, root, num_queries=stark.NUM_QUERIES):
    """Prove α = challenge(absorb(state_in, root)) in-circuit. `state_in` public, `root` witness. Returns
    (proof, challenge_digest); α = challenge_digest[0]."""
    rows, per, bnds, c_dig, T, _last = _schedule(state_in, root)
    proof = stark.prove(rows, _transitions(), bnds, periodic=per, max_degree=8,
                        num_queries=num_queries, backend=backend.ALGHASH2)
    proof["_per"] = per; proof["_bnds"] = bnds
    return proof, c_dig


def verify_step(proof, challenge_digest, num_queries=stark.NUM_QUERIES):
    per, bnds = proof.get("_per"), proof.get("_bnds")
    if per is None or bnds is None:
        return False, "missing public AIR schedule"
    pinned = tuple(v for (_r, _l, v) in bnds[-_CAP:])
    if pinned != tuple(int(d) % F.P for d in challenge_digest):
        return False, "challenge-digest boundary does not match the claimed value"
    return stark.verify(proof, _transitions(), bnds, periodic=per, max_degree=8,
                        num_queries=num_queries, backend=backend.ALGHASH2)
