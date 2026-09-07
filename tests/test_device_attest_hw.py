"""Hardware-wallet attestation formats in native/attest — `trezor` (Safe 3/5/7 device authentication: X.509 chain
signed by a bare P-256 root KEY, challenge signed by the device certificate's key) and `ledger` (factory
Issuer certificate over the device key + ephemeral certificate over BOTH nonces, secp256k1). Synthetic devices
built with openssl (Trezor) and coincurve (Ledger); every constraint has a negative. The consensus rule's
per-format constraints and the binding keys are pinned too. Run: python3 tests/test_device_attest_hw.py
"""
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="nado-hw-"))
from _attest_fixtures import cbor, sh   # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        fails += 1


CHAL = hashlib.blake2b(b"nado-hw-challenge", digest_size=32).digest()
NOW = 1_788_800_000


def b64(b):
    return base64.b64encode(b).decode()


def cdj(chal, typ="nado.hw"):
    return json.dumps({"type": typ, "challenge": base64.urlsafe_b64encode(chal).decode().rstrip("="), "origin": "https://get.nadochain.com"}).encode()


# ---- Trezor: root KEY -> CA cert -> device cert; challenge signed by the device key -------------------------------
def build_trezor(d, cn="T3T1 ABCDEF123456", serial="ABCDEF123456", ca_pathlen=0, root_signs_ca=True):
    def key(n): sh("openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", f"{d}/{n}.key")
    key("root"); key("ca"); key("dev")
    sh("openssl", "req", "-x509", "-new", "-key", f"{d}/root.key", "-sha256", "-days", "3650", "-subj", "/CN=Trezor Root Test", "-out", f"{d}/root.pem")
    ext = f"basicConstraints=critical,CA:TRUE,pathlen:{ca_pathlen}\nkeyUsage=critical,keyCertSign\n"
    open(f"{d}/ca.ext", "w").write(ext)
    sh("openssl", "req", "-new", "-key", f"{d}/ca.key", "-subj", "/CN=Trezor CA Test", "-out", f"{d}/ca.csr")
    signer = "root"
    if not root_signs_ca:                      # negative: a CA certificate issued by some OTHER root than the pinned one
        key("wrong"); signer = "wrong"
        sh("openssl", "req", "-x509", "-new", "-key", f"{d}/wrong.key", "-sha256", "-days", "3650", "-subj", "/CN=Trezor Root Test", "-out", f"{d}/wrong.pem")
    sh("openssl", "x509", "-req", "-in", f"{d}/ca.csr", "-CA", f"{d}/{signer}.pem", "-CAkey", f"{d}/{signer}.key", "-CAcreateserial", "-sha256", "-days", "3650",
       "-extfile", f"{d}/ca.ext", "-out", f"{d}/ca.pem")
    open(f"{d}/dev.ext", "w").write("basicConstraints=critical,CA:FALSE\n")
    sh("openssl", "req", "-new", "-key", f"{d}/dev.key", "-subj", f"/CN={cn}/serialNumber={serial}", "-out", f"{d}/dev.csr")
    sh("openssl", "x509", "-req", "-in", f"{d}/dev.csr", "-CA", f"{d}/ca.pem", "-CAkey", f"{d}/ca.key", "-CAcreateserial", "-sha256", "-days", "3650",
       "-extfile", f"{d}/dev.ext", "-out", f"{d}/dev.pem")
    der = lambda n: sh("openssl", "x509", "-in", f"{d}/{n}.pem", "-outform", "DER")
    spki = sh("openssl", "ec", "-in", f"{d}/root.key", "-pubout", "-outform", "DER")
    root_point = spki[-65:]
    assert root_point[0] == 0x04
    msg = bytes([19]) + b"AuthenticateDevice:" + bytes([len(CHAL)]) + CHAL
    sig = sh("openssl", "dgst", "-sha256", "-sign", f"{d}/dev.key", inp=msg)
    att = cbor({"fmt": "trezor", "attStmt": {"x5c": [der("dev"), der("ca")], "sig": sig}, "authData": b""})
    return att, root_point


def t_trezor():
    from ops import attest_native as A
    d = tempfile.mkdtemp()
    att, root = build_trezor(d)
    roots = [b"\x01" + root]
    v = A.verify(att, cdj(CHAL), CHAL, NOW, roots=roots, rp_ids=["get.nadochain.com"])
    check("trezor: synthetic Safe 5 chain verifies (model from CN, root = sha256 of the bare key)",
          v.get("ok") and v.get("fmt") == "trezor" and v.get("aaguid") == "T3T1" and v.get("root_sha256") == hashlib.sha256(root).hexdigest(), v)
    v = A.verify(att, cdj(CHAL), CHAL, NOW, roots=[b"\x01" + b"\x04" + os.urandom(64)], rp_ids=[])
    check("trezor: an unpinned root key refuses", not v.get("ok") and "root" in v.get("reason", ""), v.get("reason"))
    v = A.verify(att, cdj(os.urandom(32)), os.urandom(32), NOW, roots=roots, rp_ids=[])
    check("trezor: a different challenge refuses (device signature)", not v.get("ok") and "challenge" in v.get("reason", ""), v.get("reason"))
    v = A.verify(att, cdj(CHAL, typ="webauthn.create"), CHAL, NOW, roots=roots, rp_ids=[])
    check("trezor: clientData.type must be nado.hw", not v.get("ok") and "nado.hw" in v.get("reason", ""), v.get("reason"))
    att2, root2 = build_trezor(tempfile.mkdtemp(), cn="Trezor One 123", serial="123")
    v = A.verify(att2, cdj(CHAL), CHAL, NOW, roots=[b"\x01" + root2], rp_ids=[])
    check("trezor: a CN naming no Safe model refuses (Trezor One / Model T have no secure element)", not v.get("ok") and "model" in v.get("reason", ""), v.get("reason"))
    att3, root3 = build_trezor(tempfile.mkdtemp(), root_signs_ca=False)
    v = A.verify(att3, cdj(CHAL), CHAL, NOW, roots=[b"\x01" + root3], rp_ids=[])
    check("trezor: a CA certificate not signed by the root refuses", not v.get("ok"), v.get("reason"))
    v = A.verify(att, cdj(CHAL), CHAL, NOW + 20 * 365 * 86400, roots=roots, rp_ids=[])
    check("trezor: validity is judged at the anchor time", not v.get("ok") and "validity" in v.get("reason", ""), v.get("reason"))
    from ops.device_attest import device_binding_key, cbor_decode
    import protocol as P
    x5c0 = cbor_decode(att)["attStmt"]["x5c"][0]
    check("binding key = trezor:sha256(device certificate)", device_binding_key({"att": b64(att)}, P.DEVICE_BIND_MAX_CERT_SECS) == "trezor:" + hashlib.sha256(x5c0).hexdigest())


# ---- Ledger: issuer -> device key (cert0), device key -> ephemeral over nonces (cert1) --------------------------------
def build_ledger(host_nonce, issuer=None, device=None, bad_cert1=False):
    from coincurve import PrivateKey
    issuer = issuer or PrivateKey(); device = device or PrivateKey(); eph = PrivateKey()
    dev_pub, eph_pub = device.public_key.format(compressed=False), eph.public_key.format(compressed=False)
    hdr = bytes([0x01])
    sig0 = issuer.sign(bytes([0x02]) + hdr + dev_pub)                      # coincurve: DER, sha256 of the message
    cert0 = bytes([len(hdr)]) + hdr + bytes([65]) + dev_pub + bytes([len(sig0)]) + sig0
    device_nonce = os.urandom(8)
    m1 = bytes([0x12]) + device_nonce + host_nonce + eph_pub
    sig1 = (issuer if bad_cert1 else device).sign(m1)
    cert1 = bytes([0]) + bytes([65]) + eph_pub + bytes([len(sig1)]) + sig1
    st = {"target_id": bytes.fromhex("31100004"), "batch": bytes.fromhex("00000001"), "host_nonce": host_nonce,
          "device_nonce": device_nonce, "cert0": cert0, "cert1": cert1}
    att = cbor({"fmt": "ledger", "attStmt": st, "authData": b""})
    return att, issuer.public_key.format(compressed=False), dev_pub


def t_ledger():
    from ops import attest_native as A
    att, issuer_pub, dev_pub = build_ledger(CHAL[:8])
    roots = [b"\x02" + issuer_pub]
    v = A.verify(att, cdj(CHAL), CHAL, NOW, roots=roots, rp_ids=[])
    check("ledger: synthetic Nano S handshake verifies (issuer over device key, device over nonces + ephemeral)",
          v.get("ok") and v.get("fmt") == "ledger" and v.get("aaguid") == "31100004" and v.get("root_sha256") == hashlib.sha256(issuer_pub).hexdigest()
          and v.get("cred_id") == hashlib.sha256(dev_pub).hexdigest(), v)
    v = A.verify(att, cdj(CHAL), CHAL, NOW, roots=[b"\x02" + b"\x04" + os.urandom(64)], rp_ids=[])
    check("ledger: an unpinned issuer refuses", not v.get("ok") and "issuer" in v.get("reason", ""), v.get("reason"))
    att_bad, ip, _ = build_ledger(os.urandom(8))
    v = A.verify(att_bad, cdj(CHAL), CHAL, NOW, roots=[b"\x02" + ip], rp_ids=[])
    check("ledger: a host nonce that is not the challenge refuses (replay across registrations)", not v.get("ok") and "nonce" in v.get("reason", ""), v.get("reason"))
    att_c1, ip, _ = build_ledger(CHAL[:8], bad_cert1=True)
    v = A.verify(att_c1, cdj(CHAL), CHAL, NOW, roots=[b"\x02" + ip], rp_ids=[])
    check("ledger: an ephemeral certificate not signed by the device key refuses", not v.get("ok") and "ephemeral" in v.get("reason", ""), v.get("reason"))
    from ops.device_attest import device_binding_key
    import protocol as P
    check("binding key = ledger:sha256(device public key)", device_binding_key({"att": b64(att)}, P.DEVICE_BIND_MAX_CERT_SECS) == "ledger:" + hashlib.sha256(dev_pub).hexdigest())


def t_protocol_and_rule():
    import protocol as P
    from ops import attest_native as A
    check("formats accepted: trezor + ledger join android-key + tpm; bindable classes match", {"trezor", "ledger"} <= P.DEVICE_ATTEST_FORMATS and {"trezor", "ledger"} <= P.DEVICE_BIND_CLASSES)
    check("Trezor roots pinned per model (Safe 3 x2, Safe 5, Safe 7 + backup)", set(P.DEVICE_ATTEST_TREZOR_ROOTS) == {"T2B1", "T3B1", "T3T1", "T3W1"} and all(len(k) == 130 and k.startswith("04") for ks in P.DEVICE_ATTEST_TREZOR_ROOTS.values() for k in ks))
    check("Ledger issuer key pinned (ledgerblue DEFAULT_ISSUER_KEY)", P.DEVICE_ATTEST_LEDGER_ISSUER_KEYS[0].startswith("0490f5c9d15a0134bb019d2afd0bf297"))
    blob = A.pinned_roots_der()
    check("the roots blob carries the tagged vendor keys", sum(1 for r in blob if r[:1] == b"\x01") == sum(len(v) for v in P.DEVICE_ATTEST_TREZOR_ROOTS.values()) and sum(1 for r in blob if r[:1] == b"\x02") == len(P.DEVICE_ATTEST_LEDGER_ISSUER_KEYS))
    src = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
    seg = src[src.index("def verify_register_device"):src.index("def construct_register_tx")]
    check("rule: trezor root must be one of the model's pinned keys; ledger root must be the issuer",
          'fmt == "trezor"' in seg and "DEVICE_ATTEST_TREZOR_ROOTS.get(aaguid)" in seg and 'fmt == "ledger"' in seg and "DEVICE_ATTEST_LEDGER_ISSUER_KEYS" in seg)
    # certificate walks must ignore the tagged keys (a tagged key is not DER): the REAL Android vector through the
    # default blob, which now carries the vendor keys
    vec = json.load(open(os.path.join(ROOT, "tests", "vectors", "device_attest_android_key.json")))
    chal = base64.urlsafe_b64decode(vec["challenge_b64url"] + "=" * (-len(vec["challenge_b64url"]) % 4))
    v = A.verify(base64.b64decode(vec["att"]), base64.b64decode(vec["cdj"]), chal, int(vec["now_unix"]), rp_ids=[vec["rp"]])
    check("kernel: a WebAuthn statement still verifies with vendor keys in the default blob (chain walks skip them)", v.get("ok"), v.get("reason"))


def t_wallet_wiring():
    js = open(os.path.join(ROOT, "static", "hwattest.js")).read()
    ui = open(os.path.join(ROOT, "static", "interface.js")).read()
    html = open(os.path.join(ROOT, "static", "interface.html")).read()
    check("wallet: hwattest.js speaks both protocols and exports connect/attestHardware",
          "export async function connect(" in js and "export async function attestHardware(" in js and "0x2c97" in js and "0x1209" in js
          and 'apdu(0xe0, 0x52, 0x80, 0)' in js and "AuthenticateDevice" in js)
    check("wallet: the Ledger host nonce IS the challenge (binds the device signature to this registration)", "challenge.subarray(0, 8)" in js)
    check("wallet: the envelope is the same {att, cdj, rp} with clientData type nado.hw", 'type: "nado.hw"' in js)
    check("wallet: attestDevice routes to the hardware handle, connect happens in the click handler",
          'import("./hwattest.js' in ui and "state.hwDevice" in ui and 'hwPick("ledger")' in ui and 'hwPick("trezor")' in ui)
    check("wallet: Ledger / Trezor / this-device buttons under Start", 'id="btnHwLedger"' in html and 'id="btnHwTrezor"' in html and 'id="btnHwNone"' in html)
    check("wallet: attest from ANOTHER device — the receiving wallet polls the relay's drop store for its own address and registers with the statement",
          'id="btnHwRemote"' in html and 'attestVia === "remote"' in ui and '"/node_attest_pickup?sender=" + encodeURIComponent(state.wallet.address)' in ui
          and "buildRegisterTx(state.wallet, Number(fresh.max_block), null, nowSeconds(), fresh.device)" in ui)
    check("wallet: the card attests ANY address (wallet or node)", 'data-i18n="node.title">Attest another wallet or node' in html)
    i18n = open(os.path.join(ROOT, "static", "i18n.js")).read()
    check("i18n: hardware strings in all 16 languages", i18n.count('"hw.ledger"') == 16)


if __name__ == "__main__":
    t_trezor()
    t_ledger()
    t_protocol_and_rule()
    t_wallet_wiring()
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
