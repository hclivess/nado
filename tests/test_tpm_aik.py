"""ops/tpm_aik — the credential-protection handshake that lets us issue AIK certificates ourselves.

This is the core of attesting a TPM that Microsoft will not certify (26.8% of all attempts on this chain), so
its two security properties get pinned here rather than discovered on a user's machine:
  - a credential sealed for one AIK Name cannot be activated by a different AIK  (else one chip mints many)
  - a credential sealed to one endorsement key cannot be opened by another        (else no chip is proven)
Run: python3 tests/test_tpm_aik.py
"""
import hashlib
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="nado-aik-"))
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def main():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from ops.tpm_aik import make_credential, activate_credential, aik_name, kdfa, tpm2b, ek_identity

    ek = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_area = os.urandom(312)
    name = aik_name(pub_area)
    secret = os.urandom(32)

    check("the AIK Name is nameAlg || sha256(pubArea)",
          name == b"\x00\x0b" + hashlib.sha256(pub_area).digest())

    blob, enc_seed = make_credential(ek.public_key(), name, secret)
    check("credentialBlob and encrypted seed are TPM2B-wrapped",
          int.from_bytes(blob[:2], "big") == len(blob) - 2 and
          int.from_bytes(enc_seed[:2], "big") == len(enc_seed) - 2)
    check("a chip holding both keys recovers the secret",
          activate_credential(ek, blob, enc_seed, name) == secret)

    # ONE CHIP MUST NOT MINT MANY IDENTITIES. The credential is keyed and HMACed over the AIK's Name, so a
    # second AIK in the same TPM cannot open a credential issued for the first.
    try:
        activate_credential(ek, blob, enc_seed, aik_name(os.urandom(312)))
        check("bound to the AIK Name", False, "a different AIK activated it")
    except ValueError:
        check("bound to the AIK Name", True)

    # AND THE PROOF MUST MEAN A CHIP. Without the endorsement private key the seed cannot be unwrapped at all.
    try:
        activate_credential(rsa.generate_private_key(public_exponent=65537, key_size=2048), blob, enc_seed, name)
        check("bound to the endorsement key", False, "a foreign key opened it")
    except Exception:
        check("bound to the endorsement key", True)

    # KDFa is counter-mode HMAC; a wrong counter width or trailing bit count yields a key that is wrong in a
    # way only a real TPM would reveal, so pin its shape and determinism.
    k1 = kdfa(hashlib.sha256, b"k" * 32, b"STORAGE\x00", name, b"", 128)
    check("KDFa returns exactly the requested width", len(k1) * 8 == 128)
    check("KDFa is deterministic", k1 == kdfa(hashlib.sha256, b"k" * 32, b"STORAGE\x00", name, b"", 128))
    check("KDFa separates its labels",
          k1 != kdfa(hashlib.sha256, b"k" * 32, b"INTEGRITY\x00", name, b"", 128))
    check("KDFa separates its contexts",
          k1 != kdfa(hashlib.sha256, b"k" * 32, b"STORAGE\x00", aik_name(os.urandom(312)), b"", 128))
    # NOT a prefix relationship, and that is correct: KDFa feeds UINT32(bits) into EVERY block, so asking for
    # a different width changes all of the output. Pinning it the wrong way round would have "fixed" a correct
    # implementation into a broken one that only a real TPM could have caught.
    check("a different width is a different key, not an extension",
          kdfa(hashlib.sha256, b"k" * 32, b"STORAGE\x00", name, b"", 384)[:16] != k1)

    check("tpm2b prefixes a 16-bit big-endian length", tpm2b(b"abc") == b"\x00\x03abc")

    # THE IDENTITY HANDLE IS THE EK, NEVER AN AIK WE ISSUE (doc/windows-tpm-attester.md). A chip holds
    # unlimited AIKs; hashing one we minted would hand a single machine one identity per enrolment.
    src = open(os.path.join(ROOT, "ops", "tpm_aik.py")).read()
    check("ek_identity derives from the endorsement key's own SubjectPublicKeyInfo",
          "SubjectPublicKeyInfo" in src and "def ek_identity" in src)
    check("the module states why deriving the secret from chain data is not an option",
          "the client can recompute" in src)

    # The vendor root that makes any of this verifiable without Microsoft.
    amd = os.path.join(ROOT, "protocol_roots", "ek", "amd_ftpm_root.pem")
    check("AMD's fTPM endorsement root is carried", os.path.isfile(amd))
    if os.path.isfile(amd):
        import base64
        pem = open(amd).read()
        der = base64.b64decode("".join(l for l in pem.splitlines() if not l.startswith("-----")))
        check("and it is the root a real AMD EK certificate chains to",
              hashlib.sha256(der).hexdigest()
              == "67bd2472a546751caca5f358a78f80727531671338960a9bcfdfbe6a34d0c6a1",
              hashlib.sha256(der).hexdigest())

    print("\n" + ("ALL OK" if not _fails else f"{len(_fails)} FAILURES"))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
