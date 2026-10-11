"""ctypes binding for native/stwo_js (libnado_stwo_js.so): the node-side verifier of the Stwo join-split
(doc/stwo-migration.md section 5.1).

    verify(proof, root, nf, cm1, cm2, unshield, fee, dest) -> (ok: bool, reason: str)

  proof               the wire bytes (native/stwo_js/src/wire.rs: bincode of (claimed sums, StarkProof))
  root, nf, cm1, cm2  64-hex BLAKE2s digests, the 32 bytes in the circuit's u32-word little-endian order
  unshield            the amount leaving the pool to L1 (u64; 0 for a private transfer) — the circuit's public value
  fee                 u64
  dest                the unshield destination address ("" when unshield == 0); bound into the transcript as
                      aux = BLAKE2s-256(b"NADO/stwo-js/aux/v1\\0" || dest.encode()) (lib.rs aux_of)

The PcsConfig is NOT an argument: it is pinned in the crate (lib.rs NODE_*: log_blowup 2, 160 queries, 20 pow bits)
and a proof that carries any other config is refused. `config()` reports the pinned one.

LOADED LAZILY, ON THE FIRST VERIFY, NEVER AT IMPORT. A node whose build of this crate failed (no cargo, a compiler too
old) must keep running everything else, so importing this module, or any execnode module that imports it, touches no
library. Only a verify call can raise, and the only thing it raises is native_guard.NativeMissing (library absent,
stale against its sources, or of another ABI): a fact about this machine, never a verdict on the proof
(native_guard.NODE_LOCAL_ERRORS: a caller defers on it, it never rejects). There is no Python fallback, and
NADO_ALLOW_PYTHON_KERNELS does not change that (there is nothing to fall back to).

The crate is NOT in ops/self_update._CRATES: that list has no notion of an optional crate (every entry is built and
required), and whether the fleet builds this one is the operator's deployment decision.
"""
import ctypes
import os
import threading

from execnode.stark.native_guard import NativeMissing, is_stale

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CRATE_DIR = os.path.join(_REPO, "native", "stwo_js")
DEFAULT_SO = os.path.join(CRATE_DIR, "target", "release", "libnado_stwo_js.so")
ABI_VERSION = 1
_U64 = 1 << 64

# Result codes of nado_stwo_js_verify (lib.rs RC_*)
RC_OK, RC_BAD_ARGS, RC_MALFORMED, RC_REJECTED, RC_PANIC = 0, 1, 2, 3, 4

_lib = None
_lock = threading.Lock()


def lib_path():
    """$NADO_STWO_JS_LIB (tests, out-of-tree builds), else the crate's cargo release artifact."""
    return os.environ.get("NADO_STWO_JS_LIB") or DEFAULT_SO


def _load():
    global _lib
    if _lib is not None:
        return _lib
    with _lock:
        if _lib is not None:
            return _lib
        so = lib_path()
        if not os.path.exists(so):
            raise NativeMissing(f"native crate 'stwo_js' library {so} is missing: build it with "
                                f"`cargo build --release` in native/stwo_js (stable Rust; the verifier needs no nightly)")
        if so == DEFAULT_SO and is_stale(so, CRATE_DIR):
            raise NativeMissing(f"native crate 'stwo_js' library {so} is STALE (older than its sources): rebuild it")
        try:
            lib = ctypes.CDLL(so)
            lib.nado_stwo_js_abi_version.restype = ctypes.c_uint32
            lib.nado_stwo_js_abi_version.argtypes = []
            got = lib.nado_stwo_js_abi_version()
        except (OSError, AttributeError) as e:
            raise NativeMissing(f"native crate 'stwo_js' library {so} could not be loaded: {e}") from None
        if got != ABI_VERSION:
            raise NativeMissing(f"native crate 'stwo_js' library {so} has ABI {got}, this binding expects "
                                f"{ABI_VERSION}: rebuild it")
        lib.nado_stwo_js_verify.restype = ctypes.c_int32
        lib.nado_stwo_js_verify.argtypes = [
            ctypes.c_char_p, ctypes.c_size_t,                                   # proof
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,  # root, nf, cm1, cm2 (32 B each)
            ctypes.c_uint64, ctypes.c_uint64,                                   # unshield (public value), fee
            ctypes.c_char_p, ctypes.c_size_t,                                   # dest
            ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]  # reason buffer
        lib.nado_stwo_js_aux.restype = ctypes.c_int32
        lib.nado_stwo_js_aux.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p]
        lib.nado_stwo_js_config.restype = ctypes.c_int32
        lib.nado_stwo_js_config.argtypes = [ctypes.POINTER(ctypes.c_uint32)]
        _lib = lib
        return lib


def _digest(h):
    if not isinstance(h, str) or len(h) != 64:
        return None
    try:
        return bytes.fromhex(h)
    except ValueError:
        return None


def verify(proof: bytes, root: str, nf: str, cm1: str, cm2: str, unshield: int, fee: int, dest: str):
    """(True, "") or (False, "<short reason>"). Raises only NativeMissing (see the module docstring)."""
    lib = _load()
    if not isinstance(proof, (bytes, bytearray)) or not proof:
        return False, "proof is not bytes"
    ds = {}
    for name, h in (("root", root), ("nf", nf), ("cm1", cm1), ("cm2", cm2)):
        ds[name] = _digest(h)
        if ds[name] is None:
            return False, f"{name} is not a 64-hex digest"
    for name, v in (("unshield", unshield), ("fee", fee)):
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < _U64:
            return False, f"{name} is not a u64"
    if not isinstance(dest, str):
        return False, "dest is not a string"
    try:
        db = dest.encode("utf-8")
    except UnicodeEncodeError:
        return False, "dest is not UTF-8"
    reason = ctypes.create_string_buffer(512)
    rlen = ctypes.c_size_t(0)
    rc = lib.nado_stwo_js_verify(bytes(proof), len(proof), ds["root"], ds["nf"], ds["cm1"], ds["cm2"],
                                 unshield, fee, db, len(db), reason, len(reason), ctypes.byref(rlen))
    if rc == RC_OK:
        return True, ""
    msg = reason.raw[:rlen.value].decode("utf-8", "replace") or f"code {rc}"
    return False, msg


def aux_digest(dest: str) -> str:
    """The 32-byte aux the transcript binds for `dest`, as hex (cross-checks with the wallet's prover)."""
    lib = _load()
    db = dest.encode("utf-8")
    out = ctypes.create_string_buffer(32)
    if lib.nado_stwo_js_aux(db, len(db), out) != RC_OK:
        raise ValueError("aux")
    return out.raw.hex()


def config():
    """The pinned (log_blowup, n_queries, pow_bits) the library verifies against."""
    lib = _load()
    out = (ctypes.c_uint32 * 3)()
    lib.nado_stwo_js_config(out)
    return tuple(out)
