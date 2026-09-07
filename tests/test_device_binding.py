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
    check("apply binds the device to the sender at the recert epoch", kv_ops.devbind_get(key) == (a, 10, "lease"))
    apply_register(a, 300, lg, device_key=key)                      # same device, same sender, later renewal
    check("a renewal re-binds at the new epoch", kv_ops.devbind_get(key) == (a, 300, "lease"))
    apply_register(a, 300, lg, revert=True)
    check("reverting the renewal restores the PREVIOUS binding (not delete)", kv_ops.devbind_get(key) == (a, 10, "lease"))
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
          and seg.index("verify_register_device(") < seg.index("devbind_get(dkey)"))
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


def t_strict_binding():
    """Review 2026-09-07: (1) duplicate CBOR keys — kernel keeps the FIRST, the old Python parser the LAST — let one
    statement verify as chain A and bind as chain B; strict parsing refuses duplicates. (2) N senders could bind one
    device inside a block (rule reads parent state); register txs now occupy ("devbind", key) in the block."""
    from ops.device_attest import device_binding_key, cbor_decode
    from ops import transaction_ops as TO
    import protocol as P
    v = json.load(open(os.path.join(ROOT, "tests", "vectors", "device_attest_android_key.json")))
    raw = base64.b64decode(v["att"])
    # forge: the same attestationObject with a SECOND `attStmt` (garbage chain) appended as a duplicate key
    # by wrapping: map of 4 entries {fmt, attStmt(real), authData, attStmt(garbage)}
    real = cbor_decode(raw)
    leaf, other = _cert(3650, "/CN=A"), _cert(14, "/O=TEE/CN=B")
    root = _cert(3650, "/CN=root")
    garbage_stmt = {"x5c": [leaf, other, root], "sig": b"\x00"}
    # encode with a duplicate key using the fixture encoder (dict order preserved; duplicates via a list of pairs)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _attest_fixtures import cbor, cbor_map
    forged = cbor_map([("fmt", "android-key"), ("attStmt", real["attStmt"]), ("authData", real["authData"]), ("attStmt", garbage_stmt)])
    dev = {"att": base64.b64encode(forged).decode()}
    lax = device_binding_key(dev, P.DEVICE_BIND_MAX_CERT_SECS, strict=False)
    real_key = device_binding_key({"att": v["att"]}, P.DEVICE_BIND_MAX_CERT_SECS)
    check("lax parse (pre-gate) binds the LAST duplicate — a different device key than the kernel verified", lax != real_key, (lax, real_key))
    try:
        device_binding_key(dev, P.DEVICE_BIND_MAX_CERT_SECS, strict=True); check("strict parse refuses duplicate keys", False)
    except ValueError as e:
        check("strict parse refuses duplicate keys", "duplicate" in str(e), e)
    check("strict parse of a clean statement gives the same key as before", device_binding_key({"att": v["att"]}, P.DEVICE_BIND_MAX_CERT_SECS, strict=True) == real_key)
    check("gate: DEVICE_BIND_STRICT_HEIGHT is a height at/after the bind gate", P.DEVICE_BIND_STRICT_HEIGHT >= P.DEVICE_BIND_HEIGHT)
    tx_at = {"recipient": "register", "sender": "a" * 46, "max_block": P.DEVICE_BIND_STRICT_HEIGHT, "device": {"att": v["att"]}}
    tx_before = {**tx_at, "max_block": P.DEVICE_BIND_STRICT_HEIGHT - 1}
    keys_at, keys_before = TO.reserved_uniqueness_keys(tx_at), TO.reserved_uniqueness_keys(tx_before)
    check("in-block uniqueness: a register at/after the gate occupies ('devbind', key)", ("devbind", real_key) in keys_at and ("register", "a" * 46) in keys_at, keys_at)
    check("below the gate only the per-sender key (historical block validity unchanged)", keys_before == [("register", "a" * 46)], keys_before)
    tx_b = {**tx_at, "sender": "b" * 46}
    try:
        TO.assert_unique_reserved([tx_at, tx_b]); check("two senders, one device, one block -> refused", False)
    except ValueError as e:
        check("two senders, one device, one block -> refused", "devbind" in str(e), e)
    src = open(os.path.join(ROOT, "ops", "account_ops.py")).read()
    check("apply parses with the same strictness as validation", "strict=block_height >= DEVICE_BIND_STRICT_HEIGHT" in src)


def t_binding_modes():
    """BINDING MODES (protocol.DEVICE_BIND_PERMANENT_HEIGHT, doc/device-attestation.md §"Binding modes"): a Ledger/Trezor
    binds for LIFE (row mode "perm", account `devkey`), renews with NO statement while the row points back at it, and
    may be REBOUND by a new sender after one lease since its last statement; a phone/TPM keeps the leased row. Every
    write is journaled and reverts to byte-identical state; pre-gate rows decode unchanged."""
    from ops import kv_ops
    kv_ops.close_all(); kv_ops.init_env()
    import protocol as P
    from ops.account_ops import apply_register
    from ops import transaction_ops as TO
    import logging
    lg = logging.getLogger("t")
    a, b = "a" * 46, "b" * 46
    lkey = "ledger:" + "22" * 32
    for addr in (a, b):
        kv_ops.account_set(addr, "balance", 0)
    # --- constants
    check("permanent classes are exactly the factory-fixed-key ones", P.DEVICE_BIND_PERMANENT_CLASSES == frozenset(("ledger", "trezor")))
    check("permanent classes are bindable classes", P.DEVICE_BIND_PERMANENT_CLASSES <= P.DEVICE_BIND_CLASSES)
    check("the permanent gate is at/after the strict gate", P.DEVICE_BIND_PERMANENT_HEIGHT >= P.DEVICE_BIND_STRICT_HEIGHT)
    # --- row formats: a leased row is byte-identical to the historical two-element row (state root / replay)
    kv_ops.devbind_set("android-key:" + "33" * 32, a, 7)
    raw = kv_ops._read(lambda txn: txn.get(("android-key:" + "33" * 32).encode(), db=kv_ops._dbs()["devbind"]))
    check("a leased row is the historical two-element msgpack", raw == kv_ops._pack([a, 7]))
    check("a legacy row decodes as mode lease", kv_ops.devbind_get("android-key:" + "33" * 32) == (a, 7, "lease"))
    # --- permanent bind: row + devkey; journal; revert byte-identical
    apply_register(a, 10, lg, device_key=lkey, permanent=True)
    check("a permanent statement writes the perm row", kv_ops.devbind_get(lkey) == (a, 10, "perm"))
    check("... and stamps the sender's account with devkey", (kv_ops.get_account(a) or {}).get("devkey") == lkey)
    # statement-free renewal: nothing written to devbind, the row epoch (last STATEMENT) untouched
    apply_register(a, 100, lg)
    check("a statement-free renewal leaves the row untouched (epoch = last statement)", kv_ops.devbind_get(lkey) == (a, 10, "perm"))
    check("... records the recert like any renewal", kv_ops.recert_latest(a) == 100)
    apply_register(a, 100, lg, revert=True)
    check("reverting the statement-free renewal changes no binding", kv_ops.devbind_get(lkey) == (a, 10, "perm") and (kv_ops.get_account(a) or {}).get("devkey") == lkey)
    # --- the rule (semantics replicated exactly; the wiring is pinned by source below)
    def stmt_free_ok(sender):
        acc = kv_ops.get_account(sender) or {}
        dk = acc.get("devkey")
        bound = kv_ops.devbind_get(dk) if isinstance(dk, str) and dk else None
        return bool(bound and bound[0] == sender and bound[2] == "perm")
    def move_ok(sender, epoch_now):
        bound = kv_ops.devbind_get(lkey)
        return not (bound and bound[0] != sender and epoch_now < bound[1] + P.POSW_LEASE_EPOCHS)
    check("statement-free renewal: valid for the bound sender", stmt_free_ok(a))
    check("statement-free renewal: invalid for anyone else", not stmt_free_ok(b))
    check("rebind by another sender inside one lease of the last statement -> refused", not move_ok(b, 10 + P.POSW_LEASE_EPOCHS - 1))
    check("rebind after one lease since the last statement -> allowed (old owner's renewals do not extend it)", move_ok(b, 10 + P.POSW_LEASE_EPOCHS))
    # --- rebind: b takes the device at epoch 400; a loses statement-free renewal; revert restores everything
    apply_register(b, 400, lg, device_key=lkey, permanent=True)
    check("rebind flips the row to the new sender", kv_ops.devbind_get(lkey) == (b, 400, "perm"))
    check("the new sender carries devkey", (kv_ops.get_account(b) or {}).get("devkey") == lkey)
    check("the old sender can no longer renew without a statement", not stmt_free_ok(a) and stmt_free_ok(b))
    check("the old account is otherwise untouched (its lease runs out on its own)", (kv_ops.get_account(a) or {}).get("devkey") == lkey and (kv_ops.get_account(a) or {}).get("registered") == 1)
    apply_register(b, 400, lg, revert=True)
    check("reverting the rebind restores the previous row", kv_ops.devbind_get(lkey) == (a, 10, "perm"))
    check("... and removes the new sender's devkey (it had none)", "devkey" not in (kv_ops.get_account(b) or {}))
    check("... and the old sender renews statement-free again", stmt_free_ok(a))
    apply_register(a, 10, lg, revert=True)
    check("reverting the first permanent bind removes row and devkey", kv_ops.devbind_get(lkey) is None and "devkey" not in (kv_ops.get_account(a) or {}))
    # --- one hardware wallet per identity: a second permanent device for a live-permanent identity is refused
    lkey2 = "trezor:" + "44" * 32
    apply_register(a, 500, lg, device_key=lkey, permanent=True)
    def second_perm_ok(sender, dkey):
        acc = kv_ops.get_account(sender) or {}
        dk_prev = acc.get("devkey")
        if isinstance(dk_prev, str) and dk_prev and dk_prev != dkey:
            pb = kv_ops.devbind_get(dk_prev)
            return not (pb and pb[0] == sender and pb[2] == "perm")
        return True
    check("a second hardware wallet for a live-permanent identity -> refused", not second_perm_ok(a, lkey2))
    check("the same hardware wallet again -> fine (statement renewal refreshes the row)", second_perm_ok(a, lkey))
    apply_register(b, 900, lg, device_key=lkey, permanent=True)        # the device moved away after a lease
    check("once the device moved away the old identity may bind a new hardware wallet", second_perm_ok(a, lkey2))
    # --- in-block uniqueness: a statement-free register occupies no device key
    tx_nf = {"recipient": "register", "sender": a, "max_block": max(P.DEVICE_BIND_STRICT_HEIGHT, P.DEVICE_BIND_PERMANENT_HEIGHT)}
    check("a statement-free register occupies only its per-sender key", TO.reserved_uniqueness_keys(tx_nf) == [("register", a)], TO.reserved_uniqueness_keys(tx_nf))
    kv_ops.close_all()
    # --- wiring pins
    src = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
    seg = src[src.index('elif recipient == "register":'):src.index('elif recipient == "msgkey":')]
    check("validation: the statement-free branch is gated on DEVICE_BIND_PERMANENT_HEIGHT and checks devkey -> perm row -> sender",
          "stmt_free = bool(DEVICE_BIND_PERMANENT_HEIGHT and block_height >= DEVICE_BIND_PERMANENT_HEIGHT" in seg
          and 'bound[0] == transaction["sender"] and bound[2] == "perm"' in seg and "verify_register_device(transaction, anchor)" in seg)
    check("validation: one hardware wallet per identity is enforced from the gate", "already bound for life to another hardware wallet" in seg)
    check("validation: the txid check still runs after the register branch (no early return)", "            return\n" not in seg)
    acc = open(os.path.join(ROOT, "ops", "account_ops.py")).read()
    check("apply: permanent is derived from the class at the block height and passed to apply_register",
          "device_key.split(\":\", 1)[0] in DEVICE_BIND_PERMANENT_CLASSES" in acc and "permanent=permanent" in acc)
    check("apply: a statement-free register past the gate derives no key", "if has_device or block_height < DEVICE_BIND_PERMANENT_HEIGHT:" in acc)
    na = open(os.path.join(ROOT, "ops", "node_attest.py")).read()
    check("node: a hardware-bound node renews on its own without a statement", "def renew_without_statement" in na and 'st.get("bind_mode") == "perm" and st.get("bind_live")' in na)
    nd = open(os.path.join(ROOT, "nado.py")).read()
    check("relay: /devbind_lookup answers what a device vouches for; /get_account carries devbind", '"/devbind_lookup"' in nd and 'data["devbind"]' in nd)
    js = open(os.path.join(ROOT, "static", "interface.js")).read()
    check("wallet: a live-permanent identity renews with no statement and no prompt", "if (await bindIsPermanent())" in js and "buildRegisterTx(state.wallet, targetBlock, null, nowSeconds(), null)" in js)
    check("wallet: the Register gate is skipped for a live-permanent identity", "!state.pendingRegisterTx && !permLive" in js)
    check("wallet: the rebind confirmation asks the relay before the tap is spent", '"/devbind_lookup"' in js and 'i18("bind.rebindAsk"' in js and 'i18("bind.rebindWait"' in js)
    check("wallet: the binding mode is visible on the lease panel", 'i18("bind.perm"' in js and 'i18("bind.lease"' in js and 'id="bindModeLine"' in open(os.path.join(ROOT, "static", "interface.html")).read())
    i18n = open(os.path.join(ROOT, "static", "i18n.js")).read()
    for k in ("bind.perm", "bind.lease", "bind.rebindAsk", "bind.rebindWait", "hw.modes", "node.status.perm", "bind.renewNoTap"):
        n = i18n.count('"' + k + '":')
        check(f"i18n: {k} in every language", n >= 16 and n % 16 == 0, n)


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
    for name in ("t_binding_key", "t_apply_revert_symmetry", "t_rule", "t_strict_binding", "t_binding_modes", "t_hygiene"):
        try:
            globals()[name]()
        except Exception:
            import traceback; traceback.print_exc(); _fails.append(name)
    print("ALL PASS" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    raise SystemExit(1 if _fails else 0)
