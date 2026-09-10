"""A NODE ATTESTS ITSELF (loops/core_loop.maybe_tpm_self_enrol), driven through a real TPM 2.0.

This is the path that makes a headless Linux machine able to mine at all. It has never existed: there is
no Windows Hello on a server and no attestation service to ask, and the WebAuthn ceremony the other
device classes use requires a human gesture per signature by design. So the node does the whole thing
itself, one step per block, with nothing persisted locally — both primaries are DERIVED from fixed
templates, so the same machine recomputes the same endorsement identity and the same attestation key
after any restart and can find its own enrolment from public data alone.

The test plays the drawn challengers and the chain, and checks that what the node produces at each step
is accepted by the SAME consensus functions a block would run it through.

Requires swtpm; skips without it.

Run: python3 tests/test_tpm_self_enrol.py
"""
import hashlib
import logging
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import types

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_selfenrol_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers", "private"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

logger = logging.getLogger("selfenrol")
# THE LOOP SWALLOWS EXCEPTIONS BY DESIGN (a failing duty must never stop block production), so a silent
# handler here turns a real bug into a test that just reports nothing happened. Errors are printed.
logging.basicConfig(level=logging.INFO, format="    [node] %(levelname)s %(message)s")
from genesis import create_indexers                                      # noqa: E402
create_indexers()

import protocol as P                                                     # noqa: E402
from ops import kv_ops, tpm_aik, tpm_enrol as E, transaction_ops as T    # noqa: E402
from ops.key_ops import generate_keys                                    # noqa: E402
import loops.core_loop as core_loop                                      # noqa: E402
from loops.core_loop import CoreClient as Core                           # noqa: E402

_fails = []
CC_NV_DEFINE_SPACE = 0x0000012A
CC_NV_WRITE = 0x00000137
NV_OWNERWRITE, NV_OWNERREAD, NV_NO_DA = 0x00000002, 0x00020000, 0x02000000
ANCHOR = "ab" * 32


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


class FakeMem:
    def __init__(self, kd, tip):
        self.keydict = kd
        self.address = kd["address"]
        self.latest_block = {"block_number": tip, "block_timestamp": int(time.time())}
        self.transaction_pool = []
        self.submitted = []

    def merge_transaction(self, tx, user_origin=False):
        self.submitted.append(tx)
        self.transaction_pool.append(tx)
        return {"result": True}


def main():
    if not shutil.which("swtpm"):
        print("SKIP  swtpm is not installed")
        return 0
    from ops.tpm_linux import LinuxTpm, ST_SESSIONS, RH_OWNER, tpm2b, NV_EK_CERT_RSA, ALG_SHA256

    state = tempfile.mkdtemp(prefix="swtpm-self-")
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
        # A simulator has no endorsement certificate, so give it one to read. The CHAIN verification is
        # stubbed below; ek.rs and the pinned-root test cover that half, and what is under test here is
        # the node's own state machine.
        boot = LinuxTpm.__new__(LinuxTpm)
        boot.transmit = sim.transmit
        fake_cert = b"\x30\x82" + os.urandom(600)
        nv_public = (struct.pack(">IHI", NV_EK_CERT_RSA, ALG_SHA256,
                                 NV_OWNERWRITE | NV_OWNERREAD | NV_NO_DA)
                     + tpm2b(b"") + struct.pack(">H", len(fake_cert)))
        boot._call(ST_SESSIONS, CC_NV_DEFINE_SPACE, struct.pack(">I", RH_OWNER), boot._pw_auth(),
                   tpm2b(b"") + tpm2b(nv_public), "NV_DefineSpace")
        for off in range(0, len(fake_cert), 512):
            boot._call(ST_SESSIONS, CC_NV_WRITE, struct.pack(">II", RH_OWNER, NV_EK_CERT_RSA),
                       boot._pw_auth(), tpm2b(fake_cert[off:off + 512]) + struct.pack(">H", off),
                       "NV_Write")

        from ops.tpm_linux import ek_template, RH_ENDORSEMENT
        ek_h, ek_pub, _ = boot.create_primary(RH_ENDORSEMENT, ek_template())
        ek_spki = tpm_aik.pub_area_spki(ek_pub)
        ek_id = hashlib.sha256(ek_spki).hexdigest()
        boot.flush(ek_h)

        P.DEVICE_ATTEST_EK_HEIGHT = P.DEVICE_ATTEST_EK_HEIGHT or 1
        pinned = sorted(P.DEVICE_ATTEST_EK_ROOTS)[0]
        # patched on the MODULE, because _tpm_identity imports it at call time
        from ops import attest_native as _an
        _an.verify_ek = lambda chain, now: {
            "ok": True, "identity": ek_id, "manufacturer": "TEST", "root_sha256": pinned}
        core_loop.get_block_hash_by_number = lambda n: ANCHOR

        kd = generate_keys()
        me = kd["address"]
        tip = max(2000, P.DEVICE_ATTEST_EK_HEIGHT + 100)
        mem = FakeMem(kd, tip)
        core = types.SimpleNamespace(memserver=mem, logger=logger, _tpm_identity_cache=None)
        core._tpm_open = lambda: _sim_tpm(sim)
        for m in ("maybe_tpm_self_enrol", "_tpm_identity", "_tpm_activate_all", "_tpm_certify",
                  "_tpm_tx_pending"):
            setattr(core, m, getattr(Core, m).__get__(core))

        # --- step 1: publish -----------------------------------------------------------------------
        core.maybe_tpm_self_enrol()
        check("a node with a certified chip publishes an enrolment",
              len(mem.submitted) == 1 and mem.submitted[0]["recipient"] == "tpm_enrol",
              [t["recipient"] for t in mem.submitted])
        enrol = mem.submitted[0]
        aik_pub = bytes.fromhex(enrol["data"]["pub"])
        check("the published public area is a restricted signing key",
              "restricted" in tpm_aik.validate_aik_pub_area(aik_pub))
        check("it publishes the certificate it read out of NV",
              bytes.fromhex(enrol["data"]["ek"][0]) == fake_cert)

        core.maybe_tpm_self_enrol()
        check("no duplicate while ours is in flight", len(mem.submitted) == 1, len(mem.submitted))
        mem.transaction_pool.clear()

        # --- the chain accepts it, and the challengers answer --------------------------------------
        name_hex = E.aik_name_hex(aik_pub)
        eid = E.enrol_id(P.CHAIN_ID, ek_id, name_hex)
        challengers = [f"chal{i}" for i in range(P.DEVICE_ATTEST_EK_CHALLENGERS)]
        rec = E.new_record(ek_id, ek_spki, name_hex, aik_pub, me, tip, challengers)
        secrets, seeds = {}, {}
        for i, c in enumerate(challengers):
            secrets[c], seeds[c] = os.urandom(32), os.urandom(32)
            blob, enc = tpm_aik.make_credential(ek_spki, bytes.fromhex(name_hex), secrets[c],
                                                seed=seeds[c])
            rec = E.apply_challenge(rec, c, blob, enc, tip + 1 + i)
        kv_ops.tpm_enrol_set(eid, rec)
        mem.latest_block = {"block_number": tip + 10, "block_timestamp": int(time.time())}

        # --- step 2: the chip opens every challenge -------------------------------------------------
        core.maybe_tpm_self_enrol()
        check("the node commits once every challenger has answered",
              len(mem.submitted) == 2 and mem.submitted[1]["recipient"] == "tpm_commit",
              [t["recipient"] for t in mem.submitted])
        commitment = mem.submitted[1]["data"]["commit"]
        expected = tpm_aik.credential_commitment(b"".join(secrets[c] for c in sorted(challengers)))
        check("the commitment is over ALL the secrets, in challenger order", commitment == expected)

        # THE COMMITMENT MUST SURVIVE CONSENSUS. This is the check that would have caught a locally
        # sensible but wrongly-ordered concatenation, which fails only at the very last reveal.
        rec = E.apply_commit(rec, me, commitment, tip + 10)
        for i, c in enumerate(challengers):
            rec = E.apply_reveal(rec, c, secrets[c], seeds[c], tip + 11 + i)
        check("consensus accepts it and the enrolment is proven", rec["state"] == E.STATE_PROVEN,
              rec["state"])
        kv_ops.tpm_enrol_set(eid, rec)
        mem.transaction_pool.clear()

        # --- step 3: register with a fresh certify ---------------------------------------------------
        mem.latest_block = {"block_number": tip + 20, "block_timestamp": int(time.time())}
        core.maybe_tpm_self_enrol()
        check("a proven node registers itself",
              len(mem.submitted) == 3 and mem.submitted[2]["recipient"] == "register",
              [t["recipient"] for t in mem.submitted])
        reg = mem.submitted[2]
        check("the register carries an endorsement proof, not a WebAuthn statement",
              T.is_ek_device(reg["device"]))
        verdict = T.verify_register_device(reg, ANCHOR)
        check("THE CONSENSUS RULE ACCEPTS THE NODE'S OWN REGISTRATION",
              verdict.get("ok") and verdict.get("ek") == ek_id, verdict)

        # --- and it does not re-register every block --------------------------------------------------
        core.maybe_tpm_self_enrol()
        check("no second register while ours is in flight", len(mem.submitted) == 3,
              [t["recipient"] for t in mem.submitted])

        # --- a machine whose chip no vendor certified must NOT enrol ----------------------------------
        _an.verify_ek = lambda chain, now: {"ok": False, "reason": "no path to a root"}
        mem2 = FakeMem(generate_keys(), tip)
        core2 = types.SimpleNamespace(memserver=mem2, logger=logger, _tpm_identity_cache=None)
        core2._tpm_open = lambda: _sim_tpm(sim)
        for m in ("maybe_tpm_self_enrol", "_tpm_identity", "_tpm_activate_all", "_tpm_certify",
                  "_tpm_tx_pending"):
            setattr(core2, m, getattr(Core, m).__get__(core2))
        core2.maybe_tpm_self_enrol()
        check("an uncertified chip publishes nothing", mem2.submitted == [], mem2.submitted)

        # --- nothing is left loaded in the chip ------------------------------------------------------
        check("the node leaks no transient handles", boot.transient_handles() == [],
              boot.transient_handles())
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(state, ignore_errors=True)

    print("\n" + ("ALL OK" if not _fails else f"{len(_fails)} FAILURES"))
    return 1 if _fails else 0


def _sim_tpm(sim):
    from ops.tpm_linux import LinuxTpm
    t = LinuxTpm.__new__(LinuxTpm)
    t.transmit = sim.transmit
    t.close = lambda: None
    return t


if __name__ == "__main__":
    sys.exit(main())
