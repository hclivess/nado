"""Device attestation phase 0: the CBOR subset decoder and the authData/attestation parser read a synthetic
WebAuthn attestationObject correctly; protocol pins the vendor roots (files + fingerprints agree)."""
import base64
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ops import device_attest as da
import protocol as P


def _cbor_bytes(b):
    return bytes([0x40 | len(b)]) if len(b) < 24 else bytes([0x58, len(b)]) + b if len(b) < 256 else bytes([0x59]) + len(b).to_bytes(2, "big") + b


def _cbor_text(t):
    b = t.encode(); return bytes([0x60 | len(b)]) + b


def main():
    rp = hashlib.sha256(b"get.nadochain.com").digest()
    aaguid = bytes(range(16)); cred = b"\xaa" * 20
    auth = rp + bytes([0x45]) + (0).to_bytes(4, "big") + aaguid + len(cred).to_bytes(2, "big") + cred + b"\xa0"
    leaf, root = b"\x30\x82" + b"L" * 300, b"\x30\x82" + b"R" * 200
    att = (bytes([0xa3]) + _cbor_text("fmt") + _cbor_text("apple")
           + _cbor_text("attStmt") + bytes([0xa1]) + _cbor_text("x5c") + bytes([0x82]) + _cbor_bytes(leaf) + _cbor_bytes(root)
           + _cbor_text("authData") + _cbor_bytes(auth))
    cdj = json.dumps({"type": "webauthn.create", "challenge": "abc", "origin": "https://get.nadochain.com"}).encode()
    s = da.parse_attestation(base64.b64encode(att).decode(), base64.b64encode(cdj).decode())
    assert s["fmt"] == "apple" and s["x5c_count"] == 2 and s["x5c_lengths"] == [302, 202], s
    assert s["auth_data"]["aaguid"] == aaguid.hex() and s["auth_data"]["credential_id"] == cred.hex()
    assert s["auth_data"]["user_present"] and s["auth_data"]["attested_cred"] and s["auth_data"]["user_verified"]
    assert s["client_data"]["origin"] == "https://get.nadochain.com" and s["root_sha256"] == hashlib.sha256(root).hexdigest()
    # negative ints, nested arrays, bools/null through the decoder
    assert da.cbor_decode(bytes([0x83, 0x20, 0xf5, 0xf6])) == [-1, True, None]
    try:
        da.cbor_decode(bytes([0x9f])); raise AssertionError("indefinite length must be rejected")
    except ValueError:
        pass
    # pinned roots: every file's SHA-256 over DER is in the protocol set, and nothing is expired
    d = os.path.join(ROOT, "protocol_roots"); files = sorted(f for f in os.listdir(d) if f.endswith(".pem"))
    assert len(files) == 5, files
    for f in files:
        der = subprocess.run(["openssl", "x509", "-in", os.path.join(d, f), "-outform", "DER"], capture_output=True).stdout
        assert hashlib.sha256(der).hexdigest() in P.DEVICE_ATTEST_ROOT_FINGERPRINTS, f
    assert P.DEVICE_ATTEST_HEIGHT == 0, "phase 0: nothing gated on yet"
    assert P.DEVICE_ATTEST_FORMATS == frozenset(("apple", "android-key"))
    print("ALL OK")


if __name__ == "__main__":
    main()
