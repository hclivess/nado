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
    for path in _candidates():
        if path and os.path.exists(path):
            try:
                lib = ctypes.CDLL(path)
                lib.sp_reset.argtypes = [ctypes.c_size_t, ctypes.c_size_t, ctypes.c_uint64]
                lib.sp_lde_column.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                lib.sp_lde_column.restype = ctypes.c_int64
                lib.sp_num_cols.restype = ctypes.c_int64
                lib.sp_read.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
                lib.sp_read.restype = ctypes.c_uint64
                lib.sp_init.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
                lib.sp_commit_col.argtypes = [ctypes.c_size_t, ctypes.c_void_p]
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
                lib.sp_load_col.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
                lib.sp_load_col.restype = ctypes.c_int64
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


def commit_col(col_id):
    """Merkle-commit a retained LDE column (RECURSION backend) from the arena — no Python round-trip of the
    column. Returns (tree_id, root) where root is a CAPACITY-tuple. Bit-identical to
    merkle.commit(col_lde[col_id], backend.RECURSION)."""
    root = (ctypes.c_uint64 * _CAP)()
    tid = _LIB.sp_commit_col(int(col_id), ctypes.cast(root, ctypes.c_void_p))
    if tid < 0:
        raise RuntimeError("sp_commit_col failed")
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


def fri_prove(cp_col, offset, blowup, num_queries, transcript):
    """FRI over a retained composition column (step 4): the heavy per-layer work — Merkle commit, fold, and
    query openings — runs in the arena; the TRANSCRIPT (a handful of absorbs/challenges/grind) stays in Python,
    identical to fri.prove. Produces the same proof dict fri.prove returns. Bit-identical to
    fri.prove(cp, offset, blowup, num_queries, transcript, backend.RECURSION)."""
    from execnode.stark import fri
    t = transcript
    N = col_len(cp_col)
    roots, layers_meta = [], []          # layers_meta: (col_id, tree_id, size)
    cur, off = cp_col, int(offset) % _P
    while col_len(cur) > blowup:
        tree_id, root = commit_col(cur)
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
            "pow": pow_nonce, "queries": queries}


def prove(trace, transitions, boundaries, periodic=None, max_degree=2, num_queries=None, aux=None):
    """HOLISTIC prove (step 6) — reproduces stark.prove single-phase COLUMN mode entirely through the arena:
    trace/periodic LDEs, per-column Merkle commits, composition, and FRI all stay in Rust; only the transcript
    (a handful of hashes) is Python. Backend is RECURSION (the arena's alghash2 hash). Bit-identical to
    stark.prove(trace, transitions, boundaries, periodic, max_degree, num_queries, backend=RECURSION).
    Returns the same proof dict. (row_commit + two-phase are added next.)"""
    from execnode.stark import stark, fri, air_ir, backend as _B
    from execnode.stark.transcript import Transcript
    periodic = periodic or []
    if num_queries is None:
        num_queries = stark.NUM_QUERIES
    T = len(trace); W = len(trace[0])
    blowup = stark._blowup(max_degree); N = blowup * T
    deg_bound = stark._next_pow2(max_degree) * T
    OFF = stark.OFF

    reset(T, N, OFF)
    # LDE the W trace columns (arena ids 0..W), then the periodic columns (ids W..W+nper) — the order sp_compose
    # expects. Nothing marshals back to Python.
    for c in range(W):
        lde_column([trace[i][c] for i in range(T)], N, want_out=False)
    for pc in periodic:
        lde_column(stark._per_expand(pc, T), N, want_out=False)

    t = Transcript("nado-stark", backend=_B.RECURSION)
    if aux is not None:
        t.absorb("aux", str(aux))
    col_roots, trees = [], []
    for c in range(W):
        tid, root = commit_col(c)
        col_roots.append(root); trees.append(tid); t.absorb(root)

    alphas = [t.challenge() for _ in range(len(transitions) + len(boundaries))]
    prog = air_ir.build_program(transitions, W, len(periodic), 0)
    cp_col, _ = compose(prog, boundaries, alphas, [], T, N, blowup, want_out=False)

    fri_blowup = N // deg_bound
    fri_proof = fri_prove(cp_col, OFF, fri_blowup, num_queries, t)

    openings = []
    for q in fri_proof["queries"]:
        lo = q["idx"] % (N // 2)
        nxt = (lo + blowup) % N
        plen = N.bit_length() - 1
        cols = [{"cur": read(c, lo), "cur_path": open_at(trees[c], lo, plen),
                 "nxt": read(c, nxt), "nxt_path": open_at(trees[c], nxt, plen)} for c in range(W)]
        openings.append({"lo": lo, "cols": cols})

    free()
    return {"T": T, "W": W, "N": N, "blowup": blowup, "deg_bound": deg_bound,
            "boundaries": boundaries, "fri": fri_proof, "openings": openings, "col_roots": col_roots}


def read(col, pos):
    """One retained LDE value ARENA[col][pos]."""
    return _LIB.sp_read(int(col), int(pos))


def num_cols():
    return _LIB.sp_num_cols()


def free():
    _LIB.sp_free()
