"""ctypes binding for native/attest (libnado_attest.so) — doc/device-attestation.md.

verify(att, cdj, challenge, now_unix, roots=None, rp_ids=None) -> dict
  {"ok", "fmt", "aaguid", "cred_id", "reason", "chain", "security_level"}
Roots default to the protocol's pinned vendor roots (protocol_roots/*.pem, filtered to
protocol.DEVICE_ATTEST_ROOT_FINGERPRINTS so a stray file can never widen the set); rp_ids default to
protocol.DEVICE_ATTEST_RP_IDS. There is NO Python fallback: consensus verification without the kernel is a
hard failure (the Rust-only policy), and a missing/stale .so is reported as such.
"""
import base64
import ctypes
import hashlib
import json
import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CRATE = os.path.join(_REPO, "native", "attest")
_SO = os.path.join(_CRATE, "target", "release", "libnado_attest.so")
_lib = None
_roots_blob = None


class AttestKernelUnavailable(RuntimeError):
    pass


def _load():
    global _lib
    if _lib is not None:
        return _lib
    if not os.path.exists(_SO):
        raise AttestKernelUnavailable(f"{_SO} missing — cd native/attest && cargo build --release")
    from execnode.stark.native_guard import is_stale
    if is_stale(_SO, _CRATE):
        raise AttestKernelUnavailable(f"{_SO} is older than its sources — rebuild native/attest")
    lib = ctypes.CDLL(_SO)
    lib.nado_attest_verify.restype = ctypes.c_int64
    lib.nado_attest_verify.argtypes = [
        ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t,
        ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_int64, ctypes.c_char_p, ctypes.c_size_t]
    _lib = lib
    return lib


def pinned_roots_der():
    """DER bytes of every protocol_roots/*.pem whose SHA-256 is pinned in protocol — the pinned set is the
    protocol constant; the files are only its carrier."""
    import protocol as P
    out = []
    d = os.path.join(_REPO, "protocol_roots")
    for name in sorted(os.listdir(d)):
        if not name.endswith(".pem"):
            continue
        pem = open(os.path.join(d, name)).read()
        b64 = "".join(l.strip() for l in pem.splitlines() if l and not l.startswith("-----"))
        der = base64.b64decode(b64)
        if hashlib.sha256(der).hexdigest() in P.DEVICE_ATTEST_ROOT_FINGERPRINTS:
            out.append(der)
    # FIDO2 security-key roots (protocol_roots/fido_mds_roots.json), filtered by the pinned fingerprint set
    import json as _json
    with open(os.path.join(d, "fido_mds_roots.json")) as f:
        for r in _json.load(f)["roots"]:
            der = base64.b64decode(r["der_b64"])
            if hashlib.sha256(der).hexdigest() in P.DEVICE_ATTEST_FIDO_ROOT_FINGERPRINTS:
                out.append(der)
    return out


def _pack_roots(roots):
    return b"".join(len(r).to_bytes(4, "big") + r for r in roots)


def verify(att: bytes, cdj: bytes, challenge: bytes, now_unix: int, roots=None, rp_ids=None) -> dict:
    lib = _load()
    global _roots_blob
    if roots is None:
        if _roots_blob is None:
            _roots_blob = _pack_roots(pinned_roots_der())
        blob = _roots_blob
    else:
        blob = _pack_roots(roots)
    if rp_ids is None:
        import protocol as P
        rp_ids = list(getattr(P, "DEVICE_ATTEST_RP_IDS", ()))
    rp = ("\0".join(rp_ids)).encode() + b"\0"
    out = ctypes.create_string_buffer(65536)
    n = lib.nado_attest_verify(att, len(att), cdj, len(cdj), challenge, len(challenge), blob, len(blob), rp,
                               int(now_unix), out, len(out))
    if n < 0:
        raise AttestKernelUnavailable("kernel returned an error")
    return json.loads(out.raw[:n].decode("utf-8"))
