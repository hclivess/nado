"""
alghash2 — a WIDE-SPONGE algebraic hash over Goldilocks, for the STARK-RECURSION layer (doc/zk-recursion.md).

The existing `alghash` is width-2 / capacity-1: a 64-bit digest ⇒ ~32-bit collision resistance. That is
sound enough as an in-VM convenience hash but NOT as the commitment hash of a proof we recursively verify (a
~2^32 Merkle collision would forge the inner proof). alghash2 fixes the digest width:

    width t = 12, RATE = 8, CAPACITY = 4   →  256-bit capacity ⇒ ~128-bit collision resistance.

Poseidon-style permutation: per round, add round constants, apply the x^7 S-box (7 is coprime to p-1, a
permutation of F_p) to all lanes (full rounds), then mix by a t×t **Cauchy MDS** matrix M[i][j] =
1/((i) − (t+j)) (Cauchy matrices with disjoint node sets are MDS ⇒ maximal diffusion + invertible). Constants
are nothing-up-my-sleeve (BLAKE2b of labels). A digest is the first CAPACITY=4 rate lanes = 4 field elements
(a 256-bit value); helpers pack/compare them as tuples so `merkle`/`transcript` can treat a digest opaquely.

ROUND COUNT. This hash's generic security is 128-bit (256-bit capacity ⇒ 2^128 collision). The round count
must ensure no ALGEBRAIC shortcut beats that: an all-full-round x^7 permutation has algebraic degree 7^ROUNDS,
and an interpolation/Gröbner inversion costs ~7^ROUNDS, so we need 7^ROUNDS ≥ 2^128 ⟹ ROUNDS ≥ 46
(128 / log2 7). ROUNDS = 54 (7^54 ≈ 2^151.6, a ~20% margin over the 46 minimum) keeps the algebraic attack
strictly above the 2^128 generic bound. (8 rounds — the old "demonstration" value — gave degree only
7^8 ≈ 2^22.5, i.e. this "128-bit" hash was interpolation-invertible at ~2^22.5: a forged inner-proof Merkle
tree in the recursion layer.) ROUNDS is a single source of truth consumed by the Python permute, the recursion
AIRs (hash-block anatomy: block size = next_pow2(ROUNDS+2), see fri_verify._B), and the native Rust
(native/alghash2 `R`, native/starkprove `HR` — REBUILD after changing this: cargo build --release).
"""
from hashing import blake2b_hash
from execnode.stark import field as F

WIDTH = 12
RATE = 8
CAPACITY = WIDTH - RATE          # 4 → 256-bit capacity
DIGEST = CAPACITY                # a digest is CAPACITY field elements
ALPHA = 7
ROUNDS = 54                      # see ROUND COUNT above: 7^54 ≈ 2^151.6 ≥ the 2^128 collision bound


def _c(*parts):
    return int(blake2b_hash(["alghash2", *[str(p) for p in parts]]), 16) % F.P


# round constants: ROUNDS × WIDTH
RC = [[_c("rc", r, i) for i in range(WIDTH)] for r in range(ROUNDS)]
# capacity IV lanes (domain-separate the sponge start)
IV = [_c("iv", i) for i in range(CAPACITY)]

# Cauchy MDS: nodes x_i = i (i=0..t-1), y_j = t+j (j=0..t-1); disjoint ⇒ every square submatrix is invertible.
_MDS = [[F.inv((i - (WIDTH + j)) % F.P) for j in range(WIDTH)] for i in range(WIDTH)]

# domain tags (disjoint hashing spaces), mirroring alghash's DOM_* but in the wide sponge
DOM_LEAF, DOM_NODE, DOM_ABSORB, DOM_CHAL, DOM_INDEX, DOM_GRIND = 1, 2, 3, 4, 5, 6
DOM_LEAF_EXT = 7                 # GF(p^2) Merkle leaf — see rleaf_ext / leaf_ext


def sbox(x):
    return F.pw(x, ALPHA)


def permute(state):
    """One width-12 permutation: ROUNDS × (add constants → x^7 all lanes → MDS mix). Native Rust when
    available (bit-identical), else pure Python."""
    nat = _try_native()
    if nat:
        lib, u64 = nat
        buf = (u64 * WIDTH)(*[int(x) % F.P for x in state])
        lib.permute12(buf)
        return [buf[i] for i in range(WIDTH)]
    s = list(state)
    for r in range(ROUNDS):
        s = [sbox(F.add(s[i], RC[r][i])) for i in range(WIDTH)]
        s = [sum(F.mul(_MDS[i][j], s[j]) for j in range(WIDTH)) % F.P for i in range(WIDTH)]
    return s


# ---- optional native (Rust) acceleration for the STARK-recursion hot path (doc/zk-recursion.md) ------
# Loaded from native/alghash2/target/release/libnado_alghash2.so if present; bit-identical to the Python
# below (Python hands it the SAME RC/IV/MDS at init), so proofs stay valid either way. Build:
#   cd native/alghash2 && cargo build --release
_NATIVE = None
def _try_native():
    global _NATIVE
    if _NATIVE is not None:
        return _NATIVE
    try:
        import ctypes, os
        from execnode.stark.native_guard import is_stale
        crate = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                             "native", "alghash2")
        so = os.path.join(crate, "target", "release", "libnado_alghash2.so")
        if is_stale(so, crate):                            # .so predates its sources (pulled without rebuild)
            raise OSError("native alghash2 .so is older than its sources — stale, using pure Python")
        lib = ctypes.CDLL(so)
        lib.init.argtypes = [ctypes.POINTER(ctypes.c_uint64)] * 3
        lib.hashn.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t, ctypes.POINTER(ctypes.c_uint64)]
        lib.permute12.argtypes = [ctypes.POINTER(ctypes.c_uint64)]
        try:                                          # grind / merkle_commit / rmerkle_commit are newer —
            lib.grind.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.c_uint64, ctypes.c_uint32]
            lib.grind.restype = ctypes.c_uint64       # tolerate an older .so that lacks them
            lib.merkle_commit.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t,
                                          ctypes.POINTER(ctypes.c_uint64)]
            lib.rmerkle_commit.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t,
                                           ctypes.POINTER(ctypes.c_uint64)]
            for _nm in ("merkle_commit_ext", "rmerkle_commit_ext"):
                getattr(lib, _nm).argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t,
                                              ctypes.c_size_t, ctypes.POINTER(ctypes.c_uint64)]
                getattr(lib, _nm).restype = ctypes.c_int64
        except Exception:
            pass
        u64 = ctypes.c_uint64
        rc = (u64 * (ROUNDS * WIDTH))(*[RC[r][i] for r in range(ROUNDS) for i in range(WIDTH)])
        iv = (u64 * CAPACITY)(*IV)
        mds = (u64 * (WIDTH * WIDTH))(*[_MDS[i][j] for i in range(WIDTH) for j in range(WIDTH)])
        lib.init(rc, iv, mds)
        # INTEROP SELF-TEST — a stale/incompatible .so (e.g. one built for a different ROUNDS) is loaded and
        # TRUSTED by every caller, so it would silently diverge from consensus. Before adopting the native lib,
        # verify its permutation reproduces the pure-Python one on a fixed vector; on ANY mismatch reject it and
        # keep the whole recursion layer on the bit-identical Python path. (Reference computed inline, NOT via
        # permute(), which would recurse through _try_native.) Mirrors nado_pq_native's ML-DSA interop guard.
        probe = [(7 * i + 1) % F.P for i in range(WIDTH)]
        ref = list(probe)
        for r in range(ROUNDS):
            t = [sbox(F.add(ref[i], RC[r][i])) for i in range(WIDTH)]
            ref = [sum(F.mul(_MDS[i][j], t[j]) for j in range(WIDTH)) % F.P for i in range(WIDTH)]
        buf = (u64 * WIDTH)(*probe)
        lib.permute12(buf)
        if [buf[i] for i in range(WIDTH)] != ref:
            raise ValueError("native alghash2 disagrees with Python (stale/incompatible .so) — rejected")
        _NATIVE = (lib, u64)
    except Exception as e:
        # RUST-ONLY (see native_guard). The interop self-test above STAYS — it is the strongest guard in the
        # tree, and a .so that disagrees with Python on a fixed vector must never be adopted. What changed is
        # the consequence: adoption failing no longer silently hands the whole hash/Merkle layer to Python at
        # ~5.5x the cost, because that degradation is invisible (bit-identical output, no error, just slower).
        # A rejected or missing .so is now a startup failure that names itself.
        import os as _os
        from execnode.stark import native_guard
        if native_guard.allow_absent():
            _NATIVE = False
            return _NATIVE
        _crate = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
            "native", "alghash2")
        native_guard.require("alghash2", _os.path.join(_crate, "target", "release", "libnado_alghash2.so"),
                             _crate, reason="the sponge hash + whole-tree Merkle accelerator")
        raise native_guard.NativeMissing(
            f"native 'alghash2' is REQUIRED but could not be adopted: {e}. If that message says the library "
            f"DISAGREES WITH PYTHON on the fixed probe vector, do not work around it — the .so and this source "
            f"implement different permutations (usually a different ROUNDS), and trusting either one silently "
            f"would diverge from consensus. Rebuild with `cargo build --release` in native/alghash2.")
    return _NATIVE


def hashn(elements):
    """Sponge hash of a field-element sequence → a DIGEST-tuple (CAPACITY field elements).
    State = [0]*RATE + IV; absorb RATE lanes at a time (add into the rate, permute); squeeze the first
    CAPACITY rate lanes. Length is domain-separated by prepending the element count. Uses the native Rust
    permute when available (bit-identical), else pure Python."""
    els = [len(elements)] + [int(m) % F.P for m in elements]
    nat = _try_native()
    if nat:
        lib, u64 = nat
        buf = (u64 * len(els))(*els)
        out = (u64 * CAPACITY)()
        lib.hashn(buf, len(els), out)
        return tuple(out[i] for i in range(CAPACITY))
    state = [0] * RATE + list(IV)
    for off in range(0, len(els), RATE):
        chunk = els[off:off + RATE]
        for i, m in enumerate(chunk):
            state[i] = F.add(state[i], m)
        state = permute(state)
    return tuple(state[:CAPACITY])


def leaf(x):
    """Merkle leaf digest of one field element."""
    return hashn([DOM_LEAF, int(x) % F.P])


def node(a, b):
    """Merkle inner-node digest of two child digests (each a CAPACITY-tuple)."""
    return hashn([DOM_NODE, *a, *b])


def rnode(a, b):
    """RECURSION-tree 2-to-1 compression: ONE permutation over [a(4) | b(4) | IV(4)], digest = first CAPACITY
    lanes. Fixed-arity (a Merkle tree never mixes arities) so no length prefix is needed — which is what lets
    the recursion membership AIR spend exactly ONE permutation block per tree level (recursion.py). `a`,`b`
    are CAPACITY-tuples; RATE = 2·CAPACITY, so the two children exactly fill the rate."""
    state = [int(x) % F.P for x in a] + [int(x) % F.P for x in b] + list(IV)
    return tuple(permute(state)[:CAPACITY])


def rleaf(x):
    """RECURSION-tree leaf: rnode of (x-lane-broadcast, zero) — one permutation, digest = first CAPACITY.
    Domain-separated from an inner node by absorbing DOM_LEAF in lane 0."""
    a = (DOM_LEAF, int(x) % F.P, 0, 0)
    return tuple(permute([*a, 0, 0, 0, 0, *IV])[:CAPACITY])


def rleaf_ext(*limbs):
    """RECURSION-tree leaf for a GF(p^2) value (x0 + x1·X) — ONE permutation, exactly like rleaf.

    rleaf frames a base value as (DOM_LEAF, x, 0, 0) and leaves lanes 2..3 unused, so the second limb simply
    goes in lane 2 under its OWN domain tag. That matters for the recursion AIR: the obvious encoding for an
    extension leaf, node(leaf(x0), leaf(x1)), costs THREE permutations in-circuit (two leaves plus a
    compression) and needs the second leaf's digest carried as a constrained witness into the third block —
    tripling the leaf stage and adding a linkage the path machinery does not have. This costs one block, the
    same as a base leaf, so the in-circuit membership gadget changes only by pinning two lane values instead
    of one.

    DOM_LEAF_EXT (not DOM_LEAF) so an ext leaf and a base leaf are distinct frames even when x1 = 0 — a
    lifted base value and a genuine base value must not share a digest, or a prover could present one tree's
    opening against the other's commitment."""
    # The frame is (DOM_LEAF_EXT, limb0, limb1, ...) inside the FOUR-lane rleaf head, so degrees up to 3 fit
    # in exactly one permutation — the property that makes the in-circuit extension leaf cost the same as a
    # base one. A degree that no longer fits must fail loudly rather than silently truncate a limb.
    if len(limbs) > RATE // 2 - 1:
        raise ValueError(f"an extension leaf of {len(limbs)} limbs does not fit the {RATE // 2}-lane frame")
    a = [DOM_LEAF_EXT] + [int(x) % F.P for x in limbs]
    a += [0] * (RATE // 2 - len(a))
    return tuple(permute([*a, 0, 0, 0, 0, *IV])[:CAPACITY])


def leaf_ext(*limbs):
    """Sponge-backend extension leaf — the hashn analogue of rleaf_ext (no lane limit here)."""
    return hashn([DOM_LEAF_EXT] + [int(x) % F.P for x in limbs])


def rrow(values):
    """RECURSION-tree ROW leaf: one digest for a whole trace row (W field elements) — the row-commitment
    primitive that lets an in-circuit verifier authenticate an opened row with ONE Merkle path instead of W.
    Just hashn with DOM_LEAF prepended (⌈(W+2)/RATE⌉ permutations, multi-chunk absorption — the exact pattern
    the in-circuit sponge gadget replicates). Injective vs rleaf (its lane-0 is the element count ≥ 2, rleaf's
    is DOM_LEAF=1) and vs rnode (whose lane 0..3 is a digest) by frame structure."""
    return hashn([DOM_LEAF, *[int(v) % F.P for v in values]])


def grind(state, dom, bits):
    """Native proof-of-work: return the SMALLEST nonce whose hashn([dom, *state, nonce]) has `bits` leading
    zero bits of its 256-bit digest — the whole 2^bits loop run in Rust (the fold's dominant cost). Returns
    None if the native lib (or its grind export) is unavailable, so the caller falls back to the Python loop.
    Byte-identical to that loop: same PoW hash, same scan order (0,1,2,…), so the same nonce."""
    nat = _try_native()
    if not nat:
        return None
    lib, u64 = nat
    if not hasattr(lib, "grind"):
        return None
    buf = (u64 * CAPACITY)(*[int(x) % F.P for x in state])
    return int(lib.grind(buf, int(dom) % F.P, int(bits)))


def merkle_commit(values):
    """Native alghash2 Merkle tree build → (root, layers), bit-identical to merkle.commit over the ALGHASH2
    backend (leaf = hashn([DOM_LEAF, x]); inner = hashn([DOM_NODE, a.., b..])). `layers[0]` = leaf digests …
    `layers[-1]` = [root], the exact structure merkle.open_at walks. Returns None if the native lib (or its
    merkle_commit export) is unavailable or the length is not a power of two → caller uses the Python commit."""
    nat = _try_native()
    if not nat:
        return None
    lib, u64 = nat
    if not hasattr(lib, "merkle_commit"):
        return None
    n = len(values)
    if n < 1 or (n & (n - 1)):
        return None
    leaves = (u64 * n)(); leaves[:] = [int(v) % F.P for v in values]   # slice-assign > *-unpack for large n
    out = (u64 * ((2 * n - 1) * CAPACITY))()
    lib.merkle_commit(leaves, n, out)
    flat = out[:]                                                      # ONE bulk read of the native buffer
    digs = [tuple(flat[i * CAPACITY:(i + 1) * CAPACITY]) for i in range(2 * n - 1)]
    layers, start, ln = [], 0, n
    while True:
        layers.append(digs[start:start + ln])
        start += ln
        if ln == 1:
            break
        ln //= 2
    return layers[-1][0], layers


def rmerkle_commit(values):
    """Native RECURSION-backend (rleaf/rnode) whole-tree Merkle build → (root, layers), bit-identical to
    merkle.commit over backend.RECURSION (leaf = rleaf(x), inner = rnode(a,b) — one permutation per node). One
    FFI call replaces the ~2N per-node permute crossings that dominated recursion-backend proving. `layers[0]`
    = leaf digests … `layers[-1]` = [root], the structure merkle.open_at walks. Returns None if the native lib
    (or its rmerkle_commit export) is unavailable or the length is not a power of two → caller falls back."""
    nat = _try_native()
    if not nat:
        return None
    lib, u64 = nat
    if not hasattr(lib, "rmerkle_commit"):
        return None
    n = len(values)
    if n < 1 or (n & (n - 1)):
        return None
    leaves = (u64 * n)(); leaves[:] = [int(v) % F.P for v in values]   # slice-assign > *-unpack for large n
    out = (u64 * ((2 * n - 1) * CAPACITY))()
    lib.rmerkle_commit(leaves, n, out)
    flat = out[:]                                                      # ONE bulk read of the native buffer
    digs = [tuple(flat[i * CAPACITY:(i + 1) * CAPACITY]) for i in range(2 * n - 1)]
    layers, start, ln = [], 0, n
    while True:
        layers.append(digs[start:start + ln])
        start += ln
        if ln == 1:
            break
        ln //= 2
    return layers[-1][0], layers



def _commit_ext_native(limb_tuples, symbol):
    """Native whole-tree Merkle build over EXTENSION leaves → (root, layers), bit-identical to
    merkle.commit_digests over [leaf_ext(*v)] / [rleaf_ext(*v)].

    This is the extension counterpart of merkle_commit / rmerkle_commit, and it exists because it was
    MISSING: FRI commits an extension leaf per element on every layer once folding starts, and without a
    native build every one of those n + (n-1) permutations ran in a Python loop. That is the dominant cost of
    an extension proof and it lands on the settlement fold — the very thing the extension migration exists to
    make sound. Returns None (caller falls back to Python) when the lib, the export, the degree or the length
    is unusable; never a partial answer."""
    nat = _try_native()
    if not nat:
        return None
    lib, u64 = nat
    if not hasattr(lib, symbol):
        return None
    n = len(limb_tuples)
    if n < 1 or (n & (n - 1)):
        return None
    d = len(limb_tuples[0]) if n else 0
    if d < 1 or any(len(t) != d for t in limb_tuples):
        return None
    flat = (u64 * (n * d))()
    flat[:] = [int(x) % F.P for t in limb_tuples for x in t]
    out = (u64 * ((2 * n - 1) * CAPACITY))()
    if int(getattr(lib, symbol)(flat, n, d, out)) != 0:
        return None                      # the lib REFUSED this degree — do not guess, fall back
    buf = out[:]
    digs = [tuple(buf[i * CAPACITY:(i + 1) * CAPACITY]) for i in range(2 * n - 1)]
    layers, start, ln = [], 0, n
    while True:
        layers.append(digs[start:start + ln])
        start += ln
        if ln == 1:
            break
        ln //= 2
    return layers[-1][0], layers


def merkle_commit_ext(limb_tuples):
    """Sponge-backend (ALGHASH2) extension-leaf tree."""
    return _commit_ext_native(limb_tuples, "merkle_commit_ext")


def rmerkle_commit_ext(limb_tuples):
    """RECURSION-backend (rleaf_ext/rnode) extension-leaf tree."""
    return _commit_ext_native(limb_tuples, "rmerkle_commit_ext")


def to_int(digest):
    """Pack a DIGEST-tuple into one integer (for transcript folding / hex display)."""
    acc = 0
    for e in digest:
        acc = (acc << 64) | (int(e) % F.P)
    return acc


def eq(a, b):
    return tuple(int(x) % F.P for x in a) == tuple(int(x) % F.P for x in b)
