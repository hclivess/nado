"""
Optional native Goldilocks NTT for the Python prover — binds the SAME Rust as the browser's WASM prover
(wasm/goldilocks/src/lib.rs) as a shared library via ctypes (stdlib, no extra pip deps). It produces
bit-identical field values to field.py, so proofs stay valid; if the library isn't built, everything falls
back to pure Python. Build it with:  cargo build --release  (in wasm/goldilocks/), or scripts/install.sh --exec.
"""
import ctypes
import os

_P = 0xFFFFFFFF00000001
NMAX = 8192

_LIB = None
_BUF = None
_state = None   # None = not tried, True = loaded, False = unavailable


def _rou(n):
    return pow(7, (_P - 1) // n, _P)


def _inv(x):
    return pow(x % _P, _P - 2, _P)


def _candidates():
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
    n = len(vals)
    _BUF[:n] = [v % _P for v in vals]
    root = _inv(_rou(n)) if inverse else _rou(n)
    _LIB.ntt(n, root, 1 if inverse else 0, _inv(n) if inverse else 0)
    return list(_BUF[:n])


def coset_evaluate(coeffs, N, offset):
    _BUF[:N] = [(coeffs[i] % _P) if i < len(coeffs) else 0 for i in range(N)]
    _LIB.scale(N, offset % _P)
    _LIB.ntt(N, _rou(N), 0, 0)
    return list(_BUF[:N])
