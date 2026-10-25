"""
signatures.py — POST-QUANTUM signatures (ML-DSA-44, FIPS 204 / Dilithium).

Renamed from the legacy signatures.py (2026-07): the algorithm is ML-DSA-44, never signatures/Ed25519,
so the old name was a misnomer. Every `from signatures import ...` was updated to `from signatures import ...`.

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
import threading

from dilithium_py.ml_dsa import ML_DSA_44

from ops.address_ops import make_address

# THREAD-SAFETY (2026-07): the ML-DSA backend (pure-Python dilithium-py's shared ML_DSA_44 instance, and
# equally a native lib over a shared context) does NOT hold up under concurrent calls — its polynomial
# ring / NTT mutates MODULE-LEVEL buffers in place, and the GIL releases between bytecodes, so two threads
# interleaving inside one sign/verify corrupt each other. The node verifies signatures on MANY threads at
# once (the HTTP executor validating submitted/gossiped txs while the core loop validates a block), so under
# load a VALID signature spuriously failed verify() ~1 in 5 -> "Invalid signature" 403 (measured: 541/960
# concurrent verifies wrong; per-thread instances did NOT help -> the shared state is module-level).
# Serialize every backend call with this lock. Under the GIL only one thread runs Python at a time anyway,
# so this costs almost nothing in throughput — it only forbids the interleaving that was corrupting state.
_CRYPTO_LOCK = threading.Lock()


def unhex(hexed):
    """hex str -> bytes; every key/seed/signature crosses the API as hex, this is the one decoder."""
    # LENIENT BY DESIGN, NOT A SPELLING CHECK (audit 2026-09-25 "sig/pubkey hex re-encoding"): fromhex takes uppercase,
    # mixed case and whitespace, so many strings decode to one key or signature. A transaction's signature/public_key
    # are outside its txid, so that freedom let a relayer re-encode a tx without changing its id; consensus pins their
    # spelling in ops/transaction_ops.excluded_witness_check (protocol.py "ONE TRANSACTION, ONE BYTE STRING"). INVARIANT: a new
    # consensus path that decodes a txid-excluded hex field must run behind that check, never rely on this decoder.
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
        """FIPS 204 KeyGen_internal: deterministic (public, secret) from a 32-byte seed — the
        reference behaviour any native backend must reproduce byte-for-byte."""
        return ML_DSA_44._keygen_internal(seed)

    @staticmethod
    def sign_internal(secret, message, rnd):
        """FIPS 204 Sign_internal — NO ctx/domain wrapping (the whole interop trap), hedged with
        the caller-supplied 32-byte `rnd`. Matches the browser light-miner's signing convention."""
        return ML_DSA_44._sign_internal(secret, message, rnd)

    @staticmethod
    def verify_internal(public, message, signature):
        """FIPS 204 Verify_internal — the reference verifier every backend (and the browser's
        signatures) must satisfy; True iff `signature` is valid for (public, message)."""
        return ML_DSA_44._verify_internal(public, message, signature)


class _NativeBackend:
    """Adapter around an operator-supplied native module named by NADO_PQ_NATIVE_MODULE. The module
    must provide `keygen_internal`, `sign_internal`, `verify_internal` with the byte contract above
    (FIPS 204 *internal*, no ctx wrapping). Kept deliberately thin so binding any fast lib that
    exposes the internal functions is a few lines."""

    def __init__(self, module):
        """Bind the already-imported operator module; `name` is surfaced in the startup log so the
        active backend is always visible. No validation here — adoption is gated by _interop_ok."""
        self.name = f"native:{module.__name__}"
        self._m = module

    def keygen_internal(self, seed):
        """Delegate to the native lib; its (public, secret) MUST be byte-identical to pure-Python
        for the same seed — addresses derive from the public key, so any drift forks identities."""
        return self._m.keygen_internal(seed)

    def sign_internal(self, secret, message, rnd):
        """Delegate to the native lib; MUST be internal-mode (no ctx wrapping) so its signatures
        verify under the pure-Python backend and the browser — the interop self-test enforces this."""
        return self._m.sign_internal(secret, message, rnd)

    def verify_internal(self, public, message, signature):
        """Delegate to the native lib; MUST accept pure-Python/browser internal-mode signatures
        (cross-checked by the interop self-test before this backend is ever adopted)."""
        return self._m.verify_internal(public, message, signature)


def _interop_ok(candidate) -> bool:
    """Adopt a native backend ONLY if it round-trips AND cross-verifies with the pure-Python signer
    in BOTH directions on a fixed vector. This guarantees the native lib uses the same (internal,
    no-ctx) convention as the browser + existing on-chain sigs, so swapping it in cannot fork
    consensus. Any exception or mismatch -> reject (stay pure-Python)."""
    try:
        seed = b"\x42" * 32
        msg = b"pq-backend-interop-selftest"
        pub_p, sec_p = _PurePyBackend.keygen_internal(seed)
        pub_n, sec_n = candidate.keygen_internal(seed)
        if pub_n != pub_p or sec_n != sec_p:
            return False  # deterministic keygen must agree (addresses derive from the public key)
        rnd = b"\x07" * 32
        # native signs -> pure-Python verifies, and pure-Python signs -> native verifies
        good = _PurePyBackend.sign_internal(sec_p, msg, rnd)
        if not _PurePyBackend.verify_internal(pub_p, msg, candidate.sign_internal(sec_p, msg, rnd)):
            return False
        if not candidate.verify_internal(pub_p, msg, good):
            return False
        # NEGATIVE VECTORS (required): a positive-only self-test cannot catch the dangerous direction — a
        # native verifier that OVER-ACCEPTS (returns True for a signature the FIPS-204 reference rejects:
        # a broken build, or an unaudited lib mishandling non-canonical/out-of-range encodings). Because
        # every node runs the same .so, such over-acceptance is chain-wide signature forgery that would not
        # even show as a fork. The candidate MUST REJECT all of the following, or it is refused:
        flipped = bytearray(good); flipped[0] ^= 0x01           # (a) one flipped byte
        if candidate.verify_internal(pub_p, msg, bytes(flipped)):
            return False
        if candidate.verify_internal(pub_p, b"a different message", good):  # (b) wrong message
            return False
        pub_other, _ = _PurePyBackend.keygen_internal(b"\x99" * 32)
        if candidate.verify_internal(pub_other, msg, good):     # (c) wrong public key
            return False
        if candidate.verify_internal(pub_p, msg, b"\x00" * len(good)):  # (d) all-zero / garbage sig
            return False
        if candidate.verify_internal(pub_p, msg, good[:-1]):    # (e) truncated sig
            return False
        return True
    except Exception:
        return False


# WHY we are on the fallback, for /status. Knowing a node is degraded is only half of it: the two causes
# need OPPOSITE fixes — an unset env var is a systemd-unit edit, a failed import is a missing build
# (scripts/build_pq_native.sh, which needs cargo). Without this an operator cannot tell them apart from
# outside the box, and the stderr warning that does say which is emitted once at import and then gone.
_BACKEND_REASON = [None]


def _fallback(reason):
    """HARD-FAIL. Since betanet-14 the native ML-DSA backend is the only production implementation.

    THE DEFAULT IS NOW INVERTED. This used to return the pure-Python backend and hard-fail only when
    NADO_PQ_REQUIRE_NATIVE was set. The argument for that default was that the fallback is byte-equivalent
    (the interop self-test enforces it) so consensus is correct either way, and a light node without a build
    toolchain should still start. Both halves are true, and together they are how a node ends up degraded with
    nobody noticing — because nothing ever fails, it just gets ~84x slower.

    That is not hypothetical. On 2026-07-29 this very repository's dev tree was running pure-Python ML-DSA
    against a production node on the native backend. Consequences, none of which looked like a crypto problem:
    every signature test ran orders of magnitude slower, four of them hit their timeout and were indistinguishable
    from failures, and the heavy-proof numbers about to be written into the release notes had been measured under
    the handicap. Right answers, wrong conclusions.

    There is also a security reason the fallback should never be a default: dilithium_py is educational-origin
    and NOT constant-time, which is a side-channel risk whenever a real key signs.

    NADO_ALLOW_PYTHON_KERNELS still permits it, for building and for the conformance tests that exist precisely
    to compare this implementation against the Rust one. Nothing in the node sets it."""
    _BACKEND_REASON[0] = reason
    from execnode.stark.native_guard import allow_absent
    if allow_absent():
        return _PurePyBackend()
    raise RuntimeError(
        f"the native ML-DSA (RustCrypto ml-dsa) backend is unavailable: {reason}. REFUSING TO START. Since "
        f"betanet-14 there is no Python fallback in production: it is byte-equivalent but ~84x slower and not "
        f"constant-time, so running on it degrades a node silently rather than visibly — which has already "
        f"cost this project a set of misleading benchmark numbers. Build it with scripts/build_pq_native.sh "
        f"(needs cargo). For a build or for the Python-vs-Rust conformance tests, set "
        f"NADO_ALLOW_PYTHON_KERNELS=1 — never on a validator.")


def _select_backend():
    """Pick the signing backend at import time. If NADO_PQ_NATIVE_MODULE names an importable module that PASSES
    the interop self-test, use it (the reputable, production RustCrypto ml-dsa crate). Otherwise fall back
    loudly to pure-Python — or HARD-FAIL when NADO_PQ_REQUIRE_NATIVE demands production crypto (see _fallback).
    A bare NADO_PQ_NATIVE_MODULE also defaults to `nado_pq_native` so an installed node uses native without the
    operator having to name it."""
    mod_name = os.environ.get("NADO_PQ_NATIVE_MODULE", "").strip() or "nado_pq_native"
    try:
        candidate = _NativeBackend(importlib.import_module(mod_name))
    except Exception as e:  # operator-supplied module: import must never crash the node (unless REQUIRE_NATIVE)
        sys.stderr.write(f"[PQ] native backend '{mod_name}' import failed ({e}); using pure-Python\n")
        return _fallback(f"module '{mod_name}' did not import ({e}) — run scripts/build_pq_native.sh")
    if _interop_ok(candidate):
        sys.stderr.write(f"[PQ] native ML-DSA backend '{mod_name}' passed interop self-test; enabled\n")
        _BACKEND_REASON[0] = None
        return candidate
    sys.stderr.write(
        f"[PQ] native backend '{mod_name}' FAILED interop self-test (likely ctx-wrapping mismatch); "
        f"refusing it and using pure-Python — see signatures.py INTEROP TRAP\n")
    return _fallback(f"module '{mod_name}' failed the interop self-test (likely ctx-wrapping mismatch) "
                     f"— see signatures.py INTEROP TRAP")


_BACKEND = _select_backend()


def backend_name():
    """Which ML-DSA backend this process actually verifies with — 'native:<module>' or 'pure-python'.

    Surfaced in /status so a DEGRADED node is visible from OUTSIDE, the same way update_capable is.
    The gap is 84x measured on this box (0.154 ms/verify native vs 12.98 ms pure-Python), and every
    verify is serialised behind a single global lock because the backends share NTT buffers. A node
    that lost its native lib (no toolchain on a fresh install, a rebuild that silently failed after an
    /update) still starts, still syncs, and just quietly stops being able to keep up — the warning goes
    to stderr at import and is then invisible forever. Making it queryable turns that into something an
    operator or a peer can actually notice."""
    return getattr(_BACKEND, "name", "pure-python")


def backend_degraded_reason():
    """None when the native backend is live; otherwise WHY we fell back, in operator terms."""
    return _BACKEND_REASON[0]


def _keypair_from_seed(seed: bytes):
    """Deterministic ML-DSA keygen from a 32-byte seed (FIPS 204 KeyGen_internal). Returns
    (public_key_bytes, secret_key_bytes). Locked too: keygen shares the same module-level NTT buffers as
    sign/verify, so a concurrent keygen (e.g. a wallet import while the node validates a block) would
    otherwise corrupt an in-flight verification just the same."""
    # The seed length IS consensus-critical: dilithium-py's _keygen_internal accepts any length (a 31- or
    # 33-byte seed silently derives a valid-but-different keypair), while the native backend and the browser
    # pad/reject differently — so the SAME seed hex could yield different addresses across backends and split
    # identities. Pin it to exactly 32 bytes at the one chokepoint every seed passes through.
    if len(seed) != 32:
        raise ValueError("ML-DSA seed must be exactly 32 bytes")
    with _CRYPTO_LOCK:
        return _BACKEND.keygen_internal(seed)


# ---- the other user-selectable schemes (protocol.py "USER-SELECTABLE SIGNATURE SCHEMES", doc/signature-schemes.md) ----
# ML-DSA-44 keeps the backend above, unchanged: every existing account signs with it and nothing below touches it. The
# other schemes come from native/pqsig (nado_pqsig.py), loaded on FIRST USE — a node that never meets a tagged tx never
# maps the library, and below SIG_SCHEMES_HEIGHT consensus refuses every tagged tx before it reaches verify(). Same key
# model as ML-DSA-44: one 32-byte seed per account; the scheme's own expansion is in native/pqsig/src/lib.rs.
_SCHEME_IDS = {"mldsa65": 1, "mldsa87": 2, "slhdsa128s": 3, "fndsa512": 4}
# KNOWN ANSWERS: blake2b-128 of each scheme's public key for the seed 0x42*32. An address is a hash of the public key, so
# a library whose keygen drifts would move every account of that scheme — refused at load instead. The browser pins the
# same digests (tests/test_every_signature_scheme_derives_one_key_in_every_stack.mjs).
_SCHEME_KAT = {
    "mldsa65": "d1d310a5d8503b27ad23b4d6006ba238",
    "mldsa87": "6d5d287e5f9c1c48a46bbbfc7f38713f",
    "slhdsa128s": "5d911449939d98b95dde5d7fc5fa03db",
    "fndsa512": "dbfffe3bfae2540e147818833cea21bf",
}
_pqs = [None]
_pqs_lock = threading.Lock()


def _scheme_selftest(lib) -> str:
    """'' when every scheme of `lib` derives its known-answer key, round-trips, and REJECTS the five forgeries the
    ML-DSA-44 self-test rejects (an over-accepting verifier is chain-wide forgery that never shows as a fork); otherwise
    the first failure. ML-DSA-65/87 keys are also cross-checked against dilithium-py, the FIPS 204 reference."""
    import hashlib
    from dilithium_py.ml_dsa import ML_DSA_65, ML_DSA_87
    seed, msg, rnd = b"\x42" * 32, b"pq-scheme-selftest", b"\x07" * 32
    ref = {"mldsa65": ML_DSA_65, "mldsa87": ML_DSA_87}
    for name, i in _SCHEME_IDS.items():
        pk, sk = lib.keygen(i, seed)
        if hashlib.blake2b(pk, digest_size=16).hexdigest() != _SCHEME_KAT[name]:
            return f"{name}: keygen does not derive the known-answer key"
        if name in ref and ref[name]._keygen_internal(seed)[0] != pk:
            return f"{name}: keygen disagrees with the FIPS 204 reference"
        good = lib.sign(i, sk, msg, rnd)
        if not lib.verify(i, pk, msg, good):
            return f"{name}: an honest signature does not verify"
        flipped = bytearray(good); flipped[len(good) // 2] ^= 1
        other, _ = lib.keygen(i, b"\x99" * 32)
        for bad in ((pk, msg, bytes(flipped)), (pk, b"a different message", good), (other, msg, good),
                    (pk, msg, b"\x00" * len(good)), (pk, msg, good[:-1])):
            if lib.verify(i, *bad):
                return f"{name}: a forged signature verifies"
    return ""


def _schemes():
    """native/pqsig, self-tested once. Raises when it is missing, stale or fails the test — and verify() turns that into
    False, so a node without it refuses a tagged tx rather than guessing (from SIG_SCHEMES_HEIGHT the crate is required,
    ops/self_update._CRATES, so a live node has it)."""
    with _pqs_lock:
        if _pqs[0] is None:
            import nado_pqsig
            why = _scheme_selftest(nado_pqsig)
            if why:
                raise RuntimeError(f"native/pqsig failed its self-test: {why}")
            _pqs[0] = nado_pqsig
        return _pqs[0]


def _scheme_id(alg):
    """None for ML-DSA-44 (the backend above), the native/pqsig id otherwise; ValueError for an unknown name."""
    if alg is None or alg == "mldsa44":
        return None
    if alg not in _SCHEME_IDS:
        raise ValueError(f"unknown signature scheme {alg!r}")
    return _SCHEME_IDS[alg]


def sign(private_key, message, alg=None):
    """Sign `message` with the 32-byte seed hex `private_key`; returns the ~2420-byte signature as
    hex. The keypair is re-derived from the seed on every call (only the seed is ever stored), then
    signed INTERNAL-mode with a fresh random hedge — so signatures are randomized and deliberately
    NOT byte-reproducible across calls or implementations (consensus only checks verify()==True)."""
    seed = unhex(private_key)
    sid = _scheme_id(alg)
    if sid is not None:
        if len(seed) != 32:
            raise ValueError("a signing seed must be exactly 32 bytes")
        lib = _schemes()
        _public, secret = lib.keygen(sid, seed)
        return lib.sign(sid, secret, message, secrets.token_bytes(32)).hex()
    _public, secret = _keypair_from_seed(seed)
    # INTERNAL ML-DSA sign (FIPS 204 Sign_internal — NO ctx/domain wrapping) with a fresh 32-byte
    # hedge. This is the exact convention `@noble/post-quantum` (the browser light-miner) uses by
    # default, CROSS-VALIDATED both ways (node sig -> noble verify == true, noble sig -> node verify
    # == true). The signature is hedged/randomized and need NOT be byte-reproducible across impls
    # (consensus checks verify()==True, never sig equality).
    with _CRYPTO_LOCK:                     # backend is not concurrency-safe (shared NTT buffers)
        return _BACKEND.sign_internal(secret, message, secrets.token_bytes(32)).hex()


def verify(signed, public_key, message, alg=None):
    """True iff `signed` (hex) is a valid ML-DSA-44 *internal*-mode signature by `public_key` (hex)
    over `message`. NEVER raises (see below) — malformed input is a False, so a rejection can't
    escalate into an unhandled error or get mis-refactored into an accept. This is THE consensus
    signature check: it verifies, never recomputes, so differing signature bytes across backends/
    browser are fine."""
    # return False on ANY failure instead of raising: callers use `assert verify(...)` /
    # `if verify(...)`, and a raising verify could turn a rejection into an unhandled error or be
    # mis-refactored into a silent accept. INTERNAL verify to match the signer above + the browser.
    # `alg` None / "mldsa44": the backend above, exactly as before. Any other scheme: native/pqsig (Rust, no shared
    # buffers — it needs no lock). An unknown scheme, or a node without the library, is an invalid signature.
    try:
        sid = _scheme_id(alg)
        if sid is not None:
            return bool(_schemes().verify(sid, unhex(public_key), message, unhex(signed)))
        with _CRYPTO_LOCK:                # backend is not concurrency-safe (shared NTT buffers) — see top
            return _BACKEND.verify_internal(unhex(public_key), message, unhex(signed))
    except Exception:
        return False


def _keydict_from_seed(seed: bytes, alg=None):
    """seed -> the canonical keydict shape the rest of the node stores/passes around. The 32-byte
    seed alone IS the identity: the ML-DSA secret key is never persisted, only re-derived, which
    keeps key files tiny and makes import-by-seed (from_private_key) possible. A key of another
    scheme carries "alg" (absent = ML-DSA-44, as on the wire), and its address commits to it."""
    sid = _scheme_id(alg)
    if sid is None:
        public, _secret = _keypair_from_seed(seed)
        return {
            "private_key": seed.hex(),          # 32-byte seed (regenerates the keypair)
            "public_key": public.hex(),         # full 1312-byte ML-DSA public key
            "address": make_address(public.hex()),
        }
    if len(seed) != 32:
        raise ValueError("a signing seed must be exactly 32 bytes")
    public, _secret = _schemes().keygen(sid, seed)
    return {"private_key": seed.hex(), "public_key": public.hex(), "alg": alg,
            "address": make_address(public.hex(), alg=alg)}


def from_private_key(private_key, alg=None):
    """Recover the full keydict (public_key + address) from the 32-byte seed alone, under scheme `alg`."""
    return _keydict_from_seed(unhex(private_key), alg)


def generate_keydict(alg=None):
    """Fresh identity from a CSPRNG (secrets) 32-byte seed — the ONLY entropy the whole key model
    ever needs; everything else (secret key, public key, address) derives deterministically."""
    return _keydict_from_seed(secrets.token_bytes(32), alg)


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
