"""
IN-CIRCUIT slot_key derivation (fold-layer io binding, doc/zk-recursion.md §5c piece 2/3).

The sparse-tree POSITION of a storage slot is key = alghash.hashn([DOM_KVPOS, cid_limbs…, slot]) truncated to
`depth` bits (exec_state_bind.slot_key). For an O(1) settlement the verifier must NOT recompute that hash per io
entry — the replay must PROVE key = slot_key(cid, slot). This AIR arithmetizes the width-2 alghash sponge over the
fixed NELEM = 10 inputs (DOM_KVPOS + 8 cid limbs + slot), exposing the full digest AND its low-`depth` bit
decomposition (the merkle-update DIRs), so the position is bound to (cid, slot) with a cheap in-circuit hash. The
inputs are pinned as public boundaries — a caller ties them to the committed io (cid/slot columns) and the dir
bits to the merkle-update path (io_bind / root equality).

One absorb block = R alghash rounds; NELEM blocks chained (each absorbs the next input into the rate). Same
sponge the native slot_key runs, so the AIR digest equals alghash.hashn(...) exactly (cross-checked in tests).
"""
from execnode.stark import field as F, alghash, exec_state_bind as ESB, stark

R = alghash.ROUNDS                               # rounds per absorb block
NELEM = 10                                       # DOM_KVPOS + 8 cid limbs + slot
S0, S1 = 0, 1                                    # sponge state (rate, capacity)
NCOL = 2
MAX_DEGREE = alghash.ALPHA                       # 7


def _next_pow2(x):
    p = 1
    while p < x:
        p <<= 1
    return p


def _round(s0, s1, r):
    t0 = alghash.sbox(F.add(s0, alghash.RC[r % R][0]))
    t1 = alghash.sbox(F.add(s1, alghash.RC[r % R][1]))
    return F.add(F.mul(2, t0), t1), F.add(t0, F.mul(3, t1))


def elements(cid, slot):
    """The NELEM sponge inputs for (cid, slot) — the same sequence exec_state_bind.slot_key hashes."""
    return [ESB.DOM_KVPOS, *ESB.cid_limbs(cid), int(slot) % F.P]


def _T():
    return _next_pow2(NELEM * R + 1)


def _periodic_for(els, T):
    nextmsg = [0] * T
    last = [0] * T
    for b in range(NELEM):
        r_last = b * R + (R - 1)
        if r_last < T:
            last[r_last] = 1
            if b + 1 < NELEM:
                nextmsg[r_last] = els[b + 1] % F.P
    return [nextmsg, last]


# The alghash round constant depends on the round r = row % R. We encode RC as a public periodic pair, exactly
# like recursion.prove_preimage, so ONE transition covers every row.
def _rc_periodic(T):
    return [[alghash.RC[i % R][0] for i in range(T)], [alghash.RC[i % R][1] for i in range(T)]]


def _round_expr(s0, s1, rc0, rc1):
    t0 = alghash.sbox(F.add(s0, rc0))
    t1 = alghash.sbox(F.add(s1, rc1))
    return F.add(F.mul(2, t0), t1), F.add(t0, F.mul(3, t1))


def _all_transitions():
    # periodic layout: [NEXTMSG, LAST, RC0, RC1]
    NEXTMSG, LAST, RC0, RC1 = 0, 1, 2, 3
    def c_s0(c, n, p):
        r0, _r1 = _round_expr(c[S0], c[S1], p[RC0], p[RC1])
        want = F.add(r0, F.mul(p[LAST], p[NEXTMSG]))            # absorb next input on a block's last row
        return F.sub(n[S0], want)
    def c_s1(c, n, p):
        _r0, r1 = _round_expr(c[S0], c[S1], p[RC0], p[RC1])
        return F.sub(n[S1], r1)
    return [c_s0, c_s1]


def build_trace(cid, slot):
    """Run the sponge in the clear; return (trace, T, els, digest). Row 0 = [DOM_KVPOS(first input), IV]."""
    els = elements(cid, slot)
    T = _T()
    s0, s1 = F.add(0, els[0] % F.P), alghash.IV
    trace = []
    for r in range(T):
        trace.append([s0, s1])
        r0, r1 = _round(s0, s1, r % R)
        b, last = r // R, (r % R == R - 1)
        if last and b + 1 < NELEM:
            s0, s1 = F.add(r0, els[b + 1] % F.P), r1
        else:
            s0, s1 = r0, r1
    digest = trace[NELEM * R][S0] if NELEM * R < T else s0     # state s0 after the last block's permute
    return trace, T, els, digest


def _boundaries(T, els, digest):
    return [(0, S0, els[0] % F.P), (0, S1, alghash.IV), (NELEM * R, S0, int(digest) % F.P)]


def _full_periodic(els, T):
    nm, lst = _periodic_for(els, T)
    rc0, rc1 = _rc_periodic(T)
    return [nm, lst, rc0, rc1]


def prove(cid, slot, num_queries=stark.NUM_QUERIES, backend=None):
    """Prove key-preimage: the sponge over (cid, slot) yields `digest` (= alghash.hashn(elements)). Returns
    (proof, digest). The inputs (cid, slot) are pinned via the per-instance periodic + row-0 boundary."""
    from execnode.stark import backend as B
    b = backend or B.RECURSION
    trace, T, els, digest = build_trace(cid, slot)
    per = _full_periodic(els, T)
    proof = stark.prove(trace, _all_transitions(), _boundaries(T, els, digest), periodic=per,
                        max_degree=MAX_DEGREE, num_queries=num_queries, backend=b)
    proof["_digest"] = int(digest) % F.P
    proof["_els"] = [int(e) % F.P for e in els]
    return proof, int(digest) % F.P


def verify(proof, cid, slot, digest, num_queries=stark.NUM_QUERIES, backend=None):
    """Verify the derivation for the PUBLIC (cid, slot): rebuild the per-instance periodic + boundaries from
    (cid, slot) and the claimed digest, and check the STARK. A wrong (cid, slot) or digest fails the boundaries."""
    from execnode.stark import backend as B
    b = backend or B.RECURSION
    T = _T()
    els = elements(cid, slot)
    per = _full_periodic(els, T)
    ok, why = stark.verify(proof, _all_transitions(), _boundaries(T, els, int(digest) % F.P), periodic=per,
                           max_degree=MAX_DEGREE, num_queries=num_queries, backend=b)
    return ok, why
