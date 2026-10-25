"""
nado_pqsig — ctypes binding of native/pqsig (libnado_pqsig.so): the user-selectable signature schemes beside ML-DSA-44.

One C ABI keyed by a scheme id (native/pqsig/src/lib.rs): 1 ML-DSA-65, 2 ML-DSA-87, 3 SLH-DSA-SHA2-128s, 4 FN-DSA-512.
signatures.py is the only importer; it maps scheme names to these ids, runs the known-answer and negative-vector self-test
before trusting the library, and never lets an exception out of verify(). Rust-only like every kernel since betanet-14
(execnode/stark/native_guard.py): a missing or STALE library raises here, it is never replaced by Python.

Lengths are passed to the Rust on every call and checked there too, so an attacker-chosen public key or signature of
the wrong size is an invalid signature, never an out-of-bounds read.
"""
import ctypes
import os

from execnode.stark import native_guard

_CRATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "native", "pqsig")
_SO = os.path.join(_CRATE, "target", "release", "libnado_pqsig.so")
if not native_guard.require("pqsig", _SO, _CRATE, "user-selectable signature schemes") and not os.path.exists(_SO):
    raise ImportError(f"native/pqsig is not built (missing {_SO})")
_lib = ctypes.CDLL(_SO)

_sz = ctypes.c_size_t
_p = ctypes.c_char_p
_lib.nado_pqs_sizes.argtypes = [ctypes.c_uint32, ctypes.POINTER(_sz), ctypes.POINTER(_sz), ctypes.POINTER(_sz)]
_lib.nado_pqs_keygen.argtypes = [ctypes.c_uint32, _p, _sz, _p, _sz, _p, _sz]
_lib.nado_pqs_sign.argtypes = [ctypes.c_uint32, _p, _sz, _p, _sz, _p, _sz, _p, _sz]
_lib.nado_pqs_verify.argtypes = [ctypes.c_uint32, _p, _sz, _p, _sz, _p, _sz]
for _f in (_lib.nado_pqs_sizes, _lib.nado_pqs_keygen, _lib.nado_pqs_sign, _lib.nado_pqs_verify):
    _f.restype = ctypes.c_int


def sizes(alg_id: int):
    """(public key, secret key, signature) byte lengths of scheme `alg_id`; ValueError for an unknown id."""
    pk, sk, sig = _sz(), _sz(), _sz()
    if _lib.nado_pqs_sizes(alg_id, ctypes.byref(pk), ctypes.byref(sk), ctypes.byref(sig)) != 0:
        raise ValueError(f"unknown signature scheme id {alg_id}")
    return pk.value, sk.value, sig.value


def keygen(alg_id: int, seed: bytes):
    """Deterministic (public, secret) of scheme `alg_id` from a 32-byte seed."""
    pkl, skl, _ = sizes(alg_id)
    pk, sk = ctypes.create_string_buffer(pkl), ctypes.create_string_buffer(skl)
    if _lib.nado_pqs_keygen(alg_id, seed, len(seed), pk, pkl, sk, skl) != 0:
        raise ValueError("nado_pqs_keygen refused the seed (it must be exactly 32 bytes)")
    return pk.raw, sk.raw


def sign(alg_id: int, secret: bytes, message: bytes, rnd: bytes) -> bytes:
    """Hedged signature (rnd = 32 fresh bytes) of `message` under the encoded secret key."""
    _, _, sigl = sizes(alg_id)
    sig = ctypes.create_string_buffer(sigl)
    if _lib.nado_pqs_sign(alg_id, secret, len(secret), message, len(message), rnd, len(rnd), sig, sigl) != 0:
        raise ValueError("nado_pqs_sign refused its input")
    return sig.raw


def verify(alg_id: int, public: bytes, message: bytes, signature: bytes) -> bool:
    """True iff valid. Wrong lengths, undecodable keys or signatures, and unknown ids are all simply False."""
    return _lib.nado_pqs_verify(alg_id, public, len(public), message, len(message), signature, len(signature)) == 0
