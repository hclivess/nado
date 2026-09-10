"""THE WHOLE VENDOR-ENDORSED PATH, END TO END, THROUGH A REAL TPM AND THE REAL CONSENSUS RULE.

Every other test in this area checks one piece. This one runs the piece that matters to a user: a chip
enrols through the four on-chain messages, and then a `register` transaction carrying a fresh certify is
accepted by the same function the node runs in a block — and the identity it binds is the ENDORSEMENT key,
so a second attestation key in the same chip cannot buy a second identity.

Requires swtpm (apt install swtpm); skips without it. Opens a THROWAWAY LMDB under a temp HOME: importing
node modules against the live database takes a write transaction against production.

Run: python3 tests/test_ek_register_e2e.py
"""
import hashlib
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-ekreg-")
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def refuses(name, fn):
    try:
        fn()
        check(f"refuses {name}", False, "it was accepted")
    except AssertionError:
        check(f"refuses {name}", True)


class MsSim:
    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=10)

    def transmit(self, cmd: bytes) -> bytes:
        self.sock.sendall(struct.pack(">IBI", 8, 0, len(cmd)) + cmd)
        n = struct.unpack(">I", self._recv(4))[0]
        rsp = self._recv(n)
        self._recv(4)
        return rsp

    def _recv(self, n):
        buf = b""
        while len(buf) < n:
            c = self.sock.recv(n - len(buf))
            if not c:
                raise IOError("simulator closed")
            buf += c
        return buf


def main():
    if not shutil.which("swtpm"):
        print("SKIP  swtpm is not installed")
        return 0
    import protocol as P
    from ops import kv_ops, tpm_aik, tpm_enrol as E, transaction_ops as T
    from ops.device_attest import device_binding_key
    from ops.tpm_linux import LinuxTpm, ek_template, aik_template, RH_ENDORSEMENT

    state = tempfile.mkdtemp(prefix="swtpm-ekreg-")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    proc = subprocess.Popen(
        ["swtpm", "socket", "--tpm2", "--tpmstate", f"dir={state}",
         "--server", f"type=tcp,port={port}", "--ctrl", f"type=tcp,port={port + 1}",
         "--flags", "startup-clear", "--log", "level=0"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sim = None
    for _ in range(100):
        if proc.poll() is not None:
            break
        try:
            sim = MsSim(port); break
        except OSError:
            time.sleep(0.05)
    if sim is None:
        proc.terminate()
        print("SKIP  swtpm did not come up")
        return 0

    handles = []
    try:
        tpm = LinuxTpm.__new__(LinuxTpm)
        tpm.transmit = sim.transmit
        ek_h, ek_pub, _ = tpm.create_primary(RH_ENDORSEMENT, ek_template())
        aik_h, aik_pub, _ = tpm.create_primary(RH_ENDORSEMENT, aik_template())
        handles += [ek_h, aik_h]
        ek_spki = tpm_aik.pub_area_spki(ek_pub)
        ek_id = hashlib.sha256(ek_spki).hexdigest()
        name = tpm_aik.aik_name(aik_pub)

        # --- the four-message enrolment, with the chip actually opening every challenge ---------------
        challengers = [f"chal{i}" for i in range(P.DEVICE_ATTEST_EK_CHALLENGERS)]
        eid = E.enrol_id(P.CHAIN_ID, ek_id, name.hex())
        rec = E.new_record(ek_id, ek_spki, name.hex(), aik_pub, "opener", 100, challengers)
        secrets, seeds = {}, {}
        for i, c in enumerate(challengers):
            secrets[c], seeds[c] = os.urandom(32), os.urandom(32)
            blob, enc = tpm_aik.make_credential(ek_spki, name, secrets[c], seed=seeds[c])
            sess = tpm.start_policy_session()
            try:
                tpm.policy_secret_endorsement(sess)
                got = tpm.activate_credential(aik_h, ek_h, sess, blob, enc)
            finally:
                tpm.flush(sess)
            check(f"the chip opens challenge {i}", got == secrets[c])
            rec = E.apply_challenge(rec, c, blob, enc, 101 + i)
        joined = b"".join(secrets[c] for c in sorted(challengers))
        rec = E.apply_commit(rec, "opener", tpm_aik.credential_commitment(joined), 110)
        for i, c in enumerate(challengers):
            rec = E.apply_reveal(rec, c, secrets[c], seeds[c], 111 + i)
        check("the enrolment is proven", rec["state"] == E.STATE_PROVEN, rec["state"])
        kv_ops.tpm_enrol_set(eid, rec)
        check("the record round-trips through consensus storage",
              kv_ops.tpm_enrol_get(eid)["pub"] == aik_pub.hex())

        # --- the register ------------------------------------------------------------------------------
        P.DEVICE_ATTEST_EK_HEIGHT = P.DEVICE_ATTEST_EK_HEIGHT or 1
        sender = "a" * 46
        anchor = "b" * 64
        max_block = max(2000, P.DEVICE_ATTEST_EK_HEIGHT)
        challenge = T.register_device_challenge(sender, anchor, max_block)
        cert_info, sig = tpm.certify(aik_h, aik_h, challenge)

        def tx(**over):
            d = {"ek": ek_id, "id": eid, "certinfo": cert_info.hex(), "sig": sig.hex()}
            d.update(over.pop("device", {}))
            base = {"sender": sender, "max_block": max_block, "device": d}
            base.update(over)
            return base

        check("a WebAuthn statement is not read as this class", not T.is_ek_device({"att": "x", "id": "y"}))
        check("this class is recognised", T.is_ek_device(tx()["device"]))
        v = T.verify_register_device(tx(), anchor)
        check("the register is accepted by the consensus rule", v.get("ok") and v.get("fmt") == "ek", v)
        check("it binds the endorsement key, not the attestation key",
              device_binding_key(tx()["device"], 0) == "ek:" + ek_id)

        # --- and the ways it must not be accepted -------------------------------------------------------
        refuses("a certify for another sender's challenge",
                lambda: T.verify_register_device(tx(sender="c" * 46), anchor))
        refuses("a certify against another anchor",
                lambda: T.verify_register_device(tx(), "d" * 64))
        refuses("a certify replayed at another height",
                lambda: T.verify_register_device(tx(max_block=max_block + 1), anchor))
        refuses("a tampered signature", lambda: T.verify_register_device(
            tx(device={"sig": (sig[:-1] + bytes([sig[-1] ^ 1])).hex()}), anchor))
        refuses("an enrolment that does not exist",
                lambda: T.verify_register_device(tx(device={"id": "f" * 32}), anchor))
        refuses("a mismatched endorsement identity",
                lambda: T.verify_register_device(tx(device={"ek": "e" * 64}), anchor))

        # AN UNPROVEN ENROLMENT CONFERS NOTHING. This is the rule that makes the four messages matter: a
        # record that stopped at the commitment is exactly what a prover with no chip can produce alone.
        half = dict(rec); half["state"] = E.STATE_COMMITTED
        kv_ops.tpm_enrol_set(eid, half)
        refuses("an enrolment that never completed its challenges",
                lambda: T.verify_register_device(tx(), anchor))
        kv_ops.tpm_enrol_set(eid, rec)

        # ONE CHIP, ONE IDENTITY. A second attestation key in the same chip enrols independently and still
        # binds the same endorsement key, so it can never be a second identity.
        aik2_h, aik2_pub, _ = tpm.create_primary(RH_ENDORSEMENT, _second_aik())
        handles.append(aik2_h)
        name2 = tpm_aik.aik_name(aik2_pub)
        check("the second key really is a different key", name2 != name)
        eid2 = E.enrol_id(P.CHAIN_ID, ek_id, name2.hex())
        rec2 = E.new_record(ek_id, ek_spki, name2.hex(), aik2_pub, "opener", 200, challengers)
        s2, r2 = {}, {}
        for i, c in enumerate(challengers):
            s2[c], r2[c] = os.urandom(32), os.urandom(32)
            b2, _e2 = tpm_aik.make_credential(ek_spki, name2, s2[c], seed=r2[c])
            rec2 = E.apply_challenge(rec2, c, b2, _e2, 201 + i)
        rec2 = E.apply_commit(rec2, "opener", tpm_aik.credential_commitment(
            b"".join(s2[c] for c in sorted(challengers))), 210)
        for i, c in enumerate(challengers):
            rec2 = E.apply_reveal(rec2, c, s2[c], r2[c], 211 + i)
        kv_ops.tpm_enrol_set(eid2, rec2)
        ci2, sg2 = tpm.certify(aik2_h, aik2_h, challenge)
        d2 = {"ek": ek_id, "id": eid2, "certinfo": ci2.hex(), "sig": sg2.hex()}
        check("a second enrolment in the same chip verifies",
              T.verify_register_device({"sender": sender, "max_block": max_block, "device": d2}, anchor)["ok"])
        check("but it binds the SAME identity handle",
              device_binding_key(d2, 0) == device_binding_key(tx()["device"], 0))

        # A certify by the OTHER key must not pass under the first enrolment's public area.
        refuses("a certify by a different key in the same chip",
                lambda: T.verify_register_device(
                    tx(device={"certinfo": ci2.hex(), "sig": sg2.hex()}), anchor))
    finally:
        for h in handles:
            try:
                tpm.flush(h)
            except Exception:
                pass
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(state, ignore_errors=True)

    print("\n" + ("ALL OK" if not _fails else f"{len(_fails)} FAILURES"))
    return 1 if _fails else 0


def _second_aik():
    from ops.tpm_linux import AIK_ATTRS, ALG_RSA, ALG_SHA256, ALG_NULL, ALG_RSASSA, tpm2b
    return (struct.pack(">HHI", ALG_RSA, ALG_SHA256, AIK_ATTRS) + tpm2b(b"")
            + struct.pack(">H", ALG_NULL) + struct.pack(">HH", ALG_RSASSA, ALG_SHA256)
            + struct.pack(">HI", 2048, 0) + tpm2b(b"\x02" * 256))


if __name__ == "__main__":
    sys.exit(main())
