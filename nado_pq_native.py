"""
nado_pq_native — the optional NATIVE ML-DSA-44 backend for signatures.py's seam.

ctypes wrapper over native/mldsa44/libnado_mldsa44.so (the vendored pq-crystals reference
implementation + the FIPS 204 *internal*-mode shim — no context/domain wrapping, the exact
convention the chain and the browser sign in). Enable with:

    scripts/build_pq_native.sh                       # once, needs a C compiler
    NADO_PQ_NATIVE_MODULE=nado_pq_native             # in the node's environment

signatures.py adopts this module ONLY after its startup interop self-test cross-verifies it
against the pure-Python signer in both directions — a broken build falls back loudly to
pure-Python and can never split consensus. Verify goes from ~15 ms to ~0.1 ms (the chain's
main CPU cost: signature verification dominates block validation), which is the "native
ML-DSA" scaling item from doc/scaling-analysis.md #1 / doc/consensus-aggregation.md.

Raises ImportError when the .so is missing (signatures.py treats that as "not configured"
and stays pure-Python).
"""
import ctypes
import os

_SO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "native", "mldsa44", "libnado_mldsa44.so")
if not os.path.exists(_SO):
    raise ImportError(f"native ML-DSA backend not built — run scripts/build_pq_native.sh (missing {_SO})")
_lib = ctypes.CDLL(_SO)

# ML-DSA-44 (FIPS 204) sizes
SEED_BYTES = 32
RND_BYTES = 32
PK_BYTES = 1312
SK_BYTES = 2560
SIG_BYTES = 2420

_lib.nado_keygen_internal.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
_lib.nado_keygen_internal.restype = ctypes.c_int
_lib.nado_sign_internal.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_size_t),
                                    ctypes.c_char_p, ctypes.c_size_t,
                                    ctypes.c_char_p, ctypes.c_char_p]
_lib.nado_sign_internal.restype = ctypes.c_int
_lib.nado_verify_internal.argtypes = [ctypes.c_char_p, ctypes.c_size_t,
                                      ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p]
_lib.nado_verify_internal.restype = ctypes.c_int


def keygen_internal(seed: bytes):
    """FIPS 204 KeyGen_internal(seed) -> (public_key, secret_key), byte-identical to dilithium-py."""
    assert len(seed) == SEED_BYTES
    pk = ctypes.create_string_buffer(PK_BYTES)
    sk = ctypes.create_string_buffer(SK_BYTES)
    if _lib.nado_keygen_internal(pk, sk, seed) != 0:
        raise RuntimeError("nado_keygen_internal failed")
    return pk.raw, sk.raw


def sign_internal(secret: bytes, message: bytes, rnd: bytes) -> bytes:
    """FIPS 204 Sign_internal (empty prefix, hedged with the caller's 32-byte rnd)."""
    assert len(rnd) == RND_BYTES
    sig = ctypes.create_string_buffer(SIG_BYTES)
    siglen = ctypes.c_size_t(0)
    if _lib.nado_sign_internal(sig, ctypes.byref(siglen), message, len(message), rnd, secret) != 0:
        raise RuntimeError("nado_sign_internal failed")
    return sig.raw[:siglen.value]


def verify_internal(public: bytes, message: bytes, signature: bytes) -> bool:
    """FIPS 204 Verify_internal (empty prefix); True iff valid."""
    return _lib.nado_verify_internal(signature, len(signature), message, len(message), public) == 0
