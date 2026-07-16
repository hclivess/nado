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


def read(col, pos):
    """One retained LDE value ARENA[col][pos]."""
    return _LIB.sp_read(int(col), int(pos))


def num_cols():
    return _LIB.sp_num_cols()


def free():
    _LIB.sp_free()
