"""ops/tpm_linux — a node attesting itself, in-process, with no shipped binary.

After the consensus rule goes live every node with a TPM should enrol and register ITSELF, on startup and
before its lease lapses: no tap, no drop store, no operator. That means the TPM client has to live in the node
rather than in the Windows companion binary, and this pins the parts that would otherwise fail silently on a
stranger's hardware.

The end-to-end half needs a TPM. It runs against swtpm when one is listening and skips otherwise:
    swtpm socket --tpm2 --server type=tcp,port=2321,bindaddr=127.0.0.1 \
                 --ctrl type=tcp,port=2322,bindaddr=127.0.0.1 --tpmstate dir=<d> \
                 --flags not-need-init,startup-clear --daemon
Run: python3 tests/test_tpm_linux.py
"""
import hashlib
import os
import socket
import struct
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="nado-tpml-"))
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def main():
    from ops import tpm_linux as T

    # THE TEMPLATES ARE DERIVATION INPUT, NOT CONFIGURATION. A primary key is derived from its template, so a
    # single byte different yields a DIFFERENT key — and the vendor's endorsement certificate then belongs to
    # a key the machine does not hold, which presents as "your chip is not the chip AMD certified". These
    # digests are pinned identically in the Rust client (apps/nado-tpm-attest), so the two cannot drift apart
    # without one of them failing.
    check("EK template is the TCG L-1 profile, byte for byte",
          hashlib.sha256(T.ek_template()).hexdigest()
          == "32503929a1287eedaa3e89d932f9b51a6f92abd0fa57721ffa6fc041e04f7498")
    check("EK template length", len(T.ek_template()) == 314, len(T.ek_template()))
    check("AIK template unchanged",
          hashlib.sha256(T.aik_template()).hexdigest()
          == "6cb5284d3e55fbf1ba82e683294e1c319320bc7e6897a60b90f1497d09d55033")

    ek = T.ek_template()
    check("EK is adminWithPolicy+restricted+decrypt, never signing",
          struct.unpack(">I", ek[4:8])[0] == 0x000300B2)
    aik = T.aik_template()
    attrs = struct.unpack(">I", aik[4:8])[0]
    check("AIK is restricted and signing", attrs & 0x00010000 and attrs & 0x00040000)
    check("AIK cannot decrypt", not attrs & 0x00020000)
    check("AIK declares RSASSA/SHA-256, so the statement is COSE -257",
          struct.unpack(">HH", aik[12:16]) == (T.ALG_RSASSA, T.ALG_SHA256))

    check("a node knows whether it has a TPM without raising", isinstance(T.LinuxTpm.present(), bool))

    # --- end to end, if a simulator is listening ---------------------------------------------------------
    try:
        s = socket.create_connection(("127.0.0.1", 2321), timeout=2)
    except OSError:
        print("\nSKIP  end-to-end: no swtpm on 127.0.0.1:2321")
        print("\n" + ("ALL OK" if not _fails else f"{len(_fails)} FAILURES"))
        return 1 if _fails else 0

    from ops.tpm_aik import make_credential, aik_name, credential_commitment, verify_credential_reveal

    class Sim(T.LinuxTpm):
        """swtpm's platform protocol instead of the character device — same command bytes either way, which
        is the whole reason the transport is separable."""

        def __init__(self, sock):
            self.s, self._lock, self.path = sock, threading.Lock(), "swtpm"

        def transmit(self, cmd):
            with self._lock:
                self.s.sendall(struct.pack(">I", 8) + b"\x00" + struct.pack(">I", len(cmd)) + cmd)
                n = struct.unpack(">I", self._recv(4))[0]
                r = self._recv(n)
                self._recv(4)
                return r

        def _recv(self, n):
            b = b""
            while len(b) < n:
                b += self.s.recv(n - len(b))
            return b

        def close(self):
            self.s.close()

    def ek_spki(pa):
        """The EK's TPMT_PUBLIC re-encoded as a SubjectPublicKeyInfo — the form ops/tpm_aik takes, and what the
        kernel returns from a real endorsement certificate. Hand-rolled because the code under test has no
        certificate library: the node's runtime has none, which is the whole reason for that interface."""
        be16 = lambda o: int.from_bytes(pa[o:o + 2], "big")
        o = 10 + be16(8)
        sym = be16(o); o += 2
        if sym != 0x0010:
            o += 4
        sch = be16(o); o += 2
        if sch != 0x0010:
            o += 2
        o += 2
        e = int.from_bytes(pa[o:o + 4], "big") or 65537
        o += 4
        modulus = pa[o + 2:o + 2 + be16(o)]

        def der(tag, body):
            if len(body) < 0x80:
                return bytes([tag, len(body)]) + body
            n = (len(body).bit_length() + 7) // 8
            return bytes([tag, 0x80 | n]) + len(body).to_bytes(n, "big") + body

        def integer(v):
            v = v.lstrip(b"\x00") or b"\x00"
            return der(0x02, (b"\x00" + v) if v[0] & 0x80 else v)

        rsa_pub = der(0x30, integer(modulus) + integer(e.to_bytes(4, "big")))
        alg = der(0x30, der(0x06, bytes.fromhex("2a864886f70d010101")) + der(0x05, b""))
        return der(0x30, alg + der(0x03, b"\x00" + rsa_pub))

    t = Sim(s)
    t.flush_all_transient()          # a crashed run leaves primaries loaded; TPMs have few object slots
    ek_h, ek_pub, _ = t.create_primary(T.RH_ENDORSEMENT, T.ek_template())
    aik_h, aik_pub, aik_nm = t.create_primary(T.RH_ENDORSEMENT, T.aik_template())
    check("a real TPM accepts our EK template", len(ek_pub) == 314, len(ek_pub))
    check("the AIK's Name is nameAlg || sha256(pubArea)", aik_nm == aik_name(aik_pub))

    secret, seed = os.urandom(32), os.urandom(32)
    blob, enc = make_credential(ek_spki(ek_pub), aik_nm, secret, seed=seed)

    # The EK is adminWithPolicy: a password authorization is refused however empty the hierarchy auth is.
    sess = t.start_policy_session()
    t.policy_secret_endorsement(sess)
    got = t.activate_credential(aik_h, ek_h, sess, blob, enc)
    check("the chip returns the sealed secret — EK and AIK share silicon", got == secret)

    check("any node can replay the challenge from public data, with no CA",
          verify_credential_reveal(ek_spki(ek_pub), aik_nm, secret, seed, blob,
                                   credential_commitment(got)))

    chal = hashlib.sha256(b"node self-attestation").digest()
    ci, sig = t.certify(aik_h, aik_h, chal)
    check("certInfo is a TPM_ST_ATTEST_CERTIFY", ci[:4] == b"\xff\x54\x43\x47"
          and int.from_bytes(ci[4:6], "big") == 0x8017)
    qs = int.from_bytes(ci[6:8], "big")
    o = 8 + qs
    n = int.from_bytes(ci[o:o + 2], "big")
    check("extraData carries the challenge WE chose", ci[o + 2:o + 2 + n] == chal)
    check("the signature is a full RSA-2048 signature", len(sig) == 256)

    for h in (sess, aik_h, ek_h):
        t.flush(h)
    check("transient handles are released", t.transient_handles() == [])
    t.close()

    print("\n" + ("ALL OK" if not _fails else f"{len(_fails)} FAILURES"))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
