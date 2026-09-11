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
    # HARDWARE-WALLET VENDOR KEYS ride in the same blob as tagged bare keys — the kernel's certificate walks skip
    # them (chain::cert_roots) and the trezor/ledger formats read only their own tag:
    #   0x01 || SEC1(65)  Trezor device-authentication ROOT public keys (P-256, one or two per model)
    #   0x02 || SEC1(65)  Ledger ISSUER public key (secp256k1) that certifies every device key at the factory
    for keys in getattr(P, "DEVICE_ATTEST_TREZOR_ROOTS", {}).values():
        for k in keys:
            out.append(b"\x01" + bytes.fromhex(k))
    for k in getattr(P, "DEVICE_ATTEST_LEDGER_ISSUER_KEYS", ()):
        out.append(b"\x02" + bytes.fromhex(k))
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


def _ek_roots_blob(height=None):
    """Pinned VENDOR endorsement roots (protocol_roots/ek/*.pem), filtered by protocol.DEVICE_ATTEST_EK_ROOTS.
    Separate from the WebAuthn root set on purpose: these answer "did a silicon vendor certify this chip",
    which is a different question from "did a vendor sign this attestation statement", and conflating the two
    would let an endorsement root validate a statement or vice versa."""
    import protocol as P
    # THE ROOT SET IS A FUNCTION OF HEIGHT, because adding a vendor root is a consensus change: a node
    # that has it accepts an enrolment a node that lacks it rejects. `height=None` means "every root we
    # currently pin" and is for ADVISORY callers only (the wallet pre-flight, the self-enrol probe) —
    # never for validation, which must ask what was in force at the block it is judging.
    pinned = (P.ek_roots_at(height) if height is not None and hasattr(P, "ek_roots_at")
              else frozenset(getattr(P, "DEVICE_ATTEST_EK_ROOTS", ()))
              | frozenset(getattr(P, "DEVICE_ATTEST_EK_ROOTS_V2", ())))
    out = []
    d = os.path.join(_REPO, "protocol_roots", "ek")
    if not pinned or not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if not name.endswith(".pem"):
            continue
        pem = open(os.path.join(d, name)).read()
        der = base64.b64decode("".join(l.strip() for l in pem.splitlines() if l and not l.startswith("-----")))
        if hashlib.sha256(der).hexdigest() in pinned:
            out.append(der)
    return out


def verify_ek(chain, now_unix: int, roots=None, height=None) -> dict:
    """Verify an endorsement certificate chain to a pinned vendor root. See native/attest/src/ek.rs — this is
    in the kernel because real vendor certificates are not strictly DER and python cannot read them."""
    lib = _load()
    lib.nado_ek_verify.restype = ctypes.c_int64
    lib.nado_ek_verify.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t,
                                   ctypes.c_int64, ctypes.c_char_p, ctypes.c_size_t]
    blob = _pack_roots([bytes(c) for c in chain])
    rblob = _pack_roots(_ek_roots_blob(height) if roots is None else roots)
    out = ctypes.create_string_buffer(4096)
    n = lib.nado_ek_verify(blob, len(blob), rblob, len(rblob), int(now_unix), out, len(out))
    if n < 0:
        raise AttestKernelUnavailable("kernel returned an error")
    verdict = json.loads(out.raw[:n].decode("utf-8"))
    # ONE NAME FOR THE ENDORSEMENT IDENTITY, FIXED HERE. The kernel emits `ek_identity`; every caller
    # wants `identity`, and four of them read `identity` off the raw verdict and raised KeyError on the
    # first real certificate — a failure that never appeared in any test, because the tests stubbed this
    # function and the stubs used the caller's spelling rather than the kernel's. A boundary that two
    # sides name differently needs the translation to live at the boundary, not in each caller.
    if "ek_identity" in verdict and "identity" not in verdict:
        verdict["identity"] = verdict["ek_identity"]
    return verdict


def ek_public_der(ek_cert_der: bytes) -> bytes:
    """The endorsement key's SubjectPublicKeyInfo, lifted with the kernel's lenient parser."""
    lib = _load()
    lib.nado_ek_public.restype = ctypes.c_int64
    lib.nado_ek_public.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t]
    out = ctypes.create_string_buffer(2048)
    n = lib.nado_ek_public(ek_cert_der, len(ek_cert_der), out, len(out))
    if n <= 0:
        raise ValueError("could not read the endorsement public key")
    return out.raw[:n]
