"""native/attest kernel: synthetic WebAuthn statements built with openssl-generated P-256 chains.
apple: nonce extension = sha256(authData || sha256(cdj)), chain leaf -> intermediate signed by a pinned root.
android-key: sig over authData || sha256(cdj), key-description ext carries clientDataHash + security levels.
Negative cases: wrong challenge, unpinned root, software security level, tampered signature, expired leaf."""
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ops import attest_native as AN

sys.path.insert(0, os.path.join(ROOT, 'tests'))
from _attest_fixtures import *  # noqa: F401,F403
def main():
    now = int(time.time())
    rp = "get.nadochain.com"
    chal = hashlib.blake2b(b"challenge", digest_size=32).digest()
    cdj = client_data(chal)
    cdj_hash = hashlib.sha256(cdj).digest()
    self_signed("root", "/CN=Test Vendor Root")
    root_der = der("root")
    self_signed("other", "/CN=Some Other Root")

    # ---- apple: leaf -> inter -> (pinned root, not in x5c)
    signed("inter", "/CN=Test WebAuthn CA 1", "root", ca_flag=True)
    key("leaf_a")
    x, y = pub_xy("leaf_a")
    ad = auth_data(rp, x, y)
    nonce = hashlib.sha256(ad + cdj_hash).digest()
    ext = f"1.2.840.113635.100.8.2=ASN1:SEQUENCE:nseq\n[nseq]\nn=EXPLICIT:1,FORMAT:HEX,OCTETSTRING:{nonce.hex()}\n"
    signed("leaf_a", "/CN=Apple device", "inter", ext_conf=ext)
    att = bytes([0xa3]) + cbor("fmt") + cbor("apple") + cbor("attStmt") + bytes([0xa1]) + cbor("x5c") + cbor([der("leaf_a"), der("inter")]) + cbor("authData") + cbor(ad)
    now = int(time.time()) + 120          # evaluate AFTER the certificates were minted (notBefore = mint time)
    r = AN.verify(att, cdj, chal, now, roots=[root_der], rp_ids=[rp])
    assert r["ok"], r
    assert r["fmt"] == "apple" and r["aaguid"] == "11" * 16, r
    r = AN.verify(att, cdj, b"\x00" * 32, now, roots=[root_der], rp_ids=[rp]); assert not r["ok"] and "challenge" in r["reason"], r
    r = AN.verify(att, cdj, chal, now, roots=[der("other")], rp_ids=[rp]); assert not r["ok"] and "issuer" in r["reason"], r
    r = AN.verify(att, cdj, chal, now, roots=[root_der], rp_ids=["evil.example"]); assert not r["ok"] and "rpIdHash" in r["reason"], r
    r = AN.verify(att, cdj, chal, now + 20 * 365 * 86400, roots=[root_der], rp_ids=[rp]); assert not r["ok"] and "validity" in r["reason"], r
    bad = att.replace(nonce[:4], b"\xde\xad\xbe\xef") if nonce[:4] in att else att
    # tamper the authData instead (nonce no longer matches)
    ad2 = ad[:-1] + bytes([ad[-1] ^ 1])
    att2 = bytes([0xa3]) + cbor("fmt") + cbor("apple") + cbor("attStmt") + bytes([0xa1]) + cbor("x5c") + cbor([der("leaf_a"), der("inter")]) + cbor("authData") + cbor(ad2)
    r = AN.verify(att2, cdj, chal, now, roots=[root_der], rp_ids=[rp]); assert not r["ok"], r

    # ---- android-key: leaf signed directly by the pinned root, root included in x5c; sig by leaf key
    def android(att_level, km_level, chal_in_ext, tamper=False):
        key("leaf_k")
        xk, yk = pub_xy("leaf_k")
        adk = auth_data(rp, xk, yk, aaguid=b"\x22" * 16)
        kd = (f"1.3.6.1.4.1.11129.2.1.17=ASN1:SEQUENCE:kd\n[kd]\nav=INTEGER:200\nasl=ENUMERATED:{att_level}\n"
              f"kv=INTEGER:200\nksl=ENUMERATED:{km_level}\nchal=FORMAT:HEX,OCTETSTRING:{chal_in_ext.hex()}\n"
              f"uid=FORMAT:HEX,OCTETSTRING:00\nsw=SEQUENCE:empty\ntee=SEQUENCE:empty\n[empty]\n")
        signed("leaf_k", "/CN=Android Keystore Key", "root", ext_conf=kd)
        msg = adk + cdj_hash
        open(os.path.join(D, "msg.bin"), "wb").write(msg)
        sig = sh("openssl", "dgst", "-sha256", "-sign", "leaf_k.key", "msg.bin")
        if tamper:
            sig = sig[:-1] + bytes([sig[-1] ^ 1])
        return (bytes([0xa3]) + cbor("fmt") + cbor("android-key") + cbor("attStmt")
                + bytes([0xa3]) + cbor("alg") + cbor(-7) + cbor("sig") + cbor(sig) + cbor("x5c") + cbor([der("leaf_k"), root_der])
                + cbor("authData") + cbor(adk))
    r = AN.verify(android(1, 1, cdj_hash), cdj, chal, now, roots=[root_der], rp_ids=[rp]); assert r["ok"] and r["security_level"] == 1, r
    r = AN.verify(android(2, 2, cdj_hash), cdj, chal, now, roots=[root_der], rp_ids=[rp]); assert r["ok"] and r["security_level"] == 2, r
    r = AN.verify(android(0, 1, cdj_hash), cdj, chal, now, roots=[root_der], rp_ids=[rp]); assert not r["ok"] and "software" in r["reason"], r
    r = AN.verify(android(1, 1, b"\x00" * 32), cdj, chal, now, roots=[root_der], rp_ids=[rp]); assert not r["ok"] and "attestationChallenge" in r["reason"], r
    r = AN.verify(android(1, 1, cdj_hash, tamper=True), cdj, chal, now, roots=[root_der], rp_ids=[rp]); assert not r["ok"] and "signature" in r["reason"], r
    # the production root set loads and is exactly the pinned five
    assert len(AN.pinned_roots_der()) == 6 + 240, "Apple, four Google, Microsoft TPM, plus the 240 FIDO metadata roots"
    print("ALL OK")


if __name__ == "__main__":
    main()
