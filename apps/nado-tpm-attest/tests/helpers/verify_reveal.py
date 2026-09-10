#!/usr/bin/env python3
"""A NODE replaying someone else's challenge — the step that removes the need for a CA.

Given only public data (the endorsement public area, the AIK Name, the published blob, the client's
commitment) plus the challenger's reveal of (secret, seed), recompute the challenge and check it. No signing
key exists anywhere in this path; that is the entire point.

Exits 0 when the enrolment is genuine.
"""
import os
import sys

_here = os.path.abspath(__file__)
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(_here), "..", "..", "..", "..")))
from ops.tpm_aik import credential_commitment, verify_credential_reveal  # noqa: E402
from make_credential import spki_from_pub_area  # noqa: E402


def main():
    ek_pub, name, secret, seed, blob, commitment = (
        bytes.fromhex(sys.argv[1]), bytes.fromhex(sys.argv[2]), bytes.fromhex(sys.argv[3]),
        bytes.fromhex(sys.argv[4]), bytes.fromhex(sys.argv[5]), sys.argv[6])
    ek = spki_from_pub_area(ek_pub)
    ok = verify_credential_reveal(ek, name, secret, seed, blob, commitment)
    # A tampered reveal must fail, not merely differ: check one explicitly so a green run means something.
    tampered = verify_credential_reveal(ek, name, bytes(32), seed, blob, commitment)
    print("VERIFIED" if ok and not tampered else "REJECTED")
    return 0 if (ok and not tampered) else 1


if __name__ == "__main__":
    sys.exit(main())
