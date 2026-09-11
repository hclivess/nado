"""THE 'DIRECT' ENROLMENT IS FORGEABLE IN SOFTWARE. This test exists so it is not proposed again.

The idea: skip the interactive commit-reveal by creating the attestation key as a CHILD of the
endorsement key and having it certify its own creation, since TPMS_CREATION_DATA carries the parent's
name and any verifier can derive that name from the vendor certificate.

Every TPM command in it works — tests/test_tpm_certify_creation.py proves that against a real TPM 2.0.
The commands were never the problem. The verification is, and this constructs a message that passes
every check a verifier could make, with no TPM involved anywhere.

FOLLOW THE SIGNATURES, NOT THE FIELDS:
  - the vendor's signature covers the ENDORSEMENT key's public key and nothing else;
  - the creation attestation is signed by the CHILD, the key whose provenance is in question;
  - parentName is a claim inside a blob signed by the claimant.
There is no signature path from the vendor to the signing key. The WebAuthn `tpm` path works because
there IS one — x5c[0] is an AIK certificate, so a CA's signature reaches the signing key. The absence of
that certificate is the entire reason the commit-reveal exists.

An endorsement key is a restricted DECRYPTION key, so no signature by it can ever exist, so possession
can only be shown by decrypting something the prover could not predict — which requires someone else to
have chosen it. Interactive by construction, not by implementation.

Run: python3 tests/test_certify_creation_is_forgeable.py
"""
import hashlib
import os
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="nado-forge-"))
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def forge():
    """Build the whole enrolment message in software. Returns what a verifier would be handed."""
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.primitives import hashes

    # A victim's endorsement certificate is PUBLIC, so its public area — and therefore its name — is
    # public. Nothing here needs the victim's chip, their cooperation, or their knowledge.
    victim_ek_pubarea = b"\x00\x01\x00\x0b" + os.urandom(310)
    victim_ek_name = b"\x00\x0b" + hashlib.sha256(victim_ek_pubarea).digest()

    sw = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    n = sw.public_key().public_numbers().n.to_bytes(256, "big")
    child_pubarea = (struct.pack(">HHI", 0x0001, 0x000B, 0x00050472) + b"\x00\x00"
                     + struct.pack(">H", 0x0010) + struct.pack(">HH", 0x0014, 0x000B)
                     + struct.pack(">H", 2048) + struct.pack(">I", 0)
                     + struct.pack(">H", len(n)) + n)

    creation_data = (struct.pack(">I", 0) + struct.pack(">H", 0) + b"\x00" + b"\x00\x0b"
                     + struct.pack(">H", len(victim_ek_name)) + victim_ek_name
                     + struct.pack(">H", len(victim_ek_name)) + victim_ek_name
                     + struct.pack(">H", 0))
    creation_hash = hashlib.sha256(creation_data).digest()
    certify_info = (struct.pack(">IH", 0xFF544347, 0x801A)
                    + struct.pack(">H", 4) + b"fake"
                    + struct.pack(">H", 32) + os.urandom(32)
                    + b"\x00" * 17 + b"\x00" * 8
                    + struct.pack(">H", len(creation_hash)) + creation_hash)
    sig = sw.sign(certify_info, padding.PKCS1v15(), hashes.SHA256())
    return victim_ek_name, child_pubarea, creation_data, certify_info, sig


def main():
    from ops.tpm_aik import verify_rsassa_sha256, pub_area_rsa
    ek_name, child_pub, creation_data, certify_info, sig = forge()

    # Every check the proposed architecture would make, run against a message made with no TPM.
    check("a forged message carries the TPM_GENERATED magic",
          certify_info[:4] == b"\xff\x54\x43\x47")
    check("a forged message claims TPM_ST_ATTEST_CREATION",
          struct.unpack(">H", certify_info[4:6])[0] == 0x801A)
    o = 6
    o += 2 + struct.unpack(">H", certify_info[o:o + 2])[0]
    o += 2 + struct.unpack(">H", certify_info[o:o + 2])[0]
    o += 17 + 8
    certified = certify_info[o + 2:o + 2 + struct.unpack(">H", certify_info[o:o + 2])[0]]
    check("its certified creation hash matches its creation data",
          certified == hashlib.sha256(creation_data).digest())
    q = 4
    q += 2 + struct.unpack(">H", creation_data[q:q + 2])[0]
    q += 1 + 2
    pname = creation_data[q + 2:q + 2 + struct.unpack(">H", creation_data[q:q + 2])[0]]
    check("it names the victim's endorsement key as its parent", pname == ek_name)
    n, e = pub_area_rsa(child_pub)
    check("its signature verifies under its own public area",
          verify_rsassa_sha256(n, e, certify_info, sig))
    attrs = struct.unpack(">I", child_pub[4:8])[0]
    check("it declares itself restricted and sign",
          bool(attrs & 0x00010000) and bool(attrs & 0x00040000))

    print()
    print("  Every check above passed on a message built with a software RSA key and no TPM.")
    print("  The attributes, the magic, the type and the parent are all fields the forger authored.")
    print("  THE COMMIT-REVEAL IS NOT ACCIDENTAL COMPLEXITY: it is the only thing that makes the")
    print("  prover demonstrate something it could not have written down by itself.")
    print("\n" + ("ALL OK (the forgery succeeds, as it must)" if not _fails
                  else f"{len(_fails)} FAILURES"))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
