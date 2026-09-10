"""Device attestation — phase 0: parse a WebAuthn attestation statement and keep the sample.

doc/device-attestation.md. The consensus verifier (certificate chain to the pinned roots, signatures, the
vendor extensions) is the native kernel of phase 1; this module only needs to READ the statement: a minimal
CBOR decoder (RFC 8949 subset: unsigned/negative ints, byte/text strings, arrays, maps, false/true/null) and
the authenticator-data layout, so the relay can log what real phones send and the wallet can show it.
No third-party parser: the node has none installed and consensus code must not grow a dependency here.
"""
import base64
import hashlib
import json
import os
import time


def _b64d(s):
    s = str(s).strip()
    s = s.replace("-", "+").replace("_", "/")
    return base64.b64decode(s + "=" * (-len(s) % 4))


def cbor_decode(data: bytes, strict: bool = False):
    """Decode ONE CBOR item (subset, see module doc). Raises ValueError on anything else. `strict` refuses DUPLICATE map
    keys: the kernel (ciborium) keeps the FIRST duplicate and this decoder kept the LAST, so one statement could verify as
    chain A and bind as chain B (review 2026-09-07). Consensus paths pass strict from DEVICE_BIND_STRICT_HEIGHT."""
    pos = [0]

    def take(n):
        if pos[0] + n > len(data):
            raise ValueError("cbor: truncated")
        b = data[pos[0]:pos[0] + n]
        pos[0] += n
        return b

    def arg(ai):
        if ai < 24:
            return ai
        if ai == 24:
            return take(1)[0]
        if ai == 25:
            return int.from_bytes(take(2), "big")
        if ai == 26:
            return int.from_bytes(take(4), "big")
        if ai == 27:
            return int.from_bytes(take(8), "big")
        raise ValueError("cbor: indefinite/reserved length unsupported")

    def item():
        ib = take(1)[0]
        mt, ai = ib >> 5, ib & 0x1F
        if mt == 0:
            return arg(ai)
        if mt == 1:
            return -1 - arg(ai)
        if mt == 2:
            return bytes(take(arg(ai)))
        if mt == 3:
            return take(arg(ai)).decode("utf-8")
        if mt == 4:
            return [item() for _ in range(arg(ai))]
        if mt == 5:
            out = {}
            for _ in range(arg(ai)):
                k = item()
                if strict and k in out:
                    raise ValueError("cbor: duplicate map key")
                out[k] = item()
            return out
        if mt == 7:
            if ai == 20:
                return False
            if ai == 21:
                return True
            if ai == 22:
                return None
        raise ValueError(f"cbor: unsupported major type {mt}/{ai}")

    v = item()
    if pos[0] != len(data):
        raise ValueError("cbor: trailing bytes")
    return v


def parse_auth_data(ad: bytes) -> dict:
    """rpIdHash(32) | flags(1) | signCount(4) | [aaguid(16) | credIdLen(2) | credId | credPubKey(CBOR)]"""
    if len(ad) < 37:
        raise ValueError("authData too short")
    flags = ad[32]
    out = {"rp_id_hash": ad[:32].hex(), "flags": flags, "user_present": bool(flags & 0x01),
           "user_verified": bool(flags & 0x04), "attested_cred": bool(flags & 0x40),
           "sign_count": int.from_bytes(ad[33:37], "big")}
    if flags & 0x40:
        aaguid = ad[37:53]
        n = int.from_bytes(ad[53:55], "big")
        out["aaguid"] = aaguid.hex()
        out["credential_id"] = ad[55:55 + n].hex()
        out["cred_pubkey_len"] = len(ad) - (55 + n)
    return out


def _auth_data_or_none(ad):
    try:
        return parse_auth_data(ad) if isinstance(ad, (bytes, bytearray)) and len(ad) >= 37 else None
    except Exception:
        return None


def ledger_device_pubkey(att: dict) -> bytes:
    """The device public key of a `ledger` statement: cert0 = [hdrLen][hdr][pubLen][pub][sigLen][sig]."""
    c0 = (att.get("attStmt") or {}).get("cert0")
    if not isinstance(c0, (bytes, bytearray)):
        raise ValueError("ledger statement has no cert0")
    c0 = bytes(c0)
    o = 1 + c0[0]
    n = c0[o]
    pub = c0[o + 1:o + 1 + n]
    if len(pub) != 65 or pub[0] != 0x04:
        raise ValueError("ledger cert0 public key is not an uncompressed secp256k1 point")
    return pub


def parse_attestation(att_b64: str, cdj_b64: str) -> dict:
    """Summary of an attestationObject + clientDataJSON pair: format, chain shape, authenticator data,
    client data. Pure parsing — NOTHING here is a verdict."""
    att = cbor_decode(_b64d(att_b64))
    if not isinstance(att, dict):
        raise ValueError("attestationObject is not a map")
    fmt = att.get("fmt")
    st = att.get("attStmt") or {}
    ad = att.get("authData") or b""
    x5c = st.get("x5c") or []
    cdj_raw = _b64d(cdj_b64)
    try:
        cd = json.loads(cdj_raw.decode("utf-8"))
    except Exception:
        cd = {}
    return {
        "fmt": fmt,
        "alg": st.get("alg"),
        "x5c_count": len(x5c),
        "x5c_lengths": [len(c) for c in x5c if isinstance(c, (bytes, bytearray))],
        # per-certificate validity (unix seconds) so the wallet's pre-flight can say "expired" or "batch certificate"
        # BEFORE a submit that the kernel would refuse with a bare "x5c[1] outside validity" (2026-09-08)
        "x5c_validity": [list(_validity_or_none(c)) for c in x5c if isinstance(c, (bytes, bytearray))],
        "leaf_sha256": hashlib.sha256(x5c[0]).hexdigest() if x5c and isinstance(x5c[0], (bytes, bytearray)) else None,
        "root_sha256": hashlib.sha256(x5c[-1]).hexdigest() if x5c and isinstance(x5c[-1], (bytes, bytearray)) else None,
        "sig_len": len(st.get("sig") or b""),
        "auth_data": _auth_data_or_none(ad),      # hardware-wallet statements carry no authenticator data
        "client_data": {k: cd.get(k) for k in ("type", "challenge", "origin", "crossOrigin") if k in cd},
        "cdj_sha256": hashlib.sha256(cdj_raw).hexdigest(),
    }


def _der_tlv(buf: bytes, pos: int):
    """One DER TLV at `pos` -> (tag, header_len, length). Long-form lengths up to 4 bytes."""
    tag = buf[pos]
    l = buf[pos + 1]
    if l < 0x80:
        return tag, 2, l
    n = l & 0x7F
    if n == 0 or n > 4 or pos + 2 + n > len(buf):
        raise ValueError("bad DER length")
    return tag, 2 + n, int.from_bytes(buf[pos + 2:pos + 2 + n], "big")


def _der_time(tag: int, body: bytes) -> int:
    """UTCTime (0x17, YYMMDDHHMMSSZ) or GeneralizedTime (0x18, YYYYMMDDHHMMSSZ) -> unix seconds."""
    import calendar
    s = body.decode("ascii")
    if tag == 0x17:
        yy = int(s[0:2]); year = 1900 + yy if yy >= 50 else 2000 + yy; rest = s[2:]
    elif tag == 0x18:
        year = int(s[0:4]); rest = s[4:]
    else:
        raise ValueError("not a DER time")
    return calendar.timegm((year, int(rest[0:2]), int(rest[2:4]), int(rest[4:6]), int(rest[6:8]), int(rest[8:10]) if len(rest) >= 10 and rest[8:10].isdigit() else 0))


def _validity_or_none(der) -> tuple:
    try:
        return cert_validity(bytes(der))
    except Exception:
        return (None, None)


def cert_validity(der: bytes) -> tuple:
    """(not_before, not_after) unix seconds of a DER X.509 certificate, from a minimal, dependency-free walk:
    Certificate SEQ { tbsCertificate SEQ { [0] version?, serialNumber, signature, issuer, validity SEQ {Time, Time} ... } }.
    Deterministic and tiny on purpose — this is consensus input (device_binding_key), so it must never depend on
    a library version; the full chain is verified by the native kernel, this only READS the two dates."""
    der = bytes(der)
    tag, h, _ = _der_tlv(der, 0)
    if tag != 0x30:
        raise ValueError("certificate is not a SEQUENCE")
    p = h
    tag, h, n = _der_tlv(der, p)                     # tbsCertificate
    if tag != 0x30:
        raise ValueError("tbsCertificate is not a SEQUENCE")
    p += h
    tag, h, n = _der_tlv(der, p)
    if tag == 0xA0:                                  # [0] EXPLICIT version
        p += h + n
        tag, h, n = _der_tlv(der, p)
    if tag != 0x02:
        raise ValueError("serialNumber missing")
    p += h + n                                       # serialNumber
    for _ in range(2):                               # signature AlgorithmIdentifier, issuer Name
        tag, h, n = _der_tlv(der, p)
        if tag != 0x30:
            raise ValueError("tbs field is not a SEQUENCE")
        p += h + n
    tag, h, n = _der_tlv(der, p)                     # validity
    if tag != 0x30:
        raise ValueError("validity is not a SEQUENCE")
    p += h
    t1, h1, n1 = _der_tlv(der, p)
    nb = _der_time(t1, der[p + h1:p + h1 + n1])
    p += h1 + n1
    t2, h2, n2 = _der_tlv(der, p)
    na = _der_time(t2, der[p + h2:p + h2 + n2])
    return nb, na


def device_binding_key(device: dict, max_cert_secs: int, strict: bool = False) -> str:
    """The ONE-IDENTITY-PER-DEVICE handle of an attestation (doc/device-attestation.md §"One device, one identity"):
      android-key : "android-key:" + sha256(x5c[1]) — the device's remotely-provisioned attestation-key certificate
                    (subject O=TEE, CN=<device id>, issued by a Droid CA), reused for every credential the device
                    creates until it rotates (~2 weeks). A batch-attested (pre-RKP) device carries a multi-year
                    intermediate shared by up to 100k units, so it is REFUSED: its validity exceeds `max_cert_secs`.
      tpm         : "tpm:" + sha256(x5c[0]) — the AIK certificate, one per (physical TPM, Windows account).
      packed / apple / anything else: REFUSED — a FIDO2 batch certificate or an Apple statement carries nothing
                    that identifies the device, so "no double attestation" cannot be enforced for them.
      ek          : "ek:" + the endorsement identity (doc/tpm-attestation-without-a-ca.md) — a VENDOR-ENDORSED
                    TPM register, which carries a certify rather than a WebAuthn statement. The handle is the
                    ENDORSEMENT key, one per chip by manufacture and impossible to re-mint: a chip that enrols
                    ten attestation keys still holds one identity, and regenerating the endorsement seed to
                    fake a new chip invalidates the vendor certificate that made it admissible.
    Raises ValueError with the reason (the validation turns it into the tx's rejection message). Pure parsing over
    bytes the native kernel has already verified; deterministic by construction (consensus input)."""
    # The endorsement identity rides in the transaction, so this stays a PURE function of the tx bytes like
    # every other class: apply and revert derive the same key with no database read, and validation is what
    # checks the declared identity against the enrolment record.
    if isinstance(device, dict) and isinstance(device.get("id"), str) and "att" not in device:
        ek = device.get("ek")
        if not (isinstance(ek, str) and len(ek) == 64 and all(c in "0123456789abcdef" for c in ek)):
            raise ValueError("vendor-endorsed register carries no endorsement identity")
        return "ek:" + ek
    att = cbor_decode(_b64d(str(device.get("att", ""))), strict=strict)
    if not isinstance(att, dict):
        raise ValueError("attestationObject is not a map")
    fmt = att.get("fmt")
    x5c = (att.get("attStmt") or {}).get("x5c") or []
    x5c = [bytes(c) for c in x5c if isinstance(c, (bytes, bytearray))]
    if fmt == "android-key":
        if len(x5c) < 3:
            raise ValueError("android-key chain has no device attestation certificate")
        nb, na = cert_validity(x5c[1])
        if na - nb > int(max_cert_secs):
            raise ValueError("batch-attested Android device (long-lived attestation certificate) cannot be bound to one "
                             "identity — a device with remote key provisioning (Android 12+) is required")
        return "android-key:" + hashlib.sha256(x5c[1]).hexdigest()
    if fmt == "tpm":
        if not x5c:
            raise ValueError("tpm statement has no AIK certificate")
        return "tpm:" + hashlib.sha256(x5c[0]).hexdigest()
    if fmt == "trezor":
        # the device certificate (CN "<model> <serial>", per-device key from the secure element)
        if not x5c:
            raise ValueError("trezor statement has no device certificate")
        return "trezor:" + hashlib.sha256(x5c[0]).hexdigest()
    if fmt == "ledger":
        # the factory-certified device public key — permanent for the life of the device
        return "ledger:" + hashlib.sha256(ledger_device_pubkey(att)).hexdigest()
    raise ValueError(f"device class '{fmt}' carries no per-device certificate and cannot be bound to one identity "
                     "(accepted: Android with remote key provisioning, Windows Hello on a physical TPM)")


def store_sample(summary: dict, raw: dict, ip: str = "") -> str:
    """Keep the full statement under <home>/index/device_attest/ for the phase-1 kernel's test vectors."""
    from ops.data_ops import get_home
    d = os.path.join(get_home(), "index", "device_attest")
    os.makedirs(d, exist_ok=True)
    name = f"{int(time.time())}_{summary.get('fmt') or 'unknown'}_{(summary.get('auth_data') or {}).get('aaguid', 'noaaguid')[:8]}.json"
    with open(os.path.join(d, name), "w") as f:
        json.dump({"summary": summary, "raw": raw, "ip": ip, "at": time.time()}, f)
    return name
