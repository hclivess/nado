#!/usr/bin/env python3
"""The challenge side, called by the swtpm end-to-end test: seal a random secret to an endorsement key, bound to
an attestation key's Name. Prints `secret credentialBlob encryptedSecret`, all hex.

This is the real ops/tpm_aik implementation — the point of the test is that a TPM accepts what IT produces, so
nothing here may reimplement any of it. No certificate is issued by this or by anything it calls.
"""
import os
import sys

# tests/helpers -> tests -> nado-tpm-attest -> apps -> the repo root, where ops/ lives
_here = os.path.abspath(__file__)
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(_here), "..", "..", "..", "..")))
from ops.tpm_aik import make_credential, rsa_public_numbers_from_spki  # noqa: E402


def spki_from_pub_area(pa: bytes) -> bytes:
    """A TPMT_PUBLIC's RSA key, re-encoded as a SubjectPublicKeyInfo — the form ops/tpm_aik takes, and the form
    the kernel hands back from a real endorsement certificate. Built by hand rather than with a library,
    because the code under test deliberately has no such dependency."""
    be16 = lambda o: int.from_bytes(pa[o:o + 2], "big")
    assert be16(0) == 0x0001, "not an RSA key"
    o = 10 + be16(8)                      # authPolicy's size is at 8, after type(2) nameAlg(2) attributes(4)
    sym = be16(o); o += 2
    if sym != 0x0010:
        o += 4                            # a non-NULL symmetric carries keyBits and mode
    scheme = be16(o); o += 2
    if scheme != 0x0010:
        o += 2
    o += 2                                # keyBits
    exponent = int.from_bytes(pa[o:o + 4], "big") or 65537
    o += 4
    modulus = pa[o + 2:o + 2 + be16(o)]

    def der(tag, body):
        if len(body) < 0x80:
            return bytes([tag, len(body)]) + body
        n = (len(body).bit_length() + 7) // 8
        return bytes([tag, 0x80 | n]) + len(body).to_bytes(n, "big") + body

    def integer(v: bytes):
        v = v.lstrip(b"\x00") or b"\x00"
        return der(0x02, (b"\x00" + v) if v[0] & 0x80 else v)

    rsa_pub = der(0x30, integer(modulus) + integer(exponent.to_bytes(4, "big")))
    alg = der(0x30, der(0x06, bytes.fromhex("2a864886f70d010101")) + der(0x05, b""))
    return der(0x30, alg + der(0x03, b"\x00" + rsa_pub))


def main():
    ek_pub = bytes.fromhex(sys.argv[1])
    aik_name = bytes.fromhex(sys.argv[2])
    # An EXPLICIT seed, because the whole CA-free construction rests on the credentialBlob being reproducible
    # from (seed, name, secret) by anyone, later, with no key involved.
    secret, seed = os.urandom(32), os.urandom(32)
    blob, enc = make_credential(spki_from_pub_area(ek_pub), aik_name, secret, seed=seed)
    print(secret.hex(), blob.hex(), enc.hex(), seed.hex())


if __name__ == "__main__":
    main()
