"""
Curve25519.py — POST-QUANTUM signatures (ML-DSA-44, FIPS 204 / Dilithium).

NOTE: the module NAME is kept only for import stability (transaction_ops, key_ops, the wallets and
the testnet harness all do `from Curve25519 import ...`); the algorithm is now **ML-DSA-44**, NOT
Curve25519/Ed25519.

BACKENDS (perf — "native ML-DSA is the biggest verification speed-up"):
  * The DEFAULT backend is `dilithium-py` — a PURE-PYTHON implementation, so there is no native
    dependency to compile (in keeping with the "runs on anything, even a 386 / a phone" goal, and
    cross-validated with the browser light-miner's `@noble/post-quantum`). It is correct but slow:
    signature verification dominates block validation, which is the chain's main CPU bottleneck.
  * An OPTIONAL NATIVE backend can be plugged in by operators who want 10-100x faster verify on a
    full node/validator, WITHOUT giving up the pure-Python default for phones. Set
    `NADO_PQ_NATIVE_MODULE=<importable.module>` to a module exposing FIPS 204 *internal* primitives
    (the `keygen_internal`/`sign_internal`/`verify_internal` byte contract below). The native backend
    is adopted ONLY if it passes a startup INTEROP SELF-TEST (cross-verify against the pure-Python
    signer in BOTH directions); on any mismatch or import error it falls back to pure-Python, so a
    misconfigured/incompatible native lib can never split consensus — it just doesn't accelerate.

INTEROP TRAP (why this is gated, not a blind swap): the chain (node + browser) signs with ML-DSA
**internal** Sign (FIPS 204 Sign_internal — NO context/domain wrapping). The STANDARD external APIs
of most native libs (e.g. liboqs/`oqs`) wrap a domain-separation context, producing signatures over
a DIFFERENT message that will NOT cross-verify with existing sigs or the browser. So a native
backend must expose the *internal* (no-ctx) functions, OR the whole stack (node + light-miner) must
migrate together to external+fixed-ctx ML-DSA. The self-test enforces interop either way.

Key model: the stored `private_key` is a 32-byte SEED (hex); the (public, secret) pair is
regenerated deterministically from it via ML-DSA KeyGen_internal(seed) (FIPS 204 §6.1). That keeps
key files tiny and makes import-by-seed possible (`from_private_key`). `public_key` is the full
1312-byte ML-DSA public key (hex). Signatures are ~2420 bytes.

Determinism note: a signature need NOT be byte-identical across implementations — consensus checks
`verify(sig, pk, msg) == True`, never `sig == recompute` (only the txid is recomputed, and that is a
blake2b over canonical_bytes, unchanged). So a browser `@noble/post-quantum` signer and this node
interoperate even though their signature bytes differ. The address derivation and txid hashing are
untouched, preserving browser/light-miner reproducibility.
"""
import importlib
import os
import secrets
import sys

from dilithium_py.ml_dsa import ML_DSA_44

from ops.address_ops import make_address


def unhex(hexed):
    return b"".fromhex(hexed)


# --- backend contract -----------------------------------------------------------------------------
# A backend implements three FIPS 204 *internal* primitives over raw bytes:
#   keygen_internal(seed: bytes)             -> (public_key: bytes, secret_key: bytes)
#   sign_internal(secret: bytes, msg, rnd)   -> signature: bytes      (rnd = 32-byte hedge)
#   verify_internal(public: bytes, msg, sig) -> bool
# These mirror dilithium-py's ML_DSA_44._*_internal exactly, so the pure-Python and any conforming
# native backend produce mutually-verifiable signatures (enforced by the interop self-test).

class _PurePyBackend:
    name = "dilithium-py (pure-Python)"

    @staticmethod
    def keygen_internal(seed):
        return ML_DSA_44._keygen_internal(seed)

    @staticmethod
    def sign_internal(secret, message, rnd):
        return ML_DSA_44._sign_internal(secret, message, rnd)

    @staticmethod
    def verify_internal(public, message, signature):
        return ML_DSA_44._verify_internal(public, message, signature)


class _NativeBackend:
    """Adapter around an operator-supplied native module named by NADO_PQ_NATIVE_MODULE. The module
    must provide `keygen_internal`, `sign_internal`, `verify_internal` with the byte contract above
    (FIPS 204 *internal*, no ctx wrapping). Kept deliberately thin so binding any fast lib that
    exposes the internal functions is a few lines."""

    def __init__(self, module):
        self.name = f"native:{module.__name__}"
        self._m = module

    def keygen_internal(self, seed):
        return self._m.keygen_internal(seed)

    def sign_internal(self, secret, message, rnd):
        return self._m.sign_internal(secret, message, rnd)

    def verify_internal(self, public, message, signature):
        return self._m.verify_internal(public, message, signature)


def _interop_ok(candidate) -> bool:
    """Adopt a native backend ONLY if it round-trips AND cross-verifies with the pure-Python signer
    in BOTH directions on a fixed vector. This guarantees the native lib uses the same (internal,
    no-ctx) convention as the browser + existing on-chain sigs, so swapping it in cannot fork
    consensus. Any exception or mismatch -> reject (stay pure-Python)."""
    try:
        seed = b"\x42" * 32
        msg = b"nado-pq-backend-interop-selftest"
        pub_p, sec_p = _PurePyBackend.keygen_internal(seed)
        pub_n, sec_n = candidate.keygen_internal(seed)
        if pub_n != pub_p or sec_n != sec_p:
            return False  # deterministic keygen must agree (addresses derive from the public key)
        rnd = b"\x07" * 32
        # native signs -> pure-Python verifies, and pure-Python signs -> native verifies
        if not _PurePyBackend.verify_internal(pub_p, msg, candidate.sign_internal(sec_p, msg, rnd)):
            return False
        if not candidate.verify_internal(pub_p, msg, _PurePyBackend.sign_internal(sec_p, msg, rnd)):
            return False
        return True
    except Exception:
        return False


def _select_backend():
    """Pick the signing backend at import time. Default = pure-Python. If NADO_PQ_NATIVE_MODULE names
    an importable module that PASSES the interop self-test, use it; otherwise fall back loudly to
    pure-Python (never silently trust an unverified native lib)."""
    mod_name = os.environ.get("NADO_PQ_NATIVE_MODULE", "").strip()
    if not mod_name:
        return _PurePyBackend()
    try:
        candidate = _NativeBackend(importlib.import_module(mod_name))
    except Exception as e:  # operator-supplied module: import must never crash the node
        sys.stderr.write(f"[PQ] native backend '{mod_name}' import failed ({e}); using pure-Python\n")
        return _PurePyBackend()
    if _interop_ok(candidate):
        sys.stderr.write(f"[PQ] native ML-DSA backend '{mod_name}' passed interop self-test; enabled\n")
        return candidate
    sys.stderr.write(
        f"[PQ] native backend '{mod_name}' FAILED interop self-test (likely ctx-wrapping mismatch); "
        f"refusing it and using pure-Python — see Curve25519.py INTEROP TRAP\n")
    return _PurePyBackend()


_BACKEND = _select_backend()


def _keypair_from_seed(seed: bytes):
    """Deterministic ML-DSA keygen from a 32-byte seed (FIPS 204 KeyGen_internal). Returns
    (public_key_bytes, secret_key_bytes)."""
    return _BACKEND.keygen_internal(seed)


def sign(private_key, message):
    seed = unhex(private_key)
    _public, secret = _keypair_from_seed(seed)
    # INTERNAL ML-DSA sign (FIPS 204 Sign_internal — NO ctx/domain wrapping) with a fresh 32-byte
    # hedge. This is the exact convention `@noble/post-quantum` (the browser light-miner) uses by
    # default, CROSS-VALIDATED both ways (node sig -> noble verify == true, noble sig -> node verify
    # == true). The signature is hedged/randomized and need NOT be byte-reproducible across impls
    # (consensus checks verify()==True, never sig equality).
    return _BACKEND.sign_internal(secret, message, secrets.token_bytes(32)).hex()


def verify(signed, public_key, message):
    # return False on ANY failure instead of raising: callers use `assert verify(...)` /
    # `if verify(...)`, and a raising verify could turn a rejection into an unhandled error or be
    # mis-refactored into a silent accept. INTERNAL verify to match the signer above + the browser.
    try:
        return _BACKEND.verify_internal(unhex(public_key), message, unhex(signed))
    except Exception:
        return False


def _keydict_from_seed(seed: bytes):
    public, _secret = _keypair_from_seed(seed)
    return {
        "private_key": seed.hex(),          # 32-byte seed (regenerates the keypair)
        "public_key": public.hex(),         # full 1312-byte ML-DSA public key
        "address": make_address(public.hex()),
    }


def from_private_key(private_key):
    """Recover the full keydict (public_key + address) from the 32-byte seed alone."""
    return _keydict_from_seed(unhex(private_key))


def generate_keydict():
    return _keydict_from_seed(secrets.token_bytes(32))


if __name__ == "__main__":
    print("backend:", _BACKEND.name)
    kd = generate_keydict()
    test_message = "5adf8c531d6698a647c54435386618a0bacd8c3f91b3f1ce1d2ac7c1601a829c"
    print("address:", kd["address"])
    print("seed:", len(kd["private_key"]) // 2, "B  pubkey:", len(kd["public_key"]) // 2, "B")
    sig = sign(private_key=kd["private_key"], message=unhex(test_message))
    print("sig:", len(sig) // 2, "B  verify:",
          verify(signed=sig, public_key=kd["public_key"], message=unhex(test_message)))
    assert from_private_key(kd["private_key"]) == kd  # seed -> identical keypair
