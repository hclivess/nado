"""native/attest: the two computer formats over openssl-built chains.
packed  — FIDO2 security key: leaf v3, OU "Authenticator Attestation", AAGUID extension, sig over authData || cdjHash.
tpm     — Windows Hello: pubArea (TPMT_PUBLIC) == credential key, certInfo (TPMS_ATTEST certify) with extraData =
          hash(authData || cdjHash) and attested name = nameAlg(pubArea), signed by an AIK cert (empty subject, AIK
          EKU, SAN with the TPM manufacturer). Negatives for every constraint the consensus rule relies on."""
import base64
import hashlib
import json
import os
import struct
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _attest_fixtures as FX
from _attest_fixtures import D, sh, key, self_signed, signed, der, pub_xy, cbor, cbor_map, cose_key, auth_data, client_data
from ops import attest_native as AN


def att_obj(fmt, st_pairs, ad):
    st = bytes([0xa0 | len(st_pairs)]) + b"".join(cbor(k) + (v if isinstance(v, bytes) and k == "__raw__" else cbor(v)) for k, v in st_pairs)
    return bytes([0xa3]) + cbor("fmt") + cbor(fmt) + cbor("attStmt") + st + cbor("authData") + cbor(ad)


def sign_p256(name, msg):
    open(os.path.join(D, "msg.bin"), "wb").write(msg)
    return sh("openssl", "dgst", "-sha256", "-sign", f"{name}.key", "msg.bin")


def main():
    rp = "get.nadochain.com"
    chal = hashlib.blake2b(b"pc", digest_size=32).digest()
    cdj = client_data(chal); cdj_hash = hashlib.sha256(cdj).digest()
    self_signed("root", "/CN=Test Vendor Root"); root_der = der("root")
    now = int(time.time()) + 120

    # ---------------- packed
    aaguid = bytes.fromhex("aa" * 16)
    def packed(ou="Authenticator Attestation", ext_aaguid=aaguid, ca_leaf=False, root_for_chain=None):
        key("leaf_p"); x, y = pub_xy("leaf_p")
        ad = auth_data(rp, x, y, aaguid=aaguid)
        ext = f"1.3.6.1.4.1.45724.1.1.4=ASN1:FORMAT:HEX,OCTETSTRING:{ext_aaguid.hex()}\n" if ext_aaguid else ""
        signed("leaf_p", f"/C=US/O=Test Key Co/OU={ou}/CN=Test Key", "root", ext_conf=ext, ca_flag=ca_leaf)
        sig = sign_p256("leaf_p", ad + cdj_hash)
        att = att_obj("packed", [("alg", -7), ("sig", sig), ("x5c", [der("leaf_p"), root_der])], ad)
        os.remove(os.path.join(D, "leaf_p.key"))
        return att
    r = AN.verify(packed(), cdj, chal, now, roots=[root_der], rp_ids=[rp]); assert r["ok"] and r["fmt"] == "packed" and r["root_sha256"] == hashlib.sha256(root_der).hexdigest(), r
    r = AN.verify(packed(ou="Something Else"), cdj, chal, now, roots=[root_der], rp_ids=[rp]); assert not r["ok"] and "OU" in r["reason"], r
    r = AN.verify(packed(ext_aaguid=bytes.fromhex("bb" * 16)), cdj, chal, now, roots=[root_der], rp_ids=[rp]); assert not r["ok"] and "AAGUID" in r["reason"], r
    r = AN.verify(packed(ext_aaguid=None), cdj, chal, now, roots=[root_der], rp_ids=[rp]); assert r["ok"], "AAGUID extension is optional per spec"
    r = AN.verify(packed(ca_leaf=True), cdj, chal, now, roots=[root_der], rp_ids=[rp]); assert not r["ok"] and "CA" in r["reason"], r
    self_signed("other", "/CN=Other Root")
    r = AN.verify(packed(), cdj, chal, now, roots=[der("other")], rp_ids=[rp]); assert not r["ok"], "unpinned root accepted"

    # ---------------- tpm (ECC P-256 key in pubArea, SHA-256 nameAlg, ES256 AIK signature)
    def tpm(manufacturer="id:49465800", eku="2.23.133.8.3", subject_empty=True, bad_name=False, bad_extra=False, wrong_key=False):
        key("cred_t"); x, y = pub_xy("cred_t")
        ad = auth_data(rp, x, y, aaguid=bytes.fromhex("08987058cadc4b81b6e130de50dcbe96"))
        # TPMT_PUBLIC: type ECC(0x0023), nameAlg SHA256(0x000b), attrs, authPolicy(empty), symmetric NULL, scheme NULL, curve P256(0x0003), kdf NULL, x, y
        kx, ky = (x, y) if not wrong_key else (y, x)
        pub_area = struct.pack(">HHI", 0x0023, 0x000b, 0x00050072) + struct.pack(">H", 0) + struct.pack(">H", 0x0010) + struct.pack(">H", 0x0010) + struct.pack(">H", 0x0003) + struct.pack(">H", 0x0010) + struct.pack(">H", len(kx)) + kx + struct.pack(">H", len(ky)) + ky
        name = struct.pack(">H", 0x000b) + hashlib.sha256(pub_area).digest()
        if bad_name: name = name[:-1] + bytes([name[-1] ^ 1])
        extra = hashlib.sha256(ad + cdj_hash).digest()
        if bad_extra: extra = b"\0" * 32
        cert_info = (struct.pack(">IH", 0xff544347, 0x8017) + struct.pack(">H", 0) + struct.pack(">H", len(extra)) + extra
                     + struct.pack(">QIIB", 1, 0, 0, 1) + struct.pack(">Q", 0) + struct.pack(">H", len(name)) + name + struct.pack(">H", 0))
        # AIK certificate: empty subject, EKU AIK, SAN directoryName with the TPM manufacturer/model/version
        key("aik")
        conf = os.path.join(D, "aik.ext")
        with open(conf, "w") as f:
            f.write("[ext]\nbasicConstraints=CA:FALSE\n")
            f.write(f"extendedKeyUsage={eku}\n")
            # SAN = SEQUENCE { [4] EXPLICIT Name }, Name = SEQUENCE OF SET OF SEQUENCE { OID, UTF8String } — raw ASN.1,
            # because openssl's dirName section cannot name the TCG attribute OIDs from an extfile
            f.write("subjectAltName=ASN1:SEQUENCE:san\n[san]\ndn=EXPLICIT:4,SEQUENCE:rdns\n[rdns]\nr1=SET:rdn1\nr2=SET:rdn2\nr3=SET:rdn3\n")
            f.write("[rdn1]\na=SEQUENCE:atv1\n[atv1]\noid=OID:2.23.133.2.1\nval=UTF8:" + manufacturer + "\n")
            f.write("[rdn2]\na=SEQUENCE:atv2\n[atv2]\noid=OID:2.23.133.2.2\nval=UTF8:TestTPM\n")
            f.write("[rdn3]\na=SEQUENCE:atv3\n[atv3]\noid=OID:2.23.133.2.3\nval=UTF8:id:00010000\n")
        sh("openssl", "req", "-new", "-key", "aik.key", "-subj", "/CN=tmp" if not subject_empty else "/", "-out", "aik.csr")
        sh("openssl", "x509", "-req", "-in", "aik.csr", "-CA", "root.pem", "-CAkey", "root.key", "-CAcreateserial", "-days", "365", "-sha256",
           "-extfile", conf, "-extensions", "ext", "-out", "aik.pem")
        sig = sign_p256("aik", cert_info)
        att = att_obj("tpm", [("ver", "2.0"), ("alg", -7), ("sig", sig), ("x5c", [der("aik"), root_der]), ("certInfo", cert_info), ("pubArea", pub_area)], ad)
        for k in ("cred_t.key", "aik.key"): os.remove(os.path.join(D, k))
        return att
    r = AN.verify(tpm(), cdj, chal, now, roots=[root_der], rp_ids=[rp]); assert r["ok"] and r["fmt"] == "tpm" and r["tpm_manufacturer"] == "49465800", r
    r = AN.verify(tpm(manufacturer="id:4D534654"), cdj, chal, now, roots=[root_der], rp_ids=[rp]); assert r["ok"] and r["tpm_manufacturer"] == "4D534654", "kernel reports; consensus rule rejects MSFT"
    r = AN.verify(tpm(eku="serverAuth"), cdj, chal, now, roots=[root_der], rp_ids=[rp]); assert not r["ok"] and "extended key usage" in r["reason"], r
    r = AN.verify(tpm(subject_empty=False), cdj, chal, now, roots=[root_der], rp_ids=[rp]); assert not r["ok"] and "subject" in r["reason"], r
    r = AN.verify(tpm(bad_name=True), cdj, chal, now, roots=[root_der], rp_ids=[rp]); assert not r["ok"] and "name" in r["reason"], r
    r = AN.verify(tpm(bad_extra=True), cdj, chal, now, roots=[root_der], rp_ids=[rp]); assert not r["ok"] and "extraData" in r["reason"], r
    r = AN.verify(tpm(wrong_key=True), cdj, chal, now, roots=[root_der], rp_ids=[rp]); assert not r["ok"] and "pubArea key" in r["reason"], r
    print("ALL OK")


if __name__ == "__main__":
    main()
