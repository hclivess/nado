"""ctypes binding for native/stwo_settle (libnado_stwo_settle.so): the node-side verifier of the gen-29 settlement's VM
proof (doc/stwo/g4-settlement-statement.md section 5; the crate's ffi.rs).

    verify(statement_text, proof_bytes) -> (ok: bool, reason: str)

  statement_text   vm::parse_statement's text, which the caller (execnode/settle_b2.py) builds itself from its replay of
                   the span: the programs from authenticated code leaves, the calls' args and context from the blocks, and
                   the io logs the replay checked. Never the prover's.
  proof_bytes      native/stwo_settle/src/wire.rs's encoding, the prover's.

The PcsConfig is the crate's node_config (128 bits), pinned there; a proof at any other config is refused. The
preprocessed commitment is pinned too (vm_air::PREPROCESSED_ROOT): the verifier needs no prover and builds on stable.

LOADED LAZILY, ON THE FIRST VERIFY, NEVER AT IMPORT, exactly as stwo_js_native: a node whose build of this crate failed
keeps running everything else. The only thing a verify raises is native_guard.NativeMissing (library absent, stale against
its sources, or of another ABI): a fact about this machine, never a verdict on a proof. There is no Python fallback.

The crate is OPTIONAL (ops/self_update._OPTIONAL_CRATES) until the settlement gate needs it: every node builds it on
update, nothing requires it yet.
"""
import ctypes
import os
import threading

from execnode.stark.native_guard import NativeMissing, is_stale

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CRATE_DIR = os.path.join(_REPO, "native", "stwo_settle")
DEFAULT_SO = os.path.join(CRATE_DIR, "target", "release", "libnado_stwo_settle.so")
ABI_VERSION = 1
RC_OK, RC_REFUSED, RC_BAD_ARGS = 0, 1, 2          # ffi.rs RC_*
_REASON_CAP = 1024

_lib = None
_lock = threading.Lock()


def lib_path():
    """$NADO_STWO_SETTLE_LIB (tests, out-of-tree builds), else the crate's cargo release artifact."""
    return os.environ.get("NADO_STWO_SETTLE_LIB") or DEFAULT_SO


def _load():
    global _lib
    if _lib is not None:
        return _lib
    with _lock:
        if _lib is not None:
            return _lib
        so = lib_path()
        if not os.path.exists(so):
            raise NativeMissing(f"native crate 'stwo_settle' library {so} is missing: build it with "
                                f"`cargo build --release` in native/stwo_settle (stable Rust; the verifier needs no nightly)")
        if so == DEFAULT_SO and is_stale(so, CRATE_DIR):
            raise NativeMissing(f"native crate 'stwo_settle' library {so} is STALE (older than its sources): rebuild it")
        try:
            lib = ctypes.CDLL(so)
            lib.nado_stwo_settle_abi.restype = ctypes.c_uint32
            lib.nado_stwo_settle_abi.argtypes = []
            got = lib.nado_stwo_settle_abi()
        except (OSError, AttributeError) as e:
            raise NativeMissing(f"native crate 'stwo_settle' library {so} could not be loaded: {e}") from None
        if got != ABI_VERSION:
            raise NativeMissing(f"native crate 'stwo_settle' library {so} has ABI {got}, this binding expects "
                                f"{ABI_VERSION}: rebuild it")
        lib.nado_stwo_settle_verify.restype = ctypes.c_int32
        lib.nado_stwo_settle_verify.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t,
                                                ctypes.c_char_p, ctypes.c_size_t]
        _lib = lib
        return lib


def ensure_loaded():
    """Load the library now or raise NativeMissing."""
    _load()


def verify(statement_text, proof_bytes):
    """(True, "") if `proof_bytes` proves `statement_text`, else (False, why). A malformed statement (the caller's own
    text) is a ValueError, not a verdict; a missing library is NativeMissing."""
    if not isinstance(statement_text, str) or not isinstance(proof_bytes, (bytes, bytearray)):
        raise ValueError("verify(statement text, proof bytes)")
    lib = _load()
    st = statement_text.encode()
    pb = bytes(proof_bytes)
    out = ctypes.create_string_buffer(_REASON_CAP)
    rc = lib.nado_stwo_settle_verify(st, len(st), pb, len(pb), out, _REASON_CAP)
    why = out.value.decode(errors="replace")
    if rc == RC_OK:
        return True, ""
    if rc == RC_REFUSED:
        return False, why or "refused"
    raise ValueError(f"stwo_settle verify: bad arguments ({why})")
