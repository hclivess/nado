"""
Curve25519.py — POST-QUANTUM signatures (ML-DSA-44, FIPS 204 / Dilithium).

NOTE: the module NAME is kept only for import stability (transaction_ops, key_ops, the wallets and
the testnet harness all do `from Curve25519 import ...`); the algorithm is now **ML-DSA-44**, NOT
Curve25519/Ed25519. Backed by `dilithium-py` — a PURE-PYTHON implementation, so there is no native
dependency to compile (in keeping with the "runs on anything, even a 386" goal). The hex-in/hex-out
interface is unchanged, so every caller is untouched.

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
import secrets

from dilithium_py.ml_dsa import ML_DSA_44

from ops.address_ops import make_address


def unhex(hexed):
    return b"".fromhex(hexed)


def _keypair_from_seed(seed: bytes):
    """Deterministic ML-DSA keygen from a 32-byte seed (FIPS 204 KeyGen_internal). Returns
    (public_key_bytes, secret_key_bytes)."""
    return ML_DSA_44._keygen_internal(seed)


def sign(private_key, message):
    seed = unhex(private_key)
    _public, secret = _keypair_from_seed(seed)
    # INTERNAL ML-DSA sign (FIPS 204 Sign_internal — NO ctx/domain wrapping) with a fresh 32-byte
    # hedge. This is the exact convention `@noble/post-quantum` (the browser light-miner) uses by
    # default, CROSS-VALIDATED both ways (node sig -> noble verify == true, noble sig -> node verify
    # == true). The signature is hedged/randomized and need NOT be byte-reproducible across impls
    # (consensus checks verify()==True, never sig equality).
    return ML_DSA_44._sign_internal(secret, message, secrets.token_bytes(32)).hex()


def verify(signed, public_key, message):
    # return False on ANY failure instead of raising: callers use `assert verify(...)` /
    # `if verify(...)`, and a raising verify could turn a rejection into an unhandled error or be
    # mis-refactored into a silent accept. INTERNAL verify to match the signer above + the browser.
    try:
        return ML_DSA_44._verify_internal(unhex(public_key), message, unhex(signed))
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
    kd = generate_keydict()
    test_message = "5adf8c531d6698a647c54435386618a0bacd8c3f91b3f1ce1d2ac7c1601a829c"
    print("address:", kd["address"])
    print("seed:", len(kd["private_key"]) // 2, "B  pubkey:", len(kd["public_key"]) // 2, "B")
    sig = sign(private_key=kd["private_key"], message=unhex(test_message))
    print("sig:", len(sig) // 2, "B  verify:",
          verify(signed=sig, public_key=kd["public_key"], message=unhex(test_message)))
    assert from_private_key(kd["private_key"]) == kd  # seed -> identical keypair
