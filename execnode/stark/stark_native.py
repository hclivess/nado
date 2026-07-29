"""
Python binding for the holistic native prover (native/starkprove) — the PERSISTENT LDE ARENA.

Step 1: keep low-degree-extension columns in Rust across the prove instead of materializing each as a Python
list (the recursion memory wall, see native/starkprove/src/lib.rs). This module is a thin ctypes wrapper; it
falls back to unavailable() if the .so isn't built, so nothing depends on it being present. BIT-IDENTICAL to
stark._coset_evaluate(F.interpolate(col), N, OFF) — guarded field-for-field by tests/test_starkprove.py.

Native-only (std cdylib); the browser keeps the per-kernel wasm path. Opt-in until the whole prove pipeline
(Merkle-from-arena, compose-from-arena, FRI, openings) is built + validated on top of this arena.
"""
import ctypes
import os
import threading

_P = 0xFFFFFFFF00000001
_LIB = None
_state = None            # None = not tried, True = loaded, False = unavailable
_LOCK = threading.Lock()  # the arena is a single global in Rust — one prove at a time


def _candidates():
    env = os.environ.get("NADO_STARKPROVE_LIB")
    if env:
        yield env
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(os.path.dirname(here))          # execnode/stark -> repo root
    base = os.path.join(repo, "native", "starkprove", "target", "release")
    for name in ("libnado_starkprove.so", "libnado_starkprove.dylib", "nado_starkprove.dll"):
        yield os.path.join(base, name)


def available():
    """True if the native arena lib loaded (cached)."""
    global _LIB, _state
    if _state is not None:
        return _state
    from execnode.stark.native_guard import is_stale
    for path in _candidates():
        if path and os.path.exists(path):
            if is_stale(path, os.path.dirname(os.path.dirname(os.path.dirname(path)))):
                continue                                   # .so older than its sources (pulled without rebuild)
            try:
                lib = ctypes.CDLL(path)
                lib.sp_reset.argtypes = [ctypes.c_size_t, ctypes.c_size_t, ctypes.c_uint64]
                lib.sp_lde_column.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                lib.sp_lde_column.restype = ctypes.c_int64
                lib.sp_num_cols.restype = ctypes.c_int64
                lib.sp_read.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
                lib.sp_read.restype = ctypes.c_uint64
                lib.sp_init.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
                lib.sp_commit_col.argtypes = [ctypes.c_size_t, ctypes.c_void_p, ctypes.c_uint32]
                lib.sp_commit_col.restype = ctypes.c_int64
                lib.sp_open.argtypes = [ctypes.c_size_t, ctypes.c_size_t, ctypes.c_void_p]
                lib.sp_open.restype = ctypes.c_int64
                lib.sp_compose.argtypes = [
                    ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                    ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t,
                    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p,
                    ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_uint64, ctypes.c_void_p]
                lib.sp_compose.restype = ctypes.c_int64
                lib.sp_col_len.argtypes = [ctypes.c_size_t]
                lib.sp_col_len.restype = ctypes.c_int64
                lib.sp_fold.argtypes = [ctypes.c_size_t, ctypes.c_uint64, ctypes.c_uint64]
                lib.sp_fold.restype = ctypes.c_int64
                # GF(p^2): an extension column is TWO arena columns (lo, hi); both entry points return the
                # LO id and always retain HI at lo+1. Bound with getattr so an older .so (built before the
                # extension port) simply reports unavailable instead of raising at load.
                if hasattr(lib, "sp_fold_ext"):
                    lib.sp_fold_ext.argtypes = [ctypes.c_size_t, ctypes.c_size_t, ctypes.c_uint64,
                                                ctypes.c_uint64, ctypes.c_uint64]
                    lib.sp_fold_ext.restype = ctypes.c_int64
                if hasattr(lib, "sp_compose_ext"):
                    lib.sp_compose_ext.argtypes = [
                        ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                        ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                        ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_void_p,
                        ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p,
                        ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_uint64,
                        ctypes.c_void_p, ctypes.c_void_p]
                    lib.sp_compose_ext.restype = ctypes.c_int64
                lib.sp_load_col.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
                lib.sp_load_col.restype = ctypes.c_int64
                lib.sp_commit_rows.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
                lib.sp_commit_rows.restype = ctypes.c_int64
                _init_hash(lib)
                _LIB, _state = lib, True
                return True
            except Exception:
                continue
    _state = False
    return False


_CAP = 4


def _init_hash(lib):
    """Install the alghash2 round constants / IV / MDS — the SAME nothing-up-my-sleeve values Python hands to
    native/alghash2 — so the arena's Merkle permute is byte-identical to alghash2.py."""
    from execnode.stark import alghash2 as A
    rc = (ctypes.c_uint64 * (A.ROUNDS * A.WIDTH))(*[A.RC[r][i] for r in range(A.ROUNDS) for i in range(A.WIDTH)])
    iv = (ctypes.c_uint64 * A.CAPACITY)(*A.IV)
    mds = (ctypes.c_uint64 * (A.WIDTH * A.WIDTH))(*[A._MDS[i][j] for i in range(A.WIDTH) for j in range(A.WIDTH)])
    lib.sp_init(ctypes.cast(rc, ctypes.c_void_p), ctypes.cast(iv, ctypes.c_void_p), ctypes.cast(mds, ctypes.c_void_p))


def reset(T, N, offset):
    """Begin a proof arena of geometry (T, N, offset). Clears any retained columns."""
    _LIB.sp_reset(int(T), int(N), int(offset) % _P)


def grind(state, dom, bits):
    """PARALLEL transcript proof-of-work (sp_grind): the whole nonce scan across all cores, returning the SAME
    smallest valid nonce as the serial scan (deterministic round-minimum), so proofs stay byte-identical.
    Returns None when the lib (or the export) is unavailable — callers fall back to the serial native/Python
    grind. NADO_NATIVE_THREADS caps the fan-out."""
    if not available() or not hasattr(_LIB, "sp_grind"):
        return None
    _LIB.sp_grind.restype = ctypes.c_uint64
    buf = (ctypes.c_uint64 * 4)(*[int(x) % _P for x in state])
    n = int(_LIB.sp_grind(ctypes.cast(buf, ctypes.c_void_p), ctypes.c_uint64(int(dom) % _P),
                          ctypes.c_uint32(int(bits))))
    return None if n == (1 << 64) - 1 else n


def lde_column(col_values, N, want_out=True):
    """Compute + RETAIN the LDE of one trace column (T values on the size-T domain). Returns (col_id, lde_list)
    where lde_list is the N-length result if want_out else None. Bit-identical to
    stark._coset_evaluate(F.interpolate(col_values), N, OFF)."""
    T = len(col_values)
    inbuf = (ctypes.c_uint64 * T)(*[int(v) % _P for v in col_values])
    outbuf = (ctypes.c_uint64 * N)() if want_out else None
    out_ptr = ctypes.cast(outbuf, ctypes.c_void_p) if want_out else None
    col_id = _LIB.sp_lde_column(ctypes.cast(inbuf, ctypes.c_void_p), out_ptr)
    if col_id < 0:
        raise RuntimeError("sp_lde_column failed (arena not reset?)")
    return col_id, (list(outbuf) if want_out else None)


def commit_col(col_id, hash_mode=0):
    """Merkle-commit a retained LDE column from the arena — no Python round-trip of the column. `hash_mode`
    0 = RECURSION (rleaf/rnode), 1 = ALGHASH2 (hashn leaf/node, the default backend). Returns (tree_id, root)
    with root a CAPACITY-tuple. Bit-identical to merkle.commit(col_lde[col_id], b)."""
    root = (ctypes.c_uint64 * _CAP)()
    tid = _LIB.sp_commit_col(int(col_id), ctypes.cast(root, ctypes.c_void_p), int(hash_mode))
    if tid < 0:
        raise RuntimeError("sp_commit_col failed")
    return tid, tuple(root)


def commit_rows(col_ids):
    """Row-commit a group of retained columns into ONE tree (leaf = rrow of the row across the group). Returns
    (tree_id, root). Bit-identical to stark._row_tree(group, N)."""
    n = len(col_ids)
    ids = (ctypes.c_size_t * n)(*[int(c) for c in col_ids])
    root = (ctypes.c_uint64 * _CAP)()
    tid = _LIB.sp_commit_rows(ctypes.cast(ids, ctypes.c_void_p), n, ctypes.cast(root, ctypes.c_void_p))
    if tid < 0:
        raise RuntimeError("sp_commit_rows failed")
    return tid, tuple(root)


def open_at(tree_id, pos, path_len):
    """Authentication path for leaf `pos` of a retained tree — a list of `path_len` CAPACITY-tuples, bottom-up.
    Bit-identical to merkle.open_at(layers, pos)."""
    buf = (ctypes.c_uint64 * (path_len * _CAP))()
    got = _LIB.sp_open(int(tree_id), int(pos), ctypes.cast(buf, ctypes.c_void_p))
    if got < 0:
        raise RuntimeError("sp_open failed")
    flat = list(buf)
    return [tuple(flat[i * _CAP:(i + 1) * _CAP]) for i in range(int(got))]


def compose(prog, boundaries, alphas, chals, T, N, blowup, want_out=True):
    """Composition polynomial from the arena (step 3). The arena must already hold the W trace/aux columns
    (ids 0..W) then the `nper` periodic-LDE columns (ids W..W+nper), added via lde_column in that order. Reads
    them + computes invZ/boundary-denominators/domain in Rust; retains cp as a new arena column. Returns
    (cp_col_id, cp_list or None). Bit-identical to stark._composition → air_ir.compose_native."""
    u32, u64 = ctypes.c_uint32, ctypes.c_uint64
    ops = prog["ops"]; consts = prog["consts"]; outputs = prog["outputs"]
    W, nper, nchal = prog["W"], prog["P"], len(chals)
    n_ops, n_out, n_bnd = len(ops), len(outputs), len(boundaries)
    ops_flat = (u32 * (n_ops * 3))()
    for i, (op, a, b) in enumerate(ops):
        ops_flat[i * 3] = op; ops_flat[i * 3 + 1] = a % (1 << 32); ops_flat[i * 3 + 2] = b % (1 << 32)
    def _u64(size, vals):
        m = max(1, size); a = (u64 * m)(); v = [int(x) % _P for x in vals]; a[:len(v)] = v[:m]; return a
    consts_a = _u64(len(consts), consts)
    out_idx = (u32 * max(1, n_out))(); out_idx[:n_out] = list(outputs)
    chals_a = _u64(nchal, chals)
    alphas_a = _u64(n_out + n_bnd, alphas)
    bcol = (u32 * max(1, n_bnd))(); bcol[:n_bnd] = [c for (_r, c, _v) in boundaries]
    bval = _u64(n_bnd, [v for (_r, _c, v) in boundaries])
    brow = _u64(n_bnd, [r for (r, _c, _v) in boundaries])
    outbuf = (u64 * N)() if want_out else None
    out_ptr = ctypes.cast(outbuf, ctypes.c_void_p) if want_out else None
    P = lambda x: ctypes.cast(x, ctypes.c_void_p)
    cid = _LIB.sp_compose(n_ops, P(ops_flat), len(consts), P(consts_a), n_out, P(out_idx),
                          W, nper, nchal, P(chals_a), P(alphas_a), n_bnd, P(bcol), P(bval), P(brow),
                          int(T), int(blowup), int(stark_OFF()), out_ptr)
    if cid < 0:
        raise RuntimeError(f"sp_compose failed (code {cid})")
    return cid, (list(outbuf) if want_out else None)


def ext_capable():
    """True when the loaded .so carries the extension entry points AND was compiled for the SAME degree the
    Python side is using.

    The symbols existing says nothing about which field they implement. A degree-mismatched arena does not
    fail — it composes a well-formed polynomial over the wrong field, and the only symptom is a
    "trace/composition mismatch" at verification with nothing pointing at the field. So the degree is part of
    the handshake, and a library that cannot answer is treated as pre-port."""
    if not (available() and hasattr(_LIB, "sp_fold_ext") and hasattr(_LIB, "sp_compose_ext")):
        return False
    if not hasattr(_LIB, "sp_ext_degree"):
        return False
    from execnode.stark import extf
    _LIB.sp_ext_degree.restype = ctypes.c_int64
    return int(_LIB.sp_ext_degree()) == extf.DEGREE


def compose_ext(prog, boundaries, alphas, chals, T, N, blowup, want_out=True):
    """GF(p^D) composition from the arena. `alphas` is one EXTENSION element per LOGICAL constraint then one
    per boundary — an extension-valued constraint occupies D SSA outputs but takes a SINGLE alpha, so the
    count is len(outputs) - len(ext_pairs)*(D-1) + len(boundaries), NOT len(outputs) + len(boundaries).
    Returns (cp_col_id, (limb_lists...) or None); the further limb columns follow at cp_col_id + 1 ...
    Bit-identical to air_ir.compose_python under extension alphas."""
    from execnode.stark import extf as ext2
    u32, u64 = ctypes.c_uint32, ctypes.c_uint64
    ops = prog["ops"]; consts = prog["consts"]; outputs = prog["outputs"]
    pairs = list(prog.get("ext_pairs") or ())
    W, nper, nchal = prog["W"], prog["P"], len(chals)
    n_ops, n_out, n_bnd, n_pairs = len(ops), len(outputs), len(boundaries), len(pairs)
    # an extension constraint occupies D outputs but takes ONE alpha, so each group adds D-1 EXTRA outputs.
    # (n_out - n_pairs was right only at D=2 and would silently over-count alphas at any other degree.)
    n_logical = n_out - n_pairs * (ext2.DEGREE - 1)
    if len(alphas) != n_logical + n_bnd:
        raise ValueError(f"compose_ext: expected {n_logical + n_bnd} alphas "
                         f"(one per LOGICAL constraint + one per boundary), got {len(alphas)}")
    ops_flat = (u32 * (n_ops * 3))()
    for i, (op, a, b) in enumerate(ops):
        ops_flat[i * 3] = op; ops_flat[i * 3 + 1] = a % (1 << 32); ops_flat[i * 3 + 2] = b % (1 << 32)
    def _u64(size, vals):
        m = max(1, size); a = (u64 * m)(); v = [int(x) % _P for x in vals]; a[:len(v)] = v[:m]; return a
    consts_a = _u64(len(consts), consts)
    out_idx = (u32 * max(1, n_out))(); out_idx[:n_out] = list(outputs)
    pair_idx = (u32 * max(1, n_pairs))(); pair_idx[:n_pairs] = list(pairs)
    # The CHALLENGES are extension pairs too, not just the alphas — the arena wants both flattened to limbs,
    # and prog["C"] already counts the flattened width (2 per logical challenge under ext_chal). Flattening
    # only the alphas left the challenges as tuples and int() rejected them, which stark.prove then swallowed
    # in its correctness-preserving fallback: the native path silently never ran and the whole point of the
    # port — keeping the W trace columns out of Python — was quietly lost.
    flat_chals = [limb for c in chals for limb in ext2.lift(c)]
    chals_a = _u64(len(flat_chals), flat_chals)
    nchal = len(flat_chals)
    flat_alphas = [limb for a in alphas for limb in ext2.lift(a)]
    alphas_a = _u64(len(flat_alphas), flat_alphas)
    bcol = (u32 * max(1, n_bnd))(); bcol[:n_bnd] = [c for (_r, c, _v) in boundaries]
    bval = _u64(n_bnd, [v for (_r, _c, v) in boundaries])
    brow = _u64(n_bnd, [r for (r, _c, _v) in boundaries])
    lo_buf = (u64 * N)() if want_out else None
    hi_buf = (u64 * N)() if want_out else None
    P = lambda x: ctypes.cast(x, ctypes.c_void_p)
    cid = _LIB.sp_compose_ext(n_ops, P(ops_flat), len(consts), P(consts_a), n_out, P(out_idx),
                              n_pairs, P(pair_idx), W, nper, nchal, P(chals_a), P(alphas_a),
                              n_bnd, P(bcol), P(bval), P(brow),
                              int(T), int(blowup), int(stark_OFF()),
                              P(lo_buf) if want_out else None, P(hi_buf) if want_out else None)
    if cid < 0:
        raise RuntimeError(f"sp_compose_ext failed (code {cid})")
    return cid, ((list(lo_buf), list(hi_buf)) if want_out else None)


def fold_ext(col_lo, col_hi, offset, alpha):
    """One GF(p^2) FRI fold of an extension column pair → a new half-length pair; returns the LO id (HI is
    lo+1). Bit-identical to fri._fold_ext."""
    from execnode.stark import extf as ext2
    a0, a1 = ext2.lift(alpha)
    cid = _LIB.sp_fold_ext(int(col_lo), int(col_hi), int(offset) % _P, int(a0) % _P, int(a1) % _P)
    if cid < 0:
        raise RuntimeError("sp_fold_ext failed")
    return cid


def stark_OFF():
    from execnode.stark import stark
    return stark.OFF % _P


def load_col(values):
    """Load a vector verbatim as a new arena column (no LDE); returns its id."""
    n = len(values)
    buf = (ctypes.c_uint64 * n)(*[int(v) % _P for v in values])
    cid = _LIB.sp_load_col(ctypes.cast(buf, ctypes.c_void_p), n)
    if cid < 0:
        raise RuntimeError("sp_load_col failed")
    return cid


def col_len(col):
    """Length of a retained column (FRI layers shrink by half each fold)."""
    n = _LIB.sp_col_len(int(col))
    if n < 0:
        raise RuntimeError("sp_col_len: bad column")
    return int(n)


def fold(col, offset, alpha):
    """One FRI fold of a retained column → a new (half-length) arena column; returns its id. Bit-identical to
    fri._fold(evals, F.domain(m, offset), alpha)."""
    cid = _LIB.sp_fold(int(col), int(offset) % _P, int(alpha) % _P)
    if cid < 0:
        raise RuntimeError("sp_fold failed")
    return cid


def fri_prove(cp_col, offset, blowup, num_queries, transcript, hash_mode=0):
    """FRI over a retained composition column (step 4): the heavy per-layer work — Merkle commit, fold, and
    query openings — runs in the arena; the TRANSCRIPT (a handful of absorbs/challenges/grind) stays in Python,
    identical to fri.prove. `hash_mode` selects the arena Merkle (0 RECURSION, 1 ALGHASH2) to match the
    transcript's backend. Produces the same proof dict, bit-identical to fri.prove(cp, offset, blowup, nq, t, b)."""
    from execnode.stark import fri
    t = transcript
    N = col_len(cp_col)
    roots, layers_meta = [], []          # layers_meta: (col_id, tree_id, size)
    cur, off = cp_col, int(offset) % _P
    while col_len(cur) > blowup:
        tree_id, root = commit_col(cur, hash_mode)
        roots.append(root); t.absorb(root)
        alpha = t.challenge()
        layers_meta.append((cur, tree_id, col_len(cur)))
        cur = fold(cur, off, alpha)
        off = (off * off) % _P
    final = [read(cur, i) for i in range(col_len(cur))]
    t.absorb("final", *final)
    pow_nonce = t.grind(fri.GRIND_BITS)
    queries = []
    for _ in range(num_queries):
        idx = t.challenge_index(N)
        steps, a = [], idx
        for (col_id, tree_id, size) in layers_meta:
            half = size // 2
            a %= size
            lo = a % half
            plen = size.bit_length() - 1
            steps.append({"lo": read(col_id, lo), "lo_path": open_at(tree_id, lo, plen),
                          "hi": read(col_id, lo + half), "hi_path": open_at(tree_id, lo + half, plen)})
            a = lo
        queries.append({"idx": idx, "steps": steps})
    return {"N": N, "offset": offset, "blowup": blowup, "roots": roots, "final": final,
            "pow": pow_nonce, "queries": queries, "ext": False, "ext0": False}


def prove(trace, transitions, boundaries, periodic=None, max_degree=2, num_queries=None, aux=None,
          aux_spec=None, row_commit=False, backend=None):
    """HOLISTIC prove (step 6) — reproduces stark.prove ENTIRELY through the arena for the two alghash2
    backends (RECURSION and the default ALGHASH2): trace/aux/periodic LDEs, Merkle commits (per-column, or ONE
    row tree per phase when row_commit — RECURSION only), the composition, FRI, and the openings all stay in
    Rust u64 buffers; only the transcript (a handful of hashes) and the two-phase aux BUILDER — an AIR-specific
    Python callback over small T-length columns — run in Python. Byte-identical proof dict to stark.prove;
    tests/test_starkprove.py gates it field-for-field end-to-end + verifies under stark.verify."""
    from execnode.stark import stark, air_ir, backend as _B, fri
    from execnode.stark.transcript import Transcript, DOMAIN_STARK
    periodic = periodic or []
    if num_queries is None:
        num_queries = stark.NUM_QUERIES
    b = backend or _B.RECURSION
    _ext = stark.ext_challenges_active(b)
    # The arena carries GF(p^2) now (sp_compose_ext / sp_fold_ext). It could not before, and refusing was
    # correct then — a proof built base-field under ext challenges is one stark.verify can never accept.
    # But refusing sent stark.prove down the FULL Python path, which materializes every one of the W LDE
    # columns as a Python list: the K->1 settlement fold OOM-killed at 20.8 GB resident on a ~15 GB budget.
    # The composition is two columns; the TRACE is the memory. So the refusal now applies only to a library
    # built before the extension port, where it remains the right answer.
    if _ext and not ext_capable():
        from execnode.stark import extf as _ef
        _d = int(_LIB.sp_ext_degree()) if (available() and hasattr(_LIB, "sp_ext_degree")) else None
        raise RuntimeError(f"the arena implements extension degree {_d} but this build needs "
                           f"{_ef.DEGREE} — use the Python path")
    hmode = 1 if getattr(b, "name", "") == "alghash2" else 0     # arena Merkle: 0 rleaf/rnode, 1 hashn
    T = len(trace); W = len(trace[0])
    blowup = stark._blowup(max_degree); N = blowup * T
    deg_bound = stark._next_pow2(max_degree) * T
    OFF = stark.OFF

    reset(T, N, OFF)
    for c in range(W):                                   # main trace columns → arena ids 0..W
        lde_column([trace[i][c] for i in range(T)], N, want_out=False)

    t = Transcript(DOMAIN_STARK, backend=b)
    if aux is not None:
        t.absorb("aux", str(aux))
    col_roots, row_roots, trees, row_trees = [], [], [], []
    if row_commit:
        tid, root = commit_rows(list(range(W)))
        row_roots.append(root); row_trees.append(tid); t.absorb(root)
    else:
        for c in range(W):
            tid, root = commit_col(c, hmode); col_roots.append(root); trees.append(tid); t.absorb(root)

    challenges = None
    Wtot = W
    if aux_spec is not None:                             # phase 2: challenges AFTER the main commit, then aux
        challenges = [(t.challenge_ext() if _ext else t.challenge())
                      for _ in range(aux_spec["num_challenges"])]
        aux_cols = aux_spec["build"](trace, challenges)
        if len(aux_cols) != aux_spec["num_aux"] or any(len(c) != T for c in aux_cols):
            raise ValueError("aux builder returned wrong geometry")
        aux_ids = [lde_column([v % _P for v in col], N, want_out=False)[0] for col in aux_cols]
        if row_commit:
            tid, root = commit_rows(aux_ids); row_roots.append(root); row_trees.append(tid); t.absorb(root)
        else:
            for cid in aux_ids:
                tid, root = commit_col(cid, hmode); col_roots.append(root); trees.append(tid); t.absorb(root)
        Wtot += aux_spec["num_aux"]

    for pc in periodic:                                  # periodic columns → arena ids Wtot..Wtot+nper
        lde_column(stark._per_expand(pc, T), N, want_out=False)

    prog = air_ir.build_program(transitions, Wtot, len(periodic),
                                0 if challenges is None else len(challenges), ext_chal=_ext)
    if _ext:
        # ONE alpha per LOGICAL constraint: an extension-valued constraint occupies two SSA outputs but takes
        # a single alpha, so this count is NOT len(outputs) + len(boundaries).
        from execnode.stark import extf as _ef
        _n_logical = len(prog["outputs"]) - len(prog.get("ext_pairs") or ()) * (_ef.DEGREE - 1)
        alphas = [t.challenge_ext() for _ in range(_n_logical + len(boundaries))]
        cp_col, _ = compose_ext(prog, boundaries, alphas, challenges or [], T, N, blowup, want_out=False)
    else:
        alphas = [t.challenge() for _ in range(len(transitions) + len(boundaries))]
        cp_col, _ = compose(prog, boundaries, alphas, challenges or [], T, N, blowup, want_out=False)

    fri_blowup = N // deg_bound
    # HYBRID FRI. The arena's sp_fold multiplies by a BASE-field alpha, so it cannot carry a GF(p^2) folding
    # challenge (fri.EXT_CHALLENGES). Rather than abandon the native prover wholesale — which is what made
    # every proof pure-Python and turned a 3-circuit fold into ~50 minutes — keep ALL the heavy native work
    # (per-column LDE, Merkle commits, and the composition polynomial, which are the O(N log N) stages) and
    # run only the FRI folding in Python by reading the composition column out of the arena. FRI's folds are
    # O(N) with tiny constants next to the NTTs and W-column Merkle trees above, so this recovers essentially
    # all of the speed while keeping the stronger commit-phase bound.
    # A RECURSION-backend proof is destined to be FOLDED by the base-field in-circuit AIRs, so it stays
    # base-field (stark.prove applies the same rule) and can use the fully native FRI. Only a non-recursion
    # proof carries the GF(p^2) challenge, and only that case reads the column out for the Python fold.
    if _ext:
        # cp is EXTENSION-valued, so it occupies the column pair (cp_col, cp_col+1) — read it back as limb
        # pairs. Only these two columns cross into Python; the W trace columns stay in the arena, which is
        # the whole point (see the guard above).
        _m = col_len(cp_col)
        cp_vals = [(read(cp_col, i), read(cp_col + 1, i)) for i in range(_m)]
        fri_proof = fri.prove(cp_vals, OFF, fri_blowup, num_queries, transcript=t, backend=b)
    else:
        fri_proof = fri_prove(cp_col, OFF, fri_blowup, num_queries, t, hmode)

    openings, plen = [], N.bit_length() - 1
    for q in fri_proof["queries"]:
        lo = q["idx"] % (N // 2)
        nxt = (lo + blowup) % N
        if row_commit:
            openings.append({"lo": lo,
                             "cur": [read(c, lo) for c in range(Wtot)],
                             "nxt": [read(c, nxt) for c in range(Wtot)],
                             "cur_paths": [open_at(tid, lo, plen) for tid in row_trees],
                             "nxt_paths": [open_at(tid, nxt, plen) for tid in row_trees]})
        else:
            cols = [{"cur": read(c, lo), "cur_path": open_at(trees[c], lo, plen),
                     "nxt": read(c, nxt), "nxt_path": open_at(trees[c], nxt, plen)} for c in range(Wtot)]
            openings.append({"lo": lo, "cols": cols})

    free()
    out = {"T": T, "W": Wtot, "N": N, "blowup": blowup, "deg_bound": deg_bound,
           "boundaries": boundaries, "fri": fri_proof, "openings": openings}
    if row_commit:
        out["row_roots"] = row_roots
    else:
        out["col_roots"] = col_roots
    return out


def read(col, pos):
    """One retained LDE value ARENA[col][pos]."""
    return _LIB.sp_read(int(col), int(pos))


def num_cols():
    return _LIB.sp_num_cols()


def free():
    _LIB.sp_free()
