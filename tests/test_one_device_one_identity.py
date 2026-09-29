"""One device backs one identity — even when its certificate is sent with junk after it (protocol.py "ONE DEVICE, ONE
IDENTITY — FOR REAL"; betanet-8 from block 19800, betanet-9 from block 1 — the gate, DEVICE_BIND_CANONICAL_HEIGHT, is
deleted, but the raw-bytes key is not: devbind rows written under it on betanet-8 were carried into betanet-9).

THE HOLE (audit 2026-09-25, fixed 2026-09-27). The binding key was sha256(raw certificate bytes), while the native
kernel parses the DER and ignores anything after it. So the same chip's certificate with different trailing junk verified
every time and hashed to a new key every time: one device, unlimited identities. (Measured before the fix: no such
registration existed on betanet-8.)

Pins, on the real Android vector's per-device certificate:
  1. the raw-bytes form (canonical=False) is exactly the old key, which a carried row is found by — and junk changes it
     (the hole);
  2. the consensus key is the certificate's SIGNED part: a certificate with trailing bytes is refused, and an outer
     re-encoding (long-form length) that the signature does not cover yields the SAME key;
  3. the switch-over: a device bound under its raw-bytes key (a carried betanet-8 row) that registers for another
     identity evicts the identity its old row backs — the switch hands no device a second identity — and a rollback
     restores the old row, its mode and the eviction list exactly;
  4. validation, the one-device-per-block key and apply all derive the canonical key, and apply passes the legacy key.

Run: python3 tests/test_one_device_one_identity.py
"""
import base64, json, os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-onedev-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
from genesis import create_indexers
create_indexers()
import protocol as P
from ops import kv_ops, device_attest as DA
from ops.account_ops import apply_register
import logging
logger = logging.getLogger("onedev"); logger.addHandler(logging.NullHandler())

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def raises(fn):
    try:
        fn()
        return False
    except ValueError:
        return True


v = json.load(open(os.path.join(ROOT, "tests", "vectors", "device_attest_android_key.json")))
att = DA.cbor_decode(DA._b64d(v["att"]))
x5c = [bytes(c) for c in att["attStmt"]["x5c"]]


def statement(device_cert):
    """The vector's statement with its per-device certificate (x5c[1]) replaced."""
    import copy
    a = copy.deepcopy(att)
    a["attStmt"]["x5c"] = [x5c[0], device_cert] + x5c[2:]
    return {"att": base64.b64encode(_cbor_encode(a)).decode()}


def _cbor_encode(o):
    def hdr(m, n):
        if n < 24: return bytes([m << 5 | n])
        if n < 256: return bytes([m << 5 | 24, n])
        if n < 65536: return bytes([m << 5 | 25]) + n.to_bytes(2, "big")
        return bytes([m << 5 | 26]) + n.to_bytes(4, "big")
    if isinstance(o, (bytes, bytearray)): return hdr(2, len(o)) + bytes(o)
    if isinstance(o, str): b = o.encode(); return hdr(3, len(b)) + b
    if isinstance(o, bool): return b"\xf5" if o else b"\xf4"
    if isinstance(o, int): return hdr(0, o) if o >= 0 else hdr(1, -1 - o)
    if isinstance(o, list): return hdr(4, len(o)) + b"".join(_cbor_encode(x) for x in o)
    if isinstance(o, dict): return hdr(5, len(o)) + b"".join(_cbor_encode(k) + _cbor_encode(val) for k, val in o.items())
    raise TypeError(type(o))


MAXS = P.DEVICE_BIND_MAX_CERT_SECS
cert = x5c[1]
junk1, junk2 = cert + b"\x00", cert + b"\x01\x02"
# outer re-encoding: the Certificate SEQUENCE header rewritten with a longer (non-minimal) length form — bytes the
# issuer's signature does not cover
tag, h, n = DA._der_tlv(cert, 0)
reenc = bytes([0x30, 0x84]) + n.to_bytes(4, "big") + cert[h:]

key = lambda c, canon: DA.device_binding_key(statement(c), MAXS, strict=True, canonical=canon)
k0 = key(cert, False)
check("the raw-bytes form is the old key, exactly as before (what a carried row is keyed by)",
      k0 == DA.device_binding_key({"att": v["att"]}, MAXS))
check("...and junk after the certificate gives a NEW key (the hole: one device, many identities)",
      len({key(cert, False), key(junk1, False), key(junk2, False)}) == 3)

kc = key(cert, True)
check("the consensus key is the certificate's SIGNED part", kc == "android-key:" + __import__("hashlib").sha256(DA.cert_signed_part(cert)).hexdigest())
check("a certificate with trailing bytes is REFUSED", raises(lambda: key(junk1, True)) and raises(lambda: key(junk2, True)))
check("an outer re-encoding the signature does not cover yields the SAME key", key(reenc, True) == kc)
check("the canonical key is not the raw one (so the switch-over is needed)", kc != k0)

# --- the switch-over, on the real tables (throwaway HOME) ---------------------------------------------------------
A, B = "a" * 46, "b" * 46
E0, E1 = 10, 11
with kv_ops.write_txn():
    pass
apply_register(A, E0, logger, device_key=k0)                       # a carried row, under the raw-bytes key
check("setup: the device's raw-bytes row backs A", (kv_ops.devbind_get(k0) or [None])[0] == A)
snapshot = (kv_ops.devbind_get(k0), kv_ops.devbind_get(kc), kv_ops.devevict_get(A))
apply_register(B, E1, logger, device_key=kc, legacy_key=k0)        # the SAME device registers B
check("the device now backs B under its canonical key", (kv_ops.devbind_get(kc) or [None])[0] == B)
check("its raw-bytes row is gone, so A finds no row pointing back at it", kv_ops.devbind_get(k0) is None)
ev = kv_ops.devevict_get(A)
check("A is EVICTED in this very block (the switch hands the device no second identity)",
      len(ev) == len(snapshot[2]) + 1 and ev[-1][0] == E1, ev)
apply_register(B, E1, logger, revert=True, device_key=kc, legacy_key=k0)
check("rollback restores the raw-bytes row exactly", kv_ops.devbind_get(k0) == snapshot[0], (kv_ops.devbind_get(k0), snapshot[0]))
check("...removes the canonical row", kv_ops.devbind_get(kc) == snapshot[1])
check("...and A's eviction list", kv_ops.devevict_get(A) == snapshot[2])

# --- one key, everywhere --------------------------------------------------------------------------------------------
to = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
ac = open(os.path.join(ROOT, "ops", "account_ops.py")).read()
check("validation keys canonically", "DEVICE_BIND_MAX_CERT_SECS, strict=True,\n                                              canonical=True)" in to)
check("the one-device-per-block key too (register lands at max_block)",
      "tx.get(\"device\") or {}, DEVICE_BIND_MAX_CERT_SECS, strict=True, canonical=True)))" in to)
check("apply too, and passes the legacy key",
      "strict=True, canonical=True)   # same parse as validation" in ac and "legacy_key=legacy_key)" in ac)
check("the gate is deleted", not hasattr(P, "DEVICE_BIND_CANONICAL_HEIGHT"))

kv_ops.close_all()
print("ALL PASS — one device backs one identity" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
