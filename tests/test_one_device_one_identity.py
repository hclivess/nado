"""One device backs one identity — even when its certificate is sent with junk after it (DEVICE_BIND_CANONICAL_HEIGHT).

THE HOLE (audit 2026-09-25, fixed 2026-09-27). The binding key was sha256(raw certificate bytes), while the native
kernel parses the DER and ignores anything after it. So the same chip's certificate with different trailing junk verified
every time and hashed to a new key every time: one device, unlimited identities. (Measured before the fix: no such
registration existed on betanet-8.)

Pins, on the real Android vector's per-device certificate:
  1. below the gate the key is exactly the old raw-bytes key (replay unchanged) — and junk changes it (the hole);
  2. from the gate the key is the certificate's SIGNED part: a certificate with trailing bytes is refused, and an outer
     re-encoding (long-form length) that the signature does not cover yields the SAME key;
  3. the switch-over: a device bound BEFORE the gate (raw-bytes row) that registers for another identity after it
     evicts the identity its old row backs — the switch hands no device a second identity — and a rollback restores the
     old row, its mode and the eviction list exactly;
  4. validation, the one-device-per-block key and apply all derive the key at the same height with the same flag.

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
check("below the gate the key is the raw-bytes key, exactly as before", k0 == DA.device_binding_key({"att": v["att"]}, MAXS))
check("...and junk after the certificate gives a NEW key (the hole: one device, many identities)",
      len({key(cert, False), key(junk1, False), key(junk2, False)}) == 3)

kc = key(cert, True)
check("from the gate the key is the certificate's SIGNED part", kc == "android-key:" + __import__("hashlib").sha256(DA.cert_signed_part(cert)).hexdigest())
check("a certificate with trailing bytes is REFUSED", raises(lambda: key(junk1, True)) and raises(lambda: key(junk2, True)))
check("an outer re-encoding the signature does not cover yields the SAME key", key(reenc, True) == kc)
check("the canonical key is not the raw one (so the switch-over is needed)", kc != k0)

# --- the switch-over, on the real tables (throwaway HOME) ---------------------------------------------------------
A, B = "a" * 46, "b" * 46
E0, E1 = 10, 11
with kv_ops.write_txn():
    pass
apply_register(A, E0, logger, device_key=k0)                       # bound BEFORE the gate, under the raw-bytes key
check("setup: the device's pre-gate row backs A", (kv_ops.devbind_get(k0) or [None])[0] == A)
snapshot = (kv_ops.devbind_get(k0), kv_ops.devbind_get(kc), kv_ops.devevict_get(A))
apply_register(B, E1, logger, device_key=kc, legacy_key=k0)        # the SAME device registers B after the gate
check("the device now backs B under its canonical key", (kv_ops.devbind_get(kc) or [None])[0] == B)
check("its pre-gate row is gone, so A finds no row pointing back at it", kv_ops.devbind_get(k0) is None)
ev = kv_ops.devevict_get(A)
check("A is EVICTED in this very block (the switch hands the device no second identity)",
      len(ev) == len(snapshot[2]) + 1 and ev[-1][0] == E1, ev)
apply_register(B, E1, logger, revert=True, device_key=kc, legacy_key=k0)
check("rollback restores the pre-gate row exactly", kv_ops.devbind_get(k0) == snapshot[0], (kv_ops.devbind_get(k0), snapshot[0]))
check("...removes the canonical row", kv_ops.devbind_get(kc) == snapshot[1])
check("...and A's eviction list", kv_ops.devevict_get(A) == snapshot[2])

# --- one height, one flag, everywhere -------------------------------------------------------------------------------
to = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
ac = open(os.path.join(ROOT, "ops", "account_ops.py")).read()
check("validation keys canonically from the gate", "canonical=block_height >= DEVICE_BIND_CANONICAL_HEIGHT)" in to)
check("the one-device-per-block key too (register lands at max_block)",
      "canonical=int(tx.get(\"max_block\", 0)) >= DEVICE_BIND_CANONICAL_HEIGHT)" in to)
check("apply too, and passes the legacy key", "_canon = block_height >= DEVICE_BIND_CANONICAL_HEIGHT" in ac and "legacy_key=legacy_key)" in ac)
check("the gate carries its reroll branch", P.DEVICE_BIND_CANONICAL_HEIGHT >= 1)

kv_ops.close_all()
print("ALL PASS — one device backs one identity" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
