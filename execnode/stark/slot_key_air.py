"""
IN-CIRCUIT slot_key derivation (fold-layer io binding, doc/zk-recursion.md §5c piece 2/3) — ALGHASH2.

The sparse-tree POSITION of a storage slot is key = digest of alghash2.hashn([DOM_KVPOS, cid_limbs…, slot])
truncated to `depth` bits (exec_state_bind.slot_key). For an O(1) settlement the verifier must NOT recompute that
hash per io entry — the replay PROVES key = slot_key(cid, slot). Because the 7 sponge inputs fit ONE alghash2
chunk (RATE 8), the derivation is a SINGLE permutation, arithmetized by the recursion round AIR (recursion.py):
the absorbed init (row 0, encoding cid/slot) is pinned as boundaries, the digest lanes at row R are the position
hash. The verifier REBUILDS the init from (cid, slot) cheaply (no hashing) and pins it — verifier-authoritative —
so a wrong (cid, slot) or digest fails. 128-bit (matches the alghash2 state tree).
"""
from execnode.stark import field as F, alghash2 as A2, stark, exec_state_bind as ESB, backend as B
from execnode.stark.recursion import _round_transitions, _permute_snapshots, _next_pow2, _W, _R, _RATE

CAP = A2.CAPACITY
MAX_DEGREE = 8


def elements(cid, slot):
    return ESB.elements(cid, slot)


def _init(els):
    e = [len(els)] + [int(m) % F.P for m in els]
    if len(e) > _RATE:
        raise ValueError("slot_key_air: inputs exceed one alghash2 chunk")
    init = [0] * _RATE + list(A2.IV)
    for i, m in enumerate(e):
        init[i] = F.add(init[i], m)
    return init


def build_trace(cid, slot, pad_to=None):
    els = elements(cid, slot)
    init = _init(els)
    snaps = _permute_snapshots(init)                 # R+1 rows
    digest = tuple(snaps[_R][:CAP])
    rows = [list(s) for s in snaps]
    T = _next_pow2(len(rows))
    if pad_to:                                       # pad to a common length so it folds with other-AIR proofs
        T = max(T, int(pad_to))
    while len(rows) < T:
        rows.append(list(rows[-1]))
    return rows, T, init, digest


def _periodic(T):
    """RC schedule (per lane) + an active selector (1 on the R round rows, 0 on pad) — recursion.py's layout."""
    rc = [[A2.RC[i % _R][lane] if i < _R else 0 for i in range(T)] for lane in range(_W)]
    act = [1 if i < _R else 0 for i in range(T)]
    return rc + [act]


def _boundaries(init, digest, T):
    bnds = [(0, lane, int(init[lane]) % F.P) for lane in range(_W)]
    for lane in range(CAP):
        bnds.append((_R, lane, int(digest[lane]) % F.P))
    return bnds


def boundaries_for(cid, slot, digest, T):
    """Verifier-authoritative boundaries for (cid, slot) + a claimed digest — rebuilds the init cheaply (no hash)."""
    return _boundaries(_init(elements(cid, slot)), tuple(int(d) % F.P for d in digest), T)


def transitions():
    return _round_transitions()


def prove(cid, slot, num_queries=stark.NUM_QUERIES, backend=None, pad_to=None):
    b = backend or B.RECURSION
    rows, T, init, digest = build_trace(cid, slot, pad_to=pad_to)
    proof = stark.prove(rows, transitions(), _boundaries(init, digest, T), periodic=_periodic(T),
                        max_degree=MAX_DEGREE, num_queries=num_queries, backend=b)
    return proof, digest


def verify(proof, cid, slot, digest, num_queries=stark.NUM_QUERIES, backend=None):
    """Verify the derivation for PUBLIC (cid, slot): rebuild the init boundaries from (cid, slot) [cheap, no hash]
    + pin the claimed digest, and check the STARK. A wrong (cid, slot) or digest fails the boundaries."""
    try:
        b = backend or B.RECURSION
        T = proof["T"]
        bnds = boundaries_for(cid, slot, digest, T)
        return stark.verify(proof, transitions(), bnds, periodic=_periodic(T),
                            max_degree=MAX_DEGREE, num_queries=num_queries, backend=b)
    except Exception as e:
        return False, f"malformed slot_key proof: {e}"
