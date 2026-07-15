"""
In-circuit `alghash2.hashn` sponge (doc/zk-recursion.md §5 step 9 — the O(1)-verify keystone). Every Fiat-Shamir
transcript operation (t_init/t_absorb/t_challenge/t_index) is a call to the variable-length wide-sponge hash
`alghash2.hashn`. Arithmetizing that hash is what lets the verifier's Fiat-Shamir work (fold challenges α, query
indices, grinding) move INSIDE a proof — so the schedule stops being O(T) verifier-materialized data and the
inner-proof roots collapse to one committed public input. This module is that atomic gadget: prove, in-circuit,
that a witness preimage's `hashn` equals a public digest, for an arbitrary-length input (multi-chunk sponge).

`hashn(elements)` = sponge over `[len(elements)] + elements`: state = [0]*RATE + IV; absorb RATE lanes at a time
(add into the rate, then permute); squeeze the first CAPACITY lanes. One permutation BLOCK per absorbed chunk
(R+1 rows, mirroring `_permute_snapshots`). Between blocks an ABSORB transition adds the next chunk into the rate
and carries the capacity; the first block's row 0 is the chunk added to [0]*RATE+IV; the last block's first
CAPACITY lanes are the digest. Bit-identical to `alghash2.hashn` by construction (same RC/IV/MDS, same order).
"""
from execnode.stark import alghash2 as a2, field as F, stark, backend
from execnode.stark.recursion import _permute_snapshots

_W, _R, _RATE, _CAP = a2.WIDTH, a2.ROUNDS, a2.RATE, a2.DIGEST
_BR = _R + 1
_M = _W                                  # absorb-chunk witness columns: _W .. _W+_RATE-1
_WTOT = _W + _RATE                        # 20

# periodic columns
_RCL = 0; _ACTR = _W; _FIRST = _W + 1; _ABS = _W + 2
_NPER = _W + 3


def _blocks(elements):
    """The sponge snapshots + per-block absorbed chunks + digest for hashn(elements)."""
    els = [len(elements)] + [int(m) % F.P for m in elements]
    state = [0] * _RATE + list(a2.IV)
    blocks, chunks = [], []
    for off in range(0, len(els), _RATE):
        chunk = els[off:off + _RATE]
        M = [0] * _RATE
        for i, m in enumerate(chunk):
            M[i] = int(m) % F.P
        for i in range(_RATE):
            state[i] = F.add(state[i], M[i])
        snaps = _permute_snapshots(state)
        blocks.append(snaps); chunks.append(M)
        state = list(snaps[_R])
    digest = tuple(blocks[-1][_R][:_CAP])
    return blocks, chunks, digest


def _schedule(elements):
    blocks, chunks, digest = _blocks(elements)
    nch = len(blocks)
    n_used = nch * _BR
    T = 1
    while T < n_used + 1:
        T <<= 1
    rows = [[0] * _WTOT for _ in range(T)]
    per = [[0] * T for _ in range(_NPER)]
    for b, snaps in enumerate(blocks):
        base = b * _BR
        for s in range(_BR):
            i = base + s
            for lane in range(_W):
                rows[i][lane] = int(snaps[s][lane]) % F.P
            if s == 0:
                for k in range(_RATE):
                    rows[i][_M + k] = int(chunks[b][k]) % F.P
            if s < _R:                                  # round row: RC + active
                for lane in range(_W):
                    per[_RCL + lane][i] = a2.RC[s][lane]
                per[_ACTR][i] = 1
        if b < nch - 1:                                 # absorb transition feeds the NEXT block's row 0
            per[_ABS][base + _R] = 1
    per[_FIRST][0] = 1
    last = n_used - 1
    for i in range(n_used, T):                          # inert pad (copy the digest row)
        rows[i] = list(rows[last])
    bnds = [(0, _M, len(elements) % F.P)]              # length prefix is public
    for lane in range(_CAP):
        bnds.append((last, lane, int(digest[lane]) % F.P))
    return rows, per, bnds, digest, T, last


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

    # ABSORB: next block's row 0 = (this block's last row) + next chunk in the rate, capacity carried.
    def abs_rate(i):
        return lambda c, n, p: F.mul(p[_ABS], F.sub(n[i], F.add(c[i], n[_M + i])))

    def abs_cap(i):
        return lambda c, n, p: F.mul(p[_ABS], F.sub(n[_RATE + i], c[_RATE + i]))
    for i in range(_RATE):
        cons.append(abs_rate(i))
    for i in range(_CAP):
        cons.append(abs_cap(i))

    # FIRST block row 0 = chunk-0 in the rate (over the zero state), IV in the capacity.
    def first_rate(i):
        return lambda c, n, p: F.mul(p[_FIRST], F.sub(c[i], c[_M + i]))

    def first_cap(i):
        return lambda c, n, p: F.mul(p[_FIRST], F.sub(c[_RATE + i], a2.IV[i]))
    for i in range(_RATE):
        cons.append(first_rate(i))
    for i in range(_CAP):
        cons.append(first_cap(i))
    return cons


def prove_hashn(elements, num_queries=stark.NUM_QUERIES):
    """Prove knowledge of `elements` (witness) whose `alghash2.hashn` equals the digest this commits publicly.
    Returns (proof, digest). The length prefix is pinned public; the elements stay witness."""
    rows, per, bnds, digest, T, _last = _schedule(elements)
    proof = stark.prove(rows, _transitions(), bnds, periodic=per, max_degree=8,
                        num_queries=num_queries, backend=backend.ALGHASH2)
    proof["_per"] = per; proof["_bnds"] = bnds
    return proof, digest


def verify_hashn(proof, digest, num_queries=stark.NUM_QUERIES):
    """Verify a hashn proof and that the pinned digest boundary equals `digest`."""
    per, bnds = proof.get("_per"), proof.get("_bnds")
    if per is None or bnds is None:
        return False, "missing public AIR schedule"
    pinned = tuple(v for (_r, _l, v) in bnds[-_CAP:])
    if pinned != tuple(int(d) % F.P for d in digest):
        return False, "digest boundary does not match the claimed digest"
    return stark.verify(proof, _transitions(), bnds, periodic=per, max_degree=8,
                        num_queries=num_queries, backend=backend.ALGHASH2)
