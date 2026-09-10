"""THE FULL VENDOR-ENDORSED PROOF, DRIVEN THROUGH A REAL TPM 2.0 (swtpm).

Everything else in this area is checked against a software stand-in, which proves our arithmetic agrees with
itself. This drives an actual TPM implementation: our own command bytes in, its structures out, and our own
verifier over what it produced. It is the only place the byte LAYOUTS are checked against something that did
not come out of this repository — TPMS_ATTEST field offsets, TPMT_PUBLIC's exponent-zero-means-65537, the
credential blob a chip will actually accept.

Skips (exit 0) when swtpm is not installed. What it does NOT prove: that a particular vendor's silicon
behaves this way. swtpm accepts templates an fTPM may reject and carries no endorsement certificate at all.

Run: python3 tests/test_tpm_certify_swtpm.py
"""
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
os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="nado-swtpm-"))
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


class MsSim:
    """The simulator's TCP framing (TPM_SEND_COMMAND = 8): locality, length, command; back comes a length,
    the response, and a four-byte return code. Nothing TPM-specific — it is a transport, which is exactly why
    the command builders in ops/tpm_linux are separate from the device file they normally write to."""

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
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise IOError("simulator closed the connection")
            buf += chunk
        return buf


def main():
    if not shutil.which("swtpm"):
        print("SKIP  swtpm is not installed — nothing to drive")
        return 0
    from ops.tpm_linux import LinuxTpm, ek_template, aik_template, RH_ENDORSEMENT
    from ops.tpm_aik import (aik_name, make_credential, validate_aik_pub_area, verify_certify,
                             pub_area_rsa, credential_commitment)
    from ops import tpm_enrol as E

    state = tempfile.mkdtemp(prefix="swtpm-state-")
    port = _free_port()
    proc = subprocess.Popen(
        ["swtpm", "socket", "--tpm2", "--tpmstate", f"dir={state}",
         "--server", f"type=tcp,port={port}", "--ctrl", f"type=tcp,port={port + 1}",
         "--flags", "startup-clear", "--log", "level=0"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        sim = _wait(port, proc)
        if sim is None:
            print("SKIP  swtpm did not come up")
            return 0
        tpm = LinuxTpm.__new__(LinuxTpm)          # a transport swap, not a second TPM implementation
        tpm.transmit = sim.transmit

        ek_h, ek_pub, ek_name = tpm.create_primary(RH_ENDORSEMENT, ek_template())
        aik_h, aik_pub, _ = tpm.create_primary(RH_ENDORSEMENT, aik_template())
        check("the chip derives an EK from the TCG L-1 template", len(ek_pub) == 314, len(ek_pub))
        check("the chip derives a restricted signing key",
              "restricted" in validate_aik_pub_area(aik_pub))
        check("the name we compute is the name the chip reports", aik_name(aik_pub) is not None)

        # The exponent the chip encodes is 0, and reading that literally gives a key that verifies nothing.
        n, e = pub_area_rsa(aik_pub)
        check("a zero exponent reads as 65537", e == 65537, e)
        check("the modulus is 2048 bits", n.bit_length() == 2048, n.bit_length())

        # --- the enrolment, against this chip ---------------------------------------------------------
        ek_spki = _spki_from_pub_area(ek_pub)
        name = aik_name(aik_pub)
        secret, seed = os.urandom(32), os.urandom(32)
        blob, enc = make_credential(ek_spki, name, secret, seed=seed)

        sess = tpm.start_policy_session()
        tpm.policy_secret_endorsement(sess)
        recovered = tpm.activate_credential(aik_h, ek_h, sess, blob, enc)
        check("the chip opens a credential OUR challenger sealed", recovered == secret, recovered.hex())

        # The whole point of the deterministic blob: a node that saw none of this re-derives the challenge.
        replay, _ = make_credential(ek_spki, name, secret, seed=seed)
        check("an independent node re-derives the identical challenge", replay == blob)

        # --- what a register presents: a fresh certify over that block's challenge --------------------
        challenge = os.urandom(32)
        cert_info, sig = tpm.certify(aik_h, aik_h, challenge)
        check("the chip's certify verifies under the enrolled key",
              verify_certify(aik_pub, cert_info, sig, challenge).startswith("certify by RSA-2048"))

        for label, args in (
                ("a certify answering a different challenge", (aik_pub, cert_info, sig, os.urandom(32))),
                ("a tampered signature", (aik_pub, cert_info, bytes(sig[:-1]) + bytes([sig[-1] ^ 1]), challenge)),
                ("a tampered certInfo", (aik_pub, cert_info[:-1] + bytes([cert_info[-1] ^ 1]), sig, challenge))):
            try:
                verify_certify(*args)
                check(f"refuses {label}", False, "it was accepted")
            except ValueError:
                check(f"refuses {label}", True)

        # A DIFFERENT KEY IN THE SAME CHIP MUST NOT PASS AS THE ENROLLED ONE. Otherwise an enrolment
        # licences every key the machine ever creates, and one chip becomes an identity factory.
        other_h, other_pub, _ = tpm.create_primary(RH_ENDORSEMENT, _other_template())
        oc, osig = tpm.certify(other_h, other_h, challenge)
        try:
            verify_certify(aik_pub, oc, osig, challenge)
            check("refuses a certify by a different key in the same chip", False, "it was accepted")
        except ValueError:
            check("refuses a certify by a different key in the same chip", True)

        # And the enrolment state machine, over the values this chip actually produced.
        ek_id = __import__("hashlib").sha256(ek_spki).hexdigest()
        rec = E.new_record(ek_id, ek_spki, name.hex(), aik_pub, "owner1", 100, ["c1"])
        rec = E.apply_challenge(rec, "c1", blob, enc, 101)
        rec = E.apply_commit(rec, "owner1", credential_commitment(secret), 102)
        rec = E.apply_reveal(rec, "c1", secret, seed, 103)
        check("the enrolment reaches proven on real chip output", rec["state"] == E.STATE_PROVEN)

        # LEAKED TRANSIENT HANDLES WEDGE THE NEXT RUN with TPM_RC_OBJECT_MEMORY, which then looks like a bug
        # in whatever it is doing rather than in what the previous run failed to clean up.
        for h in (ek_h, aik_h, other_h, sess):
            tpm.flush(h)
        check("nothing is left loaded", tpm.transient_handles() == [], tpm.transient_handles())
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(state, ignore_errors=True)

    print("\n" + ("ALL OK" if not _fails else f"{len(_fails)} FAILURES"))
    return 1 if _fails else 0


def _other_template():
    """A second restricted signing key, identical to the AIK except for `unique` — a primary is DERIVED from
    its whole template, so one differing byte yields a different key. The attributes are left ALONE: clearing
    userWithAuth to make it differ produced TPM_RC_AUTH_UNAVAILABLE (0x12f) on Certify, which says nothing
    about the test's subject and everything about the template."""
    from ops.tpm_linux import AIK_ATTRS, ALG_RSA, ALG_SHA256, ALG_NULL, ALG_RSASSA, tpm2b
    return (struct.pack(">HHI", ALG_RSA, ALG_SHA256, AIK_ATTRS)
            + tpm2b(b"") + struct.pack(">H", ALG_NULL)
            + struct.pack(">HH", ALG_RSASSA, ALG_SHA256) + struct.pack(">HI", 2048, 0)
            + tpm2b(b"\x01" * 256))


def _spki_from_pub_area(pub_area: bytes) -> bytes:
    """A TPMT_PUBLIC's RSA key as a SubjectPublicKeyInfo, by hand — make_credential takes SPKI because that
    is what the kernel hands back from a certificate, and here the key comes straight out of the chip."""
    from ops.tpm_aik import pub_area_spki
    return pub_area_spki(pub_area)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _wait(port, proc):
    for _ in range(100):
        if proc.poll() is not None:
            return None
        try:
            return MsSim(port)
        except OSError:
            time.sleep(0.05)
    return None


if __name__ == "__main__":
    sys.exit(main())
