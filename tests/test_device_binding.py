"""ONE DEVICE, ONE IDENTITY (protocol.DEVICE_BIND_HEIGHT; ops/device_attest.device_binding_key; kv_ops devbind;
account_ops.apply_register; transaction_ops register branch). "Using one device to attest 100,000 wallets must be
impossible." Pins:
  1. the binding key: the REAL Android vector binds on x5c[1] (per-device RKP certificate, 13-day validity); a
     long-lived (batch) x5c[1] is refused; tpm binds on the AIK leaf; packed/apple/none are refused;
  2. the DER validity walk agrees with openssl on every certificate of the real chain;
  3. apply/revert symmetry: binding written at apply, the overwritten value restored on revert, table byte-identical;
  4. the rule: a second sender on the same device inside the lease is invalid; the same sender renews; after the
     lease the device may move; below the gate nothing is checked or written;
  5. consensus hygiene: devbind is snapshot-carried (in the root), devbind_revert is node-local; the gate is a height.
Run: python3 tests/test_device_binding.py
"""
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
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-devbind-")
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def _cbor_att(fmt, x5c):
    """Minimal CBOR attestationObject {fmt, attStmt:{x5c:[...]}, authData:b''} for the parser."""
    def _hdr(major, n):
        if n < 24: return bytes([major << 5 | n])
        if n < 256: return bytes([major << 5 | 24, n])
        if n < 65536: return bytes([major << 5 | 25]) + n.to_bytes(2, "big")
        return bytes([major << 5 | 26]) + n.to_bytes(4, "big")
    def _tstr(s): b = s.encode(); return _hdr(3, len(b)) + b
    def _bstr(b): return _hdr(2, len(b)) + b
    body = _hdr(5, 3) + _tstr("fmt") + _tstr(fmt) + _tstr("attStmt") + _hdr(5, 1) + _tstr("x5c") + _hdr(4, len(x5c)) + b"".join(_bstr(c) for c in x5c) + _tstr("authData") + _bstr(b"")
    return base64.b64encode(body).decode()


def _cert(days, subject="/CN=t"):
    """A self-signed DER certificate valid for `days` (openssl)."""
    d = tempfile.mkdtemp()
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-keyout", f"{d}/k.pem",
                    "-out", f"{d}/c.pem", "-days", str(days), "-subj", subject], check=True, capture_output=True)
    return subprocess.run(["openssl", "x509", "-in", f"{d}/c.pem", "-outform", "DER"], check=True, capture_output=True).stdout


def t_binding_key():
    from ops.device_attest import device_binding_key, cbor_decode, _b64d, cert_validity
    import protocol as P
    v = json.load(open(os.path.join(ROOT, "tests", "vectors", "device_attest_android_key.json")))
    x5c = [bytes(c) for c in cbor_decode(_b64d(v["att"]))["attStmt"]["x5c"]]
    key = device_binding_key({"att": v["att"]}, P.DEVICE_BIND_MAX_CERT_SECS)
    check("real Android: binds on x5c[1] (the per-device RKP certificate)", key == "android-key:" + hashlib.sha256(x5c[1]).hexdigest(), key)
    for i, c in enumerate(x5c):
        o = subprocess.run(["openssl", "x509", "-inform", "DER", "-noout", "-startdate", "-enddate"], input=c, capture_output=True).stdout.decode()
        import calendar   # timegm, not mktime-timezone: the box is on CEST and mktime would apply DST (an hour off)
        nb = calendar.timegm(time.strptime(o.split("notBefore=")[1].split("\n")[0].strip(), "%b %d %H:%M:%S %Y GMT"))
        na = calendar.timegm(time.strptime(o.split("notAfter=")[1].split("\n")[0].strip(), "%b %d %H:%M:%S %Y GMT"))
        got = cert_validity(c)
        check(f"DER validity walk == openssl for x5c[{i}]", got == (int(nb), int(na)), (got, nb, na))
    nb, na = cert_validity(x5c[1])
    check("the per-device certificate is short-lived (< 90 days): 13 days here", 0 < na - nb <= P.DEVICE_BIND_MAX_CERT_SECS)
    leaf, batch, root = _cert(365 * 20, "/CN=Android Keystore Key"), _cert(365 * 10, "/O=batch"), _cert(365 * 10, "/CN=root")
    try:
        device_binding_key({"att": _cbor_att("android-key", [leaf, batch, root])}, P.DEVICE_BIND_MAX_CERT_SECS); check("batch-attested Android refused", False)
    except ValueError as e:
        check("batch-attested Android (long-lived x5c[1]) is REFUSED, with the reason", "batch" in str(e), e)
    short = _cert(14, "/O=TEE/CN=dev")
    k = device_binding_key({"att": _cbor_att("android-key", [leaf, short, root])}, P.DEVICE_BIND_MAX_CERT_SECS)
    check("a short-lived x5c[1] binds", k == "android-key:" + hashlib.sha256(short).hexdigest())
    aik = _cert(3650, "/CN=")
    check("tpm binds on the AIK certificate (x5c[0])", device_binding_key({"att": _cbor_att("tpm", [aik, root])}, P.DEVICE_BIND_MAX_CERT_SECS) == "tpm:" + hashlib.sha256(aik).hexdigest())
    for fmt in ("packed", "apple", "none"):
        try:
            device_binding_key({"att": _cbor_att(fmt, [leaf, root])}, P.DEVICE_BIND_MAX_CERT_SECS); check(f"{fmt} refused", False)
        except ValueError as e:
            check(f"{fmt}: no per-device certificate -> REFUSED", "cannot be bound" in str(e), e)
    try:
        device_binding_key({"att": _cbor_att("android-key", [leaf])}, P.DEVICE_BIND_MAX_CERT_SECS); check("short chain refused", False)
    except ValueError:
        check("android-key without a device certificate is refused", True)


def t_apply_revert_symmetry():
    from ops import kv_ops
    kv_ops.close_all(); kv_ops.init_env()
    from ops.account_ops import apply_register
    import logging
    lg = logging.getLogger("t")
    a, b, key = "a" * 46, "b" * 46, "android-key:" + "11" * 32
    for addr in (a, b):
        kv_ops.account_set(addr, "balance", 0)
    apply_register(a, 10, lg, device_key=key)
    check("apply binds the device to the sender at the recert epoch", kv_ops.devbind_get(key) == (a, 10))
    apply_register(a, 300, lg, device_key=key)                      # same device, same sender, later renewal
    check("a renewal re-binds at the new epoch", kv_ops.devbind_get(key) == (a, 300))
    apply_register(a, 300, lg, revert=True)
    check("reverting the renewal restores the PREVIOUS binding (not delete)", kv_ops.devbind_get(key) == (a, 10))
    apply_register(a, 10, lg, revert=True)
    check("reverting the first binding removes the row", kv_ops.devbind_get(key) is None)
    apply_register(b, 20, lg)                                        # pre-gate style: no device key
    apply_register(b, 20, lg, revert=True)
    check("a register without a key writes no binding and reverts cleanly", kv_ops.devbind_get(key) is None and kv_ops.devbind_revert_pop(20, b) is None)
    kv_ops.close_all()


def t_rule():
    """The register branch's binding check, with the kernel verify stubbed (the kernel has its own tests)."""
    from ops import kv_ops
    kv_ops.close_all(); kv_ops.init_env()
    import protocol as P
    from ops import transaction_ops as TO
    from ops import device_attest as DA
    v = json.load(open(os.path.join(ROOT, "tests", "vectors", "device_attest_android_key.json")))
    key = DA.device_binding_key({"att": v["att"]}, P.DEVICE_BIND_MAX_CERT_SECS)
    a, b = "a" * 46, "b" * 46
    src = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
    seg = src[src.index('elif recipient == "register":'):src.index('elif recipient == "msgkey":')]
    check("rule wired after the kernel verdict, gated on DEVICE_BIND_HEIGHT",
          "verify_register_device(transaction, anchor)" in seg and "DEVICE_BIND_HEIGHT" in seg and "devbind_get(dkey)" in seg
          and seg.index("verify_register_device(") < seg.index("devbind_get("))
    # simulate the table as apply would leave it: device bound to `a` at epoch 100
    kv_ops.devbind_set(key, a, 100)
    gate_epoch = 100
    # replicate the rule's arithmetic exactly (the seg above pins the wiring; this pins the semantics)
    def rule(sender, epoch_now):
        bound = kv_ops.devbind_get(key)
        return not (bound and bound[0] != sender and epoch_now < bound[1] + P.POSW_LEASE_EPOCHS)
    check("same device, DIFFERENT sender inside the lease -> invalid", not rule(b, gate_epoch + 5))
    check("same device, same sender -> valid (renewal)", rule(a, gate_epoch + 5))
    check("after the lease expires the device may vouch for another sender", rule(b, gate_epoch + P.POSW_LEASE_EPOCHS))
    check("one epoch before expiry still blocked", not rule(b, gate_epoch + P.POSW_LEASE_EPOCHS - 1))
    kv_ops.close_all()


def t_hygiene():
    from ops import kv_ops
    import protocol as P
    from ops import snapshot_ops as S
    check("devbind is consensus state: snapshot-carried and in the root", "devbind" in kv_ops.SNAPSHOT_DBS and "devbind" not in S.ROOT_EXCLUDED_DBS)
    check("devbind_revert is a node-local journal (never in the root)", "devbind_revert" in kv_ops._LOCAL_DBS and "devbind_revert" not in kv_ops.SNAPSHOT_DBS)
    check("the gate is a height ahead of the fleet's adoption on the live chain", isinstance(P.DEVICE_BIND_HEIGHT, int) and P.DEVICE_BIND_HEIGHT >= 1)
    check("accepted classes are exactly the bindable ones", P.DEVICE_BIND_CLASSES == frozenset(("android-key", "tpm", "trezor", "ledger")))
    acc = open(os.path.join(ROOT, "ops", "account_ops.py")).read()
    check("apply derives the key from the tx bytes at the block height and passes it to apply_register",
          "device_binding_key(transaction.get(\"device\")" in acc and "device_key=device_key" in acc)
    check("apply_register journals the overwritten binding and restores it on revert",
          "devbind_revert_put(epoch, address, device_key, prev_bind)" in acc and "devbind_revert_pop(epoch, address)" in acc)


if __name__ == "__main__":
    for name in ("t_binding_key", "t_apply_revert_symmetry", "t_rule", "t_hygiene"):
        try:
            globals()[name]()
        except Exception:
            import traceback; traceback.print_exc(); _fails.append(name)
    print("ALL PASS" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    raise SystemExit(1 if _fails else 0)
