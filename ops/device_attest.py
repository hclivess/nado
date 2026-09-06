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


def cbor_decode(data: bytes):
    """Decode ONE CBOR item (subset, see module doc). Raises ValueError on anything else."""
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
        "leaf_sha256": hashlib.sha256(x5c[0]).hexdigest() if x5c and isinstance(x5c[0], (bytes, bytearray)) else None,
        "root_sha256": hashlib.sha256(x5c[-1]).hexdigest() if x5c and isinstance(x5c[-1], (bytes, bytearray)) else None,
        "sig_len": len(st.get("sig") or b""),
        "auth_data": parse_auth_data(ad) if isinstance(ad, (bytes, bytearray)) else None,
        "client_data": {k: cd.get(k) for k in ("type", "challenge", "origin", "crossOrigin") if k in cd},
        "cdj_sha256": hashlib.sha256(cdj_raw).hexdigest(),
    }


def store_sample(summary: dict, raw: dict, ip: str = "") -> str:
    """Keep the full statement under <home>/index/device_attest/ for the phase-1 kernel's test vectors."""
    from ops.data_ops import get_home
    d = os.path.join(get_home(), "index", "device_attest")
    os.makedirs(d, exist_ok=True)
    name = f"{int(time.time())}_{summary.get('fmt') or 'unknown'}_{(summary.get('auth_data') or {}).get('aaguid', 'noaaguid')[:8]}.json"
    with open(os.path.join(d, name), "w") as f:
        json.dump({"summary": summary, "raw": raw, "ip": ip, "at": time.time()}, f)
    return name
