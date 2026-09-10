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
from ops.tpm_aik import make_credential  # noqa: E402


def rsa_public_from_pub_area(pa: bytes):
    """The modulus and exponent out of a TPMT_PUBLIC (TCG part 2 §12.2.4). The EK's parameters are the profile's
    — AES-128-CFB symmetric, NULL scheme — so the layout is fixed, but it is walked rather than assumed."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    be16 = lambda o: int.from_bytes(pa[o:o + 2], "big")
    assert be16(0) == 0x0001, "not an RSA key"
    policy = be16(8)          # authPolicy's size sits at 8, after type(2) nameAlg(2) attributes(4)
    o = 10 + policy
    sym = be16(o)
    o += 2
    if sym != 0x0010:                      # a non-NULL symmetric carries keyBits and mode
        o += 4
    scheme = be16(o)
    o += 2
    if scheme != 0x0010:
        o += 2
    o += 2                                  # keyBits
    exponent = int.from_bytes(pa[o:o + 4], "big") or 65537
    o += 4
    modulus = pa[o + 2:o + 2 + be16(o)]
    return rsa.RSAPublicNumbers(exponent, int.from_bytes(modulus, "big")).public_key()


def main():
    ek_pub = bytes.fromhex(sys.argv[1])
    aik_name = bytes.fromhex(sys.argv[2])
    # An EXPLICIT seed, because the whole CA-free construction rests on the credentialBlob being reproducible
    # from (seed, name, secret) by anyone, later, with no key involved.
    secret, seed = os.urandom(32), os.urandom(32)
    ek = rsa_public_from_pub_area(ek_pub)
    blob, enc = make_credential(ek, aik_name, secret, seed=seed)
    print(secret.hex(), blob.hex(), enc.hex(), seed.hex())


if __name__ == "__main__":
    main()
