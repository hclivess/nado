"""APPLE APP ATTEST BRIDGE (doc/apple-app-attest.md): kernel formats `apple-appattest` + `apple-assertion`, the binding key,
the consensus dormancy (no App ID pinned, height 0), the wallet handoff and the app's BLAKE2b (ported line by line from
Blake2b.swift and compared with hashlib). SYNTHETIC vectors only — there is no real iPhone sample; this test proves the
plumbing, not Apple support. Run: python3 tests/test_apple_app_attest.py
"""
import base64
import hashlib
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-appattest-")
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


APP_ID = "ABCDE12345.com.nadochain.attest"
AAGUID_PROD = b"appattest" + b"\0" * 7


def build(chal, aaguid=AAGUID_PROD, counter=0, cred=None, cdj_type="nado.app", rp=APP_ID):
    from _attest_fixtures import self_signed, signed, key, pub_xy, der, cose_key, cbor
    self_signed("aroot", "/CN=Test App Attest Root")
    root_der = der("aroot")
    signed("aca", "/CN=Test App Attestation CA 1", "aroot", ca_flag=True)
    key("akey")
    x, y = pub_xy("akey")
    point = b"\x04" + x + y
    cred = hashlib.sha256(point).digest() if cred is None else cred
    ad = (hashlib.sha256(rp.encode()).digest() + bytes([0x40]) + counter.to_bytes(4, "big") + aaguid
          + len(cred).to_bytes(2, "big") + cred + cose_key(x, y))
    cdj = json.dumps({"type": cdj_type, "challenge": base64.urlsafe_b64encode(chal).decode().rstrip("="), "origin": rp}).encode()
    nonce = hashlib.sha256(ad + hashlib.sha256(cdj).digest()).digest()
    ext = f"1.2.840.113635.100.8.2=ASN1:SEQUENCE:nseq\n[nseq]\nn=EXPLICIT:1,FORMAT:HEX,OCTETSTRING:{nonce.hex()}\n"
    signed("akey", "/CN=App Attest key", "aca", ext_conf=ext)
    att = (bytes([0xa3]) + cbor("fmt") + cbor("apple-appattest") + cbor("attStmt") + bytes([0xa2]) + cbor("x5c")
           + cbor([der("akey"), der("aca")]) + cbor("receipt") + cbor(b"\x30\x80") + cbor("authData") + cbor(ad))
    return att, cdj, root_der, point, der("akey")


def build_assertion(chal, point, keyname="akey", counter=3, rp=APP_ID, cdj_type="nado.app", pub=None):
    from _attest_fixtures import sh, cbor, D
    ad = hashlib.sha256(rp.encode()).digest() + bytes([0x00]) + counter.to_bytes(4, "big")
    cdj = json.dumps({"type": cdj_type, "challenge": base64.urlsafe_b64encode(chal).decode().rstrip("="), "origin": rp}).encode()
    nonce = hashlib.sha256(ad + hashlib.sha256(cdj).digest()).digest()
    open(os.path.join(D, "nonce.bin"), "wb").write(nonce)                      # openssl runs with cwd=D
    sig = sh("openssl", "dgst", "-sha256", "-sign", f"{keyname}.key", "nonce.bin")
    att = (bytes([0xa2]) + cbor("fmt") + cbor("apple-assertion") + cbor("attStmt") + bytes([0xa3])
           + cbor("authData") + cbor(ad) + cbor("pub") + cbor(pub or point) + cbor("sig") + cbor(sig))
    return att, cdj


def t_kernel():
    from ops import attest_native as AN
    import protocol as P
    chal = hashlib.blake2b(b"apple test", digest_size=32).digest()
    now = 1_800_000_000
    att, cdj, root, point, leaf = build(chal)
    r = AN.verify(att, cdj, chal, now, roots=[root], rp_ids=[APP_ID])
    check("kernel: synthetic App Attest statement verifies", r["ok"], r)
    check("kernel: cred_id is sha256(point)", r.get("cred_id") == hashlib.sha256(point).hexdigest(), r.get("cred_id"))
    check("kernel: aaguid reported as production", bytes.fromhex(r.get("aaguid", "")) == AAGUID_PROD, r.get("aaguid"))
    r = AN.verify(att, cdj, chal, now, roots=[root], rp_ids=["OTHER.com.example"]); check("kernel: rpIdHash must be a pinned App ID", not r["ok"] and "rp" in r["reason"], r)
    r = AN.verify(att, cdj, b"\0" * 32, now, roots=[root], rp_ids=[APP_ID]); check("kernel: challenge bound", not r["ok"] and "challenge" in r["reason"], r)
    att2, cdj2, root2, _, _ = build(chal, aaguid=b"appattestdevelop"); r = AN.verify(att2, cdj2, chal, now, roots=[root2], rp_ids=[APP_ID])
    check("kernel: development aaguid refused", not r["ok"] and "aaguid" in r["reason"], r)
    att3, cdj3, root3, _, _ = build(chal, counter=1); r = AN.verify(att3, cdj3, chal, now, roots=[root3], rp_ids=[APP_ID])
    check("kernel: counter must be 0", not r["ok"] and "counter" in r["reason"], r)
    att4, cdj4, root4, _, _ = build(chal, cred=b"\xc0" * 32); r = AN.verify(att4, cdj4, chal, now, roots=[root4], rp_ids=[APP_ID])
    check("kernel: credentialId must be sha256(leaf key)", not r["ok"] and "credentialId" in r["reason"], r)
    att5, cdj5, root5, _, _ = build(chal, cdj_type="webauthn.create"); r = AN.verify(att5, cdj5, chal, now, roots=[root5], rp_ids=[APP_ID])
    check("kernel: clientData.type must be nado.app", not r["ok"] and "nado.app" in r["reason"], r)
    # assertion by the same key
    att, cdj, root, point, leaf = build(chal)
    a_att, a_cdj = build_assertion(chal, point)
    r = AN.verify(a_att, a_cdj, chal, now, roots=[], rp_ids=[APP_ID])
    check("kernel: assertion by the attested key verifies (no chain needed)", r["ok"] and r.get("fmt") == "apple-assertion", r)
    check("kernel: assertion cred_id == attestation cred_id", r.get("cred_id") == hashlib.sha256(point).hexdigest())
    r = AN.verify(a_att, a_cdj, b"\1" * 32, now, roots=[], rp_ids=[APP_ID]); check("kernel: assertion challenge bound", not r["ok"], r)
    from _attest_fixtures import key, pub_xy
    key("other"); ox, oy = pub_xy("other")
    b_att, b_cdj = build_assertion(chal, point, pub=b"\x04" + ox + oy)
    r = AN.verify(b_att, b_cdj, chal, now, roots=[], rp_ids=[APP_ID]); check("kernel: assertion signature must match pub", not r["ok"] and "signature" in r["reason"], r)
    r = AN.verify(a_att, a_cdj, chal, now, roots=[], rp_ids=["OTHER.com.example"]); check("kernel: assertion rpIdHash must be a pinned App ID", not r["ok"], r)
    # the real root is pinned and carried
    from ops.attest_native import pinned_roots_der
    fps = {hashlib.sha256(d).hexdigest() for d in pinned_roots_der()}
    check("the Apple App Attestation Root CA is pinned in protocol and carried in the roots blob",
          P.DEVICE_ATTEST_APPLE_APP_ATTEST_ROOT in P.DEVICE_ATTEST_ROOT_FINGERPRINTS and P.DEVICE_ATTEST_APPLE_APP_ATTEST_ROOT in fps)
    return att, cdj, point, a_att


def t_binding_and_rules(att, cdj, point, a_att):
    from ops.device_attest import device_binding_key
    import protocol as P
    k1 = device_binding_key({"att": base64.b64encode(att).decode()}, P.DEVICE_BIND_MAX_CERT_SECS, strict=True)
    k2 = device_binding_key({"att": base64.b64encode(a_att).decode()}, P.DEVICE_BIND_MAX_CERT_SECS, strict=True)
    check("binding key: attestation binds on sha256(key point)", k1 == "apple-appattest:" + hashlib.sha256(point).hexdigest(), k1)
    check("binding key: an assertion resolves to the SAME row", k1 == k2, (k1, k2))
    check("class: apple-appattest is bindable and permanent", "apple-appattest" in P.DEVICE_BIND_CLASSES and "apple-appattest" in P.DEVICE_BIND_PERMANENT_CLASSES)
    check("formats: both app formats are known to the format list", {"apple-appattest", "apple-assertion"} <= P.DEVICE_ATTEST_FORMATS)
    check("DORMANT: no App ID pinned and height 0 until a real team signs the app", P.DEVICE_ATTEST_APPLE_APP_IDS == () and P.DEVICE_ATTEST_APPLE_HEIGHT == 0)
    src = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
    check("validation: app formats use the PINNED App IDs only (never the tx rp) and are refused until enabled",
          'if fmt_pre in ("apple-appattest", "apple-assertion"):' in src and "rp_list = list(DEVICE_ATTEST_APPLE_APP_IDS)" in src
          and "Apple App Attest statements are not enabled on this chain yet" in src)
    check("validation: an assertion needs the key's binding row", "this key never attested (no binding row)" in src)
    check("validation: the attestation chain must end at the App Attest root", "DEVICE_ATTEST_APPLE_APP_ATTEST_ROOT" in src)
    js = open(os.path.join(ROOT, "static", "interface.js")).read()
    check("wallet: the handoff button exists and is HIDDEN until the app ships", "const APPLE_APP_LIVE = false;" in js and 'show("btnHwApple", APPLE_APP_LIVE)' in js and "nadoattest://attest?addr=" in js)
    i18n = open(os.path.join(ROOT, "static", "i18n.js")).read()
    n = i18n.count('"hw.apple":'); check("i18n: hw.apple in every language", n >= 16 and n % 16 == 0, n)
    for f in ("README.md", "Config.swift", "Blake2b.swift", "Envelope.swift", "Relay.swift", "AttestService.swift", "ContentView.swift", "NadoAttestApp.swift", "NadoAttest.entitlements"):
        p = os.path.join(ROOT, "apps", "nado-attest-ios", "NadoAttest" if f != "README.md" else "", f)
        check(f"app source present: {f}", os.path.exists(p), p)
    cfg = open(os.path.join(ROOT, "apps", "nado-attest-ios", "NadoAttest", "Config.swift")).read()
    check("app Config mirrors the chain id and anchor offset", f'chainId = "{P.CHAIN_ID}"' in cfg and f"anchorOffset = {P.POSW_ANCHOR_OFFSET}" in cfg)


def t_real_ipad_vector():
    """THE FIRST REAL APPLE STATEMENT (iPad, iPadOS 26.6.1, Swift Playgrounds build, 2026-09-07): chain to the PINNED Apple
    App Attestation Root CA, nonce in the leaf, credentialId = sha256(key), production aaguid, counter 0, 164-byte authData
    (87 + a 77-byte COSE key, no extensions). The rpIdHash is checked by the kernel against the pinned App ID once one is
    pinned; here every other field is verified independently of it."""
    import subprocess
    v = json.load(open(os.path.join(ROOT, "tests", "vectors", "device_attest_apple_appattest_ipad_2026-09-07.json")))
    raw = v.get("raw") or v
    att = base64.b64decode(raw["att"]); cdj = base64.b64decode(raw["cdj"])
    from ops.device_attest import cbor_decode, cert_spki_point
    import protocol as P
    a = cbor_decode(att, strict=True); ad = bytes(a["authData"]); x5c = [bytes(c) for c in a["attStmt"]["x5c"]]
    check("real: fmt apple-appattest with a 2-certificate chain and a receipt", a["fmt"] == "apple-appattest" and len(x5c) == 2 and len(a["attStmt"].get("receipt") or b"") > 1000)
    check("real: authData is 164 bytes = 87 + 77-byte COSE key, no trailing extensions", len(ad) == 164)
    check("real: production aaguid, counter 0, AT flag only", ad[37:53] == AAGUID_PROD and ad[33:37] == b"\0\0\0\0" and ad[32] == 0x40)
    point = cert_spki_point(x5c[0]); n = int.from_bytes(ad[53:55], "big")
    check("real: credentialId == sha256(leaf key point)", ad[55:55 + n] == hashlib.sha256(point).digest())
    d = tempfile.mkdtemp()
    for i, c in enumerate(x5c):
        open(f"{d}/c{i}.der", "wb").write(c)
        subprocess.run(["openssl", "x509", "-inform", "DER", "-in", f"{d}/c{i}.der", "-out", f"{d}/c{i}.pem"], check=True, capture_output=True)
    r = subprocess.run(["openssl", "verify", "-CAfile", os.path.join(ROOT, "protocol_roots", "apple_app_attest_root_ca.pem"), "-untrusted", f"{d}/c1.pem", f"{d}/c0.pem"], capture_output=True, text=True)
    check("real: chain verifies to the pinned Apple App Attestation Root CA (openssl)", r.returncode == 0 and ": OK" in r.stdout, r.stdout + r.stderr)
    nonce = hashlib.sha256(ad + hashlib.sha256(cdj).digest()).digest()
    asn = subprocess.run(["openssl", "asn1parse", "-inform", "DER", "-in", f"{d}/c0.der"], capture_output=True, text=True).stdout.replace("\n", "").upper()
    check("real: nonce = sha256(authData || sha256(clientDataJSON)) is in the leaf's 1.2.840.113635.100.8.2 extension", nonce.hex().upper() in asn)
    from ops.device_attest import device_binding_key
    check("real: binding key is apple-appattest:sha256(point)", device_binding_key({"att": raw["att"]}, P.DEVICE_BIND_MAX_CERT_SECS, strict=True) == "apple-appattest:" + hashlib.sha256(point).hexdigest())
    cd = json.loads(cdj)
    check("real: clientData type nado.app", cd.get("type") == "nado.app")
    from ops import attest_native as AN
    r = AN.verify(att, cdj, base64.urlsafe_b64decode(cd["challenge"] + "=" * (-len(cd["challenge"]) % 4)), 1788804290, rp_ids=list(P.DEVICE_ATTEST_APPLE_APP_IDS))
    if P.DEVICE_ATTEST_APPLE_APP_IDS:
        check("real: the kernel accepts it under the pinned App ID", r["ok"], r)
    else:
        check("real: with no App ID pinned the kernel refuses on rpIdHash and nothing else", (not r["ok"]) and "rp" in r["reason"], r)


def t_blake2b_port():
    """Line-by-line Python port of apps/nado-attest-ios/NadoAttest/Blake2b.swift, checked against hashlib — the app's
    challenge must be byte-exact with the chain's."""
    IV = [0x6a09e667f3bcc908, 0xbb67ae8584caa73b, 0x3c6ef372fe94f82b, 0xa54ff53a5f1d36f1,
          0x510e527fade682d1, 0x9b05688c2b3e6c1f, 0x1f83d9abfb41bd6b, 0x5be0cd19137e2179]
    S = [[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15],[14,10,4,8,9,15,13,6,1,12,0,2,11,7,5,3],[11,8,12,0,5,2,15,13,10,14,3,6,7,1,9,4],
         [7,9,3,1,13,12,11,14,2,6,5,10,4,0,15,8],[9,0,5,7,2,4,10,15,14,1,11,12,6,8,3,13],[2,12,6,10,0,11,8,3,4,13,7,5,15,14,1,9],
         [12,5,1,15,14,13,4,10,0,7,6,3,9,2,8,11],[13,11,7,14,12,1,3,9,5,0,15,4,8,6,2,10],[6,15,14,9,11,3,0,8,12,2,13,7,1,4,10,5],
         [10,2,8,4,7,6,1,5,15,11,9,14,3,12,13,0],[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15],[14,10,4,8,9,15,13,6,1,12,0,2,11,7,5,3]]
    M = (1 << 64) - 1
    def rotr(x, n): return ((x >> n) | (x << (64 - n))) & M
    def compress(h, block, t, last):
        m = [int.from_bytes(block[i*8:i*8+8], "little") for i in range(16)]
        v = h + IV
        v[12] ^= t & M
        if last: v[14] = (~v[14]) & M
        def g(a, b, c, d, x, y):
            v[a] = (v[a] + v[b] + x) & M; v[d] = rotr(v[d] ^ v[a], 32)
            v[c] = (v[c] + v[d]) & M; v[b] = rotr(v[b] ^ v[c], 24)
            v[a] = (v[a] + v[b] + y) & M; v[d] = rotr(v[d] ^ v[a], 16)
            v[c] = (v[c] + v[d]) & M; v[b] = rotr(v[b] ^ v[c], 63)
        for r in range(12):
            s = S[r]
            g(0,4,8,12,m[s[0]],m[s[1]]); g(1,5,9,13,m[s[2]],m[s[3]]); g(2,6,10,14,m[s[4]],m[s[5]]); g(3,7,11,15,m[s[6]],m[s[7]])
            g(0,5,10,15,m[s[8]],m[s[9]]); g(1,6,11,12,m[s[10]],m[s[11]]); g(2,7,8,13,m[s[12]],m[s[13]]); g(3,4,9,14,m[s[14]],m[s[15]])
        for i in range(8): h[i] ^= v[i] ^ v[i+8]
    def blake2b(message, out_len=32):
        h = list(IV); h[0] ^= 0x01010000 ^ out_len
        t = 0
        buf = bytes(message) if message else bytes(128)
        n = (len(buf) + 127) // 128
        for i in range(n):
            last = i == n - 1
            block = buf[i*128:min(len(buf), (i+1)*128)]
            used = (0 if not message else len(block)) if last else 128
            block = block + bytes(128 - len(block))
            t += used
            compress(h, block, t, last)
        out = b"".join(w.to_bytes(8, "little") for w in h)
        return out[:out_len]
    ok = True
    for msg in (b"", b"a", b"x" * 127, b"y" * 128, b"z" * 129, b"w" * 300, b'["betanet-7","' + b"a" * 46 + b'","' + b"0" * 64 + b'",3456]'):
        if blake2b(msg) != hashlib.blake2b(msg, digest_size=32).digest():
            ok = False; print("   mismatch for len", len(msg))
    check("Blake2b.swift (ported) == hashlib.blake2b for empty / 1 / 127 / 128 / 129 / 300 bytes and a real challenge list", ok)
    from hashing import blake2b_hash
    import protocol as P
    chal_py = blake2b_hash([P.CHAIN_ID, "a" * 46, "0" * 64, 3456])
    canonical = f'["{P.CHAIN_ID}","{"a" * 46}","{"0" * 64}",3456]'.encode()
    check("Envelope.swift canonical challenge string == hashing.canonical_bytes of the list", blake2b(canonical).hex() == chal_py)


if __name__ == "__main__":
    d = tempfile.mkdtemp(prefix="nado-appattest-vec-"); os.chdir(d)
    try:
        att, cdj, point, a_att = t_kernel()
        t_binding_and_rules(att, cdj, point, a_att)
        t_blake2b_port()
        t_real_ipad_vector()
    except Exception:
        import traceback; traceback.print_exc(); _fails.append("exception")
    print("ALL PASS" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    raise SystemExit(1 if _fails else 0)
