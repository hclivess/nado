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
    2. us       [BUILT] : verify_ek_chain() to a PINNED VENDOR ROOT to a PINNED VENDOR ROOT; derive the AIK's Name from its pubArea;
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


def make_credential(ek_spki_der: bytes, name: bytes, secret: bytes, seed: bytes = None) -> tuple:
    """TPM2_MakeCredential: seal `secret` so that only a TPM holding BOTH the endorsement key and the object
    named `name` can recover it.

    Takes the endorsement key's SubjectPublicKeyInfo, which is what the kernel hands back — deliberately NOT a
    parsed certificate object, because real vendor certificates are not strictly DER and the node's runtime has
    no certificate library at all.

    Returns (credential_blob, encrypted_seed), each already TPM2B-wrapped, which is the form
    TPM2_ActivateCredential expects.
    """
    if seed is None:
        seed = os.urandom(32)                      # size of the EK's nameAlg digest

    # The seed travels to the chip under the EK, with the spec's IDENTITY label.
    n, e = rsa_public_numbers_from_spki(ek_spki_der)
    enc_seed = rsa_oaep_encrypt(n, e, seed, _LABEL_IDENTITY)

    # Symmetric protection of the credential, keyed from the seed and BOUND TO THE NAME: a credential made for
    # one attestation key cannot be activated by another, which is the property the handshake rests on.
    sym_key = kdfa(hashlib.sha256, seed, _LABEL_STORAGE, name, b"", 128)
    enc_identity = aes_cfb_encrypt(sym_key, b"\x00" * 16, tpm2b(secret))

    hmac_key = kdfa(hashlib.sha256, seed, _LABEL_INTEGRITY, b"", b"", 256)
    outer_hmac = hmac.new(hmac_key, enc_identity + name, hashlib.sha256).digest()

    return tpm2b(tpm2b(outer_hmac) + enc_identity), tpm2b(enc_seed)


def activate_credential(ek_decrypt, credential_blob: bytes, encrypted_seed: bytes, name: bytes) -> bytes:
    """The chip's side, in software. NOT used in production — a real client does this inside the TPM, which is
    the entire point. It exists so make_credential() can be tested end to end, because a KDFa or CFB layout
    error is otherwise invisible until it fails on a stranger's machine for no stated reason.

    `ek_decrypt` is a callable taking the ciphertext and returning the seed.
    """
    seed = ek_decrypt(encrypted_seed[2:])
    body = credential_blob[2:]
    hmac_len = int.from_bytes(body[:2], "big")
    outer_hmac, enc_identity = body[2:2 + hmac_len], body[2 + hmac_len:]

    hmac_key = kdfa(hashlib.sha256, seed, _LABEL_INTEGRITY, b"", b"", 256)
    if not hmac.compare_digest(outer_hmac, hmac.new(hmac_key, enc_identity + name, hashlib.sha256).digest()):
        raise ValueError("credential integrity check failed")

    sym_key = kdfa(hashlib.sha256, seed, _LABEL_STORAGE, name, b"", 128)
    plain = aes_cfb_decrypt(sym_key, b"\x00" * 16, enc_identity)
    return plain[2:2 + int.from_bytes(plain[:2], "big")]


# ek_identity() and verify_ek_chain() were here and are gone on purpose. Both needed a certificate parser,
# and the node's runtime has none — worse, real vendor certificates are not strictly DER, so the obvious
# library refuses half the roots we pin. native/attest/src/ek.rs does the chain walk and returns the
# endorsement identity, and nado.py calls it through attest_native.verify_ek(). One implementation, in the
# place that must be deterministic anyway.


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


# --- CA-FREE ENROLMENT: commit-reveal instead of a signing key ------------------------------------------
#
# A signed AIK certificate is one way to turn the interactive proof into something consensus can check later.
# It is not the only way, and it is the expensive one: a long-lived key that can assert any endorsement
# identity is a key that can mint identities, so it has to be guarded like a mint forever.
#
# The cheaper construction uses what this chain already runs for RANDAO. MakeCredential's credentialBlob is
# DETERMINISTIC in (seed, name, secret) — only the OAEP-wrapped seed is randomised, and no verifier needs that
# half. So a challenge can be REPLAYED by everyone afterwards:
#
#     1. challenger seals secret S under seed R:  blob = make_credential(EKpub, name, S, seed=R)
#     2. client activates in its TPM, recovers S, and publishes H(S)          <- commitment
#     3. challenger reveals (S, R)
#     4. every node recomputes the blob from (S, R) and checks the commitment
#
# The client can only learn S by holding the chip, and must commit BEFORE the reveal, so it cannot read the
# answer off the chain. Nothing is signed and no key persists: there is nothing to steal, rotate or guard.
#
# The residual attack is a challenger privately leaking S so a client can commit without a TPM. That is why
# there must be SEVERAL independent challengers and the client must recover every one of their secrets:
# forgery then needs all of them to collude, which is a property consensus can see rather than a key someone
# promises to protect.


def credential_commitment(secret: bytes) -> str:
    """What the client publishes before any reveal. Binding it to the secret alone is deliberate: the client
    must prove it learned S, and S is exactly what only the chip could produce."""
    return hashlib.sha256(secret).hexdigest()


def verify_credential_reveal(ek_spki_der: bytes, name: bytes, secret: bytes, seed: bytes,
                             published_blob: bytes, commitment: str) -> bool:
    """Replay a challenge that someone else issued. Every node can run this, offline, forever.

    Returns True only if the revealed (secret, seed) genuinely produce the blob that was published, AND the
    client's earlier commitment is to that secret. Either half alone proves nothing: a blob without a
    commitment says the challenger sealed something, and a commitment without the blob says the client knew
    something.
    """
    if not hmac.compare_digest(credential_commitment(secret), commitment):
        return False
    replayed, _ = make_credential(ek_spki_der, name, secret, seed=seed)
    return hmac.compare_digest(replayed, published_blob)


# --- dependency-free primitives ------------------------------------------------------------------------
#
# The node's venv has no `cryptography`, and adding a dependency to every machine in the fleet to run an
# enrolment is the wrong trade — the rest of this codebase keeps its crypto either in the Rust kernel or in
# the standard library. AES-128-CFB and RSA-OAEP are both fully specified and small, so they live here and are
# tested BOTH against `cryptography` as an oracle (where it happens to be installed) and end to end against a
# real TPM, which is the only judge that matters.

_SBOX = None


def _aes_tables():
    """AES S-box and round constants, generated rather than pasted: a mistyped byte in a 256-entry table is
    invisible to review and produces ciphertext that is wrong only for some inputs."""
    global _SBOX
    if _SBOX is not None:
        return _SBOX
    p = q = 1
    sbox = [0] * 256
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6)) ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4))
        sbox[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    sbox[0] = 0x63
    _SBOX = sbox
    return sbox


def _xtime(a):
    a <<= 1
    return (a ^ 0x1B) & 0xFF if a & 0x100 else a


def _aes128_expand(key: bytes):
    s = _aes_tables()
    w = [list(key[i * 4:i * 4 + 4]) for i in range(4)]
    rcon = 1
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [s[b] for b in t]
            t[0] ^= rcon
            rcon = _xtime(rcon)
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return w


def _aes128_encrypt_block(w, block: bytes) -> bytes:
    s = _aes_tables()
    st = [list(block[i::4]) for i in range(4)]          # column-major state
    st = [[block[r + 4 * c] for c in range(4)] for r in range(4)]

    def add_round_key(st, rnd):
        for c in range(4):
            for r in range(4):
                st[r][c] ^= w[rnd * 4 + c][r]

    add_round_key(st, 0)
    for rnd in range(1, 11):
        for r in range(4):
            for c in range(4):
                st[r][c] = s[st[r][c]]
        for r in range(1, 4):
            st[r] = st[r][r:] + st[r][:r]
        if rnd != 10:
            for c in range(4):
                a = [st[r][c] for r in range(4)]
                st[0][c] = _xtime(a[0]) ^ (_xtime(a[1]) ^ a[1]) ^ a[2] ^ a[3]
                st[1][c] = a[0] ^ _xtime(a[1]) ^ (_xtime(a[2]) ^ a[2]) ^ a[3]
                st[2][c] = a[0] ^ a[1] ^ _xtime(a[2]) ^ (_xtime(a[3]) ^ a[3])
                st[3][c] = (_xtime(a[0]) ^ a[0]) ^ a[1] ^ a[2] ^ _xtime(a[3])
        add_round_key(st, rnd)
    return bytes(st[r][c] for c in range(4) for r in range(4))


def aes_cfb_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """AES-CFB128. The TPM uses full-block feedback with a zero IV for credential protection."""
    w = _aes128_expand(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        ks = _aes128_encrypt_block(w, prev)
        chunk = data[i:i + 16]
        c = bytes(a ^ b for a, b in zip(chunk, ks))
        out += c
        prev = c + ks[len(c):]                          # a short final block still feeds a full block
    return bytes(out)


def aes_cfb_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    w = _aes128_expand(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        ks = _aes128_encrypt_block(w, prev)
        chunk = data[i:i + 16]
        out += bytes(a ^ b for a, b in zip(chunk, ks))
        prev = chunk + ks[len(chunk):]
    return bytes(out)


def _mgf1(seed: bytes, length: int, hash_alg=hashlib.sha256) -> bytes:
    out = b""
    i = 0
    while len(out) < length:
        out += hash_alg(seed + i.to_bytes(4, "big")).digest()
        i += 1
    return out[:length]


def rsa_oaep_encrypt(n: int, e: int, message: bytes, label: bytes, rand=None) -> bytes:
    """RSA-OAEP with SHA-256, per RFC 8017 §7.1.1. `label` arrives already NUL-terminated for TPM use."""
    k = (n.bit_length() + 7) // 8
    h_len = 32
    l_hash = hashlib.sha256(label).digest()
    ps = b"\x00" * (k - len(message) - 2 * h_len - 2)
    db = l_hash + ps + b"\x01" + message
    seed = rand if rand is not None else os.urandom(h_len)
    db_mask = _mgf1(seed, k - h_len - 1)
    masked_db = bytes(a ^ b for a, b in zip(db, db_mask))
    seed_mask = _mgf1(masked_db, h_len)
    masked_seed = bytes(a ^ b for a, b in zip(seed, seed_mask))
    em = b"\x00" + masked_seed + masked_db
    c = pow(int.from_bytes(em, "big"), e, n)
    return c.to_bytes(k, "big")


def rsa_public_numbers_from_spki(spki_der: bytes):
    """(n, e) out of a SubjectPublicKeyInfo, by a minimal DER walk. Real vendor certificates are not strictly
    DER, so this deliberately does not go through a strict parser."""
    def tlv(b, i):
        tag = b[i]
        ln = b[i + 1]
        if ln < 0x80:
            return tag, i + 2, ln
        k = ln & 0x7F
        return tag, i + 2 + k, int.from_bytes(b[i + 2:i + 2 + k], "big")
    _t, h, _n = tlv(spki_der, 0)                       # SEQUENCE
    t, h2, n2 = tlv(spki_der, h)                       # AlgorithmIdentifier
    i = h + n2 + (h2 - h)
    t, h3, n3 = tlv(spki_der, i)                       # BIT STRING
    inner = spki_der[h3 + 1:h3 + n3]                   # skip the unused-bits byte
    _t, ih, _n = tlv(inner, 0)
    t, nh, nn = tlv(inner, ih)
    n = int.from_bytes(inner[nh:nh + nn], "big")
    t, eh, en = tlv(inner, nh + nn)
    e = int.from_bytes(inner[eh:eh + en], "big")
    return n, e


def verify_enrolment(ek_spki_der: bytes, aik_pub_area: bytes, secret: bytes, seed: bytes,
                     published_blob: bytes, commitment: str) -> str:
    """The whole enrolment, checked from public data. Returns a short description; raises ValueError with the
    reason. Every node runs this, offline, forever — there is nothing to sign and no key to hold.

    WHAT THIS FUNCTION CANNOT CHECK, and what therefore must be enforced by the transaction ordering around it:
    that the client committed to `secret` BEFORE the challenger revealed `(secret, seed)`. Given all five
    values at once, a client with no chip at all can pick a secret and a seed, compute the blob itself, and
    hand over a self-consistent fabrication that passes every line below. The ordering IS the proof; this only
    checks the arithmetic. A caller that collapses the three messages into one has removed the security and
    kept the ceremony.
    """
    detail = validate_aik_pub_area(aik_pub_area)          # restricted, signing, non-duplicable, TPM-originated
    name = aik_name(aik_pub_area)
    if not verify_credential_reveal(ek_spki_der, name, secret, seed, published_blob, commitment):
        raise ValueError("the revealed secret and seed do not reproduce the published credential")
    return detail
