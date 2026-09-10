"""READING THE ENDORSEMENT CERTIFICATE OUT OF THE CHIP (ops/tpm_linux.ek_certificate).

The vendor's signature over the endorsement key is what the entire vendor-endorsed path rests on, and on a
Linux box there is no service to fetch it from — the chip carries it, at the TCG-reserved NV indices. If
this read is wrong the node either cannot enrol at all or, worse, enrols on a truncated certificate whose
chain verification then fails with a message pointing somewhere else entirely.

Driven against a real TPM 2.0 (swtpm), which ships with those indices EMPTY — so the test defines and
populates one itself. Defining NV space is a test-only capability on purpose: the node reads, never writes.

Run: python3 tests/test_tpm_nv.py
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
os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="nado-nv-"))
_fails = []

CC_NV_DEFINE_SPACE = 0x0000012A
CC_NV_WRITE = 0x00000137
CC_NV_UNDEFINE_SPACE = 0x00000122
NV_OWNERWRITE, NV_OWNERREAD, NV_NO_DA = 0x00000002, 0x00020000, 0x02000000


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


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
    from ops.tpm_linux import (LinuxTpm, ST_SESSIONS, RH_OWNER, tpm2b,
                               NV_EK_CERT_RSA, NV_EK_CERT_ECC, ALG_SHA256)

    state = tempfile.mkdtemp(prefix="swtpm-nv-")
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

    try:
        tpm = LinuxTpm.__new__(LinuxTpm)
        tpm.transmit = sim.transmit

        def define(index, size):
            nv_public = (struct.pack(">IHI", index, ALG_SHA256, NV_OWNERWRITE | NV_OWNERREAD | NV_NO_DA)
                         + tpm2b(b"") + struct.pack(">H", size))
            tpm._call(ST_SESSIONS, CC_NV_DEFINE_SPACE, struct.pack(">I", RH_OWNER), tpm._pw_auth(),
                      tpm2b(b"") + tpm2b(nv_public), "NV_DefineSpace")

        def write(index, data):
            for off in range(0, len(data), 512):
                tpm._call(ST_SESSIONS, CC_NV_WRITE, struct.pack(">II", RH_OWNER, index), tpm._pw_auth(),
                          tpm2b(data[off:off + 512]) + struct.pack(">H", off), "NV_Write")

        check("an empty chip reports no endorsement certificate", tpm.ek_certificate() is None)
        check("an undefined index reads as absent, not as an error",
              tpm.nv_read_public(NV_EK_CERT_RSA) is None)

        # A CERTIFICATE THAT SPANS SEVERAL CHUNKS is the case that matters: real endorsement certificates
        # are 1-2 KiB and TPM_PT_NV_BUFFER_MAX is 512 on some parts, so a reader that issues one NV_Read
        # gets a truncated certificate and no error.
        cert = bytes(range(256)) * 6 + b"TAIL"          # 1540 bytes: four chunks, last one short
        define(NV_EK_CERT_RSA, len(cert))
        write(NV_EK_CERT_RSA, cert)

        pub = tpm.nv_read_public(NV_EK_CERT_RSA)
        check("the declared size is read correctly", pub and pub[1] == len(cert), pub)
        got = tpm.nv_read(NV_EK_CERT_RSA, len(cert))
        check("a multi-chunk read returns the whole certificate, in order", got == cert,
              f"{len(got)} bytes, tail {got[-4:]!r}")
        check("ek_certificate() finds it at the RSA index", tpm.ek_certificate() == cert)

        # And the ECC index is the fallback, not the preference.
        tpm._call(ST_SESSIONS, CC_NV_UNDEFINE_SPACE, struct.pack(">II", RH_OWNER, NV_EK_CERT_RSA),
                  tpm._pw_auth(), b"", "NV_UndefineSpace")
        ecc = b"ECC-CERT" * 40
        define(NV_EK_CERT_ECC, len(ecc))
        write(NV_EK_CERT_ECC, ecc)
        check("it falls back to the ECC index", tpm.ek_certificate() == ecc)

        define(NV_EK_CERT_RSA, len(cert))
        write(NV_EK_CERT_RSA, cert)
        check("with both present, RSA wins", tpm.ek_certificate() == cert)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(state, ignore_errors=True)

    print("\n" + ("ALL OK" if not _fails else f"{len(_fails)} FAILURES"))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
