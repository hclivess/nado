"""TPM 2.0 credential protection — the CHALLENGE half of issuing our own AIK certificates, so that a chip
Microsoft will not certify can still attest (doc/windows-tpm-attester.md).

WHAT THIS MODULE DOES AND DOES NOT DO. It seals a secret to an endorsement key, bound to an attestation key's
Name, and a chip returns that secret only if both keys live inside it. That is the PROOF. It issues nothing:
there is no CA key here, no X.509, no certificate. Step 6 below is described because it is where this leads,
not because it exists. Do not read "issuer" in this file as a component that has been built.

WHY THIS EXISTS. 26.8% of all device-attestation attempts on this chain are a Windows PC whose TPM is healthy
and whose Windows Hello refuses to produce a statement, overwhelmingly because Microsoft's AIK service has no
certificate authority registered for that chip's KeyId and answers 404. Microsoft has confirmed that as
service-side with no client-side fix. Those machines carry a perfectly good, vendor-signed ENDORSEMENT KEY
certificate — AMD's chains to CN=AMDTPM, Intel's chain through the CSME EICAs kept in the TPM's own NV — so the
hardware evidence exists and is verifiable without Microsoft. What is missing is the one signature that says
"this attestation key lives in that certified chip". This module is how we produce it ourselves.

THE PROTOCOL (TPM 2.0 part 1 §24, "Credential Protection"). It is necessarily INTERACTIVE, and that is not an
implementation choice: the verifier must know a secret the client does not.

    1. client  -> us     : EK certificate (+ its chain), and the AIK's public area
    2. us       [BUILT] : verify the EK chain to a PINNED VENDOR ROOT; derive the AIK's Name from its pubArea;
                          choose a random secret; make_credential() seals it to the EK, bound to that Name
    3. us      -> client : credentialBlob + encrypted seed
    4. client           : TPM2_ActivateCredential — the TPM returns the secret ONLY if the EK and the AIK are
                          objects in the same chip
    5. client  -> us     : the recovered secret
    6. us    [NOT BUILT] : issue an AIK certificate carrying the EK's identity

Deriving the secret from chain data instead, to avoid the round trip, does not work and must not be attempted:
anything every node can recompute, the client can recompute too, so the "proof" would prove nothing.

WHAT BINDS AN IDENTITY IS THE EK, NEVER THE AIK WE ISSUE. A chip can hold unlimited AIKs, so hashing an AIK
certificate we minted would let one machine mint one identity per enrolment. `ek_identity()` is the handle, it
is derived from the endorsement key itself, and the issued certificate carries it so consensus can bind on it
without trusting the issuer's bookkeeping.

Relay-side only: nothing here runs inside consensus. Consensus sees the finished certificate.
"""
import hashlib
import hmac
import os

# Labels are NUL-terminated in the TPM's KDF and OAEP usage (part 1 §24.4, §B.10.3).
_LABEL_IDENTITY = b"IDENTITY\x00"
_LABEL_STORAGE = b"STORAGE\x00"
_LABEL_INTEGRITY = b"INTEGRITY\x00"

TPM_ALG_SHA256 = 0x000B


def kdfa(hash_alg, key: bytes, label: bytes, context_u: bytes, context_v: bytes, bits: int) -> bytes:
    """TPM 2.0 KDFa (part 1 §11.4.10.2): counter-mode HMAC. `label` arrives already NUL-terminated.

    KDFa(key, label, u, v, bits) = HMAC(key, UINT32(i) || label || u || v || UINT32(bits)) for i = 1, 2, ...
    truncated to `bits`. Getting the counter width or the trailing bit count wrong yields a key that is wrong
    in a way no test but a real TPM would catch, so this is written straight from the spec's formula.
    """
    out = b""
    n = (bits + 7) // 8
    i = 1
    while len(out) < n:
        out += hmac.new(key, i.to_bytes(4, "big") + label + context_u + context_v + bits.to_bytes(4, "big"),
                        hash_alg).digest()
        i += 1
    return out[:n]


def tpm2b(data: bytes) -> bytes:
    """A TPM2B_* — a 16-bit big-endian size followed by that many bytes."""
    return len(data).to_bytes(2, "big") + data


def aik_name(pub_area: bytes, name_alg: int = TPM_ALG_SHA256) -> bytes:
    """The TPM Name of an object: its nameAlg followed by the digest of its public area. This is what the
    credential is cryptographically bound to, which is what makes the activation prove the AIK's identity and
    not merely the chip's."""
    if name_alg != TPM_ALG_SHA256:
        raise ValueError(f"unsupported nameAlg 0x{name_alg:04x}")
    return name_alg.to_bytes(2, "big") + hashlib.sha256(pub_area).digest()


def make_credential(ek_public_numbers, name: bytes, secret: bytes, seed: bytes = None) -> tuple:
    """TPM2_MakeCredential, issuer side: seal `secret` so that only a TPM holding BOTH the endorsement key and
    the object named `name` can recover it.

    Returns (credential_blob, encrypted_seed), each already TPM2B-wrapped, which is the form
    TPM2_ActivateCredential expects.
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    if seed is None:
        seed = os.urandom(32)                      # size of the EK's nameAlg digest

    # The seed travels to the chip under the EK, with the spec's IDENTITY label.
    pub = ek_public_numbers.public_key() if hasattr(ek_public_numbers, "public_key") else ek_public_numbers
    enc_seed = pub.encrypt(seed, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                                              algorithm=hashes.SHA256(), label=_LABEL_IDENTITY))

    # Symmetric protection of the credential, keyed from the seed and BOUND TO THE NAME: a credential made for
    # one AIK cannot be activated by another, which is the property the whole handshake rests on.
    sym_key = kdfa(hashlib.sha256, seed, _LABEL_STORAGE, name, b"", 128)
    enc = Cipher(algorithms.AES(sym_key), modes.CFB(b"\x00" * 16)).encryptor()
    enc_identity = enc.update(tpm2b(secret)) + enc.finalize()

    hmac_key = kdfa(hashlib.sha256, seed, _LABEL_INTEGRITY, b"", b"", 256)
    outer_hmac = hmac.new(hmac_key, enc_identity + name, hashlib.sha256).digest()

    credential_blob = tpm2b(tpm2b(outer_hmac) + enc_identity)
    return credential_blob, tpm2b(enc_seed)


def activate_credential(ek_private, credential_blob: bytes, encrypted_seed: bytes, name: bytes) -> bytes:
    """The chip's side of the handshake, in software. NOT used in production — a real client does this inside
    the TPM, which is the entire point. It exists so make_credential() can be tested end to end here, because
    a KDFa or CFB layout error is otherwise invisible until it fails on a user's machine for no stated reason.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    seed = ek_private.decrypt(encrypted_seed[2:], padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                                                              algorithm=hashes.SHA256(), label=_LABEL_IDENTITY))
    body = credential_blob[2:]
    hmac_len = int.from_bytes(body[:2], "big")
    outer_hmac, enc_identity = body[2:2 + hmac_len], body[2 + hmac_len:]

    hmac_key = kdfa(hashlib.sha256, seed, _LABEL_INTEGRITY, b"", b"", 256)
    if not hmac.compare_digest(outer_hmac, hmac.new(hmac_key, enc_identity + name, hashlib.sha256).digest()):
        raise ValueError("credential integrity check failed")

    sym_key = kdfa(hashlib.sha256, seed, _LABEL_STORAGE, name, b"", 128)
    dec = Cipher(algorithms.AES(sym_key), modes.CFB(b"\x00" * 16)).decryptor()
    plain = dec.update(enc_identity) + dec.finalize()
    return plain[2:2 + int.from_bytes(plain[:2], "big")]


def ek_identity(ek_cert_der: bytes) -> str:
    """THE ONE-DEVICE-ONE-IDENTITY HANDLE. Derived from the endorsement key, which is burned into the chip and
    cannot be re-minted — unlike an AIK, of which a TPM can hold unlimited numbers. Consensus binds on this."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    cert = x509.load_der_x509_certificate(ek_cert_der)
    spki = cert.public_key().public_bytes(serialization.Encoding.DER,
                                          serialization.PublicFormat.SubjectPublicKeyInfo)
    return hashlib.sha256(spki).hexdigest()


# TPMA_OBJECT bits (TCG part 2 §8.3) — the attributes that decide what a key is allowed to do.
_FIXED_TPM = 0x0000_0002            # cannot be duplicated to another chip
_FIXED_PARENT = 0x0000_0010
_SENSITIVE_DATA_ORIGIN = 0x0000_0020  # the TPM made the private key, it was not imported
_RESTRICTED = 0x0001_0000
_DECRYPT = 0x0002_0000
_SIGN = 0x0004_0000


def validate_aik_pub_area(pub_area: bytes) -> str:
    """Refuse to certify anything but a genuine attestation key. Raises ValueError with the reason.

    THIS IS A SECURITY CHECK, NOT A SANITY CHECK. The client hands us this public area and we are about to
    vouch for it. Certify an UNRESTRICTED signing key and that chip can afterwards sign anything the host asks
    it to — including a forged TPMS_ATTEST claiming to certify a key that never existed inside the TPM. The
    identity count stays capped either way, because the binding is on the endorsement key, but the guarantee
    that "this credential key lives in hardware" would be worth nothing. A restricted key signs only structures
    the TPM itself generated, which is precisely what makes TPM2_Certify evidence rather than a signature.

    Likewise sensitiveDataOrigin: without it the private half could have been generated outside and imported,
    and fixedTPM/fixedParent: without them it could be duplicated to another chip, so one enrolment would
    licence every machine the key is copied to.
    """
    be16 = lambda o: int.from_bytes(pub_area[o:o + 2], "big")
    if len(pub_area) < 12:
        raise ValueError("public area is too short to be a TPMT_PUBLIC")
    if be16(0) != 0x0001:
        raise ValueError(f"attestation key must be RSA, got algorithm 0x{be16(0):04x}")
    if be16(2) != TPM_ALG_SHA256:
        raise ValueError(f"attestation key nameAlg must be SHA-256, got 0x{be16(2):04x}")

    attrs = int.from_bytes(pub_area[4:8], "big")
    required = {
        "restricted": _RESTRICTED,
        "sign": _SIGN,
        "fixedTPM": _FIXED_TPM,
        "fixedParent": _FIXED_PARENT,
        "sensitiveDataOrigin": _SENSITIVE_DATA_ORIGIN,
    }
    missing = [n for n, bit in required.items() if not attrs & bit]
    if missing:
        raise ValueError(f"attestation key is missing required attributes: {', '.join(missing)}")
    if attrs & _DECRYPT:
        raise ValueError("attestation key must not be a decryption key")

    # The scheme must be a real signing scheme: a NULL scheme lets the caller choose one per signature, which
    # reopens exactly the freedom `restricted` is there to remove.
    policy = be16(8)
    o = 10 + policy
    sym = be16(o)
    o += 2
    if sym != 0x0010:
        o += 4
    scheme = be16(o)
    if scheme == 0x0010:
        raise ValueError("attestation key must declare a signing scheme, not TPM_ALG_NULL")
    return f"RSA-{be16(o + 4)} restricted signing key, scheme 0x{scheme:04x}"
