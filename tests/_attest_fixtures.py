"""Synthetic WebAuthn attestation statements over openssl-generated P-256 chains — shared by the kernel test
and the consensus-rule test. NOT real vendor chains: callers pin the test root themselves."""
import base64
import hashlib
import json
import os
import subprocess
import tempfile

D = tempfile.mkdtemp()


def sh(*a, inp=None):
    r = subprocess.run(list(a), input=inp, capture_output=True, cwd=D)
    if r.returncode:
        raise RuntimeError(f"{a}: {r.stderr.decode()[:300]}")
    return r.stdout


def key(name):
    sh("openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", f"{name}.key")


def self_signed(name, subj, days="3650"):
    key(name)
    sh("openssl", "req", "-x509", "-new", "-key", f"{name}.key", "-subj", subj, "-days", days, "-sha256",
       "-addext", "basicConstraints=critical,CA:TRUE", "-out", f"{name}.pem")


def signed(name, subj, ca, ext_conf=None, ca_flag=False, days="3650"):
    if not os.path.exists(os.path.join(D, f"{name}.key")):
        key(name)                                   # keep a key made earlier (its public half is already in authData)
    sh("openssl", "req", "-new", "-key", f"{name}.key", "-subj", subj, "-out", f"{name}.csr")
    conf = os.path.join(D, f"{name}.ext")
    with open(conf, "w") as f:
        f.write("[ext]\n")
        f.write("basicConstraints=critical,CA:TRUE\n" if ca_flag else "basicConstraints=CA:FALSE\n")
        if ext_conf:
            f.write(ext_conf)
    sh("openssl", "x509", "-req", "-in", f"{name}.csr", "-CA", f"{ca}.pem", "-CAkey", f"{ca}.key", "-CAcreateserial",
       "-days", days, "-sha256", "-extfile", conf, "-extensions", "ext", "-out", f"{name}.pem")


def der(name):
    return sh("openssl", "x509", "-in", f"{name}.pem", "-outform", "DER")


def pub_xy(name):
    raw = sh("openssl", "ec", "-in", f"{name}.key", "-pubout", "-outform", "DER")
    pt = raw[-65:]
    assert pt[0] == 4
    return pt[1:33], pt[33:65]


def cbor_map(pairs):
    out = bytes([0xa0 | len(pairs)])
    for k, v in pairs:
        out += cbor(k) + cbor(v)
    return out


def cbor(v):
    if isinstance(v, str):
        b = v.encode(); return (bytes([0x60 | len(b)]) if len(b) < 24 else bytes([0x78, len(b)])) + b
    if isinstance(v, bytes):
        n = len(v)
        return (bytes([0x40 | n]) if n < 24 else bytes([0x58, n]) if n < 256 else bytes([0x59]) + n.to_bytes(2, "big")) + v
    if isinstance(v, list):
        return bytes([0x80 | len(v)]) + b"".join(cbor(x) for x in v)
    if isinstance(v, int):
        if v >= 0:
            return bytes([v]) if v < 24 else bytes([0x18, v])
        n = -1 - v
        return bytes([0x20 | n]) if n < 24 else bytes([0x38, n])
    raise TypeError(v)


def cose_key(x, y):
    return cbor_map([(1, 2), (3, -7), (-1, 1), (-2, x), (-3, y)])


def auth_data(rp, x, y, aaguid=b"\x11" * 16, cred=b"\xc0" * 16):
    return hashlib.sha256(rp.encode()).digest() + bytes([0x45]) + b"\0\0\0\1" + aaguid + len(cred).to_bytes(2, "big") + cred + cose_key(x, y)


def client_data(chal):
    return json.dumps({"type": "webauthn.create", "challenge": base64.urlsafe_b64encode(chal).decode().rstrip("="),
                       "origin": "https://get.nadochain.com"}).encode()




def build_apple(rp, chal, origin="https://get.nadochain.com"):
    """(attestationObject, clientDataJSON, root_der) for an apple-format statement whose chain is
    leaf -> intermediate, signed by a fresh self-signed test root (returned, not in x5c)."""
    self_signed("root", "/CN=Test Vendor Root")
    root_der = der("root")
    signed("inter", "/CN=Test WebAuthn CA 1", "root", ca_flag=True)
    key("leaf_a")
    x, y = pub_xy("leaf_a")
    ad = auth_data(rp, x, y)
    cdj = json.dumps({"type": "webauthn.create", "challenge": base64.urlsafe_b64encode(chal).decode().rstrip("="),
                      "origin": origin}).encode()
    nonce = hashlib.sha256(ad + hashlib.sha256(cdj).digest()).digest()
    ext = f"1.2.840.113635.100.8.2=ASN1:SEQUENCE:nseq\n[nseq]\nn=EXPLICIT:1,FORMAT:HEX,OCTETSTRING:{nonce.hex()}\n"
    signed("leaf_a", "/CN=Apple device", "inter", ext_conf=ext)
    att = (bytes([0xa3]) + cbor("fmt") + cbor("apple") + cbor("attStmt") + bytes([0xa1]) + cbor("x5c")
           + cbor([der("leaf_a"), der("inter")]) + cbor("authData") + cbor(ad))
    return att, cdj, root_der
