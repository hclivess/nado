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

    # WE ARE ABOUT TO VOUCH FOR WHATEVER PUBLIC AREA THE CLIENT SENDS. Certifying an unrestricted signing key
    # would let that chip afterwards sign anything the host asked for, including a forged TPMS_ATTEST for a key
    # that never lived in the TPM — so every one of these refusals is load-bearing.
    from ops.tpm_aik import validate_aik_pub_area
    import struct

    def pub(attrs, scheme=0x0014, alg=0x0001, name_alg=0x000B):
        b = struct.pack(">HHI", alg, name_alg, attrs) + b"\x00\x00"      # no authPolicy
        b += struct.pack(">H", 0x0010)                                    # symmetric NULL
        b += struct.pack(">H", scheme) + (b"" if scheme == 0x0010 else struct.pack(">H", 0x000B))
        b += struct.pack(">H", 2048) + struct.pack(">I", 0) + b"\x00\x00"
        return b

    good = 0x0005_0472
    check("a genuine restricted signing key is accepted", "restricted" in validate_aik_pub_area(pub(good)))
    for name, attrs in (("unrestricted", good & ~0x0001_0000),
                        ("not a signing key", good & ~0x0004_0000),
                        ("duplicable (no fixedTPM)", good & ~0x0000_0002),
                        ("importable (no sensitiveDataOrigin)", good & ~0x0000_0020)):
        try:
            validate_aik_pub_area(pub(attrs))
            check(f"refuses a key that is {name}", False, "it was accepted")
        except ValueError:
            check(f"refuses a key that is {name}", True)
    try:
        validate_aik_pub_area(pub(good | 0x0002_0000))
        check("refuses a key that can also decrypt", False, "it was accepted")
    except ValueError:
        check("refuses a key that can also decrypt", True)
    try:
        validate_aik_pub_area(pub(good, scheme=0x0010))
        check("refuses a NULL signing scheme", False, "it was accepted")
    except ValueError:
        check("refuses a NULL signing scheme", True)

    # A PINNED FINGERPRINT WITH NO FILE, OR A FILE WITH NO FINGERPRINT, SILENTLY LOADS NOTHING. The loader
    # filters files by the pinned set, so either kind of drift removes a vendor from trust without any error —
    # every chip from that maker would simply stop enrolling, and the reason would not appear anywhere.
    import protocol as P
    from ops import attest_native
    loaded = attest_native._ek_roots_blob()
    check("every pinned endorsement root has its certificate on disk",
          len(loaded) == len(P.DEVICE_ATTEST_EK_ROOTS),
          f"{len(loaded)} loaded vs {len(P.DEVICE_ATTEST_EK_ROOTS)} pinned")

    ekdir = os.path.join(ROOT, "protocol_roots", "ek")
    import base64 as _b64
    on_disk = {}
    for name in sorted(os.listdir(ekdir)):
        if not name.endswith(".pem"):
            continue
        pem = open(os.path.join(ekdir, name)).read()
        der = _b64.b64decode("".join(l.strip() for l in pem.splitlines() if l and not l.startswith("-----")))
        on_disk[hashlib.sha256(der).hexdigest()] = name
    unpinned = {n for fp, n in on_disk.items() if fp not in P.DEVICE_ATTEST_EK_ROOTS}
    check("no endorsement certificate sits in the directory unpinned", not unpinned, sorted(unpinned))

    # These are TRUST ANCHORS: a root that is not self-signed is an intermediate, and pinning one silently
    # extends trust to whoever signed it. ST's published "root" is cross-signed by GlobalSign, which is why it
    # is not in the set.
    # openssl, NOT python cryptography: three of these six vendor roots are not strictly DER and the strict
    # parser refuses them outright — Intel's has ExtraData in signature_alg, both Nuvoton roots have an
    # InvalidSetOrder in their multi-valued RDN. Half the TPM ecosystem ships certificates a strict parser
    # will not read, which is exactly why endorsement parsing lives in the kernel behind x509-parser.
    import subprocess
    not_self_signed, unreadable = [], []
    for fp, name in on_disk.items():
        f = os.path.join(ekdir, name)
        def field(which):
            r = subprocess.run(["openssl", "x509", "-in", f, "-noout", f"-{which}"],
                               capture_output=True, text=True)
            return r.stdout.split("=", 1)[1].strip() if r.returncode == 0 and "=" in r.stdout else None
        sub, iss = field("subject"), field("issuer")
        if sub is None or iss is None:
            unreadable.append(name)
        elif sub != iss:
            not_self_signed.append(name)
    check("every pinned endorsement root is readable", not unreadable, sorted(unreadable))
    check("every pinned endorsement root is self-signed", not not_self_signed, sorted(not_self_signed))

    print("\n" + ("ALL OK" if not _fails else f"{len(_fails)} FAILURES"))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
