"""
Optional native Goldilocks NTT for the Python prover — binds the SAME Rust as the browser's WASM prover
(wasm/goldilocks/src/lib.rs) as a shared library via ctypes (stdlib, no extra pip deps). It produces
bit-identical field values to field.py, so proofs stay valid; if the library isn't built, everything falls
back to pure Python. Build it with:  cargo build --release  (in wasm/goldilocks/), or scripts/install.sh --exec.
"""
import ctypes
import os
import threading

_P = 0xFFFFFFFF00000001
# Must match the NATIVE build's NMAX in wasm/goldilocks/src/lib.rs (the non-wasm32 branch): the native .so is
# what this module binds, and callers gate native use on `n <= NMAX`. Raised from 8192 so the native u64 NTT
# covers STARK-RECURSION domains (fold/composition LDEs reach N ~ 10^5-10^6) instead of falling back to the
# pure-Python big-int NTT (the recursion memory/time wall). The browser WASM keeps 8192 (it never sees large N).
NMAX = 1 << 22

_LIB = None
_BUF = None
_state = None   # None = not tried, True = loaded, False = unavailable
# The Rust lib exposes ONE static scratch buffer (buf_ptr()); ntt()/coset_evaluate() write the inputs into it,
# call the lib (ctypes releases the GIL for the duration), then read the result back. Two threads doing that at
# once would clobber each other's buffer mid-NTT -> corrupted field values -> spurious "trace/composition
# mismatch". The exec node proves/verifies in worker threads, so serialize every native call. (The pure-Python
# fallback in field.py uses only locals and is already thread-safe.)
_LOCK = threading.Lock()


def _rou(n):
    """Primitive n-th root of unity (mirrors field.primitive_root_of_unity, n a power of two)."""
    return pow(7, (_P - 1) // n, _P)


def _inv(x):
    """x^-1 mod p (Fermat)."""
    return pow(x % _P, _P - 2, _P)


def _candidates():
    """Yield candidate shared-library paths: $NADO_GOLDILOCKS_LIB first, then the cargo release dir."""
    env = os.environ.get("NADO_GOLDILOCKS_LIB")
    if env:
        yield env
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(os.path.dirname(here))          # execnode/stark -> repo root
    base = os.path.join(repo, "wasm", "goldilocks", "target", "release")
    for name in ("libgoldilocks.so", "libgoldilocks.dylib", "goldilocks.dll"):
        yield os.path.join(base, name)


def available():
    """True if the native lib loaded (cached). Safe to call repeatedly."""
    global _LIB, _BUF, _state
    if _state is not None:
        return _state
    for path in _candidates():
        if path and os.path.exists(path):
            try:
                lib = ctypes.CDLL(path)
                lib.buf_ptr.restype = ctypes.c_void_p
                lib.ntt.argtypes = [ctypes.c_size_t, ctypes.c_uint64, ctypes.c_uint32, ctypes.c_uint64]
                lib.scale.argtypes = [ctypes.c_size_t, ctypes.c_uint64]
                buf = (ctypes.c_uint64 * NMAX).from_address(lib.buf_ptr())
                _LIB, _BUF, _state = lib, buf, True
                return True
            except Exception:
                continue
    _state = False
    return False


def ntt(vals, inverse=False):
    """Native NTT with the same contract (and bit-identical output) as field.ntt. Serialized on _LOCK — the
    Rust lib exposes a single static scratch buffer."""
    n = len(vals)
    root = _inv(_rou(n)) if inverse else _rou(n)
    with _LOCK:                                     # shared static buffer -> one native call at a time
        _BUF[:n] = [v % _P for v in vals]
        _LIB.ntt(n, root, 1 if inverse else 0, _inv(n) if inverse else 0)
        return list(_BUF[:n])


def coset_evaluate(coeffs, N, offset):
    """Native coset evaluation (zero-pad to N, scale coeff j by offset^j, forward NTT) — same contract as the
    pure-Python path in stark._coset_evaluate."""
    with _LOCK:                                     # shared static buffer -> one native call at a time
        _BUF[:N] = [(coeffs[i] % _P) if i < len(coeffs) else 0 for i in range(N)]
        _LIB.scale(N, offset % _P)
        _LIB.ntt(N, _rou(N), 0, 0)
        return list(_BUF[:N])
